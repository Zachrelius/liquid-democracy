"""Middleware to extract and validate org context from URL path."""
from fastapi import Request, HTTPException, Depends
from sqlalchemy.orm import Session
from database import get_db
from models import Organization, OrgMembership
from auth import get_current_user
import models


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


async def require_org_admin(
    membership: OrgMembership = Depends(require_org_membership),
):
    """Verify current user is an admin or owner of the org."""
    if membership.role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return membership


async def require_org_owner(
    membership: OrgMembership = Depends(require_org_membership),
):
    """Verify current user is the owner of the org."""
    if membership.role != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")
    return membership
