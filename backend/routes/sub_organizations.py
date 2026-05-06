"""
Phase 8.5 Session 2 — Sub-organization endpoints.
Phase 15 Cluster S — sub-org membership now uses role_id FK to Role
(parent's matrix wholesale); the legacy string ``role`` column is gone.
This module's helpers and routes were updated in Cluster S to operate
through ``role.system_key``; the legacy ``"owner"`` string was renamed
to ``"steward"`` (Phase 12.5) and the migration backfilled all existing
rows accordingly.

Mounted under `/api/orgs/{slug}/sub-orgs` (and topics `promote-to-orgwide`).

Why a new module: the existing `routes/organizations.py` is already ~1500 lines
and mixes parent-org CRUD, membership, invitations, delegate applications,
topics, proposals, and analytics. Adding 12+ sub-org endpoints in there would
push it past 2000 lines and make the file hostile to navigate. Splitting keeps
sub-org logic discoverable and isolates Decision-1/6/7 enforcement to one place.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

import auth as auth_utils
import models
import schemas
from audit_utils import log_audit_event
from database import get_db
from org_middleware import (
    require_org_admin,
    require_org_membership,
)
from permission_registry import PERMISSION_REGISTRY
from permissions import is_sub_org_admin
from reserved_slugs import RESERVED_SLUGS
from role_permissions import (
    effective_role_on_sub_org,
    has_permission_on_sub_org,
)


# Phase 15 Cluster S — accept the legacy "owner" string in API payloads
# for one cycle of backwards compatibility (callers who haven't updated
# yet); silently translate to "steward". Map keys are the four legal
# values in request bodies; the value is the role.system_key on the
# parent's Role row.
_REQUEST_ROLE_TO_SYSTEM_KEY: dict[str, str] = {
    "member": "member",
    "moderator": "moderator",
    "admin": "admin",
    "owner": "steward",
    "steward": "steward",
}


def _resolve_parent_role_id(
    db: Session, parent_org_id: str, role_str: str,
) -> str:
    """Resolve a request-payload role string to the parent's Role.id.

    Used by all the sub-org membership creators / role-changers. Raises
    HTTPException(400) if the string is unknown.
    """
    target_sk = _REQUEST_ROLE_TO_SYSTEM_KEY.get(role_str)
    if target_sk is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid role {role_str!r}. Must be one of "
                "member, moderator, admin, steward."
            ),
        )
    role = (
        db.query(models.Role)
        .filter(
            models.Role.org_id == parent_org_id,
            models.Role.system_key == target_sk,
        )
        .first()
    )
    if role is None:
        # Defensive: every org should have all four preset roles seeded
        # by Phase 12 Stage 1's migration + role_seed.seed_default_roles_for_org.
        raise HTTPException(
            status_code=500,
            detail=(
                f"Parent org missing the {target_sk!r} preset role; "
                "this should not happen on a normally-seeded org."
            ),
        )
    return role.id


def _sub_membership_role_system_key(
    sub_membership: models.SubOrgMembership | None,
) -> str | None:
    """Return the SubOrgMembership's role.system_key, or None.

    Phase 15 Cluster S: SubOrgMembership.role is now an FK relationship
    to Role; this helper centralizes the safe-access pattern (None when
    the FK row was deleted out from under the membership).
    """
    if sub_membership is None or sub_membership.role is None:
        return None
    return sub_membership.role.system_key

router = APIRouter(prefix="/api/orgs", tags=["sub-organizations"])


def _now() -> datetime:
    """Naive UTC datetime — matches the existing org route convention."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parent_or_404(db: Session, org_slug: str) -> models.Organization:
    """Resolve the parent org by slug; 404 if missing.

    Decision 1: this endpoint family operates on a parent org. If the resolved
    org has a non-null parent_org_id (i.e., it is itself a sub-org), reject
    with 400 — sub-orgs cannot have sub-sub-orgs.
    """
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


def _sub_org_or_404(
    db: Session, parent: models.Organization, sub_slug: str
) -> models.Organization:
    """Resolve a sub-org under the given parent, by sub-slug."""
    sub_org = db.query(models.Organization).filter(
        models.Organization.slug == sub_slug,
        models.Organization.parent_org_id == parent.id,
    ).first()
    if not sub_org:
        raise HTTPException(status_code=404, detail="Sub-organization not found")
    return sub_org


def _require_parent_org_member(
    db: Session, user_id: str, parent: models.Organization
) -> models.OrgMembership:
    """Helper: parent-org membership lookup, 400 if user isn't a parent member.

    Used by sub-org member-invite to check that the invitee is a parent-org
    member already (Decision 2: sub-org membership is opt-in for parent-org
    members, not a backdoor into the parent org).
    """
    m = db.query(models.OrgMembership).filter(
        models.OrgMembership.user_id == user_id,
        models.OrgMembership.org_id == parent.id,
        models.OrgMembership.status == "active",
    ).first()
    return m


def _is_parent_org_admin(
    db: Session, user_id: str, parent: models.Organization
) -> bool:
    """Phase 12 — admin-tier check on parent OrgMembership via Role.system_key.

    'admin' and 'steward' grant implicit sub-org admin power per
    Decision 6; 'owner' was renamed to 'steward' by the migration.
    """
    m = db.query(models.OrgMembership).filter(
        models.OrgMembership.user_id == user_id,
        models.OrgMembership.org_id == parent.id,
        models.OrgMembership.status == "active",
    ).first()
    if m is None or m.role is None:
        return False
    return m.role.system_key in ("admin", "steward")


def _sub_org_to_out(
    sub_org: models.Organization,
    db: Session,
    user_id: Optional[str] = None,
) -> schemas.SubOrgOut:
    """Phase 15 Cluster S §S5 — also includes ``user_role`` (the
    resolved sub-org effective role's system_key) and
    ``user_permissions`` (the matrix permission keys the user holds on
    this sub-org via the parent's matrix at the resolved role).

    Parallel to ``_org_to_out`` in routes/organizations.py. The
    resolution uses ``effective_role_on_sub_org`` from role_permissions
    so a parent admin (with default-on transferability) sees the full
    permission set on a sub-org they have no direct membership in.
    """
    member_count = db.query(models.SubOrgMembership).filter(
        models.SubOrgMembership.sub_org_id == sub_org.id,
        models.SubOrgMembership.status == "active",
    ).count()

    user_role: Optional[str] = None
    user_permissions: list[str] = []
    if user_id:
        # Phase 15: resolve the EFFECTIVE role (sub-org assignment ->
        # transferable parent role -> platform admin), not just the
        # direct sub-org membership. This matches Phase 12.5's
        # _org_to_out pattern of returning the resolved permission set.
        role, _via_pa = effective_role_on_sub_org(db, user_id, sub_org)
        if role is not None:
            user_role = role.system_key
            for perm_def in PERMISSION_REGISTRY:
                allowed, _ = has_permission_on_sub_org(
                    db, user_id, sub_org, perm_def.key,
                )
                if allowed:
                    user_permissions.append(perm_def.key)

    return schemas.SubOrgOut(
        id=sub_org.id,
        name=sub_org.name,
        slug=sub_org.slug,
        description=sub_org.description or "",
        parent_org_id=sub_org.parent_org_id,
        settings=sub_org.settings or {},
        member_count=member_count,
        user_role=user_role,
        user_permissions=user_permissions,
        created_at=sub_org.created_at,
    )


def _sub_member_to_out(
    db: Session, sm: models.SubOrgMembership
) -> schemas.SubOrgMemberOut:
    user = db.get(models.User, sm.user_id)
    return schemas.SubOrgMemberOut(
        user_id=sm.user_id,
        username=user.username if user else "",
        display_name=user.display_name if user else "",
        email=user.email if user else None,
        avatar_url=user.avatar_url if user else None,
        # Phase 15 Cluster S: emit the role.system_key, not the legacy
        # string column. Frontend reads this.
        role=_sub_membership_role_system_key(sm) or "member",
        status=sm.status,
        joined_at=sm.joined_at,
    )


# ============================================================================
# Sub-org CRUD
# ============================================================================

@router.post(
    "/{org_slug}/sub-orgs",
    response_model=schemas.SubOrgOut,
    status_code=status.HTTP_201_CREATED,
)
def create_sub_org(
    org_slug: str,
    body: schemas.SubOrgCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Create a sub-org under the parent (parent-org admin only).

    Decision 1: rejects the request 400 if the parent org itself has a
    non-null `parent_org_id` — sub-orgs cannot have sub-sub-orgs. The schema
    allows arbitrary depth; this is the API-layer enforcement point.

    Note: dependency injection for the admin check is handled inline rather
    than via `require_org_admin` so the Decision-1 400 fires BEFORE the admin
    403 — otherwise a parent-org admin trying to create a sub-sub-org gets
    403 (because they're not admin of the level-1 sub-org), which masks the
    real reason (it's structurally disallowed).
    """
    parent = _parent_or_404(db, org_slug)

    if parent.parent_org_id is not None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Cannot create a sub-org under another sub-org. "
                "Two-level hierarchy only (Decision 1)."
            ),
        )

    # Now enforce parent-org admin permission inline.
    if not _is_parent_org_admin(db, current_user.id, parent):
        raise HTTPException(status_code=403, detail="Admin access required")

    # Phase 11 B1: reserved-words check. Sub-slugs only ever appear as the
    # second slug position (/{org-slug}/admin/sub-orgs/{sub-slug}/...) so
    # they don't collide with frontend top-level routes — but we apply the
    # same check for consistency, to avoid surprising errors elsewhere, and
    # to keep the rule "all org-like slugs follow the same allowlist" true.
    if body.slug.lower() in RESERVED_SLUGS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"The slug '{body.slug}' is reserved and cannot be used. "
                "Please pick a different one."
            ),
        )

    if db.query(models.Organization).filter(
        models.Organization.slug == body.slug
    ).first():
        raise HTTPException(status_code=400, detail="Organization slug already taken")

    sub_org = models.Organization(
        name=body.name,
        slug=body.slug,
        description=body.description,
        # Sub-orgs default to invite_only — Decision 9 mentions this is the
        # typical pattern; sub-org admin can flip later via PATCH.
        join_policy="invite_only",
        settings=body.settings or {},
        parent_org_id=parent.id,
    )
    db.add(sub_org)
    db.flush()

    # Phase 9.6 Workstream 2 — auto-add the creating parent-org admin as a
    # sub-org admin so the SubOrg admin pages they immediately land on are
    # not gated against them. Mirrors the org-creation pattern where the
    # creator is bootstrapped as owner. No separate audit event — the
    # `sub_org.created` event with this actor implies the auto-add.
    # Phase 15 Cluster S: SubOrgMembership.role is now an FK to the
    # parent's Role row.
    creator_role_id = _resolve_parent_role_id(db, parent.id, "admin")
    creator_membership = models.SubOrgMembership(
        user_id=current_user.id,
        sub_org_id=sub_org.id,
        role_id=creator_role_id,
        status="active",
    )
    db.add(creator_membership)

    log_audit_event(
        db,
        action="sub_org.created",
        target_type="organization",
        target_id=sub_org.id,
        actor_id=current_user.id,
        details={
            "sub_org_id": sub_org.id,
            "name": sub_org.name,
            "slug": sub_org.slug,
            "parent_org_id": parent.id,
        },
        ip_address=request.client.host if request.client else None,
    )

    db.commit()
    db.refresh(sub_org)
    return _sub_org_to_out(sub_org, db, current_user.id)


@router.get("/{org_slug}/sub-orgs", response_model=list[schemas.SubOrgOut])
def list_sub_orgs(
    org_slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """List sub-orgs of a parent (parent-org members).

    Decision 7 visibility filter: sub-orgs whose `settings.private` is True
    are filtered out of the list for non-members of those sub-orgs, except
    parent-org admins always see everything (Decision 6).
    """
    parent = _parent_or_404(db, org_slug)
    # Phase 12 — admin-tier on Role.system_key (renamed 'owner' → 'steward').
    is_parent_admin = (
        membership.role is not None
        and membership.role.system_key in ("admin", "steward")
    )

    sub_orgs = db.query(models.Organization).filter(
        models.Organization.parent_org_id == parent.id
    ).order_by(models.Organization.name).all()

    if is_parent_admin:
        visible = sub_orgs
    else:
        visible = []
        for s in sub_orgs:
            if not (s.settings or {}).get("private", False):
                visible.append(s)
                continue
            sm = db.query(models.SubOrgMembership).filter(
                models.SubOrgMembership.user_id == current_user.id,
                models.SubOrgMembership.sub_org_id == s.id,
                models.SubOrgMembership.status == "active",
            ).first()
            if sm:
                visible.append(s)

    return [_sub_org_to_out(s, db, current_user.id) for s in visible]


@router.get(
    "/{org_slug}/sub-orgs/{sub_slug}",
    response_model=schemas.SubOrgOut,
)
def get_sub_org(
    org_slug: str,
    sub_slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """Sub-org detail. 404 if not a sub-org of this parent.

    Decision 7: if the sub-org is private, only sub-org members + parent-org
    admins can fetch detail.
    """
    parent = _parent_or_404(db, org_slug)
    sub_org = _sub_org_or_404(db, parent, sub_slug)

    # Phase 12 — admin-tier on Role.system_key (renamed 'owner' → 'steward').
    is_parent_admin = (
        membership.role is not None
        and membership.role.system_key in ("admin", "steward")
    )
    if (sub_org.settings or {}).get("private", False) and not is_parent_admin:
        sm = db.query(models.SubOrgMembership).filter(
            models.SubOrgMembership.user_id == current_user.id,
            models.SubOrgMembership.sub_org_id == sub_org.id,
            models.SubOrgMembership.status == "active",
        ).first()
        if sm is None:
            raise HTTPException(status_code=404, detail="Sub-organization not found")

    return _sub_org_to_out(sub_org, db, current_user.id)


@router.patch(
    "/{org_slug}/sub-orgs/{sub_slug}",
    response_model=schemas.SubOrgOut,
)
def update_sub_org(
    org_slug: str,
    sub_slug: str,
    body: schemas.SubOrgUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Update sub-org (sub-org admin OR parent-org admin via implicit power).

    Audit: emits `sub_org.updated` with a `changes` map of `{key: {old, new}}`
    listing only keys that actually changed (Phase 8 sustained-majority diff
    pattern). When `settings.private` flips, ALSO emits
    `sub_org.privacy_changed`. When the strict-in-group flag
    `settings.reject_non_member_delegations` flips, emits
    `sub_org.cross_scope_delegation_setting_changed`.
    """
    parent = _parent_or_404(db, org_slug)
    sub_org = _sub_org_or_404(db, parent, sub_slug)

    if not is_sub_org_admin(db, current_user.id, sub_org):
        raise HTTPException(
            status_code=403,
            detail="Sub-org admin (or parent-org admin) access required",
        )

    changes: dict = {}
    privacy_change: Optional[dict] = None
    cross_scope_change: Optional[dict] = None

    if body.name is not None and body.name != sub_org.name:
        changes["name"] = {"old": sub_org.name, "new": body.name}
        sub_org.name = body.name
    if body.description is not None and body.description != (sub_org.description or ""):
        changes["description"] = {
            "old": sub_org.description or "",
            "new": body.description,
        }
        sub_org.description = body.description

    if body.settings is not None:
        old_settings = dict(sub_org.settings or {})
        new_settings = {**old_settings, **body.settings}

        # Detect setting-level changes for the audit trail.
        for key, new_val in body.settings.items():
            old_val = old_settings.get(key)
            if old_val != new_val:
                changes.setdefault("settings", {})[key] = {
                    "old": old_val, "new": new_val,
                }
                if key == "private":
                    privacy_change = {
                        "old_value": bool(old_val),
                        "new_value": bool(new_val),
                    }
                if key == "reject_non_member_delegations":
                    cross_scope_change = {
                        "old_value": bool(old_val),
                        "new_value": bool(new_val),
                    }

        sub_org.settings = new_settings

    if changes:
        log_audit_event(
            db,
            action="sub_org.updated",
            target_type="organization",
            target_id=sub_org.id,
            actor_id=current_user.id,
            details={"sub_org_id": sub_org.id, "changes": changes},
            ip_address=request.client.host if request.client else None,
        )
    if privacy_change is not None:
        log_audit_event(
            db,
            action="sub_org.privacy_changed",
            target_type="organization",
            target_id=sub_org.id,
            actor_id=current_user.id,
            details={"sub_org_id": sub_org.id, **privacy_change},
            ip_address=request.client.host if request.client else None,
        )
    if cross_scope_change is not None:
        log_audit_event(
            db,
            action="sub_org.cross_scope_delegation_setting_changed",
            target_type="organization",
            target_id=sub_org.id,
            actor_id=current_user.id,
            details={"sub_org_id": sub_org.id, **cross_scope_change},
            ip_address=request.client.host if request.client else None,
        )

    db.commit()
    db.refresh(sub_org)
    return _sub_org_to_out(sub_org, db, current_user.id)


@router.delete(
    "/{org_slug}/sub-orgs/{sub_slug}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_sub_org(
    org_slug: str,
    sub_slug: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Delete a sub-org (parent-org admin or sub-org owner).

    Behavior choice: 409 Conflict if the sub-org has any non-archived
    proposals or topics scoped to it. Cascading would orphan votes and
    delegations on those proposals/topics in confusing ways; requiring the
    admin to explicitly clean up first matches the existing parent-org
    delete-protection norms.
    """
    parent = _parent_or_404(db, org_slug)
    sub_org = _sub_org_or_404(db, parent, sub_slug)

    is_parent_admin = _is_parent_org_admin(db, current_user.id, parent)
    # Phase 15 Cluster S: "owner" → "steward" rename applies here too.
    is_sub_steward = False
    sm = db.query(models.SubOrgMembership).filter(
        models.SubOrgMembership.user_id == current_user.id,
        models.SubOrgMembership.sub_org_id == sub_org.id,
        models.SubOrgMembership.status == "active",
    ).first()
    if _sub_membership_role_system_key(sm) == "steward":
        is_sub_steward = True

    if not (is_parent_admin or is_sub_steward):
        raise HTTPException(
            status_code=403,
            detail="Parent-org admin or sub-org Steward access required",
        )

    # Block delete if the sub-org has any active topics or proposals.
    topic_count = db.query(models.Topic).filter(
        models.Topic.sub_org_id == sub_org.id,
    ).count()
    proposal_count = db.query(models.Proposal).filter(
        models.Proposal.sub_org_id == sub_org.id,
    ).count()
    if topic_count or proposal_count:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Sub-org has {topic_count} topic(s) and {proposal_count} "
                "proposal(s) scoped to it. Promote, archive, or delete those "
                "first before deleting the sub-org."
            ),
        )

    log_audit_event(
        db,
        action="sub_org.deleted",
        target_type="organization",
        target_id=sub_org.id,
        actor_id=current_user.id,
        details={
            "sub_org_id": sub_org.id, "name": sub_org.name, "slug": sub_org.slug,
        },
        ip_address=request.client.host if request.client else None,
    )

    db.delete(sub_org)  # cascades to sub_org_memberships via the relationship
    db.commit()


# ============================================================================
# Sub-org membership flows
# ============================================================================

@router.get(
    "/{org_slug}/sub-orgs/{sub_slug}/members",
    response_model=list[schemas.SubOrgMemberOut],
)
def list_sub_org_members(
    org_slug: str,
    sub_slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """List sub-org members. Sub-org members + parent-org admins can see."""
    parent = _parent_or_404(db, org_slug)
    sub_org = _sub_org_or_404(db, parent, sub_slug)

    # Phase 12 — admin-tier on Role.system_key (renamed 'owner' → 'steward').
    is_parent_admin = (
        membership.role is not None
        and membership.role.system_key in ("admin", "steward")
    )
    sm = db.query(models.SubOrgMembership).filter(
        models.SubOrgMembership.user_id == current_user.id,
        models.SubOrgMembership.sub_org_id == sub_org.id,
        models.SubOrgMembership.status == "active",
    ).first()
    if not (is_parent_admin or sm is not None):
        raise HTTPException(
            status_code=403,
            detail="Sub-org members or parent-org admins only",
        )

    rows = db.query(models.SubOrgMembership).filter(
        models.SubOrgMembership.sub_org_id == sub_org.id,
    ).all()
    return [_sub_member_to_out(db, m) for m in rows]


@router.post(
    "/{org_slug}/sub-orgs/{sub_slug}/members/invite",
    status_code=200,
)
def invite_sub_org_member(
    org_slug: str,
    sub_slug: str,
    body: schemas.SubOrgMemberInvite,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Sub-org admin invites a parent-org member.

    The invitee must already be an active parent-org member; if not, 400.
    Creates a SubOrgMembership in `pending_approval` status (mirrors the
    existing parent-org join flow's `pending_approval` value).
    """
    parent = _parent_or_404(db, org_slug)
    sub_org = _sub_org_or_404(db, parent, sub_slug)

    if not is_sub_org_admin(db, current_user.id, sub_org):
        raise HTTPException(
            status_code=403,
            detail="Sub-org admin (or parent-org admin) access required",
        )

    target = db.get(models.User, body.user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    parent_m = _require_parent_org_member(db, body.user_id, parent)
    if parent_m is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Invitee is not an active parent-org member. They must join "
                "the parent org before they can be invited to a sub-org."
            ),
        )

    target_role_id = _resolve_parent_role_id(db, parent.id, body.role)
    existing = db.query(models.SubOrgMembership).filter(
        models.SubOrgMembership.user_id == body.user_id,
        models.SubOrgMembership.sub_org_id == sub_org.id,
    ).first()
    if existing:
        if existing.status == "active":
            raise HTTPException(status_code=409, detail="Already a sub-org member")
        if existing.status == "pending_approval":
            raise HTTPException(
                status_code=409, detail="Invite already pending"
            )
        # suspended -> resurrect as pending
        existing.status = "pending_approval"
        existing.role_id = target_role_id
    else:
        sm = models.SubOrgMembership(
            user_id=body.user_id,
            sub_org_id=sub_org.id,
            role_id=target_role_id,
            status="pending_approval",
        )
        db.add(sm)

    log_audit_event(
        db,
        action="sub_org.member_invited",
        target_type="sub_org_membership",
        target_id=sub_org.id,
        actor_id=current_user.id,
        details={
            "sub_org_id": sub_org.id,
            "target_user_id": body.user_id,
            # Phase 15 Cluster S: emit the canonical system_key (translates
            # any "owner" backwards-compat input to "steward").
            "role": _REQUEST_ROLE_TO_SYSTEM_KEY.get(body.role, body.role),
        },
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return {"message": "Invite sent", "status": "pending_approval"}


@router.post(
    "/{org_slug}/sub-orgs/{sub_slug}/members/add",
    status_code=200,
    response_model=schemas.SubOrgMemberOut,
)
def add_sub_org_member_directly(
    org_slug: str,
    sub_slug: str,
    body: schemas.SubOrgMemberDirectAdd,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Phase 9.6 Workstream 2 — directly add an active parent-org member to a
    sub-org, bypassing the invitation/approval flow.

    Permission: parent-org admin OR sub-org admin (Decision 6 lite — sub-org
    admins can also use this fast path).

    Validation:
      - target user must be an active parent-org member (otherwise 400)
      - target user must NOT already have a SubOrgMembership row for this
        sub-org (otherwise 400 — caller should use change-role / approve
        instead)

    Default role is 'member' if not provided. Audit event
    `sub_org_member.added_directly` distinguishes this fast path from the
    invitation flow (`sub_org.member_invited` + `sub_org.member_joined`).
    """
    parent = _parent_or_404(db, org_slug)
    sub_org = _sub_org_or_404(db, parent, sub_slug)

    if not is_sub_org_admin(db, current_user.id, sub_org):
        raise HTTPException(
            status_code=403,
            detail="Sub-org admin (or parent-org admin) access required",
        )

    target = db.get(models.User, body.user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    parent_m = _require_parent_org_member(db, body.user_id, parent)
    if parent_m is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Target user must be added to the parent org first via "
                "invitation. Direct-add only works for existing active "
                "parent-org members."
            ),
        )

    existing = db.query(models.SubOrgMembership).filter(
        models.SubOrgMembership.user_id == body.user_id,
        models.SubOrgMembership.sub_org_id == sub_org.id,
    ).first()
    if existing is not None:
        raise HTTPException(status_code=400, detail="Already a member")

    target_role_id = _resolve_parent_role_id(db, parent.id, body.role)
    sm = models.SubOrgMembership(
        user_id=body.user_id,
        sub_org_id=sub_org.id,
        role_id=target_role_id,
        status="active",
    )
    db.add(sm)
    db.flush()

    log_audit_event(
        db,
        action="sub_org_member.added_directly",
        target_type="sub_org_membership",
        target_id=sub_org.id,
        actor_id=current_user.id,
        details={
            "sub_org_id": sub_org.id,
            "target_user_id": body.user_id,
            "role": _REQUEST_ROLE_TO_SYSTEM_KEY.get(body.role, body.role),
            "by_actor": current_user.id,
        },
        ip_address=request.client.host if request.client else None,
    )

    db.commit()
    db.refresh(sm)
    return _sub_member_to_out(db, sm)


@router.post(
    "/{org_slug}/sub-orgs/{sub_slug}/members/request-join",
    status_code=200,
)
def request_join_sub_org(
    org_slug: str,
    sub_slug: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """Parent-org member self-requests to join a sub-org. Status pending."""
    parent = _parent_or_404(db, org_slug)
    sub_org = _sub_org_or_404(db, parent, sub_slug)

    member_role_id = _resolve_parent_role_id(db, parent.id, "member")
    existing = db.query(models.SubOrgMembership).filter(
        models.SubOrgMembership.user_id == current_user.id,
        models.SubOrgMembership.sub_org_id == sub_org.id,
    ).first()
    if existing:
        if existing.status == "active":
            raise HTTPException(status_code=409, detail="Already a sub-org member")
        if existing.status == "pending_approval":
            raise HTTPException(status_code=409, detail="Join request already pending")
        existing.status = "pending_approval"
        existing.role_id = member_role_id
    else:
        sm = models.SubOrgMembership(
            user_id=current_user.id,
            sub_org_id=sub_org.id,
            role_id=member_role_id,
            status="pending_approval",
        )
        db.add(sm)

    log_audit_event(
        db,
        action="sub_org.member_invited",
        target_type="sub_org_membership",
        target_id=sub_org.id,
        actor_id=current_user.id,
        details={
            "sub_org_id": sub_org.id,
            "target_user_id": current_user.id,
            "role": "member",
            # `requested: true` distinguishes self-request from admin invite
            # in the audit log.
            "requested": True,
        },
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return {"message": "Join request submitted", "status": "pending_approval"}


@router.post(
    "/{org_slug}/sub-orgs/{sub_slug}/members/{user_id}/approve",
    status_code=200,
)
def approve_sub_org_member(
    org_slug: str,
    sub_slug: str,
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Sub-org admin approves a pending invite/request."""
    parent = _parent_or_404(db, org_slug)
    sub_org = _sub_org_or_404(db, parent, sub_slug)

    if not is_sub_org_admin(db, current_user.id, sub_org):
        raise HTTPException(
            status_code=403,
            detail="Sub-org admin (or parent-org admin) access required",
        )

    sm = db.query(models.SubOrgMembership).filter(
        models.SubOrgMembership.user_id == user_id,
        models.SubOrgMembership.sub_org_id == sub_org.id,
        models.SubOrgMembership.status == "pending_approval",
    ).first()
    if sm is None:
        raise HTTPException(
            status_code=404, detail="Pending sub-org membership not found",
        )
    sm.status = "active"
    sm.joined_at = _now()

    log_audit_event(
        db,
        action="sub_org.member_joined",
        target_type="sub_org_membership",
        target_id=sub_org.id,
        actor_id=current_user.id,
        details={
            "sub_org_id": sub_org.id,
            "target_user_id": user_id,
            # Phase 15 Cluster S: emit role.system_key, not the legacy
            # string; the FK relationship's system_key is the canonical
            # form.
            "role": _sub_membership_role_system_key(sm) or "member",
        },
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return {"message": "Member approved", "status": "active"}


@router.post(
    "/{org_slug}/sub-orgs/{sub_slug}/members/{user_id}/deny",
    status_code=200,
)
def deny_sub_org_member(
    org_slug: str,
    sub_slug: str,
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Sub-org admin denies a pending invite/request. Row is hard-deleted;
    the audit event is the only durable record."""
    parent = _parent_or_404(db, org_slug)
    sub_org = _sub_org_or_404(db, parent, sub_slug)

    if not is_sub_org_admin(db, current_user.id, sub_org):
        raise HTTPException(
            status_code=403,
            detail="Sub-org admin (or parent-org admin) access required",
        )

    sm = db.query(models.SubOrgMembership).filter(
        models.SubOrgMembership.user_id == user_id,
        models.SubOrgMembership.sub_org_id == sub_org.id,
        models.SubOrgMembership.status == "pending_approval",
    ).first()
    if sm is None:
        raise HTTPException(
            status_code=404, detail="Pending sub-org membership not found",
        )

    log_audit_event(
        db,
        action="sub_org.member_removed",
        target_type="sub_org_membership",
        target_id=sub_org.id,
        actor_id=current_user.id,
        details={
            "sub_org_id": sub_org.id,
            "target_user_id": user_id,
            "reason": "denied",
        },
        ip_address=request.client.host if request.client else None,
    )
    db.delete(sm)
    db.commit()
    return {"message": "Membership denied"}


@router.post(
    "/{org_slug}/sub-orgs/{sub_slug}/members/{user_id}/remove",
    status_code=200,
)
def remove_sub_org_member(
    org_slug: str,
    sub_slug: str,
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Sub-org admin removes an active member."""
    parent = _parent_or_404(db, org_slug)
    sub_org = _sub_org_or_404(db, parent, sub_slug)

    if not is_sub_org_admin(db, current_user.id, sub_org):
        raise HTTPException(
            status_code=403,
            detail="Sub-org admin (or parent-org admin) access required",
        )

    sm = db.query(models.SubOrgMembership).filter(
        models.SubOrgMembership.user_id == user_id,
        models.SubOrgMembership.sub_org_id == sub_org.id,
    ).first()
    if sm is None:
        raise HTTPException(status_code=404, detail="Sub-org member not found")
    # Phase 15 Cluster S — "owner" → "steward" rename applies to the
    # protect-from-removal gate too.
    if _sub_membership_role_system_key(sm) == "steward":
        raise HTTPException(
            status_code=400, detail="Cannot remove the sub-org Steward",
        )

    log_audit_event(
        db,
        action="sub_org.member_removed",
        target_type="sub_org_membership",
        target_id=sub_org.id,
        actor_id=current_user.id,
        details={
            "sub_org_id": sub_org.id,
            "target_user_id": user_id,
            "reason": "removed",
        },
        ip_address=request.client.host if request.client else None,
    )
    db.delete(sm)
    db.commit()
    return {"message": "Member removed"}


@router.post(
    "/{org_slug}/sub-orgs/{sub_slug}/members/{user_id}/change-role",
    response_model=schemas.SubOrgMemberOut,
)
def change_sub_org_member_role(
    org_slug: str,
    sub_slug: str,
    user_id: str,
    body: schemas.SubOrgMemberRoleUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Sub-org admin changes a member's role."""
    parent = _parent_or_404(db, org_slug)
    sub_org = _sub_org_or_404(db, parent, sub_slug)

    if not is_sub_org_admin(db, current_user.id, sub_org):
        raise HTTPException(
            status_code=403,
            detail="Sub-org admin (or parent-org admin) access required",
        )

    sm = db.query(models.SubOrgMembership).filter(
        models.SubOrgMembership.user_id == user_id,
        models.SubOrgMembership.sub_org_id == sub_org.id,
    ).first()
    if sm is None:
        raise HTTPException(status_code=404, detail="Sub-org member not found")
    old_role_sk = _sub_membership_role_system_key(sm)
    new_role_sk = _REQUEST_ROLE_TO_SYSTEM_KEY.get(body.role, body.role)
    # Phase 15 Cluster S — "owner" → "steward" rename: the demote-from-
    # Steward gate parallels the parent-org Steward protection.
    if old_role_sk == "steward" and new_role_sk != "steward":
        raise HTTPException(
            status_code=400,
            detail="Cannot demote the sub-org Steward",
        )

    new_role_id = _resolve_parent_role_id(db, parent.id, body.role)
    sm.role_id = new_role_id

    log_audit_event(
        db,
        action="sub_org.member_role_changed",
        target_type="sub_org_membership",
        target_id=sub_org.id,
        actor_id=current_user.id,
        details={
            "sub_org_id": sub_org.id,
            "target_user_id": user_id,
            "old_role": old_role_sk,
            "new_role": new_role_sk,
        },
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(sm)
    return _sub_member_to_out(db, sm)


# ============================================================================
# Promote-to-org-wide  (Decision 3)
# ============================================================================

@router.post(
    "/{org_slug}/topics/{topic_id}/promote-to-orgwide",
    response_model=schemas.TopicOut,
)
def promote_topic_to_orgwide(
    org_slug: str,
    topic_id: str,
    body: schemas.PromoteTopicToOrgwide,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Promote a sub-org-scoped topic to parent-org-wide.

    **This action is irreversible.** The spec explicitly omits a reverse
    "demote" endpoint because demoting an org-wide topic to sub-org scope
    would orphan delegations and proposals already attached to it. To prevent
    accidental promotion, the body MUST include `confirm: true`.

    Authorization: sub-org admin OR parent-org admin (via implicit power).
    """
    parent = _parent_or_404(db, org_slug)

    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail=(
                "Promotion is irreversible. Set `confirm: true` in the body "
                "to proceed."
            ),
        )

    topic = db.query(models.Topic).filter(
        models.Topic.id == topic_id,
        models.Topic.org_id == parent.id,
    ).first()
    if topic is None:
        raise HTTPException(
            status_code=404, detail="Topic not found in this organization",
        )
    if topic.sub_org_id is None:
        raise HTTPException(
            status_code=400,
            detail="Topic is already org-wide; nothing to promote.",
        )

    promoted_from = topic.sub_org_id
    sub_org = db.get(models.Organization, promoted_from)
    if sub_org is None or sub_org.parent_org_id != parent.id:
        # Defensive: topic.sub_org_id should always be a child of org.
        raise HTTPException(
            status_code=400,
            detail="Topic's sub_org_id is not a sub-org of this parent",
        )

    if not is_sub_org_admin(db, current_user.id, sub_org):
        raise HTTPException(
            status_code=403,
            detail="Sub-org admin (or parent-org admin) access required",
        )

    topic.sub_org_id = None

    log_audit_event(
        db,
        action="topic.promoted_to_orgwide",
        target_type="topic",
        target_id=topic.id,
        actor_id=current_user.id,
        details={
            "topic_id": topic.id,
            "name": topic.name,
            "promoted_from_sub_org_id": promoted_from,
            "promoted_by": current_user.id,
        },
        ip_address=request.client.host if request.client else None,
    )

    db.commit()
    db.refresh(topic)
    return topic
