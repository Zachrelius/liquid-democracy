"""
Tests for POST /api/auth/verify-email (Fix 2).

Covers:
  - Happy path: register -> get token from DB -> verify-email -> confirm email_verified=True
  - Invalid token -> 400
  - Expired token -> 400
  - Already-verified token -> 400
"""

import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from database import Base, get_db
import models
import auth as auth_utils
from main import app


_DUMMY_HASH = auth_utils.hash_password("demo1234")


@pytest.fixture(scope="function")
def test_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False)
    session = TestingSessionLocal()
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


def _create_user(db: Session, username: str, email_verified: bool = False) -> models.User:
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


def _create_verification(
    db: Session,
    user: models.User,
    token: str = "test-token-123",
    hours_until_expiry: int = 24,
    verified: bool = False,
) -> models.EmailVerification:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    ev = models.EmailVerification(
        user_id=user.id,
        email=user.email,
        token=token,
        expires_at=now + timedelta(hours=hours_until_expiry),
    )
    if verified:
        ev.verified_at = now
    db.add(ev)
    db.flush()
    return ev


def test_verify_email_happy_path(client, test_db):
    """Register -> get token -> verify -> email_verified becomes True."""
    user = _create_user(test_db, "verifyuser")
    ev = _create_verification(test_db, user, token="valid-token-abc")
    test_db.commit()

    assert user.email_verified is False

    resp = client.post("/api/auth/verify-email", json={"token": "valid-token-abc"})
    assert resp.status_code == 200
    assert resp.json()["message"] == "Email verified successfully"

    test_db.refresh(user)
    assert user.email_verified is True

    test_db.refresh(ev)
    assert ev.verified_at is not None


def test_verify_email_invalid_token(client, test_db):
    """Invalid token returns 400."""
    user = _create_user(test_db, "verifyuser2")
    _create_verification(test_db, user, token="real-token")
    test_db.commit()

    resp = client.post("/api/auth/verify-email", json={"token": "bogus-token"})
    assert resp.status_code == 400
    assert "Invalid or expired" in resp.json()["detail"]


def test_verify_email_expired_token(client, test_db):
    """Expired token returns 400."""
    user = _create_user(test_db, "verifyuser3")
    _create_verification(test_db, user, token="expired-token", hours_until_expiry=-1)
    test_db.commit()

    resp = client.post("/api/auth/verify-email", json={"token": "expired-token"})
    assert resp.status_code == 400
    assert "Invalid or expired" in resp.json()["detail"]


def test_verify_email_already_verified(client, test_db):
    """Already-verified token returns 400."""
    user = _create_user(test_db, "verifyuser4")
    _create_verification(test_db, user, token="used-token", verified=True)
    test_db.commit()

    resp = client.post("/api/auth/verify-email", json={"token": "used-token"})
    assert resp.status_code == 400
    assert "Invalid or expired" in resp.json()["detail"]
