"""Phase 27 — relevance-weighted delegation tests.

Covers backend clusters B1 (pure resolver), B2 (dispatcher in
resolve_vote_pure), B3 (migration), B4 (PATCH /api/users/me/delegation-
strategy endpoint), and the service-layer _build_context populating the
new context fields.

Pure-function tests use synthetic ProposalContext objects (no DB).
Endpoint tests use TestClient with the existing get_db override pattern.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
import schemas  # noqa: F401 — for completeness
from database import Base, get_db
from main import app
from delegation_engine import (
    Ballot,
    BallotResult,
    DelegationData,
    DelegationService,
    DelegationGraphStore,
    ProposalContext,
    find_vote_via_relevance_weighting_pure,
    resolve_vote_pure,
)
from tests.conftest import make_org_membership


_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ctx(
    *,
    proposal_topics: list[str],
    relevances: dict[str, float] | None = None,
    delegations: dict[str, dict[str | None, DelegationData]] | None = None,
    precedences: dict[str, dict[str, int]] | None = None,
    direct_votes: dict[str, str] | None = None,
    user_strategies: dict[str, str] | None = None,
    voting_method: str = "binary",
) -> ProposalContext:
    return ProposalContext(
        proposal_topics=proposal_topics,
        all_delegations=delegations or {},
        all_precedences=precedences or {},
        direct_votes=direct_votes or {},
        direct_ballots={},
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
# B1 — Pure resolver: find_vote_via_relevance_weighting_pure
# ===========================================================================

class TestRelevanceWeightedSingleDelegateWins:
    def test_single_topic_single_delegate(self):
        ctx = _ctx(
            proposal_topics=["t1"],
            relevances={"t1": 1.0},
            delegations={"alice": {"t1": _dd("bob", "t1")}},
            direct_votes={"bob": "yes"},
        )
        result = find_vote_via_relevance_weighting_pure(
            user_id="alice",
            proposal_topics=["t1"],
            proposal_topic_relevances={"t1": 1.0},
            user_precedences={},
            user_delegations={"t1": _dd("bob", "t1")},
            ctx=ctx,
        )
        assert result is not None
        assert result.ballot.vote_value == "yes"
        assert result.delegate_chain == ["bob"]
        assert result.is_direct is False


class TestRelevanceWeightedTwoDelegatesAgreeing:
    def test_both_yes_sums(self):
        ctx = _ctx(
            proposal_topics=["t1", "t2"],
            relevances={"t1": 0.6, "t2": 0.4},
            delegations={
                "alice": {"t1": _dd("bob", "t1"), "t2": _dd("carol", "t2")},
            },
            direct_votes={"bob": "yes", "carol": "yes"},
        )
        result = find_vote_via_relevance_weighting_pure(
            user_id="alice",
            proposal_topics=["t1", "t2"],
            proposal_topic_relevances={"t1": 0.6, "t2": 0.4},
            user_precedences={},
            user_delegations={"t1": _dd("bob", "t1"), "t2": _dd("carol", "t2")},
            ctx=ctx,
        )
        assert result is not None
        assert result.ballot.vote_value == "yes"
        # Representative = highest individual relevance entry.
        assert result.delegate_chain == ["bob"]


class TestRelevanceWeightedTwoDelegatesDisagreeing:
    def test_higher_relevance_wins(self):
        ctx = _ctx(
            proposal_topics=["health", "econ"],
            relevances={"health": 0.7, "econ": 0.3},
            delegations={
                "alice": {
                    "health": _dd("alice_health", "health"),
                    "econ": _dd("alice_econ", "econ"),
                },
            },
            direct_votes={"alice_health": "yes", "alice_econ": "no"},
        )
        result = find_vote_via_relevance_weighting_pure(
            user_id="alice",
            proposal_topics=["health", "econ"],
            proposal_topic_relevances={"health": 0.7, "econ": 0.3},
            user_precedences={},
            user_delegations={
                "health": _dd("alice_health", "health"),
                "econ": _dd("alice_econ", "econ"),
            },
            ctx=ctx,
        )
        assert result.ballot.vote_value == "yes"
        assert result.delegate_chain == ["alice_health"]


class TestRelevanceWeightedTie:
    """Equal relevance + strict-precedence tiebreaker."""

    def test_precedence_tiebreaker(self):
        ctx = _ctx(
            proposal_topics=["health", "econ"],
            relevances={"health": 0.5, "econ": 0.5},
            delegations={
                "alice": {
                    "health": _dd("a_h", "health"),
                    "econ": _dd("a_e", "econ"),
                },
            },
            direct_votes={"a_h": "yes", "a_e": "no"},
            precedences={"alice": {"health": 1, "econ": 2}},
        )
        # health priority 1 (higher) wins the tie → yes
        result = find_vote_via_relevance_weighting_pure(
            user_id="alice",
            proposal_topics=["health", "econ"],
            proposal_topic_relevances={"health": 0.5, "econ": 0.5},
            user_precedences={"health": 1, "econ": 2},
            user_delegations={
                "health": _dd("a_h", "health"),
                "econ": _dd("a_e", "econ"),
            },
            ctx=ctx,
        )
        assert result.ballot.vote_value == "yes"

    def test_reverse_precedence_flips_outcome(self):
        """Same tie, reversed precedence → no wins."""
        ctx = _ctx(
            proposal_topics=["health", "econ"],
            relevances={"health": 0.5, "econ": 0.5},
            delegations={
                "alice": {
                    "health": _dd("a_h", "health"),
                    "econ": _dd("a_e", "econ"),
                },
            },
            direct_votes={"a_h": "yes", "a_e": "no"},
            precedences={"alice": {"econ": 1, "health": 2}},
        )
        result = find_vote_via_relevance_weighting_pure(
            user_id="alice",
            proposal_topics=["health", "econ"],
            proposal_topic_relevances={"health": 0.5, "econ": 0.5},
            user_precedences={"econ": 1, "health": 2},
            user_delegations={
                "health": _dd("a_h", "health"),
                "econ": _dd("a_e", "econ"),
            },
            ctx=ctx,
        )
        assert result.ballot.vote_value == "no"


class TestRelevanceWeightedThreeWayMix:
    def test_two_yes_one_no(self):
        ctx = _ctx(
            proposal_topics=["t1", "t2", "t3"],
            relevances={"t1": 0.4, "t2": 0.4, "t3": 0.2},
            delegations={
                "alice": {
                    "t1": _dd("d1", "t1"),
                    "t2": _dd("d2", "t2"),
                    "t3": _dd("d3", "t3"),
                },
            },
            direct_votes={"d1": "yes", "d2": "yes", "d3": "no"},
        )
        result = find_vote_via_relevance_weighting_pure(
            user_id="alice",
            proposal_topics=["t1", "t2", "t3"],
            proposal_topic_relevances={"t1": 0.4, "t2": 0.4, "t3": 0.2},
            user_precedences={},
            user_delegations={
                "t1": _dd("d1", "t1"),
                "t2": _dd("d2", "t2"),
                "t3": _dd("d3", "t3"),
            },
            ctx=ctx,
        )
        # yes total 0.8 vs no 0.2 → yes wins
        assert result.ballot.vote_value == "yes"


class TestRelevanceWeightedDelegateAbstain:
    def test_abstain_counts_for_abstain_direction(self):
        ctx = _ctx(
            proposal_topics=["t1", "t2"],
            relevances={"t1": 0.7, "t2": 0.3},
            delegations={
                "alice": {
                    "t1": _dd("d1", "t1"),
                    "t2": _dd("d2", "t2"),
                },
            },
            direct_votes={"d1": "abstain", "d2": "no"},
        )
        result = find_vote_via_relevance_weighting_pure(
            user_id="alice",
            proposal_topics=["t1", "t2"],
            proposal_topic_relevances={"t1": 0.7, "t2": 0.3},
            user_precedences={},
            user_delegations={
                "t1": _dd("d1", "t1"),
                "t2": _dd("d2", "t2"),
            },
            ctx=ctx,
        )
        # abstain total 0.7 > no 0.3 → abstain wins
        assert result.ballot.vote_value == "abstain"


class TestRelevanceWeightedDelegateDidntVote:
    """A delegate who hasn't voted contributes nothing to any direction."""

    def test_silent_delegate_excluded_with_revert_direct(self):
        # d1 didn't vote, chain_behavior=revert_direct (no fallback). Only
        # d2's no contributes; result is no.
        ctx = _ctx(
            proposal_topics=["t1", "t2"],
            relevances={"t1": 0.7, "t2": 0.3},
            delegations={
                "alice": {
                    "t1": _dd("d1", "t1", chain="revert_direct"),
                    "t2": _dd("d2", "t2"),
                },
            },
            direct_votes={"d2": "no"},  # d1 silent
        )
        result = find_vote_via_relevance_weighting_pure(
            user_id="alice",
            proposal_topics=["t1", "t2"],
            proposal_topic_relevances={"t1": 0.7, "t2": 0.3},
            user_precedences={},
            user_delegations={
                "t1": _dd("d1", "t1", chain="revert_direct"),
                "t2": _dd("d2", "t2"),
            },
            ctx=ctx,
        )
        assert result.ballot.vote_value == "no"


class TestRelevanceWeightedNoDelegationsOnAnyTopic:
    def test_returns_none_so_caller_falls_through(self):
        ctx = _ctx(
            proposal_topics=["t1"],
            relevances={"t1": 1.0},
            delegations={"alice": {}},
        )
        result = find_vote_via_relevance_weighting_pure(
            user_id="alice",
            proposal_topics=["t1"],
            proposal_topic_relevances={"t1": 1.0},
            user_precedences={},
            user_delegations={},
            ctx=ctx,
        )
        assert result is None


# ===========================================================================
# B2 — Dispatcher in resolve_vote_pure
# ===========================================================================

class TestDispatcherStrictPrecedenceUserUnchanged:
    """A user explicitly on 'strict_precedence' takes the existing code
    path even when proposal has per-topic relevance scores set."""

    def test_strict_user_uses_precedence_path(self):
        # Setup: relevances would favor no (0.7) but strict-precedence
        # of t_yes (priority 1) wins.
        ctx = _ctx(
            proposal_topics=["t_yes", "t_no"],
            relevances={"t_yes": 0.3, "t_no": 0.7},
            delegations={
                "alice": {
                    "t_yes": _dd("d_yes", "t_yes"),
                    "t_no": _dd("d_no", "t_no"),
                },
            },
            direct_votes={"d_yes": "yes", "d_no": "no"},
            precedences={"alice": {"t_yes": 1, "t_no": 2}},
            user_strategies={"alice": "strict_precedence"},
        )
        result = resolve_vote_pure(user_id="alice", ctx=ctx)
        assert result is not None
        # Strict-precedence picks t_yes (priority 1) → yes, ignoring
        # the larger 0.7 relevance on t_no.
        assert result.ballot.vote_value == "yes"


class TestDispatcherRelevanceWeightedUserUsesNewPath:
    def test_relevance_user_uses_relevance_resolver(self):
        ctx = _ctx(
            proposal_topics=["t_yes", "t_no"],
            relevances={"t_yes": 0.3, "t_no": 0.7},
            delegations={
                "alice": {
                    "t_yes": _dd("d_yes", "t_yes"),
                    "t_no": _dd("d_no", "t_no"),
                },
            },
            direct_votes={"d_yes": "yes", "d_no": "no"},
            precedences={"alice": {"t_yes": 1, "t_no": 2}},
            user_strategies={"alice": "relevance_weighted"},
        )
        result = resolve_vote_pure(user_id="alice", ctx=ctx)
        assert result is not None
        # 0.7 > 0.3 → no wins, even though t_yes has higher priority.
        assert result.ballot.vote_value == "no"


class TestDispatcherApprovalProposalFallsBackToStrict:
    """Approval voting method → relevance-weighted bypassed; strict-
    precedence applies even when user is on relevance_weighted strategy."""

    def test_approval_method_uses_strict(self):
        ctx = _ctx(
            proposal_topics=["t_a", "t_b"],
            relevances={"t_a": 0.1, "t_b": 0.9},
            delegations={
                "alice": {
                    "t_a": _dd("d_a", "t_a"),
                    "t_b": _dd("d_b", "t_b"),
                },
            },
            # Approval ballots stored as ballots on Ballot.approvals (not
            # used here — the precedence-fall-through is what matters).
            direct_votes={},  # no binary votes
            precedences={"alice": {"t_a": 1, "t_b": 2}},
            user_strategies={"alice": "relevance_weighted"},
            voting_method="approval",
        )
        # Approval flows fall back to strict-precedence: t_a (priority 1)
        # wins, delegate is d_a, but d_a has no ballot — chain_behavior
        # defaults to accept_sub which has no sub-delegate → None.
        # Important property: relevance-weighted was NOT activated despite
        # the user strategy, because voting_method != binary. The
        # result is None (no vote resolved) — same outcome as a
        # strict_precedence user with the same shape.
        result = resolve_vote_pure(user_id="alice", ctx=ctx)
        assert result is None


# ===========================================================================
# B4 — PATCH /api/users/me/delegation-strategy
# ===========================================================================

@pytest.fixture(scope="function")
def api_db():
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


def _make_client(db: Session) -> TestClient:
    def _override_db():
        try:
            yield db
        finally:
            pass
    app.dependency_overrides[get_db] = _override_db
    return TestClient(app)


def _user_row(db: Session, username: str, *, strategy: str = "strict_precedence") -> models.User:
    u = models.User(
        username=username,
        display_name=username.title(),
        password_hash=_DUMMY_HASH,
        email=f"{username}@test.example",
        email_verified=True,
        delegation_strategy=strategy,
    )
    db.add(u)
    db.flush()
    return u


def _login_token(user: models.User) -> str:
    return auth_utils.create_access_token(user.id)


class TestStrategyEndpointUpdatesUser:
    def test_patch_updates_strategy(self, api_db):
        user = _user_row(api_db, "alice", strategy="strict_precedence")
        api_db.commit()
        client = _make_client(api_db)
        token = _login_token(user)
        try:
            resp = client.patch(
                "/api/users/me/delegation-strategy",
                json={"strategy": "relevance_weighted"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["delegation_strategy"] == "relevance_weighted"
            api_db.refresh(user)
            assert user.delegation_strategy == "relevance_weighted"
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_patch_back_to_strict(self, api_db):
        user = _user_row(api_db, "alice", strategy="relevance_weighted")
        api_db.commit()
        client = _make_client(api_db)
        token = _login_token(user)
        try:
            resp = client.patch(
                "/api/users/me/delegation-strategy",
                json={"strategy": "strict_precedence"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["delegation_strategy"] == "strict_precedence"
        finally:
            app.dependency_overrides.pop(get_db, None)


class TestStrategyEndpointRejectsInvalid:
    def test_invalid_strategy_400(self, api_db):
        user = _user_row(api_db, "alice")
        api_db.commit()
        client = _make_client(api_db)
        token = _login_token(user)
        try:
            resp = client.patch(
                "/api/users/me/delegation-strategy",
                json={"strategy": "random_thing"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 400, resp.text
            assert "random_thing" in resp.text or "Allowed" in resp.text
            api_db.refresh(user)
            # Strategy unchanged.
            assert user.delegation_strategy == "strict_precedence"
        finally:
            app.dependency_overrides.pop(get_db, None)


# ===========================================================================
# Service-layer test
# ===========================================================================

class TestServiceBuildContextPopulatesRelevances:
    """_build_context reads ProposalTopic.relevance into ctx, and bulk-
    reads delegation_strategy for the eligible voter set."""

    def test_context_carries_relevances_and_strategies(self, api_db):
        # Minimal fixture: org + topic + 2 users with different strategies + proposal.
        org = models.Organization(
            name="Org",
            slug="o-svc",
            description="",
            join_policy="open",
        )
        api_db.add(org)
        api_db.flush()

        topic_a = models.Topic(
            org_id=org.id, name="A", description="", color="#000",
        )
        topic_b = models.Topic(
            org_id=org.id, name="B", description="", color="#000",
        )
        api_db.add_all([topic_a, topic_b])
        api_db.flush()

        author = _user_row(api_db, "author", strategy="relevance_weighted")
        voter = _user_row(api_db, "voter", strategy="strict_precedence")
        make_org_membership(
            api_db, org_id=org.id, user_id=author.id, role="steward", status="active",
        )
        make_org_membership(
            api_db, org_id=org.id, user_id=voter.id, role="member", status="active",
        )
        proposal = models.Proposal(
            title="P", body="", author_id=author.id, org_id=org.id,
            voting_method="binary", status="voting",
            pass_threshold=0.5, quorum_threshold=0.0,
        )
        api_db.add(proposal)
        api_db.flush()
        api_db.add_all([
            models.ProposalTopic(
                proposal_id=proposal.id, topic_id=topic_a.id, relevance=0.7,
            ),
            models.ProposalTopic(
                proposal_id=proposal.id, topic_id=topic_b.id, relevance=0.3,
            ),
        ])
        api_db.commit()
        api_db.refresh(proposal)

        eligible_ids = {author.id, voter.id}
        ctx = DelegationService._build_context(
            proposal, api_db, eligible_ids=eligible_ids,
        )

        # Phase 27 fields populated.
        assert ctx.proposal_topic_relevances == {topic_a.id: 0.7, topic_b.id: 0.3}
        assert ctx.user_strategies.get(author.id) == "relevance_weighted"
        assert ctx.user_strategies.get(voter.id) == "strict_precedence"


# ===========================================================================
# B5.12 (optional) — migration smoke
# ===========================================================================

class TestModelDefaultRelevanceWeighted:
    """Newly-created User rows default to relevance_weighted (post-Phase-27
    model default flip). Migration-cycle covered by separate smoke at
    deploy time; this is a lightweight model-defaults check."""

    def test_default_strategy(self, api_db):
        u = models.User(
            username="newbie",
            display_name="Newbie",
            password_hash=_DUMMY_HASH,
            email="newbie@test.example",
            email_verified=True,
        )
        api_db.add(u)
        api_db.flush()
        api_db.refresh(u)
        assert u.delegation_strategy == "relevance_weighted"
