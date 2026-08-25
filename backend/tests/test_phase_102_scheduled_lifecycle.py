"""Phase 102 — durable schedules, worker, bulk schemas, and monitor."""
from __future__ import annotations

from datetime import datetime, timedelta
import uuid

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import auth as auth_utils
import models
import schemas
from database import get_db
from main import app
from ops_monitoring import _proposal_lifecycle_component
from proposal_lifecycle import (
    transition_deliberation_to_voting,
    transition_draft_to_deliberation,
)
from settings import settings
from sustained_majority_worker import advance_due_deliberation_proposals
from sustained_majority_worker import close_due_budget_proposals
from role_seed import seed_default_roles_for_org
from tests.conftest import make_org_membership


def _user(db, name="phase102"):
    row = models.User(
        username=f"{name}-{uuid.uuid4().hex[:8]}", display_name=name,
        email=f"{uuid.uuid4().hex}@test.example", password_hash="x",
        email_verified=True,
    )
    db.add(row)
    db.flush()
    return row


def _org(db, **settings_value):
    row = models.Organization(
        name=f"Phase 102 {uuid.uuid4().hex[:6]}",
        slug=f"phase-102-{uuid.uuid4().hex[:8]}", description="",
        join_policy="open",
        settings={"default_deliberation_days": 4, "default_voting_days": 7, **settings_value},
    )
    db.add(row)
    db.flush()
    return row


def _proposal(db, org, user, *, status="draft", **values):
    defaults = dict(
        title="Scheduled proposal", body="Body", author_id=user.id,
        org_id=org.id, status=status, voting_method="binary",
        num_winners=1, deliberation_days=2, voting_days=5,
        is_cosign_gated=False,
    )
    defaults.update(values)
    row = models.Proposal(**defaults)
    db.add(row)
    db.flush()
    return row


def test_model_declares_nullable_indexed_deliberation_end():
    column = models.Proposal.__table__.c.deliberation_end
    assert column.nullable is True
    assert column.index is True


def test_draft_transition_captures_one_clock_and_stored_duration(db):
    org, user = _org(db), _user(db)
    proposal = _proposal(db, org, user, deliberation_days=2.5)
    now = datetime(2026, 9, 1, 13, 0)
    result = transition_draft_to_deliberation(
        db, proposal, org=org, actor_id=user.id, ip_address=None, now=now,
    )
    assert proposal.deliberation_start == now
    assert proposal.deliberation_end == now + timedelta(days=2.5)
    assert result.occurred_at == now


def test_draft_transition_uses_org_fallback_only_when_row_is_legacy_null(db):
    org, user = _org(db), _user(db)
    proposal = _proposal(db, org, user, deliberation_days=None)
    now = datetime(2026, 9, 1)
    transition_draft_to_deliberation(
        db, proposal, org=org, actor_id=None, ip_address=None, now=now,
    )
    assert proposal.deliberation_end == now + timedelta(days=4)


def test_voting_transition_preserves_planned_deliberation_boundary(db):
    org, user = _org(db), _user(db)
    planned = datetime(2026, 9, 1, 13, 0)
    actual = planned + timedelta(minutes=6)
    proposal = _proposal(
        db, org, user, status="deliberation",
        deliberation_start=planned - timedelta(days=2),
        deliberation_end=planned,
    )
    transition_deliberation_to_voting(
        db, proposal, org=org, actor_id=None, ip_address=None,
        trigger="test", now=actual,
    )
    assert proposal.deliberation_end == planned
    assert proposal.voting_start == actual
    assert proposal.voting_end == actual + timedelta(days=5)


def test_general_transition_rejects_cosign_gate(db):
    org, user = _org(db), _user(db)
    proposal = _proposal(
        db, org, user, status="deliberation", is_cosign_gated=True,
    )
    with pytest.raises(ValueError, match="cosign"):
        transition_deliberation_to_voting(
            db, proposal, org=org, actor_id=None, ip_address=None,
        )


def test_absolute_stale_voting_end_fails_without_mutating_status(db):
    org, user = _org(db), _user(db)
    now = datetime(2026, 9, 1)
    proposal = _proposal(
        db, org, user, status="deliberation",
        voting_end_date=now - timedelta(minutes=1),
    )
    with pytest.raises(HTTPException):
        transition_deliberation_to_voting(
            db, proposal, org=org, actor_id=None, ip_address=None, now=now,
        )
    assert proposal.status == "deliberation"


def test_due_worker_advances_at_equality_and_skips_future(db, monkeypatch):
    org, user = _org(db), _user(db)
    now = datetime.utcnow()
    due = _proposal(
        db, org, user, status="deliberation",
        deliberation_start=now - timedelta(days=2), deliberation_end=now,
    )
    future = _proposal(
        db, org, user, status="deliberation", title="Future",
        deliberation_start=now, deliberation_end=now + timedelta(hours=1),
    )
    monkeypatch.setattr("sustained_majority_worker._now_naive", lambda: now)
    result = advance_due_deliberation_proposals(db)
    db.expire_all()
    assert result == {"advanced": 1, "skipped": 0, "failed": 0}
    assert db.get(models.Proposal, due.id).status == "voting"
    assert db.get(models.Proposal, future.id).status == "deliberation"


def test_due_worker_ignores_null_and_cosign_schedules(db, monkeypatch):
    org, user = _org(db), _user(db)
    now = datetime.utcnow()
    _proposal(db, org, user, status="deliberation", deliberation_end=None)
    _proposal(
        db, org, user, status="deliberation", is_cosign_gated=True,
        deliberation_end=now - timedelta(minutes=1),
    )
    monkeypatch.setattr("sustained_majority_worker._now_naive", lambda: now)
    assert advance_due_deliberation_proposals(db)["advanced"] == 0


@pytest.mark.parametrize(
    ("method", "tally_type"),
    [("budget_allocation", "allocation"), ("budget_project", "project")],
)
@pytest.mark.parametrize(("cast", "expected"), [(6, "passed"), (1, "failed")])
def test_due_budget_worker_closes_on_quorum_without_snapshots(
    db, monkeypatch, method, tally_type, cast, expected,
):
    from budget_tally import AllocationTally, ProjectTally
    from delegation_engine import engine as delegation_engine
    org, user = _org(db), _user(db)
    now = datetime.utcnow()
    proposal = _proposal(
        db, org, user, status="voting", voting_method=method,
        voting_start=now - timedelta(days=2),
        voting_end=now - timedelta(minutes=1), quorum_threshold=0.5,
    )
    tally = (
        AllocationTally(total_ballots_cast=cast, total_eligible=10)
        if tally_type == "allocation"
        else ProjectTally(total_ballots_cast=cast, total_eligible=10)
    )
    monkeypatch.setattr(delegation_engine, "compute_tally", lambda *_: tally)
    monkeypatch.setattr("sustained_majority_worker._now_naive", lambda: now)
    monkeypatch.setattr("sustained_majority_worker._emit_proposal_closed_natural", lambda *a, **k: None)
    original_end = proposal.voting_end
    result = close_due_budget_proposals(db)
    db.expire_all()
    saved = db.get(models.Proposal, proposal.id)
    assert result["closed"] == 1
    assert saved.status == expected
    assert saved.voting_end == original_end
    assert db.query(models.VoteSnapshot).filter_by(proposal_id=proposal.id).count() == 0


def test_bulk_schedule_schema_requires_at_least_one_date():
    with pytest.raises(ValueError):
        schemas.BulkScheduleRequest(proposal_ids=[str(uuid.uuid4())])
    assert schemas.BulkScheduleRequest(
        proposal_ids=[str(uuid.uuid4())],
        voting_starts_at=datetime(2026, 9, 1),
    )


def test_monitor_disabled_is_public_safe_warning(db, monkeypatch):
    monkeypatch.setattr(settings, "proposal_schedule_automation_enabled", False)
    payload = _proposal_lifecycle_component(db, datetime.utcnow())
    assert payload["status"] == "warning"
    assert payload["automation_enabled"] is False
    assert "proposal_id" not in str(payload)


def test_monitor_errors_only_beyond_grace(db, monkeypatch):
    monkeypatch.setattr(settings, "proposal_schedule_automation_enabled", True)
    org, user = _org(db), _user(db)
    now = datetime.utcnow()
    _proposal(
        db, org, user, status="deliberation",
        deliberation_end=now - timedelta(minutes=12),
    )
    payload = _proposal_lifecycle_component(db, now)
    assert payload["status"] == "error"
    assert payload["overdue_count"] == 1
    assert payload["oldest_overdue_age_seconds"] >= 720


def test_monitor_null_legacy_schedule_is_informational(db, monkeypatch):
    monkeypatch.setattr(settings, "proposal_schedule_automation_enabled", True)
    org, user = _org(db), _user(db)
    _proposal(db, org, user, status="deliberation", deliberation_end=None)
    payload = _proposal_lifecycle_component(db, datetime.utcnow())
    assert payload["status"] == "ok"
    assert payload["unscheduled_active_deliberation_count"] == 1


def _client_for(db):
    def override_db():
        yield db
    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def _steward_setup(db):
    org, user = _org(db), _user(db, "steward")
    seed_default_roles_for_org(db, org.id)
    make_org_membership(db, org_id=org.id, user_id=user.id, role="steward")
    db.commit()
    return org, user


def _headers(user):
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def test_bulk_voting_endpoint_is_retry_safe_and_never_closes(db):
    org, user = _steward_setup(db)
    proposal = _proposal(
        db, org, user, status="deliberation",
        deliberation_start=datetime.utcnow() - timedelta(days=2),
        deliberation_end=datetime.utcnow() - timedelta(minutes=1),
    )
    db.commit()
    client = _client_for(db)
    try:
        url = f"/api/orgs/{org.slug}/proposals/bulk-advance-to-voting"
        first = client.post(url, headers=_headers(user), json={"proposal_ids": [proposal.id]})
        retry = client.post(url, headers=_headers(user), json={"proposal_ids": [proposal.id]})
    finally:
        app.dependency_overrides.clear()
    assert first.status_code == 200, first.text
    assert first.json()["advanced"] == 1
    assert retry.status_code == 200
    assert retry.json()["already_in_voting"] == 1
    db.expire_all()
    assert db.get(models.Proposal, proposal.id).status == "voting"


def test_bulk_voting_endpoint_returns_cosign_gate_result(db):
    org, user = _steward_setup(db)
    proposal = _proposal(
        db, org, user, status="deliberation", is_cosign_gated=True,
    )
    db.commit()
    client = _client_for(db)
    try:
        response = client.post(
            f"/api/orgs/{org.slug}/proposals/bulk-advance-to-voting",
            headers=_headers(user), json={"proposal_ids": [proposal.id]},
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["cosign_gate_required"] == 1


def test_bulk_schedule_updates_start_end_and_duration(db):
    org, user = _steward_setup(db)
    start = datetime.utcnow() + timedelta(days=2)
    end = start + timedelta(days=3)
    proposal = _proposal(
        db, org, user, status="deliberation",
        deliberation_start=datetime.utcnow(), deliberation_end=None,
    )
    db.commit()
    client = _client_for(db)
    try:
        response = client.patch(
            f"/api/orgs/{org.slug}/proposals/bulk-schedule",
            headers=_headers(user), json={
                "proposal_ids": [proposal.id],
                "voting_starts_at": start.isoformat() + "Z",
                "voting_ends_at": end.isoformat() + "Z",
            },
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200, response.text
    assert response.json()["updated"] == 1
    db.expire_all()
    saved = db.get(models.Proposal, proposal.id)
    assert saved.deliberation_end == start
    assert saved.voting_end_date == end
    expected_days = (start - saved.deliberation_start).total_seconds() / 86400
    assert saved.deliberation_days == pytest.approx(expected_days)


def test_bulk_schedule_requires_reason_to_shorten_active_vote(db):
    org, user = _steward_setup(db)
    start = datetime.utcnow() - timedelta(days=1)
    original_end = datetime.utcnow() + timedelta(days=5)
    proposal = _proposal(
        db, org, user, status="voting", voting_start=start,
        voting_end=original_end, voting_end_date=original_end,
    )
    db.commit()
    client = _client_for(db)
    try:
        response = client.patch(
            f"/api/orgs/{org.slug}/proposals/bulk-schedule",
            headers=_headers(user), json={
                "proposal_ids": [proposal.id],
                "voting_ends_at": (datetime.utcnow() + timedelta(days=2)).isoformat() + "Z",
            },
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["invalid"] == 1
    db.expire_all()
    assert db.get(models.Proposal, proposal.id).voting_end == original_end
