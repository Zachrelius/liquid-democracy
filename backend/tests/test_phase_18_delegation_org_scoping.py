"""Phase 18 — delegation org-scoping test coverage.

Spec: ``phase18_delegation_org_scoping_spec.md`` lines 137-163 (B4 — Tests).

Closes the Phase 4c retrofit gap where the four relationship tables
(``Delegation``, ``DelegationIntent``, ``FollowRelationship``,
``FollowRequest``) lacked ``org_id`` and 15+ read sites couldn't filter
by org. The 17 named tests below assert the new behavior:

  1.  test_network_endpoint_filters_by_org_context
  2.  test_tally_excludes_cross_org_delegators       (load-bearing regression)
  3.  test_global_delegation_is_org_scoped
  4.  test_network_graph_hides_other_orgs_delegations
  5.  test_delegation_intent_carries_org_context
  6.  test_follow_relationship_org_scoping
  7.  test_revoke_dependent_delegations_scoped_to_org
  8.  test_phase_4c_retrofit_completeness            (meta — schema shape)
  9.  test_subor_scoped_global_delegation_via_single_row
  10. test_graph_store_partitioned_by_org
  11. test_admin_delegation_graph_remains_cross_org
  12. test_org_scoped_admin_delegation_graph
  13. test_migration_backfill_topic_scoped_rows
  14. test_migration_backfill_global_single_shared_org
  15. test_migration_backfill_global_multi_shared_org_heuristic
  16. test_migration_backfill_audit_logging
  17. test_phase_8_5_test_comment_updated            (meta — comment text)

Style mirrors test_phase_17_tie_resolution.py: in-memory SQLite, real
``models.Vote`` rows with proper ``ballot`` shape (Phase 17 lesson),
real ``models.OrgMembership`` rows via ``make_org_membership`` so the
eligibility-iteration path in ``compute_tally`` is exercised faithfully.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect as sa_inspect, text as sa_text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from database import Base, get_db
from delegation_engine import (
    DelegationGraphStore,
    eligible_voter_ids_for_proposal,
    graph_store as global_graph_store,
)
from main import app
from role_seed import seed_default_roles_for_org
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
def client(test_db: Session):
    def _get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def fresh_graph_store():
    """Reset the module-level graph_store between tests.

    Phase 18: the singleton is shared across the process so a stale
    delegation from an earlier test could leak into the next test's
    org partition. Reset state at fixture setup AND teardown to keep
    each test hermetic.
    """
    global_graph_store._graphs = {}
    yield global_graph_store
    global_graph_store._graphs = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(
    db: Session, username: str, *,
    default_follow_policy: str = "require_approval",
) -> models.User:
    u = models.User(
        username=username,
        display_name=username.title(),
        password_hash=_DUMMY_HASH,
        email=f"{username}@test.example",
        email_verified=True,
        default_follow_policy=default_follow_policy,
    )
    db.add(u)
    db.flush()
    return u


def _make_org(
    db: Session, slug: str, *,
    parent_org_id: Optional[str] = None,
) -> models.Organization:
    o = models.Organization(
        name=slug.replace("_", " ").title(),
        slug=slug,
        description="",
        settings={},
        parent_org_id=parent_org_id,
    )
    db.add(o)
    db.flush()
    seed_default_roles_for_org(db, o.id)
    return o


def _make_topic(
    db: Session, org: models.Organization, name: str = "T", *,
    sub_org_id: Optional[str] = None,
) -> models.Topic:
    t = models.Topic(
        name=name, description="", color="#000000",
        org_id=org.id, sub_org_id=sub_org_id,
    )
    db.add(t)
    db.flush()
    return t


def _make_proposal(
    db: Session,
    author: models.User,
    org: models.Organization,
    *,
    sub_org_id: Optional[str] = None,
    status: str = "voting",
    topic: Optional[models.Topic] = None,
) -> models.Proposal:
    p = models.Proposal(
        title="P",
        body="",
        author_id=author.id,
        voting_method="binary",
        status=status,
        org_id=org.id,
        sub_org_id=sub_org_id,
        voting_start=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1),
        voting_end=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=1),
    )
    db.add(p)
    db.flush()
    if topic is not None:
        db.add(models.ProposalTopic(
            proposal_id=p.id, topic_id=topic.id, relevance=1.0,
        ))
        db.flush()
    return p


def _auth(user: models.User) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _make_delegation(
    db: Session,
    delegator: models.User,
    delegate: models.User,
    *,
    org_id: Optional[str],
    sub_org_id: Optional[str] = None,
    topic_id: Optional[str] = None,
    chain_behavior: str = "accept_sub",
) -> models.Delegation:
    d = models.Delegation(
        delegator_id=delegator.id,
        delegate_id=delegate.id,
        org_id=org_id,
        sub_org_id=sub_org_id,
        topic_id=topic_id,
        chain_behavior=chain_behavior,
    )
    db.add(d)
    db.flush()
    return d


def _make_follow_rel(
    db: Session,
    follower: models.User,
    followed: models.User,
    *,
    org_id: Optional[str],
    permission_level: str = "delegation_allowed",
) -> models.FollowRelationship:
    r = models.FollowRelationship(
        follower_id=follower.id,
        followed_id=followed.id,
        org_id=org_id,
        permission_level=permission_level,
    )
    db.add(r)
    db.flush()
    return r


def _make_follow_request(
    db: Session,
    requester: models.User,
    target: models.User,
    *,
    org_id: Optional[str],
    status: str = "pending",
    permission_level: Optional[str] = None,
    message: Optional[str] = None,
) -> models.FollowRequest:
    req = models.FollowRequest(
        requester_id=requester.id,
        target_id=target.id,
        org_id=org_id,
        status=status,
        permission_level=permission_level,
        message=message,
    )
    db.add(req)
    db.flush()
    return req


def _make_intent(
    db: Session,
    delegator: models.User,
    delegate: models.User,
    *,
    org_id: Optional[str],
    sub_org_id: Optional[str] = None,
    topic_id: Optional[str] = None,
    follow_request_id: str,
    chain_behavior: str = "accept_sub",
) -> models.DelegationIntent:
    i = models.DelegationIntent(
        delegator_id=delegator.id,
        delegate_id=delegate.id,
        org_id=org_id,
        sub_org_id=sub_org_id,
        topic_id=topic_id,
        chain_behavior=chain_behavior,
        follow_request_id=follow_request_id,
        status="pending",
        expires_at=datetime.now(timezone.utc).replace(tzinfo=None)
        + timedelta(days=30),
    )
    db.add(i)
    db.flush()
    return i


# ===========================================================================
# Test 1 — network endpoint filters by org context
# ===========================================================================


def test_network_endpoint_filters_by_org_context(client, test_db, fresh_graph_store):
    """Caller in two orgs has one delegation per org; the
    /api/orgs/{slug}/delegations/network endpoint returns only the named
    org's delegations."""
    org_a = _make_org(test_db, "neta")
    org_b = _make_org(test_db, "netb")
    caller = _make_user(test_db, "net_caller")
    target_a = _make_user(test_db, "net_target_a")
    target_b = _make_user(test_db, "net_target_b")
    for u in (caller, target_a, target_b):
        make_org_membership(test_db, org_id=org_a.id, user_id=u.id, role="member")
        make_org_membership(test_db, org_id=org_b.id, user_id=u.id, role="member")
    # caller delegates to target_a in org A and to target_b in org B.
    _make_delegation(test_db, caller, target_a, org_id=org_a.id)
    _make_delegation(test_db, caller, target_b, org_id=org_b.id)
    test_db.commit()

    resp_a = client.get(
        f"/api/orgs/{org_a.slug}/delegations/network", headers=_auth(caller),
    )
    assert resp_a.status_code == 200, resp_a.text
    a_node_ids = {n["id"] for n in resp_a.json()["nodes"]}
    assert target_a.id in a_node_ids
    assert target_b.id not in a_node_ids

    resp_b = client.get(
        f"/api/orgs/{org_b.slug}/delegations/network", headers=_auth(caller),
    )
    assert resp_b.status_code == 200, resp_b.text
    b_node_ids = {n["id"] for n in resp_b.json()["nodes"]}
    assert target_b.id in b_node_ids
    assert target_a.id not in b_node_ids


# ===========================================================================
# Test 2 — tally excludes cross-org delegators (THE LOAD-BEARING REGRESSION)
# ===========================================================================


def test_tally_excludes_cross_org_delegators(test_db, fresh_graph_store):
    """User C is in orgs X+Y. C globally delegates in X (org_id=X,
    topic_id=NULL). Tally for a proposal in Y must NOT count C's delegated
    vote, because the delegation belongs to X, not Y.

    This is the prod regression test for the C&Z bug: pre-Phase-18 the
    tally for an Org Y proposal would observe C's delegation to D and
    pull D's direct vote into C's slot, leaking C's "intent in another
    org" into Y's outcome.
    """
    from delegation_engine import engine as delegation_engine_singleton

    org_x = _make_org(test_db, "tally_x")
    org_y = _make_org(test_db, "tally_y")
    z = _make_user(test_db, "tally_z")  # author of the Y proposal
    c = _make_user(test_db, "tally_c")  # delegator in X
    d = _make_user(test_db, "tally_d")  # delegate (X)

    # All three users are members of both orgs (real OrgMembership rows).
    for u in (z, c, d):
        make_org_membership(test_db, org_id=org_x.id, user_id=u.id, role="member")
        make_org_membership(test_db, org_id=org_y.id, user_id=u.id, role="member")

    # C delegates globally in org X (Phase 18: org_id=X, topic_id=NULL).
    _make_delegation(test_db, c, d, org_id=org_x.id, topic_id=None)

    # D casts a YES vote on a proposal in org Y.
    proposal_y = _make_proposal(test_db, z, org_y)
    test_db.add(models.Vote(
        proposal_id=proposal_y.id,
        user_id=d.id,
        vote_value="yes",
        is_direct=True,
        cast_by_id=d.id,
    ))
    test_db.commit()

    # C cast no direct vote in Y. Pre-Phase-18, C's X-delegation would
    # leak into Y's tally and resolve C's slot to D's "yes." Post-fix,
    # the delegation has org_id=X != Y, so _build_context filters it
    # out and C's slot lands in not_cast.
    tally = delegation_engine_singleton.compute_tally(proposal_y, test_db)

    # Expected: D=yes (1), Z and C uncast (2). Eligible = 3 (Z, C, D).
    assert tally.yes == 1, f"expected D's direct yes only; got tally={tally}"
    assert tally.no == 0
    assert tally.not_cast == 2
    assert tally.total_eligible == 3


# ===========================================================================
# Test 3 — global delegation is org-scoped
# ===========================================================================


def test_global_delegation_is_org_scoped(client, test_db, fresh_graph_store):
    """A global delegation in org X (topic_id=NULL, org_id=X) does NOT
    apply to proposals in org Y, even when both delegator+delegate are
    co-members of Y."""
    from delegation_engine import engine as delegation_engine_singleton

    org_x = _make_org(test_db, "gx")
    org_y = _make_org(test_db, "gy")
    a = _make_user(test_db, "g_a")  # delegator
    b = _make_user(test_db, "g_b")  # delegate
    z = _make_user(test_db, "g_z")  # proposal author in Y
    for u in (a, b, z):
        make_org_membership(test_db, org_id=org_x.id, user_id=u.id, role="member")
        make_org_membership(test_db, org_id=org_y.id, user_id=u.id, role="member")
    _make_delegation(test_db, a, b, org_id=org_x.id, topic_id=None)

    proposal_y = _make_proposal(test_db, z, org_y)
    # B votes yes in Y.
    test_db.add(models.Vote(
        proposal_id=proposal_y.id, user_id=b.id, vote_value="yes",
        is_direct=True, cast_by_id=b.id,
    ))
    test_db.commit()

    # Tally semantics: A's slot must remain not_cast in Y.
    tally = delegation_engine_singleton.compute_tally(proposal_y, test_db)
    assert tally.yes == 1   # only B's direct yes
    assert tally.not_cast == 2

    # Visualization: querying the network endpoint in Y for A returns no
    # outgoing edges (the delegation belongs to X, not Y).
    resp_y = client.get(
        f"/api/orgs/{org_y.slug}/delegations/network", headers=_auth(a),
    )
    assert resp_y.status_code == 200
    edges_y = resp_y.json()["edges"]
    assert all(e["target"] != b.id for e in edges_y), (
        f"unexpected A→B edge in Y: {edges_y}"
    )

    # Visualization: in X, the same A sees the A→B edge.
    resp_x = client.get(
        f"/api/orgs/{org_x.slug}/delegations/network", headers=_auth(a),
    )
    assert resp_x.status_code == 200
    edges_x = resp_x.json()["edges"]
    assert any(e["target"] == b.id for e in edges_x), (
        f"missing A→B edge in X: {edges_x}"
    )


# ===========================================================================
# Test 4 — network graph hides other-orgs delegations
# ===========================================================================


def test_network_graph_hides_other_orgs_delegations(client, test_db, fresh_graph_store):
    """A delegates to B in org X. B's view of /api/orgs/{Y_slug}/delegations/network
    does not include the A→B edge (it lives in X)."""
    org_x = _make_org(test_db, "netx")
    org_y = _make_org(test_db, "nety")
    a = _make_user(test_db, "n4_a")
    b = _make_user(test_db, "n4_b")
    for u in (a, b):
        make_org_membership(test_db, org_id=org_x.id, user_id=u.id, role="member")
        make_org_membership(test_db, org_id=org_y.id, user_id=u.id, role="member")
    _make_delegation(test_db, a, b, org_id=org_x.id)
    test_db.commit()

    # B in Y should see no incoming edge (A→B is in X).
    resp_y = client.get(
        f"/api/orgs/{org_y.slug}/delegations/network", headers=_auth(b),
    )
    assert resp_y.status_code == 200
    body = resp_y.json()
    edge_sources = {e["source"] for e in body["edges"]}
    assert a.id not in edge_sources

    # In X, B sees A as an incoming delegator.
    resp_x = client.get(
        f"/api/orgs/{org_x.slug}/delegations/network", headers=_auth(b),
    )
    assert resp_x.status_code == 200
    body_x = resp_x.json()
    sources_x = {e["source"] for e in body_x["edges"]}
    assert a.id in sources_x


# ===========================================================================
# Test 5 — delegation intent carries org context
# ===========================================================================


def test_delegation_intent_carries_org_context(client, test_db, fresh_graph_store):
    """Intent created in org X activates into a Delegation row with
    org_id=X (not NULL). End-to-end flow: create intent → approve follow
    → verify activated delegation row carries the same org context."""
    org_x = _make_org(test_db, "intx")
    a = _make_user(test_db, "int_a")
    b = _make_user(test_db, "int_b", default_follow_policy="require_approval")
    for u in (a, b):
        make_org_membership(test_db, org_id=org_x.id, user_id=u.id, role="member")
    test_db.commit()

    # A requests delegation to B in org X (no follow exists yet → creates
    # follow_request + delegation_intent).
    resp = client.post(
        f"/api/orgs/{org_x.slug}/delegations/request",
        json={"delegate_id": b.id, "topic_id": None},
        headers=_auth(a),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "requested"

    # Verify intent row has org_id=X.
    intent = test_db.query(models.DelegationIntent).filter(
        models.DelegationIntent.delegator_id == a.id,
        models.DelegationIntent.delegate_id == b.id,
    ).one()
    assert intent.org_id == org_x.id
    assert intent.status == "pending"

    # B approves the follow request with delegation_allowed.
    freq_id = body["intent"]["follow_request_id"]
    resp2 = client.put(
        f"/api/orgs/{org_x.slug}/follows/requests/{freq_id}/respond",
        json={"status": "approved", "permission_level": "delegation_allowed"},
        headers=_auth(b),
    )
    assert resp2.status_code == 200, resp2.text

    # The activated Delegation row must carry org_id=X.
    test_db.expire_all()
    activated_intent = test_db.get(models.DelegationIntent, intent.id)
    assert activated_intent.status == "activated"
    deleg = test_db.query(models.Delegation).filter(
        models.Delegation.delegator_id == a.id,
        models.Delegation.delegate_id == b.id,
    ).one()
    assert deleg.org_id == org_x.id, (
        f"activated delegation should carry org_id=X; got {deleg.org_id!r}"
    )


# ===========================================================================
# Test 6 — follow relationship org scoping
# ===========================================================================


def test_follow_relationship_org_scoping(client, test_db, fresh_graph_store):
    """Approving a follow request in org X creates a FollowRelationship
    with org_id=X. A separate request in org Y for the same pair creates
    a separate row with org_id=Y. Works because of the new
    (follower_id, followed_id, org_id) unique constraint."""
    org_x = _make_org(test_db, "foll_x")
    org_y = _make_org(test_db, "foll_y")
    a = _make_user(test_db, "foll_a")
    b = _make_user(test_db, "foll_b", default_follow_policy="require_approval")
    for u in (a, b):
        make_org_membership(test_db, org_id=org_x.id, user_id=u.id, role="member")
        make_org_membership(test_db, org_id=org_y.id, user_id=u.id, role="member")
    test_db.commit()

    # A → B request in X.
    r1 = client.post(
        f"/api/orgs/{org_x.slug}/follows/request",
        json={"target_id": b.id},
        headers=_auth(a),
    )
    assert r1.status_code == 201
    freq_x_id = r1.json()["id"]
    assert r1.json()["org_id"] == org_x.id

    # B approves in X.
    r1a = client.put(
        f"/api/orgs/{org_x.slug}/follows/requests/{freq_x_id}/respond",
        json={"status": "approved", "permission_level": "view_only"},
        headers=_auth(b),
    )
    assert r1a.status_code == 200, r1a.text

    rel_x = test_db.query(models.FollowRelationship).filter(
        models.FollowRelationship.follower_id == a.id,
        models.FollowRelationship.followed_id == b.id,
    ).all()
    assert len(rel_x) == 1
    assert rel_x[0].org_id == org_x.id

    # A → B request in Y (separate row).
    r2 = client.post(
        f"/api/orgs/{org_y.slug}/follows/request",
        json={"target_id": b.id},
        headers=_auth(a),
    )
    assert r2.status_code == 201
    freq_y_id = r2.json()["id"]
    assert r2.json()["org_id"] == org_y.id

    r2a = client.put(
        f"/api/orgs/{org_y.slug}/follows/requests/{freq_y_id}/respond",
        json={"status": "approved", "permission_level": "view_only"},
        headers=_auth(b),
    )
    assert r2a.status_code == 200, r2a.text

    rels_total = test_db.query(models.FollowRelationship).filter(
        models.FollowRelationship.follower_id == a.id,
        models.FollowRelationship.followed_id == b.id,
    ).all()
    assert len(rels_total) == 2
    assert {r.org_id for r in rels_total} == {org_x.id, org_y.id}


# ===========================================================================
# Test 7 — revoke_dependent_delegations scoped to org
# ===========================================================================


def test_revoke_dependent_delegations_scoped_to_org(test_db, fresh_graph_store):
    """Revoking a follow in X does NOT cascade-revoke delegations in Y
    that are gated on a different (Y) follow row."""
    from routes.follows import _revoke_dependent_delegations

    org_x = _make_org(test_db, "rev_x")
    org_y = _make_org(test_db, "rev_y")
    a = _make_user(test_db, "rev_a")
    b = _make_user(test_db, "rev_b")
    for u in (a, b):
        make_org_membership(test_db, org_id=org_x.id, user_id=u.id, role="member")
        make_org_membership(test_db, org_id=org_y.id, user_id=u.id, role="member")

    # Two follow rows: X and Y. Both delegation_allowed.
    _make_follow_rel(test_db, a, b, org_id=org_x.id)
    _make_follow_rel(test_db, a, b, org_id=org_y.id)
    # Two delegation rows: one in X, one in Y.
    d_x = _make_delegation(test_db, a, b, org_id=org_x.id)
    d_y = _make_delegation(test_db, a, b, org_id=org_y.id)
    test_db.commit()

    revoked = _revoke_dependent_delegations(
        test_db, a.id, b.id, a.id, org_id=org_x.id,
    )
    test_db.flush()

    assert d_x.id in revoked, "X delegation should have been revoked"
    assert d_y.id not in revoked, "Y delegation must not cascade-revoke"
    surviving = test_db.get(models.Delegation, d_y.id)
    assert surviving is not None
    assert surviving.org_id == org_y.id


# ===========================================================================
# Test 8 — Phase 4c retrofit completeness (meta-test on schema shape)
# ===========================================================================


def test_phase_4c_retrofit_completeness():
    """Meta-test: assert every relationship table has ``org_id`` mapped
    as a FK to organizations. Future planning agents grepping for
    ``test_phase_4c_retrofit_completeness`` find the closure of the gap.
    """
    tables_to_check = [
        models.Delegation,
        models.DelegationIntent,
        models.FollowRelationship,
        models.FollowRequest,
    ]
    for cls in tables_to_check:
        cols = cls.__table__.columns
        assert "org_id" in cols, (
            f"{cls.__name__} is missing org_id column (Phase 4c retrofit gap)"
        )
        col = cols["org_id"]
        # Every retrofitted column MUST be FK to organizations.id.
        fk_targets = {fk.target_fullname for fk in col.foreign_keys}
        assert "organizations.id" in fk_targets, (
            f"{cls.__name__}.org_id missing FK to organizations.id; "
            f"got fk_targets={fk_targets!r}"
        )

    # Delegation tables additionally have sub_org_id (D4).
    for cls in (models.Delegation, models.DelegationIntent):
        cols = cls.__table__.columns
        assert "sub_org_id" in cols, (
            f"{cls.__name__} is missing sub_org_id (D4)"
        )
        col = cols["sub_org_id"]
        fk_targets = {fk.target_fullname for fk in col.foreign_keys}
        assert "organizations.id" in fk_targets


# ===========================================================================
# Test 9 — sub-org-scoped global delegation via single row
# ===========================================================================


def test_subor_scoped_global_delegation_via_single_row(
    client, test_db, fresh_graph_store,
):
    """Phase 8.5 fan-out collapse: a sub-org-wide global delegation lands
    as ONE Delegation row with (org_id=parent, sub_org_id=Y, topic_id=NULL)
    instead of N per-topic rows.

    Tests the F2 collapse: POST to /api/orgs/{slug}/delegations/request
    with sub_org_id set and topic_id=null produces exactly one row.
    """
    parent = _make_org(test_db, "subor_parent")
    sub = _make_org(test_db, "subor_sub", parent_org_id=parent.id)
    a = _make_user(test_db, "subor_a")
    b = _make_user(test_db, "subor_b", default_follow_policy="auto_approve_delegate")
    make_org_membership(test_db, org_id=parent.id, user_id=a.id, role="member")
    make_org_membership(test_db, org_id=parent.id, user_id=b.id, role="member")
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{parent.slug}/delegations/request",
        json={
            "delegate_id": b.id,
            "topic_id": None,
            "sub_org_id": sub.id,
            "chain_behavior": "accept_sub",
        },
        headers=_auth(a),
    )
    assert resp.status_code == 200, resp.text

    rows = test_db.query(models.Delegation).filter(
        models.Delegation.delegator_id == a.id,
        models.Delegation.delegate_id == b.id,
    ).all()
    assert len(rows) == 1, (
        f"expected exactly one row (single-row collapse); got {len(rows)}"
    )
    only = rows[0]
    assert only.org_id == parent.id
    assert only.sub_org_id == sub.id
    assert only.topic_id is None


# ===========================================================================
# Test 10 — graph_store partitioned by org
# ===========================================================================


def test_graph_store_partitioned_by_org():
    """Cross-org operations on graph_store don't bleed: a delegation
    added in org A is invisible to org B's neighborhood / weight queries.
    """
    store = DelegationGraphStore()

    # Build separate org partitions.
    store.add_delegation("u1", "u2", topic_id=None, org_id="orgA")
    store.add_delegation("u2", "u3", topic_id=None, org_id="orgA")
    # B has its own delegation; u1 has no edges in B.
    store.add_delegation("u4", "u5", topic_id=None, org_id="orgB")

    # Neighborhood queries: u1 in B sees nothing.
    nodes_a, edges_a = store.get_neighborhood("u1", org_id="orgA")
    assert "u2" in nodes_a
    assert any(e[1] == "u2" for e in edges_a)

    nodes_b, edges_b = store.get_neighborhood("u1", org_id="orgB")
    assert nodes_b == {"u1"}
    assert edges_b == []

    # Voting weights: u3 in A has u1 + u2 as ancestors → weight 3.
    assert store.compute_voting_weight("u3", org_id="orgA") == 3
    # u3 in B has no ancestors → weight 1.
    assert store.compute_voting_weight("u3", org_id="orgB") == 1

    # Cross-org cycle detection: adding u3→u1 in A would cycle, but the
    # same edge in B is fine (B's graph doesn't share state with A).
    assert store.would_create_cycle("u3", "u1", topic_id=None, org_id="orgA") is True
    assert store.would_create_cycle("u3", "u1", topic_id=None, org_id="orgB") is False

    # All-orgs helpers exist for forensic admin work.
    nodes_all, edges_all = store.get_neighborhood_all_orgs("u1")
    # u1 has u2 as a direct neighbor in A.
    assert "u2" in nodes_all
    assert store.compute_voting_weight_all_orgs("u3") == 3


# ===========================================================================
# Test 11 — admin delegation graph remains cross-org
# ===========================================================================


def _make_admin(db: Session, username: str) -> models.User:
    """Helper to create a platform admin (the ``is_admin=True`` shape
    expected by ``auth.get_current_admin``)."""
    u = _make_user(db, username)
    u.is_admin = True
    db.flush()
    return u


def test_admin_delegation_graph_remains_cross_org(client, test_db, fresh_graph_store):
    """GET /api/admin/delegation-graph (the renamed
    system_delegation_graph_all_orgs function) returns the union of every
    org's delegations — admin forensic view.
    """
    admin = _make_admin(test_db, "ad_admin")
    org_x = _make_org(test_db, "ad_x")
    org_y = _make_org(test_db, "ad_y")
    ux1 = _make_user(test_db, "adx1")
    ux2 = _make_user(test_db, "adx2")
    uy1 = _make_user(test_db, "ady1")
    uy2 = _make_user(test_db, "ady2")
    for u in (ux1, ux2):
        make_org_membership(test_db, org_id=org_x.id, user_id=u.id, role="member")
    for u in (uy1, uy2):
        make_org_membership(test_db, org_id=org_y.id, user_id=u.id, role="member")
    _make_delegation(test_db, ux1, ux2, org_id=org_x.id)
    _make_delegation(test_db, uy1, uy2, org_id=org_y.id)
    test_db.commit()

    resp = client.get("/api/admin/delegation-graph", headers=_auth(admin))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    node_ids = {n["id"] for n in body["nodes"]}
    # Both orgs' users present in the cross-org admin payload.
    assert {ux1.id, ux2.id, uy1.id, uy2.id}.issubset(node_ids)
    # Both edges present.
    pairs = {(e["source"], e["target"]) for e in body["edges"]}
    assert (ux1.id, ux2.id) in pairs
    assert (uy1.id, uy2.id) in pairs


# ===========================================================================
# Test 12 — org-scoped admin delegation graph
# ===========================================================================


def test_org_scoped_admin_delegation_graph(client, test_db, fresh_graph_store):
    """GET /api/admin/orgs/{slug}/delegation_graph returns only that
    org's delegations."""
    admin = _make_admin(test_db, "ad2_admin")
    org_x = _make_org(test_db, "adscope_x")
    org_y = _make_org(test_db, "adscope_y")
    ux1 = _make_user(test_db, "ads_x1")
    ux2 = _make_user(test_db, "ads_x2")
    uy1 = _make_user(test_db, "ads_y1")
    uy2 = _make_user(test_db, "ads_y2")
    for u in (ux1, ux2):
        make_org_membership(test_db, org_id=org_x.id, user_id=u.id, role="member")
    for u in (uy1, uy2):
        make_org_membership(test_db, org_id=org_y.id, user_id=u.id, role="member")
    _make_delegation(test_db, ux1, ux2, org_id=org_x.id)
    _make_delegation(test_db, uy1, uy2, org_id=org_y.id)
    test_db.commit()

    resp = client.get(
        f"/api/admin/orgs/{org_x.slug}/delegation_graph", headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    node_ids = {n["id"] for n in body["nodes"]}
    assert {ux1.id, ux2.id}.issubset(node_ids)
    # Y users must NOT leak into X's org-scoped admin graph.
    assert uy1.id not in node_ids
    assert uy2.id not in node_ids
    pairs = {(e["source"], e["target"]) for e in body["edges"]}
    assert (ux1.id, ux2.id) in pairs
    assert (uy1.id, uy2.id) not in pairs


# ===========================================================================
# Test 13-16 — migration backfill unit tests
#
# These import the migration module directly and exercise its private
# helpers against a fresh in-memory schema. The Alembic-via-CLI pathway
# is exercised by the migration cycle subprocess test (separate file);
# these are unit-level coverage that the helpers do the right thing.
# ===========================================================================


def _import_phase_18a_migration():
    """Import the Phase 18a migration module by file path (it's not a
    regular import target; alembic discovers it via the versions/
    directory)."""
    import importlib.util

    here = Path(__file__).resolve().parent.parent  # backend/
    mig_path = (
        here / "migrations" / "versions"
        / "219205801d2c_phase_18a_delegation_org_scoping_nullable.py"
    )
    spec = importlib.util.spec_from_file_location(
        "phase_18a_migration", mig_path,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_schema_pre_phase_18a(test_db: Session):
    """Replace the SQLAlchemy-mapped relationship tables with their
    pre-Phase-18 shape (no org_id columns). Used by the backfill unit
    tests so the helpers run against a "pre-migration" snapshot.

    Done by issuing raw SQL that recreates the tables without org_id /
    sub_org_id, after dropping the SQLAlchemy-mapped versions. Other
    tables (users, orgs, topics, votes, proposals, audit_log) keep
    their post-Phase-18 shape — that's fine because the backfill reads
    from those tables and writes to the relationship tables.

    Uses the session's connection rather than the engine directly so the
    DDL participates in the same transactional view (SQLAlchemy 2.x
    removed ``Engine.execute``).
    """
    conn = test_db.connection()
    conn.execute(sa_text("DROP TABLE IF EXISTS delegations"))
    conn.execute(sa_text("DROP TABLE IF EXISTS delegation_intents"))
    conn.execute(sa_text("DROP TABLE IF EXISTS follow_relationships"))
    conn.execute(sa_text("DROP TABLE IF EXISTS follow_requests"))

    conn.execute(sa_text("""
        CREATE TABLE delegations (
            id VARCHAR PRIMARY KEY,
            delegator_id VARCHAR NOT NULL,
            delegate_id VARCHAR NOT NULL,
            topic_id VARCHAR,
            chain_behavior VARCHAR NOT NULL DEFAULT 'accept_sub',
            created_at DATETIME,
            updated_at DATETIME
        )
    """))
    conn.execute(sa_text("""
        CREATE TABLE delegation_intents (
            id VARCHAR PRIMARY KEY,
            delegator_id VARCHAR NOT NULL,
            delegate_id VARCHAR NOT NULL,
            topic_id VARCHAR,
            chain_behavior VARCHAR NOT NULL DEFAULT 'accept_sub',
            follow_request_id VARCHAR NOT NULL,
            status VARCHAR NOT NULL DEFAULT 'pending',
            expires_at DATETIME NOT NULL,
            created_at DATETIME,
            activated_at DATETIME
        )
    """))
    conn.execute(sa_text("""
        CREATE TABLE follow_relationships (
            id VARCHAR PRIMARY KEY,
            follower_id VARCHAR NOT NULL,
            followed_id VARCHAR NOT NULL,
            permission_level VARCHAR NOT NULL,
            created_at DATETIME
        )
    """))
    conn.execute(sa_text("""
        CREATE TABLE follow_requests (
            id VARCHAR PRIMARY KEY,
            requester_id VARCHAR NOT NULL,
            target_id VARCHAR NOT NULL,
            status VARCHAR NOT NULL DEFAULT 'pending',
            permission_level VARCHAR,
            message TEXT,
            requested_at DATETIME,
            responded_at DATETIME
        )
    """))


def _insert_pre_phase_18a_delegation(
    conn, *, delegator_id: str, delegate_id: str,
    topic_id: Optional[str] = None,
    chain_behavior: str = "accept_sub",
    updated_at: Optional[datetime] = None,
) -> str:
    import uuid
    d_id = str(uuid.uuid4())
    conn.execute(
        sa_text(
            "INSERT INTO delegations "
            "(id, delegator_id, delegate_id, topic_id, chain_behavior, "
            " created_at, updated_at) "
            "VALUES (:id, :a, :b, :t, :cb, :ca, :ua)"
        ),
        {
            "id": d_id, "a": delegator_id, "b": delegate_id,
            "t": topic_id, "cb": chain_behavior,
            "ca": datetime.now(timezone.utc).replace(tzinfo=None),
            "ua": updated_at or datetime.now(timezone.utc).replace(tzinfo=None),
        },
    )
    return d_id


def test_migration_backfill_topic_scoped_rows(test_db):
    """Sweep 1: a pre-migration delegation with topic_id set has its
    org_id and sub_org_id populated from the topic row."""
    org = _make_org(test_db, "mig_top")
    sub = _make_org(test_db, "mig_top_sub", parent_org_id=org.id)
    delegator = _make_user(test_db, "mig_top_del")
    delegate = _make_user(test_db, "mig_top_dgt")
    topic = _make_topic(test_db, org, "T", sub_org_id=sub.id)
    test_db.commit()

    _build_schema_pre_phase_18a(test_db)
    conn = test_db.connection()
    d_id = _insert_pre_phase_18a_delegation(
        conn, delegator_id=delegator.id, delegate_id=delegate.id,
        topic_id=topic.id,
    )

    mig = _import_phase_18a_migration()
    # Add the org_id / sub_org_id columns so the backfill UPDATE works.
    conn.execute(sa_text("ALTER TABLE delegations ADD COLUMN org_id VARCHAR"))
    conn.execute(sa_text("ALTER TABLE delegations ADD COLUMN sub_org_id VARCHAR"))
    stats = mig._backfill_delegations(conn)

    assert stats["sweep1"] == 1
    row = conn.execute(
        sa_text("SELECT org_id, sub_org_id FROM delegations WHERE id = :id"),
        {"id": d_id},
    ).first()
    assert row[0] == org.id
    assert row[1] == sub.id


def test_migration_backfill_global_single_shared_org(test_db):
    """Sweep 2: a global delegation (topic_id=NULL) where parties share
    exactly one org — backfill picks that one shared org."""
    org = _make_org(test_db, "mig_solo")
    other = _make_org(test_db, "mig_solo_unrelated")  # noqa: F841
    delegator = _make_user(test_db, "mig_solo_del")
    delegate = _make_user(test_db, "mig_solo_dgt")
    make_org_membership(test_db, org_id=org.id, user_id=delegator.id, role="member")
    make_org_membership(test_db, org_id=org.id, user_id=delegate.id, role="member")
    test_db.commit()

    _build_schema_pre_phase_18a(test_db)
    conn = test_db.connection()
    d_id = _insert_pre_phase_18a_delegation(
        conn, delegator_id=delegator.id, delegate_id=delegate.id,
        topic_id=None,
    )

    mig = _import_phase_18a_migration()
    conn.execute(sa_text("ALTER TABLE delegations ADD COLUMN org_id VARCHAR"))
    conn.execute(sa_text("ALTER TABLE delegations ADD COLUMN sub_org_id VARCHAR"))
    stats = mig._backfill_delegations(conn)

    assert stats["sweep2"] == 1
    row = conn.execute(
        sa_text("SELECT org_id FROM delegations WHERE id = :id"),
        {"id": d_id},
    ).first()
    assert row[0] == org.id


def test_migration_backfill_global_multi_shared_org_heuristic(test_db):
    """Sweep 3: parties co-members of two orgs (the C&Z case). The
    most-recently-active heuristic picks the org where the delegate
    has more recent vote activity."""
    org_x = _make_org(test_db, "mig_multi_x")
    org_y = _make_org(test_db, "mig_multi_y")
    delegator = _make_user(test_db, "mig_multi_del")
    delegate = _make_user(test_db, "mig_multi_dgt")
    for u in (delegator, delegate):
        make_org_membership(
            test_db, org_id=org_x.id, user_id=u.id, role="member",
        )
        make_org_membership(
            test_db, org_id=org_y.id, user_id=u.id, role="member",
        )

    # Delegate's most recent vote is in org Y (so Y wins).
    z_in_x = _make_user(test_db, "mig_multi_zx")
    z_in_y = _make_user(test_db, "mig_multi_zy")
    make_org_membership(test_db, org_id=org_x.id, user_id=z_in_x.id, role="member")
    make_org_membership(test_db, org_id=org_y.id, user_id=z_in_y.id, role="member")
    p_x = _make_proposal(test_db, z_in_x, org_x)
    p_y = _make_proposal(test_db, z_in_y, org_y)
    # Vote in X (older).
    older = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=10)
    newer = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    test_db.add(models.Vote(
        proposal_id=p_x.id, user_id=delegate.id, vote_value="yes",
        is_direct=True, cast_by_id=delegate.id, cast_at=older,
    ))
    test_db.add(models.Vote(
        proposal_id=p_y.id, user_id=delegate.id, vote_value="yes",
        is_direct=True, cast_by_id=delegate.id, cast_at=newer,
    ))
    test_db.commit()

    _build_schema_pre_phase_18a(test_db)
    conn = test_db.connection()
    d_id = _insert_pre_phase_18a_delegation(
        conn, delegator_id=delegator.id, delegate_id=delegate.id,
        topic_id=None,
    )

    mig = _import_phase_18a_migration()
    conn.execute(sa_text("ALTER TABLE delegations ADD COLUMN org_id VARCHAR"))
    conn.execute(sa_text("ALTER TABLE delegations ADD COLUMN sub_org_id VARCHAR"))
    stats = mig._backfill_delegations(conn)

    assert stats["sweep3"] == 1
    row = conn.execute(
        sa_text("SELECT org_id FROM delegations WHERE id = :id"),
        {"id": d_id},
    ).first()
    # Y has the more recent vote → heuristic picks Y.
    assert row[0] == org_y.id


def test_migration_backfill_audit_logging(test_db):
    """Backfill emits delegation.org_id_backfilled audit events with
    sweep_number, ambiguity_resolution, old_state, new_state."""
    org = _make_org(test_db, "mig_audit")
    delegator = _make_user(test_db, "mig_aud_del")
    delegate = _make_user(test_db, "mig_aud_dgt")
    make_org_membership(test_db, org_id=org.id, user_id=delegator.id, role="member")
    make_org_membership(test_db, org_id=org.id, user_id=delegate.id, role="member")
    test_db.commit()

    _build_schema_pre_phase_18a(test_db)
    conn = test_db.connection()
    d_id = _insert_pre_phase_18a_delegation(
        conn, delegator_id=delegator.id, delegate_id=delegate.id,
        topic_id=None,
    )

    mig = _import_phase_18a_migration()
    conn.execute(sa_text("ALTER TABLE delegations ADD COLUMN org_id VARCHAR"))
    conn.execute(sa_text("ALTER TABLE delegations ADD COLUMN sub_org_id VARCHAR"))
    mig._backfill_delegations(conn)

    audit_rows = conn.execute(
        sa_text(
            "SELECT action, target_type, target_id, details "
            "FROM audit_log "
            "WHERE action = 'delegation.org_id_backfilled'"
        ),
    ).fetchall()
    assert len(audit_rows) == 1
    action, target_type, target_id, details_json = audit_rows[0]
    assert target_type == "delegation"
    assert target_id == d_id
    import json
    details = json.loads(details_json)
    assert "sweep_number" in details
    assert "ambiguity_resolution" in details
    assert "old_state" in details
    assert "new_state" in details
    # Single-shared-org case → sweep 2.
    assert details["sweep_number"] == 2
    assert details["ambiguity_resolution"] == "single_shared_org"
    assert details["new_state"]["org_id"] == org.id


# ===========================================================================
# Test 17 — phase 8.5 misleading comment updated (meta-test)
# ===========================================================================


def test_phase_8_5_test_comment_updated():
    """Meta-test: assert the misleading comment at
    test_delegation_scope.py:263 has been replaced with new copy that
    mentions Phase 18 / org-scoped enforcement.

    Cluster D (in this same pass): the lead updates the comment text;
    this test guards against re-introduction.
    """
    here = Path(__file__).resolve().parent
    target = here / "test_delegation_scope.py"
    text = target.read_text(encoding="utf-8")

    # The misleading copy MUST be gone.
    assert (
        "No special path. No new pure-layer code is required." not in text
    ), (
        "Phase 8.5's misleading comment still present in "
        "test_delegation_scope.py — Cluster D missed an update; this "
        "test guards the closure of the Phase 4c retrofit gap."
    )

    # And the new Phase 18 reference SHOULD be present.
    assert "Phase 18" in text, (
        "Replacement copy should mention Phase 18 to anchor the "
        "comment to the closure of the org-scoping retrofit."
    )


# ===========================================================================
# Additional regression coverage
# ===========================================================================


def test_intent_activation_propagates_org_id_through_helper(test_db, fresh_graph_store):
    """Regression: activate_intents_for_follow correctly propagates
    org_id from the intent into the resulting Delegation row, even
    when called directly (route-helper boundary)."""
    from routes.delegations import activate_intents_for_follow

    org = _make_org(test_db, "iact_org")
    a = _make_user(test_db, "iact_a")
    b = _make_user(test_db, "iact_b")
    make_org_membership(test_db, org_id=org.id, user_id=a.id, role="member")
    make_org_membership(test_db, org_id=org.id, user_id=b.id, role="member")
    freq = _make_follow_request(
        test_db, a, b, org_id=org.id, status="approved",
        permission_level="delegation_allowed",
    )
    _make_follow_rel(test_db, a, b, org_id=org.id)
    _make_intent(
        test_db, a, b, org_id=org.id, follow_request_id=freq.id,
    )
    test_db.commit()

    activated = activate_intents_for_follow(
        test_db, a.id, b.id, org_id=org.id,
    )
    assert len(activated) == 1
    deleg = test_db.query(models.Delegation).filter(
        models.Delegation.delegator_id == a.id,
        models.Delegation.delegate_id == b.id,
    ).one()
    assert deleg.org_id == org.id


def test_intent_activation_does_not_cross_orgs(test_db, fresh_graph_store):
    """Regression: when activate_intents_for_follow is called with
    org_id=X, intents in org Y are NOT activated (D5 propagation in the
    org-scoped direction)."""
    from routes.delegations import activate_intents_for_follow

    org_x = _make_org(test_db, "iax")
    org_y = _make_org(test_db, "iay")
    a = _make_user(test_db, "iax_a")
    b = _make_user(test_db, "iax_b")
    for u in (a, b):
        make_org_membership(test_db, org_id=org_x.id, user_id=u.id, role="member")
        make_org_membership(test_db, org_id=org_y.id, user_id=u.id, role="member")

    freq_x = _make_follow_request(
        test_db, a, b, org_id=org_x.id, status="approved",
        permission_level="delegation_allowed",
    )
    freq_y = _make_follow_request(
        test_db, a, b, org_id=org_y.id, status="approved",
        permission_level="delegation_allowed",
    )
    _make_follow_rel(test_db, a, b, org_id=org_x.id)
    _make_follow_rel(test_db, a, b, org_id=org_y.id)
    intent_x = _make_intent(test_db, a, b, org_id=org_x.id, follow_request_id=freq_x.id)
    intent_y = _make_intent(test_db, a, b, org_id=org_y.id, follow_request_id=freq_y.id)
    test_db.commit()

    activated = activate_intents_for_follow(
        test_db, a.id, b.id, org_id=org_x.id,
    )
    # Only the X intent should have activated.
    assert intent_x.id in activated
    assert intent_y.id not in activated
    test_db.refresh(intent_x)
    test_db.refresh(intent_y)
    assert intent_x.status == "activated"
    assert intent_y.status == "pending"

    # Resulting Delegation row carries org_x.
    deleg_rows = test_db.query(models.Delegation).filter(
        models.Delegation.delegator_id == a.id,
        models.Delegation.delegate_id == b.id,
    ).all()
    assert len(deleg_rows) == 1
    assert deleg_rows[0].org_id == org_x.id


def test_unique_constraint_allows_separate_per_org_globals(test_db):
    """Phase 18 unique constraint is (delegator, org, sub_org, topic).
    A user can have ONE global-per-org delegation per org. Inserting
    two rows with different org_ids and topic_id=NULL must succeed."""
    org_x = _make_org(test_db, "uq_x")
    org_y = _make_org(test_db, "uq_y")
    a = _make_user(test_db, "uq_a")
    b = _make_user(test_db, "uq_b")
    for u in (a, b):
        make_org_membership(test_db, org_id=org_x.id, user_id=u.id, role="member")
        make_org_membership(test_db, org_id=org_y.id, user_id=u.id, role="member")

    _make_delegation(test_db, a, b, org_id=org_x.id, topic_id=None)
    _make_delegation(test_db, a, b, org_id=org_y.id, topic_id=None)
    test_db.commit()

    rows = test_db.query(models.Delegation).filter(
        models.Delegation.delegator_id == a.id,
    ).all()
    assert len(rows) == 2
    assert {r.org_id for r in rows} == {org_x.id, org_y.id}


def test_revoke_delegation_endpoint_org_scoped(client, test_db, fresh_graph_store):
    """Regression: DELETE /api/orgs/{slug}/delegations/{topic_or_global}
    revokes the row in this org only — the same-shape row in another
    org is untouched."""
    org_x = _make_org(test_db, "rd_x")
    org_y = _make_org(test_db, "rd_y")
    a = _make_user(test_db, "rd_a")
    b = _make_user(test_db, "rd_b")
    for u in (a, b):
        make_org_membership(test_db, org_id=org_x.id, user_id=u.id, role="member")
        make_org_membership(test_db, org_id=org_y.id, user_id=u.id, role="member")
    d_x = _make_delegation(test_db, a, b, org_id=org_x.id, topic_id=None)
    d_y = _make_delegation(test_db, a, b, org_id=org_y.id, topic_id=None)
    test_db.commit()

    resp = client.delete(
        f"/api/orgs/{org_x.slug}/delegations/global", headers=_auth(a),
    )
    assert resp.status_code == 204, resp.text

    # Y delegation untouched.
    assert test_db.get(models.Delegation, d_x.id) is None
    assert test_db.get(models.Delegation, d_y.id) is not None


def test_list_my_delegations_filters_by_org(client, test_db, fresh_graph_store):
    """Regression: GET /api/orgs/{slug}/delegations returns only the
    caller's delegations in that org."""
    org_x = _make_org(test_db, "ll_x")
    org_y = _make_org(test_db, "ll_y")
    a = _make_user(test_db, "ll_a")
    b = _make_user(test_db, "ll_b")
    c = _make_user(test_db, "ll_c")
    for u in (a, b, c):
        make_org_membership(test_db, org_id=org_x.id, user_id=u.id, role="member")
        make_org_membership(test_db, org_id=org_y.id, user_id=u.id, role="member")
    _make_delegation(test_db, a, b, org_id=org_x.id)
    _make_delegation(test_db, a, c, org_id=org_y.id)
    test_db.commit()

    resp = client.get(
        f"/api/orgs/{org_x.slug}/delegations", headers=_auth(a),
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["delegate_id"] == b.id
    assert rows[0]["org_id"] == org_x.id


def test_old_unscoped_delegations_url_404s(client, test_db, fresh_graph_store):
    """Phase 18 D3: the old /api/delegations/* prefix is a clean break
    (no compat aliases). Hitting the legacy path returns 404."""
    a = _make_user(test_db, "old_a")
    test_db.commit()
    resp = client.get("/api/delegations/network", headers=_auth(a))
    # Either 404 (route not registered) or 405 are both acceptable; the
    # important assertion is "definitely not a 200 with org-leaking data."
    assert resp.status_code in (404, 405), (
        f"old /api/delegations/* surface should be removed; got "
        f"{resp.status_code}"
    )


def test_old_unscoped_follows_url_404s(client, test_db, fresh_graph_store):
    """Phase 18 D3: old /api/follows/* is a clean break."""
    a = _make_user(test_db, "old_f_a")
    b = _make_user(test_db, "old_f_b")
    test_db.commit()
    resp = client.post(
        "/api/follows/request",
        json={"target_id": b.id},
        headers=_auth(a),
    )
    assert resp.status_code in (404, 405)


def test_request_delegation_validates_topic_org_match(client, test_db, fresh_graph_store):
    """Regression: a delegation request with a topic_id from a different
    org returns 400 (the topic is in another org, not the URL prefix's
    org)."""
    org_x = _make_org(test_db, "tov_x")
    org_y = _make_org(test_db, "tov_y")
    a = _make_user(test_db, "tov_a")
    b = _make_user(test_db, "tov_b", default_follow_policy="auto_approve_delegate")
    make_org_membership(test_db, org_id=org_x.id, user_id=a.id, role="member")
    make_org_membership(test_db, org_id=org_x.id, user_id=b.id, role="member")
    topic_y = _make_topic(test_db, org_y, "Y_Topic")
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org_x.slug}/delegations/request",
        json={"delegate_id": b.id, "topic_id": topic_y.id},
        headers=_auth(a),
    )
    # Topic belongs to Y, the URL prefix is X → 400.
    assert resp.status_code == 400, resp.text


def test_subor_validation_must_be_child_of_url_prefix_org(
    client, test_db, fresh_graph_store,
):
    """Regression: sub_org_id must be a sub-org of the URL-prefix org.
    Sending a sub-org belonging to a different parent → 400."""
    parent_x = _make_org(test_db, "subv_x")
    parent_y = _make_org(test_db, "subv_y")
    sub_y = _make_org(test_db, "subv_y_sub", parent_org_id=parent_y.id)
    a = _make_user(test_db, "subv_a")
    b = _make_user(test_db, "subv_b", default_follow_policy="auto_approve_delegate")
    make_org_membership(test_db, org_id=parent_x.id, user_id=a.id, role="member")
    make_org_membership(test_db, org_id=parent_x.id, user_id=b.id, role="member")
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{parent_x.slug}/delegations/request",
        json={"delegate_id": b.id, "topic_id": None, "sub_org_id": sub_y.id},
        headers=_auth(a),
    )
    assert resp.status_code == 400, resp.text


def test_delegation_out_schema_surfaces_org_id(client, test_db, fresh_graph_store):
    """Schema regression: DelegationOut surfaces org_id and sub_org_id,
    so the FE can render scope labels correctly."""
    org = _make_org(test_db, "schorg")
    a = _make_user(test_db, "sch_a")
    b = _make_user(test_db, "sch_b", default_follow_policy="auto_approve_delegate")
    make_org_membership(test_db, org_id=org.id, user_id=a.id, role="member")
    make_org_membership(test_db, org_id=org.id, user_id=b.id, role="member")
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/delegations/request",
        json={"delegate_id": b.id, "topic_id": None},
        headers=_auth(a),
    )
    assert resp.status_code == 200, resp.text
    deleg = resp.json().get("delegation")
    assert deleg is not None
    assert "org_id" in deleg
    assert deleg["org_id"] == org.id
    assert "sub_org_id" in deleg


def test_follow_relationship_out_schema_surfaces_org_id(
    client, test_db, fresh_graph_store,
):
    """Schema regression: FollowRelationshipOut surfaces org_id."""
    org = _make_org(test_db, "frelorg")
    a = _make_user(test_db, "fr_a")
    b = _make_user(test_db, "fr_b", default_follow_policy="auto_approve_view")
    make_org_membership(test_db, org_id=org.id, user_id=a.id, role="member")
    make_org_membership(test_db, org_id=org.id, user_id=b.id, role="member")
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/follows/request",
        json={"target_id": b.id},
        headers=_auth(a),
    )
    assert resp.status_code == 201, resp.text

    # Follow relationship should now exist; list it.
    resp2 = client.get(
        f"/api/orgs/{org.slug}/follows/following", headers=_auth(a),
    )
    assert resp2.status_code == 200
    rows = resp2.json()
    assert len(rows) == 1
    assert rows[0]["org_id"] == org.id


def test_users_delegation_tree_org_scoped_filter(client, test_db, fresh_graph_store):
    """B2.2 regression: GET /api/users/{id}/delegation-tree?org_id=...
    filters chain_behavior lookup by org_id and reads from the right
    org's partition of the graph_store. A user with delegations in two
    orgs returns only the requested-org's tree."""
    org_x = _make_org(test_db, "dtx")
    org_y = _make_org(test_db, "dty")
    target = _make_user(test_db, "dt_target")
    delegate_x = _make_user(test_db, "dt_dx")
    delegate_y = _make_user(test_db, "dt_dy")
    viewer = _make_user(test_db, "dt_viewer")
    for u in (target, delegate_x, delegate_y, viewer):
        make_org_membership(test_db, org_id=org_x.id, user_id=u.id, role="member")
        make_org_membership(test_db, org_id=org_y.id, user_id=u.id, role="member")
    _make_delegation(test_db, target, delegate_x, org_id=org_x.id)
    _make_delegation(test_db, target, delegate_y, org_id=org_y.id)
    # Endpoint reads from the graph_store partition, not directly from
    # DB rows — replicate the production add path so the partitioned
    # store sees both edges in their respective org buckets.
    fresh_graph_store.add_delegation(
        target.id, delegate_x.id, topic_id=None, org_id=org_x.id,
    )
    fresh_graph_store.add_delegation(
        target.id, delegate_y.id, topic_id=None, org_id=org_y.id,
    )
    test_db.commit()

    resp_x = client.get(
        f"/api/users/{target.id}/delegation-tree?org_id={org_x.id}",
        headers=_auth(viewer),
    )
    assert resp_x.status_code == 200, resp_x.text
    nodes_x = resp_x.json()["nodes"]
    node_ids_x = {n["id"] for n in nodes_x}
    # Only X's delegate visible when org filter is X.
    assert delegate_x.id in node_ids_x
    assert delegate_y.id not in node_ids_x

    resp_y = client.get(
        f"/api/users/{target.id}/delegation-tree?org_id={org_y.id}",
        headers=_auth(viewer),
    )
    assert resp_y.status_code == 200
    node_ids_y = {n["id"] for n in resp_y.json()["nodes"]}
    assert delegate_y.id in node_ids_y
    assert delegate_x.id not in node_ids_y
