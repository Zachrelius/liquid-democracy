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


class _TitleUpdateBody(BaseModel):
    name: Optional[str] = None
    bound_role: Optional[str] = None
    cardinality_mode: Optional[str] = None
    max_holders: Optional[int] = None
    fill_method: Optional[str] = None
    display_order: Optional[int] = None


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

    title = models.OrgTitle(
        org_id=org.id,
        name=body.name.strip(),
        bound_role=body.bound_role or None,
        cardinality_mode=body.cardinality_mode,
        max_holders=body.max_holders,
        fill_method=body.fill_method,
        display_order=body.display_order,
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
    log_audit_event(
        db,
        action="title.updated",
        target_type="org_title",
        target_id=title.id,
        actor_id=current_user.id,
        details={"org_id": org.id, "name": title.name},
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
