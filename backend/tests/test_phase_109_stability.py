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


def stable(method, points):
    return evaluate_extension_stability(method, points, 0.5, NOW, timedelta(minutes=10))


@pytest.mark.parametrize("method", ["star", "score"])
def test_full_window_evidence_required(method):
    assert stable(method, [point(-11), point(-5), point(0)])
    assert not stable(method, [point(-9), point(0)])
    assert not stable(method, [point(-11)])
    assert not stable(method, [])


@pytest.mark.parametrize("change", [
    {"winners": ("b",)}, {"winners": ()}, {"option_set_version": "v2"},
    {"option_set_version": None}, {"quorum_met": False},
    {"meaningful": False}, {"priority_used": True},
])
@pytest.mark.parametrize("method", ["star", "score"])
def test_any_in_window_breach_prevents_stability(change, method):
    assert not stable(method, [point(-11), point(-5, **change), point(0)])


@pytest.mark.parametrize("method", ["star", "score"])
def test_old_breach_expires_and_no_future_evidence(method):
    assert stable(method, [point(-20, priority_used=True), point(-11), point(0)])
    assert not stable(method, [point(-5), point(5)])


@pytest.mark.parametrize("method", ["star", "score"])
def test_original_window_applies_same_experimental_rules(method):
    def evaluate(points, now=NOW):
        return evaluate_original_window_stability(method, points, 0.5, NOW-timedelta(minutes=100),
                                                   NOW, now, 0.1)
    assert not evaluate([point(-11), point(0)]).destabilized
    assert evaluate([point(-5), point(0)]).destabilized
    assert evaluate([]).destabilized
    assert not evaluate([point(-50, priority_used=True)], NOW-timedelta(minutes=20)).destabilized


@pytest.mark.parametrize("method", ["star", "score"])
def test_snapshot_exact_counts_and_worker_atomic_finalization(db, method):
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
                               voting_method=method, status="voting", quorum_threshold=0.4,
                               voting_start=NOW-timedelta(days=1), voting_end=NOW)
    db.add(proposal); db.flush()
    proposal.voting_rules = new_voting_rules(method, proposal.id)
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


@pytest.mark.parametrize("expression,expected_status,reason", [
    ({"scores": {}}, "failed", "all_bottom_ratings"),
    ({"abstain": True}, "failed", "no_positive_weight_preferences"),
    (None, "failed", "no_positive_weight_preferences"),
    ("tied", "passed", None),
    ("quorum", "failed", None),
])
@pytest.mark.parametrize("method", ["star", "score"])
def test_missing_snapshot_evidence_exhausts_bounded_extensions_then_closes(
        db, monkeypatch, expression, expected_status, reason, method):
    import models
    import sustained_majority_worker as worker
    from sustained_majority_service import count_extensions, _sum_extension_seconds
    from tests.conftest import make_user, make_org_membership
    from voting_methods import new_voting_rules
    user = make_user(db, "no-evidence-worker")
    org = models.Organization(name="No evidence", slug="no-evidence", settings={
        "stable_result_enabled_default": True, "stable_window_fraction": 0.25,
        "max_extension_fraction": 0.5,
    })
    db.add(org); db.flush()
    make_org_membership(db, org_id=org.id, user_id=user.id)
    if expression == "quorum":
        for i in range(2):
            absent = make_user(db, f"absent-quorum-{i}")
            make_org_membership(db, org_id=org.id, user_id=absent.id)
    proposal = models.Proposal(title="No evidence", body="", org_id=org.id,
                               author_id=user.id, voting_method=method, status="voting",
                               voting_start=NOW-timedelta(hours=4), voting_end=NOW,
                               quorum_threshold=0.4)
    db.add(proposal); db.flush()
    proposal.voting_rules = new_voting_rules(method, proposal.id)
    options = [models.ProposalOption(proposal_id=proposal.id, label=name) for name in ("A", "B")]
    db.add_all(options); db.flush()
    if expression is not None:
        ballot = ({"scores": {opt.id: 5 for opt in options}} if expression == "tied" else
                  {"scores": {options[0].id: 5}} if expression == "quorum" else expression)
        db.add(models.Vote(proposal_id=proposal.id, user_id=user.id, cast_by_id=user.id,
                           is_direct=True, ballot=ballot))
    db.commit()
    # Simulate unavailable history without turning an actual counting error
    # into success: failures from real capture still propagate and roll back.
    monkeypatch.setattr(worker, "capture_snapshot", lambda *args: None)
    notification_calls = []
    monkeypatch.setattr(worker, "_emit_extended_by_stability", lambda *args, **kwargs: None)
    monkeypatch.setattr(worker, "_stage_experimental_closed", lambda *args, **kwargs: notification_calls.append(kwargs))
    for offset in (0, 1):
        monkeypatch.setattr(worker, "_now_naive", lambda offset=offset: NOW+timedelta(hours=offset))
        assert worker.evaluate_proposal(db, proposal) == "extended"
        db.commit()
        assert proposal.voting_end == NOW+timedelta(hours=offset+1)
        assert proposal.status == "voting"
    monkeypatch.setattr(worker, "_now_naive", lambda: NOW+timedelta(hours=2))
    assert worker.evaluate_proposal(db, proposal) == "closed_on_time_after_srr_exhausted"
    db.commit()
    assert proposal.status == expected_status
    assert count_extensions(db, proposal.id) == 2
    assert _sum_extension_seconds(db, proposal.id) == 7200
    final = proposal.final_method_result
    assert final["tally"]["method_result"]["no_result_reason"] == reason
    assert final["tally"]["method_result"]["priority_used"] is (expression == "tied")
    assert len(notification_calls) == 1
    audits = db.query(models.AuditLog).filter_by(target_id=proposal.id).count()
    assert worker.evaluate_proposal(db, proposal) is None
    db.commit()
    assert len(notification_calls) == 1
    assert proposal.final_method_result == final
    assert db.query(models.AuditLog).filter_by(target_id=proposal.id).count() == audits


@pytest.mark.parametrize("method", ["star", "score"])
def test_capture_software_failure_propagates_without_fabricated_final_result(db, monkeypatch, method):
    import models
    import sustained_majority_worker as worker
    from tests.conftest import make_user
    from voting_methods import new_voting_rules
    user = make_user(db, "failed-capture-worker")
    org = models.Organization(name="Failure", slug="failed-capture", settings={"stable_result_enabled_default": True})
    db.add(org); db.flush()
    proposal = models.Proposal(title="Failure", body="", org_id=org.id, author_id=user.id,
                               voting_method=method, status="voting", voting_start=NOW-timedelta(hours=1), voting_end=NOW)
    db.add(proposal); db.flush()
    proposal.voting_rules = new_voting_rules(method, proposal.id)
    db.commit()
    def fail(*args):
        raise ValueError("Invalid stored ballot")
    monkeypatch.setattr(worker, "capture_snapshot", fail)
    with pytest.raises(ValueError, match="Invalid stored ballot"):
        worker.evaluate_proposal(db, proposal)
    db.rollback()
    assert proposal.status == "voting" and proposal.final_method_result is None


@pytest.mark.parametrize("method", ["star", "score"])
def test_worker_notification_failure_rolls_back_close_then_retry_once(db, monkeypatch, method):
    import models
    import sustained_majority_worker as worker
    from tests.conftest import make_user, make_org_membership
    from voting_methods import new_voting_rules
    user = make_user(db, "atomic-close-notice")
    org = models.Organization(name="Atomic close", slug="atomic-close", settings={})
    db.add(org); db.flush()
    make_org_membership(db, org_id=org.id, user_id=user.id)
    proposal = models.Proposal(title="Atomic close", body="", org_id=org.id, author_id=user.id,
                               voting_method=method, status="voting", stable_result_required=False,
                               voting_start=NOW-timedelta(hours=1), voting_end=NOW)
    db.add(proposal); db.flush()
    proposal.voting_rules = new_voting_rules(method, proposal.id)
    options = [models.ProposalOption(proposal_id=proposal.id, label=name) for name in ("A", "B")]
    db.add_all(options); db.flush()
    db.add(models.Vote(proposal_id=proposal.id, user_id=user.id, cast_by_id=user.id,
                       is_direct=True, ballot={"scores": {options[0].id: 5}}))
    db.add(models.NotificationPreference(user_id=user.id, event_type="proposal.closed",
                                         channel="in_app", enabled=True))
    # Historical voters who have lost visibility or account access must not
    # receive the private proposal title through the close notification.
    for name, inactive in (("removed-voter", False), ("inactive-voter", True)):
        former = make_user(db, name)
        former.is_active = not inactive
        if inactive:
            make_org_membership(db, org_id=org.id, user_id=former.id)
        db.add(models.Vote(proposal_id=proposal.id, user_id=former.id, cast_by_id=former.id,
                           is_direct=True, ballot={"scores": {options[0].id: 5}}))
        db.add(models.NotificationPreference(user_id=former.id, event_type="proposal.closed",
                                             channel="in_app", enabled=True))
    db.commit()
    monkeypatch.setattr(worker, "_now_naive", lambda: NOW)
    real_emit = worker.emit_notification
    def fail_after_row(*args, **kwargs):
        real_emit(*args, **kwargs)
        raise RuntimeError("Injected durable notification failure")
    monkeypatch.setattr(worker, "emit_notification", fail_after_row)
    with pytest.raises(RuntimeError, match="Injected durable"):
        worker.evaluate_proposal(db, proposal)
    db.rollback()
    assert proposal.status == "voting" and proposal.final_method_result is None
    assert db.query(models.Notification).filter_by(target_id=proposal.id).count() == 0
    assert db.query(models.AuditLog).filter_by(target_id=proposal.id).count() == 0
    monkeypatch.setattr(worker, "emit_notification", real_emit)
    assert worker.evaluate_proposal(db, proposal) == "closed_on_time"
    db.commit()
    assert proposal.status == "passed" and proposal.final_method_result is not None
    assert proposal.final_method_result["notification_intent_staged"] is True
    assert db.query(models.Notification).filter_by(target_id=proposal.id, event_type="proposal.closed").count() == 1
    assert db.query(models.AuditLog).filter_by(target_id=proposal.id, action="proposal.status_changed").count() == 1
    assert worker.evaluate_proposal(db, proposal) is None
    db.commit()
    assert db.query(models.Notification).filter_by(target_id=proposal.id, event_type="proposal.closed").count() == 1
    assert db.query(models.AuditLog).filter_by(target_id=proposal.id, action="proposal.status_changed").count() == 1
