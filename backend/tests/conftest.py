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

import os

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from database import Base
import models  # noqa: F401 — registers ORM classes with Base
from role_seed import seed_default_roles_for_org
from delegation_engine import (
    DelegationGraphStore,
    DelegationEngine,
    DelegationData,
    ProposalContext,
)


# ---------------------------------------------------------------------------
# Phase 38 B3 — slowapi limiter reset between tests
# ---------------------------------------------------------------------------
#
# Phase 38 B3 added ``@limiter.limit("10/minute")`` to /api/auth/login and
# /api/auth/demo-login. The slowapi limiter holds in-memory state across
# tests within the same process — without an explicit reset, tests that
# hit /api/auth/login in their setup (e.g. ``_auth_headers`` helpers
# scattered across the suite) exhaust the 10/minute quota and get 429
# from the 11th call onwards, cascading failures into unrelated tests.
#
# The reset clears both the route-local ``routes/auth.py::limiter`` and
# the app-level ``main.py::limiter`` (slowapi attaches state to both).
# Autouse + function-scope ensures every test starts with a clean
# rate-limiter counter.

@pytest.fixture(autouse=True)
def _reset_slowapi_limiter():
    from routes import auth as _auth_routes
    from main import limiter as _main_limiter
    try:
        _auth_routes.limiter.reset()
        _main_limiter.reset()
    except Exception:
        pass  # defensive — never let limiter wiring break test collection
    yield
    try:
        _auth_routes.limiter.reset()
        _main_limiter.reset()
    except Exception:
        pass

# A valid bcrypt hash for "test" — avoids bcrypt backend issues in tests
_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL") or "sqlite:///:memory:"


# ---------------------------------------------------------------------------
# Phase 61 O1 — session-scoped engine + per-test SAVEPOINT rollback.
#
# Pre-Phase-61, the `db` fixture was scope="function" and ran the full
# `Base.metadata.create_all` + `Base.metadata.drop_all` per test, on a
# fresh in-memory SQLite engine. At ~2266 tests that's 2266 full
# schema creates + drops — the dominant test-time cost.
#
# The new pattern: build the schema ONCE per session against a single
# StaticPool engine. Each test runs in an outer transaction with a
# nested SAVEPOINT; the SAVEPOINT is re-established on every commit
# (so test code can call `session.commit()` freely without breaking
# the outer rollback boundary). On teardown, the outer transaction
# rolls back, restoring the database to its post-create_all empty
# state.
#
# Isolation: each test gets its own Session bound to a fresh
# Connection; cross-test state leakage is impossible because the
# outer rollback discards everything the test wrote.
#
# Failure modes guarded:
#   - Sessions that `session.commit()` (the majority): handled by the
#     savepoint-restart event listener below.
#   - Sessions that `session.rollback()` mid-test: also handled —
#     the restart listener fires on any nested transaction end.
#   - Cross-process tests that spawn subprocesses + write to a
#     different DB URL: unaffected (they use their own engine via env
#     `DATABASE_URL`).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _shared_test_engine():
    """Phase 61 O1 — one engine + one create_all for the whole session.

    Uses StaticPool so the in-memory SQLite database persists across
    connections (without StaticPool, each connection sees its own
    fresh DB and tests would see empty schema). Disposed at session
    end.
    """
    if TEST_DB_URL.startswith("sqlite"):
        engine = create_engine(
            TEST_DB_URL,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        engine = create_engine(TEST_DB_URL)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db(_shared_test_engine) -> Session:
    """Phase 61 O1 — per-test transaction-rollback isolation.

    Each test:
      1. opens a Connection from the shared engine
      2. begins an outer transaction
      3. creates a Session bound to that Connection
      4. begins a nested SAVEPOINT (auto-restarted after each commit)
      5. yields the Session
      6. on teardown: closes the Session, rolls back the outer
         transaction, returns the Connection to the pool
    """
    connection = _shared_test_engine.connect()
    transaction = connection.begin()
    TestSession = sessionmaker(bind=connection)
    session = TestSession()

    # Begin a SAVEPOINT inside the outer transaction; re-establish it
    # after every commit so test-side commits don't release the outer
    # rollback boundary. This is the standard "tests in transactions"
    # recipe from the SQLAlchemy docs.
    nested = connection.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(_session, trans):
        nonlocal nested
        # Re-open the savepoint whenever the inner one ends (commit
        # or rollback). The outer transaction stays open until the
        # teardown below.
        if trans.nested and not trans._parent.nested:
            nested = connection.begin_nested()

    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


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
    t = models.Topic(name=name, color="#000000")
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


_DEFAULT_TEST_ORG_SLUG = "_default_test_org"


def _default_test_org_id(db: Session) -> str:
    """Phase 39 B3 — return (lazy-create) a default test Organization id.

    Phase 39 B3 synced ``Delegation.org_id`` / ``FollowRelationship.org_id``
    / ``FollowRequest.org_id`` / ``DelegationIntent.org_id`` to NOT NULL
    in the ORM declaration (the DB has been NOT NULL since the Phase 18b
    migration; only the model was lagging). Existing test fixtures
    created relationship rows without setting ``org_id`` because the
    pre-Phase-39 declaration said it was nullable. To avoid touching
    ~50 test files, helpers fall back to this default test org for
    rows that don't have a meaningful org context. Real org-scoped
    tests (Phase 18+ retrofit suites) pass an explicit ``org_id`` and
    aren't affected.
    """
    existing = db.query(models.Organization).filter(
        models.Organization.slug == _DEFAULT_TEST_ORG_SLUG,
    ).first()
    if existing is not None:
        return existing.id
    org = models.Organization(
        slug=_DEFAULT_TEST_ORG_SLUG,
        name="Default Test Org",
        description="",
        join_policy="open",
        settings={},
    )
    db.add(org)
    db.flush()
    return org.id


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
    org context. ``org_id`` is inferred in this order: explicit kwarg →
    topic's ``org_id`` (if topic is provided) → lazy-created default test
    org (Phase 39 B3 fallback so pre-Phase-39 tests that didn't set
    org_id keep working under the now-NOT-NULL constraint).
    """
    inferred = org_id
    if inferred is None and topic is not None:
        inferred = getattr(topic, "org_id", None)
    if inferred is None:
        inferred = _default_test_org_id(db)
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
