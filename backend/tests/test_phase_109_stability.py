from datetime import datetime, timedelta
from dataclasses import replace

import pytest

from sustained_majority import ExperimentalSnapshotPoint, evaluate_extension_stability, evaluate_original_window_stability

NOW = datetime(2026, 10, 8, 12)


def point(minutes, **kwargs):
    base = ExperimentalSnapshotPoint(NOW + timedelta(minutes=minutes), ("a",), 10, 10,
                                     option_set_version="v1", quorum_met=True,
                                     meaningful=True, priority_used=False)
    return replace(base, **kwargs)


def stable(points):
    return evaluate_extension_stability("star", points, 0.5, NOW, timedelta(minutes=10))


def test_full_window_evidence_required():
    assert stable([point(-11), point(-5), point(0)])
    assert not stable([point(-9), point(0)])
    assert not stable([point(-11)])
    assert not stable([])


@pytest.mark.parametrize("change", [
    {"winners": ("b",)}, {"winners": ()}, {"option_set_version": "v2"},
    {"option_set_version": None}, {"quorum_met": False},
    {"meaningful": False}, {"priority_used": True},
])
def test_any_in_window_breach_prevents_stability(change):
    assert not stable([point(-11), point(-5, **change), point(0)])


def test_old_breach_expires_and_no_future_evidence():
    assert stable([point(-20, priority_used=True), point(-11), point(0)])
    assert not stable([point(-5), point(5)])


def test_original_window_applies_same_experimental_rules():
    def evaluate(points, now=NOW):
        return evaluate_original_window_stability("star", points, 0.5, NOW-timedelta(minutes=100),
                                                   NOW, now, 0.1)
    assert not evaluate([point(-11), point(0)]).destabilized
    assert evaluate([point(-5), point(0)]).destabilized
    assert evaluate([]).destabilized
    assert not evaluate([point(-50, priority_used=True)], NOW-timedelta(minutes=20)).destabilized


def test_snapshot_exact_counts_and_worker_atomic_finalization(db):
    import models
    from tests.conftest import make_user, make_org_membership
    from voting_methods import new_voting_rules
    from sustained_majority_service import capture_snapshot
    from sustained_majority_worker import _close_proposal_now, _snapshot_points_for
    user = make_user(db, "star-worker")
    org = models.Organization(name="Worker", slug="star-worker", settings={})
    db.add(org); db.flush()
    make_org_membership(db, org_id=org.id, user_id=user.id)
    proposal = models.Proposal(title="Worker", body="", org_id=org.id, author_id=user.id,
                               voting_method="star", status="voting", quorum_threshold=0.4,
                               voting_start=NOW-timedelta(days=1), voting_end=NOW)
    db.add(proposal); db.flush()
    proposal.voting_rules = new_voting_rules("star", proposal.id)
    opts = [models.ProposalOption(proposal_id=proposal.id, label=name) for name in ("A", "B")]
    db.add_all(opts); db.flush()
    db.add(models.Vote(proposal_id=proposal.id, user_id=user.id, cast_by_id=user.id,
                       is_direct=True, ballot={"scores": {opts[0].id: 5}}))
    db.flush()
    snapshot = capture_snapshot(db, proposal, simulated_time=NOW)
    assert snapshot.total_eligible == 0  # no overflow in legacy PG int32 columns
    assert snapshot.multi_option_winners["total_eligible"] == 1
    assert snapshot.multi_option_winners["method_result"]["winner"] == opts[0].id
    points = _snapshot_points_for(db, proposal)
    assert points[0].quorum_met and points[0].meaningful and not points[0].priority_used
    assert points[0].total_eligible == 1
    assert _close_proposal_now(db, proposal, trigger="voting_end_reached", update_voting_end=False) == "passed"
    stored = proposal.final_method_result
    assert stored["tally"]["method_result"]["winner"] == opts[0].id
    assert stored["tie_seed"] == proposal.voting_rules["tie_seed"]
    audit_count = db.query(models.AuditLog).filter(models.AuditLog.target_id == proposal.id).count()
    assert _close_proposal_now(db, proposal, trigger="voting_end_reached", update_voting_end=False) == "passed"
    assert proposal.final_method_result == stored
    assert db.query(models.AuditLog).filter(models.AuditLog.target_id == proposal.id).count() == audit_count
