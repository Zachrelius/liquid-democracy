"""Phase 12 Stage 1 + Phase 15 Cluster S — has_permission helper +
per-request cache + sub-org effective-role resolution.

Single entry point for "can user X do action Y in org Z?" checks across
the backend.

Resolution order for parent-org checks (Phase 12 Stage 1):

  1. ``has_permission`` first checks the Decision-6 implicit-power
     shortcut: if ``org_id`` refers to a sub-org and the user is parent
     admin/steward AND that role transfers (Phase 15 transferability
     config), return True. **Phase 15 Cluster S note:** this shortcut is
     now transferability-aware; parent Admin no longer ALWAYS transfers
     (defaults ON but configurable). Sub-org checks should now go
     through ``has_permission_on_sub_org`` which uses
     ``effective_role_on_sub_org`` for the full resolution model.

  2. Owner-only D4 hardcoded gates. ``org.delete`` and
     ``org.transfer_stewardship`` require role.system_key == 'steward'.

  3. Standard path. Look up the user's active OrgMembership; follow
     ``membership.role_id → Role → role_permissions`` for the
     ``(role_id, permission_key)`` pair; return ``enabled``.

Phase 15 Cluster S — sub-org permission resolution:

  ``effective_role_on_sub_org(db, user_id, sub_org)`` returns the
  highest-tier applicable Role for a user on a sub-org, or None. The
  candidates are:
    1. Sub-org-specific role (from active SubOrgMembership.role_id).
    2. Parent role IF transferability is set (per
       ``role_transfers_to_sub_orgs``).
    3. Platform-admin Admin-level grant if ``user.is_admin``.

  ``has_permission_on_sub_org(db, user_id, sub_org, permission_key)``
  resolves the effective role then checks the parent org's matrix. The
  return value is ``(allowed, via_platform_admin)`` so callers can
  emit ``platform_admin_override`` audit-log enrichment when relevant.

Out of scope here:

  * Platform admin (``User.is_admin``) is consulted ONLY in
    ``effective_role_on_sub_org`` as the final fallback; parent-org
    permissions still ignore it (governed by ``auth.get_current_admin``).
"""

from __future__ import annotations

from typing import Optional, Tuple

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


def is_locked(
    role_system_key: str,
    permission_key: str,
    org: Optional["models.Organization"] = None,
) -> bool:
    """Return True if this (role, permission) cell is hardcoded and not
    user-editable via the matrix.

    Phase 12: the Steward holds the three self-lockout-protected
    permissions in ``STEWARD_LOCKED_PERMISSIONS``. Phase 45b D5: in
    ``admin_council`` mode, those same permissions are locked for the
    admin tier instead (the steward seat doesn't exist).

    ``org`` is optional for back-compat with call sites that don't
    thread it through; without ``org`` the function defaults to
    pre-45b behavior (steward locked, admin matrix-editable). Call sites
    that gate the matrix PATCH endpoint thread ``org`` through so the
    correct tier is protected in council mode.
    """
    if permission_key not in STEWARD_LOCKED_PERMISSIONS:
        return False
    if org is None:
        # Back-compat: pre-45b call sites still get the steward lock.
        return role_system_key == "steward"
    from governance import governing_role_key
    return role_system_key == governing_role_key(org)


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

    # --- Resolution step 1: sub-org effective-role resolution ---
    # If org_id is a sub-org, defer to the Phase 15 Cluster S
    # ``has_permission_on_sub_org`` path which resolves the user's
    # effective role (sub-org-specific assignment, transferable parent
    # role, or platform-admin Admin grant) and consults the parent's
    # matrix at the resolved role.
    #
    # This replaces the Phase 12 Stage 1 "implicit power" shortcut where
    # parent admin/steward got EVERY permission on the sub-org
    # unconditionally — that path didn't honor transferability config
    # and didn't model platform admin grants. The new path covers both:
    #   - parent Steward / Admin (when transferability enabled) still
    #     get the matrix's grants, identical to the old behavior for
    #     all-permissions-true Admin/Steward roles.
    #   - parent Member with default-off transferability now correctly
    #     resolves to "no permission".
    org = db.get(models.Organization, org_id)
    if org is None:
        return False
    if org.parent_org_id is not None:
        allowed, _via_pa = has_permission_on_sub_org(
            db, user_id, org, permission_key,
        )
        return allowed

    # --- Resolution step 2: D4 owner-only hardcoded gates ---
    # Phase 45b D4 — in ``admin_council`` mode there is no Steward; the
    # OWNER_ONLY_KEYS (``org.delete``, ``org.transfer_stewardship``)
    # vest in any admin instead. Default ``single_steward`` mode keeps
    # the pre-45b steward-only resolution.
    if permission_key in OWNER_ONLY_KEYS:
        from governance import governing_role_key
        target_role = governing_role_key(org)
        return _user_role_system_key(db, user_id, org_id) == target_role

    # --- Resolution step 2b: Phase 12 Stage 2 belt-and-suspenders ---
    # Steward-locked permissions are hardcoded TRUE for the top-tier
    # role on this org regardless of the underlying ``role_permissions``
    # row state. Phase 45b D5 — in admin_council mode that's the admin
    # tier; in single_steward mode it's the steward.
    # The matrix PATCH endpoint rejects flips on these cells for the
    # top-tier row, so in normal operation the row will always be
    # enabled=True; this extra check defends against a corrupted row,
    # a partial backfill, or direct DB tampering. Cheap.
    if permission_key in STEWARD_LOCKED_PERMISSIONS:
        from governance import governing_role_key
        target_role = governing_role_key(org)
        if _user_role_system_key(db, user_id, org_id) == target_role:
            return True
        # Non-top-tier callers fall through to the standard path; their
        # access is whatever the matrix says.

    # --- Resolution step 3: standard path through role_permissions ---
    cache_key = (user_id, org_id)
    if cache_key not in cache:
        cache[cache_key] = _load_permission_set_for_user_org(db, user_id, org_id)
    return cache[cache_key].get(permission_key, False)


# ---------------------------------------------------------------------------
# Phase 15 Cluster S — sub-org permission inheritance + transferability
# ---------------------------------------------------------------------------

# Tier ordering for "highest role wins" resolution. Steward is the
# strongest; Member the weakest. A user with no candidates (no sub-org
# membership, no transferable parent role, not platform admin) gets
# None — no permissions on the sub-org.
ROLE_TIER: dict[str, int] = {
    "member": 0,
    "moderator": 1,
    "admin": 2,
    "steward": 3,
}


def role_transfers_to_sub_orgs(
    org: "models.Organization", role_system_key: str,
) -> bool:
    """Return True if a user holding ``role_system_key`` on the parent
    org should inherit that role's permissions on every sub-org of
    this parent.

    Phase 15 Cluster S §S1/S3 (locked with Z):
      - Steward: ALWAYS transfers. The toggle exists in the settings
        JSON for symmetry but is locked at the helper level — even a
        stored ``False`` is overridden here. Setting it to False through
        the settings API is rejected upstream with 400.
      - Admin: defaults ON; configurable via
        ``Organization.settings.sub_org_role_transferability.admin``.
      - Moderator: defaults ON; configurable.
      - Member: defaults OFF; configurable.

    The settings JSON shape::

        Organization.settings = {
          "sub_org_role_transferability": {
            "steward": true,   # ignored, locked on
            "admin": true,
            "moderator": true,
            "member": false,
          },
          ...
        }

    Per spec, the JSON key is sibling to other Organization.settings
    entries (branding, intro_text, default thresholds, etc.); this
    helper does not touch any of them.
    """
    if role_system_key == "steward":
        return True  # Locked on; not configurable.

    settings = (org.settings or {}).get("sub_org_role_transferability", {})
    defaults = {"admin": True, "moderator": True, "member": False}
    # Use ``in`` rather than ``.get`` with a default so a missing key
    # falls back to the spec's default; an explicit False overrides.
    if role_system_key in settings:
        return bool(settings[role_system_key])
    return defaults.get(role_system_key, False)


def _platform_admin_role(
    db: Session, parent_org_id: str,
) -> Optional["models.Role"]:
    """Return the parent org's Admin Role (the role granted to platform
    admins under the spec §S1 case 3)."""
    return (
        db.query(models.Role)
        .filter(
            models.Role.org_id == parent_org_id,
            models.Role.system_key == "admin",
        )
        .first()
    )


def effective_role_on_sub_org(
    db: Session, user_id: str, sub_org: "models.Organization",
) -> Tuple[Optional["models.Role"], bool]:
    """Phase 15 Cluster S §S1 — resolve the highest-tier applicable Role
    for ``user_id`` on ``sub_org``.

    Returns a tuple ``(role, via_platform_admin)``:
      - ``role``: the resolved Role row, or None if no candidates apply.
      - ``via_platform_admin``: True iff the resolved role came ONLY from
        the platform-admin fallback (case 3) — i.e., the user has no
        sub-org membership and no transferable parent role. Callers
        should emit ``platform_admin_override: true`` on audit events
        when this flag is set.

    Resolution candidates (highest-tier wins):

      1. Sub-org-specific assignment from an active SubOrgMembership.
      2. Parent role with ``role_transfers_to_sub_orgs`` set.
      3. Platform admin Admin-level grant (if ``user.is_admin``).

    The matrix permission lookup against the resolved role is the
    caller's job (see ``has_permission_on_sub_org``); this function
    only does the resolution.
    """
    if sub_org.parent_org_id is None:
        raise ValueError(
            "effective_role_on_sub_org called on a non-sub-org "
            f"(organization id={sub_org.id} has parent_org_id=NULL)."
        )
    parent_org = db.get(models.Organization, sub_org.parent_org_id)
    if parent_org is None:
        return None, False

    candidates: list[tuple[models.Role, bool]] = []
    # ``via_platform_admin`` is True only if THIS candidate came from
    # the platform-admin fallback. The final tuple's flag is True iff
    # the WINNER's flag is True — i.e., only when no stronger candidate
    # outranks the platform-admin grant.

    # 1. Sub-org-specific role assignment.
    sub_membership = (
        db.query(models.SubOrgMembership)
        .filter(
            models.SubOrgMembership.user_id == user_id,
            models.SubOrgMembership.sub_org_id == sub_org.id,
            models.SubOrgMembership.status == "active",
        )
        .first()
    )
    if sub_membership is not None and sub_membership.role is not None:
        candidates.append((sub_membership.role, False))

    # 2. Parent role with transferability flag set.
    parent_membership = (
        db.query(models.OrgMembership)
        .filter(
            models.OrgMembership.user_id == user_id,
            models.OrgMembership.org_id == parent_org.id,
            models.OrgMembership.status == "active",
        )
        .first()
    )
    if parent_membership is not None and parent_membership.role is not None:
        parent_role = parent_membership.role
        if role_transfers_to_sub_orgs(parent_org, parent_role.system_key):
            candidates.append((parent_role, False))

    # 3. Platform admin Admin-level grant.
    user = db.get(models.User, user_id)
    if user is not None and user.is_admin:
        admin_role = _platform_admin_role(db, parent_org.id)
        if admin_role is not None:
            candidates.append((admin_role, True))

    if not candidates:
        return None, False

    # Highest-tier wins. Among ties (shouldn't happen in normal data
    # because a user can't have two distinct roles on the same scope),
    # prefer the non-platform-admin candidate so the override flag is
    # only set when the platform-admin path is actually load-bearing.
    candidates.sort(
        key=lambda rb: (
            ROLE_TIER.get(rb[0].system_key, -1),
            # Tie-break: non-override (False) sorts after True, so
            # use the negation to prefer False (real grants) over True.
            not rb[1],
        ),
        reverse=True,
    )
    winner_role, winner_via_pa = candidates[0]
    return winner_role, winner_via_pa


def has_permission_on_sub_org(
    db: Session,
    user_id: str,
    sub_org: "models.Organization",
    permission_key: str,
) -> Tuple[bool, bool]:
    """Phase 15 Cluster S §S4 — sub-org permission gate using the
    effective-role resolution model + the parent's matrix.

    Returns ``(allowed, via_platform_admin)``. Callers that emit audit
    events should pass the second element through to
    ``log_audit_event``'s ``details`` payload as
    ``platform_admin_override`` when True.

    The owner-only D4 keys (``org.delete``, ``org.transfer_stewardship``)
    are gated on the resolved system_key being ``'steward'``. Platform
    admins do NOT get these via the override path because the resolved
    role for a platform-admin-only path is ``admin``, not ``steward``.
    This is the explicit S6 test case ("Platform admin attempts
    org.delete on a sub-org: fails").

    The Steward-locked permissions (member.change_role,
    org.edit_settings, role_permissions.edit) are hardcoded TRUE for
    Stewards regardless of any matrix row state, paralleling
    ``has_permission`` for parent orgs.
    """
    role, via_pa = effective_role_on_sub_org(db, user_id, sub_org)
    if role is None:
        return False, False

    # D4 owner-only gates.
    if permission_key in OWNER_ONLY_KEYS:
        return (role.system_key == "steward", via_pa)

    # Steward-locked permissions.
    if permission_key in STEWARD_LOCKED_PERMISSIONS:
        if role.system_key == "steward":
            return True, via_pa
        # Non-Steward callers fall through to the matrix.

    # Standard path: matrix lookup against the parent's role_permissions
    # rows for this resolved role.
    cache = get_or_init_permission_cache(db)
    parent_org_id = sub_org.parent_org_id
    cache_key = (user_id, f"sub:{sub_org.id}:role:{role.id}")
    if cache_key not in cache:
        rows = (
            db.query(
                models.RolePermission.permission_key,
                models.RolePermission.enabled,
            )
            .filter(models.RolePermission.role_id == role.id)
            .all()
        )
        cache[cache_key] = {key: enabled for key, enabled in rows}
    return cache[cache_key].get(permission_key, False), via_pa


__all__ = [
    "OWNER_ONLY_KEYS",
    "STEWARD_LOCKED_PERMISSIONS",
    "ROLE_TIER",
    "get_or_init_permission_cache",
    "has_permission",
    "is_locked",
    "role_transfers_to_sub_orgs",
    "effective_role_on_sub_org",
    "has_permission_on_sub_org",
]
