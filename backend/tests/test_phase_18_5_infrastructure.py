"""Phase 18.5 — infrastructure pass regression tests.

Spec: ``phase18_5_infrastructure_spec.md`` lines 173-178 (B2.3).

Single load-bearing item right now: regression coverage for the Phase 18
QA-discovered DELETE intent 503 bug. The route handler logic was already
correct (intent.status -> 'cancelled' + audit log + commit succeeded);
the bug was that the route returned an implicit ``None`` on a
``status_code=204`` decorator, which FastAPI's default serializer turns
into a 204 with a stray ``content-type: application/json`` header.
Cloudflare / Railway's edge proxy rejects the malformed 204 (a 204 must
have no body and no content-type per RFC 7230) with a 503 even though the
upstream commit has already succeeded.

The fix is ``return Response(status_code=204)`` — the same pattern used
by ``routes/organizations.py::cancel_join_request``. The regression
test asserts:

  - HTTP 204 (not 503).
  - No ``content-type`` header on the response (the proxy-trip vector).
  - Empty body.
  - Intent's DB status correctly transitioned to ``cancelled``.
  - Audit row written.

Style mirrors ``test_phase_18_delegation_org_scoping.py``: in-memory
SQLite, real models, ``TestClient`` against the full FastAPI app with
``get_db`` dependency overridden to the test session.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from database import Base, get_db
from main import app
from role_seed import seed_default_roles_for_org
from tests.conftest import make_org_membership


_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


# ---------------------------------------------------------------------------
# Fixtures (mirror test_phase_18_delegation_org_scoping.py)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def test_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def client(test_db: Session):
    def _get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(db: Session, username: str) -> models.User:
    u = models.User(
        username=username,
        display_name=username.title(),
        password_hash=_DUMMY_HASH,
        email=f"{username}@test.example",
        email_verified=True,
        default_follow_policy="require_approval",
    )
    db.add(u)
    db.flush()
    return u


def _make_org(db: Session, slug: str) -> models.Organization:
    o = models.Organization(
        name=slug.title(),
        slug=slug,
        description="",
        settings={},
    )
    db.add(o)
    db.flush()
    seed_default_roles_for_org(db, o.id)
    return o


def _make_intent(
    db: Session,
    delegator: models.User,
    delegate: models.User,
    *,
    org_id: str,
    topic_id: Optional[str] = None,
) -> models.DelegationIntent:
    """Create a pending DelegationIntent with its supporting FollowRequest."""
    freq = models.FollowRequest(
        requester_id=delegator.id,
        target_id=delegate.id,
        org_id=org_id,
        status="pending",
    )
    db.add(freq)
    db.flush()
    intent = models.DelegationIntent(
        delegator_id=delegator.id,
        delegate_id=delegate.id,
        org_id=org_id,
        topic_id=topic_id,
        chain_behavior="accept_sub",
        follow_request_id=freq.id,
        status="pending",
        expires_at=datetime.now(timezone.utc).replace(tzinfo=None)
        + timedelta(days=30),
    )
    db.add(intent)
    db.flush()
    return intent


def _auth(user: models.User) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


# ===========================================================================
# Regression — DELETE /api/orgs/{slug}/delegations/intents/{id} returns 204.
# ===========================================================================


def test_delete_delegation_intent_returns_success(client, test_db):
    """The DELETE endpoint must return a clean 204 (no content-type, no
    body), not the malformed 204-with-JSON-content-type that triggered
    the prod 503 (Phase 18 QA report observation #1).

    Asserts both the HTTP-level shape (proxy-trip vector) and the DB
    side-effect (intent transitions to 'cancelled' + audit row written).
    """
    org = _make_org(test_db, "demo")
    alice = _make_user(test_db, "alice")
    bob = _make_user(test_db, "bob")
    make_org_membership(test_db, org_id=org.id, user_id=alice.id, role="member")
    make_org_membership(test_db, org_id=org.id, user_id=bob.id, role="member")
    intent = _make_intent(test_db, alice, bob, org_id=org.id)
    test_db.commit()
    intent_id = intent.id

    resp = client.delete(
        f"/api/orgs/{org.slug}/delegations/intents/{intent_id}",
        headers=_auth(alice),
    )

    # HTTP shape: proper 204, no content-type, empty body.
    # The content-type assertion is the load-bearing one — the prod 503
    # bug was specifically the stray 'content-type: application/json'
    # header on a 204 response, which Cloudflare / Railway's edge proxy
    # rejects per RFC 7230 (a 204 must have no message body and no
    # content-type indicating one).
    assert resp.status_code == 204, (
        f"Expected 204, got {resp.status_code}. Body: {resp.text!r}"
    )
    assert resp.text == "", f"Expected empty body on 204, got: {resp.text!r}"
    assert resp.headers.get("content-type") is None, (
        "204 response must not have content-type header (RFC 7230). "
        "If a content-type is set, Cloudflare / Railway's edge proxy "
        "rejects the response with a 503 even though the upstream "
        "commit succeeded — this is the prod bug Phase 18.5 B2 fixes. "
        f"Got content-type: {resp.headers.get('content-type')!r}"
    )

    # DB side-effect: intent transitions to 'cancelled'.
    test_db.expire_all()
    refreshed = test_db.get(models.DelegationIntent, intent_id)
    assert refreshed is not None, (
        "Intent row should still exist (cancellation is a status "
        "transition, not a DELETE)."
    )
    assert refreshed.status == "cancelled", (
        f"Intent status should be 'cancelled', got {refreshed.status!r}"
    )

    # DB side-effect: audit row written.
    audit = test_db.query(models.AuditLog).filter(
        models.AuditLog.action == "delegation_intent.cancelled",
        models.AuditLog.target_id == intent_id,
    ).first()
    assert audit is not None, (
        "Expected delegation_intent.cancelled audit row after DELETE"
    )
    assert audit.actor_id == alice.id


def test_delete_delegation_intent_404_for_nonexistent(client, test_db):
    """Sanity check the not-found path also returns a clean response —
    the fix shouldn't have broken the 404 path."""
    org = _make_org(test_db, "demo")
    alice = _make_user(test_db, "alice")
    make_org_membership(test_db, org_id=org.id, user_id=alice.id, role="member")
    test_db.commit()

    resp = client.delete(
        f"/api/orgs/{org.slug}/delegations/intents/nonexistent-id",
        headers=_auth(alice),
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Intent not found"


def test_delete_delegation_intent_409_when_already_cancelled(client, test_db):
    """A second DELETE on an already-cancelled intent should return 409
    (not 204 again, not 500). Verifies the conflict-detection path is
    intact post-fix."""
    org = _make_org(test_db, "demo")
    alice = _make_user(test_db, "alice")
    bob = _make_user(test_db, "bob")
    make_org_membership(test_db, org_id=org.id, user_id=alice.id, role="member")
    make_org_membership(test_db, org_id=org.id, user_id=bob.id, role="member")
    intent = _make_intent(test_db, alice, bob, org_id=org.id)
    test_db.commit()
    intent_id = intent.id

    # First DELETE — should succeed.
    resp1 = client.delete(
        f"/api/orgs/{org.slug}/delegations/intents/{intent_id}",
        headers=_auth(alice),
    )
    assert resp1.status_code == 204

    # Second DELETE — should 409 (intent is already cancelled).
    resp2 = client.delete(
        f"/api/orgs/{org.slug}/delegations/intents/{intent_id}",
        headers=_auth(alice),
    )
    assert resp2.status_code == 409
    assert "already cancelled" in resp2.json()["detail"]
