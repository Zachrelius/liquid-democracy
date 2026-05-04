"""Middleware to extract and validate org context from URL path.

Phase 12 Stage 1 — the role-tier dependencies (``require_org_admin`` etc.)
were rewritten to inspect ``OrgMembership.role.system_key`` after the
``OrgMembership.role`` string column was migrated to an FK to ``roles.id``.
The dependency contract (yields the OrgMembership row when the caller
clears the tier check, raises 403 otherwise) is unchanged. The fine-
grained per-action permission checks live in
``role_permissions.has_permission`` and are now invoked at the call site
rather than via the coarse dependency.
"""
from typing import Optional

from fastapi import Request, HTTPException, Depends
from sqlalchemy.orm import Session
from database import get_db
from models import Organization, OrgMembership, Role
from auth import get_current_user
import models


# Role.system_key sets used by the legacy "tier" dependencies.
# These are the renamed-from-"owner" preset rows; 'owner' no longer exists
# as a system_key after the Phase 12 migration.
_ADMIN_TIER_SYSTEM_KEYS: frozenset[str] = frozenset({"admin", "steward"})
_MODERATOR_TIER_SYSTEM_KEYS: frozenset[str] = frozenset(
    {"moderator", "admin", "steward"}
)
_STEWARD_SYSTEM_KEY: str = "steward"


def membership_role_system_key(
    membership: Optional[OrgMembership],
) -> Optional[str]:
    """Return ``membership.role.system_key`` defensively (None if no role).

    Used by serialization paths and the tier dependencies to avoid the
    ``AttributeError: 'NoneType' object has no attribute 'system_key'``
    foot-gun on rows whose role_id was somehow not backfilled.
    """
    if membership is None or membership.role is None:
        return None
    return membership.role.system_key


async def get_org_context(request: Request, db: Session = Depends(get_db)):
    """Extract org_slug from path and resolve to Organization."""
    org_slug = request.path_params.get("org_slug")
    if not org_slug:
        return None
    org = db.query(Organization).filter(Organization.slug == org_slug).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


async def require_org_membership(
    org: Organization = Depends(get_org_context),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Verify current user is an active member of the org."""
    if not org:
        raise HTTPException(status_code=400, detail="Organization context required")
    membership = db.query(OrgMembership).filter(
        OrgMembership.user_id == current_user.id,
        OrgMembership.org_id == org.id,
        OrgMembership.status == "active",
    ).first()
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this organization")
    return membership


async def require_org_moderator_or_admin(
    membership: OrgMembership = Depends(require_org_membership),
):
    """Verify current user is in the moderator-or-better tier (moderator,
    admin, or steward).

    Phase 12 — coarse tier check; per-action permissions are checked at
    call sites via ``has_permission``. Kept as a Depends() so existing
    routes that gate on "membership tier" don't need a wholesale rewrite.
    """
    if membership_role_system_key(membership) not in _MODERATOR_TIER_SYSTEM_KEYS:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to perform this action in this organization.",
        )
    return membership


async def require_org_admin(
    membership: OrgMembership = Depends(require_org_membership),
):
    """Verify current user is in the admin-or-better tier (admin, steward).

    Phase 12 — coarse tier check; per-action permissions are checked at
    call sites via ``has_permission``.
    """
    if membership_role_system_key(membership) not in _ADMIN_TIER_SYSTEM_KEYS:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to perform this action in this organization.",
        )
    return membership


async def require_org_owner(
    membership: OrgMembership = Depends(require_org_membership),
):
    """Verify current user is the Steward of the org (Phase 12 — renamed
    from 'owner').

    Used by ``org.delete`` and ``org.transfer_stewardship`` — D4 hardcoded
    gates that bypass the configurable permission system.
    """
    if membership_role_system_key(membership) != _STEWARD_SYSTEM_KEY:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to perform this action in this organization.",
        )
    return membership
