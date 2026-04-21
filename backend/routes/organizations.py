"""
Organization management endpoints — CRUD, membership, invitations,
delegate applications, topics, proposals, and analytics.
"""
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session
from sqlalchemy import func

import auth as auth_utils
import models
import schemas
from audit_utils import log_audit_event
from database import get_db
from org_middleware import (
    get_org_context,
    require_org_membership,
    require_org_moderator_or_admin,
    require_org_admin,
    require_org_owner,
)

router = APIRouter(prefix="/api/orgs", tags=["organizations"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


DEFAULT_ORG_SETTINGS = {
    "default_deliberation_days": 14,
    "default_voting_days": 7,
    "default_pass_threshold": 0.50,
    "default_quorum_threshold": 0.40,
    "allow_public_delegates": True,
    "public_delegate_policy": "admin_approval",
    "require_email_verification": True,
    "sustained_majority_floor": 0.45,
}


def _org_to_out(
    org: models.Organization,
    db: Session,
    user_id: Optional[str] = None,
) -> schemas.OrgOut:
    member_count = db.query(models.OrgMembership).filter(
        models.OrgMembership.org_id == org.id,
        models.OrgMembership.status == "active",
    ).count()

    user_role = None
    if user_id:
        membership = db.query(models.OrgMembership).filter(
            models.OrgMembership.org_id == org.id,
            models.OrgMembership.user_id == user_id,
            models.OrgMembership.status == "active",
        ).first()
        if membership:
            user_role = membership.role

    return schemas.OrgOut(
        id=org.id,
        name=org.name,
        slug=org.slug,
        description=org.description or "",
        join_policy=org.join_policy,
        settings=org.settings or {},
        created_at=org.created_at,
        member_count=member_count,
        user_role=user_role,
    )


# ============================================================================
# Setup Status (first-run experience)
# ============================================================================

@router.get("/setup-status", response_model=schemas.SetupStatusOut)
def setup_status(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Check whether the platform needs initial setup."""
    has_orgs = db.query(models.Organization).count() > 0
    has_topics = db.query(models.Topic).count() > 0
    needs_setup = not has_orgs
    return schemas.SetupStatusOut(
        needs_setup=needs_setup,
        has_orgs=has_orgs,
        has_topics=has_topics,
    )


# ============================================================================
# Organization CRUD
# ============================================================================

@router.post("", response_model=schemas.OrgOut, status_code=status.HTTP_201_CREATED)
def create_organization(
    body: schemas.OrgCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Create a new organization. Creator becomes owner."""
    if db.query(models.Organization).filter(models.Organization.slug == body.slug).first():
        raise HTTPException(status_code=400, detail="Organization slug already taken")

    org = models.Organization(
        name=body.name,
        slug=body.slug,
        description=body.description,
        join_policy=body.join_policy,
        settings=DEFAULT_ORG_SETTINGS.copy(),
    )
    db.add(org)
    db.flush()

    # Creator becomes owner
    membership = models.OrgMembership(
        user_id=current_user.id,
        org_id=org.id,
        role="owner",
        status="active",
    )
    db.add(membership)
    db.flush()

    log_audit_event(
        db,
        action="org.created",
        target_type="organization",
        target_id=org.id,
        actor_id=current_user.id,
        details={"name": org.name, "slug": org.slug},
        ip_address=request.client.host if request.client else None,
    )

    db.commit()
    db.refresh(org)
    return _org_to_out(org, db, current_user.id)


@router.get("", response_model=list[schemas.OrgOut])
def list_my_organizations(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """List organizations the current user is a member of."""
    memberships = db.query(models.OrgMembership).filter(
        models.OrgMembership.user_id == current_user.id,
        models.OrgMembership.status == "active",
    ).all()
    org_ids = [m.org_id for m in memberships]
    if not org_ids:
        return []
    orgs = db.query(models.Organization).filter(
        models.Organization.id.in_(org_ids)
    ).order_by(models.Organization.name).all()
    return [_org_to_out(o, db, current_user.id) for o in orgs]


@router.get("/{org_slug}", response_model=schemas.OrgOut)
def get_organization(
    org_slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """Get org details (requires membership)."""
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return _org_to_out(org, db, current_user.id)


@router.patch("/{org_slug}", response_model=schemas.OrgOut)
def update_organization(
    org_slug: str,
    body: schemas.OrgUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_admin),
):
    """Update org settings (requires admin)."""
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    if body.name is not None:
        org.name = body.name
    if body.description is not None:
        org.description = body.description
    if body.join_policy is not None:
        org.join_policy = body.join_policy
    if body.settings is not None:
        org.settings = {**(org.settings or {}), **body.settings}

    db.commit()
    db.refresh(org)
    return _org_to_out(org, db, current_user.id)


@router.delete("/{org_slug}", status_code=status.HTTP_204_NO_CONTENT)
def delete_organization(
    org_slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_owner),
):
    """Delete org (requires owner)."""
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    db.delete(org)
    db.commit()


# ============================================================================
# Membership Management
# ============================================================================

@router.get("/{org_slug}/members", response_model=list[schemas.OrgMemberOut])
def list_members(
    org_slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """List members (requires membership)."""
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    memberships = db.query(models.OrgMembership).filter(
        models.OrgMembership.org_id == org.id,
    ).all()
    result = []
    for m in memberships:
        user = db.get(models.User, m.user_id)
        if user:
            result.append(schemas.OrgMemberOut(
                user_id=m.user_id,
                username=user.username,
                display_name=user.display_name,
                email=user.email,
                role=m.role,
                status=m.status,
                joined_at=m.joined_at,
            ))
    return result


@router.patch("/{org_slug}/members/{user_id}", response_model=schemas.OrgMemberOut)
def change_member_role(
    org_slug: str,
    user_id: str,
    body: schemas.MemberRoleUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    admin_membership: models.OrgMembership = Depends(require_org_admin),
):
    """Change member role (requires admin)."""
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    m = db.query(models.OrgMembership).filter(
        models.OrgMembership.org_id == org.id,
        models.OrgMembership.user_id == user_id,
    ).first()
    if not m:
        raise HTTPException(status_code=404, detail="Member not found")
    if m.role == "owner":
        raise HTTPException(status_code=400, detail="Cannot change owner role")
    m.role = body.role
    db.commit()
    db.refresh(m)
    user = db.get(models.User, m.user_id)
    return schemas.OrgMemberOut(
        user_id=m.user_id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        role=m.role,
        status=m.status,
        joined_at=m.joined_at,
    )


@router.delete("/{org_slug}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    org_slug: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    admin_membership: models.OrgMembership = Depends(require_org_admin),
):
    """Remove member (requires admin)."""
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    m = db.query(models.OrgMembership).filter(
        models.OrgMembership.org_id == org.id,
        models.OrgMembership.user_id == user_id,
    ).first()
    if not m:
        raise HTTPException(status_code=404, detail="Member not found")
    if m.role == "owner":
        raise HTTPException(status_code=400, detail="Cannot remove the owner")
    db.delete(m)
    db.commit()


@router.post("/{org_slug}/members/{user_id}/suspend", status_code=200)
def suspend_member(
    org_slug: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    admin_membership: models.OrgMembership = Depends(require_org_moderator_or_admin),
):
    """Suspend member (moderator, admin, or owner). Moderators cannot remove members."""
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    m = db.query(models.OrgMembership).filter(
        models.OrgMembership.org_id == org.id,
        models.OrgMembership.user_id == user_id,
    ).first()
    if not m:
        raise HTTPException(status_code=404, detail="Member not found")
    if m.role == "owner":
        raise HTTPException(status_code=400, detail="Cannot suspend the owner")
    m.status = "suspended"
    db.commit()
    return {"message": "Member suspended"}


@router.post("/{org_slug}/members/{user_id}/reactivate", status_code=200)
def reactivate_member(
    org_slug: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    admin_membership: models.OrgMembership = Depends(require_org_admin),
):
    """Reactivate a suspended member (requires admin)."""
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    m = db.query(models.OrgMembership).filter(
        models.OrgMembership.org_id == org.id,
        models.OrgMembership.user_id == user_id,
    ).first()
    if not m:
        raise HTTPException(status_code=404, detail="Member not found")
    if m.status != "suspended":
        raise HTTPException(status_code=400, detail="Member is not suspended")
    m.status = "active"
    db.commit()
    return {"message": "Member reactivated"}


# ============================================================================
# Join Flow
# ============================================================================

@router.post("/{org_slug}/join", status_code=200)
def request_join(
    org_slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Request to join (for approval_required/open orgs)."""
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    if org.join_policy == "invite_only":
        raise HTTPException(status_code=403, detail="This organization is invite-only")

    existing = db.query(models.OrgMembership).filter(
        models.OrgMembership.org_id == org.id,
        models.OrgMembership.user_id == current_user.id,
    ).first()
    if existing:
        if existing.status == "active":
            raise HTTPException(status_code=409, detail="Already a member")
        if existing.status == "pending_approval":
            raise HTTPException(status_code=409, detail="Join request already pending")

    if org.join_policy == "open":
        membership = models.OrgMembership(
            user_id=current_user.id,
            org_id=org.id,
            role="member",
            status="active",
        )
        db.add(membership)
        db.commit()
        return {"message": "You have joined the organization", "status": "active"}
    else:
        # approval_required
        membership = models.OrgMembership(
            user_id=current_user.id,
            org_id=org.id,
            role="member",
            status="pending_approval",
        )
        db.add(membership)
        db.commit()
        return {"message": "Join request submitted, awaiting admin approval", "status": "pending_approval"}


@router.post("/{org_slug}/join/approve/{user_id}", status_code=200)
def approve_join_request(
    org_slug: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    admin_membership: models.OrgMembership = Depends(require_org_moderator_or_admin),
):
    """Approve join request (moderator, admin, or owner)."""
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    m = db.query(models.OrgMembership).filter(
        models.OrgMembership.org_id == org.id,
        models.OrgMembership.user_id == user_id,
        models.OrgMembership.status == "pending_approval",
    ).first()
    if not m:
        raise HTTPException(status_code=404, detail="Pending join request not found")
    m.status = "active"
    m.joined_at = _now()
    db.commit()
    return {"message": "Join request approved"}


@router.post("/{org_slug}/join/deny/{user_id}", status_code=200)
def deny_join_request(
    org_slug: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    admin_membership: models.OrgMembership = Depends(require_org_admin),
):
    """Deny join request (admin)."""
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    m = db.query(models.OrgMembership).filter(
        models.OrgMembership.org_id == org.id,
        models.OrgMembership.user_id == user_id,
        models.OrgMembership.status == "pending_approval",
    ).first()
    if not m:
        raise HTTPException(status_code=404, detail="Pending join request not found")
    db.delete(m)
    db.commit()
    return {"message": "Join request denied"}


# ============================================================================
# Invitations
# ============================================================================

@router.post("/{org_slug}/invitations", response_model=list[schemas.InvitationOut], status_code=201)
def create_invitations(
    org_slug: str,
    body: schemas.InvitationCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    admin_membership: models.OrgMembership = Depends(require_org_admin),
):
    """Send invitations (admin). Body: {emails: string[], role: string}"""
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    invitations = []
    for email in body.emails:
        token = secrets.token_urlsafe(48)
        inv = models.Invitation(
            org_id=org.id,
            email=email.strip().lower(),
            invited_by=current_user.id,
            role=body.role,
            token=token,
            expires_at=_now() + timedelta(days=7),
        )
        db.add(inv)
        db.flush()
        invitations.append(inv)

    db.commit()
    return [schemas.InvitationOut(
        id=inv.id,
        email=inv.email,
        role=inv.role,
        status=inv.status,
        expires_at=inv.expires_at,
        created_at=inv.created_at,
    ) for inv in invitations]


@router.get("/{org_slug}/invitations", response_model=list[schemas.InvitationOut])
def list_invitations(
    org_slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    admin_membership: models.OrgMembership = Depends(require_org_admin),
):
    """List invitations (admin)."""
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    invitations = db.query(models.Invitation).filter(
        models.Invitation.org_id == org.id,
    ).order_by(models.Invitation.created_at.desc()).all()
    return [schemas.InvitationOut(
        id=inv.id,
        email=inv.email,
        role=inv.role,
        status=inv.status,
        expires_at=inv.expires_at,
        created_at=inv.created_at,
    ) for inv in invitations]


@router.delete("/{org_slug}/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_invitation(
    org_slug: str,
    invitation_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    admin_membership: models.OrgMembership = Depends(require_org_admin),
):
    """Revoke invitation (admin)."""
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    inv = db.query(models.Invitation).filter(
        models.Invitation.id == invitation_id,
        models.Invitation.org_id == org.id,
    ).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invitation not found")
    inv.status = "revoked"
    db.commit()


@router.post("/{org_slug}/invitations/{invitation_id}/resend", status_code=200)
def resend_invitation(
    org_slug: str,
    invitation_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    admin_membership: models.OrgMembership = Depends(require_org_admin),
):
    """Resend invitation (admin) — generates a new token and extends expiry."""
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    inv = db.query(models.Invitation).filter(
        models.Invitation.id == invitation_id,
        models.Invitation.org_id == org.id,
    ).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invitation not found")
    inv.token = secrets.token_urlsafe(48)
    inv.expires_at = _now() + timedelta(days=7)
    inv.status = "pending"
    db.commit()
    return {"message": "Invitation resent"}


# Accept invitation (public, auth not required — creates account or adds to org)
@router.post("/join/{token}", status_code=200)
def accept_invitation(
    token: str,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(auth_utils.get_optional_user),
):
    """Accept invitation by token. Requires authenticated user."""
    inv = db.query(models.Invitation).filter(
        models.Invitation.token == token,
        models.Invitation.status == "pending",
    ).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invalid or expired invitation")
    if inv.expires_at < _now():
        inv.status = "expired"
        db.commit()
        raise HTTPException(status_code=400, detail="Invitation has expired")

    if not current_user:
        raise HTTPException(
            status_code=401,
            detail="Please register or log in first, then use this invitation link"
        )

    # Check if already a member
    existing = db.query(models.OrgMembership).filter(
        models.OrgMembership.org_id == inv.org_id,
        models.OrgMembership.user_id == current_user.id,
    ).first()
    if existing:
        if existing.status == "active":
            raise HTTPException(status_code=409, detail="Already a member of this organization")
        existing.status = "active"
        existing.role = inv.role
    else:
        db.add(models.OrgMembership(
            user_id=current_user.id,
            org_id=inv.org_id,
            role=inv.role,
            status="active",
        ))

    inv.status = "accepted"
    inv.accepted_at = _now()
    db.commit()

    org = db.get(models.Organization, inv.org_id)
    return {"message": f"You have joined {org.name}", "org_slug": org.slug}


# ============================================================================
# Delegate Applications
# ============================================================================

@router.post("/{org_slug}/delegate-applications", response_model=schemas.DelegateApplicationOut, status_code=201)
def submit_delegate_application(
    org_slug: str,
    body: schemas.DelegateApplicationCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """Submit application to become a public delegate (member)."""
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()

    topic = db.get(models.Topic, body.topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    # Check if already has a pending application
    existing = db.query(models.DelegateApplication).filter(
        models.DelegateApplication.user_id == current_user.id,
        models.DelegateApplication.org_id == org.id,
        models.DelegateApplication.topic_id == body.topic_id,
        models.DelegateApplication.status == "pending",
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Application already pending for this topic")

    app = models.DelegateApplication(
        user_id=current_user.id,
        org_id=org.id,
        topic_id=body.topic_id,
        bio=body.bio,
    )
    db.add(app)
    db.commit()
    db.refresh(app)
    return schemas.DelegateApplicationOut(
        id=app.id,
        user_id=app.user_id,
        username=current_user.username,
        display_name=current_user.display_name,
        topic_id=app.topic_id,
        topic_name=topic.name,
        bio=app.bio,
        status=app.status,
        feedback=app.feedback,
        created_at=app.created_at,
    )


@router.get("/{org_slug}/delegate-applications", response_model=list[schemas.DelegateApplicationOut])
def list_delegate_applications(
    org_slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    admin_membership: models.OrgMembership = Depends(require_org_admin),
):
    """List pending applications (admin)."""
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    apps = db.query(models.DelegateApplication).filter(
        models.DelegateApplication.org_id == org.id,
        models.DelegateApplication.status == "pending",
    ).order_by(models.DelegateApplication.created_at.desc()).all()

    result = []
    for app in apps:
        user = db.get(models.User, app.user_id)
        topic = db.get(models.Topic, app.topic_id)
        result.append(schemas.DelegateApplicationOut(
            id=app.id,
            user_id=app.user_id,
            username=user.username if user else "",
            display_name=user.display_name if user else "",
            topic_id=app.topic_id,
            topic_name=topic.name if topic else "",
            bio=app.bio,
            status=app.status,
            feedback=app.feedback,
            created_at=app.created_at,
        ))
    return result


@router.post("/{org_slug}/delegate-applications/{app_id}/approve", status_code=200)
def approve_delegate_application(
    org_slug: str,
    app_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    admin_membership: models.OrgMembership = Depends(require_org_admin),
):
    """Approve delegate application (admin)."""
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    app = db.query(models.DelegateApplication).filter(
        models.DelegateApplication.id == app_id,
        models.DelegateApplication.org_id == org.id,
    ).first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    if app.status != "pending":
        raise HTTPException(status_code=400, detail=f"Application is already {app.status}")

    app.status = "approved"
    app.reviewed_by = current_user.id
    app.reviewed_at = _now()
    db.flush()

    # Create or activate the delegate profile
    existing_profile = db.query(models.DelegateProfile).filter(
        models.DelegateProfile.user_id == app.user_id,
        models.DelegateProfile.topic_id == app.topic_id,
    ).first()
    if existing_profile:
        existing_profile.is_active = True
        existing_profile.bio = app.bio
        existing_profile.org_id = org.id
    else:
        profile = models.DelegateProfile(
            user_id=app.user_id,
            topic_id=app.topic_id,
            org_id=org.id,
            bio=app.bio,
            is_active=True,
        )
        db.add(profile)

    log_audit_event(
        db,
        action="delegate_application.approved",
        target_type="delegate_application",
        target_id=app.id,
        actor_id=current_user.id,
        details={"user_id": app.user_id, "topic_id": app.topic_id},
    )
    db.commit()
    return {"message": "Application approved, delegate profile activated"}


@router.post("/{org_slug}/delegate-applications/{app_id}/deny", status_code=200)
def deny_delegate_application(
    org_slug: str,
    app_id: str,
    body: schemas.DelegateApplicationReview,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    admin_membership: models.OrgMembership = Depends(require_org_admin),
):
    """Deny delegate application with optional feedback (admin)."""
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    app = db.query(models.DelegateApplication).filter(
        models.DelegateApplication.id == app_id,
        models.DelegateApplication.org_id == org.id,
    ).first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    if app.status != "pending":
        raise HTTPException(status_code=400, detail=f"Application is already {app.status}")

    app.status = "denied"
    app.feedback = body.feedback
    app.reviewed_by = current_user.id
    app.reviewed_at = _now()

    log_audit_event(
        db,
        action="delegate_application.denied",
        target_type="delegate_application",
        target_id=app.id,
        actor_id=current_user.id,
        details={"user_id": app.user_id, "topic_id": app.topic_id, "feedback": body.feedback},
    )
    db.commit()
    return {"message": "Application denied"}


# ============================================================================
# Topics (org-scoped)
# ============================================================================

@router.get("/{org_slug}/topics", response_model=list[schemas.TopicOut])
def list_org_topics(
    org_slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """List org topics."""
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    return db.query(models.Topic).filter(
        models.Topic.org_id == org.id,
    ).order_by(models.Topic.name).all()


@router.post("/{org_slug}/topics", response_model=schemas.TopicOut, status_code=201)
def create_org_topic(
    org_slug: str,
    body: schemas.TopicCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    admin_membership: models.OrgMembership = Depends(require_org_admin),
):
    """Create topic (admin)."""
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()

    # Check for duplicate name within the org
    existing = db.query(models.Topic).filter(
        models.Topic.org_id == org.id,
        models.Topic.name == body.name,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Topic name already exists in this organization")

    topic = models.Topic(
        name=body.name,
        description=body.description,
        color=body.color,
        org_id=org.id,
    )
    db.add(topic)
    db.commit()
    db.refresh(topic)
    return topic


@router.patch("/{org_slug}/topics/{topic_id}", response_model=schemas.TopicOut)
def update_org_topic(
    org_slug: str,
    topic_id: str,
    body: schemas.TopicCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    admin_membership: models.OrgMembership = Depends(require_org_moderator_or_admin),
):
    """Update topic (moderator, admin, or owner). Delete requires admin."""
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    topic = db.query(models.Topic).filter(
        models.Topic.id == topic_id,
        models.Topic.org_id == org.id,
    ).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found in this organization")

    topic.name = body.name
    topic.description = body.description
    topic.color = body.color
    db.commit()
    db.refresh(topic)
    return topic


@router.delete("/{org_slug}/topics/{topic_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_org_topic(
    org_slug: str,
    topic_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    admin_membership: models.OrgMembership = Depends(require_org_admin),
):
    """Deactivate topic (admin) — soft-delete by removing org association."""
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    topic = db.query(models.Topic).filter(
        models.Topic.id == topic_id,
        models.Topic.org_id == org.id,
    ).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found in this organization")
    topic.org_id = None  # soft-deactivate
    db.commit()


# ============================================================================
# Proposals (org-scoped)
# ============================================================================

@router.get("/{org_slug}/proposals", response_model=list[schemas.ProposalOut])
def list_org_proposals(
    org_slug: str,
    status_filter: Optional[str] = Query(None, alias="status"),
    topic_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """List org proposals."""
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    q = db.query(models.Proposal).filter(models.Proposal.org_id == org.id)
    if status_filter:
        q = q.filter(models.Proposal.status == status_filter)
    if topic_id:
        q = q.join(models.ProposalTopic).filter(models.ProposalTopic.topic_id == topic_id)
    proposals = q.order_by(models.Proposal.created_at.desc()).all()

    from routes.proposals import _build_proposal_out
    return [_build_proposal_out(p) for p in proposals]


@router.post("/{org_slug}/proposals", response_model=schemas.ProposalOut, status_code=201)
def create_org_proposal(
    org_slug: str,
    body: schemas.ProposalCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    admin_membership: models.OrgMembership = Depends(require_org_moderator_or_admin),
):
    """Create proposal within org (moderator, admin, or owner)."""
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()

    for t in body.topics:
        if not db.get(models.Topic, t.topic_id):
            raise HTTPException(status_code=400, detail=f"Topic {t.topic_id} not found")

    proposal = models.Proposal(
        title=body.title,
        body=body.body,
        author_id=current_user.id,
        org_id=org.id,
        pass_threshold=body.pass_threshold,
        quorum_threshold=body.quorum_threshold,
    )
    db.add(proposal)
    db.flush()

    for t in body.topics:
        db.add(models.ProposalTopic(
            proposal_id=proposal.id, topic_id=t.topic_id, relevance=t.relevance
        ))
    db.flush()

    log_audit_event(
        db,
        action="proposal.created",
        target_type="proposal",
        target_id=proposal.id,
        actor_id=current_user.id,
        details={"title": proposal.title, "org_id": org.id},
        ip_address=request.client.host if request.client else None,
    )

    db.commit()
    db.refresh(proposal)
    from routes.proposals import _build_proposal_out
    return _build_proposal_out(proposal)


@router.get("/{org_slug}/proposals/{proposal_id}", response_model=schemas.ProposalOut)
def get_org_proposal(
    org_slug: str,
    proposal_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """Get proposal detail within org context."""
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    proposal = db.query(models.Proposal).filter(
        models.Proposal.id == proposal_id,
        models.Proposal.org_id == org.id,
    ).first()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found in this organization")
    from routes.proposals import _build_proposal_out
    return _build_proposal_out(proposal)


# ============================================================================
# Analytics (admin)
# ============================================================================

@router.get("/{org_slug}/analytics", response_model=schemas.AnalyticsOut)
def get_org_analytics(
    org_slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    admin_membership: models.OrgMembership = Depends(require_org_admin),
):
    """Get org analytics data."""
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()

    # Member counts
    active_count = db.query(models.OrgMembership).filter(
        models.OrgMembership.org_id == org.id,
        models.OrgMembership.status == "active",
    ).count()

    # Proposals in this org
    proposals = db.query(models.Proposal).filter(
        models.Proposal.org_id == org.id,
    ).all()

    total_proposals = len(proposals)
    passed = sum(1 for p in proposals if p.status == "passed")
    failed = sum(1 for p in proposals if p.status == "failed")
    voting = sum(1 for p in proposals if p.status == "voting")

    # Delegation patterns
    # Count members who have delegations on org topics
    org_topic_ids = [t.id for t in db.query(models.Topic).filter(
        models.Topic.org_id == org.id
    ).all()]

    delegating_members = 0
    if org_topic_ids:
        delegating_members = db.query(models.Delegation.delegator_id).filter(
            models.Delegation.topic_id.in_(org_topic_ids),
        ).distinct().count()

    # Participation rates per proposal
    participation_rates = []
    for p in proposals:
        if p.status in ("voting", "passed", "failed"):
            vote_count = db.query(models.Vote).filter(
                models.Vote.proposal_id == p.id,
            ).count()
            rate = vote_count / active_count if active_count > 0 else 0
            participation_rates.append({
                "proposal_id": p.id,
                "title": p.title,
                "status": p.status,
                "participation_rate": round(rate, 4),
                "vote_count": vote_count,
                "eligible": active_count,
            })

    return schemas.AnalyticsOut(
        participation_rates=participation_rates,
        delegation_patterns={
            "total_members": active_count,
            "members_delegating": delegating_members,
            "delegation_rate": round(delegating_members / active_count, 4) if active_count > 0 else 0,
        },
        proposal_outcomes={
            "total": total_proposals,
            "passed": passed,
            "failed": failed,
            "voting": voting,
            "pass_rate": round(passed / (passed + failed), 4) if (passed + failed) > 0 else 0,
        },
        active_members={
            "total": active_count,
        },
    )
