"""Phase 10.2 W-FIX-A — refresh / logout / logout-all token-rotation tests.

Per docs/test_depth_audit_2026-05.md (Class A):
  * test_refresh_rotates_token — old token revoked, new token issued.
  * test_refresh_revoked_token_returns_401
  * test_refresh_expired_token_returns_401
  * test_logout_revokes_refresh_token_and_audits
  * test_logout_all_revokes_all_active_tokens_and_audits
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


_PASSWORD = "demo1234"
_DUMMY_HASH = auth_utils.hash_password(_PASSWORD)


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


def _make_refresh_token(
    db, user: models.User, *, token: str, revoked: bool = False, expires_in_days: int = 7,
) -> models.RefreshToken:
    rt = models.RefreshToken(
        user_id=user.id,
        token=token,
        expires_at=_now() + timedelta(days=expires_in_days),
        revoked_at=_now() if revoked else None,
    )
    db.add(rt)
    db.flush()
    return rt


def _auth(user: models.User) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


# ---------------------------------------------------------------------------
# /refresh
# ---------------------------------------------------------------------------

def test_refresh_rotates_token(client, test_db):
    """Phase 10.2 audit: Class A, POST /api/auth/refresh, token-rotation
    side-effect. Calling refresh once → old token gets revoked_at set, a
    new RefreshToken row is created and returned."""
    user = _make_user(test_db, "rotator")
    rt = _make_refresh_token(test_db, user, token="orig-token-abc")
    test_db.commit()

    resp = client.post(
        "/api/auth/refresh",
        json={"refresh_token": "orig-token-abc"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    new_refresh = body["refresh_token"]
    assert new_refresh and new_refresh != "orig-token-abc"

    test_db.expire_all()
    test_db.refresh(rt)
    assert rt.revoked_at is not None

    # New token row exists.
    new_rt = test_db.query(models.RefreshToken).filter(
        models.RefreshToken.token == new_refresh,
    ).first()
    assert new_rt is not None
    assert new_rt.revoked_at is None
    assert new_rt.user_id == user.id


def test_refresh_revoked_token_returns_401(client, test_db):
    """Phase 10.2 audit: Class A, POST /api/auth/refresh — already-revoked
    token cannot be reused."""
    user = _make_user(test_db, "revoked_rt")
    _make_refresh_token(test_db, user, token="dead-token", revoked=True)
    test_db.commit()

    resp = client.post(
        "/api/auth/refresh",
        json={"refresh_token": "dead-token"},
    )
    assert resp.status_code == 401, resp.text


def test_refresh_expired_token_returns_401(client, test_db):
    """Phase 10.2 audit: Class A, POST /api/auth/refresh — expired token
    cannot be reused."""
    user = _make_user(test_db, "expired_rt")
    _make_refresh_token(test_db, user, token="stale-token", expires_in_days=-1)
    test_db.commit()

    resp = client.post(
        "/api/auth/refresh",
        json={"refresh_token": "stale-token"},
    )
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# /logout
# ---------------------------------------------------------------------------

def test_logout_revokes_refresh_token_and_audits(client, test_db):
    """Phase 10.2 audit: Class A, POST /api/auth/logout, token-revocation
    + audit emission."""
    user = _make_user(test_db, "logout_user")
    rt = _make_refresh_token(test_db, user, token="active-rt")
    test_db.commit()

    resp = client.post(
        "/api/auth/logout",
        json={"refresh_token": "active-rt"},
        headers=_auth(user),
    )
    assert resp.status_code == 200, resp.text

    test_db.expire_all()
    test_db.refresh(rt)
    assert rt.revoked_at is not None

    audit = test_db.query(models.AuditLog).filter(
        models.AuditLog.action == "user.logout",
        models.AuditLog.target_id == user.id,
    ).first()
    assert audit is not None
    assert audit.actor_id == user.id


def test_logout_all_revokes_all_active_tokens_and_audits(client, test_db):
    """Phase 10.2 audit: Class A, POST /api/auth/logout-all — every active
    RefreshToken for the caller is revoked + audit row emitted with the
    revoked-count detail."""
    user = _make_user(test_db, "logout_all_user")
    rts = [
        _make_refresh_token(test_db, user, token=f"rt-{i}")
        for i in range(3)
    ]
    # And one already-revoked token: should not be re-revoked + not counted.
    _make_refresh_token(test_db, user, token="rt-already-dead", revoked=True)
    test_db.commit()

    resp = client.post(
        "/api/auth/logout-all",
        headers=_auth(user),
    )
    assert resp.status_code == 200, resp.text

    test_db.expire_all()
    for rt in rts:
        test_db.refresh(rt)
        assert rt.revoked_at is not None

    audit = test_db.query(models.AuditLog).filter(
        models.AuditLog.action == "user.logout_all",
        models.AuditLog.target_id == user.id,
    ).first()
    assert audit is not None
    assert audit.details["tokens_revoked"] == 3
