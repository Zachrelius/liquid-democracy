"""Experimental proposal lifecycle and public aggregate boundary.

The caller owns the transaction. No seed appears outside a finalized result.
"""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone

from fastapi import HTTPException

import models
from voting_methods import (EXPERIMENTAL_VOTING_METHODS, new_voting_rules,
                            public_voting_rules, validate_voting_rules)


def is_experimental(proposal):
    return proposal.voting_method in EXPERIMENTAL_VOTING_METHODS


def initialize_rules(proposal, db=None):
    if proposal.voting_method == "budget_allocation":
        from voting_capabilities import resolve_budget_creation
        if proposal.org_id and db is None:
            raise ValueError("Budget creation requires a database session")
        org = db.get(models.Organization, proposal.sub_org_id or proposal.org_id) if proposal.org_id else None
        proposal.budget_config = resolve_budget_creation(proposal.budget_config, org)
    if is_experimental(proposal):
        if not proposal.org_id or proposal.num_winners != 1:
            raise ValueError("Experimental methods require a single-winner organization proposal")
        if proposal.is_election:
            from experimental_elections import validate_creation
            validate_creation(proposal, db)
        proposal.voting_rules = new_voting_rules(proposal.voting_method, proposal.id)
        proposal.final_method_result = None
    else:
        proposal.voting_rules = None
        proposal.final_method_result = None


def lock_proposal(db, proposal):
    """Serialize option/ballot mutations and closing using the proposal row.

    Refresh after acquiring the lock so concurrent close/state changes cannot
    be bypassed by a cached SQLAlchemy identity. SQLite serializes writes.
    """
    if is_experimental(proposal):
        db.query(models.Proposal).filter(models.Proposal.id == proposal.id).with_for_update().populate_existing().one()
        db.expire(proposal, ["options"])
    return proposal


def require_mutable(proposal):
    if is_experimental(proposal) and (proposal.final_method_result is not None
                                    or proposal.status in ("passed", "failed", "withdrawn", "unresolved")):
        raise HTTPException(status_code=400, detail="This proposal is finalized; its ballots and options cannot change")


def weighting_metadata(proposal, db):
    from org_config import get_weighted_voting_config
    org = db.get(models.Organization, proposal.org_id) if proposal.org_id else None
    if org is not None and org.parent_org_id:
        org = db.get(models.Organization, org.parent_org_id) or org
    cfg = get_weighted_voting_config(org)
    weighted = cfg["enabled"] and proposal.count_mode != "one_per_member"
    return {"weighted": weighted, "unit_label": cfg["unit_label"] if weighted else None}


def finalize_result(proposal, tally, db):
    if proposal.final_method_result is not None:
        return proposal.final_method_result["status"]
    validate_voting_rules(proposal.voting_rules, proposal.voting_method, proposal.id)
    quorum = tally.quorum_met(proposal.quorum_threshold)
    status = "passed" if quorum and tally.winners else "failed"
    election = None
    if proposal.is_election:
        from experimental_elections import freeze_election
        election = freeze_election(proposal, tally, db)
        status = "passed" if quorum and (tally.winners or election['policy'] == 'uncontested' or election['reason'] == 'no_candidates') else "failed"
    proposal.final_method_result = {
        "record_version": 1, "method": proposal.voting_method,
        "rules": public_voting_rules(proposal.voting_rules),
        "tie_seed": proposal.voting_rules["tie_seed"],
        "option_labels": {opt.id: opt.label for opt in proposal.options},
        "tally": asdict(tally), "quorum_met": quorum,
        "status": status, "count_mode": proposal.count_mode,
        "closed_at": datetime.now(timezone.utc).isoformat(),
        **weighting_metadata(proposal, db),
    }
    if election is not None:
        from experimental_elections import display_labels
        proposal.final_method_result = {**proposal.final_method_result,
            'election': election, 'option_display_labels': display_labels(proposal)}
    return status


def decimal_counts(value):
    if type(value) is int:
        return str(value)
    if isinstance(value, dict):
        # Majority grades are ordered identifiers, not potentially large counts.
        # Preserve their numeric type in both the result and tie-removal trace.
        return {k: deepcopy(v) if k == "majority_grades" else decimal_counts(v)
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [decimal_counts(v) for v in value]
    return value


def result_response(proposal, tally, db):
    require_results_visible(proposal, db)
    import schemas
    record = proposal.final_method_result
    from experimental_elections import display_labels
    labels = (record.get('option_display_labels', record["option_labels"]) if record is not None else display_labels(proposal))
    quorum = record["quorum_met"] if record is not None else tally.quorum_met(proposal.quorum_threshold)
    aggregates = deepcopy(tally.method_result)
    for name in ("total_eligible", "total_ballots_cast", "total_abstain", "not_cast",
                 "participating_headcount", "eligible_headcount"):
        aggregates[name] = getattr(tally, name)
    aggregates.update(option_labels=labels, quorum_met=quorum, finalized=record is not None)
    if record is not None and proposal.is_election:
        aggregates["election"] = deepcopy(record["election"])
    aggregates = decimal_counts(aggregates)
    if record is not None:
        aggregates.update(tie_seed=record["tie_seed"], rules=record["rules"],
                          closed_at=record["closed_at"], count_mode=record["count_mode"])
    metadata = ({key: record[key] for key in ("weighted", "unit_label")}
                if record is not None else weighting_metadata(proposal, db))
    return schemas.ProposalResults(
        proposal_id=proposal.id, voting_method=proposal.voting_method,
        method_result=aggregates, option_labels=labels,
        quorum_met=quorum, winners=tally.winners, tied=tally.method_result["priority_used"],
        total_eligible=str(tally.total_eligible), votes_cast=str(tally.total_ballots_cast),
        total_ballots_cast=str(tally.total_ballots_cast), total_abstain=str(tally.total_abstain),
        not_cast=str(tally.not_cast), **metadata,
    )


def require_results_visible(proposal, db):
    if is_experimental(proposal) and proposal.status in ("draft", "deliberation"):
        from proposal_engagement_config import resolve_show_votes_during_deliberation
        org = db.get(models.Organization, proposal.org_id) if proposal.org_id else None
        if proposal.status == "draft" or not resolve_show_votes_during_deliberation(proposal, org):
            raise HTTPException(status_code=404, detail="Results are not visible yet")
