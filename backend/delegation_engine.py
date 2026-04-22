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
  DelegationGraphStore  — per-topic DiGraphs for cycle detection

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


# ---------------------------------------------------------------------------
# Shared data classes
# ---------------------------------------------------------------------------

@dataclass
class Ballot:
    """Unified ballot representation for all voting methods."""
    vote_value: Optional[str] = None       # "yes" | "no" | "abstain" (binary)
    approvals: Optional[list[str]] = None  # list of option_ids (approval)

    @property
    def voting_method(self) -> str:
        if self.vote_value is not None:
            return "binary"
        if self.approvals is not None:
            return "approval"
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


# ---------------------------------------------------------------------------
# Pure layer — no DB access, fully testable without fixtures
# ---------------------------------------------------------------------------

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

    # 2. Find delegate
    user_delegations = ctx.all_delegations.get(user_id, {})
    user_precedences = ctx.all_precedences.get(user_id, {})
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
) -> ProposalTally | ApprovalTally:
    """
    Compute a full tally by resolving every user's vote.
    Pure function — no DB access.
    Dispatches on ctx.voting_method.
    """
    if ctx.voting_method == "approval":
        return _compute_approval_tally_pure(user_ids, ctx)
    return _compute_binary_tally_pure(user_ids, ctx)


def _compute_binary_tally_pure(
    user_ids: list[str],
    ctx: ProposalContext,
) -> ProposalTally:
    tally = ProposalTally(total_eligible=len(user_ids))
    for uid in user_ids:
        result = resolve_vote_pure(uid, ctx)
        if result is None:
            tally.not_cast += 1
        elif result.vote_value == "yes":
            tally.yes += 1
        elif result.vote_value == "no":
            tally.no += 1
        elif result.vote_value == "abstain":
            tally.abstain += 1
    return tally


def _compute_approval_tally_pure(
    user_ids: list[str],
    ctx: ProposalContext,
) -> ApprovalTally:
    """Compute approval tally: count how many ballots approve each option."""
    option_approvals: dict[str, int] = {}
    total_ballots_cast = 0
    total_abstain = 0
    not_cast = 0

    for uid in user_ids:
        result = resolve_vote_pure(uid, ctx)
        if result is None:
            not_cast += 1
            continue
        total_ballots_cast += 1
        approvals = result.ballot.approvals
        if approvals is not None:
            if len(approvals) == 0:
                total_abstain += 1
            else:
                for oid in approvals:
                    option_approvals[oid] = option_approvals.get(oid, 0) + 1

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
        total_eligible=len(user_ids),
        winners=winners,
        tied=tied,
    )


# ---------------------------------------------------------------------------
# Graph store — thread-safe, in-memory NetworkX graphs for cycle detection
# ---------------------------------------------------------------------------

class DelegationGraphStore:
    """
    Keeps one directed graph per topic (plus a global graph for topic=None).
    Each edge  delegator -> delegate  represents an active delegation.

    Thread-safe: a single lock guards all mutations.
    """

    GLOBAL_KEY = "__global__"

    def __init__(self) -> None:
        self._graphs: dict[str, nx.DiGraph] = {}
        self._lock = Lock()

    def _key(self, topic_id: Optional[str]) -> str:
        return topic_id if topic_id else self.GLOBAL_KEY

    def _get_or_create(self, topic_id: Optional[str]) -> nx.DiGraph:
        k = self._key(topic_id)
        if k not in self._graphs:
            self._graphs[k] = nx.DiGraph()
        return self._graphs[k]

    def rebuild_from_db(self, db: Session) -> None:
        """Replace all in-memory graphs with the current DB state."""
        with self._lock:
            self._graphs = {}
            delegations: list[models.Delegation] = db.query(models.Delegation).all()
            for d in delegations:
                g = self._get_or_create(d.topic_id)
                g.add_edge(d.delegator_id, d.delegate_id)

    def would_create_cycle(
        self, delegator_id: str, delegate_id: str, topic_id: Optional[str]
    ) -> bool:
        with self._lock:
            for tid in (topic_id, None):
                g = self._get_or_create(tid)
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
        self, delegator_id: str, delegate_id: str, topic_id: Optional[str]
    ) -> None:
        with self._lock:
            g = self._get_or_create(topic_id)
            if delegator_id in g:
                for old in list(g.successors(delegator_id)):
                    g.remove_edge(delegator_id, old)
            g.add_edge(delegator_id, delegate_id)

    def remove_delegation(
        self, delegator_id: str, topic_id: Optional[str]
    ) -> None:
        with self._lock:
            g = self._get_or_create(topic_id)
            if delegator_id in g:
                for d in list(g.successors(delegator_id)):
                    g.remove_edge(delegator_id, d)

    def get_neighborhood(
        self, user_id: str, topic_id: Optional[str] = None
    ) -> tuple[set[str], list[tuple[str, str, Optional[str]]]]:
        nodes: set[str] = {user_id}
        edges: list[tuple[str, str, Optional[str]]] = []
        topic_keys = [self._key(topic_id)] if topic_id else list(self._graphs.keys())
        for key in topic_keys:
            if key not in self._graphs:
                continue
            g = self._graphs[key]
            tid = None if key == self.GLOBAL_KEY else key
            if user_id in g:
                for nb in g.successors(user_id):
                    nodes.add(nb)
                    edges.append((user_id, nb, tid))
                for nb in g.predecessors(user_id):
                    nodes.add(nb)
                    edges.append((nb, user_id, tid))
        return nodes, edges

    def compute_voting_weight(self, user_id: str) -> int:
        g = self._graphs.get(self.GLOBAL_KEY)
        if g is None or user_id not in g:
            return 1
        try:
            predecessors = nx.ancestors(g, user_id)
        except nx.NetworkXError:
            predecessors = set()
        return 1 + len(predecessors)


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
    def _build_context(proposal: models.Proposal, db: Session) -> ProposalContext:
        """
        Fetch everything needed to resolve all votes on a proposal and pack it
        into a ProposalContext.
        """
        proposal_topics = [pt.topic_id for pt in proposal.proposal_topics]
        voting_method = getattr(proposal, "voting_method", "binary") or "binary"

        # All delegations indexed by delegator → topic_id
        all_delegations: dict[str, dict[Optional[str], DelegationData]] = {}
        for row in db.query(models.Delegation).all():
            dd = DelegationData(
                delegator_id=row.delegator_id,
                delegate_id=row.delegate_id,
                topic_id=row.topic_id,
                chain_behavior=row.chain_behavior,
            )
            all_delegations.setdefault(row.delegator_id, {})[row.topic_id] = dd

        # All topic precedences indexed by user → topic_id
        all_precedences: dict[str, dict[str, int]] = {}
        for row in db.query(models.TopicPrecedence).all():
            all_precedences.setdefault(row.user_id, {})[row.topic_id] = row.priority

        # Direct votes/ballots for this proposal only
        direct_votes: dict[str, str] = {}
        direct_ballots: dict[str, Ballot] = {}
        for row in db.query(models.Vote).filter(
            models.Vote.proposal_id == proposal.id,
            models.Vote.is_direct.is_(True),
        ).all():
            if voting_method == "approval":
                ballot_data = row.ballot or {}
                approvals = ballot_data.get("approvals", [])
                direct_ballots[row.user_id] = Ballot(approvals=approvals)
            else:
                if row.vote_value is not None:
                    direct_votes[row.user_id] = row.vote_value

        return ProposalContext(
            proposal_topics=proposal_topics,
            all_delegations=all_delegations,
            all_precedences=all_precedences,
            direct_votes=direct_votes,
            direct_ballots=direct_ballots,
            voting_method=voting_method,
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
        """
        proposal = db.get(models.Proposal, proposal_id)
        if proposal is None:
            return None

        topic_ids = [pt.topic_id for pt in proposal.proposal_topics]
        precedences: dict[str, int] = {
            r.topic_id: r.priority
            for r in db.query(models.TopicPrecedence).filter(
                models.TopicPrecedence.user_id == user_id
            ).all()
        }
        sorted_topics = sorted(topic_ids, key=lambda t: precedences.get(t, 9999))

        for topic_id in sorted_topics:
            row = db.query(models.Delegation).filter(
                models.Delegation.delegator_id == user_id,
                models.Delegation.topic_id == topic_id,
            ).first()
            if row:
                return row.delegate_id, row

        global_row = db.query(models.Delegation).filter(
            models.Delegation.delegator_id == user_id,
            models.Delegation.topic_id.is_(None),
        ).first()
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
        """
        proposal = db.get(models.Proposal, proposal_id)
        if proposal is None:
            return None
        ctx = self._build_context(proposal, db)
        return resolve_vote_pure(user_id, ctx, _visited)

    def compute_tally(
        self, proposal: models.Proposal, db: Session
    ) -> ProposalTally:
        """
        Build context once, resolve all users, return aggregate tally.
        """
        ctx = self._build_context(proposal, db)
        all_user_ids = [u.id for u in db.query(models.User.id).all()]
        return compute_tally_pure(all_user_ids, ctx)

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
            if voting_method == "approval":
                log.info(
                    "Non-strict-precedence strategy %r for user %s falls back to "
                    "strict_precedence for approval proposal",
                    strategy,
                    user.id,
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
