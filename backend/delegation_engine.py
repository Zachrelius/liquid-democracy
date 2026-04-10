"""
Delegation Engine
=================
Core logic for:
  - Maintaining per-topic delegation graphs in NetworkX (cycle detection).
  - Resolving a user's effective vote on a proposal following the
    non-transitive-by-default algorithm described in the brief.
  - Computing full proposal tallies across all eligible users.
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
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class VoteResult:
    vote_value: str                  # "yes" | "no" | "abstain"
    is_direct: bool
    delegate_chain: list[str]        # user IDs in delegation path
    cast_by_id: str


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
        if self.votes_cast == 0:
            return 0.0
        return self.yes / self.votes_cast

    @property
    def no_pct(self) -> float:
        if self.votes_cast == 0:
            return 0.0
        return self.no / self.votes_cast

    @property
    def abstain_pct(self) -> float:
        if self.votes_cast == 0:
            return 0.0
        return self.abstain / self.votes_cast

    def quorum_met(self, threshold: float) -> bool:
        if self.total_eligible == 0:
            return False
        return self.votes_cast / self.total_eligible >= threshold

    def threshold_met(self, threshold: float) -> bool:
        return self.yes_pct >= threshold


# ---------------------------------------------------------------------------
# Graph store
# ---------------------------------------------------------------------------


class DelegationGraphStore:
    """
    Keeps one directed graph per topic (plus a global graph for topic=None).
    Each graph edge  delegator -> delegate  represents an active delegation.

    Thread-safe: a single lock guards all mutations.  Read operations on
    NetworkX DiGraph objects are safe under the GIL; only structural mutations
    need the lock.
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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def rebuild_from_db(self, db: Session) -> None:
        """Replace all in-memory graphs with the current DB state."""
        with self._lock:
            self._graphs = {}
            delegations: list[models.Delegation] = db.query(models.Delegation).all()
            for d in delegations:
                g = self._get_or_create(d.topic_id)
                g.add_edge(d.delegator_id, d.delegate_id)

    def would_create_cycle(self, delegator_id: str, delegate_id: str, topic_id: Optional[str]) -> bool:
        """
        Return True if adding delegator -> delegate would introduce a cycle
        in the graph for *topic_id*.  Checks both the topic-specific graph
        and the global graph (a global delegation can propagate along either).
        """
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

    def add_delegation(self, delegator_id: str, delegate_id: str, topic_id: Optional[str]) -> None:
        with self._lock:
            g = self._get_or_create(topic_id)
            # Remove any existing out-edge from delegator in this topic graph
            # (each delegator has at most one delegate per topic).
            if delegator_id in g:
                for old_delegate in list(g.successors(delegator_id)):
                    g.remove_edge(delegator_id, old_delegate)
            g.add_edge(delegator_id, delegate_id)

    def remove_delegation(self, delegator_id: str, topic_id: Optional[str]) -> None:
        with self._lock:
            g = self._get_or_create(topic_id)
            if delegator_id in g:
                for delegate in list(g.successors(delegator_id)):
                    g.remove_edge(delegator_id, delegate)

    def get_neighborhood(
        self, user_id: str, topic_id: Optional[str] = None
    ) -> tuple[set[str], list[tuple[str, str, Optional[str]]]]:
        """
        Return (node_ids, edges) for the immediate neighbourhood of user_id
        across all graphs (or one specific topic graph).
        edges are (source, target, topic_id).
        """
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
        """
        Count how many users (directly or transitively) have delegated
        their vote to user_id across all topic graphs combined.
        Uses the global graph as an approximation (good enough for UI sizing).
        """
        g = self._graphs.get(self.GLOBAL_KEY)
        if g is None or user_id not in g:
            return 1
        # Count all ancestors in the graph
        try:
            predecessors = nx.ancestors(g, user_id)
        except nx.NetworkXError:
            predecessors = set()
        return 1 + len(predecessors)


# ---------------------------------------------------------------------------
# Resolution engine
# ---------------------------------------------------------------------------


class DelegationEngine:
    """
    Resolves effective votes and computes tallies.
    Stateless with respect to the DB — all state lives in the graph store.
    """

    def __init__(self, graph_store: DelegationGraphStore) -> None:
        self.graphs = graph_store

    # ------------------------------------------------------------------
    # Internal DB helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_direct_vote(user_id: str, proposal_id: str, db: Session) -> Optional[models.Vote]:
        return (
            db.query(models.Vote)
            .filter(
                models.Vote.proposal_id == proposal_id,
                models.Vote.user_id == user_id,
                models.Vote.is_direct.is_(True),
            )
            .first()
        )

    @staticmethod
    def _get_topic_ids(proposal_id: str, db: Session) -> list[str]:
        rows = (
            db.query(models.ProposalTopic.topic_id)
            .filter(models.ProposalTopic.proposal_id == proposal_id)
            .all()
        )
        return [r[0] for r in rows]

    @staticmethod
    def _get_user_precedences(user_id: str, db: Session) -> dict[str, int]:
        """Returns {topic_id: priority} — lower number = higher priority."""
        rows = (
            db.query(models.TopicPrecedence.topic_id, models.TopicPrecedence.priority)
            .filter(models.TopicPrecedence.user_id == user_id)
            .all()
        )
        return {r[0]: r[1] for r in rows}

    @staticmethod
    def _get_delegation_for_topic(
        delegator_id: str, topic_id: Optional[str], db: Session
    ) -> Optional[models.Delegation]:
        return (
            db.query(models.Delegation)
            .filter(
                models.Delegation.delegator_id == delegator_id,
                models.Delegation.topic_id == topic_id,
            )
            .first()
        )

    # ------------------------------------------------------------------
    # find_delegate
    # ------------------------------------------------------------------

    def find_delegate(
        self, user_id: str, proposal_id: str, db: Session
    ) -> Optional[tuple[str, models.Delegation]]:
        """
        Determine which delegate should vote for user_id on proposal_id.
        Returns (delegate_id, delegation_row) or None.

        Algorithm:
          1. Sort the proposal's topics by user's precedence (lowest int first).
          2. Find the first topic that has an active delegation.
          3. Fall back to the global (topic=None) delegation.
        """
        topic_ids = self._get_topic_ids(proposal_id, db)
        precedences = self._get_user_precedences(user_id, db)

        sorted_topics = sorted(topic_ids, key=lambda t: precedences.get(t, 9999))

        for topic_id in sorted_topics:
            delegation = self._get_delegation_for_topic(user_id, topic_id, db)
            if delegation:
                return delegation.delegate_id, delegation

        global_delegation = self._get_delegation_for_topic(user_id, None, db)
        if global_delegation:
            return global_delegation.delegate_id, global_delegation

        return None

    # ------------------------------------------------------------------
    # resolve_vote
    # ------------------------------------------------------------------

    def resolve_vote(
        self,
        user_id: str,
        proposal_id: str,
        db: Session,
        _visited: Optional[set[str]] = None,
    ) -> Optional[VoteResult]:
        """
        Return the effective VoteResult for user_id on proposal_id, or None
        if no vote can be determined.

        Implements the algorithm from the brief:
          1. Direct vote → use it.
          2. Find delegate via topic precedence + global fallback.
          3. Check if delegate voted directly → use that (non-transitive default).
          4. Apply chain_behavior if delegate did not vote directly.
        """
        if _visited is None:
            _visited = set()

        if user_id in _visited:
            # Cycle guard — shouldn't happen after cycle-check on insert, but
            # be defensive.
            return None
        _visited.add(user_id)

        # 1. Direct vote
        direct = self._get_direct_vote(user_id, proposal_id, db)
        if direct:
            return VoteResult(
                vote_value=direct.vote_value,
                is_direct=True,
                delegate_chain=[],
                cast_by_id=user_id,
            )

        # 2. Find delegate
        result = self.find_delegate(user_id, proposal_id, db)
        if result is None:
            return None
        delegate_id, delegation = result

        # 3. Did the delegate vote directly?
        delegate_direct = self._get_direct_vote(delegate_id, proposal_id, db)
        if delegate_direct:
            return VoteResult(
                vote_value=delegate_direct.vote_value,
                is_direct=False,
                delegate_chain=[delegate_id],
                cast_by_id=delegate_id,
            )

        # 4. Delegate did not vote directly — apply chain_behavior
        if delegation.chain_behavior == "accept_sub":
            # Walk one level deeper via the delegate's own delegation
            sub_result = self.find_delegate(delegate_id, proposal_id, db)
            if sub_result is None:
                return None
            sub_delegate_id, _ = sub_result
            if sub_delegate_id in _visited:
                return None  # Cycle in sub-chain

            sub_direct = self._get_direct_vote(sub_delegate_id, proposal_id, db)
            if sub_direct:
                return VoteResult(
                    vote_value=sub_direct.vote_value,
                    is_direct=False,
                    delegate_chain=[delegate_id, sub_delegate_id],
                    cast_by_id=sub_delegate_id,
                )
            return None

        elif delegation.chain_behavior == "revert_direct":
            # Signal that the user needs to vote themselves
            return None

        elif delegation.chain_behavior == "abstain":
            return None

        return None

    # ------------------------------------------------------------------
    # Tally
    # ------------------------------------------------------------------

    def compute_tally(self, proposal: models.Proposal, db: Session) -> ProposalTally:
        """
        Iterate all users and resolve each one's vote for proposal.
        This is called on-read (with a short cache in the route layer).
        """
        all_users: list[models.User] = db.query(models.User).all()
        tally = ProposalTally(total_eligible=len(all_users))

        for user in all_users:
            result = self.resolve_vote(user.id, proposal.id, db)
            if result is None:
                tally.not_cast += 1
            elif result.vote_value == "yes":
                tally.yes += 1
            elif result.vote_value == "no":
                tally.no += 1
            elif result.vote_value == "abstain":
                tally.abstain += 1

        return tally


# ---------------------------------------------------------------------------
# Module-level singletons (initialised in main.py startup)
# ---------------------------------------------------------------------------

graph_store = DelegationGraphStore()
engine = DelegationEngine(graph_store)
