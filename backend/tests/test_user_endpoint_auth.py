"""Phase 10.2 W-FIX-A — auth-required regression tests for routes/users.py.

Covers the two BUG rows from ``docs/test_depth_audit_2026-05.md``:

  * ``GET /api/users/{id}`` requires auth and returns only a public-safe
    identity schema; full ``UserOut`` is reserved for self endpoints.
  * BUG: ``GET /api/users/{id}/delegation-tree`` previously had no auth
    dependency and returned the full delegation neighborhood. Fix added
    ``Depends(get_current_user)`` plus identity-redaction for nodes the
    viewer cannot see (mirrors ``can_see_votes`` rules: self / follower /
    public delegate).
"""
from __future__ import annotations

from datetime import datetime

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
    """An unrelated authenticated caller gets identity, never private data."""
    caller = _make_user(test_db, "caller")
    target = _make_user(test_db, "target")
    test_db.commit()

    resp = client.get(f"/api/users/{target.id}", headers=_auth(caller))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == target.id
    assert body["username"] == "target"
    assert set(body) == {"id", "username", "display_name", "avatar_url"}
    for private_field in (
        "email", "email_verified", "is_admin", "user_type",
        "delegation_strategy", "default_follow_policy",
        "verification_state", "verification_jurisdiction",
        "verification_provenance", "verification_updated_at", "dm_disabled",
    ):
        assert private_field not in body


def test_get_me_still_returns_private_self_fields(client, test_db):
    caller = _make_user(test_db, "self_fields")
    caller.verification_jurisdiction = "US-CA"
    test_db.commit()

    resp = client.get("/api/users/me", headers=_auth(caller))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["email"] == caller.email
    assert body["email_verified"] is True
    assert body["verification_jurisdiction"] == "US-CA"


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


def test_public_profile_aggregates_hidden_votes_without_metadata(client, test_db):
    """Anonymous and unrelated viewers learn only the number of redacted
    ballots, never the private proposal ID, title, vote ID, or timestamp."""
    target = _make_user(test_db, "private_voter")
    viewer = _make_user(test_db, "unrelated_viewer")
    follower = _make_user(test_db, "approved_follower")
    proposal = models.Proposal(
        title="Secret contract negotiation",
        body="private",
        author_id=target.id,
        status="voting",
    )
    test_db.add(proposal)
    test_db.flush()
    from tests.conftest import _default_test_org_id
    org_id = _default_test_org_id(test_db)
    topic = models.Topic(
        name="Private bargaining", color="#123456", org_id=org_id,
    )
    followers_topic = models.Topic(
        name="Follower briefing", color="#654321", org_id=org_id,
    )
    public_topic = models.Topic(
        name="Public policy", color="#abcdef", org_id=org_id,
    )
    test_db.add_all([topic, followers_topic, public_topic])
    test_db.flush()
    test_db.add_all([
        models.ProposalTopic(proposal_id=proposal.id, topic_id=topic.id),
        models.DelegateProfile(
            user_id=target.id,
            topic_id=topic.id,
            org_id=org_id,
            visibility="private",
            bio="private profile biography",
        ),
        models.DelegateProfile(
            user_id=target.id,
            topic_id=followers_topic.id,
            org_id=org_id,
            visibility="followers_only",
            bio="followers profile biography",
        ),
        models.DelegateProfile(
            user_id=target.id,
            topic_id=public_topic.id,
            org_id=org_id,
            visibility="public",
            bio="public profile biography",
        ),
        models.FollowRelationship(
            follower_id=follower.id,
            followed_id=target.id,
            org_id=org_id,
            permission_level="view_only",
        ),
    ])
    from tests.conftest import make_org_membership
    make_org_membership(
        test_db, org_id=org_id, user_id=target.id, role="member",
    )
    members_only_proposal = models.Proposal(
        title="Members-only public-delegate ballot",
        body="private org activity",
        author_id=target.id,
        org_id=org_id,
        status="voting",
    )
    test_db.add(members_only_proposal)
    test_db.flush()
    test_db.add(models.ProposalTopic(
        proposal_id=members_only_proposal.id,
        topic_id=public_topic.id,
    ))
    members_only_vote = models.Vote(
        proposal_id=members_only_proposal.id,
        user_id=target.id,
        cast_by_id=target.id,
        vote_value="no",
        is_direct=True,
        cast_at=datetime(2026, 7, 12, 13, 45, 0),
    )
    test_db.add(members_only_vote)
    vote = models.Vote(
        proposal_id=proposal.id,
        user_id=target.id,
        cast_by_id=target.id,
        vote_value="yes",
        is_direct=True,
        cast_at=datetime(2026, 7, 12, 12, 34, 56),
    )
    test_db.add(vote)
    test_db.commit()

    for headers in (None, _auth(viewer)):
        resp = client.get(f"/api/users/{target.id}/profile", headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["votes"] == []
        assert body["hidden_vote_count"] == 2
        assert [p["topic_id"] for p in body["delegate_profiles"]] == [
            public_topic.id,
        ]
        encoded = resp.text
        assert proposal.id not in encoded
        assert proposal.title not in encoded
        assert members_only_proposal.id not in encoded
        assert members_only_proposal.title not in encoded
        assert members_only_vote.id not in encoded
        assert vote.id not in encoded
        assert "2026-07-12T12:34:56" not in encoded
        assert "private profile biography" not in encoded
        assert "followers profile biography" not in encoded

        votes_resp = client.get(f"/api/users/{target.id}/votes", headers=headers)
        assert votes_resp.status_code == 200, votes_resp.text
        assert votes_resp.json() == []
        assert proposal.id not in votes_resp.text
        assert members_only_proposal.id not in votes_resp.text

    followed = client.get(
        f"/api/users/{target.id}/profile", headers=_auth(follower),
    )
    assert followed.status_code == 200, followed.text
    followed_topic_ids = {
        p["topic_id"] for p in followed.json()["delegate_profiles"]
    }
    assert followed_topic_ids == {followers_topic.id, public_topic.id}
    assert "private profile biography" not in followed.text

    # The owner retains the normal visible self history.
    own = client.get(
        f"/api/users/{target.id}/profile", headers=_auth(target),
    )
    assert own.status_code == 200, own.text
    assert own.json()["hidden_vote_count"] == 0
    assert {v["proposal_id"] for v in own.json()["votes"]} == {
        proposal.id, members_only_proposal.id,
    }
    assert {p["topic_id"] for p in own.json()["delegate_profiles"]} == {
        topic.id, followers_topic.id, public_topic.id,
    }


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
