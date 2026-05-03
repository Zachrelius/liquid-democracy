"""Phase 10.2 W-FIX-A — POST /api/auth/change-password.

Per docs/test_depth_audit_2026-05.md (Class A, change-password):
  * test_change_password_updates_hash_and_revokes_refresh_tokens — happy
    path: new password works, old password rejected, all refresh tokens
    revoked.
  * test_change_password_rejects_wrong_current — wrong current password
    → 400 with no mutation.
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


def _auth(user: models.User) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def test_change_password_updates_hash_and_revokes_refresh_tokens(
    client, test_db,
):
    """Phase 10.2 audit: Class A, POST /api/auth/change-password —
    verifies password hash actually changes (new works, old rejected) and
    every active RefreshToken for the caller is revoked."""
    user = _make_user(test_db, "changer")
    rts = []
    for i in range(2):
        rt = models.RefreshToken(
            user_id=user.id,
            token=f"pre-cp-{i}",
            expires_at=_now() + timedelta(days=7),
        )
        test_db.add(rt)
        rts.append(rt)
    test_db.commit()

    resp = client.post(
        "/api/auth/change-password",
        json={"current_password": _OLD_PASSWORD, "new_password": _NEW_PASSWORD},
        headers=_auth(user),
    )
    assert resp.status_code == 200, resp.text

    test_db.expire_all()
    test_db.refresh(user)
    assert auth_utils.verify_password(_NEW_PASSWORD, user.password_hash)
    assert not auth_utils.verify_password(_OLD_PASSWORD, user.password_hash)

    for rt in rts:
        test_db.refresh(rt)
        assert rt.revoked_at is not None


def test_change_password_rejects_wrong_current(client, test_db):
    """Phase 10.2 audit: Class A, POST /api/auth/change-password —
    wrong current password → 400 with no mutation. Refresh tokens left
    intact."""
    user = _make_user(test_db, "wrongpw")
    rt = models.RefreshToken(
        user_id=user.id,
        token="should-survive",
        expires_at=_now() + timedelta(days=7),
    )
    test_db.add(rt)
    test_db.commit()
    original_hash = user.password_hash

    resp = client.post(
        "/api/auth/change-password",
        json={"current_password": "wrong-pw", "new_password": _NEW_PASSWORD},
        headers=_auth(user),
    )
    assert resp.status_code == 400, resp.text

    test_db.refresh(user)
    assert user.password_hash == original_hash
    test_db.refresh(rt)
    assert rt.revoked_at is None
