"""Phase 80 — public read-only surfaces (Proposals + Delegates).

Phase 57 already covers anonymous (logged-out) reads + anon-cannot-write on
an activity_visibility='public' org. This file adds the Phase 80 guarantees:

  * A LOGGED-IN NON-MEMBER cannot vote / comment / delegate on a public
    org's proposal — and the side effect does NOT happen (no row written).
    This is the security backstop behind the FE read-only mode: even if the
    FE surfaced a control or a non-member crafted a direct API call, the
    backend membership gate holds.
  * A logged-out viewer can browse delegates on a public org (the FE
    Delegates page relies on this endpoint serving non-members).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

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
from role_seed import seed_default_roles_for_org


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


def _make_user(db: Session, username: str) -> models.User:
    u = models.User(
        username=username,
        display_name=username.title(),
        password_hash=hash_password("x"),
        email=f"{username}@test.example",
        email_verified=True,
    )
    db.add(u)
    db.flush()
    return u


def _make_org(db: Session, slug: str, *, activity_visibility: str = "public") -> models.Organization:
    o = models.Organization(
        name=slug.title(), slug=slug, description="", settings={},
        join_policy="open", discoverability="listed",
        activity_visibility=activity_visibility,
    )
    db.add(o)
    db.flush()
    seed_default_roles_for_org(db, o.id)
    return o


def _add_member(db: Session, org, user, role: str = "member"):
    role_row = db.query(models.Role).filter_by(org_id=org.id, system_key=role).first()
    m = models.OrgMembership(
        user_id=user.id, org_id=org.id, role_id=role_row.id, status="active",
    )
    db.add(m)
    db.flush()
    return m


def _make_proposal(db: Session, org, author, *, status: str = "voting"):
    p = models.Proposal(
        title="P", body="Body", author_id=author.id,
        voting_method="binary", status=status, org_id=org.id,
        voting_start=datetime.utcnow() - timedelta(days=1),
        voting_end=datetime.utcnow() + timedelta(days=1),
    )
    db.add(p)
    db.flush()
    return p


class TestNonMemberCannotWriteOnPublicOrg:
    """Logged-in non-member, public org → reads allowed, writes blocked."""

    def test_non_member_cannot_vote(self, client, db_session):
        org = _make_org(db_session, "pub-org")
        author = _make_user(db_session, "author")
        _add_member(db_session, org, author, role="steward")
        outsider = _make_user(db_session, "outsider")
        p = _make_proposal(db_session, org, author)
        db_session.commit()

        r = client.post(
            f"/api/proposals/{p.id}/vote",
            headers=_auth(outsider.id),
            json={"vote_value": "yes"},
        )
        assert r.status_code in (401, 403, 404), r.text
        # Side effect: no vote row for the outsider.
        assert db_session.query(models.Vote).filter_by(
            proposal_id=p.id, user_id=outsider.id,
        ).count() == 0

    def test_non_member_cannot_comment(self, client, db_session):
        org = _make_org(db_session, "pub-org-2")
        author = _make_user(db_session, "author2")
        _add_member(db_session, org, author, role="steward")
        outsider = _make_user(db_session, "outsider2")
        p = _make_proposal(db_session, org, author, status="deliberation")
        db_session.commit()

        r = client.post(
            f"/api/proposals/{p.id}/comments",
            headers=_auth(outsider.id),
            json={"body": "outsider comment"},
        )
        assert r.status_code in (401, 403, 404), r.text
        assert db_session.query(models.Comment).filter_by(
            proposal_id=p.id, author_id=outsider.id,
        ).count() == 0

    def test_non_member_cannot_delegate(self, client, db_session):
        org = _make_org(db_session, "pub-org-3")
        author = _make_user(db_session, "author3")
        _add_member(db_session, org, author, role="steward")
        outsider = _make_user(db_session, "outsider3")
        db_session.commit()

        # Delegation create is a PUT upsert (idempotent per delegator/topic).
        r = client.put(
            f"/api/orgs/{org.slug}/delegations",
            headers=_auth(outsider.id),
            json={"delegate_id": author.id, "topic_id": None},
        )
        # Membership gate (require_org_membership) rejects before any write.
        assert r.status_code in (401, 403, 404, 422), r.text
        assert db_session.query(models.Delegation).filter_by(
            org_id=org.id, delegator_id=outsider.id,
        ).count() == 0


class TestPublicDelegatesBrowse:
    def test_logged_out_can_browse_delegates_on_public_org(self, client, db_session):
        org = _make_org(db_session, "pub-org-4")
        author = _make_user(db_session, "author4")
        _add_member(db_session, org, author, role="steward")
        db_session.commit()

        # No auth header — logged-out browse. The FE Delegates page depends
        # on this returning 200 (empty list is fine; existence not leaked
        # via 404 for a listed org).
        r = client.get(f"/api/orgs/{org.slug}/delegates")
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)
