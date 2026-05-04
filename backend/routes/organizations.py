"""
Organization management endpoints — CRUD, membership, invitations,
delegate applications, topics, proposals, and analytics.
"""
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session
from sqlalchemy import func

import auth as auth_utils
import models
import schemas
from audit_utils import log_audit_event
from database import get_db
from email_service import send_invitation_email
from org_config import get_default_proposal_thresholds, get_org_config
from permission_registry import PERMISSION_REGISTRY
from reserved_slugs import RESERVED_SLUGS
from role_permissions import has_permission
from role_seed import seed_default_roles_for_org
from settings import settings as app_settings
from org_middleware import (
    get_org_context,
    membership_role_system_key,
    require_org_membership,
    require_org_moderator_or_admin,
    require_org_admin,
    require_org_owner,
)


def _resolve_role_id_by_system_key(
    db: Session, org_id: str, system_key: str,
) -> Optional[str]:
    """Phase 12 — find an org's preset Role row by system_key.

    Used by membership-construction code paths (registration auto-join,
    invitation acceptance, join-request approval). Returns None if the
    role doesn't exist; callers can raise or fall back as appropriate.
    """
    role = (
        db.query(models.Role)
        .filter(
            models.Role.org_id == org_id,
            models.Role.system_key == system_key,
        )
        .first()
    )
    return role.id if role else None


# Translate legacy invitation role strings to the new system_keys.
# Invitations.role keeps a string column per spec ('member' / 'admin'); the
# 'owner' value never appears in invitations historically.
_INV_ROLE_TO_SYSTEM_KEY: dict[str, str] = {
    "owner": "steward",
    "steward": "steward",
    "admin": "admin",
    "moderator": "moderator",
    "member": "member",
}

router = APIRouter(prefix="/api/orgs", tags=["organizations"])


def _now() -> datetime:
    """Naive UTC datetime — SQLite strips timezone info on storage, so
    comparisons between stored and fresh values must both be naive."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


DEFAULT_ORG_SETTINGS = {
    "default_deliberation_days": 14,
    "default_voting_days": 7,
    "default_pass_threshold": 0.50,
    "default_quorum_threshold": 0.40,
    "allow_public_delegates": True,
    "public_delegate_policy": "admin_approval",
    "require_email_verification": True,
    "allowed_voting_methods": ["binary", "approval"],
    # Phase 8 — sustained-majority voting windows. All defaults off / fail-safe
    # so existing orgs see no behavior change until an admin flips the switch.
    # `get_sustained_majority_config()` lazy-applies these values when an org
    # was created before Phase 8 and lacks the keys.
    "sustained_majority_enabled_default": False,
    "sustained_majority_per_proposal_override": True,
    "sustained_majority_threshold": 0.50,
    "sustained_majority_floor": 0.45,
    "sustained_majority_failure_mode": "fail",
    # Phase 9 Decision 7 — opt-in "every new proposal must link a Polis"
    # governance norm. Default off; sub-orgs inherit via get_org_config.
    # When True, the proposal-creation route requires at least one valid
    # linked_polis_id; when False, linking is optional. Always opt-in:
    # most small-org decisions (meeting times, budget allocations under $X)
    # don't need structured deliberation.
    "require_polis_for_new_proposals": False,
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
    membership = None
    if user_id:
        membership = db.query(models.OrgMembership).filter(
            models.OrgMembership.org_id == org.id,
            models.OrgMembership.user_id == user_id,
            models.OrgMembership.status == "active",
        ).first()
        # Phase 12 — emit role.system_key (stable string, e.g. 'steward')
        # rather than the dropped string column. Frontend reads this.
        user_role = membership_role_system_key(membership)

    # Phase 12.5 — resolved permission set for the current user on this
    # org. Stage 1's per-request cache makes the 25 has_permission calls
    # cheap: the first call loads the full grant set (1 SELECT against
    # role_permissions); the remaining 24 are dict lookups. Non-members
    # get []; the Decision-6 implicit-power path is handled inside
    # has_permission so a parent-org admin viewing a sub-org enumerates
    # the full set as expected.
    user_permissions: list[str] = []
    if user_id and membership is not None:
        for perm_def in PERMISSION_REGISTRY:
            if has_permission(db, user_id, org.id, perm_def.key):
                user_permissions.append(perm_def.key)

    # Phase 12.7 B4 — always emit a branding object on org responses.
    # Reads from Organization.settings.branding (a JSON sub-dict written
    # by the PATCH /branding and POST /logo endpoints). Absent or partial
    # values become explicit nulls in the response so the frontend's
    # branding-application logic doesn't have to handle "key missing"
    # vs. "value None" separately. accent_auto_derived defaults to False
    # for type consistency when no branding is configured.
    branding_dict = (org.settings or {}).get("branding") or {}
    branding_out = schemas.BrandingOut(
        logo_url=branding_dict.get("logo_url"),
        primary_color=branding_dict.get("primary_color"),
        accent_color=branding_dict.get("accent_color"),
        accent_auto_derived=bool(branding_dict.get("accent_auto_derived", False)),
    )

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
        user_permissions=user_permissions,
        branding=branding_out,
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

# Phase 9.5 — org-creation gate constants. Centralized so admin endpoints
# and tests can reference them without scattering literals.
DEFAULT_PER_USER_ORG_LIMIT = 3
PLATFORM_HOURLY_ORG_RATE_LIMIT = 20


@router.post("", response_model=schemas.OrgOut, status_code=status.HTTP_201_CREATED)
def create_organization(
    body: schemas.OrgCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Create a new organization. Creator becomes owner.

    Phase 9.5 — gates run in this order; the frontend keys off both
    status code and detail text:

      1. Platform kill switch (`platform_settings.org_creation_mode`).
         When `'approval_required'`, return 403.
      2. Email-verification check (Layer 1 spam filter). 403 when False.
      3. Per-user lifetime cap (Layer 1.5). Effective limit is
         `current_user.org_creation_limit` if set else 3. Counts owned orgs
         (`OrgMembership.role == 'owner'`). 403 when count >= limit.
      4. Platform-wide hourly rate limit (Layer 3). Counts `org.created`
         audit events in the past hour. 429 when count >= 20 (transient,
         not 403).

    On success, audit `org.created` with enriched details:
      - `creator_email_verified_age_seconds`  int seconds since the user's
        EmailVerification.verified_at (latest successful), or None.
      - `platform_org_creation_hour_count`    same count from gate 4,
        captured pre-insert post-validation.
      - `creator_user_agent`                  request header verbatim.
    """
    # Gate 1 — platform mode (kill switch)
    mode_row = db.get(models.PlatformSetting, "org_creation_mode")
    org_creation_mode = mode_row.value if mode_row is not None else "open"
    if org_creation_mode == "approval_required":
        raise HTTPException(
            status_code=403,
            detail=(
                "Org creation is temporarily paused — please contact "
                "support@liquiddemocracy.us"
            ),
        )

    # Gate 2 — email verification
    if not current_user.email_verified:
        raise HTTPException(
            status_code=403,
            detail="Please verify your email before creating an organization",
        )

    # Gate 3 — per-user cap
    # Phase 12 Stage 1: ``OrgMembership.role`` is now an FK to ``roles.id``;
    # we identify "owner-equivalent" memberships by joining to the role row
    # whose ``system_key`` is ``'steward'`` (the renamed-from-"owner" preset).
    effective_limit = (
        current_user.org_creation_limit
        if current_user.org_creation_limit is not None
        else DEFAULT_PER_USER_ORG_LIMIT
    )
    owned_count = (
        db.query(models.OrgMembership)
        .join(models.Role, models.Role.id == models.OrgMembership.role_id)
        .filter(
            models.OrgMembership.user_id == current_user.id,
            models.Role.system_key == "steward",
        )
        .count()
    )
    if owned_count >= effective_limit:
        raise HTTPException(
            status_code=403,
            detail=(
                f"You have created the maximum number of organizations "
                f"({effective_limit}). Contact support@liquiddemocracy.us "
                f"if you need more."
            ),
        )

    # Gate 4 — platform-wide hourly rate limit
    one_hour_ago = _now() - timedelta(hours=1)
    hour_count = db.query(models.AuditLog).filter(
        models.AuditLog.action == "org.created",
        models.AuditLog.timestamp > one_hour_ago,
    ).count()
    if hour_count >= PLATFORM_HOURLY_ORG_RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=(
                "The platform is processing many organization-creation "
                "requests right now — please try again in a few minutes."
            ),
        )

    # Phase 11 B1: reserved-words check. Slugs at /{slug}/... cannot
    # collide with the frontend's top-level routes (marketing, auth,
    # onboarding, user-scoped pages). Run before the uniqueness check so
    # the validation message is specific even if no row exists yet.
    if body.slug.lower() in RESERVED_SLUGS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"The slug '{body.slug}' is reserved and cannot be used. "
                "Please pick a different one."
            ),
        )

    # Slug-uniqueness check stays as a 400 (validation, not a gate).
    if db.query(models.Organization).filter(models.Organization.slug == body.slug).first():
        raise HTTPException(status_code=400, detail="Organization slug already taken")

    # Compute audit-enrichment values BEFORE inserting the new audit row so
    # `platform_org_creation_hour_count` reflects the pre-insert population.
    verified_age_seconds: Optional[int] = None
    latest_verification = db.query(models.EmailVerification).filter(
        models.EmailVerification.user_id == current_user.id,
        models.EmailVerification.verified_at.isnot(None),
    ).order_by(models.EmailVerification.verified_at.desc()).first()
    if latest_verification and latest_verification.verified_at:
        verified_age_seconds = int(
            (_now() - latest_verification.verified_at).total_seconds()
        )

    user_agent = request.headers.get("user-agent", "")

    org = models.Organization(
        name=body.name,
        slug=body.slug,
        description=body.description,
        join_policy=body.join_policy,
        settings=DEFAULT_ORG_SETTINGS.copy(),
    )
    db.add(org)
    db.flush()

    # Phase 12 Stage 1: seed the four preset Role rows + their default
    # RolePermission grants for this brand-new org BEFORE creating the
    # creator's OrgMembership (so we have a Steward role to point role_id at).
    roles_by_key = seed_default_roles_for_org(db, org.id)

    # Creator becomes Steward (the renamed-from-"owner" top-tier role).
    membership = models.OrgMembership(
        user_id=current_user.id,
        org_id=org.id,
        role_id=roles_by_key["steward"].id,
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
        details={
            "name": org.name,
            "slug": org.slug,
            "creator_email_verified_age_seconds": verified_age_seconds,
            "platform_org_creation_hour_count": hour_count,
            "creator_user_agent": user_agent,
        },
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
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_admin),
):
    """Update org settings (requires admin).

    When the patch touches any of the five sustained-majority keys, we emit a
    focused `org.sustained_majority_config_changed` audit event listing only
    the keys that actually changed, so the audit log stays signal-rich.
    """
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
        from sustained_majority_service import diff_sustained_majority_settings
        # Phase 12.5 — validate default-threshold keys (F4 backend support).
        # Range 0.0-1.0 inclusive; no hard floor per spec Q2 decision. The
        # check happens BEFORE the merge so an invalid value fails the
        # whole PATCH cleanly, matching how Pydantic field-level validation
        # would reject other settings keys.
        threshold_keys = {
            "default_pass_threshold", "default_quorum_threshold",
        }
        for tkey in threshold_keys & set(body.settings.keys()):
            tval = body.settings[tkey]
            if not isinstance(tval, (int, float)) or isinstance(tval, bool):
                raise HTTPException(
                    status_code=400,
                    detail=f"{tkey} must be a number between 0.0 and 1.0",
                )
            if tval < 0.0 or tval > 1.0:
                raise HTTPException(
                    status_code=400,
                    detail=f"{tkey} must be between 0.0 and 1.0 inclusive",
                )

        # Diff BEFORE merging so we capture the actual transition.
        sm_diff = diff_sustained_majority_settings(org.settings, body.settings)
        # Phase 12.5 — capture default-threshold transitions for the audit
        # log. Only emit when the value actually changes (no spurious
        # events on no-op patches).
        threshold_diff: dict[str, dict] = {}
        old_settings = org.settings or {}
        for tkey in threshold_keys & set(body.settings.keys()):
            old_val = old_settings.get(tkey)
            new_val = body.settings[tkey]
            if old_val != new_val:
                threshold_diff[tkey] = {"old": old_val, "new": new_val}

        org.settings = {**(org.settings or {}), **body.settings}
        if sm_diff:
            log_audit_event(
                db,
                action="org.sustained_majority_config_changed",
                target_type="organization",
                target_id=org.id,
                actor_id=current_user.id,
                details={"changes": sm_diff},
                ip_address=request.client.host if request.client else None,
            )
        if threshold_diff:
            log_audit_event(
                db,
                action="org.default_thresholds_changed",
                target_type="organization",
                target_id=org.id,
                actor_id=current_user.id,
                details={"changes": threshold_diff},
                ip_address=request.client.host if request.client else None,
            )

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
                avatar_url=user.avatar_url,
                # Phase 12 — emit role.system_key (e.g. 'steward', 'admin');
                # the dropped string column would surface a Role ORM object.
                role=membership_role_system_key(m) or "member",
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
    # Phase 12 — Steward (renamed from 'owner') is protected from
    # role-change via this endpoint; reassignment is its own flow.
    if membership_role_system_key(m) == "steward":
        raise HTTPException(status_code=400, detail="Cannot change Steward role")
    new_role_id = _resolve_role_id_by_system_key(
        db, org.id, _INV_ROLE_TO_SYSTEM_KEY.get(body.role, body.role),
    )
    if new_role_id is None:
        raise HTTPException(status_code=400, detail=f"Unknown role '{body.role}'")
    m.role_id = new_role_id
    db.commit()
    db.refresh(m)
    user = db.get(models.User, m.user_id)
    return schemas.OrgMemberOut(
        user_id=m.user_id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        avatar_url=user.avatar_url,
        role=membership_role_system_key(m) or "member",
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
    # Phase 12 — Steward (renamed from 'owner') cannot be removed.
    if membership_role_system_key(m) == "steward":
        raise HTTPException(status_code=400, detail="Cannot remove the Steward")
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
    # Phase 12 — Steward (renamed from 'owner') cannot be suspended.
    if membership_role_system_key(m) == "steward":
        raise HTTPException(status_code=400, detail="Cannot suspend the Steward")
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

    # Phase 12 — defensively seed preset roles for the org if missing
    # (production orgs are seeded at create time and via the migration; this
    # is belt-and-suspenders for legacy data paths).
    member_role_id = _resolve_role_id_by_system_key(db, org.id, "member")
    if member_role_id is None:
        seed_default_roles_for_org(db, org.id)
        member_role_id = _resolve_role_id_by_system_key(db, org.id, "member")

    if org.join_policy == "open":
        membership = models.OrgMembership(
            user_id=current_user.id,
            org_id=org.id,
            role_id=member_role_id,
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
            role_id=member_role_id,
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
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    admin_membership: models.OrgMembership = Depends(require_org_admin),
):
    """Send invitations (admin). Body: {emails: string[], role: string}

    Phase 9.6 W1 fix: previously created the Invitation DB row but never
    called send_invitation_email — invitations appeared in the admin list
    but no email ever went out. Email send now fires via BackgroundTasks
    (post-response, same pattern as registration verification in
    routes/auth.py) so the API stays fast and a Resend outage doesn't
    block invitation creation.
    """
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

    # Phase 9.6 W1: actually send the emails (was missing in Phase 4c).
    # Phase 12.7 E: pass the org's branded primary color when configured so
    # the invitation email matches the org's identity (heading + button).
    org_primary = (org.settings or {}).get("branding", {}).get("primary_color")
    for inv in invitations:
        background_tasks.add_task(
            send_invitation_email,
            inv.email, inv.token, org.name, org.slug, app_settings.base_url,
            org_primary,
        )

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
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    admin_membership: models.OrgMembership = Depends(require_org_admin),
):
    """Resend invitation (admin) — generates a new token, extends expiry,
    and actually sends the email (Phase 9.6 W1 fix — also previously
    rotated the token without sending anything)."""
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
    # Phase 12.7 E: pass the org's branded primary color for header/button.
    org_primary = (org.settings or {}).get("branding", {}).get("primary_color")
    background_tasks.add_task(
        send_invitation_email,
        inv.email, inv.token, org.name, org.slug, app_settings.base_url,
        org_primary,
    )
    return {"message": "Invitation resent"}


# Accept invitation (public, auth not required — creates account or adds to org)
@router.post("/join/{token}", status_code=200)
def accept_invitation(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(auth_utils.get_optional_user),
):
    """Accept invitation by token. Requires authenticated user.

    Phase 9.7 W1: emits an `invitation.accepted_authenticated` audit event
    so all three invitation-consumption paths (registration, login, already-
    authenticated accept) leave a per-path audit trail with the same
    payload shape.
    """
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
    # Phase 12 — resolve invitation role string to a role_id; seed presets
    # defensively in case the org predates the migration backfill.
    inv_system_key = _INV_ROLE_TO_SYSTEM_KEY.get(inv.role, inv.role)
    role_id = _resolve_role_id_by_system_key(db, inv.org_id, inv_system_key)
    if role_id is None:
        seed_default_roles_for_org(db, inv.org_id)
        role_id = _resolve_role_id_by_system_key(db, inv.org_id, inv_system_key)
    if existing:
        if existing.status == "active":
            raise HTTPException(status_code=409, detail="Already a member of this organization")
        existing.status = "active"
        existing.role_id = role_id
    else:
        db.add(models.OrgMembership(
            user_id=current_user.id,
            org_id=inv.org_id,
            role_id=role_id,
            status="active",
        ))

    inv.status = "accepted"
    inv.accepted_at = _now()

    log_audit_event(
        db,
        action="invitation.accepted_authenticated",
        target_type="invitation",
        target_id=inv.id,
        actor_id=current_user.id,
        details={
            "invitation_id": inv.id,
            "org_id": inv.org_id,
            "role": inv.role,
            "invited_email": inv.email,
            "accepting_user_id": current_user.id,
        },
        ip_address=request.client.host if request.client else None,
    )

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
        avatar_url=current_user.avatar_url,
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
            avatar_url=user.avatar_url if user else None,
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
    """List org topics, filtered by viewer scope (Decision 5).

    Parent-org-wide topics (sub_org_id IS NULL) are always visible. Sub-org
    topics are visible only to (a) sub-org members, or (b) parent-org admins
    (Decision 6 implicit power).
    """
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    all_topics = db.query(models.Topic).filter(
        models.Topic.org_id == org.id,
    ).order_by(models.Topic.name).all()

    # Phase 12 — admin-tier visibility (parent-org admin/steward see every
    # sub-org topic regardless of membership).
    is_parent_admin = membership_role_system_key(membership) in ("admin", "steward")
    if is_parent_admin:
        return all_topics

    # Resolve sub-orgs the current user belongs to under this parent.
    visible_sub_org_ids = {row.sub_org_id for row in db.query(
        models.SubOrgMembership.sub_org_id
    ).filter(
        models.SubOrgMembership.user_id == current_user.id,
        models.SubOrgMembership.status == "active",
    ).all()}

    return [
        t for t in all_topics
        if t.sub_org_id is None or t.sub_org_id in visible_sub_org_ids
    ]


@router.post("/{org_slug}/topics", response_model=schemas.TopicOut, status_code=201)
def create_org_topic(
    org_slug: str,
    body: schemas.TopicCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """Create topic.

    Phase 8.5 scope handling:
      - If `sub_org_id` is None: parent-org-wide topic; requires parent-org
        admin (existing behavior).
      - If `sub_org_id` is non-null: sub-org-scoped topic; the requested
        sub-org must be a child of `org_slug`, and the actor must be an
        active sub-org admin (or parent-org admin via implicit power).
    """
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()

    if body.sub_org_id is None:
        # Parent-org-wide topic — gated by 'topic.create' permission.
        if not has_permission(db, current_user.id, org.id, "topic.create"):
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to create topics in this organization.",
            )
        target_sub_org_id = None
    else:
        sub_org = db.query(models.Organization).filter(
            models.Organization.id == body.sub_org_id,
            models.Organization.parent_org_id == org.id,
        ).first()
        if sub_org is None:
            raise HTTPException(
                status_code=400,
                detail="sub_org_id is not a sub-org of this parent",
            )
        from permissions import is_sub_org_admin
        if not is_sub_org_admin(db, current_user.id, sub_org):
            raise HTTPException(
                status_code=403,
                detail=(
                    "Sub-org admin (or parent-org admin) required to create "
                    "topics scoped to this sub-org"
                ),
            )
        target_sub_org_id = sub_org.id

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
        sub_org_id=target_sub_org_id,
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
    """List org proposals.

    Phase 8.5 visibility (Decision 7):
      - Parent-org-wide proposals: visible to all parent-org members.
      - Sub-org proposals where the sub-org is NOT private: visible to all
        parent-org members (read-only for non-sub-org-members; visibility is
        decoupled from voting/delegation eligibility).
      - Sub-org proposals where the sub-org has settings.private = True:
        visible only to sub-org members and parent-org admins (Decision 6).
    """
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    q = db.query(models.Proposal).filter(models.Proposal.org_id == org.id)
    if status_filter:
        q = q.filter(models.Proposal.status == status_filter)
    if topic_id:
        q = q.join(models.ProposalTopic).filter(models.ProposalTopic.topic_id == topic_id)
    proposals = q.order_by(models.Proposal.created_at.desc()).all()

    # Phase 12 — admin-tier visibility (parent-org admin/steward see all
    # sub-org proposals regardless of membership).
    is_parent_admin = membership_role_system_key(membership) in ("admin", "steward")
    if not is_parent_admin:
        # Resolve which (private) sub-orgs the viewer is a member of, so
        # private-flag filtering is correct.
        viewer_sub_org_ids = {row.sub_org_id for row in db.query(
            models.SubOrgMembership.sub_org_id
        ).filter(
            models.SubOrgMembership.user_id == current_user.id,
            models.SubOrgMembership.status == "active",
        ).all()}

        # Build a {sub_org_id -> private_bool} cache, only for sub-orgs that
        # actually appear in the proposal list (typically just a few).
        relevant_sub_org_ids = {p.sub_org_id for p in proposals if p.sub_org_id}
        private_map: dict[str, bool] = {}
        if relevant_sub_org_ids:
            for sub in db.query(models.Organization).filter(
                models.Organization.id.in_(relevant_sub_org_ids)
            ).all():
                private_map[sub.id] = bool((sub.settings or {}).get("private", False))

        filtered = []
        for p in proposals:
            if p.sub_org_id is None:
                filtered.append(p)
                continue
            if not private_map.get(p.sub_org_id, False):
                filtered.append(p)
                continue
            # Private sub-org: only members can see.
            if p.sub_org_id in viewer_sub_org_ids:
                filtered.append(p)
        proposals = filtered

    from routes.proposals import _build_proposal_out
    return [_build_proposal_out(p) for p in proposals]


@router.post("/{org_slug}/proposals", response_model=schemas.ProposalOut, status_code=201)
def create_org_proposal(
    org_slug: str,
    body: schemas.ProposalCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """Create proposal within org.

    Permission dispatches on ``body.sub_org_id``:
      - Parent-org-scoped (sub_org_id is None): requires parent-org
        moderator/admin/owner role — same gate as before Phase 8.5
        Session 3.
      - Sub-org-scoped (sub_org_id is non-null): requires sub-org-internal
        moderator+/admin/owner OR parent-org admin/owner (Decision 6
        implicit power). A sub-org *member* (plain role) cannot create
        proposals; they vote on existing ones.

    The previous implementation used a hard ``require_org_moderator_or_admin``
    Depends() that gated everyone — including sub-org members who weren't
    parent-org moderators. We softened to ``require_org_membership`` and
    dispatch the moderator+ check inside the body so the sub-org-internal
    role can govern sub-org-scoped actions (Session 2 tech debt #1).
    """
    from permissions import can_create_proposal_in_sub_org

    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()

    # Phase 8.5: resolve sub-org scope BEFORE _validate_proposal_creation so
    # the voting-method allowlist walks the correct org chain (sub-org
    # override -> parent default).
    target_sub_org: Optional[models.Organization] = None
    if body.sub_org_id is not None:
        target_sub_org = db.query(models.Organization).filter(
            models.Organization.id == body.sub_org_id,
            models.Organization.parent_org_id == org.id,
        ).first()
        if target_sub_org is None:
            raise HTTPException(
                status_code=400,
                detail="sub_org_id is not a sub-org of this parent",
            )
        # Sub-org-scoped: sub-org-internal moderator+ (or parent-org admin
        # via implicit power) required. Sub-org plain members cannot create.
        if not can_create_proposal_in_sub_org(db, current_user.id, target_sub_org):
            raise HTTPException(
                status_code=403,
                detail=(
                    "Sub-org moderator, admin, or owner role required to "
                    "create proposals scoped to this sub-org "
                    "(parent-org admin/owner also permitted via implicit power)."
                ),
            )
    else:
        # Parent-org-scoped: gated by 'proposal.create' permission.
        if not has_permission(db, current_user.id, org.id, "proposal.create"):
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to create proposals in this organization.",
            )

    from routes.proposals import _validate_proposal_creation, _create_proposal_options
    # Pass the sub-org (when present) so the voting-method allowlist resolves
    # via get_org_config — sub-org overrides take precedence over parent.
    _validate_proposal_creation(body, target_sub_org or org)

    for t in body.topics:
        topic_obj = db.get(models.Topic, t.topic_id)
        if not topic_obj:
            raise HTTPException(status_code=400, detail=f"Topic {t.topic_id} not found")
        # Phase 8.5: scope-compatibility for proposal topics.
        # Parent-org proposal: only parent-org-wide topics allowed.
        # Sub-org proposal: only parent-org-wide OR same-sub-org topics allowed.
        if target_sub_org is None:
            if topic_obj.sub_org_id is not None:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Topic {topic_obj.id} is scoped to a sub-org and "
                        "cannot be used by a parent-org-wide proposal"
                    ),
                )
        else:
            if topic_obj.sub_org_id is not None and topic_obj.sub_org_id != target_sub_org.id:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Topic {topic_obj.id} is scoped to a different "
                        "sub-org and cannot be used here"
                    ),
                )

    # Phase 8 — sustained-majority per-proposal override. Reject non-null
    # value when the org disallows per-proposal overrides.
    from sustained_majority_service import validate_per_proposal_override
    validate_per_proposal_override(body.sustained_majority_enabled, org)

    # Phase 9 Decision 7 — `require_polis_for_new_proposals` enforcement.
    # Walks parent chain via get_org_config so a sub-org can override
    # parent's setting.
    require_polis = bool(get_org_config(
        target_sub_org or org,
        "require_polis_for_new_proposals",
        DEFAULT_ORG_SETTINGS["require_polis_for_new_proposals"],
    ))
    linked_ids = list(body.linked_polis_ids or [])
    if require_polis and not linked_ids:
        raise HTTPException(
            status_code=400,
            detail=(
                "This organization requires every new proposal to link at "
                "least one Polis (require_polis_for_new_proposals)."
            ),
        )
    if linked_ids:
        from routes.proposals import _validate_linked_polis_ids
        _validate_linked_polis_ids(
            db, linked_ids, current_user.id, org.id,
        )

    # Phase 12.5 — threshold permission gate + org-default fallback. The
    # gate uses model_fields_set to distinguish "explicitly passed" from
    # "Pydantic-default 0.50/0.40" so the FE can omit the threshold inputs
    # for users without `proposal.set_thresholds` and the proposal lands
    # on the org's true defaults instead of the schema defaults. Sub-orgs
    # inherit parent defaults today (per spec "Per-sub-org thresholds" out
    # of scope), so the lookup uses the parent `org` regardless of
    # target_sub_org.
    from routes.proposals import _enforce_threshold_permission
    requested_pass = (
        body.pass_threshold
        if "pass_threshold" in body.model_fields_set else None
    )
    requested_quorum = (
        body.quorum_threshold
        if "quorum_threshold" in body.model_fields_set else None
    )
    _enforce_threshold_permission(
        db, current_user.id, org, requested_pass, requested_quorum,
    )
    default_pass, default_quorum = get_default_proposal_thresholds(org)
    effective_pass = requested_pass if requested_pass is not None else default_pass
    effective_quorum = requested_quorum if requested_quorum is not None else default_quorum

    proposal = models.Proposal(
        title=body.title,
        body=body.body,
        author_id=current_user.id,
        org_id=org.id,
        sub_org_id=target_sub_org.id if target_sub_org else None,
        voting_method=body.voting_method,
        num_winners=body.num_winners,
        pass_threshold=effective_pass,
        quorum_threshold=effective_quorum,
        sustained_majority_enabled=body.sustained_majority_enabled,
        linked_polis_ids=linked_ids if linked_ids else None,
    )
    db.add(proposal)
    db.flush()

    if body.sustained_majority_enabled is True:
        log_audit_event(
            db,
            action="proposal.sustained_majority_enabled",
            target_type="proposal",
            target_id=proposal.id,
            actor_id=current_user.id,
            details={"old_value": None, "new_value": True},
        )
    elif body.sustained_majority_enabled is False:
        log_audit_event(
            db,
            action="proposal.sustained_majority_disabled",
            target_type="proposal",
            target_id=proposal.id,
            actor_id=current_user.id,
            details={"old_value": None, "new_value": False},
        )

    for t in body.topics:
        db.add(models.ProposalTopic(
            proposal_id=proposal.id, topic_id=t.topic_id, relevance=t.relevance
        ))
    db.flush()

    if body.voting_method in ("approval", "ranked_choice") and body.options:
        _create_proposal_options(db, proposal.id, body.options)

    log_audit_event(
        db,
        action="proposal.created",
        target_type="proposal",
        target_id=proposal.id,
        actor_id=current_user.id,
        details={"title": proposal.title, "org_id": org.id, "voting_method": body.voting_method},
        ip_address=request.client.host if request.client else None,
    )

    # Phase 9 — emit polis.linked_to_proposal once per linked Polis on
    # creation. Reuses the same diff-emit helper used on PATCH; with
    # old_ids=[] every new id becomes an "added".
    if linked_ids:
        from routes.proposals import _emit_polis_link_diff_audits
        _emit_polis_link_diff_audits(
            db, proposal,
            old_ids=[], new_ids=linked_ids,
            actor_id=current_user.id,
            ip_address=request.client.host if request.client else None,
        )

    db.commit()
    db.refresh(proposal)
    from routes.proposals import _build_proposal_out
    return _build_proposal_out(proposal, db)


@router.get("/{org_slug}/proposals/{proposal_id}", response_model=schemas.ProposalOut)
def get_org_proposal(
    org_slug: str,
    proposal_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """Get proposal detail within org context.

    Phase 9: includes resolved `linked_polises` array (title/prompt/status/
    participation_count) when the proposal has structurally-recorded
    Polis links.
    """
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
    return _build_proposal_out(proposal, db)


@router.post("/{org_slug}/proposals/{proposal_id}/advance", response_model=schemas.ProposalOut)
def advance_org_proposal(
    org_slug: str,
    proposal_id: str,
    body: schemas.AdvanceProposalRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_moderator_or_admin),
):
    """Advance proposal status within org. Moderators can only advance their
    own proposals; admins/owners can advance any."""
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    proposal = db.query(models.Proposal).filter(
        models.Proposal.id == proposal_id,
        models.Proposal.org_id == org.id,
    ).first()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found in this organization")

    # Phase 12 — moderator-tier authors are restricted to advancing their
    # own proposals. Admin/Steward have no such restriction. Documented in
    # docs/phase12_role_check_audit.md as DOESNT_MAP_FLAG (Stage-1
    # behavior preserved; Stage 2 may revisit).
    if (
        membership_role_system_key(membership) == "moderator"
        and proposal.author_id != current_user.id
    ):
        raise HTTPException(status_code=403, detail="Moderators can only advance proposals they created")

    from routes.proposals import STATUS_TRANSITIONS
    next_status = STATUS_TRANSITIONS.get(proposal.status)
    if next_status is None:
        raise HTTPException(status_code=400, detail=f"Cannot advance from status '{proposal.status}'")

    old_status = proposal.status
    now = _now()

    if next_status == "deliberation":
        proposal.deliberation_start = now
    elif next_status == "voting":
        proposal.voting_start = now
        if body.voting_end:
            proposal.voting_end = body.voting_end
    elif next_status == "passed":
        from delegation_engine import engine as delegation_engine, ApprovalTally, RCVTally
        tally = delegation_engine.compute_tally(proposal, db)
        if proposal.voting_method == "approval":
            if isinstance(tally, ApprovalTally) and tally.quorum_met(proposal.quorum_threshold) and tally.winners:
                next_status = "passed"
            else:
                next_status = "failed"
        elif proposal.voting_method == "ranked_choice":
            if isinstance(tally, RCVTally) and tally.quorum_met(proposal.quorum_threshold) and tally.winners:
                next_status = "passed"
            else:
                next_status = "failed"
        else:
            if tally.threshold_met(proposal.pass_threshold) and tally.quorum_met(proposal.quorum_threshold):
                next_status = "passed"
            else:
                next_status = "failed"

    proposal.status = next_status
    db.flush()

    log_audit_event(
        db,
        action="proposal.status_changed",
        target_type="proposal",
        target_id=proposal.id,
        actor_id=current_user.id,
        details={"proposal_id": proposal.id, "old_status": old_status, "new_status": next_status},
        ip_address=request.client.host if request.client else None,
    )

    db.commit()
    db.refresh(proposal)
    from routes.proposals import _build_proposal_out
    return _build_proposal_out(proposal)


# ============================================================================
# Sustained-Majority Escalation Resolution (Phase 8)
# ============================================================================

@router.post(
    "/{org_slug}/proposals/{proposal_id}/resolve_escalation",
    response_model=schemas.ProposalOut,
)
def resolve_escalation(
    org_slug: str,
    proposal_id: str,
    body: schemas.EscalationResolveRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    admin_membership: models.OrgMembership = Depends(require_org_admin),
):
    """Resolve a proposal currently in `unresolved` status (Phase 8).

    Only reachable for proposals where the sustained-majority floor was
    breached and failure_mode was `escalate`. Admin picks one of:
      - extend                : push voting_end forward, status back to voting
      - fail                  : status -> failed
      - pass                  : status -> passed (override; discouraged)
      - back_to_deliberation  : status -> deliberation (reopens for amendment)

    Always emits `proposal.escalation_resolved` with the chosen action and
    optional reason.
    """
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    proposal = db.query(models.Proposal).filter(
        models.Proposal.id == proposal_id,
        models.Proposal.org_id == org.id,
    ).first()
    if not proposal:
        raise HTTPException(
            status_code=404, detail="Proposal not found in this organization",
        )
    if proposal.status != "unresolved":
        raise HTTPException(
            status_code=400,
            detail=f"Proposal is in '{proposal.status}', not 'unresolved'",
        )

    old_status = proposal.status
    new_status: str = old_status
    audit_extra: dict = {}

    if body.action == "extend":
        # Move back to voting and extend the window. Either honor the
        # caller-supplied new_voting_end or extend by the original window.
        proposal.status = "voting"
        new_status = "voting"
        if body.new_voting_end is not None:
            proposal.voting_end = body.new_voting_end.replace(tzinfo=None) \
                if body.new_voting_end.tzinfo else body.new_voting_end
        elif proposal.voting_start and proposal.voting_end:
            from sustained_majority import extension_window_for
            proposal.voting_end = (
                proposal.voting_end
                + extension_window_for(proposal.voting_start, proposal.voting_end)
            )
        audit_extra["new_voting_end"] = (
            proposal.voting_end.isoformat() if proposal.voting_end else None
        )
        # Also emit the matching window_extended event so the
        # `count_extensions` helper in the worker reflects this manual extend.
        log_audit_event(
            db,
            action="proposal.window_extended",
            target_type="proposal",
            target_id=proposal.id,
            actor_id=current_user.id,
            details={
                "proposal_id": proposal.id,
                "voting_method": proposal.voting_method,
                "reason": "admin_escalation_resolution",
                "new_voting_end": audit_extra["new_voting_end"],
            },
            ip_address=request.client.host if request.client else None,
        )
    elif body.action == "fail":
        proposal.status = "failed"
        new_status = "failed"
    elif body.action == "pass":
        proposal.status = "passed"
        new_status = "passed"
    elif body.action == "back_to_deliberation":
        proposal.status = "deliberation"
        new_status = "deliberation"

    db.flush()

    log_audit_event(
        db,
        action="proposal.escalation_resolved",
        target_type="proposal",
        target_id=proposal.id,
        actor_id=current_user.id,
        details={
            "proposal_id": proposal.id,
            "action": body.action,
            "reason": (body.reason or "").strip() or None,
            "old_status": old_status,
            "new_status": new_status,
            **audit_extra,
        },
        ip_address=request.client.host if request.client else None,
    )

    db.commit()
    db.refresh(proposal)
    from routes.proposals import _build_proposal_out
    return _build_proposal_out(proposal)


# ============================================================================
# Tie Resolution (admin)
# ============================================================================

@router.post("/{org_slug}/proposals/{proposal_id}/resolve-tie", status_code=200)
def resolve_tie(
    org_slug: str,
    proposal_id: str,
    body: schemas.TieResolutionRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    admin_membership: models.OrgMembership = Depends(require_org_admin),
):
    """Resolve a tie on an approval proposal (admin). Picks the winning option."""
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    proposal = db.query(models.Proposal).filter(
        models.Proposal.id == proposal_id,
        models.Proposal.org_id == org.id,
    ).first()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found in this organization")

    if proposal.voting_method not in ("approval", "ranked_choice"):
        raise HTTPException(
            status_code=400,
            detail="Tie resolution is only for approval or ranked-choice proposals",
        )

    if proposal.status != "passed":
        raise HTTPException(status_code=400, detail="Proposal must be in passed status to resolve a tie")

    if proposal.tie_resolution is not None:
        raise HTTPException(status_code=409, detail="Tie has already been resolved")

    # Compute current tally to verify there is a tie
    from delegation_engine import engine as delegation_engine, ApprovalTally, RCVTally
    tally = delegation_engine.compute_tally(proposal, db)
    if isinstance(tally, ApprovalTally):
        if not tally.tied:
            raise HTTPException(status_code=400, detail="There is no tie to resolve")
        tied_pool = tally.winners
    elif isinstance(tally, RCVTally):
        if not tally.tied:
            raise HTTPException(status_code=400, detail="There is no tie to resolve")
        tied_pool = tally.winners
    else:
        raise HTTPException(status_code=400, detail="Tally type does not support tie resolution")

    # Validate selected_option_id is among the tied finalists
    if body.selected_option_id not in tied_pool:
        raise HTTPException(
            status_code=400,
            detail=f"Option {body.selected_option_id} is not among the tied finalists",
        )

    # Find the option label
    option = db.query(models.ProposalOption).filter(
        models.ProposalOption.id == body.selected_option_id,
    ).first()
    option_label = option.label if option else body.selected_option_id

    proposal.tie_resolution = {
        "selected_option_id": body.selected_option_id,
        "selected_option_label": option_label,
        "resolved_by": current_user.id,
    }
    db.flush()

    log_audit_event(
        db,
        action="proposal.tie_resolved",
        target_type="proposal",
        target_id=proposal.id,
        actor_id=current_user.id,
        details={
            "selected_option_id": body.selected_option_id,
            "selected_option_label": option_label,
            "tied_winners": tied_pool,
        },
        ip_address=request.client.host if request.client else None,
    )

    db.commit()
    db.refresh(proposal)
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
