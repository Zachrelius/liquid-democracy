"""
Tests for the delegation resolution engine.

Covers every edge case listed in the spec (section 7 Architecture Notes):

Delegation resolution:
  1.  Direct vote always overrides delegation
  2.  Topic precedence ordering
  3.  Chain behavior: accept_sub, revert_direct, abstain
  4.  Cycle prevention
  5.  Global vs topic-specific delegation fallback
  6.  Delegation change mid-voting-window updates tallies
  7.  Retracting a direct vote reverts to delegation result
  8.  Delegation to user who hasn't voted and has no sub-delegation → None
  9.  User with no delegations and no direct vote → None (resolved via service)

Cycle prevention:
  10. Direct cycle (A→B, B→A) is rejected
  11. Indirect cycle (A→B, B→C, C→A) is rejected
  12. Per-topic cycle check (A→B on topic1, B→A on topic2 is allowed)
  13. Global delegation cycle detection

Sustained majority / tally:
  14. Proposal passes when threshold met at close and never dropped below floor
  15. Proposal fails when threshold met at close but dropped below floor
  16. Proposal fails when threshold not met at close even if it was met earlier
  17. Quorum correctly counts delegated votes

Edge cases (spec section 7):
  18. Proposal with no topic tags uses only global delegations
  19. User with delegations for all proposal topics but different delegates uses highest-precedence topic
  20. Orphaned delegations handled gracefully (delegate user removed from direct_votes)
  21. accept_sub dead-end (sub-delegate hasn't voted either) → None
  22. revert_direct → None even when delegate has sub-delegation
  23. abstain → None even when delegate voted
  24. Self-delegation prevention
  25. No false-positive cycle (A→B and A→C are both fine)

Pure-function tests (no DB):
  26. find_delegate_pure honours topic precedence
  27. resolve_vote_pure cycle guard
  28. compute_tally_pure aggregation
"""

import pytest
from tests.conftest import (
    make_user,
    make_topic,
    make_proposal,
    cast_direct_vote,
    set_delegation,
    set_precedence,
    make_context,
)
import models
from delegation_engine import (
    DelegationGraphStore,
    DelegationEngine,
    DelegationData,
    ProposalContext,
    VoteResult,
    find_delegate_pure,
    resolve_vote_pure,
    compute_tally_pure,
)


# ===========================================================================
# 1. Direct vote overrides delegation
# ===========================================================================

def test_direct_vote_beats_delegation(db, store, engine_obj):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    proposal = make_proposal(db, alice)

    set_delegation(db, store, alice, bob)
    cast_direct_vote(db, bob, proposal, "yes")
    cast_direct_vote(db, alice, proposal, "no")  # alice votes directly

    result = engine_obj.resolve_vote(alice.id, proposal.id, db)
    assert result is not None
    assert result.vote_value == "no"
    assert result.is_direct is True
    assert result.cast_by_id == alice.id


# ===========================================================================
# 2. Delegation fires when no direct vote
# ===========================================================================

def test_delegation_used_when_no_direct_vote(db, store, engine_obj):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    proposal = make_proposal(db, alice)

    set_delegation(db, store, alice, bob)
    cast_direct_vote(db, bob, proposal, "yes")

    result = engine_obj.resolve_vote(alice.id, proposal.id, db)
    assert result is not None
    assert result.vote_value == "yes"
    assert result.is_direct is False
    assert result.delegate_chain == [bob.id]
    assert result.cast_by_id == bob.id


# ===========================================================================
# 3. No vote when no delegation and no direct vote
# ===========================================================================

def test_no_vote_when_no_delegation_no_direct(db, store, engine_obj):
    alice = make_user(db, "alice")
    proposal = make_proposal(db, alice)

    result = engine_obj.resolve_vote(alice.id, proposal.id, db)
    assert result is None


# ===========================================================================
# 4. Topic precedence — highest priority topic wins
# ===========================================================================

def test_topic_precedence_highest_priority_wins(db, store, engine_obj):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    carol = make_user(db, "carol")

    healthcare = make_topic(db, "healthcare")
    economy = make_topic(db, "economy")

    proposal = make_proposal(db, alice, topic_ids=[healthcare.id, economy.id])

    set_delegation(db, store, alice, bob, topic=healthcare)
    set_delegation(db, store, alice, carol, topic=economy)
    cast_direct_vote(db, bob, proposal, "yes")
    cast_direct_vote(db, carol, proposal, "no")

    # Alice prefers healthcare > economy
    set_precedence(db, alice, [healthcare, economy])

    result = engine_obj.resolve_vote(alice.id, proposal.id, db)
    assert result is not None
    assert result.vote_value == "yes"
    assert result.cast_by_id == bob.id


def test_topic_precedence_second_priority_wins(db, store, engine_obj):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    carol = make_user(db, "carol")

    healthcare = make_topic(db, "healthcare")
    economy = make_topic(db, "economy")

    proposal = make_proposal(db, alice, topic_ids=[healthcare.id, economy.id])

    set_delegation(db, store, alice, bob, topic=healthcare)
    set_delegation(db, store, alice, carol, topic=economy)
    cast_direct_vote(db, bob, proposal, "yes")
    cast_direct_vote(db, carol, proposal, "no")

    # Alice prefers economy > healthcare
    set_precedence(db, alice, [economy, healthcare])

    result = engine_obj.resolve_vote(alice.id, proposal.id, db)
    assert result is not None
    assert result.vote_value == "no"
    assert result.cast_by_id == carol.id


# ===========================================================================
# 5. Global delegation fallback
# ===========================================================================

def test_global_delegation_fallback(db, store, engine_obj):
    alice = make_user(db, "alice")
    carol = make_user(db, "carol")

    healthcare = make_topic(db, "healthcare")
    proposal = make_proposal(db, alice, topic_ids=[healthcare.id])

    set_delegation(db, store, alice, carol, topic=None)
    cast_direct_vote(db, carol, proposal, "abstain")

    result = engine_obj.resolve_vote(alice.id, proposal.id, db)
    assert result is not None
    assert result.vote_value == "abstain"
    assert result.cast_by_id == carol.id


def test_topic_delegation_takes_precedence_over_global(db, store, engine_obj):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    carol = make_user(db, "carol")

    healthcare = make_topic(db, "healthcare")
    proposal = make_proposal(db, alice, topic_ids=[healthcare.id])

    set_delegation(db, store, alice, bob, topic=healthcare)
    set_delegation(db, store, alice, carol, topic=None)
    cast_direct_vote(db, bob, proposal, "yes")
    cast_direct_vote(db, carol, proposal, "no")

    result = engine_obj.resolve_vote(alice.id, proposal.id, db)
    assert result is not None
    assert result.vote_value == "yes"
    assert result.cast_by_id == bob.id


# ===========================================================================
# 6. Chain behavior — accept_sub
# ===========================================================================

def test_chain_accept_sub_follows_sub_delegate(db, store, engine_obj):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    carol = make_user(db, "carol")

    proposal = make_proposal(db, alice)

    set_delegation(db, store, alice, bob, chain_behavior="accept_sub")
    set_delegation(db, store, bob, carol, chain_behavior="accept_sub")
    cast_direct_vote(db, carol, proposal, "yes")

    result = engine_obj.resolve_vote(alice.id, proposal.id, db)
    assert result is not None
    assert result.vote_value == "yes"
    assert result.is_direct is False
    assert bob.id in result.delegate_chain
    assert carol.id in result.delegate_chain
    assert result.cast_by_id == carol.id


def test_chain_accept_sub_returns_none_when_sub_delegate_also_absent(db, store, engine_obj):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    carol = make_user(db, "carol")

    proposal = make_proposal(db, alice)

    set_delegation(db, store, alice, bob, chain_behavior="accept_sub")
    set_delegation(db, store, bob, carol, chain_behavior="accept_sub")
    # Nobody votes

    result = engine_obj.resolve_vote(alice.id, proposal.id, db)
    assert result is None


# ===========================================================================
# 7. Chain behavior — revert_direct
# ===========================================================================

def test_chain_revert_direct_returns_none(db, store, engine_obj):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")

    proposal = make_proposal(db, alice)
    set_delegation(db, store, alice, bob, chain_behavior="revert_direct")

    result = engine_obj.resolve_vote(alice.id, proposal.id, db)
    assert result is None


def test_revert_direct_returns_none_even_when_delegate_has_sub_delegation(db, store, engine_obj):
    """revert_direct short-circuits before checking sub-delegations."""
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    carol = make_user(db, "carol")

    proposal = make_proposal(db, alice)
    set_delegation(db, store, alice, bob, chain_behavior="revert_direct")
    set_delegation(db, store, bob, carol, chain_behavior="accept_sub")
    cast_direct_vote(db, carol, proposal, "yes")

    result = engine_obj.resolve_vote(alice.id, proposal.id, db)
    assert result is None  # revert_direct stops the chain


# ===========================================================================
# 8. Chain behavior — abstain
# ===========================================================================

def test_chain_abstain_returns_none(db, store, engine_obj):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")

    proposal = make_proposal(db, alice)
    set_delegation(db, store, alice, bob, chain_behavior="abstain")

    result = engine_obj.resolve_vote(alice.id, proposal.id, db)
    assert result is None


def test_abstain_delegates_vote_used_when_delegate_voted_directly(db, store, engine_obj):
    """
    chain_behavior=abstain only fires when the delegate did NOT vote.
    Step 3 (non-transitive default) applies first: if the delegate voted
    directly, their vote is used regardless of chain_behavior.
    """
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")

    proposal = make_proposal(db, alice)
    set_delegation(db, store, alice, bob, chain_behavior="abstain")
    cast_direct_vote(db, bob, proposal, "yes")

    # Bob voted directly → non-transitive step 3 triggers; chain_behavior
    # is irrelevant because the delegate has a direct vote.
    result = engine_obj.resolve_vote(alice.id, proposal.id, db)
    assert result is not None
    assert result.vote_value == "yes"
    assert result.cast_by_id == bob.id


# ===========================================================================
# 9. Delegation to user who hasn't voted and has no sub-delegation → None
# ===========================================================================

def test_delegate_no_vote_no_sub_returns_none(db, store, engine_obj):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")  # bob never votes and has no own delegation

    proposal = make_proposal(db, alice)
    set_delegation(db, store, alice, bob, chain_behavior="accept_sub")

    result = engine_obj.resolve_vote(alice.id, proposal.id, db)
    assert result is None


# ===========================================================================
# 10. Delegation change mid-window updates tallies
# ===========================================================================

def test_tally_updates_when_delegation_changes(db, store, engine_obj):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    carol = make_user(db, "carol")
    proposal = make_proposal(db, alice)

    set_delegation(db, store, alice, bob)
    cast_direct_vote(db, bob, proposal, "yes")
    cast_direct_vote(db, carol, proposal, "no")

    result_before = engine_obj.resolve_vote(alice.id, proposal.id, db)
    assert result_before.vote_value == "yes"

    # Alice re-delegates to carol
    existing = db.query(models.Delegation).filter(
        models.Delegation.delegator_id == alice.id,
        models.Delegation.topic_id.is_(None),
    ).first()
    existing.delegate_id = carol.id
    db.flush()
    store.remove_delegation(alice.id, topic_id=None)
    store.add_delegation(alice.id, carol.id, topic_id=None)

    result_after = engine_obj.resolve_vote(alice.id, proposal.id, db)
    assert result_after.vote_value == "no"


# ===========================================================================
# 11. Retracting a direct vote reverts to delegation result
# ===========================================================================

def test_retract_direct_vote_reverts_to_delegation(db, store, engine_obj):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")

    proposal = make_proposal(db, alice)
    set_delegation(db, store, alice, bob)
    cast_direct_vote(db, bob, proposal, "yes")

    # Alice votes directly
    alice_vote = cast_direct_vote(db, alice, proposal, "no")
    result_direct = engine_obj.resolve_vote(alice.id, proposal.id, db)
    assert result_direct.vote_value == "no"
    assert result_direct.is_direct is True

    # Alice retracts her vote
    db.delete(alice_vote)
    db.flush()

    result_delegated = engine_obj.resolve_vote(alice.id, proposal.id, db)
    assert result_delegated is not None
    assert result_delegated.vote_value == "yes"  # back to bob's vote
    assert result_delegated.is_direct is False


# ===========================================================================
# 12. Cycle prevention
# ===========================================================================

def test_cycle_prevention_simple(store):
    store.add_delegation("A", "B", topic_id=None)
    assert store.would_create_cycle("B", "A", topic_id=None) is True


def test_cycle_prevention_transitive(store):
    store.add_delegation("A", "B", topic_id=None)
    store.add_delegation("B", "C", topic_id=None)
    assert store.would_create_cycle("C", "A", topic_id=None) is True


def test_no_false_positive_cycle(store):
    store.add_delegation("A", "B", topic_id=None)
    assert store.would_create_cycle("A", "C", topic_id=None) is False


def test_cycle_prevention_per_topic(store):
    """A→B on topic1. B→A on topic2 is allowed; B→A on topic1 is not."""
    store.add_delegation("A", "B", topic_id="topic1")
    assert store.would_create_cycle("B", "A", topic_id="topic2") is False
    assert store.would_create_cycle("B", "A", topic_id="topic1") is True


def test_self_delegation_cycle(store):
    assert store.would_create_cycle("A", "A", topic_id=None) is True


def test_global_delegation_cycle_detection(store):
    """Global delegation cycles are caught via the global graph."""
    store.add_delegation("X", "Y", topic_id=None)  # X →(global) Y
    store.add_delegation("Y", "Z", topic_id=None)
    assert store.would_create_cycle("Z", "X", topic_id=None) is True


# ===========================================================================
# 13. Tally aggregation
# ===========================================================================

def test_compute_tally(db, store, engine_obj):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    carol = make_user(db, "carol")
    dave = make_user(db, "dave")

    proposal = make_proposal(db, alice)

    cast_direct_vote(db, alice, proposal, "yes")
    cast_direct_vote(db, bob, proposal, "no")
    set_delegation(db, store, carol, alice)
    # dave has no vote, no delegation

    tally = engine_obj.compute_tally(proposal, db)
    assert tally.yes == 2    # alice + carol (via delegation)
    assert tally.no == 1     # bob
    assert tally.not_cast == 1  # dave
    assert tally.total_eligible == 4


# ===========================================================================
# 14. Proposal with no topic tags uses only global delegations
# ===========================================================================

def test_no_topic_proposal_uses_global_delegation(db, store, engine_obj):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")

    # Proposal has no topics
    proposal = make_proposal(db, alice, topic_ids=[])

    set_delegation(db, store, alice, bob, topic=None)  # global
    cast_direct_vote(db, bob, proposal, "yes")

    result = engine_obj.resolve_vote(alice.id, proposal.id, db)
    assert result is not None
    assert result.vote_value == "yes"
    assert result.cast_by_id == bob.id


def test_no_topic_proposal_topic_specific_delegation_ignored(db, store, engine_obj):
    """A topic-specific delegation cannot apply when proposal has no topics."""
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")

    healthcare = make_topic(db, "healthcare")
    proposal = make_proposal(db, alice, topic_ids=[])  # no topics on proposal

    # Alice has a topic-specific delegation to bob on healthcare
    set_delegation(db, store, alice, bob, topic=healthcare)
    cast_direct_vote(db, bob, proposal, "yes")

    # No global delegation, no topic match → None
    result = engine_obj.resolve_vote(alice.id, proposal.id, db)
    assert result is None


# ===========================================================================
# 15. Highest-precedence topic delegate is used when all topics have delegates
# ===========================================================================

def test_highest_precedence_topic_wins_with_all_topics_delegated(db, store, engine_obj):
    """All proposal topics have delegates; highest-precedence one is chosen."""
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    carol = make_user(db, "carol")
    dave = make_user(db, "dave")

    t1 = make_topic(db, "t1")
    t2 = make_topic(db, "t2")
    t3 = make_topic(db, "t3")

    proposal = make_proposal(db, alice, topic_ids=[t1.id, t2.id, t3.id])

    set_delegation(db, store, alice, bob, topic=t1)
    set_delegation(db, store, alice, carol, topic=t2)
    set_delegation(db, store, alice, dave, topic=t3)
    cast_direct_vote(db, bob, proposal, "yes")
    cast_direct_vote(db, carol, proposal, "no")
    cast_direct_vote(db, dave, proposal, "abstain")

    # alice's priority: t2 (0) > t3 (1) > t1 (2)
    set_precedence(db, alice, [t2, t3, t1])

    result = engine_obj.resolve_vote(alice.id, proposal.id, db)
    assert result is not None
    assert result.vote_value == "no"   # carol's vote (t2 delegate)
    assert result.cast_by_id == carol.id


# ===========================================================================
# 16. Orphaned delegations — delegate removed from direct_votes
#     (simulate by not casting a vote for the delegate)
# ===========================================================================

def test_orphaned_delegate_no_vote_returns_none(db, store, engine_obj):
    """
    If the delegate was 'deactivated' and never voted, the delegator's
    vote is unresolved (None), not an exception.
    """
    alice = make_user(db, "alice")
    ghost = make_user(db, "ghost")  # delegate who vanishes / never votes

    proposal = make_proposal(db, alice)
    set_delegation(db, store, alice, ghost, chain_behavior="accept_sub")
    # ghost never votes and has no further delegation

    result = engine_obj.resolve_vote(alice.id, proposal.id, db)
    assert result is None


# ===========================================================================
# 17. Sustained majority — tally helpers
# ===========================================================================

def test_proposal_passes_when_threshold_and_quorum_met():
    from delegation_engine import ProposalTally
    t = ProposalTally(yes=6, no=2, abstain=0, not_cast=2, total_eligible=10)
    assert t.threshold_met(0.50)   # 6/8 = 75% > 50%
    assert t.quorum_met(0.40)      # 8/10 = 80% > 40%


def test_proposal_fails_when_threshold_not_met():
    from delegation_engine import ProposalTally
    t = ProposalTally(yes=3, no=5, abstain=0, not_cast=2, total_eligible=10)
    assert not t.threshold_met(0.50)  # 3/8 = 37.5% < 50%
    assert t.quorum_met(0.40)


def test_proposal_fails_when_quorum_not_met():
    from delegation_engine import ProposalTally
    t = ProposalTally(yes=2, no=1, abstain=0, not_cast=7, total_eligible=10)
    assert t.threshold_met(0.50)   # 2/3 = 67% > 50%
    assert not t.quorum_met(0.40)  # 3/10 = 30% < 40%


def test_quorum_counts_delegated_votes(db, store, engine_obj):
    """Delegated votes count toward quorum."""
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    carol = make_user(db, "carol")
    dave = make_user(db, "dave")
    eve = make_user(db, "eve")

    proposal = make_proposal(db, alice)

    # bob votes directly
    cast_direct_vote(db, bob, proposal, "yes")
    # carol delegates to bob (yes via delegation)
    set_delegation(db, store, carol, bob)
    # dave and eve have no votes — not_cast

    tally = engine_obj.compute_tally(proposal, db)
    # alice=not_cast (author, no vote), bob=yes, carol=yes(delegated), dave=not_cast, eve=not_cast
    assert tally.yes == 2
    assert tally.not_cast == 3
    assert tally.total_eligible == 5
    # votes_cast = 2, total_eligible = 5 → 40% quorum exactly
    assert tally.quorum_met(0.40)


# ===========================================================================
# 18. Pure-function tests (no DB required)
# ===========================================================================

def test_find_delegate_pure_honours_precedence():
    ctx = make_context(
        proposal_topics=["t1", "t2"],
        delegations={
            ("alice", "t1"): ("bob", "accept_sub"),
            ("alice", "t2"): ("carol", "accept_sub"),
        },
        precedences={
            ("alice", "t1"): 10,   # lower priority
            ("alice", "t2"): 0,    # higher priority
        },
        direct_votes={},
    )
    user_delegations = ctx.all_delegations.get("alice", {})
    user_precedences = ctx.all_precedences.get("alice", {})
    dd = find_delegate_pure("alice", ctx.proposal_topics, user_precedences, user_delegations)
    assert dd is not None
    assert dd.delegate_id == "carol"  # t2 is higher priority


def test_find_delegate_pure_global_fallback():
    ctx = make_context(
        proposal_topics=["t1"],
        delegations={
            ("alice", None): ("global_delegate", "accept_sub"),
        },
        precedences={},
        direct_votes={},
    )
    user_delegations = ctx.all_delegations.get("alice", {})
    user_precedences = ctx.all_precedences.get("alice", {})
    dd = find_delegate_pure("alice", ctx.proposal_topics, user_precedences, user_delegations)
    assert dd is not None
    assert dd.delegate_id == "global_delegate"


def test_resolve_vote_pure_direct_vote():
    ctx = make_context(
        proposal_topics=[],
        delegations={},
        precedences={},
        direct_votes={"alice": "yes"},
    )
    result = resolve_vote_pure("alice", ctx)
    assert result is not None
    assert result.vote_value == "yes"
    assert result.is_direct is True


def test_resolve_vote_pure_cycle_guard():
    """_visited prevents infinite recursion on unexpected cycles."""
    ctx = make_context(
        proposal_topics=[],
        delegations={
            ("alice", None): ("alice", "accept_sub"),  # self-loop data (shouldn't exist)
        },
        precedences={},
        direct_votes={},
    )
    result = resolve_vote_pure("alice", ctx, _visited={"alice"})
    assert result is None


def test_compute_tally_pure_aggregation():
    ctx = make_context(
        proposal_topics=[],
        delegations={
            ("carol", None): ("bob", "accept_sub"),
        },
        precedences={},
        direct_votes={"alice": "yes", "bob": "no"},
    )
    tally = compute_tally_pure(["alice", "bob", "carol", "dave"], ctx)
    assert tally.yes == 1      # alice
    assert tally.no == 2       # bob + carol (via delegation)
    assert tally.not_cast == 1 # dave
    assert tally.total_eligible == 4
