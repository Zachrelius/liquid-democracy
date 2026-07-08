"""Phase 44 — Pending-actions API.

Endpoints under ``/api/orgs/{org_slug}/admin/pending-actions``:

  POST              submit a new pending action
  GET               list pending actions for this org (approver-gated)
  GET /{id}         single full preview
  POST /{id}/approve
  POST /{id}/decline (body: {reason})
  GET /count        small endpoint for nav-badge polling

The submit path is shared with the existing destructive endpoints'
interception logic — those endpoints route here when approval is ON
(see ``routes/organizations.py::remove_member`` etc).
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

import auth as auth_utils
import models
from database import get_db
from org_middleware import require_org_membership

from pending_actions import engine, registry, settings as p44_settings


router = APIRouter(prefix="/api/orgs", tags=["pending-actions"])


# ---------------------------------------------------------------------------
# Pydantic bodies
# ---------------------------------------------------------------------------

class PendingActionSubmit(BaseModel):
    action_type: str
    payload: dict[str, Any]


class PendingActionDecline(BaseModel):
    reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_org(db: Session, org_slug: str) -> models.Organization:
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug,
    ).first()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


def _resolve_pending(
    db: Session, pending_id: str, org_id: str,
) -> models.PendingAdminAction:
    p = db.get(models.PendingAdminAction, pending_id)
    if p is None or p.org_id != org_id:
        raise HTTPException(status_code=404, detail="Pending action not found")
    return p


def _require_viewer_is_eligible(
    db: Session, org: models.Organization, user: models.User,
) -> None:
    if not engine.can_view_pending_actions(db, org, user.id):
        raise HTTPException(
            status_code=403,
            detail="You are not eligible to view pending actions for this organization",
        )


def _queue_enabled(org: models.Organization) -> bool:
    """Phase 90d — the pending-action queue is active for an org when EITHER
    Phase 44 multi-admin approval is enabled OR the weighted issuance mode is
    'multi_admin' (share issuance ratification reuses the same engine but is
    gated by a different org signal)."""
    if p44_settings.is_enabled(org):
        return True
    from org_config import get_weighted_voting_config
    return get_weighted_voting_config(org)["issuance_mode"] == "multi_admin"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/{org_slug}/admin/pending-actions")
def submit_pending_action(
    org_slug: str,
    body: PendingActionSubmit,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """Submit a destructive admin action for N-of-M ratification.

    Auth is delegated to the action's required permission check inside
    ``engine.submit_pending_action`` — bare membership is not enough.

    Response is one of:
      - ``{status: "pending", pending_action: {...serialized...}}``
      - ``{status: "executed_directly", reason: "insufficient_approvers"}``
        when the D6 deadlock guard kicked in.
      - ``{status: "executed_directly", reason: "threshold_already_met"}``
        when threshold ≤ 1 (degenerate but allowed).
    """
    org = _resolve_org(db, org_slug)
    # Phase 90d — the queue is active under Phase 44 approval OR the weighted
    # multi_admin issuance mode. Share issuance actions submitted directly here
    # (cap_raise / issuance_mode_weaken) rely on the latter.
    if not _queue_enabled(org):
        raise HTTPException(
            status_code=400,
            detail="Multi-admin approval is not enabled for this organization",
        )
    ip = request.client.host if request.client else None
    result = engine.submit_pending_action(
        db, org, current_user, body.action_type, body.payload, ip_address=ip,
    )
    db.commit()
    if result.executed_directly:
        return {"status": "executed_directly", "reason": "insufficient_approvers"}
    pending = result.pending_action
    db.refresh(pending)
    return {
        "status": "pending" if pending.status == "pending" else pending.status,
        "pending_action": engine.serialize_pending(
            db, pending, viewer_id=current_user.id,
        ),
    }


@router.get("/{org_slug}/admin/pending-actions")
def list_pending_actions(
    org_slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
) -> dict[str, Any]:
    """List pending actions for this org. Approver-gated."""
    org = _resolve_org(db, org_slug)
    _require_viewer_is_eligible(db, org, current_user)
    rows = (
        db.query(models.PendingAdminAction)
        .filter(models.PendingAdminAction.org_id == org.id)
        .order_by(
            models.PendingAdminAction.status.asc(),
            models.PendingAdminAction.created_at.desc(),
        )
        .all()
    )
    items = [
        engine.serialize_pending(db, p, viewer_id=current_user.id)
        for p in rows
    ]
    pending_only = [i for i in items if i["status"] == "pending"]
    by_action_type: dict[str, int] = {}
    for i in pending_only:
        by_action_type[i["action_type"]] = by_action_type.get(i["action_type"], 0) + 1
    return {
        "items": items,
        "pending_count": len(pending_only),
        "pending_count_by_action_type": by_action_type,
    }


@router.get("/{org_slug}/admin/pending-actions/count")
def get_pending_count(
    org_slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
) -> dict[str, Any]:
    """Cheap count endpoint for the Admin-nav badge (F2b)."""
    org = _resolve_org(db, org_slug)
    if not _queue_enabled(org):
        return {"pending_count": 0, "pending_count_by_action_type": {}, "eligible": False}
    if not engine.can_view_pending_actions(db, org, current_user.id):
        return {"pending_count": 0, "pending_count_by_action_type": {}, "eligible": False}
    rows = (
        db.query(models.PendingAdminAction)
        .filter(
            models.PendingAdminAction.org_id == org.id,
            models.PendingAdminAction.status == "pending",
        )
        .all()
    )
    by_action_type: dict[str, int] = {}
    for r in rows:
        by_action_type[r.action_type] = by_action_type.get(r.action_type, 0) + 1
    return {
        "pending_count": len(rows),
        "pending_count_by_action_type": by_action_type,
        "eligible": True,
    }


@router.get("/{org_slug}/admin/pending-actions/{pending_id}")
def get_pending_action(
    org_slug: str,
    pending_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
) -> dict[str, Any]:
    org = _resolve_org(db, org_slug)
    _require_viewer_is_eligible(db, org, current_user)
    p = _resolve_pending(db, pending_id, org.id)
    return engine.serialize_pending(db, p, viewer_id=current_user.id)


@router.post("/{org_slug}/admin/pending-actions/{pending_id}/approve")
def approve_pending_action_endpoint(
    org_slug: str,
    pending_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
) -> dict[str, Any]:
    org = _resolve_org(db, org_slug)
    p = _resolve_pending(db, pending_id, org.id)
    ip = request.client.host if request.client else None
    engine.approve_pending_action(db, p, current_user, ip_address=ip)
    db.commit()
    db.refresh(p)
    return engine.serialize_pending(db, p, viewer_id=current_user.id)


@router.post("/{org_slug}/admin/pending-actions/{pending_id}/decline")
def decline_pending_action_endpoint(
    org_slug: str,
    pending_id: str,
    body: PendingActionDecline,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
) -> dict[str, Any]:
    org = _resolve_org(db, org_slug)
    p = _resolve_pending(db, pending_id, org.id)
    ip = request.client.host if request.client else None
    engine.decline_pending_action(db, p, current_user, body.reason, ip_address=ip)
    db.commit()
    db.refresh(p)
    return engine.serialize_pending(db, p, viewer_id=current_user.id)
