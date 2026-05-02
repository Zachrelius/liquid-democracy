"""Phase 9.7 W1 + W5 — invitation-aware register/login + meta endpoint.

Covers the regression matrix for the invitation flow rewrite:

  * Register with valid invitation_token: account created, OrgMembership in
    inviting org, invitation accepted, audit `invitation.accepted_via_registration`,
    AND user is NOT auto-joined to demo even with IS_PUBLIC_DEMO=true. The
    demo-skip assertion is the load-bearing regression test against the bug
    that bit Z's wife.
  * Register with bad token (expired / revoked / unknown / email-mismatch):
    400, no user created, no membership, no audit.
  * Login with valid invitation_token: existing user authenticates, gets a
    membership in the inviting org, audit `invitation.accepted_via_login`.
  * Login with already-member: idempotent — invitation accepted, no
    duplicate membership.
  * Login with email-mismatch token: 400.
  * GET /api/invitations/{token}/meta: valid pending → 200 + metadata;
    invalid / expired / accepted → 404.
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
from settings import settings


_DUMMY_HASH = auth_utils.hash_password("demo1234")


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


@pytest.fixture(scope="function")
def public_demo(monkeypatch):
    """is_public_demo=True, debug=False — matches the demo deployment."""
    monkeypatch.setattr(settings, "debug", False)
    monkeypatch.setattr(settings, "is_public_demo", True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _create_org(db, name: str = "GameNights", slug: str = "gamenights") -> models.Organization:
    org = models.Organization(
        name=name,
        slug=slug,
        description="Test org",
        join_policy="invite_only",
    )
    db.add(org)
    db.flush()
    return org


def _create_demo_org(db) -> models.Organization:
    return _create_org(db, name="Demo Organization", slug="demo")


def _create_user(db, username: str, email: str | None = None, email_verified: bool = True) -> models.User:
    u = models.User(
        username=username,
        display_name=username.title(),
        password_hash=_DUMMY_HASH,
        email=email if email is not None else f"{username}@test.example",
        email_verified=email_verified,
    )
    db.add(u)
    db.flush()
    return u


def _create_invitation(
    db,
    org: models.Organization,
    email: str,
    role: str = "member",
    *,
    inviter: models.User | None = None,
    expires_in_days: int = 7,
    status_: str = "pending",
    token: str | None = None,
) -> models.Invitation:
    if inviter is None:
        inviter = _create_user(db, f"inviter_{secrets.token_hex(4)}")
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


def _seed_first_user(db) -> None:
    """Make sure the registrant in tests isn't the platform's first user
    (which would auto-verify + auto-admin)."""
    _create_user(db, "seed_admin", email_verified=True)


# ---------------------------------------------------------------------------
# Register with invitation_token
# ---------------------------------------------------------------------------

def test_register_with_invitation_token_skips_demo_auto_join(
    client, test_db, public_demo
):
    """LOAD-BEARING: register with a valid invitation_token while
    IS_PUBLIC_DEMO=true must skip the demo auto-join. The user belongs to
    the inviting org, NOT to demo. This is the regression test against the
    bug that landed Z's wife in demo instead of GameNights."""
    demo_org = _create_demo_org(test_db)
    gamenights = _create_org(test_db)
    inviter = _create_user(test_db, "z")
    inv = _create_invitation(
        test_db, gamenights, "wife@test.example", role="member", inviter=inviter,
    )
    test_db.commit()

    resp = client.post(
        "/api/auth/register",
        json={
            "username": "wife",
            "display_name": "Wife",
            "email": "wife@test.example",
            "password": "demo1234!",
            "invitation_token": inv.token,
        },
    )
    assert resp.status_code == 201, resp.text

    user = test_db.query(models.User).filter(
        models.User.username == "wife"
    ).first()
    assert user is not None

    # OrgMembership in inviting org, with the invitation's role.
    gn_membership = test_db.query(models.OrgMembership).filter(
        models.OrgMembership.user_id == user.id,
        models.OrgMembership.org_id == gamenights.id,
    ).first()
    assert gn_membership is not None
    assert gn_membership.role == "member"
    assert gn_membership.status == "active"

    # Invitation marked accepted.
    test_db.refresh(inv)
    assert inv.status == "accepted"
    assert inv.accepted_at is not None

    # Audit fired with the right shape.
    audit = test_db.query(models.AuditLog).filter(
        models.AuditLog.action == "invitation.accepted_via_registration",
        models.AuditLog.target_id == inv.id,
    ).first()
    assert audit is not None
    assert audit.actor_id == user.id
    assert audit.target_type == "invitation"
    details = audit.details or {}
    assert details["invitation_id"] == inv.id
    assert details["org_id"] == gamenights.id
    assert details["role"] == "member"
    assert details["invited_email"] == "wife@test.example"
    assert details["accepting_user_id"] == user.id

    # Demo auto-join happens at email verification — register doesn't trigger
    # it on its own. But the spec is "skip demo auto-join even if verify-email
    # runs" — verify by completing email verification and confirming demo
    # membership is still NOT created.
    ev = test_db.query(models.EmailVerification).filter(
        models.EmailVerification.user_id == user.id,
    ).first()
    assert ev is not None
    resp_v = client.post(
        "/api/auth/verify-email", json={"token": ev.token}
    )
    assert resp_v.status_code == 200

    test_db.expire_all()
    demo_membership = test_db.query(models.OrgMembership).filter(
        models.OrgMembership.user_id == user.id,
        models.OrgMembership.org_id == demo_org.id,
    ).first()
    assert demo_membership is None, (
        "Invitation-registered user must NOT be auto-joined to demo even "
        "when IS_PUBLIC_DEMO=true. This is the regression that bit Z's wife."
    )


def test_register_without_invitation_token_still_auto_joins_demo(
    client, test_db, public_demo
):
    """Sanity: standard register path still auto-joins to demo when
    IS_PUBLIC_DEMO=true and no invitation_token is present."""
    demo_org = _create_demo_org(test_db)
    _seed_first_user(test_db)
    test_db.commit()

    resp = client.post(
        "/api/auth/register",
        json={
            "username": "newbie",
            "display_name": "Newbie",
            "email": "newbie@test.example",
            "password": "demo1234!",
        },
    )
    assert resp.status_code == 201, resp.text

    user = test_db.query(models.User).filter(
        models.User.username == "newbie"
    ).first()
    ev = test_db.query(models.EmailVerification).filter(
        models.EmailVerification.user_id == user.id,
    ).first()
    resp_v = client.post(
        "/api/auth/verify-email", json={"token": ev.token}
    )
    assert resp_v.status_code == 200

    test_db.expire_all()
    demo_membership = test_db.query(models.OrgMembership).filter(
        models.OrgMembership.user_id == user.id,
        models.OrgMembership.org_id == demo_org.id,
    ).first()
    assert demo_membership is not None


def test_register_with_expired_invitation_token_returns_400(client, test_db):
    org = _create_org(test_db)
    inv = _create_invitation(
        test_db, org, "wife@test.example", expires_in_days=-1,
    )
    test_db.commit()

    resp = client.post(
        "/api/auth/register",
        json={
            "username": "wife",
            "display_name": "Wife",
            "email": "wife@test.example",
            "password": "demo1234!",
            "invitation_token": inv.token,
        },
    )
    assert resp.status_code == 400
    assert "Invalid or expired invitation token" in resp.json()["detail"]

    # No user, no membership, no audit.
    assert test_db.query(models.User).filter(
        models.User.username == "wife"
    ).first() is None
    assert test_db.query(models.OrgMembership).filter(
        models.OrgMembership.org_id == org.id,
    ).count() == 0
    assert test_db.query(models.AuditLog).filter(
        models.AuditLog.action == "invitation.accepted_via_registration",
    ).count() == 0


def test_register_with_revoked_invitation_token_returns_400(client, test_db):
    org = _create_org(test_db)
    inv = _create_invitation(
        test_db, org, "wife@test.example", status_="revoked",
    )
    test_db.commit()

    resp = client.post(
        "/api/auth/register",
        json={
            "username": "wife",
            "display_name": "Wife",
            "email": "wife@test.example",
            "password": "demo1234!",
            "invitation_token": inv.token,
        },
    )
    assert resp.status_code == 400
    assert "Invalid or expired invitation token" in resp.json()["detail"]
    assert test_db.query(models.User).filter(
        models.User.username == "wife"
    ).first() is None


def test_register_with_unknown_invitation_token_returns_400(client, test_db):
    resp = client.post(
        "/api/auth/register",
        json={
            "username": "ghost",
            "display_name": "Ghost",
            "email": "ghost@test.example",
            "password": "demo1234!",
            "invitation_token": "nonexistent-token",
        },
    )
    assert resp.status_code == 400
    assert "Invalid or expired invitation token" in resp.json()["detail"]


def test_register_with_email_mismatch_token_returns_400(client, test_db):
    org = _create_org(test_db)
    inv = _create_invitation(test_db, org, "wife@test.example")
    test_db.commit()

    resp = client.post(
        "/api/auth/register",
        json={
            "username": "stranger",
            "display_name": "Stranger",
            "email": "someone-else@test.example",
            "password": "demo1234!",
            "invitation_token": inv.token,
        },
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "wife@test.example" in detail
    assert "someone-else@test.example" in detail
    # No user account left behind.
    assert test_db.query(models.User).filter(
        models.User.username == "stranger"
    ).first() is None


# ---------------------------------------------------------------------------
# Login with invitation_token
# ---------------------------------------------------------------------------

def test_login_with_invitation_token_consumes_invitation(client, test_db):
    org = _create_org(test_db)
    user = _create_user(test_db, "alice", email="alice@test.example")
    user.password_hash = auth_utils.hash_password("p@ssword!")
    inv = _create_invitation(test_db, org, "alice@test.example", role="admin")
    test_db.commit()

    resp = client.post(
        "/api/auth/login",
        data={
            "username": "alice",
            "password": "p@ssword!",
            "invitation_token": inv.token,
        },
    )
    assert resp.status_code == 200, resp.text

    # Membership created with invitation's role.
    membership = test_db.query(models.OrgMembership).filter(
        models.OrgMembership.user_id == user.id,
        models.OrgMembership.org_id == org.id,
    ).first()
    assert membership is not None
    assert membership.role == "admin"
    assert membership.status == "active"

    # Invitation accepted, audit fired.
    test_db.refresh(inv)
    assert inv.status == "accepted"
    audit = test_db.query(models.AuditLog).filter(
        models.AuditLog.action == "invitation.accepted_via_login",
        models.AuditLog.target_id == inv.id,
    ).first()
    assert audit is not None
    assert audit.actor_id == user.id
    details = audit.details or {}
    assert details["invitation_id"] == inv.id
    assert details["org_id"] == org.id
    assert details["accepting_user_id"] == user.id


def test_login_with_invitation_token_already_member_is_idempotent(client, test_db):
    """If the user is already an active member, the invitation is still
    marked accepted and audit fires, but no duplicate membership is created."""
    org = _create_org(test_db)
    user = _create_user(test_db, "alice", email="alice@test.example")
    user.password_hash = auth_utils.hash_password("p@ssword!")
    # Pre-existing active membership.
    test_db.add(models.OrgMembership(
        user_id=user.id, org_id=org.id, role="member", status="active",
    ))
    inv = _create_invitation(test_db, org, "alice@test.example", role="admin")
    test_db.commit()

    resp = client.post(
        "/api/auth/login",
        data={
            "username": "alice",
            "password": "p@ssword!",
            "invitation_token": inv.token,
        },
    )
    assert resp.status_code == 200, resp.text

    # Exactly one membership row, role unchanged (idempotent — we don't
    # downgrade or upgrade a pre-existing active membership).
    memberships = test_db.query(models.OrgMembership).filter(
        models.OrgMembership.user_id == user.id,
        models.OrgMembership.org_id == org.id,
    ).all()
    assert len(memberships) == 1
    assert memberships[0].role == "member"

    # Invitation marked accepted and audit fired.
    test_db.refresh(inv)
    assert inv.status == "accepted"
    audit = test_db.query(models.AuditLog).filter(
        models.AuditLog.action == "invitation.accepted_via_login",
        models.AuditLog.target_id == inv.id,
    ).first()
    assert audit is not None


def test_login_with_email_mismatch_invitation_returns_400(client, test_db):
    org = _create_org(test_db)
    user = _create_user(test_db, "alice", email="alice@test.example")
    user.password_hash = auth_utils.hash_password("p@ssword!")
    # Invitation is for a different email.
    inv = _create_invitation(test_db, org, "wife@test.example")
    test_db.commit()

    resp = client.post(
        "/api/auth/login",
        data={
            "username": "alice",
            "password": "p@ssword!",
            "invitation_token": inv.token,
        },
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "wife@test.example" in detail
    assert "alice@test.example" in detail

    # No membership created.
    assert test_db.query(models.OrgMembership).filter(
        models.OrgMembership.user_id == user.id,
        models.OrgMembership.org_id == org.id,
    ).first() is None


def test_login_without_invitation_token_unchanged(client, test_db):
    """Sanity: the login flow without invitation_token is identical to today."""
    user = _create_user(test_db, "alice")
    user.password_hash = auth_utils.hash_password("p@ssword!")
    test_db.commit()

    resp = client.post(
        "/api/auth/login",
        data={
            "username": "alice",
            "password": "p@ssword!",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert "refresh_token" in body


# ---------------------------------------------------------------------------
# GET /api/invitations/{token}/meta
# ---------------------------------------------------------------------------

def test_invitation_meta_returns_metadata_for_valid_pending_token(client, test_db):
    org = _create_org(test_db, name="GameNights", slug="gamenights")
    inv = _create_invitation(
        test_db, org, "wife@test.example", role="member",
    )
    test_db.commit()

    resp = client.get(f"/api/invitations/{inv.token}/meta")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["org_name"] == "GameNights"
    assert data["org_slug"] == "gamenights"
    assert data["invited_email"] == "wife@test.example"
    assert data["role"] == "member"
    assert "expires_at" in data


def test_invitation_meta_returns_404_for_unknown_token(client, test_db):
    resp = client.get("/api/invitations/no-such-token/meta")
    assert resp.status_code == 404


def test_invitation_meta_returns_404_for_expired_token(client, test_db):
    org = _create_org(test_db)
    inv = _create_invitation(
        test_db, org, "wife@test.example", expires_in_days=-1,
    )
    test_db.commit()

    resp = client.get(f"/api/invitations/{inv.token}/meta")
    assert resp.status_code == 404


def test_invitation_meta_returns_404_for_accepted_token(client, test_db):
    """Accepted invitations should also 404 — they're not consumable any
    longer and the meta endpoint shouldn't reveal that the org/email
    pairing exists."""
    org = _create_org(test_db)
    inv = _create_invitation(
        test_db, org, "wife@test.example", status_="accepted",
    )
    test_db.commit()

    resp = client.get(f"/api/invitations/{inv.token}/meta")
    assert resp.status_code == 404
