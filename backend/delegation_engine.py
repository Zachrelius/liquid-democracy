"""
Delegation Engine
=================
Architecture: two distinct layers.

PURE LAYER (no DB access)
  VoteResult, ProposalTally, DelegationData, ProposalContext — data classes
  find_delegate_pure()  — topic-precedence logic
  resolve_vote_pure()   — full resolution algorithm
  compute_tally_pure()  — iterate users, aggregate results

GRAPH LAYER (thread-safe in-memory NetworkX store)
  DelegationGraphStore  — per-org × per-topic DiGraphs for cycle detection
                           (Phase 18 partitioned by org)

SERVICE LAYER (DB access lives here, calls pure functions)
  DelegationService     — fetches data, builds ProposalContext, delegates to pure layer
  DelegationEngine      — thin compatibility wrapper kept for existing route imports

Module-level singletons (initialised in main.py startup):
  graph_store, engine
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from threading import Lock
from typing import Optional

import networkx as nx
from sqlalchemy.orm import Session

import models

log = logging.getLogger(__name__)


def _resolve_project_item_cost(opt) -> float:
    """Phase 74a — the all-or-nothing cost a project-budget item funds at.

    Discrete items fund at ``budget_floor_amount``. Mode C
    ``continuous-as-discrete`` items fund at ``budget_max_amount`` (the
    Phase-73 ceiling field) if set, else ``budget_floor_amount`` — treated as
    a plain discrete item with that resolved cost. NULL → 0.
    """
    kind = getattr(opt, "budget_kind", None) or "discrete"
    if kind == "continuous-as-discrete":
        max_a = getattr(opt, "budget_max_amount", None)
        if max_a is not None:
            return max_a
    return getattr(opt, "budget_floor_amount", None) or 0


# ---------------------------------------------------------------------------
# Shared data classes
# ---------------------------------------------------------------------------

@dataclass
class Ballot:
    """Unified ballot representation for all voting methods."""
    vote_value: Optional[str] = None       # "yes" | "no" | "abstain" (binary)
    approvals: Optional[list[str]] = None  # list of option_ids (approval)
    ranking: Optional[list[str]] = None    # ranked_choice — order matters
    # Phase 73 — budget_allocation: {option_id: amount}. Phase 89: delegation
    # now resolves into an allocation ballot (a delegator resolves to their
    # delegate's allocation ballot, copied whole), same as approval/RCV.
    allocations: Optional[dict] = None
    # Phase 74 — budget_project: ordered list of option_ids (highest priority
    # first). Phase 89: delegation resolves normally, same as allocation.
    project_ranked: Optional[list] = None

    @property
    def voting_method(self) -> str:
        if self.vote_value is not None:
            return "binary"
        if self.approvals is not None:
            return "approval"
        if self.ranking is not None:
            return "ranked_choice"
        if self.allocations is not None:
            return "budget_allocation"
        if self.project_ranked is not None:
            return "budget_project"
        return "unknown"


@dataclass
class BallotResult:
    """Result of resolving a user's ballot (any voting method)."""
    ballot: Ballot
    is_direct: bool
    delegate_chain: list[str]
    cast_by_id: str

    @property
    def vote_value(self) -> Optional[str]:
        return self.ballot.vote_value


# Keep VoteResult as alias for backward compatibility
VoteResult = BallotResult


@dataclass
class ProposalTally:
    yes: int = 0
    no: int = 0
    abstain: int = 0
    not_cast: int = 0
    total_eligible: int = 0

    @property
    def votes_cast(self) -> int:
        return self.yes + self.no + self.abstain

    @property
    def yes_pct(self) -> float:
        return self.yes / self.votes_cast if self.votes_cast else 0.0

    @property
    def no_pct(self) -> float:
        return self.no / self.votes_cast if self.votes_cast else 0.0

    @property
    def abstain_pct(self) -> float:
        return self.abstain / self.votes_cast if self.votes_cast else 0.0

    def quorum_met(self, threshold: float) -> bool:
        if self.total_eligible == 0:
            return False
        return self.votes_cast / self.total_eligible >= threshold

    def threshold_met(self, threshold: float) -> bool:
        return self.yes_pct >= threshold


@dataclass
class ApprovalTally:
    option_approvals: dict  # {option_id: count}
    total_ballots_cast: int = 0
    total_abstain: int = 0    # empty approval lists
    not_cast: int = 0
    total_eligible: int = 0
    winners: list[str] = field(default_factory=list)
    tied: bool = False
    # Phase 17 B3.1 — per-ballot approval sets (each inner list is one
    # voter's approved option_ids). Populated by
    # `_compute_approval_tally_pure` from the same iteration that builds
    # `option_approvals`. Consumed by
    # `tie_resolution._resolve_broader_approval_base`. Ballot identity
    # is intentionally NOT carried — only the approval sets, which are
    # already aggregable from the existing approval ballots.
    ballots: list[list[str]] = field(default_factory=list)
    # Phase 88 — parallel per-ballot weights (shares), aligned index-for-index
    # with ``ballots``. Empty in unweighted orgs / when ``ballots`` is empty;
    # the tie resolver treats a missing/short list as all-1 so unweighted
    # behavior is byte-for-byte unchanged.
    ballot_weights: list[int] = field(default_factory=list)
    # Phase 66 — multi-winner approval fields. All empty/zero when the
    # proposal carries no ``approval_winner_config`` (legacy path —
    # byte-for-byte unchanged).
    #
    # ``winner_seats``: per-winner seat attribution,
    #   {option_id: "floor" | "threshold"}. The route layer adds
    #   "tie_resolution" entries when a boundary tie is resolved.
    # ``boundary_tied``: D4 — when options are tied at a seat boundary
    #   (equal approval counts where only some fit), this is the tied
    #   subset. The pure layer seats only the unambiguous set and leaves
    #   these out of ``winners``; the route layer routes them through
    #   ``tie_resolution.resolve_tie`` for the remaining seat(s).
    # ``seats_remaining``: how many seats are left for the
    #   ``boundary_tied`` subset.
    winner_seats: dict[str, str] = field(default_factory=dict)
    boundary_tied: list[str] = field(default_factory=list)
    seats_remaining: int = 0

    @property
    def votes_cast(self) -> int:
        return self.total_ballots_cast

    def quorum_met(self, threshold: float) -> bool:
        if self.total_eligible == 0:
            return False
        return self.total_ballots_cast / self.total_eligible >= threshold


# ---------------------------------------------------------------------------
# Pure-layer data containers
# ---------------------------------------------------------------------------

@dataclass
class DelegationData:
    """Lightweight, DB-free representation of one delegation row."""
    delegator_id: str
    delegate_id: str
    topic_id: Optional[str]
    chain_behavior: str   # "accept_sub" | "revert_direct" | "abstain"


@dataclass
class ProposalContext:
    """
    All data needed to resolve every user's vote on one proposal.
    Populated by the service layer; consumed by the pure functions.
    """
    proposal_topics: list[str]
    # {user_id: {topic_id_or_None: DelegationData}}
    all_delegations: dict[str, dict[Optional[str], DelegationData]]
    # {user_id: {topic_id: priority}}  — lower int = higher priority
    all_precedences: dict[str, dict[str, int]]
    # {user_id: vote_value}  — ONLY direct votes (binary)
    direct_votes: dict[str, str]
    # {user_id: Ballot}  — ONLY direct ballots (all methods)
    direct_ballots: dict[str, Ballot] = field(default_factory=dict)
    # voting method for the proposal
    voting_method: str = "binary"
    # Phase 27 — per-proposal topic relevance scores. Populated from
    # ProposalTopic.relevance (Float, default 1.0). Consumed by
    # find_vote_via_relevance_weighting_pure when the user's strategy
    # is "relevance_weighted" and voting_method is "binary".
    proposal_topic_relevances: dict[str, float] = field(default_factory=dict)
    # Phase 27 — per-user delegation strategy. Default "strict_precedence"
    # if a user isn't in the map (defensive — service layer populates for
    # every eligible voter). Values: "strict_precedence" | "relevance_weighted".
    user_strategies: dict[str, str] = field(default_factory=dict)
    # Phase 66 — multi-winner approval selection config, lifted from
    # ``Proposal.approval_winner_config`` by the service layer (keeps the
    # pure layer DB-free). None = legacy single-winner approval behavior.
    # Phase 66a: populated for ANY approval proposal carrying a config,
    # including approval-method elections (the D6 carve-out is lifted).
    approval_winner_config: Optional[dict] = None
    # Phase 73 — budget-voting config + bucket specs, lifted from
    # ``Proposal.budget_config`` and the option cost columns by the service
    # layer (keeps the pure layer DB-free). None when not a budget proposal.
    # ``budget_buckets`` is a list of ``budget_tally.BucketSpec``.
    budget_config: Optional[dict] = None
    budget_buckets: Optional[list] = None
    # Phase 74 — project-budget items (list of ``budget_tally.ProjectItemSpec``).
    budget_items: Optional[list] = None
    # Phase 88 — per-user integer voting weight ("shares"). Populated by the
    # service layer ONLY when the proposal's org has weighted voting enabled;
    # otherwise this map stays EMPTY. An empty map ⇒ every weight resolves to 1
    # (see ``_weight_of``) ⇒ all tally math reduces to today's headcount. This
    # is the parity mechanism — protect it with tests.
    user_weights: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Pure layer — no DB access, fully testable without fixtures
# ---------------------------------------------------------------------------

def _weight_of(uid: str, ctx: ProposalContext) -> int:
    """Phase 88 — a user's voting weight. Defaults to 1 for any user absent
    from ``ctx.user_weights`` (and the map is empty entirely in unweighted
    orgs), so all weighted-counter math reduces to headcount when weighting
    is off."""
    return ctx.user_weights.get(uid, 1)

def find_delegate_pure(
    user_id: str,
    proposal_topics: list[str],
    user_precedences: dict[str, int],
    user_delegations: dict[Optional[str], DelegationData],
) -> Optional[DelegationData]:
    """
    Return the DelegationData for the delegate that should vote for user_id,
    or None if no delegation applies.

    Algorithm:
      1. Sort proposal topics by user's precedence (lowest int = highest priority).
      2. Return the delegation for the first topic that has one.
      3. Fall back to the global (topic_id=None) delegation.
    """
    sorted_topics = sorted(proposal_topics, key=lambda t: user_precedences.get(t, 9999))
    for topic_id in sorted_topics:
        d = user_delegations.get(topic_id)
        if d is not None:
            return d
    return user_delegations.get(None)  # global fallback


def _get_direct_ballot(user_id: str, ctx: ProposalContext) -> Optional[Ballot]:
    """Look up a user's direct ballot from the context (any method)."""
    # Check direct_ballots first (used for all methods in new code)
    ballot = ctx.direct_ballots.get(user_id)
    if ballot is not None:
        return ballot
    # Fallback to direct_votes for backward compatibility (binary)
    vote_value = ctx.direct_votes.get(user_id)
    if vote_value is not None:
        return Ballot(vote_value=vote_value)
    return None


# ---------------------------------------------------------------------------
# Phase 27 — relevance-weighted delegation resolver
# ---------------------------------------------------------------------------

def find_vote_via_relevance_weighting_pure(
    user_id: str,
    proposal_topics: list[str],
    proposal_topic_relevances: dict[str, float],
    user_precedences: dict[str, int],
    user_delegations: dict[Optional[str], "DelegationData"],
    ctx: ProposalContext,
    _visited: Optional[set[str]] = None,
) -> Optional[BallotResult]:
    """Phase 27 — relevance-weighted delegation resolution (binary only).

    Algorithm:
      1. For each proposal topic the user has a delegation on, resolve the
         delegate's direct ballot (or, per chain_behavior, their delegate's
         ballot one hop further).
      2. Group the resolved vote_values by direction (yes/no/abstain).
      3. Sum the per-topic relevance scores per direction.
      4. The direction with the highest summed relevance wins.
      5. Tiebreaker: among tied directions, pick the one whose source
         topic has highest user precedence (lowest priority int). Falls
         through to strict-precedence semantics when scores collide.
      6. If no topic-specific delegation produced a vote, defer to the
         caller's global-fallback path (return None — the dispatcher
         falls through to find_delegate_pure with the same context).

    Returns BallotResult with delegate_chain set to the representative
    delegate from the winning direction (the one with the highest
    individual relevance). Returns None when no resolved vote applies.

    Constraints:
      * Pure function: no DB access; recursion uses _visited.
      * Binary only. The dispatcher in resolve_vote_pure gates by
        voting_method; this function assumes binary.
      * Multi-option ballots from delegates are not merged across
        topics — a delegate whose direct ballot has vote_value=None
        (approval/RCV ballot) is skipped in the per-direction bucket.
    """
    if _visited is None:
        _visited = set()

    # votes_by_direction: {vote_value: [(delegate_id, relevance, source_topic), ...]}
    votes_by_direction: dict[str, list[tuple[str, float, str]]] = {}

    for topic_id in proposal_topics:
        delegation = user_delegations.get(topic_id)
        if delegation is None:
            # No topic-specific delegation for this topic; relevance-
            # weighted resolution doesn't reach into the global delegation
            # per-topic — the global delegation only applies as a single
            # fallback (handled by the caller's None return path).
            continue
        relevance = proposal_topic_relevances.get(topic_id, 1.0)
        delegate_id = delegation.delegate_id

        # Resolve the delegate's ballot (direct, or one chain hop per
        # chain_behavior — same shape as resolve_vote_pure's existing
        # delegate-lookup branch).
        delegate_result = _resolve_delegate_ballot(
            delegate_id=delegate_id,
            chain_behavior=delegation.chain_behavior,
            ctx=ctx,
            _visited=_visited,
        )
        if delegate_result is None:
            continue
        vote_value = delegate_result.ballot.vote_value
        if vote_value is None:
            # Delegate cast a multi-option ballot; skip in the binary
            # relevance-weighted path. (Documented limitation per spec.)
            continue
        votes_by_direction.setdefault(vote_value, []).append(
            (delegate_id, float(relevance), topic_id)
        )

    if not votes_by_direction:
        # No topic-specific delegation produced a vote; let the caller
        # fall through to the global-fallback path (find_delegate_pure).
        return None

    # Sum relevance per direction.
    summed = {
        direction: sum(r for _, r, _ in entries)
        for direction, entries in votes_by_direction.items()
    }
    max_score = max(summed.values())
    winners = [d for d, s in summed.items() if s == max_score]

    if len(winners) > 1:
        # Strict-precedence tiebreaker among tied directions.
        best_direction: Optional[str] = None
        best_priority = 99999
        for direction in winners:
            for _, _, topic_id in votes_by_direction[direction]:
                priority = user_precedences.get(topic_id, 99999)
                if priority < best_priority:
                    best_priority = priority
                    best_direction = direction
        winning_direction = best_direction or winners[0]
    else:
        winning_direction = winners[0]

    # Representative delegate = entry with the highest individual relevance
    # within the winning direction. Used to populate delegate_chain so the
    # UI can attribute the vote to a primary delegate (with the rest of
    # the contributing delegates surfaced by F3 explainability).
    representative = max(
        votes_by_direction[winning_direction], key=lambda x: x[1]
    )
    delegate_id, _, _ = representative

    return BallotResult(
        ballot=Ballot(vote_value=winning_direction),
        is_direct=False,
        delegate_chain=[delegate_id],
        cast_by_id=delegate_id,
    )


# ---------------------------------------------------------------------------
# Phase 29 — multi-option relevance-weighted delegation resolver
# ---------------------------------------------------------------------------

def find_vote_via_relevance_for_multi_option_pure(
    user_id: str,
    proposal_topics: list[str],
    proposal_topic_relevances: dict[str, float],
    user_precedences: dict[str, int],
    user_delegations: dict[Optional[str], "DelegationData"],
    ctx: ProposalContext,
    _visited: Optional[set[str]] = None,
) -> Optional[BallotResult]:
    """Phase 29 — relevance-first delegate selection for multi-option methods.

    Walks proposal topics in ``(-relevance, precedence)`` order. For each
    topic the user has a delegation on, attempts to resolve that
    delegate's ballot. Returns the first ballot that resolves successfully
    (any non-None BallotResult from ``_resolve_delegate_ballot``).

    Differs from ``find_vote_via_relevance_weighting_pure`` (Phase 27,
    binary): that function sums relevance per vote direction across
    delegates and picks the highest-summed direction. Approval and RCV
    ballots aren't trivially comparable across delegates (two approval
    lists aren't "equal" or "different" the way yes/no/abstain are), so
    Phase 29's multi-option path picks ONE delegate's ballot — the
    delegate on the highest-relevance topic — rather than attempting to
    merge ballots. No merging, no summing.

    Iteration semantics: if the highest-relevance topic's delegate
    didn't vote (or their chain didn't resolve), the function continues
    to the next-highest-relevance topic. Returns None only when ALL
    topic-specific delegations failed to resolve — caller's strict-
    precedence path then handles the global fallback.

    Tiebreaker: when two topics have equal relevance, the topic with
    lower precedence priority (higher in the user's ordering) is tried
    first.

    Pure function. Recursion via _visited; method-agnostic — returns
    whatever ballot the delegate cast (approval list, ranking, or
    vote_value).
    """
    if _visited is None:
        _visited = set()

    sorted_topics = sorted(
        proposal_topics,
        key=lambda t: (
            -float(proposal_topic_relevances.get(t, 1.0)),
            user_precedences.get(t, 9999),
        ),
    )
    for topic_id in sorted_topics:
        d = user_delegations.get(topic_id)
        if d is None:
            continue
        delegate_result = _resolve_delegate_ballot(
            delegate_id=d.delegate_id,
            chain_behavior=d.chain_behavior,
            ctx=ctx,
            _visited=_visited,
        )
        if delegate_result is not None:
            return delegate_result
    return None


def _resolve_delegate_ballot(
    delegate_id: str,
    chain_behavior: str,
    ctx: ProposalContext,
    _visited: set[str],
) -> Optional[BallotResult]:
    """Resolve one delegate's effective ballot. Used by both the
    relevance-weighted resolver (B1) and the existing strict-precedence
    branch in resolve_vote_pure.

    Behavior mirrors resolve_vote_pure's steps 3-4: if the delegate has
    a direct ballot, return it; else apply chain_behavior. Pure function;
    recursion uses _visited.
    """
    if delegate_id in _visited:
        return None
    _visited = set(_visited) | {delegate_id}

    delegate_ballot = _get_direct_ballot(delegate_id, ctx)
    if delegate_ballot is not None:
        return BallotResult(
            ballot=delegate_ballot,
            is_direct=False,
            delegate_chain=[delegate_id],
            cast_by_id=delegate_id,
        )

    # Delegate did not vote directly — apply chain_behavior.
    if chain_behavior == "accept_sub":
        sub_delegations = ctx.all_delegations.get(delegate_id, {})
        sub_precedences = ctx.all_precedences.get(delegate_id, {})
        sub_delegation = find_delegate_pure(
            delegate_id,
            ctx.proposal_topics,
            sub_precedences,
            sub_delegations,
        )
        if sub_delegation is None or sub_delegation.delegate_id in _visited:
            return None
        sub_delegate_id = sub_delegation.delegate_id
        sub_ballot = _get_direct_ballot(sub_delegate_id, ctx)
        if sub_ballot is not None:
            return BallotResult(
                ballot=sub_ballot,
                is_direct=False,
                delegate_chain=[delegate_id, sub_delegate_id],
                cast_by_id=sub_delegate_id,
            )
        return None

    # revert_direct or abstain — no vote resolved.
    return None


def resolve_vote_pure(
    user_id: str,
    ctx: ProposalContext,
    _visited: Optional[set[str]] = None,
) -> Optional[BallotResult]:
    """
    Return the effective BallotResult for user_id on the proposal described by
    ctx, or None if the vote cannot be resolved.

    Pure function — takes data, returns data, never touches the database.

    Steps:
      1. Direct ballot → use it.
      2. Find delegate via topic precedence + global fallback.
      3. Delegate has a direct ballot → use it (non-transitive default).
      4. Delegate has no ballot → apply chain_behavior.
    """
    if _visited is None:
        _visited = set()

    # Cycle guard (defensive; the graph store prevents cycles at insert time)
    if user_id in _visited:
        return None
    _visited.add(user_id)

    # 1. Direct ballot
    direct_ballot = _get_direct_ballot(user_id, ctx)
    if direct_ballot is not None:
        return BallotResult(
            ballot=direct_ballot,
            is_direct=True,
            delegate_chain=[],
            cast_by_id=user_id,
        )

    user_delegations = ctx.all_delegations.get(user_id, {})
    user_precedences = ctx.all_precedences.get(user_id, {})

    # Phase 27 / Phase 29 — strategy dispatcher. relevance_weighted now
    # covers all voting methods: binary uses Phase 27's direction-summing
    # resolver; approval/RCV/STV use Phase 29's highest-relevance-ballot
    # resolver (no ballot merging across delegates — that's future work).
    # Both paths fall through to the strict-precedence + global-fallback
    # path below when no topic-specific delegation produced a ballot.
    user_strategy = ctx.user_strategies.get(user_id, "strict_precedence")
    if user_strategy == "relevance_weighted":
        if ctx.voting_method == "binary":
            rw_result = find_vote_via_relevance_weighting_pure(
                user_id=user_id,
                proposal_topics=ctx.proposal_topics,
                proposal_topic_relevances=ctx.proposal_topic_relevances,
                user_precedences=user_precedences,
                user_delegations=user_delegations,
                ctx=ctx,
                _visited=_visited,
            )
        else:
            # Phase 29 — multi-option (approval / ranked_choice / STV).
            rw_result = find_vote_via_relevance_for_multi_option_pure(
                user_id=user_id,
                proposal_topics=ctx.proposal_topics,
                proposal_topic_relevances=ctx.proposal_topic_relevances,
                user_precedences=user_precedences,
                user_delegations=user_delegations,
                ctx=ctx,
                _visited=_visited,
            )
        if rw_result is not None:
            return rw_result
        # Fall through to the strict-precedence + global-fallback path
        # below. The relevance-weighted resolver returns None when no
        # topic-specific delegation produced a ballot.

    # 2. Find delegate (strict-precedence + global fallback)
    delegation = find_delegate_pure(
        user_id,
        ctx.proposal_topics,
        user_precedences,
        user_delegations,
    )
    if delegation is None:
        return None

    delegate_id = delegation.delegate_id

    # 3. Did the delegate vote directly?
    delegate_ballot = _get_direct_ballot(delegate_id, ctx)
    if delegate_ballot is not None:
        return BallotResult(
            ballot=delegate_ballot,
            is_direct=False,
            delegate_chain=[delegate_id],
            cast_by_id=delegate_id,
        )

    # 4. Delegate did not vote — apply chain_behavior
    if delegation.chain_behavior == "accept_sub":
        sub_delegations = ctx.all_delegations.get(delegate_id, {})
        sub_precedences = ctx.all_precedences.get(delegate_id, {})
        sub_delegation = find_delegate_pure(
            delegate_id,
            ctx.proposal_topics,
            sub_precedences,
            sub_delegations,
        )
        if sub_delegation is None or sub_delegation.delegate_id in _visited:
            return None
        sub_delegate_id = sub_delegation.delegate_id
        sub_ballot = _get_direct_ballot(sub_delegate_id, ctx)
        if sub_ballot is not None:
            return BallotResult(
                ballot=sub_ballot,
                is_direct=False,
                delegate_chain=[delegate_id, sub_delegate_id],
                cast_by_id=sub_delegate_id,
            )
        return None

    # revert_direct or abstain — no vote resolved
    return None


def compute_tally_pure(
    user_ids: list[str],
    ctx: ProposalContext,
    option_ids: Optional[list[str]] = None,
    num_winners: int = 1,
) -> ProposalTally | ApprovalTally | RCVTally:
    """
    Compute a full tally by resolving every user's vote.
    Pure function — no DB access.
    Dispatches on ctx.voting_method.

    option_ids/num_winners are only consulted for ranked_choice; binary and
    approval ignore them so existing call sites stay compatible.
    """
    if ctx.voting_method == "approval":
        return _compute_approval_tally_pure(user_ids, ctx)
    if ctx.voting_method == "ranked_choice":
        return _compute_rcv_tally_pure(
            user_ids, ctx, option_ids or [], num_winners=num_winners
        )
    if ctx.voting_method == "budget_allocation":
        return _compute_allocation_tally_pure(user_ids, ctx)
    if ctx.voting_method == "budget_project":
        return _compute_project_tally_pure(user_ids, ctx)
    return _compute_binary_tally_pure(user_ids, ctx)


def _compute_project_tally_pure(
    user_ids: list[str],
    ctx: ProposalContext,
):
    """Phase 74/89 — project-budget tally.

    Phase 89 lifted the direct-vote-only restriction: we resolve each eligible
    voter's ballot via ``resolve_vote_pure`` (mirroring the approval/RCV
    tallies). A direct caster resolves to their own ranking; a delegator
    resolves to their delegate's ranking, copied whole (including its tier
    selections), contributing once per delegator. A resolution that yields no
    project ranking (not_cast, or a non-budget-shaped resolved ballot —
    impossible on a budget proposal since every direct ballot is
    project-shaped, but defensive) contributes nothing.
    ``budget_tally.tally_project`` handles omission-at-max-spend.
    """
    import budget_tally

    ballots: list[list[str]] = []
    for uid in user_ids:
        result = resolve_vote_pure(uid, ctx)
        if result is None:
            continue
        if result.ballot.project_ranked is not None:
            ballots.append(list(result.ballot.project_ranked))

    cfg = ctx.budget_config or {}
    envelope = cfg.get("envelope", 0)
    return budget_tally.tally_project(
        envelope=envelope,
        min_spend=cfg.get("min_spend", 0),
        max_spend=cfg.get("max_spend", envelope),
        items=ctx.budget_items or [],
        ballots=ballots,
        total_eligible=len(user_ids),
    )


def _compute_allocation_tally_pure(
    user_ids: list[str],
    ctx: ProposalContext,
):
    """Phase 73/89 — allocation-budget tally.

    Phase 89 lifted the direct-vote-only restriction: we resolve each eligible
    voter's ballot via ``resolve_vote_pure`` (mirroring the approval/RCV
    tallies), so a delegator resolving to a delegate's allocation ballot
    contributes that allocation once per delegator, and a direct caster
    contributes their own. A resolution yielding no allocation ballot
    (not_cast, or a non-budget-shaped resolved ballot — impossible on a budget
    proposal since every direct ballot is allocation-shaped, but defensive)
    contributes nothing. An empty-allocations dict (`{}`) from a resolved
    ballot counts as a cast ballot allocating $0 everywhere, same as a direct
    empty ballot. The per-bucket median counts an omitted bucket as $0 for that
    voter (handled inside ``budget_tally.tally_allocation``).
    """
    import budget_tally

    ballots: list[dict] = []
    for uid in user_ids:
        result = resolve_vote_pure(uid, ctx)
        if result is None:
            continue
        if result.ballot.allocations is not None:
            ballots.append(result.ballot.allocations)

    cfg = ctx.budget_config or {}
    return budget_tally.tally_allocation(
        envelope=cfg.get("envelope", 0),
        buckets=ctx.budget_buckets or [],
        ballots=ballots,
        aggregation=cfg.get("aggregation", "median"),
        total_eligible=len(user_ids),
    )


def _compute_binary_tally_pure(
    user_ids: list[str],
    ctx: ProposalContext,
) -> ProposalTally:
    # Phase 88 — every counter is weight-denominated: each user contributes
    # ``_weight_of(uid, ctx)`` (their shares) instead of a flat 1. With an
    # empty ``user_weights`` map (unweighted orgs) every weight is 1 and this
    # is byte-identical to headcount. A resolved not_cast user still adds their
    # weight to not_cast + total_eligible (their shares exist, uncast).
    tally = ProposalTally(
        total_eligible=sum(_weight_of(uid, ctx) for uid in user_ids)
    )
    for uid in user_ids:
        w = _weight_of(uid, ctx)
        result = resolve_vote_pure(uid, ctx)
        if result is None:
            tally.not_cast += w
        elif result.vote_value == "yes":
            tally.yes += w
        elif result.vote_value == "no":
            tally.no += w
        elif result.vote_value == "abstain":
            tally.abstain += w
    return tally


def select_approval_winners_with_config(
    option_approvals: dict[str, int],
    total_ballots_cast: int,
    config: dict,
) -> tuple[list[str], dict[str, str], bool, list[str], int]:
    """Phase 66 D3/D4 — pure multi-winner approval selection.

    Inputs:
      - ``option_approvals``: {option_id: approval count} (only options
        with >= 1 approval appear — an option nobody approved can never
        seat).
      - ``total_ballots_cast``: the D2 threshold denominator. This is
        the SAME counter the existing quorum math uses: it increments
        for EVERY resolved ballot, including empty-approval (abstain)
        ballots (see ``_compute_approval_tally_pure`` — the counter is
        bumped before the approvals-content check). "B% approval" means
        B% of everyone who cast a ballot, abstainers included.
      - ``config``: ``{min_winners, max_winners, approval_threshold}``
        (validated upstream at the schema layer; this function trusts
        the shape).

    Algorithm (D3): sort options by approval count descending. Seat the
    top ``min_winners`` unconditionally. Continue seating options that
    clear ``approval_threshold`` (count / total_ballots_cast >=
    threshold) until ``max_winners`` (null = unbounded). Threshold null
    ⇒ only the unconditional floor seats.

    Boundary ties (D4): options are walked in equal-count groups
    (descending count; option_id ascending within a group for
    deterministic output ordering). When only SOME members of an
    equal-count group fit in the remaining seats, the group is a
    boundary tie: nobody from that group seats here; the tied subset +
    the number of seats they're competing for are returned so the route
    layer can run the org's configured tie resolver.

    Returns ``(winners, winner_seats, tied, boundary_tied,
    seats_remaining)`` where ``winner_seats`` maps each winner to
    ``"floor"`` or ``"threshold"`` seat attribution.
    """
    min_winners = int(config.get("min_winners") or 0)
    max_winners = config.get("max_winners")  # None = unbounded
    threshold = config.get("approval_threshold")  # None = floor only

    def _clears_threshold(count: int) -> bool:
        if threshold is None:
            return False
        if total_ballots_cast <= 0:
            return False
        return (count / total_ballots_cast) >= float(threshold)

    # Group options by approval count, descending.
    by_count: dict[int, list[str]] = {}
    for oid, count in option_approvals.items():
        by_count.setdefault(int(count), []).append(oid)
    groups = [
        (count, sorted(by_count[count]))
        for count in sorted(by_count.keys(), reverse=True)
    ]

    winners: list[str] = []
    winner_seats: dict[str, str] = {}
    boundary_tied: list[str] = []
    seats_remaining = 0
    tied = False

    for count, members in groups:
        seated = len(winners)
        floor_need = max(0, min_winners - seated)
        if max_winners is None:
            remaining_to_max: Optional[int] = None
        else:
            remaining_to_max = max(0, int(max_winners) - seated)

        if _clears_threshold(count):
            # Every member of this group wants a seat (threshold
            # cleared); capacity is bounded only by max_winners.
            qualified = (
                len(members) if remaining_to_max is None
                else min(len(members), remaining_to_max)
            )
        else:
            # Below threshold (or threshold null): only unconditional
            # floor seats are available. min_winners <= max_winners is
            # enforced at validation, so floor seats never exceed the
            # max cap.
            qualified = min(floor_need, len(members))

        if qualified <= 0:
            # No seats left for this count tier; lower tiers have lower
            # counts (and therefore lower fractions), so nothing below
            # can seat either.
            break
        if qualified < len(members):
            # D4 boundary tie — equal-count group only partially fits.
            tied = True
            boundary_tied = list(members)
            seats_remaining = qualified
            break
        for oid in members:
            winners.append(oid)
            winner_seats[oid] = (
                "floor" if len(winners) <= min_winners else "threshold"
            )

    return winners, winner_seats, tied, boundary_tied, seats_remaining


def _compute_approval_tally_pure(
    user_ids: list[str],
    ctx: ProposalContext,
) -> ApprovalTally:
    """Compute approval tally: count how many ballots approve each option.

    Phase 17 note: this pure tally function stays method-agnostic with
    respect to tie resolution. When ``tied=True`` and ``len(winners) > 1``
    the route layer (``routes/proposals.py::advance_proposal`` and the
    org-scoped equivalent in ``routes/organizations.py``) is responsible
    for invoking ``tie_resolution.resolve_tie`` and mutating
    ``tally.winners`` to the resolved set. ``tied`` itself stays ``True``
    after resolution for transparency (D9). See ``backend/tie_resolution.py``
    for the resolver contract.
    """
    option_approvals: dict[str, int] = {}
    total_ballots_cast = 0
    total_abstain = 0
    not_cast = 0
    # Phase 17 B3.1 — per-ballot approval sets, exposed for
    # broader_approval_base tie resolution. Empty/abstain ballots are
    # excluded; only ballots that actually approved options contribute.
    ballots_seen: list[list[str]] = []
    # Phase 88 — parallel per-ballot weights (shares), one per entry in
    # ``ballots_seen``. In unweighted orgs every entry is 1 so the tie
    # resolver's weight-sum reduces to a headcount and ``ballots_seen`` keeps
    # its historical ``list[list[str]]`` shape byte-for-byte.
    ballot_weights: list[int] = []

    for uid in user_ids:
        w = _weight_of(uid, ctx)
        result = resolve_vote_pure(uid, ctx)
        if result is None:
            not_cast += w
            continue
        total_ballots_cast += w
        approvals = result.ballot.approvals
        if approvals is not None:
            if len(approvals) == 0:
                total_abstain += w
            else:
                for oid in approvals:
                    option_approvals[oid] = option_approvals.get(oid, 0) + w
                ballots_seen.append(list(approvals))
                ballot_weights.append(w)

    # Phase 66 — multi-winner selection when the proposal carries an
    # ``approval_winner_config`` (threaded through ProposalContext to
    # keep this layer DB-free). NULL config takes the legacy
    # single-winner path below, byte-for-byte.
    config = getattr(ctx, "approval_winner_config", None)
    if config:
        (
            mw_winners, winner_seats, mw_tied, boundary_tied,
            seats_remaining,
        ) = select_approval_winners_with_config(
            option_approvals, total_ballots_cast, config,
        )
        return ApprovalTally(
            option_approvals=option_approvals,
            total_ballots_cast=total_ballots_cast,
            total_abstain=total_abstain,
            not_cast=not_cast,
            total_eligible=sum(_weight_of(uid, ctx) for uid in user_ids),
            winners=mw_winners,
            tied=mw_tied,
            ballots=ballots_seen,
            ballot_weights=ballot_weights,
            winner_seats=winner_seats,
            boundary_tied=boundary_tied,
            seats_remaining=seats_remaining,
        )

    # Determine winners: option(s) with highest approval count
    winners: list[str] = []
    tied = False
    if option_approvals:
        max_approvals = max(option_approvals.values())
        winners = [oid for oid, count in option_approvals.items() if count == max_approvals]
        tied = len(winners) > 1

    return ApprovalTally(
        option_approvals=option_approvals,
        total_ballots_cast=total_ballots_cast,
        total_abstain=total_abstain,
        not_cast=not_cast,
        total_eligible=sum(_weight_of(uid, ctx) for uid in user_ids),
        winners=winners,
        tied=tied,
        ballots=ballots_seen,
        ballot_weights=ballot_weights,
    )


# ---------------------------------------------------------------------------
# Ranked-choice (IRV / STV) tabulation via pyrankvote
# ---------------------------------------------------------------------------
#
# pyrankvote (pinned 2.0.6) implements the algorithm internals. The wrapper
# below maps its ElectionResults object onto our internal RCVTally/RCVRound
# dataclasses so routes / frontend never touch the library types directly.
# If we ever swap libraries, only _compute_rcv_tally_pure needs to change.


@dataclass
class RCVRound:
    round_number: int
    option_counts: dict[str, float]            # option_id → vote count
    eliminated: Optional[str] = None           # option_id eliminated this round
    elected: list[str] = field(default_factory=list)  # option_ids elected this round
    transferred_from: Optional[str] = None     # option whose votes transferred
    transfer_breakdown: dict[str, float] = field(default_factory=dict)


@dataclass
class RCVTally:
    rounds: list[RCVRound] = field(default_factory=list)
    winners: list[str] = field(default_factory=list)  # option_ids; len > 1 => unresolved final-round tie
    total_ballots_cast: int = 0
    total_abstain: int = 0                     # empty rankings
    not_cast: int = 0
    total_eligible: int = 0
    tied: bool = False
    method: str = "irv"                        # "irv" or "stv"
    num_winners: int = 1

    @property
    def votes_cast(self) -> int:
        return self.total_ballots_cast

    def quorum_met(self, threshold: float) -> bool:
        if self.total_eligible == 0:
            return False
        return self.total_ballots_cast / self.total_eligible >= threshold


def _compute_rcv_tally_pure(
    user_ids: list[str],
    ctx: ProposalContext,
    option_ids: list[str],
    num_winners: int = 1,
) -> RCVTally:
    """
    Resolve ranked ballots through delegation, then run IRV (num_winners=1)
    or STV (num_winners>1) via pyrankvote and translate the result.

    option_ids: all valid option_ids on the proposal — needed even when no
    voter ranked them so they appear as 0-vote candidates in the rounds.

    Phase 17 note: as with `_compute_approval_tally_pure`, this pure
    tally function stays method-agnostic with respect to tie resolution.
    When `tied=True` and `len(winners) > 1`, the route layer (advance_proposal
    in routes/proposals.py and the org-scoped equivalent in
    routes/organizations.py) invokes `tie_resolution.resolve_tie` and
    mutates `tally.winners` to the resolved set. `tied` stays True after
    resolution for transparency (D9).

    Phase 88 (Stage 1) note: this tally deliberately IGNORES ``ctx.user_weights``
    — RCV creation is blocked in weighted orgs (§2.4), so weights never matter
    for a fresh RCV proposal. The only way a weighted org tallies RCV is a
    proposal that was already open when the weighted-voting toggle flipped ON;
    Stage 1 tallies that case by headcount (defensive). Phase 88a lifts the
    block and makes this tally weight-aware via ballot duplication.
    """
    # Local import — pyrankvote is heavy and only loaded when ranked-choice
    # tabulation actually runs.
    import pyrankvote
    from pyrankvote.helpers import CandidateStatus

    method = "irv" if num_winners <= 1 else "stv"

    # Resolve every voter's ballot through delegation
    rankings: list[list[str]] = []
    total_abstain = 0
    not_cast = 0
    total_ballots_cast = 0
    for uid in user_ids:
        result = resolve_vote_pure(uid, ctx)
        if result is None:
            not_cast += 1
            continue
        total_ballots_cast += 1
        ranking = result.ballot.ranking
        if ranking is None or len(ranking) == 0:
            total_abstain += 1
            continue
        # Filter out any option_ids no longer in the proposal (defensive)
        clean = [oid for oid in ranking if oid in set(option_ids)]
        if not clean:
            total_abstain += 1
            continue
        rankings.append(clean)

    eligible = len(user_ids)
    valid_option_set = set(option_ids)

    # If there are no valid ballots at all, return an empty tally
    if not rankings:
        return RCVTally(
            rounds=[],
            winners=[],
            total_ballots_cast=total_ballots_cast,
            total_abstain=total_abstain,
            not_cast=not_cast,
            total_eligible=eligible,
            tied=False,
            method=method,
            num_winners=num_winners,
        )

    # Build pyrankvote candidates / ballots
    candidates = [pyrankvote.Candidate(oid) for oid in option_ids]
    cand_by_id = {c.name: c for c in candidates}

    pv_ballots = []
    for ranking in rankings:
        pv_ballots.append(pyrankvote.Ballot(
            ranked_candidates=[cand_by_id[oid] for oid in ranking if oid in cand_by_id]
        ))

    if num_winners <= 1:
        election = pyrankvote.instant_runoff_voting(candidates, pv_ballots)
    else:
        election = pyrankvote.single_transferable_vote(
            candidates, pv_ballots, number_of_seats=num_winners
        )

    # Translate ElectionResults → RCVRound list.
    rounds: list[RCVRound] = []
    prev_counts: dict[str, float] = {oid: 0.0 for oid in option_ids}
    prev_elected: set[str] = set()
    prev_rejected: set[str] = set()

    for i, rr in enumerate(election.rounds):
        cur_counts: dict[str, float] = {}
        cur_elected: set[str] = set()
        cur_rejected: set[str] = set()
        for cr in rr.candidate_results:
            oid = cr.candidate.name
            cur_counts[oid] = float(cr.number_of_votes)
            status = cr.status
            # Status comes through as a CandidateStatus enum (string-valued).
            if status == CandidateStatus.Elected:
                cur_elected.add(oid)
            elif status == CandidateStatus.Rejected:
                cur_rejected.add(oid)

        newly_elected = sorted(cur_elected - prev_elected)
        newly_rejected = cur_rejected - prev_rejected
        # Eliminated this round = newly Rejected candidate(s).
        # pyrankvote eliminates one per round in IRV, but STV may eliminate
        # multiple at once (rare); pick first deterministically.
        eliminated: Optional[str] = None
        if newly_rejected:
            # Use the option_id ordering for stability when multiple are dropped.
            eliminated = sorted(newly_rejected)[0]

        # Compute transfer breakdown: where did votes flow this round?
        # transferred_from = the option whose votes shifted (eliminated, OR
        # over-quota winner whose surplus moved).
        transferred_from: Optional[str] = None
        transfer_breakdown: dict[str, float] = {}
        if i > 0:
            # Find option(s) whose count dropped versus previous round
            dropped = [
                oid for oid in option_ids
                if cur_counts.get(oid, 0.0) < prev_counts.get(oid, 0.0) - 1e-9
            ]
            gained = {
                oid: cur_counts.get(oid, 0.0) - prev_counts.get(oid, 0.0)
                for oid in option_ids
                if cur_counts.get(oid, 0.0) > prev_counts.get(oid, 0.0) + 1e-9
            }
            if dropped:
                # Pick the largest drop as primary source (typically the
                # eliminated option in IRV or the elected-with-surplus in STV).
                transferred_from = max(
                    dropped,
                    key=lambda o: prev_counts.get(o, 0.0) - cur_counts.get(o, 0.0),
                )
                transfer_breakdown = gained

        rounds.append(RCVRound(
            round_number=i,
            option_counts=cur_counts,
            eliminated=eliminated,
            elected=newly_elected,
            transferred_from=transferred_from,
            transfer_breakdown=transfer_breakdown,
        ))

        prev_counts = cur_counts
        prev_elected = cur_elected
        prev_rejected = cur_rejected

    pv_winners = [c.name for c in election.get_winners()]

    # Detect a final-round tie: in the last round, if any Rejected candidate
    # has a vote count equal to the lowest Elected candidate, pyrankvote broke
    # a real tie internally — surface it for admin resolution.
    tied = False
    final_winners = list(pv_winners)
    if rounds and pv_winners:
        last = rounds[-1]
        elected_counts = [last.option_counts.get(w, 0.0) for w in pv_winners]
        # Only consider it a tie if the marginal winner had a non-zero count
        # (otherwise we are just picking unanimous winners against zeroes).
        marginal = min(elected_counts) if elected_counts else 0.0
        if marginal > 0:
            tied_with: list[str] = []
            for oid, count in last.option_counts.items():
                if oid in pv_winners:
                    continue
                if abs(count - marginal) < 1e-9:
                    tied_with.append(oid)
            if tied_with:
                tied = True
                # Final winners list = the marginal pyrankvote winner(s) at
                # the same vote count + the rejected candidates tied with them.
                marginal_winners = [w for w in pv_winners if abs(
                    last.option_counts.get(w, 0.0) - marginal) < 1e-9]
                # Non-marginal (clear) winners stay as winners; the marginal
                # ones are still listed as candidates needing resolution.
                clear_winners = [w for w in pv_winners if w not in marginal_winners]
                final_winners = clear_winners + sorted(set(marginal_winners + tied_with))

    return RCVTally(
        rounds=rounds,
        winners=final_winners,
        total_ballots_cast=total_ballots_cast,
        total_abstain=total_abstain,
        not_cast=not_cast,
        total_eligible=eligible,
        tied=tied,
        method=method,
        num_winners=num_winners,
    )


# ---------------------------------------------------------------------------
# Graph store — thread-safe, in-memory NetworkX graphs for cycle detection
# ---------------------------------------------------------------------------

class DelegationGraphStore:
    """
    Phase 18 (B2.3): partitioned by org. Storage shape is
    ``Dict[Optional[str], Dict[Optional[str], nx.DiGraph]]`` — outer key is
    ``org_id`` and inner key is ``topic_id`` (with ``None`` for the org's
    "global" graph i.e. topic-less delegations).

    The outer ``org_id=None`` bucket is the **legacy / unscoped** bucket.
    It exists for two reasons:
      1. backwards-compat with pre-Phase-18 callers that hadn't yet been
         updated to thread ``org_id`` (Backend Agent #3 fixes the callers
         in routes/delegations.py + routes/follows.py within the same pass);
      2. unit tests that exercise the cycle-detection / neighborhood
         primitives without setting up a full org context.

    Cycle detection is per-org natural — cross-org cycles aren't possible
    post-fix because cross-org delegation doesn't exist.

    ``compute_voting_weight(user_id, org_id)`` walks ancestors only within
    the specified org's graph; cross-org weight inflation goes away.

    Thread-safe: a single lock guards all mutations. The lock is one
    global lock (not per-org) because partition is a data-shape concern,
    not a concurrency boundary.
    """

    GLOBAL_KEY = "__global__"

    def __init__(self) -> None:
        # outer key: org_id (None = legacy/unscoped bucket)
        # inner key: topic_id (None = the org's __global__ graph)
        self._graphs: dict[Optional[str], dict[Optional[str], nx.DiGraph]] = {}
        self._lock = Lock()

    def _get_or_create(
        self, org_id: Optional[str], topic_id: Optional[str]
    ) -> nx.DiGraph:
        org_bucket = self._graphs.setdefault(org_id, {})
        if topic_id not in org_bucket:
            org_bucket[topic_id] = nx.DiGraph()
        return org_bucket[topic_id]

    def rebuild_from_db(self, db: Session) -> None:
        """Replace all in-memory graphs with the current DB state.

        Phase 18: pre-creates one per-org bucket per Organization row, then
        loads every Delegation row that has ``org_id IS NOT NULL``. Rows
        with ``org_id IS NULL`` (which can exist transiently between the
        18a and 18b migration deploys) are SKIPPED — they're not yet
        placeable in the partitioned structure. Post-18b they don't exist.
        """
        with self._lock:
            self._graphs = {}
            # Pre-create per-org buckets so subsequent lookups can
            # distinguish "no delegations yet" from "unknown org."
            for org in db.query(models.Organization).all():
                self._graphs.setdefault(org.id, {})
            delegations: list[models.Delegation] = db.query(
                models.Delegation
            ).filter(models.Delegation.org_id.isnot(None)).all()
            for d in delegations:
                g = self._get_or_create(d.org_id, d.topic_id)
                g.add_edge(d.delegator_id, d.delegate_id)

    def would_create_cycle(
        self,
        delegator_id: str,
        delegate_id: str,
        topic_id: Optional[str],
        org_id: Optional[str] = None,
    ) -> bool:
        """Check whether the (delegator → delegate) edge would create a
        cycle within the org's graph(s).

        Phase 18: cycle detection is per-org. Within the org, both the
        topic-specific graph and the org's global graph (topic_id=None)
        are checked, since a topic delegation can chain through a global
        one and vice versa.
        """
        with self._lock:
            for tid in (topic_id, None):
                g = self._get_or_create(org_id, tid)
                if self._edge_creates_cycle(g, delegator_id, delegate_id):
                    return True
        return False

    @staticmethod
    def _edge_creates_cycle(g: nx.DiGraph, src: str, dst: str) -> bool:
        g.add_edge(src, dst)
        has_cycle = not nx.is_directed_acyclic_graph(g)
        g.remove_edge(src, dst)
        return has_cycle

    def add_delegation(
        self,
        delegator_id: str,
        delegate_id: str,
        topic_id: Optional[str],
        org_id: Optional[str] = None,
    ) -> None:
        with self._lock:
            g = self._get_or_create(org_id, topic_id)
            if delegator_id in g:
                for old in list(g.successors(delegator_id)):
                    g.remove_edge(delegator_id, old)
            g.add_edge(delegator_id, delegate_id)

    def remove_delegation(
        self,
        delegator_id: str,
        topic_id: Optional[str],
        org_id: Optional[str] = None,
    ) -> None:
        with self._lock:
            g = self._get_or_create(org_id, topic_id)
            if delegator_id in g:
                for d in list(g.successors(delegator_id)):
                    g.remove_edge(delegator_id, d)

    def get_neighborhood(
        self,
        user_id: str,
        topic_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> tuple[set[str], list[tuple[str, str, Optional[str]]]]:
        """Return (nodes, edges) for the user's neighborhood.

        Phase 18: scoped to the specified ``org_id``'s partition. When
        ``org_id`` is None, the legacy/unscoped bucket is consulted (for
        backwards-compat tests) — NOT the union across all orgs (that
        would re-introduce the cross-org leak this whole pass exists to
        fix). Admin tools that need a true cross-org view should call
        :meth:`get_neighborhood_all_orgs`.
        """
        nodes: set[str] = {user_id}
        edges: list[tuple[str, str, Optional[str]]] = []
        org_bucket = self._graphs.get(org_id, {})
        topic_keys = [topic_id] if topic_id is not None else list(org_bucket.keys())
        for tid in topic_keys:
            g = org_bucket.get(tid)
            if g is None or user_id not in g:
                continue
            for nb in g.successors(user_id):
                nodes.add(nb)
                edges.append((user_id, nb, tid))
            for nb in g.predecessors(user_id):
                nodes.add(nb)
                edges.append((nb, user_id, tid))
        return nodes, edges

    def get_neighborhood_all_orgs(
        self, user_id: str
    ) -> tuple[set[str], list[tuple[str, str, Optional[str], Optional[str]]]]:
        """Return (nodes, edges) for the user's neighborhood across every
        org's graph — admin/forensic helper.

        Edges are 4-tuples ``(src, dst, topic_id, org_id)`` so the caller
        can reconstruct which org each edge came from. Used by
        ``/api/admin/delegation-graph`` (renamed
        ``system_delegation_graph_all_orgs``) where cross-org visibility is
        the documented behavior.
        """
        nodes: set[str] = {user_id}
        edges: list[tuple[str, str, Optional[str], Optional[str]]] = []
        for org_id, org_bucket in self._graphs.items():
            for tid, g in org_bucket.items():
                if user_id not in g:
                    continue
                for nb in g.successors(user_id):
                    nodes.add(nb)
                    edges.append((user_id, nb, tid, org_id))
                for nb in g.predecessors(user_id):
                    nodes.add(nb)
                    edges.append((nb, user_id, tid, org_id))
        return nodes, edges

    def compute_voting_weight(
        self,
        user_id: str,
        org_id: Optional[str] = None,
    ) -> int:
        """Voting weight = 1 + ancestors-in-org's-global-graph.

        Phase 18: only walks the specified org's global delegation graph.
        Cross-org weight inflation (the pre-fix bug where someone with
        delegators in two orgs got their weights summed) is gone.
        """
        org_bucket = self._graphs.get(org_id, {})
        g = org_bucket.get(None)  # the org's __global__ graph
        if g is None or user_id not in g:
            return 1
        try:
            predecessors = nx.ancestors(g, user_id)
        except nx.NetworkXError:
            predecessors = set()
        return 1 + len(predecessors)

    def compute_voting_weight_all_orgs(self, user_id: str) -> int:
        """Cross-org voting weight — admin/forensic helper.

        Sum of ancestors across every org's global graph. Used by the
        ``system_delegation_graph_all_orgs`` admin endpoint where the
        cross-org union is the documented behavior. Production app code
        should call :meth:`compute_voting_weight` instead.
        """
        total = 0
        for org_bucket in self._graphs.values():
            g = org_bucket.get(None)
            if g is None or user_id not in g:
                continue
            try:
                predecessors = nx.ancestors(g, user_id)
            except nx.NetworkXError:
                predecessors = set()
            total += len(predecessors)
        return 1 + total


# ---------------------------------------------------------------------------
# Eligibility helper — Phase 8.5
# ---------------------------------------------------------------------------

def eligible_voter_ids_for_proposal(
    db: Session, proposal: models.Proposal
) -> set[str]:
    """Return the set of user IDs eligible to vote on this proposal.

    Phase 8.5 (Session 2) dispatches on scope:
      - sub-org-scoped proposals (``sub_org_id`` IS NOT NULL): active
        SubOrgMembership in that sub-org.
      - parent-org-scoped proposals (``sub_org_id`` IS NULL with a non-null
        ``org_id``): active OrgMembership of that parent org.
      - proposals with no org context (``org_id`` IS NULL — pre-multi-tenancy
        legacy rows; should not exist for newly created proposals): defensive
        fallback to "all users in the DB". Documented because some early
        backend tests construct proposals without an org for unit-test
        convenience and rely on this semantic. Real production rows always
        have an org_id since Phase 4.

    Phase 52 Stage 1 — verification-gated proposals additionally
    narrow the set per the locked delegation fork (default No):

      * If the proposal has no ``verification_floor`` → today's
        behavior, byte-for-byte.
      * If the proposal IS gated AND the org has
        ``verification_delegation_carries_weight=False`` (the
        default) → the set is intersected with users who satisfy the
        proposal's floor. Unverified users are dropped from the set,
        which propagates through the existing Phase 10.1 chain-
        resolution machinery: their direct ballots aren't loaded
        into ``direct_ballots``, so a delegate resolving to them gets
        ``None`` and ``chain_behavior`` fires. NO parallel tally
        path; the fork rides the eligibility filter the cross-scope-
        leak fix already established.
      * If the proposal IS gated AND the org has flipped the setting
        to True → the set is NOT narrowed at the eligibility layer.
        Verified delegates can carry their unverified principals'
        weight; the C3 direct-cast block still keeps unverified
        users from voting directly.
    """
    sub_org_id = getattr(proposal, "sub_org_id", None)
    if sub_org_id:
        rows = db.query(models.SubOrgMembership.user_id).filter(
            models.SubOrgMembership.sub_org_id == sub_org_id,
            models.SubOrgMembership.status == "active",
        ).all()
        ids = {r.user_id for r in rows}
    else:
        org_id = getattr(proposal, "org_id", None)
        if org_id:
            rows = db.query(models.OrgMembership.user_id).filter(
                models.OrgMembership.org_id == org_id,
                models.OrgMembership.status == "active",
            ).all()
            ids = {r.user_id for r in rows}
        else:
            # Defensive fallback: pre-multi-tenancy rows / unit-test
            # fixtures with no org context. Preserves the legacy
            # "all users" semantic so tests that don't set up org
            # membership rows continue to work.
            rows = db.query(models.User.id).all()
            ids = {r.id for r in rows}

    # Phase 52 Stage 1 — verification fork. Narrow the eligible set
    # when the EFFECTIVE proposal floor is non-None (Phase 52j J3
    # routes this through ``effective_proposal_floor`` so an
    # ``always``-policy org applies its org floor uniformly across
    # the eligibility filter AND the vote-cast block; a ``never``-
    # policy org applies no narrowing even if the proposal row
    # carries a stale stored floor).
    org_id_for_setting = getattr(proposal, "org_id", None)
    org_row = (
        db.get(models.Organization, org_id_for_setting)
        if org_id_for_setting else None
    )
    from verification import effective_proposal_floor
    floor, jurisdiction = effective_proposal_floor(proposal, org_row)
    if floor:
        carries = False
        if org_row is not None:
            from verification import (
                delegation_carries_unverified_weight,
            )
            carries = delegation_carries_unverified_weight(org_row)
        if not carries and ids:
            from verification import user_satisfies_floor
            users = db.query(models.User).filter(
                models.User.id.in_(ids),
            ).all()
            ids = {
                u.id for u in users
                if user_satisfies_floor(u, floor, jurisdiction)
            }
    return ids


# ---------------------------------------------------------------------------
# Service layer — DB access lives here, calls the pure functions
# ---------------------------------------------------------------------------

class DelegationService:
    """
    Fetches data from the database and delegates to the pure resolution
    functions.  No resolution logic lives here — only DB queries and
    object mapping.
    """

    def __init__(self, graph_store: DelegationGraphStore) -> None:
        self.graphs = graph_store

    # ------------------------------------------------------------------
    # DB → pure-layer data builders
    # ------------------------------------------------------------------

    @staticmethod
    def _build_context(
        proposal: models.Proposal,
        db: Session,
        eligible_ids: Optional[set[str]] = None,
    ) -> ProposalContext:
        """
        Fetch everything needed to resolve all votes on a proposal and pack it
        into a ProposalContext.

        Phase 8.5 scope handling: ``proposal_topics`` is the proposal's own
        topic list (which the proposal-creation route is responsible for keeping
        in scope). Sub-org-scope filtering happens at the topic level — a
        sub-org-scoped proposal may only attach parent-org-wide topics or its
        own sub-org's topics; a parent-org-wide proposal may only attach
        parent-org-wide topics. The pure resolver doesn't need to re-check
        scope because the topics are already filtered upstream.

        Phase 10.1 (cross-scope vote leak fix): when ``eligible_ids`` is
        provided, the direct-vote/direct-ballot query is filtered to that set.
        This prevents a non-eligible user's pre-fix Vote row from leaking
        through delegation chain resolution — when the resolver looks up the
        delegate's direct ballot, it finds None and the existing
        ``chain_behavior`` logic (``accept_sub`` / ``revert_direct`` /
        ``abstain``) fires correctly. ``eligible_ids=None`` keeps legacy
        behavior for any call site not yet updated.
        """
        proposal_topics = [pt.topic_id for pt in proposal.proposal_topics]
        voting_method = getattr(proposal, "voting_method", "binary") or "binary"
        # Phase 27 — per-topic relevance from ProposalTopic.relevance.
        # Default 1.0 if a row is missing the field (older fixtures).
        proposal_topic_relevances: dict[str, float] = {
            pt.topic_id: float(getattr(pt, "relevance", 1.0) or 1.0)
            for pt in proposal.proposal_topics
        }

        # All delegations indexed by delegator → topic_id.
        #
        # Phase 18 (B2.1): scoped to the proposal's org. Pre-fix this
        # loaded every Delegation row platform-wide, which is the
        # diagnostic's load-bearing tally read leak (Case 3 / Case 4 in
        # the C&Z prod scenario). Post-fix only delegations whose
        # ``org_id`` matches the proposal's ``org_id`` enter the context.
        # Defensive fallback: when the proposal has no ``org_id`` (legacy
        # / unit-test fixtures pre-Phase-4c), fall back to the unscoped
        # query so existing tests don't regress. Real production proposals
        # always carry an ``org_id`` since Phase 4.
        proposal_org_id = getattr(proposal, "org_id", None)

        # Phase 65 — delegation gating. When the org master switch is off
        # OR any attached topic disallows delegation (D1 whole-proposal
        # semantics), the context is built with an EMPTY delegation map
        # (and empty precedences — they only exist to choose among
        # delegations) so no delegated ballot ever resolves: direct
        # ballots only, everyone else not_cast. Gating here, at the sole
        # delegation-loading chokepoint, automatically covers
        # compute_tally, resolve_vote, the sustained-majority worker,
        # cosign weight resolution, and the vote-graph endpoint. Existing
        # Delegation rows are KEPT (D2) — they're simply not loaded into
        # the context while gated.
        from org_config import proposal_is_delegation_gated

        _gate_org = (
            db.get(models.Organization, proposal_org_id)
            if proposal_org_id is not None
            else None
        )
        _gate_topics: list[models.Topic] = []
        if proposal_topics:
            _gate_topics = (
                db.query(models.Topic)
                .filter(models.Topic.id.in_(proposal_topics))
                .all()
            )
        delegation_gated = proposal_is_delegation_gated(
            proposal, _gate_org, _gate_topics,
        )

        all_delegations: dict[str, dict[Optional[str], DelegationData]] = {}
        all_precedences: dict[str, dict[str, int]] = {}
        if not delegation_gated:
            delegation_query = db.query(models.Delegation)
            if proposal_org_id is not None:
                delegation_query = delegation_query.filter(
                    models.Delegation.org_id == proposal_org_id
                )
            for row in delegation_query.all():
                dd = DelegationData(
                    delegator_id=row.delegator_id,
                    delegate_id=row.delegate_id,
                    topic_id=row.topic_id,
                    chain_behavior=row.chain_behavior,
                )
                all_delegations.setdefault(row.delegator_id, {})[row.topic_id] = dd

            # All topic precedences indexed by user → topic_id
            for row in db.query(models.TopicPrecedence).all():
                all_precedences.setdefault(row.user_id, {})[row.topic_id] = row.priority

        # Direct votes/ballots for this proposal only.
        # Phase 10.1: filter to eligible voters when provided so non-eligible
        # users' rows never enter the resolver's direct_ballots map.
        direct_votes: dict[str, str] = {}
        direct_ballots: dict[str, Ballot] = {}
        vote_query = db.query(models.Vote).filter(
            models.Vote.proposal_id == proposal.id,
            models.Vote.is_direct.is_(True),
        )
        if eligible_ids is not None:
            vote_query = vote_query.filter(models.Vote.user_id.in_(eligible_ids))
        for row in vote_query.all():
            if voting_method == "approval":
                ballot_data = row.ballot or {}
                approvals = ballot_data.get("approvals", [])
                direct_ballots[row.user_id] = Ballot(approvals=approvals)
            elif voting_method == "ranked_choice":
                ballot_data = row.ballot or {}
                ranking = ballot_data.get("ranking", [])
                direct_ballots[row.user_id] = Ballot(ranking=ranking)
            elif voting_method == "budget_allocation":
                # Phase 73 — direct allocation ballot. Delegated budget votes
                # are never materialized as Vote rows (only is_direct rows
                # here); Phase 89 resolves delegation at tally time from these
                # direct ballots, same as approval/RCV.
                ballot_data = row.ballot or {}
                allocations = ballot_data.get("allocations", {})
                direct_ballots[row.user_id] = Ballot(allocations=allocations)
            elif voting_method == "budget_project":
                # Phase 74 + 74b — direct project ballot: ordered list of
                # (option_id, tier_id) pairs (tier_id None for non-tiered
                # items). Order is the ranking; tally_project normalizes.
                ballot_data = row.ballot or {}
                ranked = [
                    (item.get("option_id"), item.get("tier_id"))
                    for item in (ballot_data.get("ranked") or [])
                    if isinstance(item, dict) and item.get("option_id")
                ]
                direct_ballots[row.user_id] = Ballot(project_ranked=ranked)
            else:
                if row.vote_value is not None:
                    direct_votes[row.user_id] = row.vote_value

        # Phase 27 — per-user delegation_strategy lookup. Pulled once per
        # tally; the strategy doesn't change mid-tally (a user toggling
        # mid-resolution picks up the new strategy on the next tally).
        # When eligible_ids isn't supplied, defensively load every user
        # who appears as a delegator in this org (covers the existing
        # un-narrowed call sites in tests without exploding the query).
        strategy_user_ids: set[str] = set()
        if eligible_ids is not None:
            strategy_user_ids.update(eligible_ids)
        else:
            strategy_user_ids.update(all_delegations.keys())
            strategy_user_ids.update(direct_votes.keys())
            strategy_user_ids.update(direct_ballots.keys())
        user_strategies: dict[str, str] = {}
        if strategy_user_ids:
            for uid, strat in (
                db.query(models.User.id, models.User.delegation_strategy)
                .filter(models.User.id.in_(strategy_user_ids))
                .all()
            ):
                user_strategies[uid] = strat or "strict_precedence"

        # Phase 66 — lift the multi-winner approval config onto the
        # context (the pure layer never touches the DB). Phase 66a:
        # approval-method ELECTIONS now attach the config too (the D6
        # carve-out is lifted) — finalize_election consumes the
        # resulting multi-winner set. Non-approval methods never carry
        # a config (route-layer 400s + the method gate here).
        approval_winner_config = None
        if voting_method == "approval":
            approval_winner_config = getattr(
                proposal, "approval_winner_config", None,
            )

        # Phase 73 — lift budget config + bucket specs onto the context for
        # budget_allocation proposals (the pure layer never touches the DB).
        budget_config = None
        budget_buckets = None
        budget_items = None
        if voting_method == "budget_allocation":
            import budget_tally
            budget_config = getattr(proposal, "budget_config", None)
            budget_buckets = [
                budget_tally.BucketSpec(
                    option_id=opt.id,
                    max_amount=getattr(opt, "budget_max_amount", None),
                )
                for opt in proposal.options
            ]
        elif voting_method == "budget_project":
            import budget_tally
            budget_config = getattr(proposal, "budget_config", None)
            # Phase 74 core/74a/74b — build the item list:
            #  - discrete + Mode C continuous-as-discrete fund at their resolved
            #    cost (ceiling-or-floor) — _resolve_project_item_cost.
            #  - tier parents (74b) carry no cost of their own; their tier
            #    CHILDREN (budget_tier_parent_id set) are folded into the
            #    parent's `tiers` and EXCLUDED from the top-level item list
            #    (children aren't ranked directly — only the parent is).
            opts = list(proposal.options)
            children_by_parent: dict = {}
            for opt in opts:
                pid = getattr(opt, "budget_tier_parent_id", None)
                if pid:
                    children_by_parent.setdefault(pid, []).append(opt)
            budget_items = []
            for opt in opts:
                if getattr(opt, "budget_tier_parent_id", None):
                    continue  # a tier child — folded into its parent below
                if getattr(opt, "budget_kind", None) == "tier_parent":
                    tiers = [
                        budget_tally.TierSpec(
                            tier_id=child.id,
                            cost=getattr(child, "budget_floor_amount", None) or 0,
                        )
                        for child in children_by_parent.get(opt.id, [])
                    ]
                    fb = getattr(opt, "tier_allow_fallback", None)
                    budget_items.append(budget_tally.ProjectItemSpec(
                        option_id=opt.id, kind="tier_parent", tiers=tiers,
                        tier_allow_fallback=True if fb is None else bool(fb),
                    ))
                else:
                    budget_items.append(budget_tally.ProjectItemSpec(
                        option_id=opt.id,
                        floor_amount=_resolve_project_item_cost(opt),
                        kind=getattr(opt, "budget_kind", None) or "discrete",
                    ))

        # Phase 88 — per-user voting weights (shares). Populated ONLY when the
        # weight-holding org has weighted voting enabled; otherwise the map
        # stays EMPTY and every weight reduces to 1 (headcount parity). Shares
        # are a parent-org property, so a sub-org proposal resolves weights
        # from the PARENT org's OrgMembership rows.
        from org_config import get_weighted_voting_config

        user_weights: dict[str, int] = {}
        weight_org = _gate_org
        if weight_org is not None and getattr(weight_org, "parent_org_id", None):
            _parent = db.get(models.Organization, weight_org.parent_org_id)
            if _parent is not None:
                weight_org = _parent
        if weight_org is not None and get_weighted_voting_config(weight_org)["enabled"]:
            wq = db.query(
                models.OrgMembership.user_id, models.OrgMembership.voting_weight,
            ).filter(models.OrgMembership.org_id == weight_org.id)
            if eligible_ids is not None:
                wq = wq.filter(models.OrgMembership.user_id.in_(eligible_ids))
            for uid, w in wq.all():
                user_weights[uid] = int(w) if w is not None else 1

        return ProposalContext(
            proposal_topics=proposal_topics,
            all_delegations=all_delegations,
            all_precedences=all_precedences,
            direct_votes=direct_votes,
            direct_ballots=direct_ballots,
            voting_method=voting_method,
            proposal_topic_relevances=proposal_topic_relevances,
            user_strategies=user_strategies,
            approval_winner_config=approval_winner_config,
            budget_config=budget_config,
            budget_buckets=budget_buckets,
            budget_items=budget_items,
            user_weights=user_weights,
        )

    # ------------------------------------------------------------------
    # Public API — mirrors the old DelegationEngine interface
    # ------------------------------------------------------------------

    def find_delegate(
        self, user_id: str, proposal_id: str, db: Session
    ) -> Optional[tuple[str, models.Delegation]]:
        """
        Returns (delegate_id, delegation_row) or None.
        Used by routes that need the ORM delegation object.

        Phase 18 (B2.1): both ORM lookups (per-topic + global fallback)
        now filter on ``org_id == proposal.org_id`` so a global
        delegation in org X cannot resolve a vote on a proposal in org Y.
        Defensive fallback: when ``proposal.org_id`` is None (legacy /
        unit-test fixtures pre-Phase-4c) the filter is skipped so existing
        tests don't regress.
        """
        proposal = db.get(models.Proposal, proposal_id)
        if proposal is None:
            return None

        proposal_org_id = getattr(proposal, "org_id", None)

        topic_ids = [pt.topic_id for pt in proposal.proposal_topics]
        precedences: dict[str, int] = {
            r.topic_id: r.priority
            for r in db.query(models.TopicPrecedence).filter(
                models.TopicPrecedence.user_id == user_id
            ).all()
        }
        sorted_topics = sorted(topic_ids, key=lambda t: precedences.get(t, 9999))

        for topic_id in sorted_topics:
            q = db.query(models.Delegation).filter(
                models.Delegation.delegator_id == user_id,
                models.Delegation.topic_id == topic_id,
            )
            if proposal_org_id is not None:
                q = q.filter(models.Delegation.org_id == proposal_org_id)
            row = q.first()
            if row:
                return row.delegate_id, row

        global_q = db.query(models.Delegation).filter(
            models.Delegation.delegator_id == user_id,
            models.Delegation.topic_id.is_(None),
        )
        if proposal_org_id is not None:
            global_q = global_q.filter(
                models.Delegation.org_id == proposal_org_id
            )
        global_row = global_q.first()
        if global_row:
            return global_row.delegate_id, global_row

        return None

    def resolve_vote(
        self,
        user_id: str,
        proposal_id: str,
        db: Session,
        _visited: Optional[set[str]] = None,
    ) -> Optional[VoteResult]:
        """
        Build a ProposalContext from the DB and call the pure resolver.

        Phase 10.1: pass the eligible-voter set through to ``_build_context`` so
        a delegation chain that lands on a non-eligible direct ballot doesn't
        leak that ballot back through resolution.
        """
        proposal = db.get(models.Proposal, proposal_id)
        if proposal is None:
            return None
        eligible_ids = eligible_voter_ids_for_proposal(db, proposal)
        ctx = self._build_context(proposal, db, eligible_ids=eligible_ids)
        return resolve_vote_pure(user_id, ctx, _visited)

    def compute_tally(
        self, proposal: models.Proposal, db: Session
    ) -> ProposalTally | ApprovalTally | RCVTally:
        """
        Build context once, resolve all eligible users, return aggregate tally.

        Phase 10.1 (cross-scope vote leak fix): single helper covers all three
        scope cases (sub-org / parent-org / no-org legacy). Pre-fix, the
        ``else`` branch iterated every user in the platform — that leaked
        votes from cross-org users into any org-scoped tally. ``sorted(...)``
        gives the same deterministic RCV/STV ballot insertion order the old
        ``db.query(User.id).all()`` path was rationalized for, without the
        leak. The eligibility filter is also propagated into ``_build_context``
        so a non-eligible user's pre-fix Vote row can't leak through delegation
        chain resolution either.
        """
        eligible_ids = eligible_voter_ids_for_proposal(db, proposal)
        ctx = self._build_context(proposal, db, eligible_ids=eligible_ids)
        # Sort by User.id for deterministic RCV/STV ballot insertion order.
        # eligible_voter_ids_for_proposal already dispatches on sub_org_id vs
        # org_id vs no-org, so the same call covers all three scope cases.
        user_ids = sorted(eligible_ids)
        option_ids: list[str] = []
        num_winners = getattr(proposal, "num_winners", 1) or 1
        if ctx.voting_method == "ranked_choice":
            option_ids = [opt.id for opt in proposal.options]
        return compute_tally_pure(
            user_ids, ctx,
            option_ids=option_ids,
            num_winners=num_winners,
        )

    @staticmethod
    def _get_strategy(user: models.User, voting_method: str = "binary") -> str:
        """
        Read user's delegation_strategy.  Only 'strict_precedence' is
        implemented; anything else falls back with a warning.
        Non-strict-precedence strategies always fall back to
        strict_precedence for approval proposals.
        """
        strategy = getattr(user, "delegation_strategy", "strict_precedence")
        if strategy != "strict_precedence":
            if voting_method in ("approval", "ranked_choice"):
                log.info(
                    "Non-strict-precedence strategy %r for user %s falls back to "
                    "strict_precedence for %s proposal",
                    strategy,
                    user.id,
                    voting_method,
                )
            else:
                log.warning(
                    "Unknown delegation_strategy %r for user %s — falling back to strict_precedence",
                    strategy,
                    user.id,
                )
        return "strict_precedence"


# ---------------------------------------------------------------------------
# Backward-compat shim — routes import `engine` and call the same methods
# ---------------------------------------------------------------------------

class DelegationEngine(DelegationService):
    """
    Preserved for backward compatibility with existing route imports.
    DelegationService is the real implementation.
    """
    pass


# ---------------------------------------------------------------------------
# Module-level singletons (initialised in main.py startup)
# ---------------------------------------------------------------------------

graph_store = DelegationGraphStore()
engine = DelegationEngine(graph_store)
