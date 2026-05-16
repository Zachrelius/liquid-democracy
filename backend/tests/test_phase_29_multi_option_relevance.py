"""Phase 29 — multi-option relevance-weighted delegation tests.

Covers backend cluster B1: find_vote_via_relevance_for_multi_option_pure
+ the dispatcher branch in resolve_vote_pure for approval/RCV/STV when
the user is on relevance_weighted strategy.

Pure-function tests use synthetic ProposalContext objects (no DB) so
the tests stay tight and don't need TestClient.
"""
from __future__ import annotations

import pytest

from delegation_engine import (
    Ballot,
    BallotResult,
    DelegationData,
    ProposalContext,
    find_vote_via_relevance_for_multi_option_pure,
    resolve_vote_pure,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ctx(
    *,
    proposal_topics: list[str],
    voting_method: str,
    relevances: dict[str, float] | None = None,
    delegations: dict[str, dict[str | None, DelegationData]] | None = None,
    precedences: dict[str, dict[str, int]] | None = None,
    direct_ballots: dict[str, Ballot] | None = None,
    user_strategies: dict[str, str] | None = None,
) -> ProposalContext:
    return ProposalContext(
        proposal_topics=proposal_topics,
        all_delegations=delegations or {},
        all_precedences=precedences or {},
        direct_votes={},
        direct_ballots=direct_ballots or {},
        voting_method=voting_method,
        proposal_topic_relevances=relevances or {},
        user_strategies=user_strategies or {},
    )


def _dd(delegate_id: str, topic_id: str | None, chain: str = "accept_sub") -> DelegationData:
    return DelegationData(
        delegator_id="alice",
        delegate_id=delegate_id,
        topic_id=topic_id,
        chain_behavior=chain,
    )


# ===========================================================================
# B1 — multi-option relevance resolver
# ===========================================================================

class TestApprovalRelevanceWeightedPicksHighestRelevanceBallot:
    """Approval proposal with two topics; the delegate on the
    higher-relevance topic supplies the user's effective ballot,
    verbatim. No merging."""

    def test_picks_alice_not_bob_not_merged(self):
        ctx = _ctx(
            proposal_topics=["A", "B"],
            voting_method="approval",
            relevances={"A": 0.7, "B": 0.3},
            delegations={
                "alice_user": {
                    "A": _dd("alice_d", "A"),
                    "B": _dd("bob_d", "B"),
                },
            },
            direct_ballots={
                "alice_d": Ballot(approvals=["opt1", "opt2"]),
                "bob_d": Ballot(approvals=["opt3"]),
            },
        )
        result = find_vote_via_relevance_for_multi_option_pure(
            user_id="alice_user",
            proposal_topics=["A", "B"],
            proposal_topic_relevances={"A": 0.7, "B": 0.3},
            user_precedences={},
            user_delegations={"A": _dd("alice_d", "A"), "B": _dd("bob_d", "B")},
            ctx=ctx,
        )
        assert result is not None
        assert result.ballot.approvals == ["opt1", "opt2"]
        # Crucially NOT merged ([opt1, opt2, opt3]) and NOT Bob's ([opt3]).
        assert "opt3" not in (result.ballot.approvals or [])
        assert result.delegate_chain == ["alice_d"]


class TestRankedChoiceRelevanceWeightedPicksHighestRelevanceBallot:
    """Same shape for RCV: highest-relevance delegate's ranking wins."""

    def test_picks_alice_ranking(self):
        ctx = _ctx(
            proposal_topics=["A", "B"],
            voting_method="ranked_choice",
            relevances={"A": 0.7, "B": 0.3},
            delegations={
                "alice_user": {
                    "A": _dd("alice_d", "A"),
                    "B": _dd("bob_d", "B"),
                },
            },
            direct_ballots={
                "alice_d": Ballot(ranking=["opt1", "opt2", "opt3"]),
                "bob_d": Ballot(ranking=["opt3", "opt2", "opt1"]),
            },
        )
        result = find_vote_via_relevance_for_multi_option_pure(
            user_id="alice_user",
            proposal_topics=["A", "B"],
            proposal_topic_relevances={"A": 0.7, "B": 0.3},
            user_precedences={},
            user_delegations={"A": _dd("alice_d", "A"), "B": _dd("bob_d", "B")},
            ctx=ctx,
        )
        assert result is not None
        assert result.ballot.ranking == ["opt1", "opt2", "opt3"]


class TestMultiOptionRelevanceTiebreakerByPrecedence:
    """Equal relevance → strict-precedence tiebreaker fires; higher-
    priority topic's delegate provides the ballot."""

    def test_a_wins_when_a_has_higher_precedence(self):
        ctx = _ctx(
            proposal_topics=["A", "B"],
            voting_method="approval",
            relevances={"A": 0.5, "B": 0.5},
            delegations={
                "alice_user": {
                    "A": _dd("alice_d", "A"),
                    "B": _dd("bob_d", "B"),
                },
            },
            direct_ballots={
                "alice_d": Ballot(approvals=["opt1"]),
                "bob_d": Ballot(approvals=["opt2"]),
            },
            precedences={"alice_user": {"A": 1, "B": 2}},
        )
        result = find_vote_via_relevance_for_multi_option_pure(
            user_id="alice_user",
            proposal_topics=["A", "B"],
            proposal_topic_relevances={"A": 0.5, "B": 0.5},
            user_precedences={"A": 1, "B": 2},
            user_delegations={"A": _dd("alice_d", "A"), "B": _dd("bob_d", "B")},
            ctx=ctx,
        )
        # A is priority 1 (higher); Alice wins.
        assert result.ballot.approvals == ["opt1"]

    def test_b_wins_when_b_has_higher_precedence(self):
        """Same setup, reversed precedence — Bob wins."""
        ctx = _ctx(
            proposal_topics=["A", "B"],
            voting_method="approval",
            relevances={"A": 0.5, "B": 0.5},
            delegations={
                "alice_user": {
                    "A": _dd("alice_d", "A"),
                    "B": _dd("bob_d", "B"),
                },
            },
            direct_ballots={
                "alice_d": Ballot(approvals=["opt1"]),
                "bob_d": Ballot(approvals=["opt2"]),
            },
            precedences={"alice_user": {"B": 1, "A": 2}},
        )
        result = find_vote_via_relevance_for_multi_option_pure(
            user_id="alice_user",
            proposal_topics=["A", "B"],
            proposal_topic_relevances={"A": 0.5, "B": 0.5},
            user_precedences={"B": 1, "A": 2},
            user_delegations={"A": _dd("alice_d", "A"), "B": _dd("bob_d", "B")},
            ctx=ctx,
        )
        assert result.ballot.approvals == ["opt2"]


class TestMultiOptionRelevanceIteratesPastUnresolvedDelegate:
    """When the highest-relevance delegate didn't vote and their chain
    fails (revert_direct), the resolver continues to the next-relevance
    topic instead of falling through to global. Bob's ballot wins."""

    def test_alice_silent_revert_direct_falls_to_bob_not_global(self):
        ctx = _ctx(
            proposal_topics=["A", "B"],
            voting_method="approval",
            relevances={"A": 0.7, "B": 0.3},
            delegations={
                "alice_user": {
                    "A": _dd("alice_d", "A", chain="revert_direct"),
                    "B": _dd("bob_d", "B"),
                },
            },
            # alice_d didn't vote; bob_d voted.
            direct_ballots={
                "bob_d": Ballot(approvals=["opt3"]),
            },
        )
        result = find_vote_via_relevance_for_multi_option_pure(
            user_id="alice_user",
            proposal_topics=["A", "B"],
            proposal_topic_relevances={"A": 0.7, "B": 0.3},
            user_precedences={},
            user_delegations={
                "A": _dd("alice_d", "A", chain="revert_direct"),
                "B": _dd("bob_d", "B"),
            },
            ctx=ctx,
        )
        assert result is not None
        assert result.ballot.approvals == ["opt3"]
        assert result.delegate_chain == ["bob_d"]


class TestMultiOptionRelevanceFallthroughWhenAllUnresolved:
    """When the user has only a global delegation (no topic-specific
    rows), the multi-option resolver returns None and the dispatcher
    falls through to find_delegate_pure, which picks up the global as
    final fallback. Verified through resolve_vote_pure. This confirms
    Phase 29's multi-option resolver doesn't break the global-fallback
    path for relevance_weighted users on multi-option proposals."""

    def test_global_delegate_carol_wins_via_strict_fallback(self):
        ctx = _ctx(
            proposal_topics=["A", "B"],
            voting_method="approval",
            relevances={"A": 0.7, "B": 0.3},
            delegations={
                "alice_user": {
                    None: _dd("carol_global", None),  # global only
                },
            },
            direct_ballots={
                "carol_global": Ballot(approvals=["opt_global"]),
            },
            user_strategies={"alice_user": "relevance_weighted"},
        )
        result = resolve_vote_pure(user_id="alice_user", ctx=ctx)
        assert result is not None
        assert result.ballot.approvals == ["opt_global"]
        assert result.cast_by_id == "carol_global"


# ===========================================================================
# Dispatcher integration — confirms voting_method routes correctly
# ===========================================================================

class TestDispatcherRoutesMultiOptionToNewResolver:
    """Approval proposal + relevance_weighted user: dispatcher activates
    the Phase 29 multi-option resolver (not Phase 27's binary summer)."""

    def test_approval_user_takes_multi_option_path(self):
        ctx = _ctx(
            proposal_topics=["A", "B"],
            voting_method="approval",
            relevances={"A": 0.9, "B": 0.1},
            delegations={
                "alice_user": {
                    "A": _dd("alice_d", "A"),
                    "B": _dd("bob_d", "B"),
                },
            },
            direct_ballots={
                "alice_d": Ballot(approvals=["high_relevance_pick"]),
                "bob_d": Ballot(approvals=["low_relevance_pick"]),
            },
            user_strategies={"alice_user": "relevance_weighted"},
        )
        result = resolve_vote_pure(user_id="alice_user", ctx=ctx)
        assert result is not None
        assert result.ballot.approvals == ["high_relevance_pick"]


class TestDispatcherStrictUserStillUsesStrictPath:
    """A strict_precedence user on a multi-option proposal — old
    behavior preserved, no change."""

    def test_strict_user_unaffected(self):
        ctx = _ctx(
            proposal_topics=["A", "B"],
            voting_method="approval",
            relevances={"A": 0.9, "B": 0.1},
            delegations={
                "alice_user": {
                    "A": _dd("alice_d", "A"),
                    "B": _dd("bob_d", "B"),
                },
            },
            direct_ballots={
                "alice_d": Ballot(approvals=["alice_pick"]),
                "bob_d": Ballot(approvals=["bob_pick"]),
            },
            # Strict precedence puts B first; expect Bob to win regardless
            # of the 0.9 vs 0.1 relevance gap (which strict ignores).
            precedences={"alice_user": {"B": 1, "A": 2}},
            user_strategies={"alice_user": "strict_precedence"},
        )
        result = resolve_vote_pure(user_id="alice_user", ctx=ctx)
        assert result is not None
        assert result.ballot.approvals == ["bob_pick"]
