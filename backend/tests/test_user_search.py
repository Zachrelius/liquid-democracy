"""Phase 9.9 W1 — org-scoped delegate search tests.

Covers the new ``org_slug`` query parameter on ``GET /api/users/search``:

  * Filtering: caller is in two orgs, searches with org_slug=A, sees only A
    members (not B members).
  * Authorization: caller is not in org B, calls with org_slug=B, gets 403
    (defense in depth — search must not be a way to enumerate other orgs'
    membership).
  * Backward compat: omitting org_slug returns the unscoped result set
    (with self-exclusion still applied).
  * Composition with ``topic_id``: when both are present, results are users
    who are active members of the org AND have an active public delegate
    profile for that topic.
  * Status filter: members with status='suspended' don't appear in the
    org-scoped result.
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


_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _make_org(db, name: str, slug: str) -> models.Organization:
    org = models.Organization(
        name=name,
        slug=slug,
        description="",
        join_policy="approval_required",
    )
    db.add(org)
    db.flush()
    return org


def _join(db, user: models.User, org: models.Organization, status: str = "active") -> models.OrgMembership:
    m = models.OrgMembership(
        user_id=user.id,
        org_id=org.id,
        role="member",
        status=status,
    )
    db.add(m)
    db.flush()
    return m


def _auth(user: models.User) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_search_filters_by_org_slug(client, test_db):
    """Caller is an active member of both A and B; passing org_slug=A
    yields only A members and never any B-only member."""
    caller = _make_user(test_db, "caller")
    a_member = _make_user(test_db, "alice_a")
    b_member = _make_user(test_db, "bob_b")
    both_orgs = _make_user(test_db, "carol_both")

    org_a = _make_org(test_db, "Org A", "org-a")
    org_b = _make_org(test_db, "Org B", "org-b")

    _join(test_db, caller, org_a)
    _join(test_db, caller, org_b)
    _join(test_db, a_member, org_a)
    _join(test_db, b_member, org_b)
    _join(test_db, both_orgs, org_a)
    _join(test_db, both_orgs, org_b)

    test_db.commit()

    resp = client.get("/api/users/search?org_slug=org-a", headers=_auth(caller))
    assert resp.status_code == 200, resp.text
    ids = {u["id"] for u in resp.json()}

    # A-members appear (a_member, both_orgs); caller excluded; B-only
    # member excluded.
    assert a_member.id in ids
    assert both_orgs.id in ids
    assert caller.id not in ids
    assert b_member.id not in ids


def test_search_org_slug_unauthorized(client, test_db):
    """Caller is not in org B; passing org_slug=org-b returns 403."""
    caller = _make_user(test_db, "outsider")
    insider = _make_user(test_db, "insider")
    org_b = _make_org(test_db, "Org B", "org-b")
    _join(test_db, insider, org_b)
    test_db.commit()

    resp = client.get("/api/users/search?org_slug=org-b", headers=_auth(caller))
    assert resp.status_code == 403, resp.text
    detail = resp.json().get("detail", "")
    assert "not a member" in detail.lower()


def test_search_no_org_slug_returns_all(client, test_db):
    """Backward compat: omitting org_slug returns all users, with self
    excluded. (This is the legacy behavior the bug is being fixed
    against — keeping it intact for non-org-scoped callers.)"""
    caller = _make_user(test_db, "caller2")
    other_a = _make_user(test_db, "other_a")
    other_b = _make_user(test_db, "other_b")
    org_a = _make_org(test_db, "Org A", "org-a-2")
    org_b = _make_org(test_db, "Org B", "org-b-2")
    # Members live in different orgs to prove unscoped search ignores
    # membership.
    _join(test_db, other_a, org_a)
    _join(test_db, other_b, org_b)
    test_db.commit()

    resp = client.get("/api/users/search", headers=_auth(caller))
    assert resp.status_code == 200, resp.text
    ids = {u["id"] for u in resp.json()}
    assert other_a.id in ids
    assert other_b.id in ids
    assert caller.id not in ids


def test_search_org_and_topic_compose(client, test_db):
    """org_slug + topic_id together: results are users who are active
    members of the org AND have an active public delegate profile for the
    topic, with both conditions composed via the same org boundary."""
    caller = _make_user(test_db, "caller3")
    a_delegate = _make_user(test_db, "a_delegate")
    a_nondelegate = _make_user(test_db, "a_nondelegate")
    b_delegate = _make_user(test_db, "b_delegate")

    org_a = _make_org(test_db, "Org A", "org-a-3")
    org_b = _make_org(test_db, "Org B", "org-b-3")

    _join(test_db, caller, org_a)
    _join(test_db, caller, org_b)
    _join(test_db, a_delegate, org_a)
    _join(test_db, a_nondelegate, org_a)
    _join(test_db, b_delegate, org_b)

    topic = models.Topic(name="climate", description="", color="#000000")
    test_db.add(topic)
    test_db.flush()

    # Public delegate profile in org A for a_delegate (topic, org A scope).
    test_db.add(models.DelegateProfile(
        user_id=a_delegate.id,
        topic_id=topic.id,
        org_id=org_a.id,
        bio="",
        is_active=True,
    ))
    # And b_delegate has a profile in org B for the same topic — should be
    # excluded when org_slug=org-a.
    test_db.add(models.DelegateProfile(
        user_id=b_delegate.id,
        topic_id=topic.id,
        org_id=org_b.id,
        bio="",
        is_active=True,
    ))
    test_db.commit()

    resp = client.get(
        f"/api/users/search?org_slug=org-a-3&topic_id={topic.id}",
        headers=_auth(caller),
    )
    assert resp.status_code == 200, resp.text
    ids = {u["id"] for u in resp.json()}
    # Only a_delegate satisfies both conditions in org A.
    assert ids == {a_delegate.id}


def test_search_excludes_inactive_members(client, test_db):
    """A user with status='suspended' in the searched org doesn't show
    up; a status='active' user does."""
    caller = _make_user(test_db, "caller4")
    active_member = _make_user(test_db, "active_member")
    suspended_member = _make_user(test_db, "suspended_member")
    org_a = _make_org(test_db, "Org A", "org-a-4")
    _join(test_db, caller, org_a)
    _join(test_db, active_member, org_a, status="active")
    _join(test_db, suspended_member, org_a, status="suspended")
    test_db.commit()

    resp = client.get("/api/users/search?org_slug=org-a-4", headers=_auth(caller))
    assert resp.status_code == 200, resp.text
    ids = {u["id"] for u in resp.json()}
    assert active_member.id in ids
    assert suspended_member.id not in ids
