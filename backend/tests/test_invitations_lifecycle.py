"""Phase 10.2 W-FIX-A — invitation create/resend/revoke/accept-authenticated.

Per docs/test_depth_audit_2026-05.md (Class A invitation entries):
  * test_create_invitations_schedules_email_per_invitee — POST
    /api/orgs/{slug}/invitations: each invitee gets a send_invitation_email
    BackgroundTask scheduled with the right args. Phase 9.6 W1 regression
    guard.
  * test_resend_invitation_rotates_token_and_schedules_email — POST
    .../invitations/{id}/resend: rotates token, extends expires_at, and
    schedules the email. Phase 9.6 W1 regression guard.
  * test_revoke_invitation_marks_status — DELETE
    .../invitations/{id}: status becomes "revoked".
  * test_accept_invitation_authenticated_emits_audit_and_membership —
    POST /api/orgs/join/{token} with an authenticated user emits
    `invitation.accepted_authenticated` audit + creates the OrgMembership.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from database import Base, get_db
from main import app
from routes import organizations as org_route
from tests.conftest import make_org_membership


_DUMMY_HASH = auth_utils.hash_password("demo1234")


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


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
def client(test_db):
    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def captured_invitation_calls(monkeypatch):
    """Capture calls to send_invitation_email so the BackgroundTask
    side-effect is observable. Route imports it from email_service so we
    monkeypatch the route-module binding.

    Phase 12.7 E added an optional `primary_color` 6th argument; capture
    it positionally so existing tests that index c[0..4] keep working
    while a new test can read c[5] for the branded color.
    """
    calls: list[tuple] = []

    async def _fake_send(email, token, org_name, org_slug, base_url, primary_color=None):
        calls.append((email, token, org_name, org_slug, base_url, primary_color))
        return True

    monkeypatch.setattr(org_route, "send_invitation_email", _fake_send)
    return calls


def _make_user(db, username: str, email: str | None = None) -> models.User:
    u = models.User(
        username=username,
        display_name=username.title(),
        password_hash=_DUMMY_HASH,
        email=email if email is not None else f"{username}@test.example",
        email_verified=True,
    )
    db.add(u)
    db.flush()
    return u


def _make_org(db, slug: str = "testorg", name: str = "Test Org") -> models.Organization:
    org = models.Organization(
        name=name,
        slug=slug,
        description="",
        join_policy="invite_only",
    )
    db.add(org)
    db.flush()
    return org


def _join(db, user, org, role="admin", status="active"):
    m = make_org_membership(
        db,
        user_id=user.id, org_id=org.id, role=role, status=status,
    )
    return m


def _make_invitation(
    db, org, *, email="invitee@test.example", inviter=None, role="member",
    expires_in_days=7, status_="pending", token=None,
) -> models.Invitation:
    if inviter is None:
        inviter = _make_user(db, f"inviter_{secrets.token_hex(4)}")
    inv = models.Invitation(
        org_id=org.id,
        email=email.lower(),
        invited_by=inviter.id,
        role=role,
        token=token or secrets.token_urlsafe(48),
        status=status_,
        expires_at=_now() + timedelta(days=expires_in_days),
    )
    db.add(inv)
    db.flush()
    return inv


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


# ---------------------------------------------------------------------------
# POST /api/orgs/{slug}/invitations  (create)
# ---------------------------------------------------------------------------

def test_create_invitations_schedules_email_per_invitee(
    client, test_db, captured_invitation_calls,
):
    """Phase 10.2 audit: Class A, POST /api/orgs/{slug}/invitations,
    send_invitation_email regression guard. POSTing two emails schedules
    two background-task calls with (email, token, org.name, org.slug,
    base_url) and the tokens match the rows actually persisted."""
    admin = _make_user(test_db, "orgadmin")
    org = _make_org(test_db, slug="acme", name="Acme")
    _join(test_db, admin, org, role="admin")
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/invitations",
        json={"emails": ["a@x.example", "b@x.example"], "role": "member"},
        headers=_auth(admin),
    )
    assert resp.status_code == 201, resp.text

    assert len(captured_invitation_calls) == 2
    by_email = {c[0]: c for c in captured_invitation_calls}
    assert set(by_email.keys()) == {"a@x.example", "b@x.example"}
    for email, c in by_email.items():
        # Look up the persisted invitation row and verify the token argument
        # matches the persisted row.
        inv = test_db.query(models.Invitation).filter(
            models.Invitation.email == email,
            models.Invitation.org_id == org.id,
        ).first()
        assert inv is not None
        # c = (email, token, org_name, org_slug, base_url)
        assert c[1] == inv.token
        assert c[2] == org.name
        assert c[3] == org.slug


def test_create_invitations_threads_org_branding_primary_color(
    client, test_db, captured_invitation_calls,
):
    """Phase 12.7 E: when the org has a configured branding primary color,
    the invitation email send is invoked with that color so the templated
    heading + button match the org's identity. When no branding is
    configured (covered by the prior test), the color arg is None and the
    template falls back to the platform default."""
    admin = _make_user(test_db, "branded_admin")
    org = _make_org(test_db, slug="branded", name="Branded Org")
    org.settings = {"branding": {"primary_color": "#4A90E2"}}
    _join(test_db, admin, org, role="admin")
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/invitations",
        json={"emails": ["c@x.example"], "role": "member"},
        headers=_auth(admin),
    )
    assert resp.status_code == 201, resp.text

    assert len(captured_invitation_calls) == 1
    c = captured_invitation_calls[0]
    # c = (email, token, org_name, org_slug, base_url, primary_color)
    assert c[0] == "c@x.example"
    assert c[5] == "#4A90E2"


# ---------------------------------------------------------------------------
# POST /api/orgs/{slug}/invitations/{id}/resend
# ---------------------------------------------------------------------------

def test_resend_invitation_rotates_token_and_schedules_email(
    client, test_db, captured_invitation_calls,
):
    """Phase 10.2 audit: Class A, POST .../invitations/{id}/resend,
    Phase 9.6 regression guard. Resend rotates the token, extends
    expires_at, and schedules the email background task."""
    admin = _make_user(test_db, "ad")
    org = _make_org(test_db, slug="rotor", name="Rotor")
    _join(test_db, admin, org, role="admin")
    inv = _make_invitation(
        test_db, org, email="rotate@x.example", inviter=admin,
    )
    original_token = inv.token
    original_expires = inv.expires_at
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/invitations/{inv.id}/resend",
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text

    test_db.refresh(inv)
    assert inv.token != original_token
    assert inv.expires_at >= original_expires

    assert len(captured_invitation_calls) == 1
    c = captured_invitation_calls[0]
    assert c[0] == "rotate@x.example"
    assert c[1] == inv.token  # the NEW token, not the old one
    assert c[2] == org.name
    assert c[3] == org.slug


# ---------------------------------------------------------------------------
# DELETE /api/orgs/{slug}/invitations/{id}
# ---------------------------------------------------------------------------

def test_revoke_invitation_marks_status(client, test_db):
    """Phase 10.2 audit: Class A, DELETE .../invitations/{id} — after a
    204, the row's status is "revoked"."""
    admin = _make_user(test_db, "revoker")
    org = _make_org(test_db, slug="rev", name="Rev")
    _join(test_db, admin, org, role="admin")
    inv = _make_invitation(test_db, org, email="bye@x.example", inviter=admin)
    test_db.commit()

    resp = client.delete(
        f"/api/orgs/{org.slug}/invitations/{inv.id}",
        headers=_auth(admin),
    )
    assert resp.status_code == 204, resp.text

    test_db.refresh(inv)
    assert inv.status == "revoked"


# ---------------------------------------------------------------------------
# POST /api/orgs/join/{token}  (accept_invitation, authenticated path)
# ---------------------------------------------------------------------------

def test_accept_invitation_authenticated_emits_audit_and_membership(
    client, test_db,
):
    """Phase 10.2 audit: Class A, POST /api/orgs/join/{token} —
    authenticated caller path emits `invitation.accepted_authenticated`
    audit + creates active OrgMembership in the inviting org."""
    inviter = _make_user(test_db, "host")
    accepter = _make_user(test_db, "guest", email="guest@x.example")
    org = _make_org(test_db, slug="hosted", name="Hosted")
    _join(test_db, inviter, org, role="admin")
    inv = _make_invitation(
        test_db, org, email="guest@x.example", inviter=inviter, role="member",
    )
    test_db.commit()

    resp = client.post(
        f"/api/orgs/join/{inv.token}",
        headers=_auth(accepter),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["org_slug"] == org.slug

    # Membership was created.
    m = test_db.query(models.OrgMembership).filter(
        models.OrgMembership.user_id == accepter.id,
        models.OrgMembership.org_id == org.id,
    ).first()
    assert m is not None
    assert m.status == "active"
    # Phase 12 — role is a Role ORM object; assert via system_key.
    assert m.role is not None and m.role.system_key == "member"

    # Invitation marked accepted.
    test_db.refresh(inv)
    assert inv.status == "accepted"

    # Audit row emitted.
    audit = test_db.query(models.AuditLog).filter(
        models.AuditLog.action == "invitation.accepted_authenticated",
        models.AuditLog.target_id == inv.id,
    ).first()
    assert audit is not None
    assert audit.actor_id == accepter.id
    assert audit.details["invitation_id"] == inv.id
    assert audit.details["org_id"] == org.id
    assert audit.details["role"] == "member"
    assert audit.details["accepting_user_id"] == accepter.id
