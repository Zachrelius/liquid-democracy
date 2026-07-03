"""
Phase 18 (D2 / D3 / B3) — Follow routes are now mounted under
``/api/orgs/{org_slug}/follows/*``. Follow rows carry ``org_id`` so the
``delegation_allowed`` permission level cannot leak cross-org via an
account-level approval. ``_revoke_dependent_delegations`` is scoped to
the follow's ``org_id``: revoking a follow in org X revokes only the
delegations in org X gated on that follow row; delegations in org Y
(gated on a different follow row in Y) stay intact.

The frontend's API client must update accordingly (Frontend Agent F3).
This is a clean break — there are no compat aliases at the old
``/api/follows/*`` prefix.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.orm import Session

import auth as auth_utils
from rate_limit_utils import content_limiter, FOLLOW_REQUEST_LIMIT
import models
import schemas
from audit_utils import log_audit_event
from database import get_db
from delegation_engine import graph_store
from notification_emit import emit_notification
from org_middleware import require_org_membership


log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/orgs", tags=["follows"])


def _now() -> datetime:
    """Naive UTC datetime — SQLite strips timezone info on storage, so
    comparisons between stored and fresh values must both be naive."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _revoke_dependent_delegations(
    db: Session,
    follower_id: str,
    followed_id: str,
    actor_id: str,
    org_id: str,
) -> list[str]:
    """
    Phase 18 (B3): scoped revocation. Revoke delegations from
    ``follower_id`` → ``followed_id`` IN ``org_id`` that are no longer
    backed by an active ``delegate_profile`` covering the topic. Delegations
    in other orgs (gated on a different per-org follow row) are not touched.

    Returns list of revoked delegation IDs.
    """
    revoked = []
    delegations = db.query(models.Delegation).filter(
        models.Delegation.delegator_id == follower_id,
        models.Delegation.delegate_id == followed_id,
        models.Delegation.org_id == org_id,
    ).all()

    for d in delegations:
        # Check if there's a delegate_profile that still allows this.
        # Profile lookup intentionally NOT org-scoped — delegate profiles
        # are an account-level surface (see Phase 19 public-delegate-pages
        # spec). The org-scoping is applied above by the Delegation query.
        if d.topic_id:
            profile = db.query(models.DelegateProfile).filter(
                models.DelegateProfile.user_id == followed_id,
                models.DelegateProfile.topic_id == d.topic_id,
            ).first()
        else:
            profile = db.query(models.DelegateProfile).filter(
                models.DelegateProfile.user_id == followed_id,
            ).first()

        if not profile:
            # No profile covers this delegation — revoke it
            log_audit_event(
                db, action="delegation.revoked",
                target_type="delegation", target_id=d.id,
                actor_id=actor_id,
                details={
                    "delegator_id": follower_id,
                    "delegate_id": followed_id,
                    "topic_id": d.topic_id,
                    "org_id": org_id,
                    "reason": "follow_relationship_revoked",
                },
            )
            graph_store.remove_delegation(follower_id, d.topic_id, org_id=org_id)
            revoked.append(d.id)
            db.delete(d)

    return revoked


# ---------------------------------------------------------------------------
# Send follow request
# ---------------------------------------------------------------------------

@router.post(
    "/{org_slug}/follows/request",
    response_model=schemas.FollowRequestOut,
    status_code=201,
)
@content_limiter.limit(FOLLOW_REQUEST_LIMIT)
def send_follow_request(
    org_slug: str,
    body: schemas.FollowRequestCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    # Phase 86 (B-9) — follow requests require a verified email.
    current_user: models.User = Depends(auth_utils.require_verified_email),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    org_id = membership.org_id

    if body.target_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot follow yourself")

    target = db.get(models.User, body.target_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    # Phase 18 (D2): per-org follow uniqueness. A follow in org X is
    # distinct from one in org Y; both can coexist for the same pair.
    existing_rel = db.query(models.FollowRelationship).filter(
        models.FollowRelationship.follower_id == current_user.id,
        models.FollowRelationship.followed_id == body.target_id,
        models.FollowRelationship.org_id == org_id,
    ).first()
    if existing_rel:
        raise HTTPException(status_code=409, detail="Already following this user")

    # Per-org pending request lookup.
    existing_req = db.query(models.FollowRequest).filter(
        models.FollowRequest.requester_id == current_user.id,
        models.FollowRequest.target_id == body.target_id,
        models.FollowRequest.org_id == org_id,
    ).first()
    if existing_req:
        if existing_req.status == "pending":
            raise HTTPException(status_code=409, detail="Follow request already pending")
        # Previously denied — allow re-request by updating
        existing_req.status = "pending"
        existing_req.message = body.message
        existing_req.requested_at = _now()
        existing_req.responded_at = None
        existing_req.permission_level = None
        db.flush()
        freq = existing_req
    else:
        freq = models.FollowRequest(
            requester_id=current_user.id,
            target_id=body.target_id,
            org_id=org_id,
            message=body.message,
        )
        db.add(freq)
        db.flush()

    log_audit_event(
        db, action="follow.requested",
        target_type="follow_request", target_id=freq.id,
        actor_id=current_user.id,
        details={"target_id": body.target_id, "org_id": org_id, "message": body.message},
        ip_address=request.client.host if request.client else None,
    )

    # Apply target's default_follow_policy
    policy = target.default_follow_policy
    if policy in ("auto_approve_view", "auto_approve_delegate"):
        perm = "delegation_allowed" if policy == "auto_approve_delegate" else "view_only"
        freq.status = "approved"
        freq.permission_level = perm
        freq.responded_at = _now()
        db.flush()

        rel = models.FollowRelationship(
            follower_id=current_user.id,
            followed_id=body.target_id,
            org_id=org_id,
            permission_level=perm,
        )
        db.add(rel)
        db.flush()

        log_audit_event(
            db, action="follow.approved",
            target_type="follow_request", target_id=freq.id,
            actor_id=body.target_id,
            details={
                "requester_id": current_user.id,
                "permission_level": perm,
                "org_id": org_id,
                "auto": True,
            },
        )

        if perm == "delegation_allowed":
            from routes.delegations import activate_intents_for_follow
            activate_intents_for_follow(
                db, current_user.id, body.target_id, org_id=org_id,
            )

    db.commit()
    db.refresh(freq)

    # Phase 13 B-emit — follow.requested -> target user. Auto-approve cases
    # ALSO emit follow.approved -> requester. Note: notifications still pass
    # ``org_id=None`` because follow notifications were authored as an
    # account-level event surface; preserving that shape avoids retro-active
    # changes to digest/inbox grouping rules. Phase 18 doesn't refactor the
    # notification surface — that would be a separate pass.
    actor_display = current_user.display_name or current_user.username
    try:
        emit_notification(
            db,
            background_tasks,
            event_type="follow.requested",
            user_id=body.target_id,
            org_id=None,  # account-level event
            actor_id=current_user.id,
            target_type="follow_request",
            target_id=freq.id,
            payload={
                "requester_id": current_user.id,
                "actor_display_name": actor_display,
                "message": body.message,
            },
        )
        if freq.status == "approved":
            target_display = target.display_name or target.username
            emit_notification(
                db,
                background_tasks,
                event_type="follow.approved",
                user_id=current_user.id,
                org_id=None,
                actor_id=body.target_id,
                target_type="follow_request",
                target_id=freq.id,
                payload={
                    "target_id": body.target_id,
                    "actor_display_name": target_display,
                    "permission_level": freq.permission_level,
                    "auto_approved": True,
                },
            )
        db.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("follow.requested emit failed: %s: %s", type(e).__name__, e)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass

    return freq


# ---------------------------------------------------------------------------
# Incoming / outgoing requests
# ---------------------------------------------------------------------------

@router.get(
    "/{org_slug}/follows/requests/incoming",
    response_model=list[schemas.FollowRequestOut],
)
def incoming_requests(
    org_slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    org_id = membership.org_id
    return db.query(models.FollowRequest).filter(
        models.FollowRequest.target_id == current_user.id,
        models.FollowRequest.org_id == org_id,
        models.FollowRequest.status == "pending",
    ).order_by(models.FollowRequest.requested_at.desc()).all()


@router.get(
    "/{org_slug}/follows/requests/outgoing",
    response_model=list[schemas.FollowRequestOut],
)
def outgoing_requests(
    org_slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    org_id = membership.org_id
    return db.query(models.FollowRequest).filter(
        models.FollowRequest.requester_id == current_user.id,
        models.FollowRequest.org_id == org_id,
    ).order_by(models.FollowRequest.requested_at.desc()).all()


# ---------------------------------------------------------------------------
# Respond to a follow request
# ---------------------------------------------------------------------------

@router.put(
    "/{org_slug}/follows/requests/{request_id}/respond",
    response_model=schemas.FollowRequestOut,
)
def respond_to_request(
    org_slug: str,
    request_id: str,
    body: schemas.FollowRequestRespond,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    org_id = membership.org_id

    freq = db.get(models.FollowRequest, request_id)
    if not freq:
        raise HTTPException(status_code=404, detail="Follow request not found")
    # Phase 18: cross-org access to a follow request looks like a 404 from
    # this org's vantage point.
    if freq.org_id is not None and freq.org_id != org_id:
        raise HTTPException(status_code=404, detail="Follow request not found")
    if freq.target_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your request to respond to")
    if freq.status != "pending":
        raise HTTPException(status_code=409, detail=f"Request already {freq.status}")

    freq.status = body.status
    freq.responded_at = _now()

    if body.status == "approved":
        perm = body.permission_level or "view_only"
        freq.permission_level = perm
        db.flush()

        # Check if relationship already exists in this org (shouldn't, but be safe)
        existing = db.query(models.FollowRelationship).filter(
            models.FollowRelationship.follower_id == freq.requester_id,
            models.FollowRelationship.followed_id == current_user.id,
            models.FollowRelationship.org_id == org_id,
        ).first()
        if not existing:
            rel = models.FollowRelationship(
                follower_id=freq.requester_id,
                followed_id=current_user.id,
                org_id=org_id,
                permission_level=perm,
            )
            db.add(rel)
            db.flush()

        log_audit_event(
            db, action="follow.approved",
            target_type="follow_request", target_id=freq.id,
            actor_id=current_user.id,
            details={
                "requester_id": freq.requester_id,
                "permission_level": perm,
                "org_id": org_id,
            },
        )

        # Auto-activate delegation intents if approved with delegation_allowed.
        # Phase 18 (D5): pass org_id so only intents in this org are activated.
        if perm == "delegation_allowed":
            from routes.delegations import activate_intents_for_follow
            activate_intents_for_follow(
                db, freq.requester_id, current_user.id, org_id=org_id,
            )
    else:
        db.flush()
        log_audit_event(
            db, action="follow.denied",
            target_type="follow_request", target_id=freq.id,
            actor_id=current_user.id,
            details={"requester_id": freq.requester_id, "org_id": org_id},
        )

    db.commit()
    db.refresh(freq)

    # Phase 13 B-emit — follow.approved -> requester (only on approval).
    if freq.status == "approved":
        try:
            actor_display = current_user.display_name or current_user.username
            emit_notification(
                db,
                background_tasks,
                event_type="follow.approved",
                user_id=freq.requester_id,
                org_id=None,
                actor_id=current_user.id,
                target_type="follow_request",
                target_id=freq.id,
                payload={
                    "target_id": current_user.id,
                    "actor_display_name": actor_display,
                    "permission_level": freq.permission_level,
                },
            )
            db.commit()
        except Exception as e:  # noqa: BLE001
            log.warning("follow.approved emit failed: %s: %s", type(e).__name__, e)
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass

    return freq


# ---------------------------------------------------------------------------
# Following / followers lists
# ---------------------------------------------------------------------------

@router.get(
    "/{org_slug}/follows/following",
    response_model=list[schemas.FollowRelationshipOut],
)
def list_following(
    org_slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    org_id = membership.org_id
    return db.query(models.FollowRelationship).filter(
        models.FollowRelationship.follower_id == current_user.id,
        models.FollowRelationship.org_id == org_id,
    ).all()


@router.get(
    "/{org_slug}/follows/followers",
    response_model=list[schemas.FollowRelationshipOut],
)
def list_followers(
    org_slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    org_id = membership.org_id
    return db.query(models.FollowRelationship).filter(
        models.FollowRelationship.followed_id == current_user.id,
        models.FollowRelationship.org_id == org_id,
    ).all()


# ---------------------------------------------------------------------------
# Update / revoke relationship
# ---------------------------------------------------------------------------

@router.put(
    "/{org_slug}/follows/{relationship_id}/permission",
    response_model=schemas.FollowRelationshipOut,
)
def update_permission(
    org_slug: str,
    relationship_id: str,
    body: schemas.FollowPermissionUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    org_id = membership.org_id
    rel = db.get(models.FollowRelationship, relationship_id)
    if not rel:
        raise HTTPException(status_code=404, detail="Relationship not found")
    if rel.org_id is not None and rel.org_id != org_id:
        raise HTTPException(status_code=404, detail="Relationship not found")
    # Only the followed party can change permission level
    if rel.followed_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the followed user can change permission level")

    rel.permission_level = body.permission_level
    db.commit()
    db.refresh(rel)
    return rel


@router.delete(
    "/{org_slug}/follows/{relationship_id}",
    status_code=204,
)
def revoke_relationship(
    org_slug: str,
    relationship_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """Either party can revoke. Automatically revokes dependent delegations
    in this org only (Phase 18 B3 — see ``_revoke_dependent_delegations``)."""
    org_id = membership.org_id

    rel = db.get(models.FollowRelationship, relationship_id)
    if not rel:
        raise HTTPException(status_code=404, detail="Relationship not found")
    if rel.org_id is not None and rel.org_id != org_id:
        raise HTTPException(status_code=404, detail="Relationship not found")
    if rel.follower_id != current_user.id and rel.followed_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your relationship to revoke")

    follower_id = rel.follower_id
    followed_id = rel.followed_id
    rel_org_id = rel.org_id or org_id  # 18a fallback for NULL rows during backfill window
    other_party = followed_id if current_user.id == follower_id else follower_id

    # Revoke dependent delegations IN THIS ORG ONLY (Phase 18 B3).
    revoked_ids = _revoke_dependent_delegations(
        db, follower_id, followed_id, current_user.id, org_id=rel_org_id,
    )

    log_audit_event(
        db, action="follow.revoked",
        target_type="follow_relationship", target_id=relationship_id,
        actor_id=current_user.id,
        details={
            "other_party_id": other_party,
            "revoked_by": current_user.id,
            "org_id": rel_org_id,
            "delegations_revoked": revoked_ids,
        },
    )
    db.delete(rel)
    db.commit()
