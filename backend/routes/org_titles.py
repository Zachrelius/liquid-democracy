"""Phase 47 — Org titles / offices HTTP routes.

CRUD on titles (B2) + assignment / revocation (B3). The title concept
is additive over the platform role model per D2; bound-role
assignments flow through the existing 45a/45b role-assignment
machinery so the cardinality floor is unchanged.

System titles (Steward, Admin) are uneditable + undeletable + not
directly assignable per D6. They are a label layer over the existing
role and are derived from membership.role at response-build time.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

import auth as auth_utils
import models
from audit_utils import log_audit_event
from database import get_db
from org_middleware import (
    get_org_context, membership_role_system_key, require_org_membership,
)
from org_titles import (
    SYSTEM_TITLE_DEFINITIONS, assignment_count, grant_title,
    revoke_title, validate_title_input,
)
from role_permissions import has_permission


router = APIRouter(prefix="/api/orgs", tags=["org-titles"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class _TitleCreateBody(BaseModel):
    name: str
    bound_role: Optional[str] = None  # 'steward' | 'admin' | 'moderator' | 'member' | None
    cardinality_mode: str = "single"
    max_holders: Optional[int] = None
    fill_method: str = "assigned"
    display_order: int = 0
    # Phase 49 — fixed-term scheduled re-election (D1, D4).
    # None / 0 / negative => no term (Phase 48 elected-until-
    # challenged behavior preserved).
    term_length_days: Optional[int] = None
    election_lead_time_days: Optional[int] = None


class _TitleUpdateBody(BaseModel):
    name: Optional[str] = None
    bound_role: Optional[str] = None
    cardinality_mode: Optional[str] = None
    max_holders: Optional[int] = None
    fill_method: Optional[str] = None
    display_order: Optional[int] = None
    # Phase 49 — term fields are PATCH-able. Setting term_length_days
    # to None or 0 clears the term (and the next-due timestamp); a
    # positive value sets/updates the term and recomputes
    # next_election_due_at on the server when newly set or changed.
    term_length_days: Optional[int] = None
    election_lead_time_days: Optional[int] = None


class _TitleAssignBody(BaseModel):
    user_id: str


class _TitleOut(BaseModel):
    id: str
    org_id: str
    name: str
    bound_role: Optional[str]
    cardinality_mode: str
    max_holders: Optional[int]
    fill_method: str
    is_system: bool
    display_order: int
    holder_count: int
    # Phase 49 — term-config surface.
    term_length_days: Optional[int]
    election_lead_time_days: int
    next_election_due_at: Optional[str]

    @classmethod
    def from_orm(cls, db: Session, title: models.OrgTitle) -> "_TitleOut":
        return cls(
            id=title.id,
            org_id=title.org_id,
            name=title.name,
            bound_role=title.bound_role,
            cardinality_mode=title.cardinality_mode,
            max_holders=title.max_holders,
            fill_method=title.fill_method,
            is_system=title.is_system,
            display_order=title.display_order,
            holder_count=assignment_count(db, title.id),
            term_length_days=title.term_length_days,
            election_lead_time_days=title.election_lead_time_days,
            next_election_due_at=(
                title.next_election_due_at.isoformat()
                if title.next_election_due_at else None
            ),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_title_manage(db: Session, user_id: str, org_id: str) -> None:
    if not has_permission(db, user_id, org_id, "title.manage"):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to manage titles in this organization.",
        )


def _resolve_title_or_404(
    db: Session, org_id: str, title_id: str,
) -> models.OrgTitle:
    title = db.get(models.OrgTitle, title_id)
    if title is None or title.org_id != org_id:
        raise HTTPException(status_code=404, detail="Title not found")
    return title


def _bound_role_holders_count(
    db: Session, org: models.Organization, system_key: str,
) -> int:
    """Count active members of ``org`` whose role.system_key matches."""
    rows = db.query(models.OrgMembership).filter(
        models.OrgMembership.org_id == org.id,
        models.OrgMembership.status == "active",
    ).all()
    n = 0
    for m in rows:
        if m.role_id is None:
            continue
        role = db.get(models.Role, m.role_id)
        if role is not None and role.system_key == system_key:
            n += 1
    return n


# ---------------------------------------------------------------------------
# Routes — list + CRUD
# ---------------------------------------------------------------------------

@router.get("/{org_slug}/titles")
def list_titles(
    org_slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """List titles defined for this org (any active member can view)."""
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug,
    ).first()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    titles = (
        db.query(models.OrgTitle)
        .filter(models.OrgTitle.org_id == org.id)
        .order_by(models.OrgTitle.display_order, models.OrgTitle.name)
        .all()
    )
    return [_TitleOut.from_orm(db, t).model_dump() for t in titles]


@router.post("/{org_slug}/titles", status_code=status.HTTP_201_CREATED)
def create_title(
    org_slug: str,
    body: _TitleCreateBody,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug,
    ).first()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    _require_title_manage(db, current_user.id, org.id)

    validate_title_input(
        name=body.name,
        bound_role=body.bound_role,
        cardinality_mode=body.cardinality_mode,
        max_holders=body.max_holders,
        fill_method=body.fill_method,
    )

    # Don't shadow a system-title name.
    if any(body.name.strip().lower() == d["name"].lower() for d in SYSTEM_TITLE_DEFINITIONS):
        existing_system = db.query(models.OrgTitle).filter(
            models.OrgTitle.org_id == org.id,
            models.OrgTitle.name == body.name.strip(),
        ).first()
        if existing_system is not None and existing_system.is_system:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"'{body.name}' is a system title and cannot be "
                    "redefined. Pick a different name."
                ),
            )

    # Phase 49 — accept term config at create time. Setting a term
    # (positive term_length_days) computes next_election_due_at from
    # now so the schedule clock starts immediately. Lead-time defaults
    # to the model server_default (7) when not specified.
    term_length: Optional[int] = None
    if body.term_length_days is not None and int(body.term_length_days) > 0:
        term_length = int(body.term_length_days)
    lead_time = 7
    if body.election_lead_time_days is not None and int(body.election_lead_time_days) > 0:
        lead_time = int(body.election_lead_time_days)

    title = models.OrgTitle(
        org_id=org.id,
        name=body.name.strip(),
        bound_role=body.bound_role or None,
        cardinality_mode=body.cardinality_mode,
        max_holders=body.max_holders,
        fill_method=body.fill_method,
        display_order=body.display_order,
        term_length_days=term_length,
        election_lead_time_days=lead_time,
    )
    if term_length is not None:
        from datetime import datetime as _dt, timedelta as _td, timezone as _tz
        title.next_election_due_at = (
            _dt.now(_tz.utc).replace(tzinfo=None) + _td(days=term_length)
        )
    db.add(title)
    db.flush()
    log_audit_event(
        db,
        action="title.created",
        target_type="org_title",
        target_id=title.id,
        actor_id=current_user.id,
        details={
            "org_id": org.id,
            "name": title.name,
            "bound_role": title.bound_role,
            "cardinality_mode": title.cardinality_mode,
            "fill_method": title.fill_method,
        },
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(title)
    return _TitleOut.from_orm(db, title).model_dump()


@router.patch("/{org_slug}/titles/{title_id}")
def update_title(
    org_slug: str,
    title_id: str,
    body: _TitleUpdateBody,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug,
    ).first()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    _require_title_manage(db, current_user.id, org.id)
    title = _resolve_title_or_404(db, org.id, title_id)
    if title.is_system:
        raise HTTPException(
            status_code=400,
            detail="System titles cannot be edited.",
        )
    validate_title_input(
        name=body.name,
        bound_role=body.bound_role,
        cardinality_mode=body.cardinality_mode,
        max_holders=body.max_holders,
        fill_method=body.fill_method,
    )
    if body.name is not None:
        title.name = body.name.strip()
    if body.bound_role is not None:
        title.bound_role = body.bound_role or None
    if body.cardinality_mode is not None:
        title.cardinality_mode = body.cardinality_mode
    if body.max_holders is not None:
        title.max_holders = body.max_holders
    if body.fill_method is not None:
        title.fill_method = body.fill_method
    if body.display_order is not None:
        title.display_order = body.display_order
    # Phase 49 — term-config updates.
    # term_length_days=None means "no change" (Pydantic Optional);
    # term_length_days=0 OR a negative value means "clear the term"
    # (cancels scheduled re-elections). A positive value sets/updates
    # the term and recomputes next_election_due_at from now.
    if body.term_length_days is not None:
        new_term = int(body.term_length_days)
        if new_term <= 0:
            title.term_length_days = None
            title.next_election_due_at = None
        else:
            old_term = title.term_length_days
            title.term_length_days = new_term
            # Only (re)compute next-due if the term actually changed
            # OR if it was previously unset. This avoids resetting the
            # clock on a no-op PATCH that just touches other fields.
            if old_term != new_term or title.next_election_due_at is None:
                from datetime import (
                    datetime as _dt, timedelta as _td, timezone as _tz,
                )
                title.next_election_due_at = (
                    _dt.now(_tz.utc).replace(tzinfo=None) + _td(days=new_term)
                )
    if body.election_lead_time_days is not None:
        new_lead = int(body.election_lead_time_days)
        if new_lead < 1:
            new_lead = 1
        title.election_lead_time_days = new_lead
    log_audit_event(
        db,
        action="title.updated",
        target_type="org_title",
        target_id=title.id,
        actor_id=current_user.id,
        details={
            "org_id": org.id, "name": title.name,
            "term_length_days": title.term_length_days,
            "next_election_due_at": (
                title.next_election_due_at.isoformat()
                if title.next_election_due_at else None
            ),
        },
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(title)
    return _TitleOut.from_orm(db, title).model_dump()


@router.delete("/{org_slug}/titles/{title_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_title(
    org_slug: str,
    title_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug,
    ).first()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    _require_title_manage(db, current_user.id, org.id)
    title = _resolve_title_or_404(db, org.id, title_id)
    if title.is_system:
        raise HTTPException(
            status_code=400,
            detail="System titles cannot be deleted.",
        )
    # Phase 67 W4 — election proposals keep a permanent FK reference to
    # their target title (``proposals.election_title_id``, no
    # ondelete). Deleting such a title used to 500 with a raw FK
    # violation; surface a friendly 400 BEFORE attempting the delete.
    # Checked before the holders check so callers get the permanent
    # answer first (revoking holders wouldn't make this deletable).
    election_history_count = (
        db.query(models.Proposal)
        .filter(models.Proposal.election_title_id == title.id)
        .count()
    )
    if election_history_count > 0:
        raise HTTPException(
            status_code=400,
            detail=(
                "This title has election history and can't be deleted. "
                "Past elections keep a permanent record of the title "
                "they were held for; revoke its holders instead if it "
                "should no longer be in use."
            ),
        )
    if assignment_count(db, title.id) > 0:
        raise HTTPException(
            status_code=400,
            detail=(
                "Cannot delete a title that still has holders. Revoke "
                "all assignments first."
            ),
        )
    log_audit_event(
        db,
        action="title.deleted",
        target_type="org_title",
        target_id=title.id,
        actor_id=current_user.id,
        details={"org_id": org.id, "name": title.name},
        ip_address=request.client.host if request.client else None,
    )
    db.delete(title)
    db.commit()


# ---------------------------------------------------------------------------
# Routes — assignment / revocation (B3)
# ---------------------------------------------------------------------------

def _apply_bound_role_for_assign(
    db: Session, org: models.Organization, target_user: models.User,
    bound_role: str, request: Request,
) -> None:
    """Apply the bound role grant via the existing 45a/45b machinery.

    Per D2/D6 the role is the source of truth + the floor reads it.
    This function NEVER bypasses the floor — it routes through the
    same paths that ``change_member_role`` / ``transfer_stewardship``
    use, so the floor + governance-mode checks are uniform.
    """
    from governance import mode_of, ADMIN_COUNCIL, SINGLE_STEWARD

    target_membership = db.query(models.OrgMembership).filter(
        models.OrgMembership.org_id == org.id,
        models.OrgMembership.user_id == target_user.id,
        models.OrgMembership.status == "active",
    ).first()
    if target_membership is None:
        raise HTTPException(
            status_code=400,
            detail="Target user is not an active member of this org.",
        )

    target_role = db.query(models.Role).filter(
        models.Role.org_id == org.id,
        models.Role.system_key == bound_role,
    ).first()
    if target_role is None:
        raise HTTPException(
            status_code=500,
            detail=f"Org is missing the preset {bound_role!r} role",
        )

    current_key = membership_role_system_key(target_membership)

    # Phase 52 Stage 1 — verification role-grant gate. The check
    # goes BEFORE any role-id write (and before the steward atomic-
    # swap demote below). If the target fails verification, the
    # function raises HTTPException(403) with a structured payload;
    # the caller (manual assign route OR the election close hook)
    # decides how to surface it. The election close hook in
    # ``elections.finalize_election`` catches the 403, records a
    # ``title.assigned`` audit with reason="verification_required",
    # and leaves the existing role-holder unchanged — the
    # governance floor invariant is preserved by construction.
    # Skip the check when the target already holds the bound role
    # at or above the required tier (no-op assignment doesn't need
    # to re-verify).
    if current_key != bound_role:
        from verification import check_role_grant_floor, check_role_residency_for_grant
        check_role_grant_floor(target_user, org, bound_role)
        # Phase 52j J1 — also residency-scope.
        check_role_residency_for_grant(target_user, org, bound_role)

    # Steward binding has special handling per D7.
    if bound_role == "steward":
        if mode_of(org) == ADMIN_COUNCIL:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Cannot assign a steward-binding title in "
                    "admin_council mode — the org has no steward seat. "
                    "Switch governance mode first."
                ),
            )
        if current_key == "steward":
            return  # Already steward — no role change needed.
        # Find existing steward (if any) to atomically swap with.
        existing_steward = None
        for m in db.query(models.OrgMembership).filter(
            models.OrgMembership.org_id == org.id,
            models.OrgMembership.status == "active",
        ).all():
            if m.role_id is None:
                continue
            r = db.get(models.Role, m.role_id)
            if r is not None and r.system_key == "steward":
                existing_steward = m
                break
        if existing_steward is not None:
            # Demote prior steward to admin (mirrors transfer-stewardship).
            admin_role = db.query(models.Role).filter(
                models.Role.org_id == org.id,
                models.Role.system_key == "admin",
            ).first()
            if admin_role is None:
                raise HTTPException(
                    status_code=500,
                    detail="Org is missing the preset Admin role",
                )
            existing_steward.role_id = admin_role.id
            log_audit_event(
                db,
                action="org.stewardship_transferred",
                target_type="organization",
                target_id=org.id,
                actor_id=existing_steward.user_id,
                details={
                    "outgoing_steward_id": existing_steward.user_id,
                    "incoming_steward_id": target_user.id,
                    "trigger": "title_assignment",
                },
                ip_address=request.client.host if request.client else None,
            )
        target_membership.role_id = target_role.id
        return

    # Non-steward bindings: just bump role if it isn't already at-or-above.
    if current_key == bound_role:
        return
    target_membership.role_id = target_role.id


def _check_revoke_floor(
    db: Session, org: models.Organization, target_user_id: str, bound_role: str,
) -> None:
    """Floor check before revoking a bound-role title. If revocation
    would leave the org below its mode-specific floor (D2 + 45b D6),
    block."""
    if bound_role not in ("steward", "admin"):
        return
    from governance import (
        mode_of, ADMIN_COUNCIL, SINGLE_STEWARD,
        count_active_governors,
    )
    target_membership = db.query(models.OrgMembership).filter(
        models.OrgMembership.org_id == org.id,
        models.OrgMembership.user_id == target_user_id,
        models.OrgMembership.status == "active",
    ).first()
    if target_membership is None:
        return
    role = db.get(models.Role, target_membership.role_id) if target_membership.role_id else None
    if role is None or role.system_key != bound_role:
        return  # Target's role doesn't reflect this binding any more.

    if bound_role == "steward" and mode_of(org) == SINGLE_STEWARD:
        # Revoking would drop them from steward → floor block.
        raise HTTPException(
            status_code=400,
            detail=(
                "Cannot revoke a steward-binding title from the org's "
                "only steward — transfer stewardship first."
            ),
        )
    if bound_role == "admin" and mode_of(org) == ADMIN_COUNCIL:
        other = count_active_governors(
            db, org, exclude_user_id=target_user_id,
        )
        if other == 0:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Cannot revoke a admin-binding title from the org's "
                    "last admin in admin_council mode."
                ),
            )


@router.post("/{org_slug}/titles/{title_id}/assignments", status_code=status.HTTP_201_CREATED)
def assign_title(
    org_slug: str,
    title_id: str,
    body: _TitleAssignBody,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug,
    ).first()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    _require_title_manage(db, current_user.id, org.id)
    title = _resolve_title_or_404(db, org.id, title_id)

    # System titles cannot be assigned directly per D6 — the underlying
    # role is managed via transfer-stewardship / change-member-role.
    # Check BEFORE any role mutation so a system-title assign attempt
    # doesn't leave a half-applied state.
    if title.is_system:
        raise HTTPException(
            status_code=400,
            detail=(
                "System titles are derived from the member's role and "
                "cannot be assigned directly. Use the existing "
                "transfer-stewardship or change-member-role flows."
            ),
        )

    # Target must be an active member of the org.
    target_user = db.get(models.User, body.user_id)
    if target_user is None:
        raise HTTPException(status_code=404, detail="Target user not found")
    if not target_user.is_active:
        raise HTTPException(
            status_code=400,
            detail="Target user's account must be active.",
        )
    target_membership = db.query(models.OrgMembership).filter(
        models.OrgMembership.org_id == org.id,
        models.OrgMembership.user_id == body.user_id,
        models.OrgMembership.status == "active",
    ).first()
    if target_membership is None:
        raise HTTPException(
            status_code=400,
            detail="Target user is not an active member of this org.",
        )

    # Cardinality.
    if title.cardinality_mode == "single":
        current_count = assignment_count(db, title.id)
        if current_count >= 1:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"'{title.name}' is a single-holder title and is "
                    "already assigned. Revoke the current holder first."
                ),
            )
    elif title.cardinality_mode == "multi":
        if title.max_holders is not None:
            current_count = assignment_count(db, title.id)
            if current_count >= title.max_holders:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"'{title.name}' is already at its max_holders "
                        f"cap of {title.max_holders}."
                    ),
                )

    # Apply bound role (via the existing role-assignment machinery)
    # BEFORE inserting the assignment row, so floor / mode rejections
    # don't leave a half-applied state.
    if title.bound_role:
        _apply_bound_role_for_assign(
            db, org, target_user, title.bound_role, request,
        )

    grant_title(db, title, target_user.id, current_user.id)
    log_audit_event(
        db,
        action="title.assigned",
        target_type="org_title",
        target_id=title.id,
        actor_id=current_user.id,
        details={
            "org_id": org.id,
            "title_name": title.name,
            "bound_role": title.bound_role,
            "user_id": target_user.id,
        },
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(title)
    return _TitleOut.from_orm(db, title).model_dump()


@router.delete(
    "/{org_slug}/titles/{title_id}/assignments/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_title_assignment(
    org_slug: str,
    title_id: str,
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug,
    ).first()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    _require_title_manage(db, current_user.id, org.id)
    title = _resolve_title_or_404(db, org.id, title_id)

    if title.bound_role:
        _check_revoke_floor(db, org, user_id, title.bound_role)

    removed = revoke_title(db, title, user_id)
    if not removed:
        raise HTTPException(
            status_code=404,
            detail="User does not hold this title.",
        )
    log_audit_event(
        db,
        action="title.revoked",
        target_type="org_title",
        target_id=title.id,
        actor_id=current_user.id,
        details={
            "org_id": org.id,
            "title_name": title.name,
            "user_id": user_id,
        },
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
