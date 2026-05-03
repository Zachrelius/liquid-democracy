"""Phase 10.2 W-FIX-A — POST /api/auth/resend-verification side-effects.

Per docs/test_depth_audit_2026-05.md (Class A, resend-verification):
  * test_resend_creates_token_and_sends_email — new EmailVerification row
    is persisted and send_verification_email is awaited (mocked).
  * test_resend_rate_limited_after_recent_send_returns_429 — a row created
    in the last minute trips the in-route rate-limit check (separate from
    the slowapi limit, which is bypassed in tests).
  * test_resend_short_circuits_when_already_verified — caller whose
    email_verified is True gets a 200 with no new token + no send.
"""
from __future__ import annotations

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
from routes import auth as auth_route


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


@pytest.fixture(autouse=True)
def reset_slowapi_limiter():
    """The @limiter.limit("1/minute") decorator on resend_verification keeps
    in-memory state across tests within the same process. Reset before each
    test so the slowapi gate doesn't fire spuriously and mask the in-route
    DB-driven 429 path we're actually testing."""
    auth_route.limiter.reset()
    yield
    auth_route.limiter.reset()


@pytest.fixture
def captured_email_calls(monkeypatch):
    calls: list[tuple] = []

    async def _fake_send(email, token, base_url):
        calls.append((email, token, base_url))
        return True

    monkeypatch.setattr(auth_route, "send_verification_email", _fake_send)
    return calls


def _make_user(db, username: str, *, email_verified: bool = False) -> models.User:
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


def _auth(user: models.User) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def test_resend_creates_token_and_sends_email(
    client, test_db, captured_email_calls,
):
    """Phase 10.2 audit: Class A, POST /api/auth/resend-verification —
    new EmailVerification row is persisted and send_verification_email is
    awaited with that token."""
    user = _make_user(test_db, "resender", email_verified=False)
    test_db.commit()

    resp = client.post(
        "/api/auth/resend-verification",
        headers=_auth(user),
    )
    assert resp.status_code == 200, resp.text

    ev = test_db.query(models.EmailVerification).filter(
        models.EmailVerification.user_id == user.id,
    ).first()
    assert ev is not None

    assert len(captured_email_calls) == 1
    email_arg, token_arg, _ = captured_email_calls[0]
    assert email_arg == user.email
    assert token_arg == ev.token


def test_resend_rate_limited_after_recent_send_returns_429(
    client, test_db, captured_email_calls,
):
    """Phase 10.2 audit: Class A, POST /api/auth/resend-verification —
    in-route rate-limit (no new token if one was created in the last
    minute) returns 429 and does NOT send another email.

    NB: this exercises the per-DB-row check inside the handler, not the
    slowapi `@limiter.limit` decorator (which uses a separate in-memory
    counter and resets between TestClient calls in some pytest configs).
    """
    user = _make_user(test_db, "ratelimited", email_verified=False)
    # Pre-existing recent token (created right now → within the 1-min window).
    ev_prior = models.EmailVerification(
        user_id=user.id,
        email=user.email,
        token="prior-token",
        expires_at=_now() + timedelta(hours=24),
    )
    test_db.add(ev_prior)
    test_db.commit()

    resp = client.post(
        "/api/auth/resend-verification",
        headers=_auth(user),
    )
    assert resp.status_code == 429, resp.text
    assert captured_email_calls == []

    # No new EmailVerification row was created.
    rows = test_db.query(models.EmailVerification).filter(
        models.EmailVerification.user_id == user.id,
    ).all()
    assert len(rows) == 1


def test_resend_short_circuits_when_already_verified(
    client, test_db, captured_email_calls,
):
    """Phase 10.2 audit: Class A, POST /api/auth/resend-verification —
    early `already verified` short-circuit returns 200 with no new token,
    no email send."""
    user = _make_user(test_db, "verified_user", email_verified=True)
    test_db.commit()

    resp = client.post(
        "/api/auth/resend-verification",
        headers=_auth(user),
    )
    assert resp.status_code == 200, resp.text
    assert "already verified" in resp.json()["message"].lower()

    assert captured_email_calls == []
    assert test_db.query(models.EmailVerification).filter(
        models.EmailVerification.user_id == user.id,
    ).count() == 0
