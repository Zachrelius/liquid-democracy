"""Phase 86 (B-4) — member content report / flag queue.

Reports are SIGNAL ONLY: creating one never hides or actions anything at any
count. It surfaces content to the org's moderators, who act (or not) through
the real moderation tools (Phase 85 comment removal, proposal archive/delete,
member remove/ban). Threshold automation is deliberately out of scope.

Endpoints
---------
POST  /api/reports                        — member (verified email) files a report
GET   /api/orgs/{org_slug}/reports        — moderator queue (comment.moderate)
PATCH /api/reports/{report_id}            — moderator resolves (dismissed|actioned)

The queue gate is ``comment.moderate`` (Phase 85 made it real) — no new
permission key, avoiding the existing-org seed/backfill trap.
"""
# NOTE: no ``from __future__ import annotations`` — the slowapi rate-limit
# decorator on create_report wraps via functools.wraps, and FastAPI would
# resolve PEP-563 string annotations against slowapi's module globals,
# misclassifying the request body. Eager annotations avoid that.

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

import auth as auth_utils
import models
import schemas
from audit_utils import log_audit_event
from database import get_db
from eligibility import eligible_viewers_for_proposal
from notification_emit import emit_notification
from rate_limit_utils import content_limiter, REPORT_CREATE_LIMIT
from role_permissions import has_permission


log = logging.getLogger(__name__)

# Two routers: the account-level /api/reports (submit + resolve) and the
# org-scoped queue. main.py mounts both.
report_router = APIRouter(prefix="/api/reports", tags=["reports"])
org_report_router = APIRouter(prefix="/api/orgs", tags=["reports"])


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _client_ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


def _display_for(db: Session, user: Optional[models.User], org: Optional[models.Organization]) -> str:
    if user is None:
        return "Unknown"
    if org is not None:
        from verification import display_name_for
        return display_name_for(user, org)
    return user.display_name or user.username


def _resolve_target(
    db: Session, target_type: str, target_id: str,
) -> tuple[models.Proposal, Optional[str], str, bool]:
    """Resolve a report target to (proposal, author_id, excerpt, is_removed).

    ``is_removed`` is True when the target is already deleted/removed
    (soft-deleted comment or archived/withdrawn proposal) — reporting it is a
    400 (nothing left to act on).
    """
    if target_type == "comment":
        comment = db.get(models.Comment, target_id)
        if comment is None:
            raise HTTPException(status_code=404, detail="Comment not found")
        proposal = comment.proposal
        if proposal is None:
            raise HTTPException(status_code=404, detail="Comment not found")
        excerpt = (comment.body or "")[:200]
        return proposal, comment.author_id, excerpt, comment.deleted_at is not None
    # proposal
    proposal = db.get(models.Proposal, target_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    excerpt = (proposal.title or "")[:200]
    # Phase 68b — archived proposals live in the 'withdrawn' status bucket.
    is_removed = proposal.status == "withdrawn"
    return proposal, proposal.author_id, excerpt, is_removed


# ---------------------------------------------------------------------------
# POST /api/reports — submit
# ---------------------------------------------------------------------------

@report_router.post("", status_code=status.HTTP_201_CREATED)
@content_limiter.limit(REPORT_CREATE_LIMIT)
def create_report(
    body: schemas.ReportCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.require_verified_email),
):
    proposal, author_id, excerpt, is_removed = _resolve_target(
        db, body.target_type, body.target_id,
    )
    if is_removed:
        raise HTTPException(
            status_code=400, detail="This content has already been removed.",
        )
    org_id = getattr(proposal, "org_id", None)
    if not org_id:
        raise HTTPException(status_code=400, detail="This content cannot be reported.")

    # Reporter must be able to view the target (covers org + sub-org
    # membership + visibility), mirroring comment READ eligibility.
    viewers = eligible_viewers_for_proposal(db, proposal)
    if current_user.id not in viewers:
        raise HTTPException(
            status_code=403,
            detail="You must be a member of this organization to report content.",
        )

    if author_id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot report your own content.")

    # Idempotent: one OPEN report per (reporter, target). Re-report is a no-op.
    existing = (
        db.query(models.ContentReport)
        .filter(
            models.ContentReport.reporter_id == current_user.id,
            models.ContentReport.target_type == body.target_type,
            models.ContentReport.target_id == body.target_id,
            models.ContentReport.status == "open",
        )
        .first()
    )
    if existing is not None:
        return {"status": "ok", "report_id": existing.id, "already_open": True}

    report = models.ContentReport(
        org_id=org_id,
        reporter_id=current_user.id,
        target_type=body.target_type,
        target_id=body.target_id,
        reason=body.reason,
        note=body.note,
        status="open",
    )
    db.add(report)
    db.flush()

    log_audit_event(
        db,
        action="report.created",
        target_type=body.target_type,
        target_id=body.target_id,
        actor_id=current_user.id,
        details={
            "report_id": report.id,
            "org_id": org_id,
            "reason": body.reason,
            "note_present": body.note is not None,
        },
        ip_address=_client_ip(request),
    )
    db.commit()
    db.refresh(report)

    # Notify moderators (holders of comment.moderate). Invisible to the
    # reported author. Wrapped so a notification failure never sinks the
    # report (spec §B3 pattern).
    try:
        from routes.organizations import _users_with_permission_in_org
        proposal_title = getattr(proposal, "title", None)
        mod_ids = _users_with_permission_in_org(db, org_id, "comment.moderate")
        for mod_id in mod_ids:
            if mod_id == current_user.id:
                continue
            emit_notification(
                db,
                background_tasks,
                event_type="report_created",
                user_id=mod_id,
                org_id=org_id,
                actor_id=current_user.id,
                target_type=body.target_type,
                target_id=body.target_id,
                payload={
                    "org_slug": getattr(proposal.organization, "slug", None),
                    "proposal_id": proposal.id,
                    "target_type": body.target_type,
                    "reason": body.reason,
                    "proposal_title": proposal_title,
                },
            )
        db.commit()
    except Exception as e:  # noqa: BLE001 — never block the report
        log.warning("report_created notify failed: %s: %s", type(e).__name__, e)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass

    return {"status": "ok", "report_id": report.id, "already_open": False}


# ---------------------------------------------------------------------------
# GET /api/orgs/{org_slug}/reports — moderator queue
# ---------------------------------------------------------------------------

@org_report_router.get("/{org_slug}/reports/count")
def open_reports_count(
    org_slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Cheap count for the moderator nav badge. ``eligible`` is False (and
    count 0) when the caller lacks ``comment.moderate`` — the badge just
    doesn't render, no 403 noise in the console."""
    org = (
        db.query(models.Organization)
        .filter(models.Organization.slug == org_slug)
        .first()
    )
    if org is None or not has_permission(db, current_user.id, org.id, "comment.moderate"):
        return {"open_count": 0, "eligible": False}
    n = (
        db.query(models.ContentReport)
        .filter(
            models.ContentReport.org_id == org.id,
            models.ContentReport.status == "open",
        )
        .count()
    )
    return {"open_count": n, "eligible": True}


@org_report_router.get(
    "/{org_slug}/reports", response_model=list[schemas.ReportGroupOut],
)
def list_reports(
    org_slug: str,
    status: str = "open",
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    org = (
        db.query(models.Organization)
        .filter(models.Organization.slug == org_slug)
        .first()
    )
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    if not has_permission(db, current_user.id, org.id, "comment.moderate"):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to view reports in this organization.",
        )

    rows = (
        db.query(models.ContentReport)
        .filter(
            models.ContentReport.org_id == org.id,
            models.ContentReport.status == status,
        )
        .order_by(models.ContentReport.created_at.desc())
        .all()
    )

    # Group by (target_type, target_id).
    groups: dict[tuple[str, str], list[models.ContentReport]] = {}
    for r in rows:
        groups.setdefault((r.target_type, r.target_id), []).append(r)

    out: list[schemas.ReportGroupOut] = []
    for (ttype, tid), reps in groups.items():
        try:
            proposal, author_id, excerpt, _removed = _resolve_target(db, ttype, tid)
            proposal_id = proposal.id
        except HTTPException:
            # Target vanished (hard-deleted user/proposal). Still surface the
            # reports so the moderator can dismiss them.
            proposal_id, author_id, excerpt = None, None, "[content unavailable]"
        author = db.get(models.User, author_id) if author_id else None
        items = [
            schemas.ReportItemOut(
                id=r.id,
                reporter_id=r.reporter_id,
                reporter_display_name=_display_for(db, db.get(models.User, r.reporter_id), org),
                reason=r.reason,
                note=r.note,
                status=r.status,
                created_at=r.created_at,
            )
            for r in reps
        ]
        out.append(schemas.ReportGroupOut(
            target_type=ttype,
            target_id=tid,
            org_slug=org.slug,
            proposal_id=proposal_id,
            target_excerpt=excerpt,
            target_author_id=author_id,
            target_author_display=_display_for(db, author, org) if author else None,
            open_count=len(reps),
            reports=items,
        ))
    return out


# ---------------------------------------------------------------------------
# PATCH /api/reports/{report_id} — resolve
# ---------------------------------------------------------------------------

@report_router.patch("/{report_id}")
def resolve_report(
    report_id: str,
    body: schemas.ReportResolveIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Resolve a single report. 'actioned' is a bookkeeping label the
    moderator sets AFTER using the real tools — this endpoint changes nothing
    about the target itself."""
    report = db.get(models.ContentReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if not has_permission(db, current_user.id, report.org_id, "comment.moderate"):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to resolve reports in this organization.",
        )
    if report.status != "open":
        # Idempotent — already resolved.
        return {"status": report.status}

    report.status = body.status
    report.resolved_by_id = current_user.id
    report.resolved_at = _now_naive()
    log_audit_event(
        db,
        action="report.resolved",
        target_type=report.target_type,
        target_id=report.target_id,
        actor_id=current_user.id,
        details={
            "report_id": report.id,
            "org_id": report.org_id,
            "disposition": body.status,
        },
        ip_address=_client_ip(request),
    )
    db.commit()
    return {"status": report.status}
