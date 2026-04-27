"""
Phase 7.5 — Privacy and Access Hardening tests.

Covers:
  - Audit log redaction at the `/api/admin/audit` boundary (per-action allowlist).
  - Elevated single-entry endpoint `/api/admin/audit/ballots/{id}` —
    reason-required, self-logs the elevation, returns unredacted content.
  - Audit-logging on `/api/admin/delegation-graph` and `/api/admin/users`.
  - User-facing access log at `/api/users/me/access-log` —
    surfaces elevated ballot views targeting the user, system-wide views
    that touch the user, and excludes non-elevated admin audit reads.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from database import Base, get_db
from main import app

_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def test_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def client(test_db):
    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user(db: Session, username: str, *, is_admin: bool = False) -> models.User:
    u = models.User(
        username=username,
        display_name=username.title(),
        password_hash=_DUMMY_HASH,
        email=f"{username}@test.example",
        email_verified=True,
        is_admin=is_admin,
    )
    db.add(u)
    db.flush()
    return u


def _auth(user: models.User) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _seed_vote_audit(
    db: Session,
    actor: models.User,
    *,
    action: str = "vote.cast",
    details: dict | None = None,
) -> models.AuditLog:
    """Create an audit log row directly (no proposal/vote machinery needed)."""
    entry = models.AuditLog(
        actor_id=actor.id,
        action=action,
        target_type="vote",
        target_id="00000000-0000-0000-0000-000000000001",
        details=details
        or {
            "proposal_id": "00000000-0000-0000-0000-0000000000aa",
            "vote_value": "yes",
            "ballot": {"approvals": ["00000000-0000-0000-0000-0000000000bb"]},
            "is_direct": True,
            "previous_value": None,
            "delegate_chain": None,
        },
        ip_address="127.0.0.1",
    )
    db.add(entry)
    db.flush()
    return entry


def _seed_delegation_audit(db: Session, actor: models.User) -> models.AuditLog:
    entry = models.AuditLog(
        actor_id=actor.id,
        action="delegation.created",
        target_type="delegation",
        target_id="00000000-0000-0000-0000-0000000000cc",
        details={
            "delegate_id": "00000000-0000-0000-0000-0000000000dd",
            "topic_id": None,
            "chain_behavior": "accept_sub",
        },
        ip_address="127.0.0.1",
    )
    db.add(entry)
    db.flush()
    return entry


# ---------------------------------------------------------------------------
# 1. Audit redaction
# ---------------------------------------------------------------------------

def test_audit_log_redacts_vote_cast(client, test_db):
    admin = _user(test_db, "admin1", is_admin=True)
    voter = _user(test_db, "voter1")
    _seed_vote_audit(
        test_db,
        voter,
        details={
            "proposal_id": "00000000-0000-0000-0000-0000000000ee",
            "vote_value": "yes",
            "ballot": {"approvals": ["x", "y"]},
            "is_direct": True,
            "previous_value": "no",
            "delegate_chain": None,
        },
    )
    test_db.commit()

    resp = client.get("/api/admin/audit?action=vote.cast", headers=_auth(admin))
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 1
    details = rows[0]["details"]
    assert details["vote_value"] == "<redacted>"
    assert details["ballot"] == "<redacted>"
    assert details["previous_value"] == "<redacted>"
    # Non-redacted fields pass through
    assert details["proposal_id"] == "00000000-0000-0000-0000-0000000000ee"
    assert details["is_direct"] is True
    # Redaction marker
    assert set(details["_redacted_fields"]) == {"vote_value", "ballot", "previous_value"}


def test_audit_log_passes_through_other_actions(client, test_db):
    admin = _user(test_db, "admin1", is_admin=True)
    delegator = _user(test_db, "delegator1")
    _seed_delegation_audit(test_db, delegator)
    test_db.commit()

    resp = client.get("/api/admin/audit?action=delegation.created", headers=_auth(admin))
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    details = rows[0]["details"]
    # No redaction applied
    assert details.get("delegate_id") == "00000000-0000-0000-0000-0000000000dd"
    assert details.get("chain_behavior") == "accept_sub"
    assert "_redacted_fields" not in details


# ---------------------------------------------------------------------------
# 2. Elevated endpoint
# ---------------------------------------------------------------------------

def test_elevated_endpoint_requires_reason(client, test_db):
    admin = _user(test_db, "admin1", is_admin=True)
    voter = _user(test_db, "voter1")
    entry = _seed_vote_audit(test_db, voter)
    test_db.commit()

    # Missing reason → 422 from FastAPI Query(..., required); spec says 400-ish.
    # FastAPI returns 422 for missing required query params; a string with all
    # whitespace passes the min_length but fails the runtime strip check.
    resp_missing = client.get(
        f"/api/admin/audit/ballots/{entry.id}", headers=_auth(admin)
    )
    assert resp_missing.status_code in (400, 422)

    # Whitespace-only reason → 400 (passes min_length=1, fails strip check)
    resp_blank = client.get(
        f"/api/admin/audit/ballots/{entry.id}?reason=%20%20%20",
        headers=_auth(admin),
    )
    assert resp_blank.status_code == 400
    assert "reason" in resp_blank.json()["detail"].lower()


def test_elevated_endpoint_returns_unredacted(client, test_db):
    admin = _user(test_db, "admin1", is_admin=True)
    voter = _user(test_db, "voter1")
    entry = _seed_vote_audit(
        test_db,
        voter,
        details={
            "proposal_id": "00000000-0000-0000-0000-0000000000ff",
            "vote_value": "yes",
            "ballot": {"approvals": ["alpha", "beta"]},
            "is_direct": True,
            "previous_value": None,
        },
    )
    test_db.commit()

    resp = client.get(
        f"/api/admin/audit/ballots/{entry.id}?reason=investigation",
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["details"]["vote_value"] == "yes"
    assert body["details"]["ballot"] == {"approvals": ["alpha", "beta"]}
    assert "_redacted_fields" not in body["details"]


def test_elevated_endpoint_logs_elevation(client, test_db):
    admin = _user(test_db, "admin1", is_admin=True)
    voter = _user(test_db, "voter1")
    entry = _seed_vote_audit(test_db, voter)
    test_db.commit()

    resp = client.get(
        f"/api/admin/audit/ballots/{entry.id}?reason=incident-2026-04-26",
        headers=_auth(admin),
    )
    assert resp.status_code == 200

    elevation = (
        test_db.query(models.AuditLog)
        .filter(models.AuditLog.action == "admin.audit_ballot_viewed")
        .one()
    )
    assert elevation.actor_id == admin.id
    assert elevation.target_type == "audit_log"
    assert elevation.target_id == entry.id
    assert elevation.details["reason"] == "incident-2026-04-26"
    assert elevation.details["viewed_action"] == "vote.cast"
    assert elevation.details["viewed_actor_id"] == voter.id


def test_elevated_endpoint_requires_admin(client, test_db):
    plain = _user(test_db, "plain1", is_admin=False)
    actor = _user(test_db, "voter1")
    entry = _seed_vote_audit(test_db, actor)
    test_db.commit()

    resp = client.get(
        f"/api/admin/audit/ballots/{entry.id}?reason=curious",
        headers=_auth(plain),
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 3. System-endpoint audit logging
# ---------------------------------------------------------------------------

def test_delegation_graph_logs_access(client, test_db):
    admin = _user(test_db, "admin1", is_admin=True)
    test_db.commit()

    resp = client.get("/api/admin/delegation-graph", headers=_auth(admin))
    assert resp.status_code == 200

    rows = (
        test_db.query(models.AuditLog)
        .filter(models.AuditLog.action == "admin.delegation_graph_viewed")
        .all()
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.actor_id == admin.id
    assert row.target_type == "system"
    assert row.target_id == "system_delegation_graph"
    assert "node_count" in row.details and "edge_count" in row.details


def test_user_list_logs_access(client, test_db):
    admin = _user(test_db, "admin1", is_admin=True)
    _user(test_db, "u2")
    _user(test_db, "u3")
    test_db.commit()

    resp = client.get("/api/admin/users", headers=_auth(admin))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) >= 3

    rows = (
        test_db.query(models.AuditLog)
        .filter(models.AuditLog.action == "admin.user_list_viewed")
        .all()
    )
    assert len(rows) == 1
    assert rows[0].actor_id == admin.id
    assert rows[0].details["user_count"] == len(body)


# ---------------------------------------------------------------------------
# 4. User access log
# ---------------------------------------------------------------------------

def test_access_log_includes_elevated_ballot_view_for_target_user(client, test_db):
    admin = _user(test_db, "admin1", is_admin=True)
    target = _user(test_db, "target_user")
    entry = _seed_vote_audit(test_db, target)
    test_db.commit()

    elev = client.get(
        f"/api/admin/audit/ballots/{entry.id}?reason=fraud-check",
        headers=_auth(admin),
    )
    assert elev.status_code == 200

    log = client.get("/api/users/me/access-log", headers=_auth(target))
    assert log.status_code == 200, log.text
    body = log.json()
    ballot_views = [e for e in body if e["action_type"] == "Viewed your ballot"]
    assert len(ballot_views) == 1
    e = ballot_views[0]
    assert e["accessor_id"] == admin.id
    assert e["accessor_role"] == "Platform admin"
    assert e["reason"] == "fraud-check"


def test_access_log_excludes_non_elevated_admin_audit_views(client, test_db):
    admin = _user(test_db, "admin1", is_admin=True)
    target = _user(test_db, "target_user")
    _seed_vote_audit(test_db, target)
    test_db.commit()

    # Admin reads the redacted audit log — this should NOT appear in target's
    # access log because no elevation occurred.
    resp = client.get("/api/admin/audit", headers=_auth(admin))
    assert resp.status_code == 200

    log = client.get("/api/users/me/access-log", headers=_auth(target))
    assert log.status_code == 200
    body = log.json()
    assert all(e["action_type"] != "Viewed your ballot" for e in body), (
        "Non-elevated admin audit reads must not surface in user access log"
    )


def test_access_log_cross_user_isolation(client, test_db):
    admin = _user(test_db, "admin1", is_admin=True)
    user_a = _user(test_db, "user_a")
    user_b = _user(test_db, "user_b")
    entry_b = _seed_vote_audit(test_db, user_b)
    test_db.commit()

    # Admin elevates to view user_b's ballot.
    resp = client.get(
        f"/api/admin/audit/ballots/{entry_b.id}?reason=user_b-investigation",
        headers=_auth(admin),
    )
    assert resp.status_code == 200

    # user_a's access log must NOT include the user_b ballot view.
    log_a = client.get("/api/users/me/access-log", headers=_auth(user_a)).json()
    assert all(e["action_type"] != "Viewed your ballot" for e in log_a)

    # user_b's access log MUST include it.
    log_b = client.get("/api/users/me/access-log", headers=_auth(user_b)).json()
    assert any(e["action_type"] == "Viewed your ballot" for e in log_b)


def test_access_log_includes_delegation_graph_view(client, test_db):
    admin = _user(test_db, "admin1", is_admin=True)
    user_x = _user(test_db, "user_x")
    test_db.commit()

    resp = client.get("/api/admin/delegation-graph", headers=_auth(admin))
    assert resp.status_code == 200

    log = client.get("/api/users/me/access-log", headers=_auth(user_x)).json()
    graph_views = [
        e for e in log if e["action_type"] == "Viewed system delegation graph"
    ]
    assert len(graph_views) == 1
    assert graph_views[0]["accessor_id"] == admin.id
    assert graph_views[0]["accessor_role"] == "Platform admin"
    assert graph_views[0]["reason"] is None
