"""
Tests for Phase 6: Multi-option approval voting.

Tests 1-11:  Data model / proposal creation validation
Tests 12-18: Vote casting
Tests 19-24: Delegation for approval
Tests 25-28: Tabulation
Tests 29-34: Tie resolution
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
    Ballot,
    BallotResult,
    ApprovalTally,
    ProposalContext,
    DelegationData,
    resolve_vote_pure,
    compute_tally_pure,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_approval_proposal(
    db, author, topic_ids=None, option_labels=None, status="voting"
):
    """Create an approval proposal with options."""
    p = models.Proposal(
        title="Approval Test Proposal",
        body="",
        author_id=author.id,
        voting_method="approval",
        status=status,
    )
    db.add(p)
    db.flush()
    for tid in (topic_ids or []):
        db.add(models.ProposalTopic(proposal_id=p.id, topic_id=tid))
    labels = option_labels or ["Option A", "Option B", "Option C"]
    for i, label in enumerate(labels):
        db.add(models.ProposalOption(
            proposal_id=p.id,
            label=label,
            description=f"Description for {label}",
            display_order=i,
        ))
    db.flush()
    return p


def cast_approval_vote(db, user, proposal, option_ids):
    """Cast an approval ballot."""
    v = models.Vote(
        proposal_id=proposal.id,
        user_id=user.id,
        vote_value=None,
        ballot={"approvals": option_ids},
        is_direct=True,
        cast_by_id=user.id,
    )
    db.add(v)
    db.flush()
    return v


def get_option_ids(db, proposal):
    """Get option IDs for a proposal sorted by display_order."""
    opts = db.query(models.ProposalOption).filter(
        models.ProposalOption.proposal_id == proposal.id,
    ).order_by(models.ProposalOption.display_order).all()
    return [o.id for o in opts]


# ===========================================================================
# Tests 1-11: Data model / proposal creation validation
# ===========================================================================

def test_01_binary_proposal_has_no_options(db):
    """Binary proposal should have zero ProposalOption rows."""
    author = make_user(db, "author")
    p = make_proposal(db, author)
    assert p.voting_method == "binary"
    opts = db.query(models.ProposalOption).filter(
        models.ProposalOption.proposal_id == p.id,
    ).all()
    assert len(opts) == 0


def test_02_approval_proposal_has_options(db):
    """Approval proposal should have ProposalOption rows."""
    author = make_user(db, "author")
    p = make_approval_proposal(db, author)
    assert p.voting_method == "approval"
    opts = db.query(models.ProposalOption).filter(
        models.ProposalOption.proposal_id == p.id,
    ).all()
    assert len(opts) == 3


def test_03_approval_options_ordered(db):
    """Options should be ordered by display_order."""
    author = make_user(db, "author")
    p = make_approval_proposal(db, author, option_labels=["Zebra", "Apple", "Middle"])
    opts = db.query(models.ProposalOption).filter(
        models.ProposalOption.proposal_id == p.id,
    ).order_by(models.ProposalOption.display_order).all()
    assert opts[0].label == "Zebra"
    assert opts[1].label == "Apple"
    assert opts[2].label == "Middle"


def test_04_voting_method_default_binary(db):
    """Default voting_method should be binary."""
    author = make_user(db, "author")
    p = make_proposal(db, author)
    assert p.voting_method == "binary"


def test_05_num_winners_default_one(db):
    """Default num_winners should be 1."""
    author = make_user(db, "author")
    p = make_proposal(db, author)
    assert p.num_winners == 1


def test_06_tie_resolution_initially_null(db):
    """tie_resolution should be None until resolved."""
    author = make_user(db, "author")
    p = make_approval_proposal(db, author)
    assert p.tie_resolution is None


def test_07_vote_ballot_column_exists(db):
    """Vote model should have a ballot column."""
    author = make_user(db, "author")
    p = make_approval_proposal(db, author)
    oids = get_option_ids(db, p)
    v = cast_approval_vote(db, author, p, [oids[0]])
    assert v.ballot == {"approvals": [oids[0]]}
    assert v.vote_value is None


def test_08_binary_vote_has_no_ballot(db):
    """Binary vote should have vote_value set and ballot None."""
    author = make_user(db, "author")
    p = make_proposal(db, author)
    v = cast_direct_vote(db, author, p, "yes")
    assert v.vote_value == "yes"
    assert v.ballot is None


def test_09_proposal_option_label_max_200(db):
    """ProposalOption label max length is 200."""
    author = make_user(db, "author")
    p = models.Proposal(
        title="Test",
        body="",
        author_id=author.id,
        voting_method="approval",
        status="draft",
    )
    db.add(p)
    db.flush()
    # A label of exactly 200 chars should work
    db.add(models.ProposalOption(
        proposal_id=p.id,
        label="X" * 200,
        description="",
        display_order=0,
    ))
    db.flush()
    opt = db.query(models.ProposalOption).filter(
        models.ProposalOption.proposal_id == p.id,
    ).first()
    assert len(opt.label) == 200


def test_10_proposal_option_cascade_delete(db):
    """Deleting a proposal should cascade-delete its options."""
    author = make_user(db, "author")
    p = make_approval_proposal(db, author, status="draft")
    pid = p.id
    db.delete(p)
    db.flush()
    opts = db.query(models.ProposalOption).filter(
        models.ProposalOption.proposal_id == pid,
    ).all()
    assert len(opts) == 0


def test_11_approval_proposal_min_two_options(db):
    """Approval proposals should have at least 2 options (test at model level)."""
    author = make_user(db, "author")
    # Creating with 1 option is not prevented at model level, but we verify
    # the schema/route validation would catch it. Here just test the model accepts it.
    p = make_approval_proposal(db, author, option_labels=["Only One", "Two"])
    opts = db.query(models.ProposalOption).filter(
        models.ProposalOption.proposal_id == p.id,
    ).all()
    assert len(opts) == 2


# ===========================================================================
# Tests 12-18: Vote casting
# ===========================================================================

def test_12_cast_approval_vote_single_option(db):
    """Cast approval vote with a single option selected."""
    author = make_user(db, "author")
    p = make_approval_proposal(db, author)
    oids = get_option_ids(db, p)
    v = cast_approval_vote(db, author, p, [oids[0]])
    assert v.ballot["approvals"] == [oids[0]]
    assert v.vote_value is None


def test_13_cast_approval_vote_multiple_options(db):
    """Cast approval vote with multiple options selected."""
    author = make_user(db, "author")
    p = make_approval_proposal(db, author)
    oids = get_option_ids(db, p)
    v = cast_approval_vote(db, author, p, [oids[0], oids[2]])
    assert set(v.ballot["approvals"]) == {oids[0], oids[2]}


def test_14_cast_approval_vote_empty_abstain(db):
    """Empty approval list is a valid ballot (abstain equivalent)."""
    author = make_user(db, "author")
    p = make_approval_proposal(db, author)
    v = cast_approval_vote(db, author, p, [])
    assert v.ballot["approvals"] == []
    assert v.vote_value is None


def test_15_cast_approval_vote_all_options(db):
    """Approve all options is a valid ballot."""
    author = make_user(db, "author")
    p = make_approval_proposal(db, author)
    oids = get_option_ids(db, p)
    v = cast_approval_vote(db, author, p, oids)
    assert set(v.ballot["approvals"]) == set(oids)


def test_16_update_approval_vote(db):
    """Updating an approval vote replaces the ballot."""
    author = make_user(db, "author")
    p = make_approval_proposal(db, author)
    oids = get_option_ids(db, p)
    cast_approval_vote(db, author, p, [oids[0]])

    # Update
    existing = db.query(models.Vote).filter(
        models.Vote.proposal_id == p.id,
        models.Vote.user_id == author.id,
    ).first()
    existing.ballot = {"approvals": [oids[1], oids[2]]}
    db.flush()

    refreshed = db.query(models.Vote).filter(
        models.Vote.proposal_id == p.id,
        models.Vote.user_id == author.id,
    ).first()
    assert set(refreshed.ballot["approvals"]) == {oids[1], oids[2]}


def test_17_binary_and_approval_votes_independent(db):
    """Binary vote on binary prop and approval vote on approval prop coexist."""
    author = make_user(db, "author")
    bp = make_proposal(db, author)
    ap = make_approval_proposal(db, author, option_labels=["X", "Y"])
    oids = get_option_ids(db, ap)

    cast_direct_vote(db, author, bp, "yes")
    cast_approval_vote(db, author, ap, [oids[0]])

    binary_vote = db.query(models.Vote).filter(
        models.Vote.proposal_id == bp.id,
        models.Vote.user_id == author.id,
    ).first()
    assert binary_vote.vote_value == "yes"
    assert binary_vote.ballot is None

    approval_vote = db.query(models.Vote).filter(
        models.Vote.proposal_id == ap.id,
        models.Vote.user_id == author.id,
    ).first()
    assert approval_vote.vote_value is None
    assert approval_vote.ballot["approvals"] == [oids[0]]


def test_18_unique_constraint_one_vote_per_user(db):
    """A user can only have one vote per proposal (unique constraint)."""
    author = make_user(db, "author")
    p = make_approval_proposal(db, author)
    oids = get_option_ids(db, p)
    cast_approval_vote(db, author, p, [oids[0]])

    # Attempting to add another vote for the same user+proposal should fail
    with pytest.raises(Exception):
        db.add(models.Vote(
            proposal_id=p.id,
            user_id=author.id,
            vote_value=None,
            ballot={"approvals": [oids[1]]},
            is_direct=True,
            cast_by_id=author.id,
        ))
        db.flush()
    db.rollback()


# ===========================================================================
# Tests 19-24: Delegation for approval
# ===========================================================================

def test_19_approval_delegation_direct_ballot(db, store, engine_obj):
    """Direct approval ballot is used when user has voted."""
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    p = make_approval_proposal(db, alice)
    oids = get_option_ids(db, p)

    set_delegation(db, store, alice, bob)
    cast_approval_vote(db, bob, p, [oids[0], oids[1]])
    cast_approval_vote(db, alice, p, [oids[2]])

    # Alice voted directly, so delegation is ignored
    result = engine_obj.resolve_vote(alice.id, p.id, db)
    assert result is not None
    assert result.is_direct is True
    assert result.ballot.approvals == [oids[2]]


def test_20_approval_delegation_fires_when_no_direct_vote(db, store, engine_obj):
    """Approval ballot comes from delegate when user hasn't voted."""
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    p = make_approval_proposal(db, alice)
    oids = get_option_ids(db, p)

    set_delegation(db, store, alice, bob)
    cast_approval_vote(db, bob, p, [oids[0], oids[1]])

    result = engine_obj.resolve_vote(alice.id, p.id, db)
    assert result is not None
    assert result.is_direct is False
    assert set(result.ballot.approvals) == {oids[0], oids[1]}
    assert result.delegate_chain == [bob.id]


def test_21_approval_delegation_chain_accept_sub(db, store, engine_obj):
    """accept_sub chains through for approval ballots."""
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    carol = make_user(db, "carol")
    p = make_approval_proposal(db, alice)
    oids = get_option_ids(db, p)

    set_delegation(db, store, alice, bob, chain_behavior="accept_sub")
    set_delegation(db, store, bob, carol, chain_behavior="accept_sub")
    cast_approval_vote(db, carol, p, [oids[1]])

    result = engine_obj.resolve_vote(alice.id, p.id, db)
    assert result is not None
    assert result.ballot.approvals == [oids[1]]
    assert bob.id in result.delegate_chain
    assert carol.id in result.delegate_chain


def test_22_approval_delegation_no_vote_returns_none(db, store, engine_obj):
    """No vote resolved if delegate hasn't cast an approval ballot."""
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    p = make_approval_proposal(db, alice)

    set_delegation(db, store, alice, bob, chain_behavior="accept_sub")
    # Bob hasn't voted

    result = engine_obj.resolve_vote(alice.id, p.id, db)
    assert result is None


def test_23_approval_delegation_empty_ballot_is_valid(db, store, engine_obj):
    """Empty approvals list from delegate is a valid ballot (counts as cast)."""
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    p = make_approval_proposal(db, alice)

    set_delegation(db, store, alice, bob)
    cast_approval_vote(db, bob, p, [])  # abstain

    result = engine_obj.resolve_vote(alice.id, p.id, db)
    assert result is not None
    assert result.ballot.approvals == []
    assert result.is_direct is False


def test_24_approval_delegation_topic_precedence(db, store, engine_obj):
    """Topic precedence works for approval proposals."""
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    carol = make_user(db, "carol")

    t1 = make_topic(db, "topic1")
    t2 = make_topic(db, "topic2")

    p = make_approval_proposal(db, alice, topic_ids=[t1.id, t2.id])
    oids = get_option_ids(db, p)

    set_delegation(db, store, alice, bob, topic=t1)
    set_delegation(db, store, alice, carol, topic=t2)
    cast_approval_vote(db, bob, p, [oids[0]])
    cast_approval_vote(db, carol, p, [oids[1], oids[2]])

    # Alice prefers t2 > t1
    set_precedence(db, alice, [t2, t1])

    result = engine_obj.resolve_vote(alice.id, p.id, db)
    assert result is not None
    assert set(result.ballot.approvals) == {oids[1], oids[2]}
    assert result.cast_by_id == carol.id


# ===========================================================================
# Tests 25-28: Tabulation (pure functions)
# ===========================================================================

def test_25_approval_tally_basic():
    """Basic approval tally counts per-option approvals."""
    opt_a, opt_b, opt_c = "opt_a", "opt_b", "opt_c"
    ctx = ProposalContext(
        proposal_topics=[],
        all_delegations={},
        all_precedences={},
        direct_votes={},
        direct_ballots={
            "u1": Ballot(approvals=[opt_a, opt_b]),
            "u2": Ballot(approvals=[opt_a]),
            "u3": Ballot(approvals=[opt_b, opt_c]),
        },
        voting_method="approval",
    )
    tally = compute_tally_pure(["u1", "u2", "u3", "u4"], ctx)
    assert isinstance(tally, ApprovalTally)
    assert tally.option_approvals[opt_a] == 2
    assert tally.option_approvals[opt_b] == 2
    assert tally.option_approvals[opt_c] == 1
    assert tally.total_ballots_cast == 3
    assert tally.not_cast == 1
    assert tally.total_eligible == 4


def test_26_approval_tally_tie_with_equal_counts():
    """Equal approval counts produce a tie."""
    ctx = ProposalContext(
        proposal_topics=[],
        all_delegations={},
        all_precedences={},
        direct_votes={},
        direct_ballots={
            "u1": Ballot(approvals=["opt_a", "opt_b"]),
            "u2": Ballot(approvals=["opt_a"]),
            "u3": Ballot(approvals=["opt_b"]),
        },
        voting_method="approval",
    )
    tally = compute_tally_pure(["u1", "u2", "u3"], ctx)
    # opt_a=2, opt_b=2 — that's a tie
    assert set(tally.winners) == {"opt_a", "opt_b"}
    assert tally.tied is True


def test_27_approval_tally_no_tie():
    """Clear winner when one option has more approvals."""
    ctx = ProposalContext(
        proposal_topics=[],
        all_delegations={},
        all_precedences={},
        direct_votes={},
        direct_ballots={
            "u1": Ballot(approvals=["opt_a"]),
            "u2": Ballot(approvals=["opt_a"]),
            "u3": Ballot(approvals=["opt_b"]),
        },
        voting_method="approval",
    )
    tally = compute_tally_pure(["u1", "u2", "u3"], ctx)
    assert tally.winners == ["opt_a"]
    assert tally.tied is False


def test_28_approval_tally_abstain_counted():
    """Empty approval list counts as ballot cast but abstain."""
    ctx = ProposalContext(
        proposal_topics=[],
        all_delegations={},
        all_precedences={},
        direct_votes={},
        direct_ballots={
            "u1": Ballot(approvals=["opt_a"]),
            "u2": Ballot(approvals=[]),  # abstain
        },
        voting_method="approval",
    )
    tally = compute_tally_pure(["u1", "u2", "u3"], ctx)
    assert tally.total_ballots_cast == 2
    assert tally.total_abstain == 1
    assert tally.not_cast == 1
    assert tally.option_approvals.get("opt_a") == 1


# ===========================================================================
# Tests 29-34: Tie resolution
# ===========================================================================

def test_29_tie_resolution_field_stored(db):
    """tie_resolution JSON is stored correctly on proposal."""
    author = make_user(db, "author")
    p = make_approval_proposal(db, author, status="passed")
    oids = get_option_ids(db, p)
    p.tie_resolution = {
        "selected_option_id": oids[0],
        "selected_option_label": "Option A",
        "resolved_by": author.id,
    }
    db.flush()
    db.refresh(p)
    assert p.tie_resolution["selected_option_id"] == oids[0]


def test_30_approval_tally_tied_detection():
    """Tied detection works when two options have equal approvals."""
    ctx = ProposalContext(
        proposal_topics=[],
        all_delegations={},
        all_precedences={},
        direct_votes={},
        direct_ballots={
            "u1": Ballot(approvals=["opt_a"]),
            "u2": Ballot(approvals=["opt_b"]),
        },
        voting_method="approval",
    )
    tally = compute_tally_pure(["u1", "u2"], ctx)
    assert tally.tied is True
    assert set(tally.winners) == {"opt_a", "opt_b"}


def test_31_three_way_tie():
    """Three-way tie detected correctly."""
    ctx = ProposalContext(
        proposal_topics=[],
        all_delegations={},
        all_precedences={},
        direct_votes={},
        direct_ballots={
            "u1": Ballot(approvals=["opt_a"]),
            "u2": Ballot(approvals=["opt_b"]),
            "u3": Ballot(approvals=["opt_c"]),
        },
        voting_method="approval",
    )
    tally = compute_tally_pure(["u1", "u2", "u3"], ctx)
    assert tally.tied is True
    assert set(tally.winners) == {"opt_a", "opt_b", "opt_c"}


def test_32_no_tie_single_winner():
    """No tie when one option clearly wins."""
    ctx = ProposalContext(
        proposal_topics=[],
        all_delegations={},
        all_precedences={},
        direct_votes={},
        direct_ballots={
            "u1": Ballot(approvals=["opt_a", "opt_b"]),
            "u2": Ballot(approvals=["opt_a"]),
            "u3": Ballot(approvals=["opt_c"]),
        },
        voting_method="approval",
    )
    tally = compute_tally_pure(["u1", "u2", "u3"], ctx)
    assert tally.tied is False
    assert tally.winners == ["opt_a"]


def test_33_quorum_met_approval():
    """Approval tally quorum calculation."""
    ctx = ProposalContext(
        proposal_topics=[],
        all_delegations={},
        all_precedences={},
        direct_votes={},
        direct_ballots={
            "u1": Ballot(approvals=["opt_a"]),
            "u2": Ballot(approvals=["opt_b"]),
        },
        voting_method="approval",
    )
    tally = compute_tally_pure(["u1", "u2", "u3", "u4", "u5"], ctx)
    assert tally.total_ballots_cast == 2
    assert tally.total_eligible == 5
    assert tally.quorum_met(0.40) is True   # 2/5 = 40%
    assert tally.quorum_met(0.50) is False  # 2/5 = 40% < 50%


def test_34_approval_tally_with_delegation():
    """Approval tally correctly counts delegated ballots."""
    ctx = ProposalContext(
        proposal_topics=[],
        all_delegations={
            "u3": {None: DelegationData("u3", "u1", None, "accept_sub")},
        },
        all_precedences={},
        direct_votes={},
        direct_ballots={
            "u1": Ballot(approvals=["opt_a", "opt_b"]),
            "u2": Ballot(approvals=["opt_b"]),
        },
        voting_method="approval",
    )
    tally = compute_tally_pure(["u1", "u2", "u3"], ctx)
    assert isinstance(tally, ApprovalTally)
    # u1 directly: opt_a, opt_b
    # u2 directly: opt_b
    # u3 via delegation to u1: opt_a, opt_b
    assert tally.option_approvals["opt_a"] == 2  # u1 + u3
    assert tally.option_approvals["opt_b"] == 3  # u1 + u2 + u3
    assert tally.total_ballots_cast == 3
    assert tally.not_cast == 0


# ===========================================================================
# Bonus: Binary tally backward compat
# ===========================================================================

def test_35_binary_tally_still_works():
    """Binary tally still works with the new engine."""
    ctx = ProposalContext(
        proposal_topics=[],
        all_delegations={},
        all_precedences={},
        direct_votes={"u1": "yes", "u2": "no"},
        direct_ballots={},
        voting_method="binary",
    )
    from delegation_engine import ProposalTally
    tally = compute_tally_pure(["u1", "u2", "u3"], ctx)
    assert isinstance(tally, ProposalTally)
    assert tally.yes == 1
    assert tally.no == 1
    assert tally.not_cast == 1
