"""
Tests for the delegation resolution engine.

Covers every edge case listed in the brief:
  1. Direct vote overrides delegation
  2. Topic precedence ordering
  3. Chain behavior: accept_sub, revert_direct, abstain
  4. Cycle prevention
  5. Global vs topic-specific delegation fallback
  6. Delegation change during voting window updates tallies
"""

import pytest
from tests.conftest import (
    make_user,
    make_topic,
    make_proposal,
    cast_direct_vote,
    set_delegation,
    set_precedence,
)
import models
from delegation_engine import DelegationGraphStore, DelegationEngine


# ---------------------------------------------------------------------------
# 1. Direct vote overrides delegation
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# 2. Delegation fires when no direct vote
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# 3. No vote at all when no delegation and no direct vote
# ---------------------------------------------------------------------------

def test_no_vote_when_no_delegation_no_direct(db, store, engine_obj):
    alice = make_user(db, "alice")
    proposal = make_proposal(db, alice)

    result = engine_obj.resolve_vote(alice.id, proposal.id, db)
    assert result is None


# ---------------------------------------------------------------------------
# 4. Topic precedence ordering — highest priority topic wins
# ---------------------------------------------------------------------------

def test_topic_precedence_highest_priority_wins(db, store, engine_obj):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")    # alice's healthcare delegate
    carol = make_user(db, "carol")  # alice's economy delegate

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
    assert result.vote_value == "yes"  # followed bob (healthcare delegate)
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
    assert result.vote_value == "no"  # followed carol (economy delegate)
    assert result.cast_by_id == carol.id


# ---------------------------------------------------------------------------
# 5. Global (topic=None) delegation fallback
# ---------------------------------------------------------------------------

def test_global_delegation_fallback(db, store, engine_obj):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    carol = make_user(db, "carol")

    healthcare = make_topic(db, "healthcare")
    proposal = make_proposal(db, alice, topic_ids=[healthcare.id])

    # Alice has a global delegation to carol, but no topic-specific one
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

    set_delegation(db, store, alice, bob, topic=healthcare)  # topic-specific
    set_delegation(db, store, alice, carol, topic=None)       # global
    cast_direct_vote(db, bob, proposal, "yes")
    cast_direct_vote(db, carol, proposal, "no")

    # Topic-specific delegation should win
    result = engine_obj.resolve_vote(alice.id, proposal.id, db)
    assert result is not None
    assert result.vote_value == "yes"
    assert result.cast_by_id == bob.id


# ---------------------------------------------------------------------------
# 6. Chain behavior — accept_sub
# ---------------------------------------------------------------------------

def test_chain_accept_sub_follows_sub_delegate(db, store, engine_obj):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")    # alice's delegate, did NOT vote
    carol = make_user(db, "carol")  # bob's delegate, voted YES

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
    carol = make_user(db, "carol")  # carol also didn't vote

    proposal = make_proposal(db, alice)

    set_delegation(db, store, alice, bob, chain_behavior="accept_sub")
    set_delegation(db, store, bob, carol, chain_behavior="accept_sub")
    # Nobody votes

    result = engine_obj.resolve_vote(alice.id, proposal.id, db)
    assert result is None


# ---------------------------------------------------------------------------
# 7. Chain behavior — revert_direct
# ---------------------------------------------------------------------------

def test_chain_revert_direct_returns_none(db, store, engine_obj):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")  # did NOT vote

    proposal = make_proposal(db, alice)
    set_delegation(db, store, alice, bob, chain_behavior="revert_direct")

    result = engine_obj.resolve_vote(alice.id, proposal.id, db)
    assert result is None  # needs alice to vote directly


# ---------------------------------------------------------------------------
# 8. Chain behavior — abstain
# ---------------------------------------------------------------------------

def test_chain_abstain_returns_none(db, store, engine_obj):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")

    proposal = make_proposal(db, alice)
    set_delegation(db, store, alice, bob, chain_behavior="abstain")

    result = engine_obj.resolve_vote(alice.id, proposal.id, db)
    assert result is None


# ---------------------------------------------------------------------------
# 9. Cycle prevention in the graph store
# ---------------------------------------------------------------------------

def test_cycle_prevention_simple(store):
    """A -> B -> A would be a cycle."""
    store.add_delegation("A", "B", topic_id=None)
    assert store.would_create_cycle("B", "A", topic_id=None) is True


def test_cycle_prevention_transitive(store):
    """A -> B -> C; adding C -> A is a cycle."""
    store.add_delegation("A", "B", topic_id=None)
    store.add_delegation("B", "C", topic_id=None)
    assert store.would_create_cycle("C", "A", topic_id=None) is True


def test_no_false_positive_cycle(store):
    """A -> B and A -> C is not a cycle."""
    store.add_delegation("A", "B", topic_id=None)
    assert store.would_create_cycle("A", "C", topic_id=None) is False


def test_cycle_prevention_per_topic(store):
    """
    A -> B on topic1.  B -> A on topic2 is fine (different graph).
    But B -> A on topic1 is a cycle.
    """
    store.add_delegation("A", "B", topic_id="topic1")
    assert store.would_create_cycle("B", "A", topic_id="topic2") is False
    assert store.would_create_cycle("B", "A", topic_id="topic1") is True


# ---------------------------------------------------------------------------
# 10. Delegation update mid-vote-window changes tallies
# ---------------------------------------------------------------------------

def test_tally_updates_when_delegation_changes(db, store, engine_obj):
    """
    Alice delegates to Bob (votes YES). Tally: YES.
    Alice then re-delegates to Carol (votes NO). Tally: NO.
    """
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    carol = make_user(db, "carol")
    proposal = make_proposal(db, alice)

    set_delegation(db, store, alice, bob)
    cast_direct_vote(db, bob, proposal, "yes")
    cast_direct_vote(db, carol, proposal, "no")

    result_before = engine_obj.resolve_vote(alice.id, proposal.id, db)
    assert result_before.vote_value == "yes"

    # Alice changes delegation to carol
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


# ---------------------------------------------------------------------------
# 11. Tally aggregation
# ---------------------------------------------------------------------------

def test_compute_tally(db, store, engine_obj):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    carol = make_user(db, "carol")
    dave = make_user(db, "dave")

    proposal = make_proposal(db, alice)

    cast_direct_vote(db, alice, proposal, "yes")
    cast_direct_vote(db, bob, proposal, "no")
    # carol delegates to alice
    set_delegation(db, store, carol, alice)
    # dave has no vote, no delegation

    tally = engine_obj.compute_tally(proposal, db)
    assert tally.yes == 2    # alice + carol (via delegation)
    assert tally.no == 1     # bob
    assert tally.not_cast == 1  # dave
    assert tally.total_eligible == 4


# ---------------------------------------------------------------------------
# 12. Self-delegation prevention via graph store
# ---------------------------------------------------------------------------

def test_self_delegation_cycle(store):
    """A -> A is a cycle."""
    assert store.would_create_cycle("A", "A", topic_id=None) is True
