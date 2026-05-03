"""
Phase 8.5 Session 2 — Sub-organization endpoints.

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
from permissions import is_sub_org_admin
from reserved_slugs import RESERVED_SLUGS

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
    m = db.query(models.OrgMembership).filter(
        models.OrgMembership.user_id == user_id,
        models.OrgMembership.org_id == parent.id,
        models.OrgMembership.status == "active",
    ).first()
    return m is not None and m.role in ("admin", "owner")


def _sub_org_to_out(
    sub_org: models.Organization,
    db: Session,
    user_id: Optional[str] = None,
) -> schemas.SubOrgOut:
    member_count = db.query(models.SubOrgMembership).filter(
        models.SubOrgMembership.sub_org_id == sub_org.id,
        models.SubOrgMembership.status == "active",
    ).count()

    user_role = None
    if user_id:
        sm = db.query(models.SubOrgMembership).filter(
            models.SubOrgMembership.sub_org_id == sub_org.id,
            models.SubOrgMembership.user_id == user_id,
            models.SubOrgMembership.status == "active",
        ).first()
        if sm:
            user_role = sm.role

    return schemas.SubOrgOut(
        id=sub_org.id,
        name=sub_org.name,
        slug=sub_org.slug,
        description=sub_org.description or "",
        parent_org_id=sub_org.parent_org_id,
        settings=sub_org.settings or {},
        member_count=member_count,
        user_role=user_role,
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
        role=sm.role,
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
    creator_membership = models.SubOrgMembership(
        user_id=current_user.id,
        sub_org_id=sub_org.id,
        role="admin",
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
    is_parent_admin = membership.role in ("admin", "owner")

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

    is_parent_admin = membership.role in ("admin", "owner")
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
    is_sub_owner = False
    sm = db.query(models.SubOrgMembership).filter(
        models.SubOrgMembership.user_id == current_user.id,
        models.SubOrgMembership.sub_org_id == sub_org.id,
        models.SubOrgMembership.status == "active",
    ).first()
    if sm is not None and sm.role == "owner":
        is_sub_owner = True

    if not (is_parent_admin or is_sub_owner):
        raise HTTPException(
            status_code=403,
            detail="Parent-org admin or sub-org owner access required",
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

    is_parent_admin = membership.role in ("admin", "owner")
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
        existing.role = body.role
    else:
        sm = models.SubOrgMembership(
            user_id=body.user_id,
            sub_org_id=sub_org.id,
            role=body.role,
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
            "role": body.role,
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

    sm = models.SubOrgMembership(
        user_id=body.user_id,
        sub_org_id=sub_org.id,
        role=body.role,
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
            "role": body.role,
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
        existing.role = "member"
    else:
        sm = models.SubOrgMembership(
            user_id=current_user.id,
            sub_org_id=sub_org.id,
            role="member",
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
            "role": sm.role,
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
    if sm.role == "owner":
        raise HTTPException(
            status_code=400, detail="Cannot remove the sub-org owner",
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
    if sm.role == "owner" and body.role != "owner":
        raise HTTPException(
            status_code=400,
            detail="Cannot demote the sub-org owner",
        )

    old_role = sm.role
    sm.role = body.role

    log_audit_event(
        db,
        action="sub_org.member_role_changed",
        target_type="sub_org_membership",
        target_id=sub_org.id,
        actor_id=current_user.id,
        details={
            "sub_org_id": sub_org.id,
            "target_user_id": user_id,
            "old_role": old_role,
            "new_role": body.role,
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
