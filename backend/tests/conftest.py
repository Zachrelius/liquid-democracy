"""
Shared pytest fixtures for the backend test suite.

Uses an in-memory SQLite database so tests are fast and isolated.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from database import Base
import models  # noqa: F401 — registers ORM classes with Base
from delegation_engine import (
    DelegationGraphStore,
    DelegationEngine,
    DelegationData,
    ProposalContext,
)

# A valid bcrypt hash for "test" — avoids bcrypt backend issues in tests
_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"

TEST_DB_URL = "sqlite:///:memory:"


@pytest.fixture(scope="function")
def db() -> Session:
    engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def store() -> DelegationGraphStore:
    return DelegationGraphStore()


@pytest.fixture(scope="function")
def engine_obj(store: DelegationGraphStore) -> DelegationEngine:
    return DelegationEngine(store)


# ---------------------------------------------------------------------------
# DB helper factories
# ---------------------------------------------------------------------------

def make_user(db: Session, username: str, display_name: str | None = None) -> models.User:
    u = models.User(
        username=username,
        display_name=display_name or username,
        password_hash=_DUMMY_HASH,
        email=f"{username}@test.example",
        email_verified=True,
    )
    db.add(u)
    db.flush()
    return u


def make_topic(db: Session, name: str) -> models.Topic:
    t = models.Topic(name=name, description="", color="#000000")
    db.add(t)
    db.flush()
    return t


def make_proposal(
    db: Session, author: models.User, topic_ids: list[str] | None = None
) -> models.Proposal:
    p = models.Proposal(
        title="Test Proposal",
        body="",
        author_id=author.id,
        status="voting",
    )
    db.add(p)
    db.flush()
    for tid in (topic_ids or []):
        db.add(models.ProposalTopic(proposal_id=p.id, topic_id=tid))
    db.flush()
    return p


def cast_direct_vote(
    db: Session, user: models.User, proposal: models.Proposal, value: str
) -> models.Vote:
    v = models.Vote(
        proposal_id=proposal.id,
        user_id=user.id,
        vote_value=value,
        is_direct=True,
        cast_by_id=user.id,
    )
    db.add(v)
    db.flush()
    return v


def set_delegation(
    db: Session,
    store: DelegationGraphStore,
    delegator: models.User,
    delegate: models.User,
    topic: models.Topic | None = None,
    chain_behavior: str = "accept_sub",
) -> models.Delegation:
    d = models.Delegation(
        delegator_id=delegator.id,
        delegate_id=delegate.id,
        topic_id=topic.id if topic else None,
        chain_behavior=chain_behavior,
    )
    db.add(d)
    db.flush()
    store.add_delegation(delegator.id, delegate.id, topic.id if topic else None)
    return d


def set_precedence(
    db: Session,
    user: models.User,
    ordered_topics: list[models.Topic],
) -> None:
    for priority, topic in enumerate(ordered_topics):
        db.add(
            models.TopicPrecedence(
                user_id=user.id,
                topic_id=topic.id,
                priority=priority,
            )
        )
    db.flush()


# ---------------------------------------------------------------------------
# Pure-layer helpers (no DB needed)
# ---------------------------------------------------------------------------

def make_context(
    proposal_topics: list[str],
    delegations: dict,       # {(delegator_id, topic_id): (delegate_id, chain_behavior)}
    precedences: dict,       # {(user_id, topic_id): priority}
    direct_votes: dict,      # {user_id: vote_value}
) -> ProposalContext:
    """Build a ProposalContext directly for pure-function unit tests."""
    all_delegations: dict = {}
    for (delegator_id, topic_id), (delegate_id, chain_behavior) in delegations.items():
        dd = DelegationData(
            delegator_id=delegator_id,
            delegate_id=delegate_id,
            topic_id=topic_id,
            chain_behavior=chain_behavior,
        )
        all_delegations.setdefault(delegator_id, {})[topic_id] = dd

    all_precedences: dict = {}
    for (user_id, topic_id), priority in precedences.items():
        all_precedences.setdefault(user_id, {})[topic_id] = priority

    return ProposalContext(
        proposal_topics=proposal_topics,
        all_delegations=all_delegations,
        all_precedences=all_precedences,
        direct_votes=direct_votes,
    )
