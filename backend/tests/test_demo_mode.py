"""
Phase 6.5 — EA Demo Landing + Public Deployment.

Covers the public-demo backend surface:
  - GET  /api/auth/demo-users   (persona picker gating)
  - POST /api/auth/demo-login   (passwordless persona login + audit log)
  - Demo-org auto-join on email verification when is_public_demo=True
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from jose import jwt
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
def flags_off(monkeypatch):
    """Both debug and is_public_demo are False."""
    monkeypatch.setattr(settings, "debug", False)
    monkeypatch.setattr(settings, "is_public_demo", False)


@pytest.fixture(scope="function")
def public_demo(monkeypatch):
    """is_public_demo=True, debug=False — matches the demo deployment."""
    monkeypatch.setattr(settings, "debug", False)
    monkeypatch.setattr(settings, "is_public_demo", True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_demo_org(db) -> models.Organization:
    org = models.Organization(
        name="Demo Organization",
        slug="demo",
        description="Test demo org",
        join_policy="open",
    )
    db.add(org)
    db.flush()
    return org


def _create_user(db, username: str, email_verified: bool = True) -> models.User:
    u = models.User(
        username=username,
        display_name=username.title(),
        password_hash=_DUMMY_HASH,
        email=f"{username}@test.example",
        email_verified=email_verified,
    )
    db.add(u)
    db.flush()
    return u


# ---------------------------------------------------------------------------
# GET /api/auth/demo-users
# ---------------------------------------------------------------------------

def test_demo_users_endpoint_returns_404_when_flag_off(client, flags_off):
    resp = client.get("/api/auth/demo-users")
    assert resp.status_code == 404


def test_demo_users_endpoint_returns_list_when_is_public_demo_true(
    client, test_db, public_demo
):
    _create_user(test_db, "alice")
    _create_user(test_db, "admin")
    _create_user(test_db, "carol")
    test_db.commit()

    resp = client.get("/api/auth/demo-users")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    usernames = {u["username"] for u in data}
    assert {"alice", "admin", "carol"}.issubset(usernames)
    # Shape check: each entry has username + display_name only.
    for entry in data:
        assert set(entry.keys()) == {"username", "display_name"}


# ---------------------------------------------------------------------------
# POST /api/auth/demo-login
# ---------------------------------------------------------------------------

def test_demo_login_404_when_flag_off(client, test_db, flags_off):
    _create_user(test_db, "alice")
    test_db.commit()

    resp = client.post("/api/auth/demo-login", json={"username": "alice"})
    assert resp.status_code == 404


def test_demo_login_404_for_non_allowlisted_username(client, test_db, public_demo):
    # A real user that is NOT on the persona allowlist.
    _create_user(test_db, "mallory")
    test_db.commit()

    resp = client.post("/api/auth/demo-login", json={"username": "mallory"})
    assert resp.status_code == 404

    # And a username that doesn't exist at all.
    resp = client.post("/api/auth/demo-login", json={"username": "notauser"})
    assert resp.status_code == 404


def test_demo_login_issues_tokens_for_allowlisted_user(client, test_db, public_demo):
    alice = _create_user(test_db, "alice")
    test_db.commit()

    resp = client.post("/api/auth/demo-login", json={"username": "alice"})
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["refresh_token"]

    # Access token decodes to alice's user id.
    payload = jwt.decode(
        body["access_token"],
        settings.secret_key,
        algorithms=[auth_utils.ALGORITHM],
    )
    assert payload["sub"] == alice.id

    # Refresh token is persisted and unrevoked.
    rt = test_db.query(models.RefreshToken).filter(
        models.RefreshToken.token == body["refresh_token"],
    ).first()
    assert rt is not None
    assert rt.user_id == alice.id
    assert rt.revoked_at is None


def test_demo_login_writes_audit_log_entry(client, test_db, public_demo):
    alice = _create_user(test_db, "alice")
    test_db.commit()

    resp = client.post("/api/auth/demo-login", json={"username": "alice"})
    assert resp.status_code == 200

    entry = test_db.query(models.AuditLog).filter(
        models.AuditLog.action == "user.demo_login",
        models.AuditLog.target_id == alice.id,
    ).first()
    assert entry is not None
    assert entry.actor_id == alice.id
    assert entry.target_type == "user"
    assert entry.details.get("username") == "alice"


# ---------------------------------------------------------------------------
# Email verification → demo-org auto-join
# ---------------------------------------------------------------------------

def _register_and_get_verify_token(client, test_db, username: str) -> str:
    resp = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "display_name": username.title(),
            "email": f"{username}@test.example",
            "password": "demo1234!",
        },
    )
    assert resp.status_code == 201, resp.text

    # First registered user is auto-verified with no email sent — use second user
    # to exercise the full verify flow. Fetch the pending (unverified) record.
    user = test_db.query(models.User).filter(
        models.User.username == username
    ).first()
    assert user is not None
    ev = test_db.query(models.EmailVerification).filter(
        models.EmailVerification.user_id == user.id,
        models.EmailVerification.verified_at.is_(None),
    ).first()
    return ev.token if ev else ""


def test_registration_auto_joins_demo_org_when_public_demo_flag_set(
    client, test_db, public_demo
):
    demo_org = _create_demo_org(test_db)
    # Seed a first-user placeholder so our registrant isn't the auto-verified
    # first user (we need the real verification path).
    _create_user(test_db, "seed_admin", email_verified=True)
    test_db.commit()

    token = _register_and_get_verify_token(client, test_db, "newbie")
    assert token

    # Before verification: no membership yet.
    user = test_db.query(models.User).filter(models.User.username == "newbie").first()
    membership_before = test_db.query(models.OrgMembership).filter(
        models.OrgMembership.user_id == user.id,
        models.OrgMembership.org_id == demo_org.id,
    ).first()
    assert membership_before is None

    resp = client.post("/api/auth/verify-email", json={"token": token})
    assert resp.status_code == 200

    test_db.expire_all()
    membership = test_db.query(models.OrgMembership).filter(
        models.OrgMembership.user_id == user.id,
        models.OrgMembership.org_id == demo_org.id,
    ).first()
    assert membership is not None
    assert membership.role == "member"
    assert membership.status == "active"


def test_registration_does_not_auto_join_when_flag_off(
    client, test_db, flags_off
):
    demo_org = _create_demo_org(test_db)
    _create_user(test_db, "seed_admin", email_verified=True)
    test_db.commit()

    token = _register_and_get_verify_token(client, test_db, "newbie2")
    assert token

    resp = client.post("/api/auth/verify-email", json={"token": token})
    assert resp.status_code == 200

    user = test_db.query(models.User).filter(
        models.User.username == "newbie2"
    ).first()
    membership = test_db.query(models.OrgMembership).filter(
        models.OrgMembership.user_id == user.id,
        models.OrgMembership.org_id == demo_org.id,
    ).first()
    assert membership is None


def test_verify_tolerates_missing_demo_org_when_public_demo_flag_set(
    client, test_db, public_demo
):
    """If the demo org isn't seeded we still verify successfully — just warn."""
    _create_user(test_db, "seed_admin", email_verified=True)
    test_db.commit()

    token = _register_and_get_verify_token(client, test_db, "lonely")
    assert token

    resp = client.post("/api/auth/verify-email", json={"token": token})
    assert resp.status_code == 200
