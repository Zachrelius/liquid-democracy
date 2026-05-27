"""Phase 10.2 W-FIX-A — admin endpoint side-effect coverage.

Per docs/test_depth_audit_2026-05.md (Class A admin entries):
  * test_seed_endpoint_403_when_debug_off — POST /api/admin/seed
    debug-gate.
  * test_time_simulation_creates_snapshot_row — POST
    /api/admin/time-simulation writes a VoteSnapshot under debug=True.
  * test_time_simulation_403_when_debug_off — debug gate.
  * test_make_admin_flips_flag — PATCH /api/admin/users/{id}/make-admin
    sets is_admin=True on the target row.
  * test_make_admin_requires_admin_caller — non-admin caller gets 403.
"""
from __future__ import annotations

from datetime import datetime, timezone

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


def _make_user(
    db, username: str, *, is_admin: bool = False,
) -> models.User:
    u = models.User(
        username=username,
        display_name=username.title(),
        password_hash=_DUMMY_HASH,
        email=f"{username}@test.example",
        email_verified=True,
        is_admin=is_admin,
    )
    db.add(u)
    db.flush()
    return u


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


# ---------------------------------------------------------------------------
# /api/admin/seed
# ---------------------------------------------------------------------------

def test_seed_endpoint_403_when_debug_off(client, test_db, monkeypatch):
    """Phase 10.2 audit (updated Phase 37 B4): POST /api/admin/seed — debug
    gate. With settings.debug=False the route returns 403 for an admin
    caller. Phase 37 added admin-auth as an upstream gate, so this test now
    passes admin headers; unauthenticated requests get 401 (see
    test_phase_37_security_hotfix.py)."""
    monkeypatch.setattr(settings, "debug", False)
    admin = _make_user(test_db, "seed_off_admin", is_admin=True)
    test_db.commit()

    resp = client.post(
        "/api/admin/seed",
        json={"scenario": "default"},
        headers=_auth(admin),
    )
    assert resp.status_code == 403, resp.text
    assert "debug mode" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# /api/admin/time-simulation
# ---------------------------------------------------------------------------

def test_time_simulation_creates_snapshot_row(client, test_db, monkeypatch):
    """Phase 10.2 audit: Class A, POST /api/admin/time-simulation — under
    debug=True the route writes a VoteSnapshot row for the proposal."""
    monkeypatch.setattr(settings, "debug", True)
    admin = _make_user(test_db, "platformadmin", is_admin=True)
    proposal = models.Proposal(
        title="Snapshot Me",
        body="",
        author_id=admin.id,
        status="voting",
    )
    test_db.add(proposal)
    test_db.commit()

    sim_time = datetime(2026, 1, 1, 12, 0, 0).replace(tzinfo=None)
    resp = client.post(
        "/api/admin/time-simulation",
        json={"proposal_id": proposal.id, "simulated_time": sim_time.isoformat()},
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text

    snap = test_db.query(models.VoteSnapshot).filter(
        models.VoteSnapshot.proposal_id == proposal.id,
    ).first()
    assert snap is not None


def test_time_simulation_403_when_debug_off(client, test_db, monkeypatch):
    """Phase 10.2 audit: Class A, POST /api/admin/time-simulation — debug
    gate returns 403 even for an admin caller."""
    monkeypatch.setattr(settings, "debug", False)
    admin = _make_user(test_db, "admin_off", is_admin=True)
    proposal = models.Proposal(
        title="No-go", body="", author_id=admin.id, status="voting",
    )
    test_db.add(proposal)
    test_db.commit()

    resp = client.post(
        "/api/admin/time-simulation",
        json={"proposal_id": proposal.id, "simulated_time": _now().isoformat()},
        headers=_auth(admin),
    )
    assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# /api/admin/users/{id}/make-admin
# ---------------------------------------------------------------------------

def test_make_admin_flips_flag(client, test_db):
    """Phase 10.2 audit: Class A, PATCH /api/admin/users/{id}/make-admin —
    target user's is_admin flips from False to True."""
    admin = _make_user(test_db, "promoter", is_admin=True)
    target = _make_user(test_db, "promotee", is_admin=False)
    test_db.commit()

    resp = client.patch(
        f"/api/admin/users/{target.id}/make-admin",
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text

    test_db.refresh(target)
    assert target.is_admin is True


def test_make_admin_requires_admin_caller(client, test_db):
    """Phase 10.2 audit: Class A, PATCH /api/admin/users/{id}/make-admin —
    non-admin caller gets 403 from get_current_admin gate."""
    nonadmin = _make_user(test_db, "regular", is_admin=False)
    target = _make_user(test_db, "victim", is_admin=False)
    test_db.commit()

    resp = client.patch(
        f"/api/admin/users/{target.id}/make-admin",
        headers=_auth(nonadmin),
    )
    assert resp.status_code == 403, resp.text

    test_db.refresh(target)
    assert target.is_admin is False
