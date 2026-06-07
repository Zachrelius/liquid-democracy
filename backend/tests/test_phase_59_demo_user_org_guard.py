"""Phase 59 Cluster D — demo user org-creation guard.

Asserts:
  * A demo-stamped user (verification_provenance='demo_stub') is
    blocked with 403 from POST /api/orgs.
  * A `backdoor` provenance user is also blocked.
  * A real user (provenance='none' or 'didit') is NOT blocked
    (the load-bearing no-false-positive assert).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from auth import hash_password
from database import Base, get_db
from main import app


@pytest.fixture(scope="function")
def db_session():
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
def client(db_session):
    def _get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _auth(user_id: str) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user_id)}"}


def _make_user(
    db: Session, username: str, *,
    verification_provenance: str = "none",
    verification_state: str = "email_only",
) -> models.User:
    u = models.User(
        username=username,
        display_name=username.title(),
        password_hash=hash_password("x"),
        email=f"{username}@test.example",
        email_verified=True,
        verification_provenance=verification_provenance,
        verification_state=verification_state,
    )
    db.add(u)
    db.flush()
    return u


# ===========================================================================
# Guard fires for demo users
# ===========================================================================


def test_demo_stub_user_blocked_from_creating_org(client, db_session):
    demo_user = _make_user(
        db_session, "demo_persona",
        verification_provenance="demo_stub",
        verification_state="identity_unique",
    )
    db_session.commit()

    r = client.post(
        "/api/orgs",
        headers=_auth(demo_user.id),
        json={
            "name": "Sneaky Org", "slug": "sneaky-org",
            "description": "demo trying to make a real org",
        },
    )
    assert r.status_code == 403, r.text
    assert "demo" in r.text.lower()
    # No org was created.
    assert db_session.query(models.Organization).filter_by(
        slug="sneaky-org",
    ).first() is None


def test_backdoor_user_also_blocked(client, db_session):
    backdoor_user = _make_user(
        db_session, "backdoor_admin",
        verification_provenance="backdoor",
    )
    db_session.commit()

    r = client.post(
        "/api/orgs",
        headers=_auth(backdoor_user.id),
        json={"name": "Backdoor Org", "slug": "backdoor-org"},
    )
    assert r.status_code == 403, r.text


# ===========================================================================
# No false positives (the load-bearing assert)
# ===========================================================================


def test_real_user_can_still_create_org(client, db_session):
    """Provenance 'none' (the default for a fresh registration before
    they verify with a real provider) is NOT a demo identity. They
    can create orgs after email verification per the normal gate
    ladder."""
    real_user = _make_user(
        db_session, "real_person",
        verification_provenance="none",
    )
    db_session.commit()

    r = client.post(
        "/api/orgs",
        headers=_auth(real_user.id),
        json={"name": "Real Org", "slug": "real-org"},
    )
    assert r.status_code == 201, r.text


def test_didit_verified_user_can_create_org(client, db_session):
    """Real didit-verified user should still be able to create orgs."""
    didit_user = _make_user(
        db_session, "didit_person",
        verification_provenance="didit",
        verification_state="identity",
    )
    db_session.commit()

    r = client.post(
        "/api/orgs",
        headers=_auth(didit_user.id),
        json={"name": "Real Didit Org", "slug": "real-didit-org"},
    )
    assert r.status_code == 201, r.text
