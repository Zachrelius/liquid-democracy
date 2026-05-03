"""Phase 12 Stage 1 — has_permission helper tests (Cluster H, H1+H2).

Coverage:

  * Standard path positive: user with the granting role on the org → True.
  * Standard path negative: user with a non-granting role → False.
  * Non-member: user without any membership → False.
  * Suspended membership: active=False → False.
  * Decision-6 implicit power: parent-org admin/steward gets every
    permission on every sub-org of that parent.
  * Decision-6 cross-parent: parent-org admin gets NOTHING on a sub-org
    whose parent is a DIFFERENT org (the cross-parent guard).
  * D4 owner-only gates: only steward can call ``org.delete`` /
    ``org.transfer_stewardship``; admin gets False even with default
    grants in place. role_permissions rows for these keys are ignored.
  * Per-request cache: repeated has_permission calls for the same
    ``(user, org)`` pair issue exactly one underlying DB load.

Uses the seed helper from ``backend/role_seed.py`` (Cluster D) to set up
the four preset roles and their default RolePermission grants.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from database import Base
from role_permissions import (
    OWNER_ONLY_KEYS,
    get_or_init_permission_cache,
    has_permission,
)
from role_seed import seed_default_roles_for_org


_DUMMY_HASH = auth_utils.hash_password("demo1234")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def db() -> Session:
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


def _make_user(db: Session, username: str) -> models.User:
    u = models.User(
        username=username,
        display_name=username.title(),
        password_hash=_DUMMY_HASH,
        email=f"{username}@test.example",
        email_verified=True,
    )
    db.add(u)
    db.flush()
    return u


def _make_org(
    db: Session, name: str, slug: str, parent_org_id: str | None = None
) -> models.Organization:
    org = models.Organization(
        name=name,
        slug=slug,
        description="",
        parent_org_id=parent_org_id,
    )
    db.add(org)
    db.flush()
    seed_default_roles_for_org(db, org.id)
    return org


def _add_membership(
    db: Session,
    user: models.User,
    org: models.Organization,
    system_key: str,
    status: str = "active",
) -> models.OrgMembership:
    role = (
        db.query(models.Role)
        .filter(
            models.Role.org_id == org.id,
            models.Role.system_key == system_key,
        )
        .first()
    )
    assert role is not None, f"role {system_key!r} not found for org {org.slug}"
    m = models.OrgMembership(
        user_id=user.id,
        org_id=org.id,
        role_id=role.id,
        status=status,
    )
    db.add(m)
    db.flush()
    return m


# ---------------------------------------------------------------------------
# Standard-path tests
# ---------------------------------------------------------------------------

def test_admin_has_proposal_create_default(db):
    """Standard positive: an admin gets proposal.create by default."""
    user = _make_user(db, "alice")
    org = _make_org(db, "Org", "org")
    _add_membership(db, user, org, "admin")
    db.flush()

    assert has_permission(db, user.id, org.id, "proposal.create") is True


def test_member_does_not_have_proposal_create(db):
    """Standard negative: members get no admin-tier permissions by default."""
    user = _make_user(db, "bob")
    org = _make_org(db, "Org", "org")
    _add_membership(db, user, org, "member")
    db.flush()

    assert has_permission(db, user.id, org.id, "proposal.create") is False


def test_moderator_has_eight_default_grants(db):
    """Spot-check moderator's 8-key default set: gets proposal.create but
    NOT proposal.delete; gets topic.edit but NOT topic.delete."""
    user = _make_user(db, "carol")
    org = _make_org(db, "Org", "org")
    _add_membership(db, user, org, "moderator")
    db.flush()

    # Granted to moderator by default.
    assert has_permission(db, user.id, org.id, "proposal.create") is True
    assert has_permission(db, user.id, org.id, "proposal.advance_phase") is True
    assert has_permission(db, user.id, org.id, "topic.create") is True
    assert has_permission(db, user.id, org.id, "topic.edit") is True
    assert has_permission(db, user.id, org.id, "member.approve_join") is True
    assert has_permission(db, user.id, org.id, "member.invite") is True
    assert has_permission(db, user.id, org.id, "polis.create") is True
    assert has_permission(db, user.id, org.id, "comment.moderate") is True

    # NOT granted to moderator by default (admin+).
    assert has_permission(db, user.id, org.id, "proposal.delete") is False
    assert has_permission(db, user.id, org.id, "topic.delete") is False
    assert has_permission(db, user.id, org.id, "member.remove") is False
    assert has_permission(db, user.id, org.id, "member.suspend") is False
    assert has_permission(db, user.id, org.id, "polis.manage") is False
    assert has_permission(db, user.id, org.id, "audit.view_org") is False


def test_non_member_returns_false(db):
    """User with no OrgMembership row → False on every key."""
    user = _make_user(db, "outsider")
    org = _make_org(db, "Org", "org")
    db.flush()

    assert has_permission(db, user.id, org.id, "proposal.create") is False
    assert has_permission(db, user.id, org.id, "audit.view_org") is False


def test_suspended_membership_returns_false(db):
    """Active gate: suspended (or pending_approval) membership shouldn't
    grant any permissions even if the role would otherwise allow them."""
    user = _make_user(db, "suspended")
    org = _make_org(db, "Org", "org")
    _add_membership(db, user, org, "admin", status="suspended")
    db.flush()

    assert has_permission(db, user.id, org.id, "proposal.create") is False
    assert has_permission(db, user.id, org.id, "member.remove") is False


def test_unknown_org_returns_false(db):
    """Defensive: unknown org_id → False rather than raising."""
    user = _make_user(db, "alice")
    db.flush()

    assert has_permission(db, user.id, "nonexistent-org-id", "proposal.create") is False


def test_unknown_permission_key_returns_false(db):
    """A permission_key not in the registry (typo) → False without raising."""
    user = _make_user(db, "alice")
    org = _make_org(db, "Org", "org")
    _add_membership(db, user, org, "admin")
    db.flush()

    assert has_permission(db, user.id, org.id, "made.up.key") is False


# ---------------------------------------------------------------------------
# Decision-6 implicit power
# ---------------------------------------------------------------------------

def test_parent_admin_has_all_permissions_on_sub_org(db):
    """D3 + Decision 6: admin/steward of a parent org gets every
    permission on every sub-org of that parent — including ones the
    sub-org's own role table doesn't grant."""
    parent = _make_org(db, "Parent Co", "parent")
    sub = _make_org(db, "Sub Team", "sub", parent_org_id=parent.id)

    user = _make_user(db, "parent_admin")
    _add_membership(db, user, parent, "admin")
    db.flush()

    # User has NO membership on the sub-org, but inherits via parent admin.
    assert has_permission(db, user.id, sub.id, "proposal.create") is True
    assert has_permission(db, user.id, sub.id, "proposal.delete") is True
    assert has_permission(db, user.id, sub.id, "audit.view_org") is True


def test_parent_steward_has_all_permissions_on_sub_org(db):
    """D3: steward variant of the implicit-power test."""
    parent = _make_org(db, "Parent Co", "parent")
    sub = _make_org(db, "Sub Team", "sub", parent_org_id=parent.id)

    user = _make_user(db, "parent_steward")
    _add_membership(db, user, parent, "steward")
    db.flush()

    assert has_permission(db, user.id, sub.id, "proposal.create") is True
    assert has_permission(db, user.id, sub.id, "polis.manage") is True


def test_parent_moderator_does_not_inherit_sub_org_permissions(db):
    """D3 boundary: only admin/steward on the parent inherit. A parent
    moderator gets NO implicit power on sub-orgs."""
    parent = _make_org(db, "Parent Co", "parent")
    sub = _make_org(db, "Sub Team", "sub", parent_org_id=parent.id)

    user = _make_user(db, "parent_moderator")
    _add_membership(db, user, parent, "moderator")
    db.flush()

    # Moderator on parent ≠ implicit admin on sub-org.
    assert has_permission(db, user.id, sub.id, "proposal.create") is False
    assert has_permission(db, user.id, sub.id, "polis.manage") is False


def test_parent_admin_cross_parent_isolation(db):
    """D3 critical guard: an admin of Parent A gets no implicit power on
    a sub-org of Parent B. The cross-parent boundary is the load-bearing
    isolation property."""
    parent_a = _make_org(db, "Parent A", "parent-a")
    parent_b = _make_org(db, "Parent B", "parent-b")
    sub_of_b = _make_org(db, "Sub of B", "sub-b", parent_org_id=parent_b.id)

    user = _make_user(db, "alice_admin_of_a")
    _add_membership(db, user, parent_a, "admin")
    db.flush()

    # No membership on parent_b → no implicit power on sub_of_b.
    assert has_permission(db, user.id, sub_of_b.id, "proposal.create") is False
    assert has_permission(db, user.id, sub_of_b.id, "audit.view_org") is False


def test_implicit_power_caches_parent_permission_set(db):
    """The implicit-power path also caches the parent's permission set as
    a side effect, so a follow-up has_permission(user, parent, key) call
    in the same request is a dict lookup."""
    parent = _make_org(db, "Parent", "parent")
    sub = _make_org(db, "Sub", "sub", parent_org_id=parent.id)

    user = _make_user(db, "alice")
    _add_membership(db, user, parent, "admin")
    db.flush()

    cache = get_or_init_permission_cache(db)
    assert (user.id, parent.id) not in cache

    # Implicit-power call on sub-org should fill the parent cache slot.
    has_permission(db, user.id, sub.id, "proposal.create")

    assert (user.id, parent.id) in cache
    assert cache[(user.id, parent.id)]["proposal.create"] is True


# ---------------------------------------------------------------------------
# D4 owner-only hardcoded gates
# ---------------------------------------------------------------------------

def test_owner_only_keys_constant_includes_org_delete_and_transfer(db):
    """OWNER_ONLY_KEYS is the single source of truth for D4 — the helper
    consults it before falling through to role_permissions."""
    assert "org.delete" in OWNER_ONLY_KEYS
    assert "org.transfer_stewardship" in OWNER_ONLY_KEYS


def test_steward_can_delete_org(db):
    """D4 positive: only the user with role.system_key='steward' on the
    org can call org.delete."""
    user = _make_user(db, "alice")
    org = _make_org(db, "Org", "org")
    _add_membership(db, user, org, "steward")
    db.flush()

    assert has_permission(db, user.id, org.id, "org.delete") is True
    assert has_permission(db, user.id, org.id, "org.transfer_stewardship") is True


def test_admin_cannot_delete_org_even_with_default_grants(db):
    """D4 negative: an admin holds 23 default permission rows but
    org.delete bypasses the role_permissions table entirely. Admin → False."""
    user = _make_user(db, "alice")
    org = _make_org(db, "Org", "org")
    _add_membership(db, user, org, "admin")
    db.flush()

    assert has_permission(db, user.id, org.id, "org.delete") is False
    assert has_permission(db, user.id, org.id, "org.transfer_stewardship") is False


def test_owner_only_explicit_grant_is_ignored(db):
    """D4 enforcement: even an explicit role_permissions row enabling
    org.delete on a non-Steward role is ignored. The hardcoded gate
    never consults role_permissions for these keys."""
    user = _make_user(db, "rogue_admin")
    org = _make_org(db, "Org", "org")
    _add_membership(db, user, org, "admin")

    # Look up the admin role and inject an explicit org.delete grant.
    admin_role = (
        db.query(models.Role)
        .filter(models.Role.org_id == org.id, models.Role.system_key == "admin")
        .first()
    )
    db.add(models.RolePermission(
        role_id=admin_role.id,
        permission_key="org.delete",
        enabled=True,
    ))
    db.flush()

    # Still False — the explicit grant doesn't matter for D4 keys.
    assert has_permission(db, user.id, org.id, "org.delete") is False


def test_parent_admin_can_delete_sub_org_via_implicit_power(db):
    """Subtle D3 + D4 interaction: org.delete on a sub-org is gated by
    Decision-6 implicit power BEFORE the D4 check fires (because step 1
    runs before step 2). A parent-org admin can delete a sub-org because
    they get every permission on it via implicit power.

    This matches the spec intent: D4 is about preventing a NON-Steward
    from deleting the ORG THEY'RE ON. Sub-org deletion already has its
    own permission key (sub_org.delete), and the implicit-power path is
    how parent admins manage their sub-orgs."""
    parent = _make_org(db, "Parent", "parent")
    sub = _make_org(db, "Sub", "sub", parent_org_id=parent.id)
    user = _make_user(db, "alice")
    _add_membership(db, user, parent, "admin")
    db.flush()

    # Parent admin gets implicit power on the sub-org → org.delete True.
    # (In practice, deleting a sub-org goes through sub_org.delete; the
    # owner-only org.delete key is for top-level org self-delete. But the
    # helper's resolution order makes this combination work cleanly.)
    assert has_permission(db, user.id, sub.id, "org.delete") is True


def test_non_member_cannot_use_owner_only_key(db):
    """D4 + non-member: a user not in the org can't use D4 keys either."""
    user = _make_user(db, "outsider")
    org = _make_org(db, "Org", "org")
    db.flush()

    assert has_permission(db, user.id, org.id, "org.delete") is False


# ---------------------------------------------------------------------------
# Per-request cache (D6 / H2)
# ---------------------------------------------------------------------------

def test_cache_initialized_lazily(db):
    """get_or_init_permission_cache creates the dict on first call and
    returns the same object on subsequent calls."""
    assert "_permission_cache" not in db.info
    cache_a = get_or_init_permission_cache(db)
    assert "_permission_cache" in db.info
    cache_b = get_or_init_permission_cache(db)
    assert cache_a is cache_b


def test_cache_populated_after_first_lookup(db):
    """Acceptable-alternative form of the cache test (per dispatch H2):
    after the first has_permission call for (user, org), the cache dict
    contains a (user, org) entry holding the user's full permission set."""
    user = _make_user(db, "alice")
    org = _make_org(db, "Org", "org")
    _add_membership(db, user, org, "admin")
    db.flush()

    cache = get_or_init_permission_cache(db)
    assert (user.id, org.id) not in cache

    has_permission(db, user.id, org.id, "proposal.create")

    assert (user.id, org.id) in cache
    permission_set = cache[(user.id, org.id)]
    # Admin gets all 23 default grants — every entry should be in the cache.
    assert "proposal.create" in permission_set
    assert "audit.view_org" in permission_set
    assert permission_set["proposal.create"] is True


def test_repeated_calls_issue_single_role_permission_query(db):
    """D6 instrumented form: an event listener counts SELECTs against the
    role_permissions table; three has_permission calls for the same
    (user, org) pair issue exactly ONE such query (the first; subsequent
    calls are dict lookups on the cache)."""
    user = _make_user(db, "alice")
    org = _make_org(db, "Org", "org")
    _add_membership(db, user, org, "admin")
    db.flush()

    # Reset cache so we measure cold → warm transition.
    db.info.pop("_permission_cache", None)

    role_permission_query_count = {"n": 0}

    @event.listens_for(db.bind, "before_cursor_execute")
    def _count(conn, cursor, statement, parameters, context, executemany):
        # Match the SELECT against role_permissions (case-insensitive,
        # tolerant of quoting).
        if "FROM role_permissions" in statement or "from role_permissions" in statement:
            role_permission_query_count["n"] += 1

    try:
        # Three calls — different keys, same (user, org).
        has_permission(db, user.id, org.id, "proposal.create")
        has_permission(db, user.id, org.id, "topic.create")
        has_permission(db, user.id, org.id, "member.invite")
    finally:
        event.remove(db.bind, "before_cursor_execute", _count)

    # Exactly one role_permissions SELECT — the first call's load.
    assert role_permission_query_count["n"] == 1, (
        f"expected 1 role_permissions query, got {role_permission_query_count['n']}"
    )


def test_cache_isolated_per_user(db):
    """Cache key is (user_id, org_id). Two different users in the same
    org get independent cache entries; one's lookup doesn't pollute the
    other's."""
    alice = _make_user(db, "alice")
    bob = _make_user(db, "bob")
    org = _make_org(db, "Org", "org")
    _add_membership(db, alice, org, "admin")
    _add_membership(db, bob, org, "member")
    db.flush()

    has_permission(db, alice.id, org.id, "proposal.create")
    has_permission(db, bob.id, org.id, "proposal.create")

    cache = get_or_init_permission_cache(db)
    assert (alice.id, org.id) in cache
    assert (bob.id, org.id) in cache
    # Alice's cache shows admin perms; Bob's is empty (member has none).
    assert cache[(alice.id, org.id)].get("proposal.create") is True
    assert cache[(bob.id, org.id)] == {}
