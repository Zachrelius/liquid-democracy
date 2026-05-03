"""Phase 10.1 W1 — cross-scope vote leak fix tests.

Pilot bug: a parent-org member who is NOT a member of any sub-org delegates
her global vote to another user; that user votes on a sub-org-scoped
proposal he is eligible for; her ballot was being counted in the tally even
though she had no eligibility on that proposal.

Tracing the code showed the bug surface was broader than just sub-org scope:

  * routes/votes.py::cast_vote had no eligibility check at all, so cross-org
    users could vote on any proposal whose ID they knew.
  * delegation_engine.compute_tally's else branch iterated every user in the
    platform for non-sub-org proposals, leaking cross-org votes into any
    org-scoped tally.
  * routes/proposals.get_vote_graph's all_users query was unscoped, so the
    graph showed cross-scope users as nodes and total_eligible was inflated.
  * delegation_engine._build_context loaded direct_ballots without an
    eligibility filter, so a non-eligible user's pre-fix Vote row could leak
    through delegation chain resolution as the chain's direct_ballot.

This test file covers all four call sites with eight tests:

  1. Sub-org non-member POSTing a vote on a sub-org proposal -> 403
  2. Cross-org non-member POSTing a vote on a parent-org proposal -> 403
  3. Sub-org member POSTing a vote on their sub-org proposal -> 200
  4. Parent-org member POSTing a vote on a parent-org-wide proposal -> 200
  5. Tally excludes a pre-seeded direct vote from a non-eligible user
  6. Tally excludes a delegated chain that lands on a non-eligible delegator
     (the canonical Z's-wife scenario)
  7. Cross-org tally excludes a pre-seeded vote from a different-org user
  8. Vote-graph total_eligible matches the eligible set, not all-users count
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
from delegation_engine import engine as delegation_engine
from main import app
from tests.conftest import make_org_membership


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


def _make_org(db, slug: str, parent_org_id: str | None = None) -> models.Organization:
    org = models.Organization(
        name=slug,
        slug=slug,
        description="",
        parent_org_id=parent_org_id,
        join_policy="approval_required",
        settings={},
    )
    db.add(org)
    db.flush()
    return org


def _join_org(db, user, org, role: str = "member"):
    m = make_org_membership(
        db,
        user_id=user.id, org_id=org.id, role=role, status="active",
    )
    return m


def _join_sub_org(db, user, sub_org, role: str = "member"):
    m = models.SubOrgMembership(
        user_id=user.id, sub_org_id=sub_org.id, role=role, status="active",
    )
    db.add(m)
    db.flush()
    return m


def _make_proposal(
    db, author, *, org_id: str | None = None, sub_org_id: str | None = None,
    status: str = "voting", voting_method: str = "binary",
) -> models.Proposal:
    p = models.Proposal(
        title="Test Proposal",
        body="",
        author_id=author.id,
        status=status,
        org_id=org_id,
        sub_org_id=sub_org_id,
        voting_method=voting_method,
    )
    db.add(p)
    db.flush()
    return p


def _auth(user: models.User) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _build_persona_world(db):
    """Set up the canonical persona world used across these tests:

      * parent_org with two sub-orgs (sub_a, sub_b)
      * other_org (totally separate from parent_org)
      * alice: parent_org member only (no sub-org)
      * bob: parent_org + sub_a member
      * carol: parent_org + sub_b member
      * dave: other_org member only
    """
    parent = _make_org(db, "gamenights")
    sub_a = _make_org(db, "sub-a", parent_org_id=parent.id)
    sub_b = _make_org(db, "sub-b", parent_org_id=parent.id)
    other = _make_org(db, "other-org")

    alice = _make_user(db, "alice")
    bob = _make_user(db, "bob")
    carol = _make_user(db, "carol")
    dave = _make_user(db, "dave")

    _join_org(db, alice, parent)
    _join_org(db, bob, parent)
    _join_org(db, carol, parent)
    _join_sub_org(db, bob, sub_a)
    _join_sub_org(db, carol, sub_b)
    _join_org(db, dave, other)
    db.commit()

    return {
        "parent": parent, "sub_a": sub_a, "sub_b": sub_b, "other": other,
        "alice": alice, "bob": bob, "carol": carol, "dave": dave,
    }


# ===========================================================================
# 1a/1f — cast_vote eligibility gate
# ===========================================================================

def test_cast_vote_sub_org_non_member_403(client, test_db):
    """alice is a parent-org member but NOT a sub-org-A member; her POST
    on a sub-org-A proposal must be rejected with 403 'not eligible'.

    This is the upstream cause that lets non-eligible users' votes enter
    the system at all. Pre-fix the row would persist; post-fix the gate
    blocks it before any side effect.
    """
    w = _build_persona_world(test_db)
    proposal = _make_proposal(
        test_db, w["bob"], org_id=w["parent"].id, sub_org_id=w["sub_a"].id,
    )
    test_db.commit()

    resp = client.post(
        f"/api/proposals/{proposal.id}/vote",
        headers=_auth(w["alice"]),
        json={"vote_value": "yes"},
    )
    assert resp.status_code == 403, resp.text
    assert "not eligible" in resp.json()["detail"].lower()
    # Confirm no Vote row was created.
    rows = test_db.query(models.Vote).filter(
        models.Vote.proposal_id == proposal.id,
        models.Vote.user_id == w["alice"].id,
    ).all()
    assert rows == []


def test_cast_vote_cross_org_non_member_403(client, test_db):
    """dave belongs to a totally different org; his POST on the parent
    org's proposal must be 403'd. This is the cross-org leak case Z
    flagged once we audited the call sites broadly.
    """
    w = _build_persona_world(test_db)
    proposal = _make_proposal(
        test_db, w["alice"], org_id=w["parent"].id, sub_org_id=None,
    )
    test_db.commit()

    resp = client.post(
        f"/api/proposals/{proposal.id}/vote",
        headers=_auth(w["dave"]),
        json={"vote_value": "yes"},
    )
    assert resp.status_code == 403, resp.text
    assert "not eligible" in resp.json()["detail"].lower()


def test_cast_vote_sub_org_member_200(client, test_db):
    """bob IS a sub-org-A member; his vote on a sub-org-A proposal
    succeeds and the row persists. Sanity check that the gate doesn't
    over-restrict legitimate voters."""
    w = _build_persona_world(test_db)
    proposal = _make_proposal(
        test_db, w["bob"], org_id=w["parent"].id, sub_org_id=w["sub_a"].id,
    )
    test_db.commit()

    resp = client.post(
        f"/api/proposals/{proposal.id}/vote",
        headers=_auth(w["bob"]),
        json={"vote_value": "yes"},
    )
    assert resp.status_code == 200, resp.text
    persisted = test_db.query(models.Vote).filter(
        models.Vote.proposal_id == proposal.id,
        models.Vote.user_id == w["bob"].id,
    ).first()
    assert persisted is not None
    assert persisted.vote_value == "yes"
    assert persisted.is_direct is True


def test_cast_vote_parent_org_member_200(client, test_db):
    """alice is a parent-org member; her vote on a parent-org-wide
    proposal (sub_org_id IS NULL) succeeds. Mirrors test_3 for the
    parent-org-scope branch of eligible_voter_ids_for_proposal."""
    w = _build_persona_world(test_db)
    proposal = _make_proposal(
        test_db, w["alice"], org_id=w["parent"].id, sub_org_id=None,
    )
    test_db.commit()

    resp = client.post(
        f"/api/proposals/{proposal.id}/vote",
        headers=_auth(w["alice"]),
        json={"vote_value": "yes"},
    )
    assert resp.status_code == 200, resp.text


# ===========================================================================
# 1b — compute_tally scope-aware
# ===========================================================================

def test_tally_excludes_non_member_direct_vote(test_db):
    """Pre-seed a Vote row for dave (other-org) on a sub-org-A proposal,
    simulating a vote cast pre-fix. After the scope-aware tally lands,
    dave's vote must NOT appear in the count.

    This is the load-bearing assertion: existing pre-fix data stays in
    the DB but stops contributing to tallies.
    """
    w = _build_persona_world(test_db)
    proposal = _make_proposal(
        test_db, w["bob"], org_id=w["parent"].id, sub_org_id=w["sub_a"].id,
    )
    # Direct-INSERT dave's vote (bypassing the cast_vote endpoint, which
    # would now reject him). Simulates a pre-fix row.
    test_db.add(models.Vote(
        proposal_id=proposal.id,
        user_id=w["dave"].id,
        vote_value="yes",
        is_direct=True,
        cast_by_id=w["dave"].id,
    ))
    # bob casts a legitimate yes vote so the tally has at least one count.
    test_db.add(models.Vote(
        proposal_id=proposal.id,
        user_id=w["bob"].id,
        vote_value="yes",
        is_direct=True,
        cast_by_id=w["bob"].id,
    ))
    test_db.commit()

    tally = delegation_engine.compute_tally(proposal, test_db)
    # bob is the only eligible (sub_a) voter, and he voted yes.
    assert tally.yes == 1
    assert tally.no == 0
    assert tally.abstain == 0
    # total_eligible reflects sub-org-A membership (just bob), NOT the 4
    # users in the platform.
    assert tally.total_eligible == 1


def test_tally_excludes_non_member_delegated_chain(test_db):
    """The canonical Z's-wife scenario. alice is parent-org-only (NOT a
    sub-org-A member). She delegates globally to bob. bob votes yes on a
    sub-org-A proposal he is eligible for. Post-fix, the tally must
    count bob's vote ONCE — alice must not be counted via her delegation
    to bob, because she has no eligibility on this proposal.

    Pre-fix the delegation chain resolved alice's vote to bob's, and
    the all-users tally counted her. Post-fix the eligible set excludes
    alice, so resolve_vote_pure is never even called for her on this
    proposal.
    """
    from delegation_engine import graph_store

    w = _build_persona_world(test_db)
    proposal = _make_proposal(
        test_db, w["bob"], org_id=w["parent"].id, sub_org_id=w["sub_a"].id,
    )
    # alice global delegation to bob.
    delegation = models.Delegation(
        delegator_id=w["alice"].id,
        delegate_id=w["bob"].id,
        topic_id=None,
        chain_behavior="accept_sub",
    )
    test_db.add(delegation)
    test_db.flush()
    graph_store.add_delegation(w["alice"].id, w["bob"].id, None)

    # bob votes yes directly.
    test_db.add(models.Vote(
        proposal_id=proposal.id,
        user_id=w["bob"].id,
        vote_value="yes",
        is_direct=True,
        cast_by_id=w["bob"].id,
    ))
    test_db.commit()

    try:
        tally = delegation_engine.compute_tally(proposal, test_db)
        assert tally.yes == 1, (
            "Expected ONLY bob's direct vote to count. If alice's delegation "
            "to bob added a second yes via the chain, the cross-scope leak is "
            "still open."
        )
        assert tally.no == 0
        assert tally.total_eligible == 1
    finally:
        # Clean up the in-memory graph store so it doesn't bleed into other
        # tests in the same process.
        graph_store.remove_delegation(w["alice"].id, None)


def test_tally_cross_org_excludes_non_member(test_db):
    """dave is a member of a totally different org. He has a pre-seeded
    vote on the parent_org's parent-org-wide proposal. Post-fix tally
    excludes him because parent_org's eligible set is its OrgMembership
    rows, not the entire user table."""
    w = _build_persona_world(test_db)
    proposal = _make_proposal(
        test_db, w["alice"], org_id=w["parent"].id, sub_org_id=None,
    )
    test_db.add(models.Vote(
        proposal_id=proposal.id,
        user_id=w["dave"].id,
        vote_value="yes",
        is_direct=True,
        cast_by_id=w["dave"].id,
    ))
    test_db.add(models.Vote(
        proposal_id=proposal.id,
        user_id=w["alice"].id,
        vote_value="no",
        is_direct=True,
        cast_by_id=w["alice"].id,
    ))
    test_db.commit()

    tally = delegation_engine.compute_tally(proposal, test_db)
    # Only parent-org members count: alice, bob, carol (3 eligible).
    # Only alice voted (no). dave's pre-seed must NOT count for yes.
    assert tally.no == 1
    assert tally.yes == 0
    assert tally.total_eligible == 3


# ===========================================================================
# 1c — vote-graph total_eligible
# ===========================================================================

def test_vote_graph_total_eligible_matches_eligible_set(client, test_db):
    """Sub-org-A has only one member (bob). The platform has many users
    (we add 17 extras to push the user count well past the eligible set).
    GET vote-graph for a sub-org-A proposal must report total_eligible == 1,
    not the full user count.

    Pre-fix all_users = db.query(User).all() and total_eligible was the
    entire DB user count, so the graph visually inflated to show every
    user as a potential voter.
    """
    w = _build_persona_world(test_db)
    # Pad the platform with extra users who have no relationship to the
    # parent org.
    for i in range(17):
        u = _make_user(test_db, f"padding{i}")
        # Some live in other_org for variety.
        if i % 3 == 0:
            _join_org(test_db, u, w["other"])
    test_db.commit()

    # Sanity: there are at least 21 users on the platform now.
    total_users = test_db.query(models.User).count()
    assert total_users >= 21

    proposal = _make_proposal(
        test_db, w["bob"], org_id=w["parent"].id, sub_org_id=w["sub_a"].id,
    )
    test_db.commit()

    resp = client.get(
        f"/api/proposals/{proposal.id}/vote-graph",
        headers=_auth(w["bob"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Sub-org-A has exactly one member (bob).
    assert body["total_eligible"] == 1
    assert body["clusters"]["total_eligible"] == 1
    # And the nodes list should not contain padding users.
    node_ids = {n["id"] for n in body["nodes"]}
    assert node_ids == {w["bob"].id}
