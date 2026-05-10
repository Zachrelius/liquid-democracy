"""
Shared pytest fixtures for the backend test suite.

Uses an in-memory SQLite database so tests are fast and isolated.

Phase 12 Stage 1 — ``make_org_membership`` helper added to bridge the
``OrgMembership.role`` (string) → ``OrgMembership.role_id`` (FK) migration.
Test fixtures and direct callers should construct memberships via this
helper rather than ``models.OrgMembership(role="...")`` so the underlying
Role row is auto-seeded for the org and the FK is correctly populated.
The helper is a thin wrapper around ``role_seed.seed_default_roles_for_org``;
production code calls that seed helper directly during org creation /
migration, so the conftest indirection is a test-only convenience.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from database import Base
import models  # noqa: F401 — registers ORM classes with Base
from role_seed import seed_default_roles_for_org
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


# ---------------------------------------------------------------------------
# Phase 12 — role / membership helpers
# ---------------------------------------------------------------------------

# Legacy role-string → preset Role.system_key. The migration renamed
# 'owner' → 'steward'; tests that still pass the legacy string get the
# rename applied transparently so the broad fixture sweep is purely
# mechanical (s/role="owner"/role_id=<steward>/).
_LEGACY_ROLE_TO_SYSTEM_KEY: dict[str, str] = {
    "owner": "steward",
    "steward": "steward",
    "admin": "admin",
    "moderator": "moderator",
    "member": "member",
}


def ensure_org_roles(db: Session, org_id: str) -> dict[str, models.Role]:
    """Idempotent: ensure the four preset Role rows exist for ``org_id``.

    Returns a ``{system_key: Role}`` dict identical to the production seed
    helper. Safe to call repeatedly within a single test.
    """
    return seed_default_roles_for_org(db, org_id)


def resolve_role_id(db: Session, org_id: str, role_str: str) -> str:
    """Return the Role.id matching ``(org_id, system_key)`` for the given
    legacy role string. Auto-seeds presets on first use.

    ``role_str`` accepts both the new system_keys ('steward', 'admin',
    'moderator', 'member') and the legacy 'owner' (silently mapped to
    'steward' to keep the test-fixture diff small).
    """
    system_key = _LEGACY_ROLE_TO_SYSTEM_KEY.get(role_str, role_str)
    roles = ensure_org_roles(db, org_id)
    if system_key not in roles:
        raise ValueError(
            f"resolve_role_id: unknown role string {role_str!r}; expected one "
            f"of {sorted(_LEGACY_ROLE_TO_SYSTEM_KEY)}"
        )
    return roles[system_key].id


def make_org_membership(
    db: Session,
    *,
    org_id: str,
    user_id: str,
    role: str = "member",
    status: str = "active",
) -> models.OrgMembership:
    """Test-only constructor for ``OrgMembership`` post-Phase-12 migration.

    Replaces ``models.OrgMembership(role="admin", ...)`` patterns scattered
    throughout the suite. Auto-seeds the org's preset Role rows on first
    use (idempotent), resolves the legacy role string to a ``role_id``,
    and inserts the row. Returns the flushed ORM object.
    """
    role_id = resolve_role_id(db, org_id, role)
    m = models.OrgMembership(
        user_id=user_id,
        org_id=org_id,
        role_id=role_id,
        status=status,
    )
    db.add(m)
    db.flush()
    return m


def make_sub_org_membership(
    db: Session,
    *,
    sub_org_id: str,
    user_id: str,
    role: str = "member",
    status: str = "active",
) -> models.SubOrgMembership:
    """Phase 15 Cluster S — test-only constructor for ``SubOrgMembership``
    post-migration.

    Like ``make_org_membership``, replaces ``models.SubOrgMembership(
    role="admin", ...)`` patterns. Sub-orgs inherit the parent's matrix
    wholesale, so this helper looks up the role row on the PARENT org,
    not on the sub-org itself. Auto-seeds the parent's preset Role rows
    on first use (idempotent).

    The ``role`` arg accepts both the new system_keys ('steward', 'admin',
    'moderator', 'member') and the legacy 'owner' (silently mapped to
    'steward' to match Phase 12 helpers).
    """
    sub_org = db.get(models.Organization, sub_org_id)
    if sub_org is None:
        raise ValueError(f"sub_org_id={sub_org_id!r} not found")
    if sub_org.parent_org_id is None:
        raise ValueError(
            f"sub_org_id={sub_org_id!r} has no parent_org_id; "
            "make_sub_org_membership is only valid for actual sub-orgs."
        )
    role_id = resolve_role_id(db, sub_org.parent_org_id, role)
    sm = models.SubOrgMembership(
        user_id=user_id,
        sub_org_id=sub_org_id,
        role_id=role_id,
        status=status,
    )
    db.add(sm)
    db.flush()
    return sm


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
    *,
    org_id: str | None = None,
) -> models.Delegation:
    """Phase 18: optional ``org_id`` parameter so newer tests can thread
    org context. When ``org_id`` is None (legacy callers in the 18a
    transitional window) the row lands with ``org_id IS NULL`` — that's
    OK until B1b flips the NOT NULL constraint. ``org_id`` is also
    inferred from the topic when topic is provided and ``org_id`` is
    not explicitly set.
    """
    inferred = org_id
    if inferred is None and topic is not None:
        inferred = getattr(topic, "org_id", None)
    d = models.Delegation(
        delegator_id=delegator.id,
        delegate_id=delegate.id,
        org_id=inferred,
        topic_id=topic.id if topic else None,
        chain_behavior=chain_behavior,
    )
    db.add(d)
    db.flush()
    store.add_delegation(
        delegator.id, delegate.id, topic.id if topic else None,
        org_id=inferred,
    )
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
