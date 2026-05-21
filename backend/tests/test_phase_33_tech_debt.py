"""Phase 33 tech-debt refresh tests.

Covers:
- B1: org-aware resolvers raise loud failure when proposal.org_id is set
  but org=None (closes the recurring Phase 32/32.1/32.2 silent-fallback
  pattern at the resolver layer).
- C1: GET /api/users/me returns 200 with current user (was 404 because
  the generic /{user_id} route matched the literal "me" string).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from database import Base, get_db
from main import app
from proposal_engagement_config import (
    resolve_allow_pre_voting_full,
    resolve_allow_write_in_options_full,
    resolve_allow_write_ins_during_voting_full,
    resolve_edit_lockout_fraction,
    resolve_max_write_ins,
    resolve_show_votes_during_deliberation_full,
)


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
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _make_user(db, username):
    user = models.User(
        username=username,
        display_name=username.title(),
        email=f"{username}@example.com",
        email_verified=True,
        password_hash=auth_utils.hash_password("noop"),
    )
    db.add(user)
    db.flush()
    db.commit()
    return user


def _make_org(db, slug="test-org"):
    org = models.Organization(name=slug.title(), slug=slug, settings={})
    db.add(org)
    db.flush()
    return org


def _make_proposal_with_org(db, org):
    user = _make_user(db, "author")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    p = models.Proposal(
        title="T", body="", author_id=user.id, org_id=org.id,
        status="deliberation", voting_method="approval", num_winners=1,
        deliberation_start=now,
        voting_end=now + timedelta(days=3),
        deliberation_days=14.0, voting_days=7.0,
        allow_write_in_options=None,
    )
    db.add(p)
    db.flush()
    return p


# ===========================================================================
# B1 — Resolver loud-failure guard
# ===========================================================================


class TestResolversRaiseOnMissingOrg:
    """Every org-aware resolver must raise when proposal.org_id is set but
    org=None — the caller failed to load the Organization. Was a silent
    platform-default fallback pre-Phase-33."""

    def test_resolve_write_ins_raises_when_org_missing(self, db_session):
        org = _make_org(db_session)
        proposal = _make_proposal_with_org(db_session, org)
        with pytest.raises(ValueError, match="org_id="):
            resolve_allow_write_in_options_full(proposal, None)

    def test_resolve_write_ins_during_voting_raises(self, db_session):
        org = _make_org(db_session)
        proposal = _make_proposal_with_org(db_session, org)
        with pytest.raises(ValueError, match="org_id="):
            resolve_allow_write_ins_during_voting_full(proposal, None)

    def test_resolve_pre_voting_raises(self, db_session):
        org = _make_org(db_session)
        proposal = _make_proposal_with_org(db_session, org)
        with pytest.raises(ValueError, match="org_id="):
            resolve_allow_pre_voting_full(proposal, None)

    def test_resolve_visibility_raises(self, db_session):
        org = _make_org(db_session)
        proposal = _make_proposal_with_org(db_session, org)
        with pytest.raises(ValueError, match="org_id="):
            resolve_show_votes_during_deliberation_full(proposal, None)

    def test_resolve_max_write_ins_raises_on_null_override(self, db_session):
        """resolve_max_write_ins short-circuits on a per-proposal override
        (which doesn't need org); only the org-fallback path triggers the
        guard, so test with override=None."""
        org = _make_org(db_session)
        proposal = _make_proposal_with_org(db_session, org)
        # max_write_ins per-proposal override is None on _make_proposal_with_org
        with pytest.raises(ValueError, match="org_id="):
            resolve_max_write_ins(proposal, None)

    def test_resolve_edit_lockout_raises_on_null_override(self, db_session):
        org = _make_org(db_session)
        proposal = _make_proposal_with_org(db_session, org)
        with pytest.raises(ValueError, match="org_id="):
            resolve_edit_lockout_fraction(proposal, None)

    def test_legacy_no_org_proposal_falls_through_to_default(self, db_session):
        """Proposals with proposal.org_id=None (pre-Phase-4c legacy) must
        still get the platform default — the guard only fires when org_id
        is set but org wasn't loaded."""
        user = _make_user(db_session, "legacy")
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        p = models.Proposal(
            title="T", body="", author_id=user.id, org_id=None,
            status="deliberation", voting_method="binary", num_winners=1,
            deliberation_start=now,
            voting_end=now + timedelta(days=3),
            deliberation_days=14.0, voting_days=7.0,
        )
        db_session.add(p)
        db_session.flush()
        r = resolve_allow_write_in_options_full(p, None)
        assert r.effective is False
        assert r.overridable is True


# ===========================================================================
# C1 — GET /api/users/me
# ===========================================================================


class TestGetUsersMe:
    """Phase 33 C1: explicit GET /api/users/me route before the generic
    /{user_id} catch-all, returning current_user."""

    def test_returns_200_with_valid_jwt(self, db_session, client):
        user = _make_user(db_session, "alice")
        resp = client.post(
            "/api/auth/login",
            data={"username": "alice", "password": "noop"},
        )
        token = resp.json()["access_token"]
        r = client.get(
            "/api/users/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["username"] == "alice"
        assert body["id"] == user.id

    def test_returns_401_without_token(self, client):
        r = client.get("/api/users/me")
        assert r.status_code == 401
