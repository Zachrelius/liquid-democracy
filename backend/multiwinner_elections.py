"""Versioned all-or-nothing office installation from a frozen winner set."""
from copy import deepcopy
from fastapi import HTTPException
import models


def freeze_election_set(proposal, tally, db):
    from elections import active_candidacies
    declared = {row.user_id for row in active_candidacies(db, proposal.id)}
    snapshot = {}
    identities = set()
    for option in proposal.options:
        if option.label not in declared or option.label in identities:
            raise ValueError("Candidate options do not map uniquely to authorized candidates")
        identities.add(option.label)
        snapshot[option.id] = {"user_id": option.label, "display_name": option.description or option.label}
    if identities != declared or len(tally.winners) > proposal.num_winners or any(oid not in snapshot for oid in tally.winners):
        raise ValueError("Election candidate snapshot or winner set is inconsistent")
    quorum = tally.quorum_met(proposal.quorum_threshold)
    reason = None
    policy = None
    selected = list(tally.winners)
    if not quorum:
        reason = "quorum_not_met"
        selected = []
    elif not snapshot:
        reason = "no_candidates"
    elif len(snapshot) <= proposal.num_winners:
        policy = "uncontested"
        selected = sorted(snapshot)
    elif not selected:
        reason = tally.method_result["no_result_reason"] or "no_meaningful_preference"
    return {"outcome_version": 2, "title_id": proposal.election_title_id,
        "candidate_snapshot": snapshot, "counting_winner_option_ids": list(tally.winners),
        "selected_option_ids": selected, "winner_user_ids": [snapshot[oid]["user_id"] for oid in selected],
        "requested_count": proposal.num_winners, "selected_count": len(selected),
        "unfilled_count": proposal.num_winners - len(selected),
        "unfilled_reason": ("uncontested_vacancies" if policy else tally.method_result.get("unfilled_reason")) if len(selected) < proposal.num_winners else None,
        "candidate_outcomes": [], "policy": policy, "installation": "pending", "reason": reason, "title_granted": False}


def install_frozen_set(db, proposal, *, actor_id=None, ip_address=None):
    from audit_utils import log_audit_event
    from experimental_elections import _active_member, _preflight_role
    from elections import _cap_winners_to_title_capacity, _refresh_slate_for_title, _apply_election_winner, title_is_electable
    record = deepcopy(proposal.final_method_result)
    if not record or record.get("record_version") != 2 or record.get("election", {}).get("outcome_version") != 2:
        raise ValueError("Multiwinner installation requires a versioned frozen election")
    outcome = record["election"]
    if outcome["installation"] != "pending":
        return record["status"]
    # Every close owns the proposal lock first, then organization, title, members.
    org = db.query(models.Organization).filter_by(id=proposal.org_id).with_for_update().populate_existing().one()
    title = db.query(models.OrgTitle).filter_by(id=proposal.election_title_id, org_id=org.id).with_for_update().populate_existing().one()
    db.query(models.OrgMembership).filter_by(org_id=org.id).order_by(models.OrgMembership.id).with_for_update().populate_existing().all()
    users = []
    candidate_outcomes = []
    if outcome["reason"]:
        outcome["installation"] = "not_installed"
    else:
        # Inspect the complete set before changing any seat or privilege.
        for uid in outcome["winner_user_ids"]:
            candidate = {"user_id": uid, "status": "eligible", "reason": None}
            user = db.query(models.User).filter_by(id=uid).with_for_update().populate_existing().one_or_none()
            try:
                if user is None or not user.is_active:
                    raise HTTPException(400, "winner_inactive")
                member = _active_member(db, proposal, uid)
                if _preflight_role(db, org, title, user, member):
                    candidate.update(status="pending_verification", reason="verification_required")
                users.append(user)
            except HTTPException as exc:
                if exc.status_code >= 500:
                    raise
                candidate.update(status="rejected", reason=str(exc.detail))
            candidate_outcomes.append(candidate)
        outcome["candidate_outcomes"] = candidate_outcomes
        try:
            if not title_is_electable(title):
                raise HTTPException(400, "title_no_longer_electable")
            if title.cardinality_mode == "single" or title.bound_role == "steward":
                raise HTTPException(400, "title_cannot_have_multiple_occupants")
            if proposal.election_slate_mode == "refresh_slate" and len(outcome["winner_user_ids"]) < proposal.num_winners:
                raise HTTPException(400, "partial_selection_cannot_refresh_slate")
            seated, overflow = _cap_winners_to_title_capacity(db, title, outcome["winner_user_ids"], slate_mode=proposal.election_slate_mode)
            if overflow or seated != outcome["winner_user_ids"]:
                raise HTTPException(400, "title_capacity_unavailable")
            if any(row["status"] == "rejected" for row in candidate_outcomes):
                outcome.update(installation="rejected", reason="winner_set_policy_rejected")
            elif any(row["status"] == "pending_verification" for row in candidate_outcomes):
                outcome.update(installation="pending_verification", reason="verification_required")
            else:
                with db.begin_nested():
                    if proposal.election_slate_mode == "refresh_slate":
                        _refresh_slate_for_title(db, org, title, outcome["winner_user_ids"], actor_id=actor_id, ip_address=ip_address)
                    from org_titles import is_holder
                    for user in users:
                        assigning_id = user.id
                        if title.is_system or not is_holder(db, title.id, user.id):
                            _apply_election_winner(db, org, title, user, actor_id=actor_id, ip_address=ip_address)
                        elif title.bound_role:
                            from routes.org_titles import _apply_bound_role_for_assign
                            from types import SimpleNamespace
                            _apply_bound_role_for_assign(db, org, user, title.bound_role, SimpleNamespace(client=SimpleNamespace(host=ip_address)))
                    db.flush()
                outcome.update(installation="installed", title_granted=True)
                for row in candidate_outcomes:
                    row["status"] = "installed"
        except HTTPException as exc:
            if exc.status_code >= 500:
                raise
            outcome.update(installation="rejected", reason=str(exc.detail), title_granted=False)
            for row in candidate_outcomes:
                if row["user_id"] == locals().get("assigning_id"):
                    row.update(status="rejected", reason=str(exc.detail))
    if not outcome["title_granted"]:
        for row in candidate_outcomes:
            if row["status"] == "eligible":
                row.update(status="not_installed", reason=outcome["reason"])
    log_audit_event(db, action="election.resolved", target_type="proposal", target_id=proposal.id,
        actor_id=actor_id, ip_address=ip_address,
        details={**outcome, "proposal_id": proposal.id, "method": proposal.voting_method})
    proposal.final_method_result = record
    db.flush()
    return record["status"]


def announcement_set(outcome):
    selected = set(outcome["winner_user_ids"])
    names = [row["display_name"] for row in outcome["candidate_snapshot"].values() if row["user_id"] in selected]
    people = ", ".join(names)
    if outcome["installation"] == "installed":
        prefix = "Uncontested election" if outcome["policy"] == "uncontested" else "Elected"
        return f"{prefix}: {people}. {len(names)} of {outcome['requested_count']} places filled; office installation completed."
    if outcome["installation"] == "pending_verification":
        return f"Selected: {people}. The entire set is pending verification; existing seats and roles were preserved."
    if outcome["installation"] == "rejected":
        return f"Selected: {people}. The entire set could not be installed; existing seats and roles were preserved ({outcome['reason']})."
    return f"No officeholders installed ({outcome['reason']}); existing seats and roles were preserved."
