"""
Organization management endpoints — CRUD, membership, invitations,
delegate applications, topics, proposals, and analytics.
"""
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

import auth as auth_utils
import models
import schemas
from audit_utils import log_audit_event
from database import get_db
from email_service import send_invitation_email
from notification_emit import emit_notification
from org_config import (
    get_default_proposal_durations,
    get_default_proposal_thresholds,
    get_org_config,
)
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


log = logging.getLogger(__name__)


def _users_with_permission_in_org(
    db: Session, org_id: str, permission_key: str,
) -> list[str]:
    """Return user_ids of all active org members holding ``permission_key``.

    Phase 13 B-emit helper for fan-out events (member.join_request,
    delegate.applied) — those notifications must reach every user with
    approval rights, regardless of role tier. Iterates active memberships
    and consults ``has_permission`` so the result tracks any custom
    role_permission grants (matrix is the source of truth).
    """
    member_rows = (
        db.query(models.OrgMembership.user_id)
        .filter(
            models.OrgMembership.org_id == org_id,
            models.OrgMembership.status == "active",
        )
        .all()
    )
    return [
        r.user_id for r in member_rows
        if has_permission(db, r.user_id, org_id, permission_key)
    ]


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
    # Phase 8 / Phase 20 — "Stable Result Required" voting-window config.
    # All defaults off / fail-safe so existing orgs see no behavior change
    # until an admin flips the switch. ``get_stable_result_config()``
    # lazy-applies these values when an org was created before Phase 20 and
    # lacks the keys. Per spec D13 the threshold / floor / failure_mode keys
    # are gone; old values in the settings JSON are silently ignored.
    "stable_result_enabled_default": False,
    "stable_result_per_proposal_override": True,
    "stable_window_fraction": 0.25,
    "max_extension_fraction": 0.25,
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
    #
    # Phase 34.1 E5 — sub-org branding fields fall through to parent's
    # values when null. logo_url + primary_color + accent_color each
    # resolve via: sub-org value → parent value → None (platform
    # default applied client-side). Implementation walks parent_org_id
    # once (no deep recursion — sub-org nesting is single-level only).
    branding_dict = (org.settings or {}).get("branding") or {}
    parent_branding_dict: dict = {}
    if org.parent_org_id is not None:
        parent = db.get(models.Organization, org.parent_org_id)
        if parent is not None:
            parent_branding_dict = (parent.settings or {}).get("branding") or {}

    def _inherit(key: str):
        v = branding_dict.get(key)
        if v is not None and v != "":
            return v
        pv = parent_branding_dict.get(key)
        if pv is not None and pv != "":
            return pv
        return None

    branding_out = schemas.BrandingOut(
        logo_url=_inherit("logo_url"),
        primary_color=_inherit("primary_color"),
        accent_color=_inherit("accent_color"),
        accent_auto_derived=bool(branding_dict.get("accent_auto_derived", False)),
    )

    return schemas.OrgOut(
        id=org.id,
        name=org.name,
        slug=org.slug,
        description=org.description or "",
        join_policy=org.join_policy,
        settings=org.settings or {},
        parent_org_id=org.parent_org_id,
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

    When the patch touches any of the Stable Result Required keys, we emit a
    focused ``org.stable_result_config_changed`` audit event listing only
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
        from sustained_majority_service import diff_stable_result_settings
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

        # Phase 17 B5 — tie_resolution validation. Same pre-merge shape:
        # invalid method on either voting_method fails the whole PATCH
        # cleanly with HTTP 400. Unknown keys (e.g., a future
        # "score_voting") are silently dropped by the validator for
        # forward-compat. The validator returns the cleaned dict, which
        # we substitute back into body.settings so the merge below stores
        # only the valid subset.
        if "tie_resolution" in body.settings:
            from tie_resolution import validate_tie_resolution_settings
            try:
                body.settings["tie_resolution"] = (
                    validate_tie_resolution_settings(
                        body.settings["tie_resolution"]
                    )
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))

        # Phase 15 Cluster S §S3 — sub_org_role_transferability validation.
        # Steward toggle is locked ON: rejecting an explicit False keeps
        # the resolution helper's invariant (Steward always transfers)
        # readable. Other keys validated as bools.
        if "sub_org_role_transferability" in body.settings:
            transferability = body.settings["sub_org_role_transferability"]
            if not isinstance(transferability, dict):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "sub_org_role_transferability must be an object "
                        "with role-key booleans (steward, admin, moderator, "
                        "member)."
                    ),
                )
            allowed_keys = {"steward", "admin", "moderator", "member"}
            unknown = set(transferability.keys()) - allowed_keys
            if unknown:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Unknown role keys in sub_org_role_transferability: "
                        f"{sorted(unknown)}. Allowed: "
                        f"{sorted(allowed_keys)}."
                    ),
                )
            for k, v in transferability.items():
                if not isinstance(v, bool):
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"sub_org_role_transferability.{k} must be a "
                            f"boolean, got {type(v).__name__}."
                        ),
                    )
            if transferability.get("steward") is False:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Steward role transferability cannot be disabled."
                    ),
                )

        # Diff BEFORE merging so we capture the actual transition.
        sm_diff = diff_stable_result_settings(org.settings, body.settings)
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
                action="org.stable_result_config_changed",
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
# Phase 14 B2 — Public landing page endpoint (NO AUTH)
# ============================================================================

# The public endpoint is intentionally unauthenticated: anyone with the
# slug can fetch org name/description/logo/branding/intro for the three
# public join-policy variants. invite_only_secret orgs are 404'd to be
# indistinguishable from non-existent ones (a probe for a random slug
# returns the same status whether the slug is unused or belongs to a
# secret org). NO server-side caching layer in v1; data changes
# infrequently so the absence is acceptable, and adding caching now
# without an invalidation hook on PATCH endpoints would risk staleness.

# Phase 14 — public-org sub-router. Dedicated APIRouter so the no-auth
# path is visible at the route-table level (no Depends on get_current_user).
public_org_router = APIRouter(prefix="/api/orgs", tags=["organizations-public"])


@public_org_router.get("/{org_slug}/public", response_model=schemas.OrgPublicOut)
def get_public_org(
    org_slug: str,
    db: Session = Depends(get_db),
):
    """Return the public-facing data shape for an org's landing page.

    No auth required. Logged-in users get the same response as logged-out
    callers — auth state does not affect the response.

    404 if the org doesn't exist OR if its join_policy is
    'invite_only_secret'. The 404 response is identical in both cases by
    design (security: secret orgs must be indistinguishable from
    non-existent ones from an unauthenticated probe perspective). No
    leaking via response timing differences either — the same SQL path
    is taken for both branches.

    Returns a small subset of org fields: slug, name, description,
    logo_url, branding (primary_color + accent_color), intro_text,
    join_policy. No member_count, no created_at, no internal IDs.
    """
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    if org is None or org.join_policy == "invite_only_secret":
        raise HTTPException(status_code=404, detail="Organization not found")

    branding_dict = (org.settings or {}).get("branding") or {}
    return schemas.OrgPublicOut(
        slug=org.slug,
        name=org.name,
        description=org.description or "",
        logo_url=branding_dict.get("logo_url"),
        branding=schemas.OrgPublicBrandingOut(
            primary_color=branding_dict.get("primary_color"),
            accent_color=branding_dict.get("accent_color"),
        ),
        intro_text=(org.settings or {}).get("intro_text") or None,
        join_policy=org.join_policy,
    )


# ============================================================================
# Phase 23 B6 — Demo directory endpoint (NO AUTH)
# ============================================================================
#
# Surfaces the per-org directory consumed by the updated /demo page (F2).
# Public-readable, no auth, matches the Phase 14 public-landing pattern.
# Returns all is_demo=True orgs sorted by display_order, each with the
# bible-seeded persona allowlist + counts + the platform-wide reset
# clock. The endpoint is the single source the frontend reads — it
# doubles as both the directory-card data and the persona-pick gateway
# into the per-org demo-login (B7).
#
# Caching: Cache-Control: max-age=60. The data changes slowly (member
# counts and proposal counts shift gradually; the reset event itself
# only fires once per day). 60s strikes the balance between freshness
# and absorbing burst traffic against the splash page.

class DemoPersonaOut(BaseModel):
    """One quick-login persona on a demo org card.

    Fields mirror the shape persisted in ``Organization.personas`` JSONB
    (seeded by the bible per D25/Amendment D). ``description`` is the
    Stage-8 one-sentence blurb; if a persona is bible-seeded without one
    the seed mechanism falls back to ``description = role`` so the card
    always has non-empty text. Phase 30 B3: ``avatar_url`` surfaces the
    User.avatar_url (Phase 29 C6 portraits) so the /demo picker can
    render AI-illustration portraits instead of initial circles.
    """
    username: str
    display_name: str
    role: str
    description: str
    avatar_url: Optional[str] = None


class DemoOrgCardOut(BaseModel):
    """One demo-org card on the /demo directory page.

    ``charter_summary`` is a ~150-char ellipsized slice of the org's
    description (D22). Counts are computed at request time (active
    memberships, proposals in voting status, proposals in deliberation).
    ``personas`` is the bible-seeded allowlist; empty list when the seed
    hasn't run yet. ``is_demo_resetting`` lets the frontend dim a card
    during an in-flight reset (D20).
    """
    slug: str
    name: str
    governance_type: Optional[str] = None
    charter_summary: str
    member_count: int
    active_proposal_count: int
    deliberation_proposal_count: int
    personas: list[DemoPersonaOut]
    display_order: Optional[int] = None
    is_demo_resetting: bool


class DemoDirectoryOut(BaseModel):
    """Top-level response for the /api/orgs/demo directory endpoint.

    ``reset_time_pacific`` echoes the configured HH:MM (Pacific) reset
    moment so the frontend can render "resets daily at HH:MM Pacific"
    copy without duplicating env knowledge. ``next_reset_at`` is the
    UTC instant of the next reset, computed from current Pacific time
    + ``reset_time_pacific`` with DST handled correctly via zoneinfo.
    """
    orgs: list[DemoOrgCardOut]
    reset_time_pacific: str
    next_reset_at: datetime


def _charter_summary(description: Optional[str], max_chars: int = 150) -> str:
    """Build the directory-card charter summary from ``description``.

    Returns the first ``max_chars`` characters of ``description``,
    ellipsized with ``...`` when truncated. Whitespace is trimmed.
    Empty/None description → empty string (the frontend handles the
    empty-state copy — this helper returns predictable shape only).
    """
    if not description:
        return ""
    text = description.strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def _compute_next_reset_at(reset_time_pacific: str) -> datetime:
    """Compute the next reset moment in UTC, DST-aware.

    ``reset_time_pacific`` is HH:MM 24-hour. We interpret it in
    America/Los_Angeles (which switches between PST/PDT automatically
    via zoneinfo), pick today's reset moment if it's still in the
    future, otherwise tomorrow's. The result is converted to UTC so
    clients can render relative countdowns without a timezone lib.

    Malformed values fall back to midnight Pacific so a typo in the
    env var never breaks the directory endpoint.
    """
    try:
        hh_str, mm_str = reset_time_pacific.split(":", 1)
        hh = int(hh_str)
        mm = int(mm_str)
        if not (0 <= hh < 24 and 0 <= mm < 60):
            raise ValueError("out-of-range")
    except (ValueError, AttributeError):
        hh, mm = 0, 0

    pacific = ZoneInfo("America/Los_Angeles")
    now_pacific = datetime.now(pacific)
    candidate = now_pacific.replace(
        hour=hh, minute=mm, second=0, microsecond=0,
    )
    if candidate <= now_pacific:
        candidate = candidate + timedelta(days=1)
    # Convert to UTC for the response. The naive timezone-aware->UTC
    # conversion via astimezone correctly accounts for DST transitions
    # because the source ``candidate`` is tz-aware in Pacific.
    return candidate.astimezone(timezone.utc)


@public_org_router.get("/demo", response_model=DemoDirectoryOut)
def get_demo_directory(
    response: Response,
    db: Session = Depends(get_db),
):
    """Phase 23 B6 — directory of demo orgs for the /demo page.

    Public-readable, no auth. Returns every ``is_demo=True`` org
    sorted by ``display_order ASC NULLS LAST, name ASC`` (D23), with
    per-org counts + the bible-seeded persona allowlist (D22, D25,
    Amendment D). The response also carries the platform-wide reset
    clock (``reset_time_pacific``, ``next_reset_at``) so the frontend
    can render the daily-reset disclosure copy + countdown without
    duplicating env config.

    Pre-seed edge case: if no demo orgs exist yet (e.g., between
    deploy and the first scheduled reset), returns ``orgs: []`` plus
    the reset clock. The frontend handles the empty case ("Demo is
    refreshing, please check back in a moment").

    Caching: ``Cache-Control: max-age=60``. Data changes slowly
    (counts shift gradually; reset fires once per day); a brief
    cache absorbs burst traffic on the splash page without making
    the data stale enough to mislead.
    """
    orgs = (
        db.query(models.Organization)
        .filter(models.Organization.is_demo.is_(True))
        # Phase 34 — filter out sub-orgs (parent_org_id IS NOT NULL) so the
        # public demo directory shows top-level orgs only. Cedar Court
        # Condos sub-org seeds with is_demo=True (so the wipe boundary
        # covers it) but it shouldn't surface as a standalone tile.
        .filter(models.Organization.parent_org_id.is_(None))
        .order_by(
            # NULLS LAST on display_order so any future demo org seeded
            # without an explicit order falls to the bottom rather than
            # leading by accident. SQLAlchemy's ``func.coalesce`` is the
            # cross-dialect-safe NULLS-LAST pattern (SQLite doesn't
            # support PG's ``NULLS LAST`` modifier directly).
            func.coalesce(models.Organization.display_order, 999999).asc(),
            models.Organization.name.asc(),
        )
        .all()
    )
    # Phase 29 C1: filter out orgs flagged as hidden from the public demo
    # listing in their bible. ``org.is_demo`` stays True (the daily-reset
    # wipe boundary); the listing-visibility flag lives in settings JSON
    # so no migration is required.
    orgs = [
        o for o in orgs
        if not (o.settings or {}).get("hidden_from_demo_listing")
    ]

    cards: list[DemoOrgCardOut] = []
    for org in orgs:
        member_count = (
            db.query(models.OrgMembership)
            .filter(
                models.OrgMembership.org_id == org.id,
                models.OrgMembership.status == "active",
            )
            .count()
        )
        active_proposal_count = (
            db.query(models.Proposal)
            .filter(
                models.Proposal.org_id == org.id,
                models.Proposal.status == "voting",
            )
            .count()
        )
        deliberation_proposal_count = (
            db.query(models.Proposal)
            .filter(
                models.Proposal.org_id == org.id,
                models.Proposal.status == "deliberation",
            )
            .count()
        )

        # personas JSONB may be NULL (pre-seed) or a list of dicts
        # matching the DemoPersonaOut shape. Defensive: skip entries
        # missing the required username key rather than 500ing the
        # whole directory if a malformed entry slips through.
        raw_personas = org.personas or []
        personas: list[DemoPersonaOut] = []
        for p in raw_personas:
            if not isinstance(p, dict) or not p.get("username"):
                continue
            personas.append(DemoPersonaOut(
                username=p.get("username"),
                display_name=p.get("display_name") or p.get("username"),
                role=p.get("role") or "",
                description=p.get("description") or p.get("role") or "",
                avatar_url=p.get("avatar_url"),
            ))

        cards.append(DemoOrgCardOut(
            slug=org.slug,
            name=org.name,
            governance_type=org.governance_type,
            charter_summary=_charter_summary(org.description),
            member_count=member_count,
            active_proposal_count=active_proposal_count,
            deliberation_proposal_count=deliberation_proposal_count,
            personas=personas,
            display_order=org.display_order,
            is_demo_resetting=bool(org.is_demo_resetting),
        ))

    reset_time = app_settings.demo_reset_time_pacific
    next_reset_at = _compute_next_reset_at(reset_time)

    # 60s cache per spec. Light enough to absorb splash-page burst
    # traffic without staleness becoming user-visible.
    response.headers["Cache-Control"] = "max-age=60"

    return DemoDirectoryOut(
        orgs=cards,
        reset_time_pacific=reset_time,
        next_reset_at=next_reset_at,
    )


# ============================================================================
# Phase 14 B3 — Public join-request endpoint (consolidates two paths)
# ============================================================================

@router.post("/{org_slug}/join-request", status_code=200, response_model=schemas.JoinRequestOut)
def create_join_request(
    org_slug: str,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Phase 14 B3 — single entry point for prospective members joining
    an org from its public landing page.

    Dispatches by ``org.join_policy``:

      * ``invite_only_secret`` -> 404 (matches B2's secret-disambiguation
        rule; even an authenticated probe gets the same answer).
      * ``invite_only_public`` -> 403 (org has a public landing page but
        joining requires an invitation; explicit error message).
      * ``approval_required`` -> create OrgMembership(status='pending_approval'),
        fire member.join_request notification to all approvers, audit
        as ``org.join_requested``, return {status: 'pending', ...}.
      * ``open`` -> create OrgMembership(status='active'), audit as
        ``org.joined``, return {status: 'active', ...}.

    Already-active members get 409 ("You are already a member.").
    Already-pending requesters get 409 ("Your request is already pending.").

    Consolidates what were previously two separate code paths (the
    POST /join legacy endpoint kept the existing approval_required + open
    behavior; this new endpoint is the public-landing-page front door
    and is what the new OrgPublicLanding.jsx page calls).
    """
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    if org is None or org.join_policy == "invite_only_secret":
        # Same 404 shape for non-existent and secret orgs.
        raise HTTPException(status_code=404, detail="Organization not found")

    if org.join_policy == "invite_only_public":
        raise HTTPException(
            status_code=403,
            detail="This organization requires an invitation.",
        )

    if org.join_policy not in ("approval_required", "open"):
        # Defensive: should be unreachable given the value set, but
        # surfaces a loud error if a future policy variant is added
        # without updating this dispatch.
        raise HTTPException(
            status_code=500,
            detail=f"Unknown join_policy {org.join_policy!r}",
        )

    existing = db.query(models.OrgMembership).filter(
        models.OrgMembership.org_id == org.id,
        models.OrgMembership.user_id == current_user.id,
    ).first()
    if existing is not None:
        if existing.status == "active":
            raise HTTPException(status_code=409, detail="You are already a member.")
        if existing.status == "pending_approval":
            raise HTTPException(
                status_code=409, detail="Your request is already pending.",
            )

    # Resolve the Member role (defensive seed for legacy orgs).
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
        db.flush()
        log_audit_event(
            db,
            action="org.joined",
            target_type="organization",
            target_id=org.id,
            actor_id=current_user.id,
            details={"slug": org.slug, "policy": "open"},
            ip_address=request.client.host if request.client else None,
        )
        db.commit()
        db.refresh(membership)
        return schemas.JoinRequestOut(status="active", member_id=membership.id)

    # approval_required path.
    membership = models.OrgMembership(
        user_id=current_user.id,
        org_id=org.id,
        role_id=member_role_id,
        status="pending_approval",
    )
    db.add(membership)
    db.flush()
    log_audit_event(
        db,
        action="org.join_requested",
        target_type="organization",
        target_id=org.id,
        actor_id=current_user.id,
        details={"slug": org.slug, "policy": "approval_required"},
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(membership)

    # Notification fan-out — same pattern as the legacy /join handler.
    # Wrapped in try/except so a notification failure can't sink the
    # join-request creation (the membership row is already committed).
    try:
        actor_display = current_user.display_name or current_user.username
        approver_ids = _users_with_permission_in_org(
            db, org.id, "member.approve_join",
        )
        for approver_id in approver_ids:
            emit_notification(
                db,
                background_tasks,
                event_type="member.join_request",
                user_id=approver_id,
                org_id=org.id,
                actor_id=current_user.id,
                target_type="user",
                target_id=current_user.id,
                payload={
                    "org_id": org.id,
                    "org_slug": org.slug,
                    "org_name": org.name,
                    "requester_id": current_user.id,
                    "actor_display_name": actor_display,
                },
            )
        db.commit()
    except Exception as e:  # noqa: BLE001
        log.warning(
            "member.join_request emit failed (B3 path): %s: %s",
            type(e).__name__, e,
        )
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass

    return schemas.JoinRequestOut(status="pending", member_id=membership.id)


@router.delete("/{org_slug}/join-request", status_code=204)
def cancel_join_request(
    org_slug: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Phase 14 B3 — cancel a pending join request.

    Auth required.

    404 if org doesn't exist or is invite_only_secret (same disambiguation
    rule as B2).
    404 if no pending request from this user exists (idempotent within
    the 404-on-no-pending behavior — a second call after deletion gets
    the same 404, no errors).

    Audit event: ``org.join_request_cancelled``.

    Deletes the OrgMembership row outright (rather than transitioning
    its status), matching the existing deny-join-request pattern.
    """
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    if org is None or org.join_policy == "invite_only_secret":
        raise HTTPException(status_code=404, detail="Organization not found")

    membership = db.query(models.OrgMembership).filter(
        models.OrgMembership.org_id == org.id,
        models.OrgMembership.user_id == current_user.id,
        models.OrgMembership.status == "pending_approval",
    ).first()
    if membership is None:
        raise HTTPException(status_code=404, detail="No pending join request")

    db.delete(membership)
    log_audit_event(
        db,
        action="org.join_request_cancelled",
        target_type="organization",
        target_id=org.id,
        actor_id=current_user.id,
        details={"slug": org.slug},
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    # 204 — explicit empty response.
    from fastapi import Response
    return Response(status_code=204)


# ============================================================================
# Join Flow
# ============================================================================

@router.post("/{org_slug}/join", status_code=200)
def request_join(
    org_slug: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Request to join (for approval_required/open orgs)."""
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    # Phase 14 B5 — new value set: invite_only is gone; secret/public
    # are both invite-only variants from this endpoint's perspective.
    # Treat invite_only_secret as 404 to match B2's secret rule even on
    # this legacy endpoint (defense-in-depth: the new client uses B3
    # exclusively, but old clients calling /join shouldn't leak secret
    # org existence).
    if org.join_policy == "invite_only_secret":
        raise HTTPException(status_code=404, detail="Organization not found")
    if org.join_policy in ("invite_only", "invite_only_public"):
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

        # Phase 13 B-emit — member.join_request -> all org members holding
        # the member.approve_join permission. Fan-out wrapped per spec
        # §B3: notification failure must not sink the join request.
        try:
            actor_display = current_user.display_name or current_user.username
            approver_ids = _users_with_permission_in_org(
                db, org.id, "member.approve_join",
            )
            for approver_id in approver_ids:
                emit_notification(
                    db,
                    background_tasks,
                    event_type="member.join_request",
                    user_id=approver_id,
                    org_id=org.id,
                    actor_id=current_user.id,
                    target_type="user",
                    target_id=current_user.id,
                    payload={
                        "org_id": org.id,
                        "org_slug": org.slug,
                        "org_name": org.name,
                        "requester_id": current_user.id,
                        "actor_display_name": actor_display,
                    },
                )
            db.commit()
        except Exception as e:  # noqa: BLE001
            log.warning(
                "member.join_request emit failed: %s: %s",
                type(e).__name__, e,
            )
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass

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
    background_tasks: BackgroundTasks,
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

    # Phase 13 B-emit — invitation.accepted -> the inviter (Invitation.invited_by).
    if inv.invited_by and inv.invited_by != current_user.id:
        try:
            actor_display = current_user.display_name or current_user.username
            emit_notification(
                db,
                background_tasks,
                event_type="invitation.accepted",
                user_id=inv.invited_by,
                org_id=inv.org_id,
                actor_id=current_user.id,
                target_type="invitation",
                target_id=inv.id,
                payload={
                    "org_id": inv.org_id,
                    "org_slug": org.slug,
                    "org_name": org.name,
                    "invited_email": inv.email,
                    "accepting_user_id": current_user.id,
                    "actor_display_name": actor_display,
                },
            )
            db.commit()
        except Exception as e:  # noqa: BLE001
            log.warning(
                "invitation.accepted emit failed: %s: %s",
                type(e).__name__, e,
            )
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass

    return {"message": f"You have joined {org.name}", "org_slug": org.slug}


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
    # Phase 34.1 E3-sibling — when org_slug resolves to a sub-org, topics
    # are stored with org_id=parent + sub_org_id=this-sub. Filter
    # accordingly so /api/orgs/<sub_slug>/topics returns the sub-org's
    # topics (was empty list pre-fix).
    if org.parent_org_id is not None:
        all_topics = db.query(models.Topic).filter(
            models.Topic.org_id == org.parent_org_id,
            models.Topic.sub_org_id == org.id,
        ).order_by(models.Topic.name).all()
    else:
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
        # Phase 33 D2 — Topic.description dropped.
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
    # Phase 33 D2 — Topic.description column dropped.
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
    # Phase 34.1 E3 — when org_slug resolves to a sub-org, proposals are
    # stored with org_id=parent + sub_org_id=this-sub. Filter accordingly
    # so navigating to /api/orgs/<sub_slug>/proposals returns the sub-org's
    # proposals (was empty list pre-fix).
    if org.parent_org_id is not None:
        q = db.query(models.Proposal).filter(
            models.Proposal.org_id == org.parent_org_id,
            models.Proposal.sub_org_id == org.id,
        )
    else:
        q = db.query(models.Proposal).filter(models.Proposal.org_id == org.id)
    if status_filter:
        q = q.filter(models.Proposal.status == status_filter)
    if topic_id:
        q = q.join(models.ProposalTopic).filter(models.ProposalTopic.topic_id == topic_id)
    # Phase 31 F1 — three-tier ordering: voting → deliberation → closed.
    from routes.proposals import _proposal_list_ordering as _f1_ordering
    proposals = q.order_by(*_f1_ordering()).all()

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
    return [_build_proposal_out(p, db) for p in proposals]


@router.post("/{org_slug}/proposals", response_model=schemas.ProposalOut, status_code=201)
def create_org_proposal(
    org_slug: str,
    body: schemas.ProposalCreate,
    request: Request,
    background_tasks: BackgroundTasks,
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

    # Phase 8 / Phase 20 — Stable Result Required per-proposal override.
    # Reject non-null value when the org disallows per-proposal overrides.
    from sustained_majority_service import validate_per_proposal_override
    validate_per_proposal_override(body.stable_result_required, org)

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

    # Phase 16 — per-proposal duration override gate. Mirrors the
    # threshold block above: same model_fields_set pattern; the helper
    # short-circuits when both fields are omitted or match the org
    # defaults. Floor checks are independent of the permission gate.
    # Sub-org-scoped proposals reuse the parent org's defaults today
    # (per-sub-org defaults out of scope per spec line 411).
    from routes.proposals import (
        _enforce_duration_permission,
        _validate_duration_floors,
    )
    requested_delib_days = (
        body.deliberation_days
        if "deliberation_days" in body.model_fields_set else None
    )
    requested_vote_days = (
        body.voting_days
        if "voting_days" in body.model_fields_set else None
    )
    _validate_duration_floors(requested_delib_days, requested_vote_days)
    _enforce_duration_permission(
        db, current_user.id, org, requested_delib_days, requested_vote_days,
    )
    default_delib_days, default_vote_days = get_default_proposal_durations(org)
    effective_delib_days = (
        requested_delib_days
        if requested_delib_days is not None else default_delib_days
    )
    effective_vote_days = (
        requested_vote_days
        if requested_vote_days is not None else default_vote_days
    )

    # Phase 25 B2 — 0-day deliberation skip: when the effective
    # deliberation duration resolves to zero (either an explicit
    # per-proposal override or the org default), create the proposal
    # directly in `voting` status. Single audit event (draft -> voting)
    # rather than two-at-the-same-timestamp events; the user's intent is
    # "skip deliberation," not "deliberate for zero seconds."
    skip_deliberation = (
        effective_delib_days is not None and float(effective_delib_days) == 0.0
    )
    initial_status = "voting" if skip_deliberation else "draft"
    now_at_create = _now() if skip_deliberation else None

    proposal = models.Proposal(
        title=body.title,
        body=body.body,
        author_id=current_user.id,
        org_id=org.id,
        sub_org_id=target_sub_org.id if target_sub_org else None,
        voting_method=body.voting_method,
        num_winners=body.num_winners,
        status=initial_status,
        deliberation_start=now_at_create,
        voting_start=now_at_create,
        voting_end=(
            now_at_create + timedelta(days=float(effective_vote_days))
            if skip_deliberation else None
        ),
        pass_threshold=effective_pass,
        quorum_threshold=effective_quorum,
        deliberation_days=effective_delib_days,
        voting_days=effective_vote_days,
        stable_result_required=body.stable_result_required,
        linked_polis_ids=linked_ids if linked_ids else None,
        # Phase 32.1 fixup: the org-scoped create endpoint was missed in
        # Phase 32 — it silently dropped the six per-proposal override
        # fields, leaving every proposal created via this path with
        # null overrides (forcing the F1 create-form toggles to be
        # ignored end-to-end). Pass them through so per-proposal
        # overrides survive the create call. The seed_pipeline path
        # already handles this directly.
        allow_write_in_options=body.allow_write_in_options,
        allow_write_ins_during_voting=body.allow_write_ins_during_voting,
        max_write_ins=body.max_write_ins,
        allow_pre_voting=body.allow_pre_voting,
        show_votes_during_deliberation=body.show_votes_during_deliberation,
        edit_lockout_fraction=body.edit_lockout_fraction,
    )
    db.add(proposal)
    db.flush()

    if skip_deliberation:
        # Single audit event (draft -> voting) for the skip path. Per
        # spec: the user's intent is "skip the phase," so the audit log
        # records one transition, not two.
        log_audit_event(
            db,
            action="proposal.status_changed",
            target_type="proposal",
            target_id=proposal.id,
            actor_id=current_user.id,
            details={
                "proposal_id": proposal.id,
                "old_status": "draft",
                "new_status": "voting",
                "trigger": "zero_day_deliberation_skip",
            },
            ip_address=request.client.host if request.client else None,
        )

    if body.stable_result_required is True:
        log_audit_event(
            db,
            action="proposal.stable_result_required_enabled",
            target_type="proposal",
            target_id=proposal.id,
            actor_id=current_user.id,
            details={"old_value": None, "new_value": True},
        )
    elif body.stable_result_required is False:
        log_audit_event(
            db,
            action="proposal.stable_result_required_disabled",
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

    # Phase 25 B2 — when the 0-day-deliberation skip fired, emit the
    # proposal.entered_voting notification path same as the advance flow
    # would. Wrapped in try/except so a notification failure never sinks
    # the create (matches the advance endpoint's pattern).
    if skip_deliberation:
        try:
            from routes.proposals import _emit_proposal_status_notifications
            _emit_proposal_status_notifications(
                db, background_tasks, proposal,
                old_status="draft", new_status="voting",
                actor_id=current_user.id,
            )
            db.commit()
        except Exception as e:  # noqa: BLE001
            log.warning(
                "proposal status emit failed on 0-day skip (draft -> voting): "
                "%s: %s", type(e).__name__, e,
            )
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass

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
    background_tasks: BackgroundTasks,
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
        # Phase 25 B1.1 — derive voting_end from proposal.voting_days (or
        # org default) when the body doesn't supply one. body.voting_end is
        # honored if present but logs a deprecation warning.
        from routes.proposals import _compute_voting_end_at_advance
        proposal.voting_end = _compute_voting_end_at_advance(
            voting_start=now,
            body_voting_end=body.voting_end,
            proposal=proposal,
            org=org,
        )
    elif next_status == "passed":
        from delegation_engine import engine as delegation_engine, ApprovalTally, RCVTally
        from routes.proposals import _maybe_resolve_tie
        tally = delegation_engine.compute_tally(proposal, db)
        if proposal.voting_method == "approval":
            if isinstance(tally, ApprovalTally) and tally.quorum_met(proposal.quorum_threshold) and tally.winners:
                _maybe_resolve_tie(
                    proposal, tally, "approval", db,
                    current_user_id=current_user.id,
                )
                next_status = "passed"
            else:
                next_status = "failed"
        elif proposal.voting_method == "ranked_choice":
            if isinstance(tally, RCVTally) and tally.quorum_met(proposal.quorum_threshold) and tally.winners:
                _maybe_resolve_tie(
                    proposal, tally, "ranked_choice", db,
                    current_user_id=current_user.id,
                )
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

    # Phase 13 B-emit — proposal.entered_voting / proposal.closed.
    try:
        from routes.proposals import _emit_proposal_status_notifications
        _emit_proposal_status_notifications(
            db, background_tasks, proposal, old_status, next_status,
            actor_id=current_user.id,
        )
        db.commit()
    except Exception as e:  # noqa: BLE001
        log.warning(
            "proposal status emit failed (%s -> %s): %s: %s",
            old_status, next_status, type(e).__name__, e,
        )
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass

    from routes.proposals import _build_proposal_out
    return _build_proposal_out(proposal, db)


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
            # Phase 20: ``extension_window_for`` was removed (the worker now
            # extends by the org's ``stable_window_fraction * original_voting
            # _duration``, computed inside the service layer). For admin-
            # driven escalation resolution we preserve the prior implicit
            # default — extend by the current voting-window span — so the
            # admin UI behaves the same when no explicit new_voting_end is
            # supplied.
            proposal.voting_end = (
                proposal.voting_end
                + (proposal.voting_end - proposal.voting_start)
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
    return _build_proposal_out(proposal, db)


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

    # Delegation patterns — Phase 18 (B2.2): switched from indirect
    # ``topic_id.in_(org_topic_ids)`` filtering to direct
    # ``Delegation.org_id == org.id``. Pre-fix the topic-indirect filter
    # was the one accidentally org-aware site, but it missed global
    # delegations (``topic_id IS NULL``); the direct ``org_id`` filter
    # catches both topic-scoped and global delegations cleanly.
    delegating_members = db.query(models.Delegation.delegator_id).filter(
        models.Delegation.org_id == org.id,
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
