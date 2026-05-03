"""Phase 10.2 W-FIX-A — POST /api/auth/login side-effect coverage.

Per docs/test_depth_audit_2026-05.md (Class A, login):
  * test_login_emits_user_login_audit_and_creates_refresh_token — bare
    login (no invitation) must emit user.login audit + create an active
    RefreshToken row.
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


_PASSWORD = "demo1234"
_DUMMY_HASH = auth_utils.hash_password(_PASSWORD)


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


def test_login_emits_user_login_audit_and_creates_refresh_token(
    client, test_db,
):
    """Phase 10.2 audit: Class A, POST /api/auth/login, audit + token
    side-effects (bare-login happy path)."""
    user = _make_user(test_db, "loginuser")
    test_db.commit()

    resp = client.post(
        "/api/auth/login",
        data={"username": "loginuser", "password": _PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"]
    assert body["refresh_token"]

    # Audit row.
    audit = test_db.query(models.AuditLog).filter(
        models.AuditLog.action == "user.login",
        models.AuditLog.target_id == user.id,
    ).first()
    assert audit is not None
    assert audit.actor_id == user.id
    assert audit.details["username"] == "loginuser"

    # Refresh token row exists, not revoked.
    rt = test_db.query(models.RefreshToken).filter(
        models.RefreshToken.user_id == user.id,
    ).first()
    assert rt is not None
    assert rt.revoked_at is None
    # The token returned in the response body must match the persisted row.
    assert rt.token == body["refresh_token"]
