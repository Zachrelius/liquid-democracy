"""Close exactly four newly created synthetic QA fixtures; never run a global tick.

Read a method-to-proposal-ID object from stdin. Production execution requires
an explicit flag and explicit PostgreSQL DATABASE_URL. Prints no credentials.
"""
import argparse
from copy import deepcopy
from datetime import timedelta
import json
import os
from pathlib import Path
import sys
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.phase109_release_qa_bootstrap import ACCOUNTS, SLUG

METHODS = ("star", "score", "ranked_pairs", "majority_judgment")
TITLE_PREFIX = "Release QA worker "


def require(condition, message):
    if not condition:
        raise ValueError(message)


def close_exact_fixtures(db, proposal_ids):
    import models
    import sustained_majority_worker as worker
    from experimental_voting import lock_proposal

    require(isinstance(proposal_ids, dict) and set(proposal_ids) == set(METHODS), "Exactly four method/ID pairs are required")
    require(all(isinstance(value, str) for value in proposal_ids.values()), "Proposal IDs must be strings")
    require(len(set(proposal_ids.values())) == 4, "Proposal IDs must be distinct")
    for value in proposal_ids.values():
        UUID(value)
    require(not db.new and not db.dirty and not db.deleted, "Use a clean dedicated database session")
    try:
        org = db.query(models.Organization).filter_by(slug=SLUG).one_or_none()
        require(org is not None, "The isolated bootstrap org is missing")
        require(org.discoverability == "hidden" and org.activity_visibility == "members_only"
                and org.join_policy == "invite" and not org.is_demo, "QA org privacy/safety boundary changed")
        accounts = db.query(models.User).filter(models.User.username.in_([row[0] for row in ACCOUNTS])).all()
        require(len(accounts) == 2 and all(not user.is_admin and user.email == user.username + "@demo.example"
                                          for user in accounts), "Synthetic account identity boundary changed")
        user_ids = {user.id for user in accounts}
        memberships = db.query(models.OrgMembership).filter_by(org_id=org.id).all()
        require({row.user_id for row in memberships} == user_ids and all(row.status == "active" for row in memberships),
                "Only the two synthetic accounts may belong to the QA org")
        require(not db.query(models.NotificationPreference.id).filter(
            models.NotificationPreference.user_id.in_(user_ids), models.NotificationPreference.enabled.is_(True)).first(),
            "All synthetic notification channels must remain opted out")
        proposals = {}
        now = worker._now_naive()
        # Validate and lock the entire batch before any deadline is changed.
        for method, pid in sorted(proposal_ids.items(), key=lambda pair: pair[1]):
            proposal = db.get(models.Proposal, pid)
            require(proposal is not None, "A supplied proposal is missing")
            lock_proposal(db, proposal)
            require(proposal.org_id == org.id and proposal.sub_org_id is None and proposal.author_id in user_ids,
                    "Proposal is outside the isolated parent-org/synthetic-author boundary")
            require(proposal.voting_method == method and not proposal.is_election and not proposal.is_issuance
                    and proposal.num_winners == 1, "Proposal is not the expected ordinary voting method")
            require(proposal.title.startswith(TITLE_PREFIX) and proposal.status == "voting"
                    and proposal.final_method_result is None, "Use fresh voting fixtures with the worker QA title prefix")
            require(proposal.voting_start is not None and proposal.voting_start < now - timedelta(microseconds=1),
                    "Worker fixture voting start must precede its shortened deadline")
            proposals[method] = proposal
        outcome = {}
        records = {}
        audit_counts = {}
        for method, proposal in proposals.items():
            baseline = db.query(models.AuditLog).filter_by(target_id=proposal.id, action="proposal.status_changed").count()
            proposal.voting_end = now - timedelta(microseconds=1)
            proposal.stable_result_required = False
            db.flush()
            action = worker.evaluate_proposal(db, proposal)
            require(action == "closed_on_time", "Scoped worker did not close the due fixture")
            require(proposal.status in ("passed", "failed") and proposal.final_method_result is not None,
                    "Worker did not freeze the result")
            require(proposal.final_method_result.get("notification_intent_staged") is True,
                    "Notification staging marker is missing")
            count = db.query(models.AuditLog).filter_by(target_id=proposal.id, action="proposal.status_changed").count()
            require(count == baseline + 1, "Expected exactly one new closure status audit")
            audit_counts[method] = count
            records[method] = deepcopy(proposal.final_method_result)
            outcome[method] = {"proposal_id": proposal.id, "status": proposal.status,
                               "action": action, "new_status_audits": count - baseline, "notification_intent_staged": True}
        db.commit()
        for method, proposal in proposals.items():
            require(worker.evaluate_proposal(db, proposal) is None, "Worker retry was not a no-op")
            require(proposal.final_method_result == records[method], "Worker retry changed the frozen result")
            require(db.query(models.AuditLog).filter_by(target_id=proposal.id, action="proposal.status_changed").count() == audit_counts[method],
                    "Worker retry duplicated its status audit")
            outcome[method]["retry_noop"] = True
        db.commit()
        return {"org_slug": SLUG, "worker_fixtures": outcome}
    except Exception:
        db.rollback()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-exact-production-worker-qa", action="store_true")
    args = parser.parse_args()
    if not args.confirm_exact_production_worker_qa:
        parser.error("Explicit confirmation is required; no writes performed")
    if not os.environ.get("DATABASE_URL", "").startswith(("postgresql://", "postgresql+psycopg2://", "postgres://")):
        parser.error("An explicit PostgreSQL DATABASE_URL is required")
    proposal_ids = json.loads(sys.stdin.read(4096))
    from database import SessionLocal
    with SessionLocal() as db:
        result = close_exact_fixtures(db, proposal_ids)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
