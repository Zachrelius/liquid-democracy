"""Phase 10.2 W-FIX-A — POST /api/auth/register side-effect coverage.

Per docs/test_depth_audit_2026-05.md (Class A, register):
  * test_register_queues_verification_email — assert
    background_tasks.add_task scheduled send_verification_email with
    (email, token_from_db, settings.base_url) for the non-first-user path.
  * test_register_first_user_skips_email_send_and_auto_verifies — empty DB
    → first registrant gets email_verified=True, is_admin=True, NO email
    scheduled.
  * test_register_audit_emits_user_registered — non-first-user registration
    emits a `user.registered` audit row with the expected detail shape.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from database import Base, get_db
from main import app
from routes import auth as auth_route
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


@pytest.fixture
def captured_email_calls(monkeypatch):
    """Capture every call to send_verification_email so we can assert on
    args + count without actually trying to ship via Resend/SMTP. The route
    imports the function from email_service, so we monkeypatch the binding
    on the route module."""
    calls: list[tuple] = []

    async def _fake_send(email, token, base_url):
        calls.append((email, token, base_url))
        return True

    monkeypatch.setattr(auth_route, "send_verification_email", _fake_send)
    return calls


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_first_user(db) -> models.User:
    """Make sure the registrant under test isn't the platform's first user
    (which would trigger auto-verify + auto-admin)."""
    u = models.User(
        username="seed_admin",
        display_name="Seed Admin",
        password_hash=_DUMMY_HASH,
        email="seed@test.example",
        email_verified=True,
        is_admin=True,
    )
    db.add(u)
    db.flush()
    return u


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_register_queues_verification_email(
    client, test_db, captured_email_calls,
):
    """Phase 10.2 audit: Class A, POST /api/auth/register,
    send_verification_email assertion. Non-first-user registration must
    schedule send_verification_email with the email + DB-stored token +
    settings.base_url."""
    _seed_first_user(test_db)
    test_db.commit()

    resp = client.post(
        "/api/auth/register",
        json={
            "username": "newcomer",
            "display_name": "New Comer",
            "email": "newcomer@test.example",
            "password": "demo1234!",
        },
    )
    assert resp.status_code == 201, resp.text

    # Background task already executed — TestClient waits for it.
    assert len(captured_email_calls) == 1, (
        f"expected exactly 1 send_verification_email call, got "
        f"{captured_email_calls!r}"
    )
    email_arg, token_arg, base_url_arg = captured_email_calls[0]
    assert email_arg == "newcomer@test.example"
    assert base_url_arg == settings.base_url

    # The token argument must match the token that was actually persisted
    # for this user — proves the route didn't race / pass a stale value.
    user = test_db.query(models.User).filter(
        models.User.username == "newcomer",
    ).first()
    assert user is not None
    ev = test_db.query(models.EmailVerification).filter(
        models.EmailVerification.user_id == user.id,
    ).first()
    assert ev is not None
    assert ev.token == token_arg


def test_register_first_user_skips_email_send_and_auto_verifies(
    client, test_db, captured_email_calls,
):
    """Phase 10.2 audit: Class A, POST /api/auth/register, first-user
    branch. Empty DB → first registrant gets email_verified=True,
    is_admin=True, and NO send_verification_email is scheduled."""
    # No seed user — this caller IS the first user.

    resp = client.post(
        "/api/auth/register",
        json={
            "username": "founder",
            "display_name": "Founder",
            "email": "founder@test.example",
            "password": "demo1234!",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["email_verified"] is True
    assert body["is_admin"] is True
    assert body["is_first_user"] is True

    # No email scheduled.
    assert captured_email_calls == [], (
        f"expected NO send_verification_email calls for first-user, got "
        f"{captured_email_calls!r}"
    )

    # The verification record itself is created and pre-marked verified.
    user = test_db.query(models.User).filter(
        models.User.username == "founder",
    ).first()
    ev = test_db.query(models.EmailVerification).filter(
        models.EmailVerification.user_id == user.id,
    ).first()
    assert ev is not None
    assert ev.verified_at is not None


def test_register_audit_emits_user_registered(
    client, test_db, captured_email_calls,
):
    """Phase 10.2 audit: Class A, POST /api/auth/register, audit emission.
    Non-first-user registration must emit `user.registered` with the
    expected detail shape ({username, email, is_first_user})."""
    _seed_first_user(test_db)
    test_db.commit()

    resp = client.post(
        "/api/auth/register",
        json={
            "username": "auditme",
            "display_name": "Audit Me",
            "email": "auditme@test.example",
            "password": "demo1234!",
        },
    )
    assert resp.status_code == 201, resp.text

    user = test_db.query(models.User).filter(
        models.User.username == "auditme",
    ).first()
    audit = test_db.query(models.AuditLog).filter(
        models.AuditLog.action == "user.registered",
        models.AuditLog.target_id == user.id,
    ).first()
    assert audit is not None
    assert audit.actor_id == user.id
    assert audit.details["username"] == "auditme"
    assert audit.details["email"] == "auditme@test.example"
    assert audit.details["is_first_user"] is False
