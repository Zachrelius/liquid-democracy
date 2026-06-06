"""Phase 52e Stage 2 E4 — admin adjudication for org-scoped
duplicate flags.

Endpoints (mounted under ``/api/orgs/{org_slug}/duplicate-flags``):

  * ``GET  /open`` — list open flags for this org. Org admin only.
  * ``POST /{flag_id}/resolve`` — set ``resolved_distinct`` or
    ``resolved_same``. Org admin only.

No platform-admin PII access; no cross-org leakage. The list returns
the implicated members' ``user_id`` + ``display_name`` (the admin
already knows their members), but NOT the matched name/DOB values.
The flag tier (``name_dob_address`` high-confidence vs ``name_dob``
low-confidence) is surfaced so the admin can weight the signal.

Cardinality-floor invariant note (E3): the admin adjudication
endpoints DO NOT modify role assignments or membership status of a
seated user. A "confirm_same" decision records the verdict but the
actual consequence (restricting an account) is an org-policy call;
v1 records + audits only. The Phase 52 Stage 1 cardinality-floor
protection (verification changes never auto-strip a seated role
below the governor floor) is preserved by construction — nothing
in this module mutates role rows.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

import auth as auth_utils
import models
import verification_flags
from database import get_db
from routes.organizations import require_org_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/orgs/{org_slug}/duplicate-flags", tags=["duplicate-flags"])


class _FlagMemberOut(BaseModel):
    user_id: str
    display_name: str
    username: str


class _FlagOut(BaseModel):
    id: str
    confidence: str
    status: str
    created_at: str
    resolved_at: Optional[str] = None
    member_a: _FlagMemberOut
    member_b: _FlagMemberOut


class _ResolveBody(BaseModel):
    resolution: str  # "resolved_distinct" or "resolved_same"


def _member_repr(db: Session, user_id: str) -> _FlagMemberOut:
    u = db.get(models.User, user_id)
    if u is None:
        return _FlagMemberOut(
            user_id=user_id, display_name="(deleted user)", username="",
        )
    return _FlagMemberOut(
        user_id=u.id,
        display_name=u.display_name or u.username,
        username=u.username,
    )


@router.get("/open", response_model=list[_FlagOut])
def list_open_flags(
    org_slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    admin_membership: models.OrgMembership = Depends(require_org_admin),
):
    """List all OPEN duplicate flags in this org. Org admin only.

    Returns a list sorted newest-first. Each entry shows which two
    members the flag implicates (display name + username) + the
    confidence tier — never the matched name/DOB values.
    """
    org = db.get(models.Organization, admin_membership.org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    rows = db.execute(
        select(models.OrgDuplicateFlag).where(
            models.OrgDuplicateFlag.org_id == org.id,
            models.OrgDuplicateFlag.status == "open",
        ).order_by(models.OrgDuplicateFlag.created_at.desc()),
    ).scalars().all()
    out: list[_FlagOut] = []
    for f in rows:
        out.append(_FlagOut(
            id=f.id,
            confidence=f.confidence,
            status=f.status,
            created_at=f.created_at.isoformat() if f.created_at else "",
            resolved_at=f.resolved_at.isoformat() if f.resolved_at else None,
            member_a=_member_repr(db, f.user_a_id),
            member_b=_member_repr(db, f.user_b_id),
        ))
    return out


@router.post("/{flag_id}/resolve", response_model=_FlagOut)
def resolve_flag(
    org_slug: str,
    flag_id: str,
    body: _ResolveBody,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    admin_membership: models.OrgMembership = Depends(require_org_admin),
):
    """Resolve a flag as ``resolved_distinct`` (these ARE two
    different people; suppresses re-flagging the pair) or
    ``resolved_same`` (these ARE the same person; recorded only,
    enforcement is manual for v1)."""
    flag = db.get(models.OrgDuplicateFlag, flag_id)
    if flag is None or flag.org_id != admin_membership.org_id:
        raise HTTPException(status_code=404, detail="Flag not found")
    try:
        verification_flags.resolve_flag(
            db, flag=flag, resolution=body.resolution, actor=current_user,
            ip_address=request.client.host if request.client else None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    db.commit()
    db.refresh(flag)
    return _FlagOut(
        id=flag.id,
        confidence=flag.confidence,
        status=flag.status,
        created_at=flag.created_at.isoformat() if flag.created_at else "",
        resolved_at=flag.resolved_at.isoformat() if flag.resolved_at else None,
        member_a=_member_repr(db, flag.user_a_id),
        member_b=_member_repr(db, flag.user_b_id),
    )
