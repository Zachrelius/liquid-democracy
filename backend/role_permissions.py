"""Phase 12 Stage 1 — has_permission helper + per-request cache (Cluster H, H1+H2).

Single entry point for "can user X do action Y in org Z?" checks across the
backend. Replaces the scattered ``role in ('admin', 'owner')`` patterns
(refactored away by Cluster R).

Resolution order (per spec H1, lines 263-300):

  1. Decision-6 implicit power. If ``org_id`` refers to a sub-org
     (``Organization.parent_org_id IS NOT NULL``), check whether the user
     has an active OrgMembership on the PARENT org with role.system_key in
     {'admin', 'steward'}. If yes, return True for ANY permission_key.
     Hardcoded — not user-configurable in Stage 1.

  2. Owner-only D4 hardcoded gates. The keys ``org.delete`` and
     ``org.transfer_stewardship`` cannot be re-granted via the permission
     system. They require the user's role.system_key on this org to be
     'steward'. The role_permissions table is NOT consulted for these
     keys — even an explicit row would be ignored.

  3. Standard path. Look up the user's active OrgMembership for this org;
     follow membership.role_id → Role → role_permissions for
     ``(role_id, permission_key)``; return ``enabled``.

Returns False if the user is not a member, the membership is not active,
the role row is missing, or no matching role_permission row exists.

Per-request cache (Decision 6, spec H2):

  Stored on ``Session.info['_permission_cache']`` keyed by
  ``(user_id, org_id)`` → ``dict[permission_key, bool]`` (the user's full
  permission set for that org). On a first miss for a given (user, org)
  pair, ONE query joins OrgMembership → Role → RolePermission and loads
  every grant; subsequent calls in the same request are dict lookups.

  The Decision-6 path also fills the ``(user, parent_org)`` cache as a
  side effect because it loads the parent's permission set during the
  implicit-power check.

  ``Session.info`` is request-scoped (FastAPI's ``get_db`` dependency
  yields a fresh session per request), so no manual eviction is needed.

Out of scope here (separate concerns):

  * Platform admin (``User.is_admin``) — completely separate gate;
    governed by ``auth.get_current_admin``. Not consulted here.
  * Sub-org direct membership roles (``SubOrgMembership.role``) — Stage 1
    keeps these as string columns; helpers in ``permissions.py`` continue
    to use them for the direct-sub-org-admin path. ``has_permission`` only
    handles the parent-org-implicit branch of the sub-org story.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

import models


# Permission keys that bypass the permission system entirely (D4).
# Even an explicit ``role_permissions`` row enabling these for a non-Steward
# role is ignored — the only path to True is ``role.system_key == 'steward'``.
OWNER_ONLY_KEYS: frozenset[str] = frozenset(
    {"org.delete", "org.transfer_stewardship"}
)


# Phase 12 Stage 2 (Q1) — permissions that are HARDCODED-TRUE for the
# Steward role and not editable through the matrix UI. The matrix PATCH
# endpoint rejects any attempt to flip these cells; ``has_permission``
# also returns True for the Steward on these keys regardless of any
# ``role_permissions`` row state (belt-and-suspenders against a corrupt
# row, a partial migration, or direct DB tampering).
#
# The three keys are the minimum protection against self-lockout:
#   - member.change_role: without it, removing a Steward's admin/moderator
#     subordinates leaves no one to promote, and the org is structurally
#     stuck.
#   - org.edit_settings: without it, basic org operability is broken.
#   - role_permissions.edit: without it, a Steward who saves a bad matrix
#     state can't undo their own change; one save and the org is frozen.
STEWARD_LOCKED_PERMISSIONS: frozenset[str] = frozenset(
    {"member.change_role", "org.edit_settings", "role_permissions.edit"}
)


# Role system_keys that grant implicit sub-org admin power on the parent org.
_PARENT_IMPLICIT_ADMIN_KEYS: frozenset[str] = frozenset({"admin", "steward"})


def is_locked(role_system_key: str, permission_key: str) -> bool:
    """Return True if this (role, permission) cell is hardcoded and not
    user-editable via the matrix.

    Currently only Steward has locked cells (the three
    self-lockout-protected permissions in
    ``STEWARD_LOCKED_PERMISSIONS``). The function is structured to admit
    future locks on other roles without a signature change — callers
    pass both axes and trust this single source of truth.
    """
    if role_system_key == "steward" and permission_key in STEWARD_LOCKED_PERMISSIONS:
        return True
    return False


def get_or_init_permission_cache(db: Session) -> dict:
    """Return the per-request permission cache dict, creating it lazily.

    The cache lives on ``Session.info`` — SQLAlchemy's request-scoped dict
    that's cleared when the session is closed (which FastAPI's ``get_db``
    does at the end of every request).

    Cache shape::

        {
          (user_id, org_id): {permission_key: bool, ...},  # full grant set
          ...
        }

    A ``(user, org)`` key with value ``{}`` (empty dict) is a real cache hit
    meaning "the user has no permissions in this org" (e.g., not a member,
    or a member with the four-defaults-empty 'member' role). The absence of
    the key means "not yet looked up."
    """
    cache = db.info.get("_permission_cache")
    if cache is None:
        cache = {}
        db.info["_permission_cache"] = cache
    return cache


def _load_permission_set_for_user_org(
    db: Session, user_id: str, org_id: str
) -> dict[str, bool]:
    """One-query load of the user's full permission set for this org.

    Joins OrgMembership → Role → RolePermission. Returns a dict of every
    permission_key with its enabled flag. Empty dict if the user has no
    active membership, no role, or no role_permission rows.

    This is the only function that hits the database for permission lookups;
    ``has_permission`` calls it once per ``(user_id, org_id)`` pair per
    request (subsequent calls hit the cache).
    """
    # Find the user's active OrgMembership row for this org.
    membership = (
        db.query(models.OrgMembership)
        .filter(
            models.OrgMembership.user_id == user_id,
            models.OrgMembership.org_id == org_id,
            models.OrgMembership.status == "active",
        )
        .first()
    )
    if membership is None or membership.role_id is None:
        return {}

    # Pull every role_permission row for this role in one query.
    rows = (
        db.query(
            models.RolePermission.permission_key,
            models.RolePermission.enabled,
        )
        .filter(models.RolePermission.role_id == membership.role_id)
        .all()
    )
    return {key: enabled for key, enabled in rows}


def _user_role_system_key(
    db: Session, user_id: str, org_id: str
) -> Optional[str]:
    """Return the user's role.system_key on this org, or None.

    Used by the D4 owner-only gate which can't be expressed as a
    role_permission row — Stewardship is intrinsic to the role, not
    grantable.
    """
    membership = (
        db.query(models.OrgMembership)
        .filter(
            models.OrgMembership.user_id == user_id,
            models.OrgMembership.org_id == org_id,
            models.OrgMembership.status == "active",
        )
        .first()
    )
    if membership is None or membership.role_id is None:
        return None
    role = db.get(models.Role, membership.role_id)
    if role is None:
        return None
    return role.system_key


def has_permission(
    db: Session,
    user_id: str,
    org_id: str,
    permission_key: str,
) -> bool:
    """Return True if user holds the named permission in the given org.

    See module docstring for full resolution order. Result is cached per
    request via the SQLAlchemy session's ``info`` dict; the cache is keyed
    by ``(user_id, org_id)`` and stores the user's full permission set for
    that org.

    Args:
      db: request-scoped SQLAlchemy session.
      user_id: caller user.id.
      org_id: target Organization.id (parent org or sub-org).
      permission_key: a key from ``permission_registry.PERMISSION_REGISTRY``,
        OR one of the OWNER_ONLY_KEYS (``org.delete``, ``org.transfer_stewardship``).

    Returns False on any of: user not a member, membership not active,
    role row missing, no matching role_permission row, owner-only key
    requested by a non-Steward, etc.
    """
    cache = get_or_init_permission_cache(db)

    # --- Resolution step 1: Decision-6 implicit power ---
    # If org_id is a sub-org, check whether the user is admin/steward on
    # the parent. If so, they get every permission on the sub-org.
    org = db.get(models.Organization, org_id)
    if org is None:
        return False
    if org.parent_org_id is not None:
        parent_id = org.parent_org_id
        # Load (and cache) the parent's permission set for this user — but
        # the implicit-power test is on the parent role's system_key, not on
        # a permission key. We need the role.system_key for that check,
        # which the cached permission set doesn't carry. Load it directly.
        parent_system_key = _user_role_system_key(db, user_id, parent_id)
        if parent_system_key in _PARENT_IMPLICIT_ADMIN_KEYS:
            # Side-effect: also cache the parent's permission set so any
            # subsequent has_permission(user, parent_id, ...) call in the
            # same request hits the cache.
            parent_cache_key = (user_id, parent_id)
            if parent_cache_key not in cache:
                cache[parent_cache_key] = _load_permission_set_for_user_org(
                    db, user_id, parent_id
                )
            return True

    # --- Resolution step 2: D4 owner-only hardcoded gates ---
    if permission_key in OWNER_ONLY_KEYS:
        # The role_permissions table is NOT consulted for these keys; only
        # the role's system_key being 'steward' grants them.
        return _user_role_system_key(db, user_id, org_id) == "steward"

    # --- Resolution step 2b: Phase 12 Stage 2 belt-and-suspenders ---
    # Steward-locked permissions are hardcoded TRUE for the Steward role
    # on this org regardless of the underlying ``role_permissions`` row
    # state. The matrix PATCH endpoint rejects flips on these cells, so
    # in normal operation the row will always be enabled=True; this
    # extra check defends against a corrupted row, a partial backfill, or
    # direct DB tampering. Cheap (one frozenset membership check + one
    # role lookup that's also needed for D4 above).
    if permission_key in STEWARD_LOCKED_PERMISSIONS:
        if _user_role_system_key(db, user_id, org_id) == "steward":
            return True
        # Non-Steward callers fall through to the standard path; their
        # access is whatever the matrix says (admin defaults to True for
        # role_permissions.edit, etc.).

    # --- Resolution step 3: standard path through role_permissions ---
    cache_key = (user_id, org_id)
    if cache_key not in cache:
        cache[cache_key] = _load_permission_set_for_user_org(db, user_id, org_id)
    return cache[cache_key].get(permission_key, False)


__all__ = [
    "OWNER_ONLY_KEYS",
    "STEWARD_LOCKED_PERMISSIONS",
    "get_or_init_permission_cache",
    "has_permission",
    "is_locked",
]
