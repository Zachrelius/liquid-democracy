"""Phase 10.2 W-FIX-A — auth-required regression tests for routes/users.py.

Covers the two BUG rows from ``docs/test_depth_audit_2026-05.md``:

  * BUG: ``GET /api/users/{id}`` previously had no auth dependency and
    returned the full ``UserOut`` schema (including ``email``) for any user
    ID a caller could guess. Fix added ``Depends(get_current_user)``.
  * BUG: ``GET /api/users/{id}/delegation-tree`` previously had no auth
    dependency and returned the full delegation neighborhood. Fix added
    ``Depends(get_current_user)`` plus identity-redaction for nodes the
    viewer cannot see (mirrors ``can_see_votes`` rules: self / follower /
    public delegate).
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
from delegation_engine import graph_store
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


@pytest.fixture(autouse=True)
def reset_graph_store():
    """The module-level delegation graph_store is shared across tests; make
    sure we start each test with a clean in-memory graph and clean up after
    so we don't poison sibling test files."""
    graph_store._graphs.clear()
    yield
    graph_store._graphs.clear()


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


def _auth(user: models.User) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _add_delegation(
    db, delegator: models.User, delegate: models.User, topic_id=None,
    *, org_id=None,
) -> models.Delegation:
    """Phase 18: optional org_id (inferred from topic when absent).
    Phase 39 B3 — falls back to the conftest default test org if no
    org_id can be inferred (now-NOT-NULL post-Phase-18b)."""
    if org_id is None and topic_id is not None:
        topic = db.get(models.Topic, topic_id)
        if topic is not None:
            org_id = topic.org_id
    if org_id is None:
        from tests.conftest import _default_test_org_id
        org_id = _default_test_org_id(db)
    d = models.Delegation(
        delegator_id=delegator.id,
        delegate_id=delegate.id,
        org_id=org_id,
        topic_id=topic_id,
        chain_behavior="accept_sub",
    )
    db.add(d)
    db.flush()
    graph_store.add_delegation(delegator.id, delegate.id, topic_id)
    return d


# ---------------------------------------------------------------------------
# BUG 1: GET /api/users/{id} requires auth
# ---------------------------------------------------------------------------

def test_get_user_requires_auth_returns_401_unauthenticated(client, test_db):
    """Phase 10.2 audit: Class B BUG, GET /api/users/{id}, no-auth caller
    must not receive PII (email) — endpoint now requires get_current_user."""
    target = _make_user(test_db, "target_user")
    test_db.commit()

    resp = client.get(f"/api/users/{target.id}")
    assert resp.status_code == 401, resp.text


def test_get_user_authenticated_caller_returns_200(client, test_db):
    """Phase 10.2 audit: Class B BUG, GET /api/users/{id} — authenticated
    caller still gets 200 + UserOut after the auth gate is added."""
    caller = _make_user(test_db, "caller")
    target = _make_user(test_db, "target")
    test_db.commit()

    resp = client.get(f"/api/users/{target.id}", headers=_auth(caller))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == target.id
    assert body["username"] == "target"


def test_get_user_unknown_id_authenticated_returns_404(client, test_db):
    """Phase 10.2 audit: Class B BUG follow-up — auth-passing caller with a
    bogus user_id still hits the 404 branch (post-auth)."""
    caller = _make_user(test_db, "caller")
    test_db.commit()

    resp = client.get(
        "/api/users/00000000-0000-0000-0000-000000000000",
        headers=_auth(caller),
    )
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# BUG 2: GET /api/users/{id}/delegation-tree requires auth + redaction
# ---------------------------------------------------------------------------

def test_delegation_tree_requires_auth(client, test_db):
    """Phase 10.2 audit: Class B BUG, GET /api/users/{id}/delegation-tree
    no-auth caller must not get the delegation neighborhood — endpoint now
    requires get_current_user."""
    target = _make_user(test_db, "target_dt")
    test_db.commit()

    resp = client.get(f"/api/users/{target.id}/delegation-tree")
    assert resp.status_code == 401, resp.text


def test_delegation_tree_self_view_returns_real_identities(client, test_db):
    """Phase 10.2 audit: Class B BUG redaction parity — when the viewer is
    the target (self), every node in the neighborhood is returned with its
    real display_name / username (no anonymization for self)."""
    self_user = _make_user(test_db, "self_user")
    other = _make_user(test_db, "other_node")
    test_db.commit()

    _add_delegation(test_db, self_user, other)
    test_db.commit()

    resp = client.get(
        f"/api/users/{self_user.id}/delegation-tree",
        headers=_auth(self_user),
    )
    assert resp.status_code == 200, resp.text
    nodes = {n["id"]: n for n in resp.json()["nodes"]}
    assert self_user.id in nodes
    assert other.id in nodes
    # Both nodes return real identities to self.
    assert nodes[self_user.id]["display_name"] == "Self_User"
    assert nodes[other.id]["display_name"] == "Other_Node"
    assert nodes[other.id]["username"] == "other_node"


def test_delegation_tree_redacts_identities_per_viewer_relationships(
    client, test_db,
):
    """Phase 10.2 audit: Class B BUG redaction parity — third-party viewer
    sees only identities they're entitled to (self / follower / public
    delegate). All other nodes are anonymized.

    Set-up:
      target — owner of the delegation tree (whose tree we're viewing)
      followed_by_viewer — viewer follows this user, so viewer can see them
      pub_delegate — public delegate, visible to everyone
      stranger — viewer has no relationship; identity must be anonymized
    Viewer is none of the above.
    """
    viewer = _make_user(test_db, "viewer_x")
    target = _make_user(test_db, "target_x")
    followed_by_viewer = _make_user(test_db, "followed_x")
    pub_delegate = _make_user(test_db, "pub_x")
    stranger = _make_user(test_db, "stranger_x")
    # Use distinct topics so each delegation from `target` survives — the
    # graph store collapses multiple outgoing edges per (delegator, topic)
    # tuple to the most-recent one.
    topic_a = models.Topic(name="climate_x", color="#000000")
    topic_b = models.Topic(name="economy_x", color="#000000")
    topic_c = models.Topic(name="health_x", color="#000000")
    test_db.add_all([topic_a, topic_b, topic_c])
    test_db.flush()

    # Public delegate profile for pub_delegate.
    # Phase 37 B3 (2026-05-27): explicit visibility="public" — the model
    # default is "followers_only" which no longer counts as public-delegate
    # for the redaction check (correct per privacy semantics).
    test_db.add(models.DelegateProfile(
        user_id=pub_delegate.id,
        topic_id=topic_a.id,
        bio="",
        visibility="public",
    ))
    # Viewer follows followed_by_viewer.
    # Phase 18: org_id left None — this test exercises account-level
    # privacy semantics, not org-scoping. Phase 39 B3 — synced the
    # ORM declaration to NOT NULL so the fixture now uses the
    # default test org id (the privacy semantics being tested are
    # unaffected by which org the FollowRelationship belongs to).
    from tests.conftest import _default_test_org_id
    test_db.add(models.FollowRelationship(
        follower_id=viewer.id,
        followed_id=followed_by_viewer.id,
        permission_level="view_only",
        org_id=_default_test_org_id(test_db),
    ))
    # Build the target's delegation tree: target delegates to all three on
    # different topics so the graph store keeps all three edges.
    _add_delegation(test_db, target, followed_by_viewer, topic_id=topic_a.id)
    _add_delegation(test_db, target, pub_delegate,       topic_id=topic_b.id)
    _add_delegation(test_db, target, stranger,           topic_id=topic_c.id)
    test_db.commit()

    resp = client.get(
        f"/api/users/{target.id}/delegation-tree",
        headers=_auth(viewer),
    )
    assert resp.status_code == 200, resp.text
    nodes = {n["id"]: n for n in resp.json()["nodes"]}

    # followed_by_viewer: visible.
    assert nodes[followed_by_viewer.id]["display_name"] == "Followed_X"
    assert nodes[followed_by_viewer.id]["username"] == "followed_x"
    # pub_delegate: visible (public delegate).
    assert nodes[pub_delegate.id]["display_name"] == "Pub_X"
    assert nodes[pub_delegate.id]["username"] == "pub_x"
    # stranger: anonymized.
    assert nodes[stranger.id]["display_name"] == "Anonymous user"
    assert nodes[stranger.id]["username"] == "anonymous"
    # target itself: viewer is not target, not following them, not a public
    # delegate — also anonymized.
    assert nodes[target.id]["display_name"] == "Anonymous user"


def test_delegation_tree_unknown_user_authenticated_returns_404(client, test_db):
    """Phase 10.2 audit: Class B BUG follow-up — auth passes; unknown
    user_id hits the 404 branch."""
    caller = _make_user(test_db, "caller_dt")
    test_db.commit()

    resp = client.get(
        "/api/users/00000000-0000-0000-0000-000000000000/delegation-tree",
        headers=_auth(caller),
    )
    assert resp.status_code == 404, resp.text
