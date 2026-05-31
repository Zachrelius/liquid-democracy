"""Phase 44 — Submit / approve / decline / execute / expire engine.

Functions in this module are HTTP-agnostic (no FastAPI request/response
plumbing); the route layer in ``routes/pending_actions.py`` is a thin
wrapper. Sessions are passed in by the caller; commits are the caller's
responsibility EXCEPT where noted (the expiry worker tick commits itself
since it runs out-of-request).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

import models
from audit_utils import log_audit_event

from . import registry, settings as p44_settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _emit_safe(
    event_type: str,
    db: Session,
    *,
    user_id: str,
    org_id: Optional[str] = None,
    actor_id: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    payload: Optional[dict] = None,
) -> None:
    """Wrap ``emit_notification`` in try/except — a notification failure
    must never sink the originating request (CLAUDE.md notification
    convention)."""
    try:
        from notification_emit import emit_notification
        emit_notification(
            db,
            None,  # background_tasks unused for in-app notifications
            event_type,
            user_id,
            org_id=org_id,
            actor_id=actor_id,
            target_type=target_type,
            target_id=target_id,
            payload=payload,
        )
    except Exception:
        # Swallow — see docstring.
        pass


def _eligible_approvers(
    db: Session, org: models.Organization, action_type: str,
) -> set[str]:
    defn = registry.get_action_definition(action_type)
    return defn.approver_set_resolver(db, org)


def _is_eligible_approver(
    db: Session, org: models.Organization, action_type: str, user_id: str,
) -> bool:
    return user_id in _eligible_approvers(db, org, action_type)


def can_view_pending_actions(
    db: Session, org: models.Organization, user_id: str,
) -> bool:
    """A user can see the pending queue iff they're an eligible approver
    for at least ONE wrapped action type in this org. We union the
    approver sets across all registered types — typically equivalent to
    "is admin/steward" in a stock org, but configurable matrices may
    yield narrower sets per action.
    """
    for action_type in registry.known_action_types():
        try:
            if _is_eligible_approver(db, org, action_type, user_id):
                return True
        except HTTPException:
            continue
    return False


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------

class SubmitResult:
    """Returned by ``submit_pending_action``.

    - ``executed_directly`` is True iff the deadlock-guard (D6) kicked
      in: the initiator was the only eligible approver, so we executed
      immediately. ``pending_action`` is None in that case (the row was
      never persisted as pending).
    - Otherwise, ``pending_action`` carries the newly-created row in
      ``status="pending"`` and ``executed_directly`` is False.
    """
    def __init__(
        self,
        *,
        pending_action: Optional[models.PendingAdminAction],
        executed_directly: bool,
    ):
        self.pending_action = pending_action
        self.executed_directly = executed_directly


def submit_pending_action(
    db: Session,
    org: models.Organization,
    initiator: models.User,
    action_type: str,
    payload: dict,
    *,
    ip_address: Optional[str] = None,
) -> SubmitResult:
    """Submit a destructive action for N-of-M ratification.

    Flow:
      1. Look up the action definition (400 on unknown).
      2. Validate initiator's authority — they MUST hold the permission
         (or be steward for org.delete) that the action requires.
      3. Validate payload shape + target existence.
      4. Compute the eligible-approver set + threshold.
      5. D6 deadlock guard: if the eligible-approver set size < threshold,
         OR the initiator is the only eligible approver, execute directly
         (the ratification is vacuous). Write audit entry noting the
         bypass; do not create a pending row.
      6. Otherwise, create the PendingAdminAction row + the initiator's
         own implicit approval (D4); emit notifications to other approvers;
         audit the submit.

    Caller must ``db.commit()`` after a successful return.
    """
    defn = registry.get_action_definition(action_type)

    # (2) Authority.
    if defn.steward_only:
        from role_permissions import _user_role_system_key
        if _user_role_system_key(db, initiator.id, org.id) != "steward":
            raise HTTPException(
                status_code=403,
                detail="Only the Steward can initiate this action",
            )
    else:
        from role_permissions import has_permission
        if not has_permission(
            db, initiator.id, org.id, defn.required_permission_key,
        ):
            raise HTTPException(
                status_code=403,
                detail=(
                    "You do not have permission to initiate this action."
                ),
            )

    # (3) Payload validation.
    defn.payload_validator(payload, db, org, initiator)

    # (4) Approver set + threshold.
    approver_set = defn.approver_set_resolver(db, org)
    threshold = p44_settings.threshold_for(org, action_type)
    window_hours = p44_settings.window_hours(org)

    # (5) D6 deadlock guard.
    if (
        len(approver_set) < threshold
        or approver_set == {initiator.id}
        or len(approver_set) == 0
    ):
        # Execute directly. Write a special audit entry per D6.
        _execute_directly_with_audit(
            db, org, initiator, action_type, payload, ip_address=ip_address,
        )
        return SubmitResult(pending_action=None, executed_directly=True)

    # (6) Create the pending row + initiator's implicit approval.
    expires_at = _now() + timedelta(hours=window_hours)
    pending = models.PendingAdminAction(
        org_id=org.id,
        action_type=action_type,
        payload=payload,
        initiator_id=initiator.id,
        status="pending",
        threshold=threshold,
        expires_at=expires_at,
        resolved_at=None,
        resolution_detail=None,
    )
    db.add(pending)
    db.flush()  # need pending.id for the approval row

    db.add(models.PendingActionApproval(
        pending_action_id=pending.id,
        approver_id=initiator.id,
        decision="approve",
        reason=None,
    ))
    db.flush()

    # Audit + notify.
    log_audit_event(
        db,
        action="pending_admin_action.submitted",
        target_type="pending_admin_action",
        target_id=pending.id,
        actor_id=initiator.id,
        details={
            "action_type": action_type,
            "threshold": threshold,
            "approver_count": len(approver_set),
            "expires_at": expires_at.isoformat(),
            "org_id": org.id,
        },
        ip_address=ip_address,
    )
    for approver_id in approver_set:
        if approver_id == initiator.id:
            continue
        _emit_safe(
            "pending_action.submitted",
            db,
            user_id=approver_id,
            org_id=org.id,
            actor_id=initiator.id,
            target_type="pending_admin_action",
            target_id=pending.id,
            payload={"action_type": action_type},
        )

    # If the initiator's own implicit approval already meets the threshold
    # (e.g. threshold=1, which is allowed but discouraged), execute now.
    if threshold <= 1:
        _execute_now(db, pending, initiator, ip_address=ip_address)

    return SubmitResult(pending_action=pending, executed_directly=False)


def _execute_directly_with_audit(
    db: Session,
    org: models.Organization,
    initiator: models.User,
    action_type: str,
    payload: dict,
    *,
    ip_address: Optional[str] = None,
) -> None:
    """Apply the action immediately without going through the queue
    (D6 deadlock guard fallback). Re-validates first (same flow as the
    ratified path)."""
    defn = registry.get_action_definition(action_type)
    defn.payload_validator(payload, db, org, initiator)

    # Build a synthetic pending row to satisfy the executor's signature
    # (it expects PendingAdminAction-like). We don't persist it.
    stub = models.PendingAdminAction(
        org_id=org.id,
        action_type=action_type,
        payload=payload,
        initiator_id=initiator.id,
        status="pending",
        threshold=1,
        expires_at=_now() + timedelta(hours=1),
    )
    defn.executor(db, stub, initiator)
    log_audit_event(
        db,
        action="pending_admin_action.executed_without_ratification",
        target_type="organization",
        target_id=org.id,
        actor_id=initiator.id,
        details={
            "action_type": action_type,
            "reason": "insufficient_approvers",
        },
        ip_address=ip_address,
    )


# ---------------------------------------------------------------------------
# Approve / decline
# ---------------------------------------------------------------------------

def approve_pending_action(
    db: Session,
    pending: models.PendingAdminAction,
    approver: models.User,
    *,
    ip_address: Optional[str] = None,
) -> models.PendingAdminAction:
    """Record approver's approval; execute if threshold now met."""
    _assert_pending(pending)
    org = db.get(models.Organization, pending.org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    if not _is_eligible_approver(db, org, pending.action_type, approver.id):
        raise HTTPException(
            status_code=403,
            detail="You are not eligible to approve this action",
        )
    if _already_decided(db, pending.id, approver.id):
        raise HTTPException(
            status_code=400, detail="You have already weighed in on this action",
        )

    db.add(models.PendingActionApproval(
        pending_action_id=pending.id,
        approver_id=approver.id,
        decision="approve",
        reason=None,
    ))
    db.flush()

    log_audit_event(
        db,
        action="pending_admin_action.approved",
        target_type="pending_admin_action",
        target_id=pending.id,
        actor_id=approver.id,
        details={"action_type": pending.action_type, "org_id": pending.org_id},
        ip_address=ip_address,
    )

    if _approval_count(db, pending.id) >= pending.threshold:
        _execute_now(db, pending, approver, ip_address=ip_address)
    return pending


def decline_pending_action(
    db: Session,
    pending: models.PendingAdminAction,
    approver: models.User,
    reason: Optional[str],
    *,
    ip_address: Optional[str] = None,
) -> models.PendingAdminAction:
    """Single decline vetoes the whole action (D9)."""
    _assert_pending(pending)
    org = db.get(models.Organization, pending.org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    if not _is_eligible_approver(db, org, pending.action_type, approver.id):
        raise HTTPException(
            status_code=403, detail="You are not eligible to decline this action",
        )
    if _already_decided(db, pending.id, approver.id):
        raise HTTPException(
            status_code=400, detail="You have already weighed in on this action",
        )
    db.add(models.PendingActionApproval(
        pending_action_id=pending.id,
        approver_id=approver.id,
        decision="decline",
        reason=reason,
    ))
    pending.status = "declined"
    pending.resolved_at = _now()
    pending.resolution_detail = {
        "decliner_id": approver.id,
        "reason": reason,
    }
    log_audit_event(
        db,
        action="pending_admin_action.declined",
        target_type="pending_admin_action",
        target_id=pending.id,
        actor_id=approver.id,
        details={
            "action_type": pending.action_type,
            "org_id": pending.org_id,
            "reason": reason,
        },
        ip_address=ip_address,
    )
    _emit_safe(
        "pending_action.declined",
        db,
        user_id=pending.initiator_id,
        org_id=pending.org_id,
        actor_id=approver.id,
        target_type="pending_admin_action",
        target_id=pending.id,
        payload={"action_type": pending.action_type, "reason": reason},
    )
    db.flush()
    return pending


# ---------------------------------------------------------------------------
# Execute (called when threshold met)
# ---------------------------------------------------------------------------

def _execute_now(
    db: Session,
    pending: models.PendingAdminAction,
    actor: models.User,
    *,
    ip_address: Optional[str] = None,
) -> None:
    """Re-validate + execute. On revalidation failure resolve ``failed``."""
    defn = registry.get_action_definition(pending.action_type)
    org = db.get(models.Organization, pending.org_id)
    if org is None:
        _resolve_failed(db, pending, "organization_not_found", actor.id, ip_address)
        return

    # D7 — re-check initiator still holds the required authority.
    initiator = db.get(models.User, pending.initiator_id)
    if initiator is None:
        _resolve_failed(db, pending, "initiator_gone", actor.id, ip_address)
        return
    if defn.steward_only:
        from role_permissions import _user_role_system_key
        if _user_role_system_key(db, initiator.id, org.id) != "steward":
            _resolve_failed(db, pending, "initiator_no_longer_authorized", actor.id, ip_address)
            return
    else:
        from role_permissions import has_permission
        if not has_permission(
            db, initiator.id, org.id, defn.required_permission_key,
        ):
            _resolve_failed(db, pending, "initiator_no_longer_authorized", actor.id, ip_address)
            return

    # D7 — re-validate payload + target.
    try:
        defn.payload_validator(pending.payload, db, org, initiator)
        defn.executor(db, pending, actor)
    except HTTPException as exc:
        _resolve_failed(db, pending, f"revalidation_failed: {exc.detail}", actor.id, ip_address)
        return

    pending.status = "executed"
    pending.resolved_at = _now()
    pending.resolution_detail = {"executed_by_approval_of": actor.id}
    log_audit_event(
        db,
        action="pending_admin_action.executed",
        target_type="pending_admin_action",
        target_id=pending.id,
        actor_id=actor.id,
        details={
            "action_type": pending.action_type,
            "org_id": pending.org_id,
            "approval_count": _approval_count(db, pending.id),
            "threshold": pending.threshold,
        },
        ip_address=ip_address,
    )
    _emit_safe(
        "pending_action.executed",
        db,
        user_id=pending.initiator_id,
        org_id=pending.org_id,
        actor_id=actor.id,
        target_type="pending_admin_action",
        target_id=pending.id,
        payload={"action_type": pending.action_type},
    )
    db.flush()


def _resolve_failed(
    db: Session,
    pending: models.PendingAdminAction,
    reason: str,
    actor_id: Optional[str],
    ip_address: Optional[str],
) -> None:
    pending.status = "failed"
    pending.resolved_at = _now()
    pending.resolution_detail = {"reason": reason}
    log_audit_event(
        db,
        action="pending_admin_action.failed",
        target_type="pending_admin_action",
        target_id=pending.id,
        actor_id=actor_id,
        details={
            "action_type": pending.action_type,
            "org_id": pending.org_id,
            "reason": reason,
        },
        ip_address=ip_address,
    )
    _emit_safe(
        "pending_action.failed",
        db,
        user_id=pending.initiator_id,
        org_id=pending.org_id,
        actor_id=actor_id,
        target_type="pending_admin_action",
        target_id=pending.id,
        payload={"action_type": pending.action_type, "reason": reason},
    )
    db.flush()


# ---------------------------------------------------------------------------
# Expiry (called from digest_scheduler.run_one_tick)
# ---------------------------------------------------------------------------

def expire_due_pending_actions(db: Session, *, now: Optional[datetime] = None) -> int:
    """Resolve any pending actions whose ``expires_at`` has passed.

    Cheap short-circuit when no rows are due (zero-row branch returns
    without touching the heavy code path). Commits its own work because
    it runs out-of-request from the scheduler.
    """
    now = now or _now()
    due = (
        db.query(models.PendingAdminAction)
        .filter(
            models.PendingAdminAction.status == "pending",
            models.PendingAdminAction.expires_at <= now,
        )
        .all()
    )
    if not due:
        return 0
    for pending in due:
        pending.status = "expired"
        pending.resolved_at = now
        pending.resolution_detail = {"reason": "window_elapsed"}
        log_audit_event(
            db,
            action="pending_admin_action.expired",
            target_type="pending_admin_action",
            target_id=pending.id,
            actor_id=None,
            details={
                "action_type": pending.action_type,
                "org_id": pending.org_id,
            },
        )
        _emit_safe(
            "pending_action.expired",
            db,
            user_id=pending.initiator_id,
            org_id=pending.org_id,
            actor_id=None,
            target_type="pending_admin_action",
            target_id=pending.id,
            payload={"action_type": pending.action_type},
        )
    db.commit()
    return len(due)


# ---------------------------------------------------------------------------
# Internal: query helpers
# ---------------------------------------------------------------------------

def _assert_pending(pending: models.PendingAdminAction) -> None:
    if pending.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Action is already {pending.status}; cannot modify",
        )


def _already_decided(db: Session, pending_id: str, user_id: str) -> bool:
    return db.query(models.PendingActionApproval).filter(
        models.PendingActionApproval.pending_action_id == pending_id,
        models.PendingActionApproval.approver_id == user_id,
    ).count() > 0


def _approval_count(db: Session, pending_id: str) -> int:
    return db.query(models.PendingActionApproval).filter(
        models.PendingActionApproval.pending_action_id == pending_id,
        models.PendingActionApproval.decision == "approve",
    ).count()


# ---------------------------------------------------------------------------
# Read helpers (used by GET endpoints)
# ---------------------------------------------------------------------------

def serialize_pending(
    db: Session, pending: models.PendingAdminAction, *, viewer_id: str,
) -> dict[str, Any]:
    """Build the JSON shape returned by the list + detail endpoints."""
    defn = registry.get_action_definition(pending.action_type)
    preview = defn.preview_builder(pending, db)
    initiator = db.get(models.User, pending.initiator_id)
    decisions = (
        db.query(models.PendingActionApproval)
        .filter(models.PendingActionApproval.pending_action_id == pending.id)
        .all()
    )
    approvals_count = sum(1 for d in decisions if d.decision == "approve")
    viewer_has_decided = any(d.approver_id == viewer_id for d in decisions)
    return {
        "id": pending.id,
        "org_id": pending.org_id,
        "action_type": pending.action_type,
        "summary_label": defn.summary_label,
        "preview": preview,
        "initiator": {
            "id": pending.initiator_id,
            "display_name": initiator.display_name if initiator else "(unknown)",
            "username": initiator.username if initiator else None,
        },
        "status": pending.status,
        "threshold": pending.threshold,
        "approvals_count": approvals_count,
        "approver_decisions": [
            {
                "approver_id": d.approver_id,
                "decision": d.decision,
                "reason": d.reason,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in decisions
        ],
        "viewer_has_decided": viewer_has_decided,
        "created_at": pending.created_at.isoformat() if pending.created_at else None,
        "expires_at": pending.expires_at.isoformat() if pending.expires_at else None,
        "resolved_at": pending.resolved_at.isoformat() if pending.resolved_at else None,
        "resolution_detail": pending.resolution_detail,
    }
