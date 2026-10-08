from datetime import datetime, timedelta, timezone

import pytest

import models
from experimental_voting import initialize_rules
from scripts.phase109_release_qa_bootstrap import bootstrap
from scripts.phase109_release_worker_qa import close_exact_fixtures, METHODS, TITLE_PREFIX


def fixtures(db):
    info = bootstrap(db, "Synthetic-owner-password-109!", "Synthetic-member-password-109!")
    owner = info["accounts"][0]["id"]
    rows = {}
    for method in METHODS:
        proposal = models.Proposal(title=TITLE_PREFIX + method, body="Synthetic", org_id=info["org_id"],
            author_id=owner, voting_method=method, status="voting", num_winners=1, quorum_threshold=0,
            voting_start=datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(hours=1),
            voting_end=datetime.now(timezone.utc).replace(tzinfo=None)+timedelta(days=1))
        db.add(proposal); db.flush(); initialize_rules(proposal)
        options = [models.ProposalOption(proposal_id=proposal.id, label=label) for label in ("A", "B")]
        db.add_all(options); db.flush()
        field = "grades" if method == "majority_judgment" else "scores"
        ballot = {"rank_groups": [[options[0].id]]} if method == "ranked_pairs" else {field: {options[0].id: 5}}
        db.add(models.Vote(proposal_id=proposal.id, user_id=owner, cast_by_id=owner, is_direct=True, ballot=ballot))
        rows[method] = proposal
    db.commit()
    return info, rows


def test_exact_worker_batch_closes_all_methods_and_retry_is_noop(db):
    info, rows = fixtures(db)
    # Real API zero-day creation records a draft-to-voting transition first.
    from audit_utils import log_audit_event
    for row in rows.values():
        log_audit_event(db, action="proposal.status_changed", target_type="proposal", target_id=row.id,
            actor_id=row.author_id, details={"old_status": "draft", "new_status": "voting"})
    unrelated = models.Proposal(title="Unrelated keep open", body="", org_id=info["org_id"],
        author_id=info["accounts"][0]["id"], status="voting",
        voting_end=datetime.now(timezone.utc).replace(tzinfo=None)+timedelta(days=7))
    db.add(unrelated); db.commit()
    deadline = unrelated.voting_end
    result = close_exact_fixtures(db, {method: row.id for method, row in rows.items()})
    assert all(row["status"] == "passed" and row["retry_noop"] and row["new_status_audits"] == 1
               for row in result["worker_fixtures"].values())
    assert unrelated.status == "voting" and unrelated.voting_end == deadline
    assert db.query(models.Notification).count() == 0


@pytest.mark.parametrize("fault", ["wrong_org", "notifications", "wrong_method", "already_final", "wrong_title"])
def test_worker_scope_refusal_preserves_every_deadline(db, fault):
    info, rows = fixtures(db)
    victim = rows["majority_judgment"]
    if fault == "wrong_org":
        other = models.Organization(name="Unrelated", slug="worker-unrelated")
        db.add(other); db.flush(); victim.org_id = other.id
    elif fault == "notifications":
        pref = db.query(models.NotificationPreference).filter_by(user_id=info["accounts"][0]["id"]).first()
        pref.enabled = True
    elif fault == "wrong_method":
        victim.voting_method = "binary"
    elif fault == "already_final":
        victim.status = "passed"
    else:
        victim.title = "Real decision must remain untouched"
    db.commit()
    deadlines = {method: row.voting_end for method, row in rows.items()}
    with pytest.raises(ValueError):
        close_exact_fixtures(db, {method: row.id for method, row in rows.items()})
    assert {method: row.voting_end for method, row in rows.items()} == deadlines
    assert not any(row.final_method_result for row in rows.values())
    assert db.query(models.AuditLog).count() == 0
