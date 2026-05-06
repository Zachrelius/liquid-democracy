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
    STEWARD_LOCKED_PERMISSIONS,
    get_or_init_permission_cache,
    has_permission,
    is_locked,
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


def test_parent_moderator_inherits_sub_org_permissions_by_default(db):
    """Phase 15 Cluster S — parent Moderator transferability defaults ON
    (per spec table). A parent Moderator with no sub-org membership now
    inherits the Moderator permission set on the sub-org via the
    parent's matrix at the resolved (Moderator) role.

    This REPLACES Phase 12 Stage 1's behavior where only admin/steward
    on the parent transferred. The Phase 12 Stage 1 "implicit power"
    path was reframed in Phase 15 as "transferability + matrix lookup":
    parent Moderator now resolves to the parent's Moderator role on
    the sub-org, which has proposal.create granted by default but does
    not have org.edit_settings.
    """
    parent = _make_org(db, "Parent Co", "parent")
    sub = _make_org(db, "Sub Team", "sub", parent_org_id=parent.id)

    user = _make_user(db, "parent_moderator")
    _add_membership(db, user, parent, "moderator")
    db.flush()

    # Moderator transferability defaults ON; the parent's Moderator
    # matrix grants proposal.create (in DEFAULT_GRANTS).
    assert has_permission(db, user.id, sub.id, "proposal.create") is True
    # Moderator does NOT have polis.manage (admin-tier only by default).
    assert has_permission(db, user.id, sub.id, "polis.manage") is False


def test_parent_member_does_not_inherit_sub_org_permissions_by_default(db):
    """Phase 15 Cluster S — parent Member transferability defaults OFF
    (per spec table). A parent Member with no sub-org membership has
    no permissions on the sub-org by default.

    This is the load-bearing privacy property: a parent Member cannot
    discover what's happening in a sub-org they don't belong to via
    permission-based features unless the org has explicitly enabled
    Member transferability.
    """
    parent = _make_org(db, "Parent Co", "parent")
    sub = _make_org(db, "Sub Team", "sub", parent_org_id=parent.id)

    user = _make_user(db, "parent_member")
    _add_membership(db, user, parent, "member")
    db.flush()

    # Member transferability defaults OFF.
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


def test_sub_org_permission_lookup_caches_resolved_role_set(db):
    """Phase 15 Cluster S — the sub-org permission path caches the
    resolved-role permission set under a sub-org-specific cache key
    (``(user, "sub:<sub_id>:role:<role_id>")``) so subsequent calls for
    other permission keys in the same request hit the cache. Replaces
    the Phase 12 Stage 1 implicit-power side-effect cache, which keyed
    on the parent ``(user, parent_id)`` because the old shortcut always
    returned True regardless of permission_key.
    """
    parent = _make_org(db, "Parent", "parent")
    sub = _make_org(db, "Sub", "sub", parent_org_id=parent.id)

    user = _make_user(db, "alice")
    _add_membership(db, user, parent, "admin")
    db.flush()

    cache = get_or_init_permission_cache(db)
    # No sub-org cache entries at start.
    assert not any(
        isinstance(k, tuple) and len(k) == 2
        and isinstance(k[1], str) and k[1].startswith("sub:")
        for k in cache.keys()
    )

    # Sub-org permission call should fill a sub-org-specific cache slot.
    has_permission(db, user.id, sub.id, "proposal.create")

    sub_keys = [
        k for k in cache.keys()
        if isinstance(k, tuple) and len(k) == 2
        and isinstance(k[1], str) and k[1].startswith(f"sub:{sub.id}:")
    ]
    assert len(sub_keys) == 1, (
        f"expected exactly one sub-org cache entry, got {sub_keys}"
    )
    cached_set = cache[sub_keys[0]]
    assert cached_set.get("proposal.create") is True


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


def test_parent_admin_cannot_delete_sub_org_via_inherited_admin(db):
    """Phase 15 Cluster S — the Phase 12 Stage 1 "implicit power"
    shortcut is replaced by transferability-aware effective-role
    resolution. A parent Admin (default-on transferability) resolves
    to the sub-org's Admin role; ``org.delete`` is hardcoded
    Steward-only, so Admin still cannot delete via inheritance.

    This MATCHES the explicit spec §S6 test case: "Platform admin
    attempts org.delete on a sub-org: fails (Admin doesn't have
    org.delete; that's hardcoded Steward-only)." The same logic
    applies to a parent Admin who inherits the Admin role on the
    sub-org via transferability.

    The CHANGE from Phase 12 Stage 1: the old shortcut returned True
    for any permission_key (including org.delete) when parent admin
    inherited; that was actually a latent bug — the matrix's
    Steward-only protection was being bypassed via inheritance. Phase
    15 closes that hole.
    """
    parent = _make_org(db, "Parent", "parent")
    sub = _make_org(db, "Sub", "sub", parent_org_id=parent.id)
    user = _make_user(db, "alice")
    _add_membership(db, user, parent, "admin")
    db.flush()

    # Parent Admin inherits Admin on sub-org but org.delete is locked
    # Steward-only.
    assert has_permission(db, user.id, sub.id, "org.delete") is False
    # Sanity: they DO have other Admin-tier permissions.
    assert has_permission(db, user.id, sub.id, "proposal.create") is True


def test_parent_steward_can_delete_sub_org_via_inheritance(db):
    """Phase 15 Cluster S — parent Steward has Steward transferability
    locked ON; resolved role on sub-org is Steward; org.delete is
    granted (Steward-only key matches the resolved role)."""
    parent = _make_org(db, "Parent", "parent")
    sub = _make_org(db, "Sub", "sub", parent_org_id=parent.id)
    user = _make_user(db, "alice")
    _add_membership(db, user, parent, "steward")
    db.flush()

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


# ---------------------------------------------------------------------------
# Phase 12 Stage 2 (B4) — STEWARD_LOCKED_PERMISSIONS + is_locked +
# has_permission belt-and-suspenders
# ---------------------------------------------------------------------------

def test_steward_locked_permissions_constant_contents():
    """The frozenset enumerates exactly the three keys the spec calls out
    as required for self-lockout protection (Q1)."""
    assert STEWARD_LOCKED_PERMISSIONS == frozenset({
        "member.change_role",
        "org.edit_settings",
        "role_permissions.edit",
    })


def test_is_locked_true_for_steward_on_each_protected_key():
    """is_locked covers all three Steward-protected permissions."""
    assert is_locked("steward", "member.change_role") is True
    assert is_locked("steward", "org.edit_settings") is True
    assert is_locked("steward", "role_permissions.edit") is True


def test_is_locked_false_for_steward_on_unprotected_key():
    """is_locked returns False for any permission outside the protected
    subset, even if the role is steward — only the three keys are locked."""
    assert is_locked("steward", "proposal.create") is False
    assert is_locked("steward", "topic.create") is False
    assert is_locked("steward", "audit.view_org") is False
    assert is_locked("steward", "org.delete") is False  # D4, not Stage-2-locked


def test_is_locked_false_for_admin_on_protected_key():
    """is_locked is steward-only — admin/moderator/member callers always
    return False, even on the three protected keys (which they CAN have
    flipped via the matrix for their own row)."""
    assert is_locked("admin", "member.change_role") is False
    assert is_locked("admin", "org.edit_settings") is False
    assert is_locked("admin", "role_permissions.edit") is False
    assert is_locked("moderator", "member.change_role") is False
    assert is_locked("member", "role_permissions.edit") is False


def test_is_locked_false_for_unknown_role():
    """Defensive: an unknown system_key (typo, future custom role) is
    never locked — only the literal 'steward' triggers the protection."""
    assert is_locked("nonexistent-role", "member.change_role") is False
    assert is_locked("", "role_permissions.edit") is False


def test_has_permission_belt_and_suspenders_on_member_change_role(db):
    """B4 belt-and-suspenders: a Steward asking for a STEWARD_LOCKED
    permission gets True even if the underlying role_permissions row is
    explicitly enabled=False (corrupted state, partial migration, manual
    DB tampering — defense in depth)."""
    user = _make_user(db, "steward_alice")
    org = _make_org(db, "Org", "org")
    _add_membership(db, user, org, "steward")

    # Locate the Steward role, find its member.change_role row, force it
    # to enabled=False to simulate a corrupted/tampered state.
    steward_role = (
        db.query(models.Role)
        .filter(models.Role.org_id == org.id, models.Role.system_key == "steward")
        .first()
    )
    rp = (
        db.query(models.RolePermission)
        .filter(
            models.RolePermission.role_id == steward_role.id,
            models.RolePermission.permission_key == "member.change_role",
        )
        .first()
    )
    assert rp is not None, "default seeding should leave a member.change_role row for steward"
    rp.enabled = False
    db.flush()

    # has_permission still returns True — the locked-key short-circuit
    # fires before the role_permissions lookup.
    assert has_permission(db, user.id, org.id, "member.change_role") is True


def test_has_permission_belt_and_suspenders_on_org_edit_settings(db):
    """Same belt-and-suspenders shape for org.edit_settings."""
    user = _make_user(db, "steward_bob")
    org = _make_org(db, "Org", "org")
    _add_membership(db, user, org, "steward")
    steward_role = (
        db.query(models.Role)
        .filter(models.Role.org_id == org.id, models.Role.system_key == "steward")
        .first()
    )
    rp = (
        db.query(models.RolePermission)
        .filter(
            models.RolePermission.role_id == steward_role.id,
            models.RolePermission.permission_key == "org.edit_settings",
        )
        .first()
    )
    rp.enabled = False
    db.flush()

    assert has_permission(db, user.id, org.id, "org.edit_settings") is True


def test_has_permission_belt_and_suspenders_on_role_permissions_edit(db):
    """B4 belt-and-suspenders for role_permissions.edit. Note: the
    seed_default_roles_for_org helper inserts grant rows for the keys in
    DEFAULT_GRANTS; role_permissions.edit IS in DEFAULT_GRANTS for steward
    (Stage 2 added it), so the row exists."""
    user = _make_user(db, "steward_carol")
    org = _make_org(db, "Org", "org")
    _add_membership(db, user, org, "steward")
    steward_role = (
        db.query(models.Role)
        .filter(models.Role.org_id == org.id, models.Role.system_key == "steward")
        .first()
    )
    rp = (
        db.query(models.RolePermission)
        .filter(
            models.RolePermission.role_id == steward_role.id,
            models.RolePermission.permission_key == "role_permissions.edit",
        )
        .first()
    )
    assert rp is not None, "Stage 2 seed should insert a role_permissions.edit row for steward"
    rp.enabled = False
    db.flush()

    assert has_permission(db, user.id, org.id, "role_permissions.edit") is True


def test_has_permission_belt_and_suspenders_works_with_missing_row(db):
    """Edge case: if the role_permissions row for a locked key is missing
    entirely (would never happen via the helper, but possible via raw DB
    tampering), the steward still gets True. Belt-and-suspenders doesn't
    require the row to exist."""
    user = _make_user(db, "steward_dave")
    org = _make_org(db, "Org", "org")
    _add_membership(db, user, org, "steward")
    steward_role = (
        db.query(models.Role)
        .filter(models.Role.org_id == org.id, models.Role.system_key == "steward")
        .first()
    )
    # Delete the role_permissions.edit row entirely.
    db.query(models.RolePermission).filter(
        models.RolePermission.role_id == steward_role.id,
        models.RolePermission.permission_key == "role_permissions.edit",
    ).delete()
    db.flush()

    assert has_permission(db, user.id, org.id, "role_permissions.edit") is True


def test_belt_and_suspenders_does_not_promote_non_steward(db):
    """The belt-and-suspenders short-circuit is specific to the Steward
    role — admins and moderators querying a locked key still go through
    the standard role_permissions lookup and get whatever the matrix
    says (admin defaults to True for role_permissions.edit; moderator
    defaults to False)."""
    admin_user = _make_user(db, "alice_admin")
    mod_user = _make_user(db, "bob_mod")
    org = _make_org(db, "Org", "org")
    _add_membership(db, admin_user, org, "admin")
    _add_membership(db, mod_user, org, "moderator")
    db.flush()

    # Admin gets True for role_permissions.edit by default (it's in
    # DEFAULT_GRANTS for admin via ALL_PERMISSION_KEYS).
    assert has_permission(db, admin_user.id, org.id, "role_permissions.edit") is True

    # Moderator gets False — it's not in their default grants and
    # belt-and-suspenders doesn't apply to non-Steward callers.
    assert has_permission(db, mod_user.id, org.id, "role_permissions.edit") is False

    # member.change_role: admin gets True (default grant); moderator
    # also gets False (not in moderator default grants).
    assert has_permission(db, admin_user.id, org.id, "member.change_role") is True
    assert has_permission(db, mod_user.id, org.id, "member.change_role") is False


def test_belt_and_suspenders_does_not_grant_arbitrary_permissions(db):
    """The short-circuit fires only for keys in STEWARD_LOCKED_PERMISSIONS.
    A Steward whose proposal.create row is enabled=False would actually
    return False (proposal.create is not a locked key)."""
    user = _make_user(db, "steward_alice")
    org = _make_org(db, "Org", "org")
    _add_membership(db, user, org, "steward")
    steward_role = (
        db.query(models.Role)
        .filter(models.Role.org_id == org.id, models.Role.system_key == "steward")
        .first()
    )
    rp = (
        db.query(models.RolePermission)
        .filter(
            models.RolePermission.role_id == steward_role.id,
            models.RolePermission.permission_key == "proposal.create",
        )
        .first()
    )
    rp.enabled = False
    db.flush()

    # proposal.create is NOT in STEWARD_LOCKED_PERMISSIONS → falls through
    # to the standard role_permissions lookup, which now reads False.
    assert has_permission(db, user.id, org.id, "proposal.create") is False
