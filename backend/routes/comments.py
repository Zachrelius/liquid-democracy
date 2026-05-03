"""Phase 10 — proposal comment CRUD.

Endpoints
---------

GET    /api/proposals/{proposal_id}/comments
POST   /api/proposals/{proposal_id}/comments
PATCH  /api/comments/{id}
DELETE /api/comments/{id}

Permission rules
----------------

  * GET — caller must satisfy ``_eligible_viewers_for_proposal`` (org-wide
    proposal -> active OrgMembership; sub-org-scoped -> SubOrgMembership +
    parent-org admin implicit power + Decision-7 default-visible-with-
    private-opt-out, mirroring the Polis viewer rules).
  * POST — caller must additionally be email-verified AND an active member
    of the proposal's parent org. For sub-org-scoped proposals we require
    the same eligibility (caller can post if they can read).
  * PATCH — caller must be the comment's ``author_id`` AND
    ``(now - created_at) < 15 minutes``. 403 with ``"Edit window has
    expired"`` otherwise.
  * DELETE — caller must be the comment's ``author_id``. No time limit.
    Soft-delete only (sets ``deleted_at``; row stays so reply children
    still render).

Body validation
---------------

  * Min 1 char (post-trim), max 5000.
  * Sanitized via ``schemas._sanitize_markdown`` — same nh3 pipeline used
    for proposal bodies. The Pydantic validator does the sanitization; the
    route re-checks the post-trim length so a payload like ``"<script>"``
    that sanitizes down to "" comes back as 422-style 400.

Reply rules (one-level threading)
---------------------------------

  * If ``parent_comment_id`` is provided, the parent must exist, must
    belong to the same proposal, AND must itself be top-level (its own
    ``parent_comment_id`` is NULL). Otherwise 400.

Audit events
------------

  * ``comment.created`` — details ``{comment_id, proposal_id,
    parent_comment_id (or null), body_length}``. Body content NOT logged.
  * ``comment.edited``  — details ``{comment_id, proposal_id, body_length}``.
    Body diff NOT logged.
  * ``comment.deleted`` — details ``{comment_id, proposal_id}``.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

import auth as auth_utils
import models
import schemas
from audit_utils import log_audit_event
from database import get_db


# Two routers wired into a single module — the proposal-scoped GET/POST and
# the comment-scoped PATCH/DELETE. main.py mounts both.
proposal_router = APIRouter(prefix="/api/proposals", tags=["comments"])
comment_router = APIRouter(prefix="/api/comments", tags=["comments"])


_ADMIN_ROLES = ("admin", "owner")
EDIT_WINDOW = timedelta(minutes=15)


# ---------------------------------------------------------------------------
# Eligibility helpers (Phase 10 — first proposal-scoped viewer set)
# ---------------------------------------------------------------------------

def _eligible_viewers_for_proposal(
    db: Session, proposal: models.Proposal,
) -> set[str]:
    """Return the set of user IDs who can VIEW a proposal (and its comments).

    Mirrors ``polis_engine.eligible_viewers_for_polis`` for the Proposal
    artifact. Phase 8.5 Decisions 3, 6, 7 apply identically:

      * Org-wide proposal (``sub_org_id`` IS NULL with non-null ``org_id``):
        all active OrgMembership members of ``proposal.org_id``.
      * Sub-org-scoped proposal (``sub_org_id`` IS NOT NULL):
        - active SubOrgMembership of ``proposal.sub_org_id``;
        - PLUS active OrgMembership admins/owners of the parent org
          (Decision 6 — implicit power);
        - PLUS, when the sub-org's ``settings.private`` is False, all active
          parent-org members (Decision 7 — default visibility).
      * No org context (``org_id`` IS NULL): defensive fallback to "all
        users" so legacy / unit-test fixtures with no org keep working —
        same shape as ``delegation_engine.eligible_voter_ids_for_proposal``.
    """
    sub_org_id = getattr(proposal, "sub_org_id", None)
    org_id = getattr(proposal, "org_id", None)

    if sub_org_id is None and org_id is None:
        # Defensive: pre-multi-tenancy / unit-test fixture path.
        rows = db.query(models.User.id).all()
        return {r.id for r in rows}

    if sub_org_id is None:
        # Org-wide proposal — all active parent-org members.
        rows = db.query(models.OrgMembership.user_id).filter(
            models.OrgMembership.org_id == org_id,
            models.OrgMembership.status == "active",
        ).all()
        return {r.user_id for r in rows}

    # Sub-org-scoped.
    visible: set[str] = set()

    sub_rows = db.query(models.SubOrgMembership.user_id).filter(
        models.SubOrgMembership.sub_org_id == sub_org_id,
        models.SubOrgMembership.status == "active",
    ).all()
    visible.update(r.user_id for r in sub_rows)

    if org_id is not None:
        parent_admins = db.query(models.OrgMembership.user_id).filter(
            models.OrgMembership.org_id == org_id,
            models.OrgMembership.status == "active",
            models.OrgMembership.role.in_(_ADMIN_ROLES),
        ).all()
        visible.update(r.user_id for r in parent_admins)

    sub_org = db.get(models.Organization, sub_org_id)
    is_private = False
    if sub_org is not None:
        settings = sub_org.settings or {}
        is_private = bool(settings.get("private", False))
    if not is_private and org_id is not None:
        parent_members = db.query(models.OrgMembership.user_id).filter(
            models.OrgMembership.org_id == org_id,
            models.OrgMembership.status == "active",
        ).all()
        visible.update(r.user_id for r in parent_members)

    return visible


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _proposal_or_404(proposal_id: str, db: Session) -> models.Proposal:
    p = db.get(models.Proposal, proposal_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return p


def _comment_or_404(comment_id: str, db: Session) -> models.Comment:
    c = db.get(models.Comment, comment_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    return c


def _now_naive() -> datetime:
    """Return a naive UTC datetime so comparisons against the column (which
    SQLAlchemy stores as naive datetimes via ``DateTime`` without tz) line
    up. Matches the ``_now()`` helper in models.py minus the tz-aware part —
    SQLAlchemy strips tz on write under SQLite anyway."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _build_comment_out(c: models.Comment) -> schemas.CommentOut:
    """Build the wire payload for a comment, blanking body when soft-deleted.

    Decision: keep ``body_deleted`` as an explicit boolean rather than
    overloading the body string. The frontend renders ``[deleted]`` from
    that flag, which avoids the corner case where a legitimate comment
    happens to read "[deleted]" verbatim.
    """
    is_deleted = c.deleted_at is not None
    return schemas.CommentOut(
        id=c.id,
        proposal_id=c.proposal_id,
        author_id=c.author_id,
        author=schemas.CommentAuthorOut(
            id=c.author.id,
            username=c.author.username,
            display_name=c.author.display_name,
            avatar_url=c.author.avatar_url,
        ),
        parent_comment_id=c.parent_comment_id,
        body="" if is_deleted else c.body,
        body_deleted=is_deleted,
        created_at=c.created_at,
        updated_at=c.updated_at,
        deleted_at=c.deleted_at,
    )


def _client_ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


# ---------------------------------------------------------------------------
# GET /api/proposals/{proposal_id}/comments
# ---------------------------------------------------------------------------

@proposal_router.get(
    "/{proposal_id}/comments",
    response_model=list[schemas.CommentOut],
)
def list_comments(
    proposal_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    proposal = _proposal_or_404(proposal_id, db)

    viewers = _eligible_viewers_for_proposal(db, proposal)
    if current_user.id not in viewers:
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to view this proposal's comments.",
        )

    rows = (
        db.query(models.Comment)
        .filter(models.Comment.proposal_id == proposal_id)
        .order_by(models.Comment.created_at.asc())
        .all()
    )
    return [_build_comment_out(c) for c in rows]


# ---------------------------------------------------------------------------
# POST /api/proposals/{proposal_id}/comments
# ---------------------------------------------------------------------------

@proposal_router.post(
    "/{proposal_id}/comments",
    response_model=schemas.CommentOut,
    status_code=status.HTTP_201_CREATED,
)
def create_comment(
    proposal_id: str,
    body: schemas.CommentCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    proposal = _proposal_or_404(proposal_id, db)

    if not current_user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email before commenting.",
        )

    # Caller must satisfy proposal visibility (covers both org and sub-org
    # scopes — the route mirrors the Polis viewer rules so commenting is
    # gated by the same set of users that can read the proposal).
    viewers = _eligible_viewers_for_proposal(db, proposal)
    if current_user.id not in viewers:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be an active member of this proposal's organization to comment.",
        )

    # Re-validate post-sanitize/trim length: nh3 may have stripped tags
    # leaving whitespace-only content, which the schema's pre-sanitize
    # min_length=1 won't catch.
    cleaned = body.body.strip()
    if not cleaned:
        raise HTTPException(
            status_code=400, detail="Comment body cannot be empty.",
        )
    if len(cleaned) > 5000:
        raise HTTPException(
            status_code=400, detail="Comment body exceeds 5000 characters.",
        )

    parent_comment_id = body.parent_comment_id
    if parent_comment_id is not None:
        parent = db.get(models.Comment, parent_comment_id)
        if parent is None:
            raise HTTPException(
                status_code=400,
                detail="Parent comment not found.",
            )
        if parent.proposal_id != proposal.id:
            raise HTTPException(
                status_code=400,
                detail="Parent comment belongs to a different proposal.",
            )
        if parent.parent_comment_id is not None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Replies cannot themselves be replied to "
                    "(only one level of threading is supported)."
                ),
            )

    comment = models.Comment(
        proposal_id=proposal.id,
        author_id=current_user.id,
        parent_comment_id=parent_comment_id,
        body=cleaned,
    )
    db.add(comment)
    db.flush()

    log_audit_event(
        db,
        action="comment.created",
        target_type="comment",
        target_id=comment.id,
        actor_id=current_user.id,
        details={
            "comment_id": comment.id,
            "proposal_id": proposal.id,
            "parent_comment_id": parent_comment_id,
            "body_length": len(cleaned),
        },
        ip_address=_client_ip(request),
    )

    db.commit()
    db.refresh(comment)
    return _build_comment_out(comment)


# ---------------------------------------------------------------------------
# PATCH /api/comments/{id}
# ---------------------------------------------------------------------------

@comment_router.patch(
    "/{comment_id}",
    response_model=schemas.CommentOut,
)
def update_comment(
    comment_id: str,
    body: schemas.CommentUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    comment = _comment_or_404(comment_id, db)

    if comment.author_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only edit your own comments.",
        )

    if comment.deleted_at is not None:
        raise HTTPException(
            status_code=400,
            detail="Cannot edit a deleted comment.",
        )

    # Compare in naive UTC — the column is stored without tz.
    age = _now_naive() - comment.created_at
    if age >= EDIT_WINDOW:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Edit window has expired",
        )

    cleaned = body.body.strip()
    if not cleaned:
        raise HTTPException(
            status_code=400, detail="Comment body cannot be empty.",
        )
    if len(cleaned) > 5000:
        raise HTTPException(
            status_code=400, detail="Comment body exceeds 5000 characters.",
        )

    comment.body = cleaned

    log_audit_event(
        db,
        action="comment.edited",
        target_type="comment",
        target_id=comment.id,
        actor_id=current_user.id,
        details={
            "comment_id": comment.id,
            "proposal_id": comment.proposal_id,
            "body_length": len(cleaned),
        },
        ip_address=_client_ip(request),
    )

    db.commit()
    db.refresh(comment)
    return _build_comment_out(comment)


# ---------------------------------------------------------------------------
# DELETE /api/comments/{id}
# ---------------------------------------------------------------------------

@comment_router.delete(
    "/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_comment(
    comment_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    comment = _comment_or_404(comment_id, db)

    if comment.author_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own comments.",
        )

    if comment.deleted_at is not None:
        # Idempotent — already soft-deleted. Return 204 without re-auditing.
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    comment.deleted_at = _now_naive()
    # Blank the body in the DB too — the row stays so reply children still
    # render correctly, but the original body content is gone. The audit
    # event intentionally omits body content (only ``comment_id`` +
    # ``proposal_id``) so we don't recreate the deleted text in the audit
    # trail. If future moderation needs the original, that's a heavier
    # workflow that should be designed deliberately.
    comment.body = ""

    log_audit_event(
        db,
        action="comment.deleted",
        target_type="comment",
        target_id=comment.id,
        actor_id=current_user.id,
        details={
            "comment_id": comment.id,
            "proposal_id": comment.proposal_id,
        },
        ip_address=_client_ip(request),
    )

    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
