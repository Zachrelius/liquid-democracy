"""Phase 12 Stage 2 — per-org role-permissions matrix endpoints
(Cluster B, B1 + B2).

Two endpoints scoped to a specific organization:

  * ``GET /api/orgs/{org_slug}/role-permissions`` — read the matrix.
    Auth: any authenticated user with an active OrgMembership on the
    org. Reading the matrix is NOT permission-gated; only writing is.
    Response shape per spec lines 102-121.

  * ``PATCH /api/orgs/{org_slug}/role-permissions`` — write the matrix.
    Gated by ``has_permission(user, org, "role_permissions.edit")``.
    Body: ``{"changes": [{role_system_key, permission_key, enabled}, ...]}``.
    Per-spec rules (lines 143-156): atomic transaction; reject locked
    cells; reject unknown role/permission keys; no-op (no rows changed)
    skips the audit insert; otherwise emit one audit event per save.

The handlers live in their own module rather than extending
``routes/permissions.py`` (the static registry endpoint) so the prefix
shape is org-scoped and the audit + permission machinery is co-located.
``main.py`` wires this router alongside the existing
``permissions.router``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import auth as auth_utils
import models
from audit_utils import log_audit_event
from database import get_db
from permission_registry import ALL_PERMISSION_KEYS
from role_permissions import (
    STEWARD_LOCKED_PERMISSIONS,
    has_permission,
    is_locked,
)


router = APIRouter(prefix="/api/orgs", tags=["role-permissions"])


# Stable preset role ordering — mirrors role_seed.PRESET_ROLES. We can't
# import it here without pulling in extra surface; the four-element tuple
# is small enough to inline. Display order is enforced by the matrix UI's
# column rendering.
_PRESET_SYSTEM_KEYS: frozenset[str] = frozenset(
    {"steward", "admin", "moderator", "member"}
)


# ---------------------------------------------------------------------------
# Request/response shapes
# ---------------------------------------------------------------------------

class RolePermissionChange(BaseModel):
    role_system_key: str = Field(..., min_length=1)
    permission_key: str = Field(..., min_length=1)
    enabled: bool


class RolePermissionPatch(BaseModel):
    changes: list[RolePermissionChange] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_org_or_404(db: Session, org_slug: str) -> models.Organization:
    org = (
        db.query(models.Organization)
        .filter(models.Organization.slug == org_slug)
        .first()
    )
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


def _resolve_active_membership_or_404(
    db: Session, user_id: str, org_id: str
) -> models.OrgMembership:
    """Return the caller's active OrgMembership for this org. 404 if not
    a member — same shape as the routes/organizations.py "not a member"
    response so the matrix endpoints don't leak org existence to outsiders.
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
    if membership is None:
        # Hide the org from non-members: 404 (per spec line 220 "404 caller
        # not member of org"). Direct curl callers can't distinguish "org
        # doesn't exist" from "you're not in it".
        raise HTTPException(status_code=404, detail="Organization not found")
    return membership


def _build_matrix_payload(
    db: Session, org: models.Organization
) -> dict[str, Any]:
    """Construct the B1 response payload for *org*.

    Shape::

        {
          "org_id": ...,
          "org_slug": ...,
          "roles": [{id, system_key, name, display_order} × 4],
          "permissions": {<perm_key>: {<role_system_key>: bool} × 24},
          "locked": {"steward": [<3 keys>]}
        }

    Frontend joins client-side with ``/api/permissions/registry`` for
    category metadata (per spec line 126: don't include registry inline).
    """
    # Fetch the org's preset roles in display_order. We only emit rows for
    # the four preset roles; custom roles are out of scope for Stage 2.
    roles = (
        db.query(models.Role)
        .filter(
            models.Role.org_id == org.id,
            models.Role.system_key.in_(list(_PRESET_SYSTEM_KEYS)),
        )
        .order_by(models.Role.display_order.asc())
        .all()
    )
    role_id_by_system_key: dict[str, str] = {
        r.system_key: r.id for r in roles
    }

    # Pull every role_permissions row for these roles in one query.
    rp_rows = (
        db.query(
            models.RolePermission.role_id,
            models.RolePermission.permission_key,
            models.RolePermission.enabled,
        )
        .filter(
            models.RolePermission.role_id.in_(
                list(role_id_by_system_key.values())
            )
        )
        .all()
    )
    # Index by (role_id, permission_key) -> enabled for fast lookup.
    rp_index: dict[tuple[str, str], bool] = {
        (role_id, pkey): bool(enabled) for role_id, pkey, enabled in rp_rows
    }

    # Build the per-permission, per-role nested dict. We emit every key
    # in the registry × every preset role; missing rows default to False
    # (matches has_permission's resolution for the standard path).
    permissions_block: dict[str, dict[str, bool]] = {}
    for pkey in sorted(ALL_PERMISSION_KEYS):
        per_role: dict[str, bool] = {}
        for system_key, role_id in role_id_by_system_key.items():
            per_role[system_key] = rp_index.get((role_id, pkey), False)
        permissions_block[pkey] = per_role

    # Locked map. Currently only Steward; the structure leaves room for
    # future-pass extensions (other roles gaining locked cells).
    locked_block: dict[str, list[str]] = {
        "steward": sorted(STEWARD_LOCKED_PERMISSIONS),
    }

    return {
        "org_id": org.id,
        "org_slug": org.slug,
        "roles": [
            {
                "id": r.id,
                "system_key": r.system_key,
                "name": r.name,
                "display_order": r.display_order,
            }
            for r in roles
        ],
        "permissions": permissions_block,
        "locked": locked_block,
    }


# ---------------------------------------------------------------------------
# B1 — GET matrix
# ---------------------------------------------------------------------------

@router.get("/{org_slug}/role-permissions")
def get_role_permissions(
    org_slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
) -> dict[str, Any]:
    """Return the org's full permission matrix.

    Auth: any authenticated user with active OrgMembership on the org.
    NOT permission-gated — reading the matrix is open to every member;
    only writing requires ``role_permissions.edit``.

    Per spec line 220 ("404 caller not member of org"), non-member
    callers receive a 404 (not 403) — the response intentionally
    doesn't disclose org existence to outsiders.
    """
    org = _resolve_org_or_404(db, org_slug)
    _resolve_active_membership_or_404(db, current_user.id, org.id)
    return _build_matrix_payload(db, org)


# ---------------------------------------------------------------------------
# B2 — PATCH matrix
# ---------------------------------------------------------------------------

@router.patch("/{org_slug}/role-permissions")
def patch_role_permissions(
    org_slug: str,
    body: RolePermissionPatch,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
) -> dict[str, Any]:
    """Apply a list of cell-level matrix changes atomically.

    Auth: ``has_permission(user, org, "role_permissions.edit")``. Bare
    membership is not enough; the caller must have the meta-permission
    (which steward and admin hold by default; moderator and member do
    not, unless an org has reconfigured the matrix).

    Per spec lines 143-156:
      - Validate auth.
      - For each change: reject locked cell (400), reject unknown
        permission_key (400), reject unknown role_system_key (400). Look
        up the org's role row + existing role_permissions row; compare
        enabled to requested.
      - If no real changes (every change already matches state): return
        200 ``{"changes_applied": 0, ...full matrix...}`` and skip audit.
      - Otherwise: apply atomically, emit ONE audit event with the full
        changes payload, return 200 + new matrix.

    Atomicity: one DB transaction. Partial-success isn't a thing — one
    invalid cell rejects the whole request.

    Last-writer-wins on concurrent edits (no version field).
    """
    org = _resolve_org_or_404(db, org_slug)
    membership = _resolve_active_membership_or_404(db, current_user.id, org.id)

    # Permission gate. Note: has_permission consults the caller's role
    # membership, not the membership we just fetched (it does its own
    # lookup), but we've already validated active membership above so
    # the gate's only filter here is the per-cell role_permissions row.
    if not has_permission(
        db, current_user.id, org.id, "role_permissions.edit"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "You do not have permission to edit role permissions in "
                "this organization."
            ),
        )

    # Pre-fetch the org's preset roles for fast lookup. Missing role rows
    # would be a data-integrity bug (Stage 1 seeds all four), so it's
    # safe to fail loudly if one is absent.
    roles = (
        db.query(models.Role)
        .filter(
            models.Role.org_id == org.id,
            models.Role.system_key.in_(list(_PRESET_SYSTEM_KEYS)),
        )
        .all()
    )
    role_by_system_key: dict[str, models.Role] = {
        r.system_key: r for r in roles
    }

    # --- Validate every change before mutating anything ---
    # Building the list of (role, change, current_enabled) tuples for
    # the apply loop, but only after we've passed validation. The whole
    # request 400s on the first invalid cell.
    real_changes: list[dict[str, Any]] = []  # for audit payload
    rows_to_update: list[tuple[models.RolePermission | None, models.Role, RolePermissionChange]] = []

    for change in body.changes:
        # Locked-cell guard.
        if is_locked(change.role_system_key, change.permission_key):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Cannot change '{change.permission_key}' for the "
                    f"Steward role: this permission is locked for the "
                    f"Steward role and cannot be changed."
                ),
            )

        # Permission-key validity.
        if change.permission_key not in ALL_PERMISSION_KEYS:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown permission key: {change.permission_key!r}",
            )

        # Role-key validity.
        if change.role_system_key not in _PRESET_SYSTEM_KEYS:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown role: {change.role_system_key!r}",
            )

        role = role_by_system_key.get(change.role_system_key)
        if role is None:
            # Defensive — Stage 1 seeded all four presets. If a preset is
            # missing for this org, the data is broken; surface as 500
            # (not user error). Treat as a unknown role for safety though.
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Org is missing the preset role "
                    f"{change.role_system_key!r}; please contact support."
                ),
            )

        # Look up the current row (may not exist; missing == False).
        rp_row = (
            db.query(models.RolePermission)
            .filter(
                models.RolePermission.role_id == role.id,
                models.RolePermission.permission_key == change.permission_key,
            )
            .first()
        )
        current_enabled = bool(rp_row.enabled) if rp_row is not None else False

        # Real change only if the requested value differs.
        if current_enabled == change.enabled:
            # No-op for this cell; nothing to apply, no audit entry.
            continue
        real_changes.append({
            "role_system_key": change.role_system_key,
            "permission_key": change.permission_key,
            "old": current_enabled,
            "new": change.enabled,
        })
        rows_to_update.append((rp_row, role, change))

    # --- No-op shortcut (per spec: no audit, no transaction) ---
    if not real_changes:
        return {
            "changes_applied": 0,
            **_build_matrix_payload(db, org),
        }

    # --- Apply atomically. SQLAlchemy session is one transaction; any
    # error before commit rolls everything back. ---
    for rp_row, role, change in rows_to_update:
        if rp_row is None:
            db.add(
                models.RolePermission(
                    role_id=role.id,
                    permission_key=change.permission_key,
                    enabled=change.enabled,
                )
            )
        else:
            rp_row.enabled = change.enabled

    log_audit_event(
        db,
        action="role_permissions.updated",
        target_type="organization",
        target_id=org.id,
        actor_id=current_user.id,
        details={"changes": real_changes},
        ip_address=request.client.host if request.client else None,
    )

    db.commit()

    # Invalidate the per-request permission cache so a follow-up
    # has_permission call in the same request reflects the fresh state.
    # (FastAPI yields a fresh session per request anyway, so cross-request
    # invalidation isn't required; this keeps single-request consistency.)
    db.info.pop("_permission_cache", None)

    return {
        "changes_applied": len(real_changes),
        **_build_matrix_payload(db, org),
    }
