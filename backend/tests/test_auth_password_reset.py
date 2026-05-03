"""Phase 10.2 W-FIX-A — POST /api/auth/forgot-password + reset-password.

Per docs/test_depth_audit_2026-05.md (Class A):
  * test_forgot_password_creates_reset_and_sends_email_for_known_email —
    PasswordReset row + send_password_reset_email mock + audit emission.
  * test_forgot_password_returns_same_message_for_unknown_email_no_send —
    account-enumeration safety: 200 + same message + NO email send.
  * test_reset_password_rotates_password_and_revokes_tokens_and_audits —
    new password hash works, all RefreshTokens revoked, audit emitted.
  * test_reset_password_with_bad_token_returns_400.
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


_OLD_PASSWORD = "demo1234"
_NEW_PASSWORD = "shinyNewPass!"
_DUMMY_HASH = auth_utils.hash_password(_OLD_PASSWORD)


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
    """Forgot-password is decorated with @limiter.limit("3/hour"); reset
    its slowapi storage between tests so the limiter doesn't carry state
    across this file's tests (and from sibling tests that hit the same
    endpoint with the testclient's shared remote address)."""
    auth_route.limiter.reset()
    yield
    auth_route.limiter.reset()


@pytest.fixture
def captured_password_reset_calls(monkeypatch):
    calls: list[tuple] = []

    async def _fake_send(email, token, base_url):
        calls.append((email, token, base_url))
        return True

    monkeypatch.setattr(auth_route, "send_password_reset_email", _fake_send)
    return calls


def _make_user(db, username: str) -> models.User:
    u = models.User(
        username=username,
        display_name=username.title(),
        password_hash=_DUMMY_HASH,
        email=f"{username}@test.example",
        email_verified=True,
    )
    db.add(u)
    db.flush()
    return u


# ---------------------------------------------------------------------------
# /forgot-password
# ---------------------------------------------------------------------------

def test_forgot_password_creates_reset_and_sends_email_for_known_email(
    client, test_db, captured_password_reset_calls,
):
    """Phase 10.2 audit: Class A, POST /api/auth/forgot-password — known
    email → PasswordReset row + send_password_reset_email called + audit."""
    user = _make_user(test_db, "forgetful")
    test_db.commit()

    resp = client.post(
        "/api/auth/forgot-password",
        json={"email": user.email},
    )
    assert resp.status_code == 200, resp.text

    pr = test_db.query(models.PasswordReset).filter(
        models.PasswordReset.user_id == user.id,
    ).first()
    assert pr is not None
    assert pr.used_at is None

    assert len(captured_password_reset_calls) == 1
    email_arg, token_arg, _ = captured_password_reset_calls[0]
    assert email_arg == user.email
    assert token_arg == pr.token

    audit = test_db.query(models.AuditLog).filter(
        models.AuditLog.action == "user.password_reset_requested",
        models.AuditLog.target_id == user.id,
    ).first()
    assert audit is not None
    assert audit.details["email"] == user.email


def test_forgot_password_returns_same_message_for_unknown_email_no_send(
    client, test_db, captured_password_reset_calls,
):
    """Phase 10.2 audit: Class A, POST /api/auth/forgot-password — unknown
    email returns the same success message (no enumeration leak) and does
    NOT send any email."""
    # No user exists.
    resp = client.post(
        "/api/auth/forgot-password",
        json={"email": "nobody@nowhere.example"},
    )
    assert resp.status_code == 200, resp.text
    assert "if that email is registered" in resp.json()["message"].lower()

    assert captured_password_reset_calls == []

    # No PasswordReset row was created.
    assert test_db.query(models.PasswordReset).count() == 0


# ---------------------------------------------------------------------------
# /reset-password
# ---------------------------------------------------------------------------

def test_reset_password_rotates_password_and_revokes_tokens_and_audits(
    client, test_db,
):
    """Phase 10.2 audit: Class A, POST /api/auth/reset-password — verifies
    (a) password hash changes (new password works), (b) all refresh tokens
    revoked, (c) reset row marked used, (d) audit emitted."""
    user = _make_user(test_db, "resetter")
    # Pre-existing refresh tokens that should all be revoked on reset.
    rts = []
    for i in range(2):
        rt = models.RefreshToken(
            user_id=user.id,
            token=f"pre-{i}",
            expires_at=_now() + timedelta(days=7),
        )
        test_db.add(rt)
        rts.append(rt)
    pr = models.PasswordReset(
        user_id=user.id,
        token="reset-token-xyz",
        expires_at=_now() + timedelta(hours=1),
    )
    test_db.add(pr)
    test_db.commit()

    resp = client.post(
        "/api/auth/reset-password",
        json={"token": "reset-token-xyz", "new_password": _NEW_PASSWORD},
    )
    assert resp.status_code == 200, resp.text

    test_db.expire_all()
    test_db.refresh(user)
    test_db.refresh(pr)
    # New password works.
    assert auth_utils.verify_password(_NEW_PASSWORD, user.password_hash)
    # Old password no longer works.
    assert not auth_utils.verify_password(_OLD_PASSWORD, user.password_hash)
    # Reset row marked used.
    assert pr.used_at is not None
    # All refresh tokens revoked.
    for rt in rts:
        test_db.refresh(rt)
        assert rt.revoked_at is not None

    audit = test_db.query(models.AuditLog).filter(
        models.AuditLog.action == "user.password_reset_completed",
        models.AuditLog.target_id == user.id,
    ).first()
    assert audit is not None


def test_reset_password_with_bad_token_returns_400(client, test_db):
    """Phase 10.2 audit: Class A, POST /api/auth/reset-password — bad/
    unknown token returns 400 with no side effect."""
    user = _make_user(test_db, "noreset")
    test_db.commit()
    original_hash = user.password_hash

    resp = client.post(
        "/api/auth/reset-password",
        json={"token": "no-such-token", "new_password": _NEW_PASSWORD},
    )
    assert resp.status_code == 400, resp.text

    test_db.refresh(user)
    assert user.password_hash == original_hash
