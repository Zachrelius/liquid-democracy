"""Phase 12 Stage 1 — seed helper for the four preset Role rows + their
default RolePermission grants.

Called from:
  - ``routes/organizations.py::create_organization`` for new orgs.
  - The phase_12_role_permissions migration for every existing org during
    the upgrade.

The DEFAULT_GRANTS / PRESET_ROLES tables defined below are duplicated by
intent: this module needs them at import time during the migration where
``backend/permission_registry.py`` (the canonical home, written by the
parallel Cluster H workstream) may not be importable from inside the
Alembic env. **Once H lands**, this module's ``DEFAULT_GRANTS`` and
``PRESET_ROLES`` should be removed and replaced with a re-export from
``permission_registry``. See the "DEFAULT_GRANTS coordination" note in
the closeout report.
"""
from __future__ import annotations

from typing import Dict

from sqlalchemy.orm import Session

import models


# ---------------------------------------------------------------------------
# Preset role definitions (display_order matches the spec)
# ---------------------------------------------------------------------------

# (system_key, display_name, display_order)
PRESET_ROLES: list[tuple[str, str, int]] = [
    ("steward", "Steward", 0),
    ("admin", "Admin", 1),
    ("moderator", "Moderator", 2),
    ("member", "Member", 3),
]


# ---------------------------------------------------------------------------
# Default permission grants per preset role
# ---------------------------------------------------------------------------
# Source of truth: phase12_configurable_role_permissions_stage1_spec.md
# §"Permission registry" (lines 99-145). 23 permission keys total.
# Steward and Admin currently get all 23; Moderator gets the 8 keys
# explicitly listing "moderator" in the default column; Member gets none.

_ALL_PERMISSIONS: tuple[str, ...] = (
    # Proposals
    "proposal.create",
    "proposal.delete",
    "proposal.advance_phase",
    "proposal.resolve_tie",
    # Topics
    "topic.create",
    "topic.edit",
    "topic.delete",
    # Members
    "member.approve_join",
    "member.remove",
    "member.suspend",
    "member.change_role",
    "member.invite",
    # Sub-organizations
    "sub_org.create",
    "sub_org.delete",
    "sub_org.edit_settings",
    # Delegate applications
    "delegate_application.approve",
    # Polis
    "polis.create",
    "polis.manage",
    # Comments
    "comment.moderate",
    # Organization
    "org.edit_settings",
    "org.edit_branding",
    # Audit & analytics
    "audit.view_org",
    "analytics.view",
)

# Moderator-tier grants per spec (8 keys; the dispatch's "10" is stale).
_MODERATOR_GRANTS: frozenset[str] = frozenset({
    "proposal.create",
    "proposal.advance_phase",
    "topic.create",
    "topic.edit",
    "member.approve_join",
    "member.invite",
    "polis.create",
    "comment.moderate",
})

DEFAULT_GRANTS: Dict[str, frozenset[str]] = {
    "steward": frozenset(_ALL_PERMISSIONS),
    "admin": frozenset(_ALL_PERMISSIONS),
    "moderator": _MODERATOR_GRANTS,
    "member": frozenset(),
}


# ---------------------------------------------------------------------------
# Seed helper — used by routes and (via a dialect-agnostic raw SQL
# equivalent) the migration.
# ---------------------------------------------------------------------------

def seed_default_roles_for_org(db: Session, org_id: str) -> dict[str, "models.Role"]:
    """Create the 4 preset Role rows + default RolePermission grants for *org_id*.

    Idempotent: if any preset role already exists for this org (matched by
    ``(org_id, system_key)``), the existing one is reused and any missing
    permission rows are inserted. Returns a dict mapping ``system_key -> Role``
    so callers can immediately set e.g. ``membership.role_id = roles["steward"].id``.

    The function flushes (so generated IDs are populated) but does not commit;
    the caller owns the transaction.
    """
    # 1. Find or create the four preset Roles for this org.
    existing_roles = (
        db.query(models.Role)
        .filter(models.Role.org_id == org_id)
        .all()
    )
    by_key: dict[str, models.Role] = {r.system_key: r for r in existing_roles}

    for system_key, display_name, display_order in PRESET_ROLES:
        if system_key in by_key:
            continue
        role = models.Role(
            org_id=org_id,
            name=display_name,
            system_key=system_key,
            is_system_preset=True,
            display_order=display_order,
        )
        db.add(role)
        db.flush()  # populate role.id
        by_key[system_key] = role

    # 2. For each preset role, ensure the default permission rows exist.
    for system_key, _, _ in PRESET_ROLES:
        role = by_key[system_key]
        granted: frozenset[str] = DEFAULT_GRANTS.get(system_key, frozenset())
        # Don't insert anything for member (granted is empty); but DO insert
        # the granted set for the others if missing.
        if not granted:
            continue
        existing_keys = {
            rp.permission_key for rp in
            db.query(models.RolePermission)
            .filter(models.RolePermission.role_id == role.id)
            .all()
        }
        for permission_key in granted:
            if permission_key in existing_keys:
                continue
            db.add(
                models.RolePermission(
                    role_id=role.id,
                    permission_key=permission_key,
                    enabled=True,
                )
            )
        db.flush()

    return by_key
