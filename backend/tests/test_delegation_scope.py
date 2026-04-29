"""Phase 8.5 — Pure-layer scope filtering and cross-scope delegation tests.

Decisions exercised:
  - Decision 3: sub-org-scoped topics are visible only inside their sub-org;
    parent-org proposals can't use sub-org topics. A sub-org proposal sees
    parent-org topics + its own sub-org's topics.
  - Decision 8: cross-scope delegation works "naturally" — a non-member
    delegate's missing vote triggers chain-behavior just like any other
    "delegate didn't vote" path. No new pure-layer code is required.

The scope-filtering test exercises the post-Phase-8.5 invariant that the
upstream code only puts in-scope topics on a Proposal in the first place.
We confirm at the pure-layer level that resolution still works; the actual
in-scope filter is a Session 2 concern (route-layer change).
"""

from __future__ import annotations

import models
from delegation_engine import (
    DelegationData,
    ProposalContext,
    Ballot,
    eligible_voter_ids_for_proposal,
    compute_tally_pure,
    resolve_vote_pure,
)
from tests.conftest import (
    make_user, make_topic, make_proposal,
    cast_direct_vote, set_delegation, set_precedence, make_context,
)


def _make_org(db, slug: str, parent_org_id: str | None = None) -> models.Organization:
    org = models.Organization(
        name=slug, slug=slug, description="",
        parent_org_id=parent_org_id, settings={},
    )
    db.add(org)
    db.flush()
    return org


def _add_membership(db, user, org):
    m = models.OrgMembership(
        user_id=user.id, org_id=org.id, role="member", status="active",
    )
    db.add(m)
    db.flush()
    return m


def _add_sub_membership(db, user, sub_org):
    m = models.SubOrgMembership(
        user_id=user.id, sub_org_id=sub_org.id, role="member", status="active",
    )
    db.add(m)
    db.flush()
    return m


# ---------------------------------------------------------------------------
# Pure-layer scope demonstration: topics passed in via ProposalContext
# ---------------------------------------------------------------------------

def test_pure_layer_resolves_with_in_scope_topics_only():
    """Pure-layer demonstration: when ctx.proposal_topics already reflects the
    Phase 8.5 scope filter (parent-org-wide + own sub-org's topics), the
    resolver picks the right delegation. This pins that the pure layer doesn't
    need scope awareness — it only sees the filtered topic list."""
    # Two parent-org topics + one sub-org-only topic. Sub-org proposal includes
    # one parent-org topic and the sub-org topic. alice has delegations on both.
    ctx = make_context(
        proposal_topics=["parent-topic", "sub-org-topic"],  # in-scope only
        delegations={
            ("alice", "parent-topic"): ("delegate_a", "accept_sub"),
            ("alice", "sub-org-topic"): ("delegate_b", "accept_sub"),
        },
        precedences={
            ("alice", "sub-org-topic"): 0,  # higher priority (lower int)
            ("alice", "parent-topic"): 1,
        },
        direct_votes={"delegate_b": "yes"},
    )
    result = resolve_vote_pure("alice", ctx)
    assert result is not None
    assert result.vote_value == "yes"
    assert result.cast_by_id == "delegate_b"


def test_pure_layer_parent_proposal_excludes_sub_org_topic():
    """When a parent-org proposal is built, only parent-org topics appear in
    ctx.proposal_topics — alice's sub-org delegation isn't reachable, so her
    parent-org delegation fires instead."""
    ctx = make_context(
        proposal_topics=["parent-topic"],  # sub-org-topic NOT in scope
        delegations={
            ("alice", "parent-topic"): ("delegate_a", "accept_sub"),
            ("alice", "sub-org-topic"): ("delegate_b", "accept_sub"),
        },
        precedences={
            ("alice", "sub-org-topic"): 0,
            ("alice", "parent-topic"): 1,
        },
        direct_votes={"delegate_a": "no", "delegate_b": "yes"},
    )
    result = resolve_vote_pure("alice", ctx)
    assert result is not None
    # delegate_a (parent-topic) wins because sub-org-topic isn't in proposal_topics
    assert result.vote_value == "no"
    assert result.cast_by_id == "delegate_a"


# ---------------------------------------------------------------------------
# Decision 8: cross-scope delegation uses existing chain-behavior mechanics
# ---------------------------------------------------------------------------

def test_cross_scope_non_member_delegate_no_vote_revert_direct():
    """Decision 8: alice (sub-org member) delegates to bob (NOT a sub-org
    member). On a sub-org proposal, bob can't vote. The chain-behavior
    'revert_direct' default handles this exactly as if bob just hadn't voted —
    no new code path needed."""
    ctx = ProposalContext(
        proposal_topics=["topic-1"],
        all_delegations={
            "alice": {
                "topic-1": DelegationData(
                    delegator_id="alice",
                    delegate_id="bob",
                    topic_id="topic-1",
                    chain_behavior="revert_direct",
                ),
            },
        },
        all_precedences={"alice": {"topic-1": 0}},
        direct_votes={},  # neither alice nor bob cast a direct ballot
    )
    # alice's delegate (bob) didn't vote → revert_direct → no resolved vote.
    result = resolve_vote_pure("alice", ctx)
    assert result is None


def test_cross_scope_non_member_delegate_no_vote_abstain():
    """Same shape, chain_behavior='abstain' → also resolves to None."""
    ctx = ProposalContext(
        proposal_topics=["topic-1"],
        all_delegations={
            "alice": {
                "topic-1": DelegationData(
                    delegator_id="alice",
                    delegate_id="bob",
                    topic_id="topic-1",
                    chain_behavior="abstain",
                ),
            },
        },
        all_precedences={"alice": {"topic-1": 0}},
        direct_votes={},
    )
    result = resolve_vote_pure("alice", ctx)
    assert result is None


def test_cross_scope_non_member_delegate_accept_sub_falls_to_grandparent():
    """Decision 8 + accept_sub: if bob (cross-scope, can't vote) has his own
    delegation to carol, alice's vote inherits from carol exactly as the
    existing chain-behavior code already handles. No new pure-layer logic."""
    ctx = ProposalContext(
        proposal_topics=["topic-1"],
        all_delegations={
            "alice": {
                "topic-1": DelegationData(
                    delegator_id="alice",
                    delegate_id="bob",
                    topic_id="topic-1",
                    chain_behavior="accept_sub",
                ),
            },
            "bob": {
                "topic-1": DelegationData(
                    delegator_id="bob",
                    delegate_id="carol",
                    topic_id="topic-1",
                    chain_behavior="accept_sub",
                ),
            },
        },
        all_precedences={
            "alice": {"topic-1": 0},
            "bob": {"topic-1": 0},
        },
        direct_votes={"carol": "yes"},  # carol IS a sub-org member who voted
    )
    result = resolve_vote_pure("alice", ctx)
    assert result is not None
    assert result.vote_value == "yes"
    assert result.cast_by_id == "carol"
    # The chain shows alice → bob → carol, even though bob is "cross-scope"
    # from the sub-org's perspective. The pure layer doesn't care.
    assert result.delegate_chain == ["bob", "carol"]


# ---------------------------------------------------------------------------
# End-to-end: cross-scope delegation under tally for a sub-org proposal
# ---------------------------------------------------------------------------

def test_cross_scope_delegation_natural_no_vote_in_sub_org_tally(db):
    """Integration-flavored test: a sub-org proposal where one sub-org member
    delegated to a parent-org-only user. The non-member delegate has no vote;
    the delegator's chain-behavior fires; the tally counts it as not_cast.
    This is the canonical Decision 8 demonstration that no new pure-layer
    code is required — the existing 'delegate didn't vote' path handles it."""
    # Build a parent + sub-org membership shape.
    parent = _make_org(db, "parent")
    sub = _make_org(db, "sub", parent_org_id=parent.id)
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")  # parent-org only, NOT in sub-org
    carol = make_user(db, "carol")
    _add_membership(db, alice, parent)
    _add_membership(db, bob, parent)
    _add_membership(db, carol, parent)
    _add_sub_membership(db, alice, sub)
    _add_sub_membership(db, carol, sub)
    # bob is intentionally NOT added to the sub-org.

    topic = make_topic(db, "Sub-Topic")

    # alice delegates to bob with default chain_behavior (accept_sub)
    # but bob has no further delegation, so alice's vote will resolve to None.
    ctx = ProposalContext(
        proposal_topics=[topic.id],
        all_delegations={
            alice.id: {
                topic.id: DelegationData(
                    delegator_id=alice.id,
                    delegate_id=bob.id,
                    topic_id=topic.id,
                    chain_behavior="accept_sub",
                ),
            },
        },
        all_precedences={alice.id: {topic.id: 0}},
        direct_votes={carol.id: "yes"},  # carol votes yes directly
    )

    # Eligible voters for a sub-org proposal = sub-org members only.
    proposal = models.Proposal(
        title="t", body="", author_id=alice.id, status="voting",
        org_id=parent.id, sub_org_id=sub.id,
    )
    db.add(proposal)
    db.flush()
    eligible = eligible_voter_ids_for_proposal(db, proposal)
    assert eligible == {alice.id, carol.id}

    # Tally over sub-org members only.
    tally = compute_tally_pure(sorted(eligible), ctx)
    # alice's chain didn't resolve (bob didn't vote, no fallback), carol = yes
    assert tally.yes == 1
    assert tally.no == 0
    assert tally.not_cast == 1
    assert tally.total_eligible == 2
    # The KEY assertion: non-member-delegate "no vote" landed in not_cast,
    # exactly as if alice's delegate had simply abstained. No special path.


def test_single_org_regression_with_no_sub_org_present(db):
    """Sanity: an org with no sub-orgs behaves identically to pre-Phase-8.5.
    Pure-layer resolution is unchanged for parent-org-only flows."""
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    topic = make_topic(db, "Healthcare")
    proposal = make_proposal(db, alice, topic_ids=[topic.id])
    cast_direct_vote(db, alice, proposal, "yes")
    cast_direct_vote(db, bob, proposal, "no")
    db.flush()

    eligible = eligible_voter_ids_for_proposal(db, proposal)
    # No sub-org, no org_id → "all users" path.
    assert eligible == {alice.id, bob.id}
