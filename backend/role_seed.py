"""Phase 12 Stage 1 — seed helper for the four preset Role rows + their
default RolePermission grants.

Called from:
  - ``routes/organizations.py::create_organization`` for new orgs.
  - The phase_12_role_permissions migration for every existing org during
    the upgrade.

DEFAULT_GRANTS coordination note: the canonical home for the grant table
is ``backend/permission_registry.py`` (Cluster H). This module re-exports
it via ``from permission_registry import DEFAULT_GRANTS`` so the seed
helper and the registry stay in sync. The Alembic migration intentionally
duplicates the table inline because the Alembic env's import path is not
guaranteed to include the application's ``permission_registry`` module
during a production migration run; that duplication is the only place
DEFAULT_GRANTS is restated outside this re-export.
"""
from __future__ import annotations

from typing import Dict

from sqlalchemy.orm import Session

import models
from permission_registry import DEFAULT_GRANTS as _REGISTRY_DEFAULT_GRANTS


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


# Re-export the registry's DEFAULT_GRANTS keyed by Role.system_key so the
# rest of this module (and the test suite asserting on it) can use one
# canonical name. Per-set entries are coerced to frozenset for hashability.
DEFAULT_GRANTS: Dict[str, frozenset[str]] = {
    system_key: frozenset(grant_set)
    for system_key, grant_set in _REGISTRY_DEFAULT_GRANTS.items()
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
