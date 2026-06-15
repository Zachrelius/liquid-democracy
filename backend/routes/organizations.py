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
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError
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
from org_titles import seed_system_titles_for_org
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
        # Phase 45a hotfix #1 — OWNER_ONLY_KEYS (org.delete,
        # org.transfer_stewardship) are deliberately excluded from
        # PERMISSION_REGISTRY because they're hardcoded gates on
        # role.system_key=='steward' rather than matrix-routed. But the FE
        # useHasPermission hook reads only user_permissions, so prior to
        # this enrichment any UI gate using useHasPermission for these
        # keys resolved permanently False — including the Phase 45a F1
        # Danger Zone gate and F2 Stewardship section gate. has_permission
        # handles OWNER_ONLY_KEYS correctly (returns True iff steward), so
        # we just feed them through the same resolver.
        from role_permissions import OWNER_ONLY_KEYS
        for key in OWNER_ONLY_KEYS:
            if has_permission(db, user_id, org.id, key):
                user_permissions.append(key)

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
        # Phase 57 — surface the two new access axes on every OrgOut.
        # Fall back to today's effective defaults (`listed`,
        # `members_only`) for any pre-migration row that somehow lacks
        # them — the server_defaults make this defensive only.
        discoverability=org.discoverability or "listed",
        activity_visibility=org.activity_visibility or "members_only",
        settings=org.settings or {},
        parent_org_id=org.parent_org_id,
        created_at=org.created_at,
        member_count=member_count,
        user_role=user_role,
        user_permissions=user_permissions,
        branding=branding_out,
        # Phase 45b — surface the governance mode so the FE can render
        # the mode-aware controls (F1 switch, F2 conditional UI).
        governance_mode=org.governance_mode or "single_steward",
        # Phase 49a Cluster B — surface the simplified cosign-petition
        # toggle so the FE renders the single boolean control + the
        # ProposalForm cosign hint when relevant. Replaces the legacy
        # 3-way proposal_creation_mode enum.
        allow_cosign_petition=bool(
            (org.settings or {}).get("allow_cosign_petition", False)
        ) if org.settings else False,
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

    # Phase 59 D1 — block demo-stamped users from creating real orgs.
    # The demo-seed pipeline stamps personas with
    # `verification_provenance='demo_stub'`; `backdoor` is the
    # auxiliary admin-test marker. Both are demo-only identities and
    # neither should be able to create real organizations. The FE
    # hides the create-org affordance for these users; this is the
    # backend enforcement that catches a stale FE bundle or direct
    # API call.
    if current_user.verification_provenance in ("demo_stub", "backdoor"):
        raise HTTPException(
            status_code=403,
            detail=(
                "Demo accounts can't create organizations. Sign out and "
                "register a real account if you want to create one."
            ),
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

    # Phase 57 — pass the three access axes through. The OrgCreate
    # model_validator has already normalized any legacy join_policy
    # value AND filled in the implied discoverability, so the body
    # fields here are canonical. discoverability + activity_visibility
    # may still be None if the FE didn't send them and no legacy value
    # implied one; in that case we omit them and the column's
    # server_default ('listed' / 'members_only') applies.
    org_kwargs = dict(
        name=body.name,
        slug=body.slug,
        description=body.description,
        join_policy=body.join_policy,
        settings=DEFAULT_ORG_SETTINGS.copy(),
    )
    if body.discoverability is not None:
        org_kwargs["discoverability"] = body.discoverability
    if body.activity_visibility is not None:
        org_kwargs["activity_visibility"] = body.activity_visibility
    org = models.Organization(**org_kwargs)
    db.add(org)
    db.flush()

    # Phase 12 Stage 1: seed the four preset Role rows + their default
    # RolePermission grants for this brand-new org BEFORE creating the
    # creator's OrgMembership (so we have a Steward role to point role_id at).
    roles_by_key = seed_default_roles_for_org(db, org.id)

    # Phase 47 B5 — seed the two system titles per D6. These are a
    # label layer over the existing roles, NOT a separate permission
    # path. The role is still the source of truth for permissions and
    # the cardinality floor.
    seed_system_titles_for_org(db, org.id)

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
    # Phase 57 — discoverability + activity_visibility on PATCH. The
    # OrgUpdate model_validator has already normalized any legacy
    # join_policy literal and filled in implied discoverability if the
    # caller didn't set it explicitly.
    if body.discoverability is not None:
        org.discoverability = body.discoverability
    if body.activity_visibility is not None:
        org.activity_visibility = body.activity_visibility
    # Phase 49a Cluster B — `proposal_creation_mode` body field
    # removed; the new control is `settings.allow_cosign_petition`,
    # handled by the generic settings-merge below.
    if body.settings is not None:
        # Phase 46 — validate cosign config shape before merge so a bad
        # value fails the whole PATCH cleanly (matches the existing
        # default-threshold / tie_resolution validators below).
        if "cosign" in body.settings:
            from cosign import normalize_config_input
            body.settings["cosign"] = normalize_config_input(body.settings["cosign"])
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

        # Phase 56 B4 — topic_guidance + topic_categories_enabled
        # validation. Same pre-merge fail-cleanly shape as the threshold
        # validators above: a bad value short-circuits the whole PATCH.
        if "topic_guidance" in body.settings:
            tg = body.settings["topic_guidance"]
            if tg is not None and not isinstance(tg, str):
                raise HTTPException(
                    status_code=400,
                    detail="topic_guidance must be a string",
                )
            if isinstance(tg, str) and len(tg) > 5000:
                raise HTTPException(
                    status_code=400,
                    detail="topic_guidance exceeds 5000-character maximum length",
                )
        if "topic_categories_enabled" in body.settings:
            tce = body.settings["topic_categories_enabled"]
            if not isinstance(tce, bool):
                raise HTTPException(
                    status_code=400,
                    detail="topic_categories_enabled must be a boolean",
                )

        # Phase 59 B1 — org-defined topic categories list. JSON array of
        # strings, each ≤80 chars (matches Topic.category column width),
        # ≤50 entries, deduplicated. The org's topic-edit dropdown
        # populates from this list when the toggle is on. Legacy free-
        # text Topic.category values remain on rows and are surfaced
        # with a "(not in list)" marker by the FE; this validator does
        # NOT enforce that existing values conform to the new list.
        if "topic_categories" in body.settings:
            tc = body.settings["topic_categories"]
            if not isinstance(tc, list):
                raise HTTPException(
                    status_code=400,
                    detail="topic_categories must be a list of strings",
                )
            if len(tc) > 50:
                raise HTTPException(
                    status_code=400,
                    detail="topic_categories may contain at most 50 entries",
                )
            cleaned: list[str] = []
            seen: set[str] = set()
            for entry in tc:
                if not isinstance(entry, str):
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "topic_categories entries must be strings"
                        ),
                    )
                stripped = entry.strip()
                if not stripped:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "topic_categories entries must be non-empty"
                        ),
                    )
                if len(stripped) > 80:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "topic_categories entries must be ≤80 chars"
                        ),
                    )
                key = stripped.lower()
                if key in seen:
                    # Silently de-dup on case-insensitive match — drop
                    # the duplicate rather than 400'ing (user-friendly).
                    continue
                seen.add(key)
                cleaned.append(stripped)
            body.settings["topic_categories"] = cleaned

        # Phase 65 — org-wide delegation master switch validation. Same
        # pre-merge fail-cleanly shape: `delegation` must be an object
        # and `delegation.enabled` (when present) must be a boolean. The
        # key is read-time-defaulted (absent ⇒ enabled) so no backfill
        # exists for orgs that never touch it.
        if "delegation" in body.settings:
            dele = body.settings["delegation"]
            if not isinstance(dele, dict):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "delegation must be an object, e.g. "
                        '{"enabled": false}'
                    ),
                )
            if "enabled" in dele and not isinstance(dele["enabled"], bool):
                raise HTTPException(
                    status_code=400,
                    detail="delegation.enabled must be a boolean",
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

        # Phase 49a A1 — multi_admin_approval lockdown. Weakening
        # changes to the approval config (disable, threshold decrease,
        # known wrapped-action removal) must themselves be ratified
        # through the approval workflow they're trying to disarm. First-
        # enable (false→true) + strengthening + window-only changes
        # still apply directly. The check pops the multi_admin_approval
        # block out of the patch BEFORE the merge so the rest of the
        # settings still apply directly; the multi_admin_approval block
        # is then either re-injected (if non-weakening) or routed to a
        # pending action (if weakening + currently enabled).
        approval_submitted_action = None
        if "multi_admin_approval" in body.settings:
            from pending_actions import (
                engine as _p44_engine, settings as _p44_settings,
            )
            proposed_block = body.settings.pop("multi_admin_approval")
            normalized_proposed = _p44_settings.normalize_config_input(proposed_block)
            current_block = (org.settings or {}).get("multi_admin_approval", {})
            if not isinstance(current_block, bool) and not isinstance(current_block, dict):
                current_block = {}
            currently_enabled = (
                isinstance(current_block, dict)
                and bool(current_block.get("enabled", False))
            )
            is_weakening = (
                isinstance(current_block, dict)
                and _p44_settings.is_weakening_change(current_block, normalized_proposed)
            )
            if currently_enabled and is_weakening:
                # Route through the approval workflow being weakened.
                # Note: submit_pending_action calls
                # _validate_approval_config_change which re-checks
                # weakness — defensive double-check.
                ip = request.client.host if request.client else None
                result = _p44_engine.submit_pending_action(
                    db, org, current_user, "org.approval_config_change",
                    {"new_config": normalized_proposed},
                    ip_address=ip,
                )
                # If executed_directly returns True the action was
                # auto-ratified (e.g. threshold==1 + initiator-counts);
                # in that case the executor already wrote the new config.
                # Otherwise the action is pending — config unchanged.
                if not result.executed_directly:
                    approval_submitted_action = result.pending_action
            else:
                # Strengthening / first-enable / window-only change OR
                # any change while disabled — apply directly.
                body.settings["multi_admin_approval"] = normalized_proposed

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


class _OrgDeleteBody(BaseModel):
    confirmation: Optional[str] = None


class _TransferStewardshipBody(BaseModel):
    """Phase 45a B3 — body for POST /api/orgs/{slug}/transfer-stewardship."""
    target_user_id: str


class _GovernanceModeBody(BaseModel):
    """Phase 45b B2 — body for POST /api/orgs/{slug}/governance-mode.

    ``mode`` is the target mode. When switching FROM admin_council back
    TO single_steward, ``successor_user_id`` names the admin who claims
    the Steward seat. When switching FROM single_steward to council mode
    the caller (current Steward) atomically demotes to admin; no
    successor is needed.
    """
    mode: str
    successor_user_id: Optional[str] = None


@router.post("/{org_slug}/transfer-stewardship")
def transfer_stewardship(
    org_slug: str,
    body: _TransferStewardshipBody,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_owner),
):
    """Phase 45a B3 — voluntary stewardship handoff.

    Atomic role swap (D1): the outgoing steward becomes Admin; the
    named ``target_user_id`` (must be an active member of this org)
    becomes Steward. Steward-only initiation; gated by
    ``require_org_owner`` which matches the ``org.transfer_stewardship``
    OWNER_ONLY_KEY (Phase 12 D4) that has been declared since Phase 12
    but had no consuming route until now.

    Per D3, this is the structurally-safe path: the swap is atomic, so
    the org never observes a zero-steward state.
    """
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    target_membership = db.query(models.OrgMembership).filter(
        models.OrgMembership.org_id == org.id,
        models.OrgMembership.user_id == body.target_user_id,
        models.OrgMembership.status == "active",
    ).first()
    if target_membership is None:
        raise HTTPException(
            status_code=400,
            detail="Target must be an active member of this organization.",
        )

    target_user = db.get(models.User, body.target_user_id)
    if target_user is None or not target_user.is_active:
        raise HTTPException(
            status_code=400,
            detail="Target user's account must be active.",
        )

    if body.target_user_id == current_user.id:
        raise HTTPException(
            status_code=400,
            detail="You cannot transfer stewardship to yourself.",
        )

    # Phase 52 Stage 1 — verification role-grant gate. Target user
    # must satisfy the steward floor; otherwise the swap aborts +
    # the existing steward keeps the role (governance floor
    # preserved naturally). Phase 52j J1 — also residency-scope.
    from verification import check_role_grant_floor, check_role_residency_for_grant
    check_role_grant_floor(target_user, org, "steward")
    check_role_residency_for_grant(target_user, org, "steward")

    # Resolve the Admin + Steward role ids for this org.
    steward_role_id = _resolve_role_id_by_system_key(db, org.id, "steward")
    admin_role_id = _resolve_role_id_by_system_key(db, org.id, "admin")
    if steward_role_id is None or admin_role_id is None:
        raise HTTPException(
            status_code=500,
            detail="Org is missing the preset Steward or Admin role",
        )

    # Atomic swap: outgoing steward → admin, target → steward.
    outgoing_membership = membership
    outgoing_membership.role_id = admin_role_id
    target_membership.role_id = steward_role_id

    log_audit_event(
        db,
        action="org.stewardship_transferred",
        target_type="organization",
        target_id=org.id,
        actor_id=current_user.id,
        details={
            "outgoing_steward_id": current_user.id,
            "incoming_steward_id": body.target_user_id,
        },
        ip_address=request.client.host if request.client else None,
    )

    db.commit()
    return {
        "status": "ok",
        "outgoing_steward_id": current_user.id,
        "incoming_steward_id": body.target_user_id,
    }


@router.post("/{org_slug}/governance-mode")
def change_governance_mode(
    org_slug: str,
    body: _GovernanceModeBody,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_admin),
):
    """Phase 45b B2 — switch the org's governance mode.

    Two directions:
      * ``single_steward → admin_council`` (D1/D2): caller must be the
        current Steward. The Steward atomically demotes to admin and
        the mode flips, in one transaction. After the switch there is
        no steward and at least one admin (the former steward).
      * ``admin_council → single_steward`` (D3): caller must be an
        admin. The body's ``successor_user_id`` names the admin who
        claims the new Steward seat (defaults to the caller). Atomic:
        the named admin's role flips to steward and the mode flips.

    Mode switch is NOT gated by Phase 44 multi-admin approval (D1 —
    less dramatic than org.delete, which is steward-only/any-admin per
    mode). In-mode high-stakes actions still defer to Phase 44 when
    that opt-in is on.
    """
    from governance import (
        mode_of, SINGLE_STEWARD, ADMIN_COUNCIL, VALID_MODES,
    )

    if body.mode not in VALID_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown governance mode: {body.mode!r}",
        )

    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug,
    ).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    current_mode = mode_of(org)
    if body.mode == current_mode:
        # Idempotent no-op.
        return {"status": "ok", "mode": current_mode, "changed": False}

    actor_role = membership_role_system_key(membership)
    ip = request.client.host if request.client else None

    if current_mode == SINGLE_STEWARD and body.mode == ADMIN_COUNCIL:
        # D2 — steward-initiated; the steward demotes to admin
        # atomically with the mode flip.
        if actor_role != "steward":
            raise HTTPException(
                status_code=403,
                detail="Only the Steward can switch to admin_council mode.",
            )
        admin_role_id = _resolve_role_id_by_system_key(db, org.id, "admin")
        if admin_role_id is None:
            raise HTTPException(
                status_code=500,
                detail="Org is missing the preset Admin role",
            )
        membership.role_id = admin_role_id
        org.governance_mode = ADMIN_COUNCIL
        log_audit_event(
            db,
            action="org.governance_mode_changed",
            target_type="organization",
            target_id=org.id,
            actor_id=current_user.id,
            details={
                "from": SINGLE_STEWARD,
                "to": ADMIN_COUNCIL,
                "demoted_user_id": current_user.id,
            },
            ip_address=ip,
        )
        db.commit()
        return {
            "status": "ok",
            "mode": ADMIN_COUNCIL,
            "changed": True,
            "demoted_user_id": current_user.id,
        }

    # current_mode == ADMIN_COUNCIL and body.mode == SINGLE_STEWARD
    # D3 — admin-initiated; the named admin (default: caller) claims
    # the steward seat atomically with the mode flip.
    if actor_role != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only an Admin can switch the org back to single_steward mode.",
        )
    successor_user_id = body.successor_user_id or current_user.id
    successor_membership = db.query(models.OrgMembership).filter(
        models.OrgMembership.org_id == org.id,
        models.OrgMembership.user_id == successor_user_id,
        models.OrgMembership.status == "active",
    ).first()
    if successor_membership is None:
        raise HTTPException(
            status_code=400,
            detail="Successor must be an active admin of this organization.",
        )
    successor_user = db.get(models.User, successor_user_id)
    if successor_user is None or not successor_user.is_active:
        raise HTTPException(
            status_code=400,
            detail="Successor's account must be active.",
        )
    if membership_role_system_key(successor_membership) != "admin":
        raise HTTPException(
            status_code=400,
            detail="Successor must currently hold the Admin role.",
        )

    # Phase 52 Stage 1 — verification role-grant gate. Successor
    # becomes Steward; must satisfy that role's floor. Existing
    # admin tier remains unchanged on block. Phase 52j J1 — also
    # residency-scope.
    from verification import check_role_grant_floor, check_role_residency_for_grant
    check_role_grant_floor(successor_user, org, "steward")
    check_role_residency_for_grant(successor_user, org, "steward")

    # Phase 48 Stage 3 D12 — direct council→single_steward revert
    # requires multi-admin sign-off when Phase 44 is enabled for the
    # ``org.governance_mode_revert`` action. The elected-revert path
    # (electing a steward in council mode) bypasses this — the
    # election itself is the multi-admin ratification, surfaced via
    # `elections._flip_mode_to_single_steward` with via='elected_revert'.
    from pending_actions import engine as p44_engine, settings as p44_settings
    if p44_settings.is_action_wrapped(org, "org.governance_mode_revert"):
        result = p44_engine.submit_pending_action(
            db, org, current_user, "org.governance_mode_revert",
            {"successor_user_id": successor_user_id},
            ip_address=ip,
        )
        db.commit()
        if result.executed_directly:
            return {
                "status": "ok",
                "mode": SINGLE_STEWARD,
                "changed": True,
                "promoted_user_id": successor_user_id,
            }
        db.refresh(result.pending_action)
        return {
            "status": "submitted_for_approval",
            "pending_action": p44_engine.serialize_pending(
                db, result.pending_action, viewer_id=current_user.id,
            ),
        }

    steward_role_id = _resolve_role_id_by_system_key(db, org.id, "steward")
    if steward_role_id is None:
        raise HTTPException(
            status_code=500,
            detail="Org is missing the preset Steward role",
        )
    successor_membership.role_id = steward_role_id
    org.governance_mode = SINGLE_STEWARD
    log_audit_event(
        db,
        action="org.governance_mode_changed",
        target_type="organization",
        target_id=org.id,
        actor_id=current_user.id,
        details={
            "from": ADMIN_COUNCIL,
            "to": SINGLE_STEWARD,
            "via": "direct",
            "promoted_user_id": successor_user_id,
        },
        ip_address=ip,
    )
    db.commit()
    return {
        "status": "ok",
        "mode": SINGLE_STEWARD,
        "changed": True,
        "promoted_user_id": successor_user_id,
    }


@router.delete("/{org_slug}")
def delete_organization(
    org_slug: str,
    request: Request,
    body: Optional[_OrgDeleteBody] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_owner),
):
    """Delete org (requires Steward).

    Phase 44 — wrapped under multi-admin approval when enabled. The
    request body may include a ``confirmation`` field (= org slug) to
    satisfy the pending-action payload validator; this is optional when
    approval is OFF (the direct path matches the live pre-Phase-44
    behavior of any-Steward-can-delete).
    """
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    from pending_actions import engine as p44_engine, settings as p44_settings
    if p44_settings.is_action_wrapped(org, "org.delete"):
        ip = request.client.host if request.client else None
        confirmation = body.confirmation if body is not None else None
        result = p44_engine.submit_pending_action(
            db, org, current_user, "org.delete",
            {"confirmation": confirmation},
            ip_address=ip,
        )
        db.commit()
        if result.executed_directly:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        db.refresh(result.pending_action)
        return {
            "status": "submitted_for_approval",
            "pending_action": p44_engine.serialize_pending(
                db, result.pending_action, viewer_id=current_user.id,
            ),
        }

    db.delete(org)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    # Phase 47 B4 — resolve held titles for each member (system titles
    # from role + custom titles from org_title_assignments).
    from org_titles import held_titles_for_member
    # Phase 52e Stage 2 E3 — derived per-org verified status. The
    # predicate is evaluated per-member; it's a read against the org
    # settings + user.verification_state + the OrgDuplicateFlag table.
    import verification_flags
    result = []
    for m in memberships:
        user = db.get(models.User, m.user_id)
        if user:
            role_key = membership_role_system_key(m) or "member"
            # Phase 52f — surface the per-org effective display name
            # via the resolver. Members.jsx + every other surface that
            # reads this list now reflects the per-org override.
            import verification as _verification
            effective_display_name = _verification.display_name_for(
                user, org, membership=m,
            )
            result.append(schemas.OrgMemberOut(
                user_id=m.user_id,
                username=user.username,
                display_name=effective_display_name,
                email=user.email,
                avatar_url=user.avatar_url,
                # Phase 12 — emit role.system_key (e.g. 'steward', 'admin');
                # the dropped string column would surface a Role ORM object.
                role=role_key,
                status=m.status,
                joined_at=m.joined_at,
                held_titles=held_titles_for_member(db, org.id, m.user_id, role_key),
                is_org_verified=verification_flags.is_org_verified(user, org, db),
            ))
    return result


@router.patch(
    "/{org_slug}/me/display-name",
    response_model=dict,
)
def set_my_org_display_name(
    org_slug: str,
    body: dict,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """Phase 52f — set the caller's per-org display name override.
    NULL / empty string clears the override (falls back to
    ``User.display_name``).

    Enforcement (per the locked Z decision — both options offered
    per org):
      * If the org has ``verification_require_name_match`` set to a
        non-``off`` mode, the new display name is validated against
        the caller's legal name via
        ``display_name_matches_legal``.
      * If the match fails AND the org's
        ``verification_name_match_action`` is ``block`` (default),
        the write is REJECTED with 422 ``name_match_required``.
      * If the match fails AND the action is ``flag``, the write
        proceeds and an audit row ``org.display_name_mismatch`` is
        logged so the admin sees it.

    A user with no legal name on file (unverified) is unconstrained
    — the verification floor is what forces verification first; the
    name-match is an ADDITIONAL constraint layered on top.
    """
    import verification as _verification
    org = db.get(models.Organization, membership.org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    raw = body.get("display_name") if isinstance(body, dict) else None
    new_name: Optional[str]
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        new_name = None
    elif isinstance(raw, str):
        new_name = raw.strip()
        if len(new_name) > 80:
            raise HTTPException(
                status_code=400,
                detail="Display name must be 80 characters or fewer.",
            )
    else:
        raise HTTPException(status_code=400, detail="Invalid display_name")

    mode = _verification.get_org_name_match_mode(org)
    if mode != _verification.NAME_MATCH_OFF and new_name is not None:
        passes = _verification.display_name_matches_legal(
            new_name, current_user, org,
        )
        if not passes:
            action = _verification.get_org_name_match_action(org)
            if action == _verification.NAME_MATCH_ACTION_BLOCK:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": "name_match_required",
                        "mode": mode,
                    },
                )
            # flag mode — allow + audit
            log_audit_event(
                db,
                action="org.display_name_mismatch",
                target_type="organization",
                target_id=org.id,
                actor_id=current_user.id,
                details={
                    "org_id": org.id,
                    "user_id": current_user.id,
                    "mode": mode,
                    "candidate_display_name": new_name,
                },
                ip_address=request.client.host if request.client else None,
            )

    membership.display_name = new_name
    db.commit()
    return {
        "display_name": _verification.display_name_for(
            current_user, org, membership=membership,
        ),
        "override_set": new_name is not None,
    }


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
    # Phase 12 / 45b — top governing tier is protected from demotion via
    # this endpoint. In single_steward mode that's Steward (today's rule).
    # In admin_council mode, the last admin must remain; demoting a
    # non-last admin to a lower role is permitted.
    current_role_key = membership_role_system_key(m)
    if current_role_key == "steward":
        raise HTTPException(status_code=400, detail="Cannot change Steward role")
    # Phase 45b D6 — in admin_council mode, demoting the LAST active
    # admin would drop the org below the floor; block that path.
    from governance import mode_of, ADMIN_COUNCIL, count_active_governors
    if current_role_key == "admin" and mode_of(org) == ADMIN_COUNCIL:
        new_system_key = _INV_ROLE_TO_SYSTEM_KEY.get(body.role, body.role)
        if new_system_key != "admin":
            other_governors = count_active_governors(
                db, org, exclude_user_id=m.user_id,
            )
            if other_governors == 0:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot demote the last admin of this organization.",
                )
    new_system_key = _INV_ROLE_TO_SYSTEM_KEY.get(body.role, body.role)
    new_role_id = _resolve_role_id_by_system_key(
        db, org.id, new_system_key,
    )
    if new_role_id is None:
        raise HTTPException(status_code=400, detail=f"Unknown role '{body.role}'")
    # Phase 52 Stage 1 — verification role-grant gate. Block the
    # mutation when the target user doesn't satisfy the floor for
    # the destination role. Existing role-holder keeps their role on
    # block; the governance-floor invariant is preserved by
    # construction (no demote happens). The check goes BEFORE the
    # role_id write. Phase 52j J1 — also residency-scope.
    from verification import check_role_grant_floor, check_role_residency_for_grant
    target_user = db.get(models.User, m.user_id)
    if target_user is not None:
        check_role_grant_floor(target_user, org, new_system_key)
        check_role_residency_for_grant(target_user, org, new_system_key)
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


class _MemberRemoveBody(BaseModel):
    # Phase 45a B2 — optional successor required when removing the org's
    # sole (inactive) steward. Ignored for non-steward removals.
    successor_user_id: Optional[str] = None


@router.delete("/{org_slug}/members/{user_id}")
def remove_member(
    org_slug: str,
    user_id: str,
    request: Request,
    body: Optional[_MemberRemoveBody] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    admin_membership: models.OrgMembership = Depends(require_org_admin),
):
    """Remove member (requires admin).

    Phase 44 — when the org has opted in to multi-admin approval and the
    ``member.remove`` action is wrapped, the destructive mutation is
    deferred to the ratification queue and this endpoint returns a
    ``submitted_for_approval`` response instead of executing.

    Phase 45a — an inactive steward (User.is_active=False) may be removed
    as a recovery action. If removal would leave the org steward-less,
    the request body must include ``successor_user_id`` naming an active
    member to atomically promote to Steward in the same transaction.
    """
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()

    successor_user_id = body.successor_user_id if body is not None else None

    # Phase 44 intercept — when approval is on, hand off to the engine.
    from pending_actions import engine as p44_engine, settings as p44_settings
    if p44_settings.is_action_wrapped(org, "member.remove"):
        ip = request.client.host if request.client else None
        payload: dict = {"target_user_id": user_id}
        if successor_user_id:
            payload["successor_user_id"] = successor_user_id
        result = p44_engine.submit_pending_action(
            db, org, current_user, "member.remove",
            payload,
            ip_address=ip,
        )
        db.commit()
        if result.executed_directly:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        db.refresh(result.pending_action)
        return {
            "status": "submitted_for_approval",
            "pending_action": p44_engine.serialize_pending(
                db, result.pending_action, viewer_id=current_user.id,
            ),
        }

    # Phase 71b — config-authoritative on the DIRECT path only (the Phase 44
    # engine path above already gates the initiator on "member.remove" via
    # required_permission_key). Floor is admin+ (require_org_admin Depends).
    if org is not None and not has_permission(
        db, current_user.id, org.id, "member.remove"
    ):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to remove members from this organization.",
        )

    # Direct path — delegate to the shared executor so the inactive-steward
    # recovery logic + audit emission lives in one place.
    from pending_actions.registry import execute_member_remove
    execute_member_remove(
        db, org, user_id,
        successor_user_id=successor_user_id,
        actor_id=current_user.id,
        ip_address=request.client.host if request.client else None,
    )
    # Phase 45b B4 — detect + audit zero-governor recovery condition.
    from governance import check_and_audit_rebootstrap
    check_and_audit_rebootstrap(
        db, org,
        actor_id=current_user.id,
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    # ---- Phase 71a — CANONICAL CONFIG-AUTHORITATIVE ENFORCEMENT PATTERN ----
    # The tier `Depends(require_org_*)` above stays as a cheap pre-filter /
    # FLOOR (a plain member can never reach this action — the escalation
    # invariant). On top of the floor, the org's own `role_permissions`
    # config decides, via `has_permission`, which is per-org and already
    # correct on sub-orgs. Add this check AFTER `org` is resolved; raise 403
    # naming the capability. 71b copies this exact shape to the remaining
    # tier-gated routes. (Greppable on purpose: `has_permission(..., "<key>")`
    # must appear literally at each converted call site — Phase 69 audit's
    # own success criterion.)
    if org is not None and not has_permission(
        db, current_user.id, org.id, "member.suspend"
    ):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to suspend members in this organization.",
        )
    m = db.query(models.OrgMembership).filter(
        models.OrgMembership.org_id == org.id,
        models.OrgMembership.user_id == user_id,
    ).first()
    if not m:
        raise HTTPException(status_code=404, detail="Member not found")
    # Phase 12 / 45b — top governing tier cannot be suspended. In
    # single_steward mode that's Steward (today's rule). In
    # admin_council mode, the last admin cannot be suspended either
    # (D6 floor — suspending leaves zero active governors).
    current_role_key = membership_role_system_key(m)
    if current_role_key == "steward":
        raise HTTPException(status_code=400, detail="Cannot suspend the Steward")
    from governance import mode_of, ADMIN_COUNCIL, count_active_governors
    if current_role_key == "admin" and mode_of(org) == ADMIN_COUNCIL:
        other_governors = count_active_governors(
            db, org, exclude_user_id=m.user_id,
        )
        if other_governors == 0:
            raise HTTPException(
                status_code=400,
                detail="Cannot suspend the last admin of this organization.",
            )
    m.status = "suspended"
    # Phase 45b B4 — detect + audit zero-governor recovery condition.
    # Suspension drops the user out of the active-governor count.
    from governance import check_and_audit_rebootstrap
    check_and_audit_rebootstrap(db, org, actor_id=current_user.id)
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
    # Phase 57 — was `join_policy == 'invite_only_secret'`; now keys on
    # the discoverability axis so an org whose access posture is
    # (any join_policy, hidden) 404s the public landing exactly as the
    # legacy secret check did.
    if org is None or org.discoverability == "hidden":
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
        # Phase 57 — included so the FE can decide whether to render
        # the public proposal-list panel without a second API call.
        activity_visibility=org.activity_visibility or "members_only",
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
# Phase 55 — Public org discovery endpoint (NO AUTH)
# ============================================================================
#
# Surfaces the directory of discoverable public orgs at /explore. Filters:
# join_policy != 'invite_only_secret' (secret orgs stay hidden, mirroring
# the Phase 14 404-for-secret posture), is_demo=False (demo orgs live at
# /demo, not /explore), parent_org_id IS NULL (sub-orgs are not standalone
# discoverable). Search across name + description (case-insensitive).
# Sorts: members (DESC member_count) or activity (DESC most-recent proposal
# created_at, NULLS LAST). Default: activity. Cap 200 (no pagination v1).
#
# Projection is deliberately minimal — does NOT expose settings,
# user_permissions, governance_mode, member identities, or any per-user
# fields. See schemas.ExploreOrgCard.

# Phase 55 — defensive cap to avoid pathological payload growth before
# pagination ships. With a handful of public orgs at launch this is far
# above the realistic ceiling; when the platform grows past it the
# follow-up is to add cursor pagination, not bump the constant.
EXPLORE_RESULT_CAP = 200


@public_org_router.get("/explore", response_model=schemas.ExploreResponse)
def get_explore_orgs(
    response: Response,
    q: Optional[str] = Query(default=None),
    sort: str = Query(default="activity"),
    db: Session = Depends(get_db),
):
    """Phase 55 — list discoverable public orgs for the /explore page.

    No auth required; logged-in callers get the same response. The
    projection is intentionally small and public-safe — see
    schemas.ExploreOrgCard.

    Filters (all required, applied as AND):
      * join_policy != 'invite_only_secret' — secret orgs are hidden.
      * is_demo == False — demo orgs live at /demo.
      * parent_org_id IS NULL — sub-orgs are not independently discoverable.

    Search: when ``q`` is provided, matches case-insensitively against
    name OR description. Empty/absent q returns the full discoverable set.

    Sort:
      * 'members' — descending member_count, then name ASC.
      * 'activity' (default) — descending most-recent proposal
        created_at, NULLS LAST (orgs with zero proposals sort last),
        then name ASC.

    Unknown ``sort`` values fall back to the default ('activity') rather
    than 400'ing — keeps the public endpoint forgiving against typo'd
    bookmarks. The result set is capped at EXPLORE_RESULT_CAP=200 (no
    pagination in v1).

    Caching: ``Cache-Control: max-age=60``. Data changes slowly
    (member counts and proposal recency shift gradually); a brief
    cache absorbs burst traffic on the discovery page without staleness
    becoming user-visible. Mirrors the /demo endpoint's posture.
    """
    # Grouped aggregates avoid N+1: one subquery for member counts,
    # one for activity recency. Both LEFT JOIN onto the org query so
    # orgs with zero members or zero proposals still appear (with 0
    # count and NULL activity respectively).
    member_count_subq = (
        db.query(
            models.OrgMembership.org_id.label("org_id"),
            func.count(models.OrgMembership.id).label("member_count"),
        )
        .filter(models.OrgMembership.status == "active")
        .group_by(models.OrgMembership.org_id)
        .subquery()
    )
    activity_subq = (
        db.query(
            models.Proposal.org_id.label("org_id"),
            func.max(models.Proposal.created_at).label("last_proposal_at"),
        )
        .group_by(models.Proposal.org_id)
        .subquery()
    )

    base = (
        db.query(
            models.Organization,
            func.coalesce(member_count_subq.c.member_count, 0).label("mc"),
            activity_subq.c.last_proposal_at.label("la"),
        )
        .outerjoin(
            member_count_subq,
            member_count_subq.c.org_id == models.Organization.id,
        )
        .outerjoin(
            activity_subq,
            activity_subq.c.org_id == models.Organization.id,
        )
        # Phase 57 — was `join_policy != 'invite_only_secret'`; now keys
        # on the discoverability axis. Only orgs whose steward has set
        # discoverability='listed' appear here. `unlisted` orgs serve
        # their /{slug} splash by direct link but stay off the index;
        # `hidden` orgs 404 the splash entirely.
        .filter(models.Organization.discoverability == "listed")
        .filter(models.Organization.is_demo.is_(False))
        .filter(models.Organization.parent_org_id.is_(None))
    )

    if q:
        # Case-insensitive substring match on either name or description.
        # ``ilike`` is PG-native and translates to LIKE-with-LOWER on
        # SQLite via SQLAlchemy. Description column may be NULL on some
        # rows — the OR with the name match keeps the filter correct in
        # that case (NULL ilike returns NULL/false, which doesn't bias
        # the overall predicate against name-only matches).
        like = f"%{q}%"
        from sqlalchemy import or_
        base = base.filter(
            or_(
                models.Organization.name.ilike(like),
                models.Organization.description.ilike(like),
            )
        )

    if sort == "members":
        base = base.order_by(
            func.coalesce(member_count_subq.c.member_count, 0).desc(),
            models.Organization.name.asc(),
        )
    else:
        # Default + unknown sort param both fall through to 'activity'.
        # ``coalesce(last_proposal_at, <epoch>)`` is the cross-dialect
        # NULLS-LAST pattern (SQLite doesn't support PG's NULLS LAST
        # modifier directly); a sentinel epoch sorts before any real
        # timestamp under DESC, putting zero-proposal orgs at the end.
        epoch_sentinel = datetime(1970, 1, 1)
        base = base.order_by(
            func.coalesce(
                activity_subq.c.last_proposal_at, epoch_sentinel,
            ).desc(),
            models.Organization.name.asc(),
        )

    rows = base.limit(EXPLORE_RESULT_CAP).all()

    cards: list[schemas.ExploreOrgCard] = []
    for org, mc, _la in rows:
        branding_dict = (org.settings or {}).get("branding") or {}
        cards.append(schemas.ExploreOrgCard(
            slug=org.slug,
            name=org.name,
            description=org.description or "",
            governance_type=org.governance_type,
            join_policy=org.join_policy,
            member_count=int(mc or 0),
            logo_url=branding_dict.get("logo_url"),
            branding=schemas.OrgPublicBrandingOut(
                primary_color=branding_dict.get("primary_color"),
                accent_color=branding_dict.get("accent_color"),
            ),
        ))

    response.headers["Cache-Control"] = "max-age=60"
    return schemas.ExploreResponse(orgs=cards, count=len(cards))


# ============================================================================
# Phase 57 — Public activity surface (anon-allowed when activity_visibility='public')
# ============================================================================
#
# When an org's steward has set ``activity_visibility='public'``, non-
# members may read the org's proposal list + per-proposal detail +
# comments at the public sibling endpoints below. The default
# (``members_only``) returns 404 — byte-for-byte the same response as
# for a non-existent org, mirroring the discoverability=hidden posture.
#
# Individual delegate-vote rendering still routes through the
# Phase 30.3 ``can_see_votes`` gate; this surface does NOT bypass it.
# Participation (voting, commenting) still requires membership at the
# member-scoped endpoints — these public endpoints are READ-ONLY.

def _public_activity_org_or_404(
    db: Session, org_slug: str,
) -> models.Organization:
    """Resolve an org for the public activity surface.

    Returns the org IFF discoverability is non-hidden AND
    activity_visibility=='public'. Otherwise raises 404 — the same
    response shape as for a non-existent org, so an unauthenticated
    probe of a members-only org learns nothing.
    """
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug,
    ).first()
    if org is None or org.discoverability == "hidden":
        raise HTTPException(status_code=404, detail="Organization not found")
    if org.activity_visibility != "public":
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


@public_org_router.get(
    "/{org_slug}/public/proposals",
    response_model=list[schemas.ProposalOut],
)
def list_public_org_proposals(
    org_slug: str,
    status_filter: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
):
    """Phase 57 B5 — list an org's proposals to anonymous viewers when
    the org has ``activity_visibility='public'``. Returns 404 for any
    other access posture.

    Reuses ``_build_proposal_out`` so the projection is byte-identical
    to the member-scoped list endpoint. Sub-org proposals are excluded
    here (the public surface is parent-org only; sub-org public exposure
    is out of scope for Phase 57).
    """
    org = _public_activity_org_or_404(db, org_slug)
    # Phase 57 — top-level proposals only on the public surface.
    q = db.query(models.Proposal).filter(
        models.Proposal.org_id == org.id,
        models.Proposal.sub_org_id.is_(None),
    )
    if status_filter:
        q = q.filter(models.Proposal.status == status_filter)
    # Phase 31 F1 — three-tier ordering (voting → deliberation → closed).
    from routes.proposals import (
        _proposal_list_ordering as _f1_ordering, _build_proposal_out,
    )
    proposals = q.order_by(*_f1_ordering()).all()
    return [_build_proposal_out(p, db) for p in proposals]


@public_org_router.get(
    "/{org_slug}/public/proposals/{proposal_id}",
    response_model=schemas.ProposalOut,
)
def get_public_org_proposal(
    org_slug: str,
    proposal_id: str,
    db: Session = Depends(get_db),
):
    """Phase 57 B5 — proposal detail (body, options, status, voting
    method, and the effective deliberation-engagement flags) for an
    org with ``activity_visibility='public'``. Returns 404 otherwise.

    Aggregate tallies live at the sibling `/results` public endpoint
    below to keep the projection shapes parallel with the member
    endpoints. Individual delegate votes are NOT exposed here — those
    route through ``can_see_votes`` at the member-scoped endpoints
    only.
    """
    org = _public_activity_org_or_404(db, org_slug)
    proposal = db.query(models.Proposal).filter(
        models.Proposal.id == proposal_id,
        models.Proposal.org_id == org.id,
        models.Proposal.sub_org_id.is_(None),
    ).first()
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    from routes.proposals import _build_proposal_out
    return _build_proposal_out(proposal, db)


@public_org_router.get(
    "/{org_slug}/public/proposals/{proposal_id}/results",
    response_model=schemas.ProposalResults,
)
def get_public_org_proposal_results(
    org_slug: str,
    proposal_id: str,
    db: Session = Depends(get_db),
):
    """Phase 57 B5 — aggregate tally for a proposal in a public-activity
    org. Reuses the member-scoped ``get_results`` body verbatim; this
    is the public counterpart with no auth dep.

    Aggregate-only — no individual vote data ever flows through this
    endpoint regardless of org config.
    """
    org = _public_activity_org_or_404(db, org_slug)
    proposal = db.query(models.Proposal).filter(
        models.Proposal.id == proposal_id,
        models.Proposal.org_id == org.id,
        models.Proposal.sub_org_id.is_(None),
    ).first()
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    # Reuse the existing results-construction logic. Import locally to
    # avoid circular import at module load time.
    import delegation_engine
    from delegation_engine import ApprovalTally, RCVTally
    tally = delegation_engine.compute_tally(proposal, db)
    from sustained_majority_service import build_status as _sm_build_status
    sm_status = _sm_build_status(db, proposal, org)
    snapshots = (
        db.query(models.VoteSnapshot)
        .filter(models.VoteSnapshot.proposal_id == proposal_id)
        .order_by(models.VoteSnapshot.simulated_time)
        .all()
    )
    time_series = [
        schemas.SnapshotPoint(
            simulated_time=s.simulated_time,
            yes=s.yes_count, no=s.no_count, abstain=s.abstain_count,
            not_cast=s.not_cast_count, total_eligible=s.total_eligible,
        )
        for s in snapshots
    ]
    if proposal.voting_method == "approval" and isinstance(tally, ApprovalTally):
        from routes.proposals import _approval_winner_seats
        option_labels = {opt.id: opt.label for opt in proposal.options}
        return schemas.ProposalResults(
            proposal_id=proposal_id, voting_method="approval",
            not_cast=tally.not_cast, total_eligible=tally.total_eligible,
            votes_cast=tally.total_ballots_cast,
            quorum_met=tally.quorum_met(proposal.quorum_threshold),
            option_approvals=tally.option_approvals,
            option_labels=option_labels,
            total_ballots_cast=tally.total_ballots_cast,
            total_abstain=tally.total_abstain, winners=tally.winners,
            tied=tally.tied, tie_resolution=proposal.tie_resolution,
            # Phase 66 — multi-winner attribution + boundary-tie surface.
            winner_seats=_approval_winner_seats(tally, proposal),
            boundary_tied=list(tally.boundary_tied or []),
            seats_remaining=tally.seats_remaining,
            approval_winner_config=getattr(
                proposal, "approval_winner_config", None,
            ),
            time_series=time_series, sustained_majority=sm_status,
        )
    if proposal.voting_method == "ranked_choice" and isinstance(tally, RCVTally):
        option_labels = {opt.id: opt.label for opt in proposal.options}
        rounds_out = [
            schemas.RCVRoundOut(
                round_number=r.round_number,
                option_counts=r.option_counts,
                eliminated=r.eliminated, elected=r.elected,
                transferred_from=r.transferred_from,
                transfer_breakdown=r.transfer_breakdown,
            )
            for r in tally.rounds
        ]
        return schemas.ProposalResults(
            proposal_id=proposal_id, voting_method="ranked_choice",
            not_cast=tally.not_cast, total_eligible=tally.total_eligible,
            votes_cast=tally.total_ballots_cast,
            quorum_met=tally.quorum_met(proposal.quorum_threshold),
            option_labels=option_labels,
            total_ballots_cast=tally.total_ballots_cast,
            total_abstain=tally.total_abstain, winners=tally.winners,
            tied=tally.tied, tie_resolution=proposal.tie_resolution,
            rounds=rounds_out, method=tally.method,
            num_winners=tally.num_winners,
            time_series=time_series, sustained_majority=sm_status,
        )
    from budget_tally import AllocationTally
    if (
        proposal.voting_method == "budget_allocation"
        and isinstance(tally, AllocationTally)
    ):
        option_labels = {opt.id: opt.label for opt in proposal.options}
        cfg = getattr(proposal, "budget_config", None) or {}
        return schemas.ProposalResults(
            proposal_id=proposal_id, voting_method="budget_allocation",
            not_cast=tally.not_cast, total_eligible=tally.total_eligible,
            votes_cast=tally.total_ballots_cast,
            quorum_met=tally.quorum_met(proposal.quorum_threshold),
            option_labels=option_labels,
            total_ballots_cast=tally.total_ballots_cast,
            budget_amounts=tally.amounts,
            budget_total_allocated=tally.total_allocated,
            budget_unallocated_remainder=tally.unallocated_remainder,
            budget_degenerate_no_support=tally.degenerate_no_support,
            budget_envelope=cfg.get("envelope"),
            budget_currency=cfg.get("currency", "USD"),
            budget_aggregation=tally.aggregation,
            time_series=time_series, sustained_majority=sm_status,
        )
    return schemas.ProposalResults(
        proposal_id=proposal_id, voting_method="binary",
        yes=tally.yes, no=tally.no, abstain=tally.abstain,
        not_cast=tally.not_cast, total_eligible=tally.total_eligible,
        votes_cast=tally.total_ballots_cast,
        quorum_met=tally.quorum_met(proposal.quorum_threshold),
        winners=tally.winners, tied=tally.tied,
        tie_resolution=proposal.tie_resolution,
        time_series=time_series, sustained_majority=sm_status,
    )


@public_org_router.get(
    "/{org_slug}/public/proposals/{proposal_id}/comments",
    response_model=list[schemas.CommentOut],
)
def list_public_org_proposal_comments(
    org_slug: str,
    proposal_id: str,
    db: Session = Depends(get_db),
):
    """Phase 57 B5 — proposal comments for an org with
    ``activity_visibility='public'``. Read-only; posting still requires
    membership at the member-scoped POST endpoint."""
    org = _public_activity_org_or_404(db, org_slug)
    proposal = db.query(models.Proposal).filter(
        models.Proposal.id == proposal_id,
        models.Proposal.org_id == org.id,
        models.Proposal.sub_org_id.is_(None),
    ).first()
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    from routes.comments import _build_comment_out
    rows = (
        db.query(models.Comment)
        .filter(models.Comment.proposal_id == proposal_id)
        .order_by(models.Comment.created_at.asc())
        .all()
    )
    return [_build_comment_out(c) for c in rows]


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
    # Phase 57 — keys on discoverability axis (was `invite_only_secret`
    # check on join_policy). Hidden orgs 404 anonymously.
    if org is None or org.discoverability == "hidden":
        # Same 404 shape for non-existent and hidden orgs.
        raise HTTPException(status_code=404, detail="Organization not found")

    if org.join_policy == "invite":
        # Phase 57 — was `invite_only_public`; the join axis is now
        # disentangled from discoverability. An invite-policy org with
        # any non-hidden discoverability still requires an invitation
        # to join — the splash explains this, and this endpoint 403s
        # the join attempt loudly.
        raise HTTPException(
            status_code=403,
            detail="This organization requires an invitation.",
        )

    if org.join_policy not in ("approval", "open"):
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

    # Phase 52 Stage 1 — verification membership floor gate. Same
    # rationale as the legacy ``/join`` route: applies to BOTH
    # branches so an unverified user can't queue a pending request
    # that would only be approvable into an active row violating
    # the floor.
    from verification import (
        check_membership_floor_for_join, ensure_can_join_real_org,
        check_membership_min_age_for_join,
        check_membership_locality_for_join,
    )
    check_membership_floor_for_join(current_user, org)
    check_membership_min_age_for_join(current_user, org)
    check_membership_locality_for_join(current_user, org)
    ensure_can_join_real_org(current_user, org)

    # Resolve the Member role (defensive seed for legacy orgs).
    member_role_id = _resolve_role_id_by_system_key(db, org.id, "member")
    if member_role_id is None:
        seed_default_roles_for_org(db, org.id)
        member_role_id = _resolve_role_id_by_system_key(db, org.id, "member")

    # Phase 52e Stage 2 E4 — evaluate org-scoped duplicate flags for
    # this candidate against the org's current member population.
    # Same-org only; cross-org matches are computed-but-ignored
    # because this loop only runs against the org being joined.
    # A high-confidence flag with the org's
    # ``verification_high_confidence_flag_action`` set to
    # ``pending_approval`` routes the membership into the existing
    # approval queue regardless of ``join_policy``; otherwise the
    # flag is created + audited but doesn't change routing (the
    # admin handles it via the existing pending list / a future
    # adjudication surface). Low-confidence flags are NEVER routing-
    # changers — the birthday-paradox math means they'd wall
    # innocents at scale.
    import verification_flags
    new_flags = verification_flags.evaluate_duplicate_flags_for_org(
        db, candidate_user=current_user, org=org,
        actor_id=current_user.id,
        ip_address=request.client.host if request.client else None,
    )
    # Phase 52h Stage 1 H2 — both tiers now read their own settings.
    # Routing dispatches per-tier via flag_action_for_confidence;
    # low-confidence defaults to pending_approval too (was hardcoded
    # review-only pre-52h). An org can flip either tier to
    # ``review_only`` independently.
    flag_routes_to_pending = any(
        verification_flags.flag_action_for_confidence(org, f.confidence)
            == verification_flags.ACTION_PENDING_APPROVAL
        for f in new_flags
    )

    if org.join_policy == "open" and not flag_routes_to_pending:
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

    # approval path (Phase 57 — was 'approval_required').
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
        details={"slug": org.slug, "policy": "approval"},
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


@router.post("/{org_slug}/leave")
def leave_organization(
    org_slug: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Phase 50 — self-service leave-org.

    Auth required. The caller leaves their own active membership; no
    target user id (you can only leave for yourself).

    Outcomes:
      * 404 if the org doesn't exist.
      * 400 if the caller isn't an active member.
      * 409 ``transfer_required`` if the caller's departure would
        leave the org without a governor (sole steward in
        single_steward mode; last admin in admin_council mode). The
        body carries the mode + a human-readable detail so the FE
        can render the inline transfer-first step (D2). The
        membership is NOT deleted in this case — the caller has to
        complete the transfer first, then re-call this endpoint.
      * 200 on success. Custom titles revoked, outgoing org-scoped
        delegations cleaned, membership hard-deleted, ``org.left``
        audit emitted.

    Reuses the existing floor (``governance.count_active_governors``),
    the Phase 47 title-assignment table, and the audit infrastructure.
    The core logic lives in ``org_leave.leave_org`` so a future
    account-deletion path can loop it across the user's orgs.
    """
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug,
    ).first()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    from org_leave import leave_org, TransferRequired
    ip = request.client.host if request.client else None
    try:
        result = leave_org(
            db, org, current_user, ip_address=ip,
        )
    except TransferRequired as e:
        # Surface the structured payload as a 409 so the FE can render
        # the inline transfer-first flow per D2.
        raise HTTPException(status_code=409, detail=e.to_dict())
    db.commit()
    return result


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
    # Phase 57 — was secret-policy check; now keys on discoverability.
    if org is None or org.discoverability == "hidden":
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
    request: Request,
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
    # Phase 57 — hidden discoverability 404s anonymously regardless of
    # join_policy (the legacy invite_only_secret semantic). Invite join
    # policy 403s with the invitation-required message.
    if org.discoverability == "hidden":
        raise HTTPException(status_code=404, detail="Organization not found")
    if org.join_policy == "invite":
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

    # Phase 52 Stage 1 — verification membership floor gate. Raises
    # 403 with structured detail when the org has set a floor and
    # the caller doesn't satisfy it. No-op for the default-config
    # case (every org pre-Phase-52 + every org that doesn't opt
    # in). Applies to BOTH the open-join and approval-required
    # branches: an unverified user shouldn't be able to file a
    # pending request either, since approving them would create the
    # active row that the floor prohibits.
    from verification import (
        check_membership_floor_for_join, ensure_can_join_real_org,
        check_membership_min_age_for_join,
        check_membership_locality_for_join,
    )
    check_membership_floor_for_join(current_user, org)
    check_membership_min_age_for_join(current_user, org)
    check_membership_locality_for_join(current_user, org)
    ensure_can_join_real_org(current_user, org)

    # Phase 12 — defensively seed preset roles for the org if missing
    # (production orgs are seeded at create time and via the migration; this
    # is belt-and-suspenders for legacy data paths).
    member_role_id = _resolve_role_id_by_system_key(db, org.id, "member")
    if member_role_id is None:
        seed_default_roles_for_org(db, org.id)
        member_role_id = _resolve_role_id_by_system_key(db, org.id, "member")

    # Phase 52e Stage 2 E4 — same duplicate-flag evaluation as the
    # newer ``request_join`` path. Same-org only; high-confidence
    # match + ``pending_approval`` setting routes to the existing
    # approval queue regardless of ``join_policy``.
    import verification_flags
    new_flags = verification_flags.evaluate_duplicate_flags_for_org(
        db, candidate_user=current_user, org=org,
        actor_id=current_user.id,
        ip_address=request.client.host if request.client else None,
    )
    # Phase 52h Stage 1 H2 — both tiers now read their own settings.
    # Routing dispatches per-tier via flag_action_for_confidence;
    # low-confidence defaults to pending_approval too (was hardcoded
    # review-only pre-52h). An org can flip either tier to
    # ``review_only`` independently.
    flag_routes_to_pending = any(
        verification_flags.flag_action_for_confidence(org, f.confidence)
            == verification_flags.ACTION_PENDING_APPROVAL
        for f in new_flags
    )

    if org.join_policy == "open" and not flag_routes_to_pending:
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
    # Phase 71b — config-authoritative (pattern: see suspend_member). Tier
    # floor (moderator+) preserved by the Depends above.
    if org is not None and not has_permission(
        db, current_user.id, org.id, "member.approve_join"
    ):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to approve join requests in this organization.",
        )
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
    admin_membership: models.OrgMembership = Depends(require_org_moderator_or_admin),
):
    """Send invitations (moderator+ holding member.invite). Body: {emails: string[], role: string}

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
    # Phase 71b — member.invite is config-authoritative; Z lowered the floor
    # from admin to moderator+ (the moderator default grant now actually
    # works). member.invite governs the whole invitation surface (send /
    # list / revoke / resend) so a moderator who can send also sees + manages
    # the list — gating only "send" would show them a list that 403s.
    if not has_permission(db, current_user.id, org.id, "member.invite"):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to send invitations in this organization.",
        )

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
    admin_membership: models.OrgMembership = Depends(require_org_moderator_or_admin),
):
    """List invitations (moderator+ holding member.invite)."""
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    # Phase 71b — member.invite config-authoritative (floor lowered to mod+).
    if org is not None and not has_permission(
        db, current_user.id, org.id, "member.invite"
    ):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to view invitations in this organization.",
        )
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
    admin_membership: models.OrgMembership = Depends(require_org_moderator_or_admin),
):
    """Revoke invitation (moderator+ holding member.invite)."""
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    # Phase 71b — member.invite config-authoritative (floor lowered to mod+).
    if org is not None and not has_permission(
        db, current_user.id, org.id, "member.invite"
    ):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to revoke invitations in this organization.",
        )
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
    admin_membership: models.OrgMembership = Depends(require_org_moderator_or_admin),
):
    """Resend invitation (moderator+ holding member.invite) — generates a new
    token, extends expiry, and actually sends the email (Phase 9.6 W1 fix —
    also previously rotated the token without sending anything)."""
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    # Phase 71b — member.invite config-authoritative (floor lowered to mod+).
    if org is not None and not has_permission(
        db, current_user.id, org.id, "member.invite"
    ):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to resend invitations in this organization.",
        )
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

    # Phase 52 Stage 1 — verification membership floor gate. Even an
    # invited user has to satisfy the org's membership floor; an
    # invitation is who-can-join-at-all, the verification floor is
    # the qualification bar. Both must pass. Also gate against the
    # *role* floor (invitations can target a role above member, e.g.
    # admin invitations — the target user must qualify for that role
    # too).
    inv_org = db.get(models.Organization, inv.org_id)
    if inv_org is not None:
        from verification import (
            check_membership_floor_for_join, check_role_grant_floor,
            ensure_can_join_real_org, check_membership_min_age_for_join,
            check_membership_locality_for_join,
            check_role_residency_for_grant,
        )
        check_membership_floor_for_join(current_user, inv_org)
        check_membership_min_age_for_join(current_user, inv_org)
        check_membership_locality_for_join(current_user, inv_org)
        ensure_can_join_real_org(current_user, inv_org)
        inv_system_key_for_check = _INV_ROLE_TO_SYSTEM_KEY.get(inv.role, inv.role)
        if inv_system_key_for_check and inv_system_key_for_check != "member":
            check_role_grant_floor(
                current_user, inv_org, inv_system_key_for_check,
            )
            # Phase 52j J1 — also residency-scope.
            check_role_residency_for_grant(
                current_user, inv_org, inv_system_key_for_check,
            )
        # Phase 52e Stage 2 E4 — duplicate-flag evaluation on
        # invitation-accept too. Invitations from an org admin don't
        # bypass the dedup check; the admin invited a person, not an
        # alternate identity.
        import verification_flags
        verification_flags.evaluate_duplicate_flags_for_org(
            db, candidate_user=current_user, org=inv_org,
            actor_id=current_user.id,
            ip_address=request.client.host if request.client else None,
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
        # Phase 56 — optional purpose + category persist when supplied.
        # Empty strings normalize to None so the column reads as NULL
        # rather than as the empty literal (FE renders nothing for both
        # but the data shape stays clean).
        purpose=body.purpose or None,
        category=body.category or None,
        # Phase 65 — per-topic delegation disallow flag; defaults True
        # (delegation allowed) when the caller omits it.
        allow_delegation=body.allow_delegation,
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
    # Phase 71b — config-authoritative (pattern: see suspend_member). Tier
    # floor (moderator+) preserved by the Depends above.
    if org is not None and not has_permission(
        db, current_user.id, org.id, "topic.edit"
    ):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to edit topics in this organization.",
        )
    topic = db.query(models.Topic).filter(
        models.Topic.id == topic_id,
        models.Topic.org_id == org.id,
    ).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found in this organization")

    topic.name = body.name
    # Phase 33 D2 — Topic.description column dropped.
    topic.color = body.color
    # Phase 56 — purpose + category are persistable on PATCH. The PATCH
    # body shape is TopicCreate (full-replacement semantics, not partial)
    # so we mirror that: NULL when the caller sends None / empty, the
    # supplied value otherwise.
    topic.purpose = body.purpose or None
    topic.category = body.category or None
    # Phase 65 — per-topic delegation disallow flag. Full-replacement
    # semantics like the other TopicCreate fields: the schema default
    # (True) applies when the caller omits it. Existing Delegation rows
    # on a newly-disallowed topic are kept but inert (D2) — flipping the
    # flag back restores behavior.
    topic.allow_delegation = body.allow_delegation
    db.commit()
    db.refresh(topic)
    return topic


@router.delete("/{org_slug}/topics/{topic_id}")
def delete_org_topic(
    org_slug: str,
    topic_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    admin_membership: models.OrgMembership = Depends(require_org_admin),
):
    """Deactivate topic (admin) — soft-delete by removing org association.

    Phase 44 — wrapped under multi-admin approval when enabled.
    """
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()

    from pending_actions import engine as p44_engine, settings as p44_settings
    if p44_settings.is_action_wrapped(org, "topic.delete"):
        ip = request.client.host if request.client else None
        result = p44_engine.submit_pending_action(
            db, org, current_user, "topic.delete", {"topic_id": topic_id},
            ip_address=ip,
        )
        db.commit()
        if result.executed_directly:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        db.refresh(result.pending_action)
        return {
            "status": "submitted_for_approval",
            "pending_action": p44_engine.serialize_pending(
                db, result.pending_action, viewer_id=current_user.id,
            ),
        }

    # Phase 71b — config-authoritative on the DIRECT path (the Phase 44
    # engine path above already gates the initiator on "topic.delete" via
    # required_permission_key, so it isn't double-gated). Floor is admin+
    # (require_org_admin Depends) — VERIFIED against the live route, which
    # disagrees with the 71b spec table's "moderator+"; live route wins, so
    # topic.delete stays admin-floored and the 71a backfill seeded it
    # admin-only. has_permission lets an org tighten/loosen within that floor.
    if org is not None and not has_permission(
        db, current_user.id, org.id, "topic.delete"
    ):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to delete topics in this organization.",
        )
    topic = db.query(models.Topic).filter(
        models.Topic.id == topic_id,
        models.Topic.org_id == org.id,
    ).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found in this organization")
    topic.org_id = None  # soft-deactivate
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
        # Parent-org-scoped: the gating decision (direct vs cosign-
        # gated vs 403) is handled by ``gate_proposal_creation``
        # below. Phase 49a Cluster B removed the standalone
        # ``proposal.create``-permission check here — the gate now
        # owns the decision: hold ``proposal.create`` → direct;
        # else if ``allow_cosign_petition=True`` → cosign-gated;
        # else 403. Combining the two checks into one gate removes
        # the prior conflict where mode + permission-key gave
        # subtly-different answers depending on path.
        pass

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

    # Phase 46 — cosign-gating dispatch (B3). For parent-org-scoped
    # proposals only (sub-org-scoped proposals retain their own
    # creation rules per Phase 8.5). If the org is in cosign_required
    # mode and the caller is member-tier (lacks proposal.advance_phase),
    # the proposal enters cosign gathering; in admin_only mode a
    # member-tier caller is rejected here. Holders of advance_phase
    # create normally regardless of mode. Sub-org-scoped proposals
    # skip this dispatch.
    from cosign import gate_proposal_creation, init_cosign_gated_proposal
    cosign_decision = "direct"
    if target_sub_org is None:
        cosign_decision = gate_proposal_creation(db, current_user.id, org)

    # Phase 25 B2 — 0-day deliberation skip: when the effective
    # deliberation duration resolves to zero (either an explicit
    # per-proposal override or the org default), create the proposal
    # directly in `voting` status. Single audit event (draft -> voting)
    # rather than two-at-the-same-timestamp events; the user's intent is
    # "skip deliberation," not "deliberate for zero seconds."
    # Cosign-gated proposals always enter `deliberation` (the gathering
    # phase reuses deliberation), so they bypass the 0-day skip.
    skip_deliberation = (
        cosign_decision != "cosign_gated"
        and effective_delib_days is not None
        and float(effective_delib_days) == 0.0
    )
    if cosign_decision == "cosign_gated":
        initial_status = "deliberation"
        now_at_create = _now()
    elif skip_deliberation:
        initial_status = "voting"
        now_at_create = _now()
    else:
        initial_status = "draft"
        now_at_create = None

    # Phase 52 Stage 1 — validate the per-proposal verification gate
    # inputs against the shipped Phase 51 state list + the
    # jurisdiction-presence consistency rule. Done HERE (at proposal
    # creation) so a malformed gate fails the whole POST cleanly
    # rather than being a silent NULL at write time.
    if body.verification_floor is not None:
        from verification import (
            VALID_STATES, ORDER, jurisdiction_required_for, EMAIL_ONLY,
        )
        if body.verification_floor not in VALID_STATES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unknown verification_floor {body.verification_floor!r}. "
                    f"Allowed: {list(ORDER)}."
                ),
            )
        # Normalize blank jurisdiction → None for the
        # presence-consistency check.
        _jur = body.verification_jurisdiction
        _jur = _jur.strip() if isinstance(_jur, str) else None
        if _jur == "":
            _jur = None
        if jurisdiction_required_for(body.verification_floor) and not _jur:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"verification_floor {body.verification_floor!r} "
                    "requires a non-empty verification_jurisdiction."
                ),
            )
        if not jurisdiction_required_for(body.verification_floor) and _jur:
            # Drop misleading input (mirrors the backdoor setter's
            # behavior — lower-tier floors don't carry a
            # jurisdiction claim).
            body.verification_jurisdiction = None
        else:
            body.verification_jurisdiction = _jur
        # ``email_only`` as a floor is a no-op (the gate predicate
        # returns True for everyone). Normalize to NULL so the
        # ungated path is the canonical "no gate" representation.
        if body.verification_floor == EMAIL_ONLY:
            body.verification_floor = None
            body.verification_jurisdiction = None

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
        voting_start=now_at_create if skip_deliberation else None,
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
        # Phase 52 Stage 1 — per-proposal verification gate. Validated
        # against ``VALID_STATES`` + jurisdiction-presence consistency
        # right above ``models.Proposal(...)``.
        verification_floor=body.verification_floor,
        verification_jurisdiction=body.verification_jurisdiction,
        # Phase 66 — multi-winner approval config. Shape validated at
        # the Pydantic layer; method-compatibility (approval only)
        # enforced by _validate_proposal_creation above. NULL = legacy
        # single-winner. (Phase 32.1 lesson: a new Proposal field must
        # flow through BOTH create endpoints — this is the org-scoped
        # half.)
        approval_winner_config=body.approval_winner_config,
        # Phase 73 — budget config (allocation mode). Validated for shape at
        # the Pydantic layer + method/mode coherence in
        # _validate_proposal_creation above. NULL = not a budget proposal.
        # (Phase 32.1 lesson: a new Proposal field must flow through BOTH
        # create endpoints — this is the org-scoped half.)
        budget_config=getattr(body, "budget_config", None),
    )
    db.add(proposal)
    db.flush()

    # Phase 46 B3 — stamp cosign markers + insert author's implicit first
    # signature (D3) when the proposal entered gathering state.
    if cosign_decision == "cosign_gated":
        init_cosign_gated_proposal(db, proposal, org)
        log_audit_event(
            db,
            action="proposal.cosign_created",
            target_type="proposal",
            target_id=proposal.id,
            actor_id=current_user.id,
            details={
                "proposal_id": proposal.id,
                "org_id": org.id,
                "threshold": proposal.cosign_threshold_snapshot,
                "expires_at": proposal.cosign_expires_at.isoformat(),
            },
            ip_address=request.client.host if request.client else None,
        )

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

    if body.voting_method in ("approval", "ranked_choice", "budget_allocation") and body.options:
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


# ===========================================================================
# Phase 68a — import a proposal from a JSON file
#
# A multi-option proposal (approval/RCV with many options) is tedious to
# build field-by-field. This lets a user (or an AI assistant) author the
# whole thing as a structured JSON file and import it. The import NEVER
# writes a proposal row — it parses + validates against the SAME rules the
# create path uses, then returns a ``ProposalCreate``-shaped payload the FE
# pre-fills into the normal create form. The user reviews and submits
# through the existing create endpoint (one create code path, one review
# step). See phase68_proposal_import_and_archive_dispatch_2026-06-13.md.
# ===========================================================================

# Cap the import upload — a proposal is small text; reject larger to avoid
# abuse / accidental huge uploads.
_IMPORT_MAX_BYTES = 256 * 1024

# Phase 72 — cap the number of proposals in one multi-import array.
_IMPORT_MAX_PROPOSALS = 50

# Annotated template base returned by the import-template endpoint (Phase
# 72: threshold/duration fields are appended PER CALLER from the org's
# actual defaults, only when the caller holds the matching permission — see
# get_proposal_import_template). Doubles as the format doc for the
# AI-assistant workflow. The ``_readme`` key is an UNKNOWN field — importing
# this template back produces a "skipped unknown field" warning,
# demonstrating the forward-compatible ignore-unknown rule.
_IMPORT_TEMPLATE_BASE: dict = {
    "_readme": (
        "Liquid Democracy proposal import template. Fill in the fields "
        "below and import via the proposal create form. You can import a "
        "SINGLE proposal (a JSON object like this one) OR MULTIPLE proposals "
        "(a JSON array of these objects, e.g. [ {…}, {…} ]). 'voting_method' "
        "is one of 'binary', 'approval', or 'ranked_choice'. Binary "
        "proposals omit 'options'. Approval/ranked_choice need at least 2 "
        "options. Topics may be given by 'topic_name' (resolved against this "
        "org's topics) or 'topic_id'. Unknown fields (like this _readme) are "
        "ignored on import. Threshold and duration fields are optional — "
        "omit them to use the organization's defaults. Fields you don't have "
        "permission to set are omitted from this template."
    ),
    "title": "Example: Adopt a community garden policy",
    "body": "Markdown body explaining the proposal goes here.",
    "voting_method": "approval",
    "num_winners": 1,
    "options": [
        {"label": "Option A", "description": "What option A means."},
        {"label": "Option B", "description": "What option B means."},
    ],
    "topics": [
        {"topic_name": "Parks & Recreation", "relevance": 1.0},
    ],
}

# ProposalCreate fields the importer accepts. Computed from the schema so
# new ProposalCreate fields are accepted automatically (forward-compat).
_IMPORT_KNOWN_KEYS: set[str] = set(schemas.ProposalCreate.model_fields.keys())


def _import_candidate_topics(db: Session, org: models.Organization) -> list[models.Topic]:
    """Topics a proposal in ``org`` could attach — used to resolve
    ``topic_name`` references and to validate ``topic_id`` references.

    Mirrors the create path's scope rules: a parent-org slug resolves to
    parent-org-wide topics; a sub-org slug resolves to that sub-org's
    topics plus the parent-org-wide ones.
    """
    if org.parent_org_id is not None:
        return (
            db.query(models.Topic)
            .filter(
                models.Topic.org_id == org.parent_org_id,
                (models.Topic.sub_org_id.is_(None))
                | (models.Topic.sub_org_id == org.id),
            )
            .all()
        )
    return (
        db.query(models.Topic)
        .filter(
            models.Topic.org_id == org.id,
            models.Topic.sub_org_id.is_(None),
        )
        .all()
    )


def _resolve_import_topics(
    raw_topics: object, candidates: list[models.Topic],
) -> tuple[list[dict], list[str], list[dict], list[str]]:
    """Resolve an imported ``topics`` list to ``[{topic_id, relevance}]``.

    Accepts entries that are a bare ``topic_id`` string, ``{topic_id,
    relevance?}``, or ``{topic_name, relevance?}`` (Phase 68a D4). Returns
    ``(resolved_for_create, warnings, resolved_transparency, errors)``:
      * resolved_for_create — ``[{topic_id, relevance}]`` for matched entries
      * warnings — name→id resolution notes
      * resolved_transparency — ``[{topic_id, topic_name, relevance}]``
      * errors — human-readable strings for unmatched/invalid entries
    """
    by_name = {t.name.strip().lower(): t for t in candidates}
    by_id = {t.id: t for t in candidates}
    available = sorted(t.name for t in candidates)

    resolved: list[dict] = []
    warnings: list[str] = []
    transparency: list[dict] = []
    errors: list[str] = []

    if raw_topics is None:
        return resolved, warnings, transparency, errors
    if not isinstance(raw_topics, list):
        errors.append("'topics' must be a list.")
        return resolved, warnings, transparency, errors

    for entry in raw_topics:
        relevance = 1.0
        topic: Optional[models.Topic] = None
        if isinstance(entry, str):
            topic = by_id.get(entry)
            if topic is None:
                errors.append(
                    f"Topic id '{entry}' not found in this organization."
                )
                continue
        elif isinstance(entry, dict):
            if entry.get("relevance") is not None:
                relevance = entry["relevance"]
            if entry.get("topic_id"):
                topic = by_id.get(entry["topic_id"])
                if topic is None:
                    errors.append(
                        f"Topic id '{entry['topic_id']}' not found in this "
                        "organization."
                    )
                    continue
            elif entry.get("topic_name"):
                name = str(entry["topic_name"]).strip()
                topic = by_name.get(name.lower())
                if topic is None:
                    errors.append(
                        f"Topic name '{name}' did not match any topic in "
                        f"this organization. Available topics: "
                        f"{', '.join(available) if available else '(none)'}."
                    )
                    continue
                warnings.append(
                    f"Resolved topic name '{name}' to id {topic.id}."
                )
            else:
                errors.append(
                    "Each topic entry needs a 'topic_id' or 'topic_name'."
                )
                continue
        else:
            errors.append(f"Invalid topic entry: {entry!r}.")
            continue

        resolved.append({"topic_id": topic.id, "relevance": relevance})
        transparency.append({
            "topic_id": topic.id,
            "topic_name": topic.name,
            "relevance": relevance,
        })

    return resolved, warnings, transparency, errors


def _preview_one_proposal(
    item: object,
    org: models.Organization,
    db: Session,
    user: models.User,
) -> dict:
    """Phase 72 — parse + validate ONE imported proposal dict. The single
    source of validation shared by the single-object and array import paths
    (no duplicated logic). NEVER writes.

    Returns ``{proposal: dict | None, warnings: [str], resolved_topics:
    [dict], errors: {field: [str]}}``. ``proposal`` is non-null only when
    the item validated cleanly.

    Section B (permission-aware fallback): after a clean build, threshold /
    duration values that DIVERGE from the org default are dropped from the
    prefill payload (with a warning, not an error) when the caller lacks the
    matching permission — mirroring the create-path gate's "diverges from
    default, NOT merely present" rule (``_enforce_threshold_permission`` /
    ``_enforce_duration_permission``). A value EQUAL to the default is kept
    and never warns. The create-time gates remain the real boundary.
    """
    errors: dict[str, list[str]] = {}
    warnings: list[str] = []

    def add_error(field: str, message: str) -> None:
        errors.setdefault(field, [])
        if message not in errors[field]:
            errors[field].append(message)

    if not isinstance(item, dict):
        add_error("_item", "Each proposal must be a JSON object.")
        return {"proposal": None, "warnings": warnings, "resolved_topics": [], "errors": errors}

    # --- split known / unknown keys (forward-compat: a future export may
    # carry read-only fields like id/status — ignore them with a warning) ---
    cleaned: dict = {}
    for key, value in item.items():
        if key in _IMPORT_KNOWN_KEYS:
            cleaned[key] = value
        else:
            warnings.append(f"Ignored unknown field '{key}'.")

    # --- resolve topics (name → id) before building ProposalCreate ---
    candidates = _import_candidate_topics(db, org)
    resolved_topics, topic_warnings, topic_transparency, topic_errors = (
        _resolve_import_topics(cleaned.get("topics"), candidates)
    )
    warnings.extend(topic_warnings)
    for msg in topic_errors:
        add_error("topics", msg)
    # Pass only the successfully-resolved topics into ProposalCreate so the
    # rest of validation can still run when some names didn't match.
    cleaned["topics"] = resolved_topics

    # --- build ProposalCreate (Pydantic field/range/shape validation) ---
    proposal_model: Optional[schemas.ProposalCreate] = None
    try:
        proposal_model = schemas.ProposalCreate(**cleaned)
    except ValidationError as exc:
        for err in exc.errors():
            loc = err.get("loc") or ()
            field = str(loc[0]) if loc else "_file"
            add_error(field, err.get("msg", "Invalid value."))

    # --- create-rule parity + floors + verification (only if it built) ---
    if proposal_model is not None:
        from routes.proposals import (
            _collect_proposal_creation_errors,
            _VOTING_DAYS_FLOOR,
            _DELIBERATION_DAYS_FLOOR,
        )
        for field, _status_code, message in _collect_proposal_creation_errors(
            proposal_model, org,
        ):
            add_error(field, message)

        if (
            proposal_model.voting_days is not None
            and proposal_model.voting_days < _VOTING_DAYS_FLOOR
        ):
            add_error(
                "voting_days",
                "Voting duration must be at least 0.05 days (72 minutes).",
            )
        if (
            proposal_model.deliberation_days is not None
            and proposal_model.deliberation_days < _DELIBERATION_DAYS_FLOOR
        ):
            add_error("deliberation_days", "Deliberation duration cannot be negative.")

        if proposal_model.verification_floor is not None:
            from verification import VALID_STATES, ORDER, jurisdiction_required_for
            floor = proposal_model.verification_floor
            jur = proposal_model.verification_jurisdiction
            jur = jur.strip() if isinstance(jur, str) else None
            if floor not in VALID_STATES:
                add_error(
                    "verification_floor",
                    f"Unknown verification_floor {floor!r}. Allowed: {list(ORDER)}.",
                )
            elif jurisdiction_required_for(floor) and not jur:
                add_error(
                    "verification_jurisdiction",
                    f"verification_floor {floor!r} requires a non-empty "
                    "verification_jurisdiction.",
                )

    if errors or proposal_model is None:
        return {
            "proposal": None,
            "warnings": warnings,
            "resolved_topics": topic_transparency,
            "errors": errors,
        }

    proposal_dict = proposal_model.model_dump(mode="json")

    # --- Section B: permission-aware threshold/duration handling ---
    # Two jobs, both keyed on model_fields_set (the SAME mechanism the create
    # endpoint uses to tell "explicitly provided" from "schema default"):
    #   1. A field NOT in the file is dropped from the prefill so the create
    #      form / endpoint applies the ORG default. (Otherwise ProposalCreate's
    #      schema defaults — pass_threshold=0.50, quorum_threshold=0.40 — would
    #      leak into the payload and, if they differ from the org's actual
    #      defaults, trip the create gate for an unpermitted caller.)
    #   2. A field IN the file that DIVERGES from the org default is dropped
    #      WITH a warning when the caller lacks the permission. A value EQUAL
    #      to the default is kept silently (mirrors _enforce_*_permission's
    #      "diverges, not present" rule exactly). A permitted caller keeps a
    #      divergent value (normal override).
    fields_set = proposal_model.model_fields_set
    can_thresholds = has_permission(db, user.id, org.id, "proposal.set_thresholds")
    can_durations = has_permission(db, user.id, org.id, "proposal.set_durations")
    default_pass, default_quorum = get_default_proposal_thresholds(org)
    default_delib, default_vote = get_default_proposal_durations(org)

    _threshold_duration_fields = [
        ("pass_threshold", default_pass, can_thresholds, "pass threshold", False),
        ("quorum_threshold", default_quorum, can_thresholds, "quorum threshold", False),
        ("voting_days", default_vote, can_durations, "voting duration", True),
        ("deliberation_days", default_delib, can_durations, "deliberation duration", True),
    ]
    for field, default_value, has_perm, label, is_duration in _threshold_duration_fields:
        if field not in fields_set:
            # Not provided in the file — don't leak the schema default; the
            # org default applies at create time.
            proposal_dict.pop(field, None)
            continue
        model_value = getattr(proposal_model, field)
        if model_value is None or default_value is None:
            continue
        if is_duration:
            diverges = float(model_value) != float(default_value)
        else:
            diverges = model_value != default_value
        if diverges and not has_perm:
            proposal_dict.pop(field, None)
            warnings.append(
                f"You don't have permission to set a custom {label}; using "
                f"the organization default ({default_value})."
            )

    return {
        "proposal": proposal_dict,
        "warnings": warnings,
        "resolved_topics": topic_transparency,
        "errors": {},
    }


@router.get("/{org_slug}/proposals/import-template")
def get_proposal_import_template(
    org_slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """Phase 68a / 72 — per-caller annotated JSON template for the importer.

    Behind org membership (same surface as the import flow). The FE
    "Download template" link fetches this; AI-assistant / scripting
    workflows GET it directly as the format reference.

    Phase 72 B1: threshold/duration fields are seeded from the ORG's actual
    defaults (not hardcoded examples) and OMITTED entirely when the caller
    lacks the matching permission — so a non-admin's template carries no
    divergent values and imports cleanly.
    """
    import copy

    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    tmpl = copy.deepcopy(_IMPORT_TEMPLATE_BASE)
    if has_permission(db, current_user.id, membership.org_id, "proposal.set_thresholds"):
        default_pass, default_quorum = get_default_proposal_thresholds(org)
        tmpl["pass_threshold"] = default_pass
        tmpl["quorum_threshold"] = default_quorum
    if has_permission(db, current_user.id, membership.org_id, "proposal.set_durations"):
        default_delib, default_vote = get_default_proposal_durations(org)
        tmpl["deliberation_days"] = default_delib
        tmpl["voting_days"] = default_vote
    return tmpl


@router.post("/{org_slug}/proposals/import-preview")
async def import_preview_proposal(
    org_slug: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """Phase 68a — parse + validate an imported proposal file WITHOUT
    persisting anything.

    Accepts a multipart file upload (what the FE sends) OR a raw
    ``application/json`` body (convenient for API / AI-assistant use).
    Returns a ``ProposalCreate``-shaped ``proposal`` payload + ``warnings``
    + ``resolved_topics`` on success (200), or ``{errors, warnings}``
    field-keyed on validation failure (422). NEVER writes a Proposal row
    and emits no audit event — the eventual create through the existing
    endpoint does that.

    Auth: org member holding ``proposal.create`` (the same gate the create
    form is behind). No new permission key.
    """
    # --- auth: same gate as the create form ---
    if not has_permission(db, current_user.id, membership.org_id, "proposal.create"):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to create proposals in this organization.",
        )

    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    # --- read raw bytes from either transport ---
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        upload = None
        for value in form.values():
            if hasattr(value, "read"):
                upload = value
                break
        if upload is None:
            return JSONResponse(
                status_code=422,
                content={"errors": {"_file": ["No file was uploaded."]}, "warnings": []},
            )
        raw_bytes = await upload.read()
    else:
        raw_bytes = await request.body()

    if len(raw_bytes) > _IMPORT_MAX_BYTES:
        return JSONResponse(
            status_code=413,
            content={
                "errors": {"_file": [
                    f"Import file is too large (max {_IMPORT_MAX_BYTES // 1024} KB)."
                ]},
                "warnings": [],
            },
        )

    # --- parse JSON ---
    import json
    try:
        parsed = json.loads(raw_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse(
            status_code=422,
            content={"errors": {"_file": ["Could not parse file as JSON."]}, "warnings": []},
        )

    # --- Phase 72: dispatch on the input type ---
    # Single object → 68a-compatible {proposal, warnings, resolved_topics}
    # (success) / {errors, warnings} (422). Array → per-item {items, summary}
    # at 200 (one bad item doesn't fail the batch). Disambiguation is by the
    # INPUT type, not a query param.
    if isinstance(parsed, dict):
        result = _preview_one_proposal(parsed, org, db, current_user)
        if result["errors"]:
            return JSONResponse(
                status_code=422,
                content={"errors": result["errors"], "warnings": result["warnings"]},
            )
        return {
            "proposal": result["proposal"],
            "warnings": result["warnings"],
            "resolved_topics": result["resolved_topics"],
        }

    if isinstance(parsed, list):
        if len(parsed) > _IMPORT_MAX_PROPOSALS:
            return JSONResponse(
                status_code=422,
                content={
                    "errors": {"_file": [
                        f"Too many proposals in one import (max "
                        f"{_IMPORT_MAX_PROPOSALS}); got {len(parsed)}."
                    ]},
                    "warnings": [],
                },
            )
        items: list[dict] = []
        valid = 0
        for index, raw_item in enumerate(parsed):
            r = _preview_one_proposal(raw_item, org, db, current_user)
            if r["proposal"] is not None and not r["errors"]:
                valid += 1
            items.append({
                "index": index,
                "proposal": r["proposal"],
                "warnings": r["warnings"],
                "resolved_topics": r["resolved_topics"],
                "errors": r["errors"],
            })
        total = len(parsed)
        return {
            "items": items,
            "summary": {"total": total, "valid": valid, "invalid": total - valid},
        }

    return JSONResponse(
        status_code=422,
        content={
            "errors": {"_file": [
                "Import must be a JSON object or an array of proposal objects."
            ]},
            "warnings": [],
        },
    )


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
        if getattr(proposal, "is_election", False):
            # Phase 67 W1 — elections: quorum is the ONLY pass/fail
            # gate (mirrors routes/proposals.py). Winner determination
            # belongs to finalize_election, fired on the "passed"
            # close via run_election_close_hook below.
            from elections import election_close_status
            next_status = election_close_status(proposal, tally)
        elif proposal.voting_method == "approval":
            # Phase 66: a multi-winner boundary tie can leave ``winners``
            # empty with the contested set in ``boundary_tied`` — that's
            # resolvable, not a failure (mirrors routes/proposals.py).
            if (
                isinstance(tally, ApprovalTally)
                and tally.quorum_met(proposal.quorum_threshold)
                and (tally.winners or tally.boundary_tied)
            ):
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
        elif proposal.voting_method == "budget_allocation":
            # Phase 73 — allocation budgets pass on quorum alone (no yes/no,
            # so pass_threshold is not consulted), including the degenerate
            # all-zero case. No winner set → never routes to tie resolution.
            # (Mirrors routes/proposals.py.)
            from budget_tally import AllocationTally
            if (
                isinstance(tally, AllocationTally)
                and tally.quorum_met(proposal.quorum_threshold)
            ):
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

    # Phase 67 W1 — election close hook. This org-scoped advance path
    # previously closed election proposals WITHOUT running
    # ``finalize_election`` at all (only the /api/proposals advance
    # had the Phase 48 hook), so an election advanced here never
    # seated its winners. Run the shared hook so both advance paths
    # and the worker natural close agree: quorum gates seat
    # installation — finalize only fires on a "passed" close; a
    # "failed" (quorum unmet) close skips seating and records
    # election.not_finalized.
    if getattr(proposal, "is_election", False) and next_status in ("passed", "failed"):
        from elections import run_election_close_hook
        next_status = run_election_close_hook(
            db, proposal, next_status,
            actor_id=current_user.id,
            ip_address=request.client.host if request.client else None,
        )

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

    # Phase 71a — config-authoritative enforcement (pattern: see
    # suspend_member). Admin tier is the floor; the org's config decides.
    if org is not None and not has_permission(
        db, current_user.id, org.id, "analytics.view"
    ):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to view analytics for this organization.",
        )

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
