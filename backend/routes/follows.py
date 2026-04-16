"""
Follow request and relationship endpoints.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

import auth as auth_utils
import models
import schemas
from audit_utils import log_audit_event
from database import get_db
from delegation_engine import graph_store

router = APIRouter(prefix="/api/follows", tags=["follows"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _revoke_dependent_delegations(
    db: Session, follower_id: str, followed_id: str, actor_id: str
) -> list[str]:
    """
    Revoke any delegations from follower → followed that were gated on a
    follow relationship (i.e. no active delegate_profile covers them).
    Returns list of revoked delegation IDs.
    """
    revoked = []
    delegations = db.query(models.Delegation).filter(
        models.Delegation.delegator_id == follower_id,
        models.Delegation.delegate_id == followed_id,
    ).all()

    for d in delegations:
        # Check if there's a delegate_profile that still allows this
        if d.topic_id:
            profile = db.query(models.DelegateProfile).filter(
                models.DelegateProfile.user_id == followed_id,
                models.DelegateProfile.topic_id == d.topic_id,
                models.DelegateProfile.is_active.is_(True),
            ).first()
        else:
            profile = db.query(models.DelegateProfile).filter(
                models.DelegateProfile.user_id == followed_id,
                models.DelegateProfile.is_active.is_(True),
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
                    "reason": "follow_relationship_revoked",
                },
            )
            graph_store.remove_delegation(follower_id, d.topic_id)
            revoked.append(d.id)
            db.delete(d)

    return revoked


# ---------------------------------------------------------------------------
# Send follow request
# ---------------------------------------------------------------------------

@router.post("/request", response_model=schemas.FollowRequestOut, status_code=201)
def send_follow_request(
    body: schemas.FollowRequestCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    if body.target_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot follow yourself")

    target = db.get(models.User, body.target_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    # Already following?
    existing_rel = db.query(models.FollowRelationship).filter(
        models.FollowRelationship.follower_id == current_user.id,
        models.FollowRelationship.followed_id == body.target_id,
    ).first()
    if existing_rel:
        raise HTTPException(status_code=409, detail="Already following this user")

    # Pending request already exists?
    existing_req = db.query(models.FollowRequest).filter(
        models.FollowRequest.requester_id == current_user.id,
        models.FollowRequest.target_id == body.target_id,
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
            message=body.message,
        )
        db.add(freq)
        db.flush()

    log_audit_event(
        db, action="follow.requested",
        target_type="follow_request", target_id=freq.id,
        actor_id=current_user.id,
        details={"target_id": body.target_id, "message": body.message},
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
            permission_level=perm,
        )
        db.add(rel)
        db.flush()

        log_audit_event(
            db, action="follow.approved",
            target_type="follow_request", target_id=freq.id,
            actor_id=body.target_id,
            details={"requester_id": current_user.id, "permission_level": perm, "auto": True},
        )

        if perm == "delegation_allowed":
            from routes.delegations import activate_intents_for_follow
            activate_intents_for_follow(db, current_user.id, body.target_id)

    db.commit()
    db.refresh(freq)
    return freq


# ---------------------------------------------------------------------------
# Incoming / outgoing requests
# ---------------------------------------------------------------------------

@router.get("/requests/incoming", response_model=list[schemas.FollowRequestOut])
def incoming_requests(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    return db.query(models.FollowRequest).filter(
        models.FollowRequest.target_id == current_user.id,
        models.FollowRequest.status == "pending",
    ).order_by(models.FollowRequest.requested_at.desc()).all()


@router.get("/requests/outgoing", response_model=list[schemas.FollowRequestOut])
def outgoing_requests(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    return db.query(models.FollowRequest).filter(
        models.FollowRequest.requester_id == current_user.id,
    ).order_by(models.FollowRequest.requested_at.desc()).all()


# ---------------------------------------------------------------------------
# Respond to a follow request
# ---------------------------------------------------------------------------

@router.put("/requests/{request_id}/respond", response_model=schemas.FollowRequestOut)
def respond_to_request(
    request_id: str,
    body: schemas.FollowRequestRespond,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    freq = db.get(models.FollowRequest, request_id)
    if not freq:
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

        # Check if relationship already exists (shouldn't, but be safe)
        existing = db.query(models.FollowRelationship).filter(
            models.FollowRelationship.follower_id == freq.requester_id,
            models.FollowRelationship.followed_id == current_user.id,
        ).first()
        if not existing:
            rel = models.FollowRelationship(
                follower_id=freq.requester_id,
                followed_id=current_user.id,
                permission_level=perm,
            )
            db.add(rel)
            db.flush()

        log_audit_event(
            db, action="follow.approved",
            target_type="follow_request", target_id=freq.id,
            actor_id=current_user.id,
            details={"requester_id": freq.requester_id, "permission_level": perm},
        )

        # Auto-activate delegation intents if approved with delegation_allowed
        if perm == "delegation_allowed":
            from routes.delegations import activate_intents_for_follow
            activate_intents_for_follow(db, freq.requester_id, current_user.id)
    else:
        db.flush()
        log_audit_event(
            db, action="follow.denied",
            target_type="follow_request", target_id=freq.id,
            actor_id=current_user.id,
            details={"requester_id": freq.requester_id},
        )

    db.commit()
    db.refresh(freq)
    return freq


# ---------------------------------------------------------------------------
# Following / followers lists
# ---------------------------------------------------------------------------

@router.get("/following", response_model=list[schemas.FollowRelationshipOut])
def list_following(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    return db.query(models.FollowRelationship).filter(
        models.FollowRelationship.follower_id == current_user.id,
    ).all()


@router.get("/followers", response_model=list[schemas.FollowRelationshipOut])
def list_followers(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    return db.query(models.FollowRelationship).filter(
        models.FollowRelationship.followed_id == current_user.id,
    ).all()


# ---------------------------------------------------------------------------
# Update / revoke relationship
# ---------------------------------------------------------------------------

@router.put("/{relationship_id}/permission", response_model=schemas.FollowRelationshipOut)
def update_permission(
    relationship_id: str,
    body: schemas.FollowPermissionUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    rel = db.get(models.FollowRelationship, relationship_id)
    if not rel:
        raise HTTPException(status_code=404, detail="Relationship not found")
    # Only the followed party can change permission level
    if rel.followed_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the followed user can change permission level")

    rel.permission_level = body.permission_level
    db.commit()
    db.refresh(rel)
    return rel


@router.delete("/{relationship_id}", status_code=204)
def revoke_relationship(
    relationship_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Either party can revoke. Automatically revokes dependent delegations."""
    rel = db.get(models.FollowRelationship, relationship_id)
    if not rel:
        raise HTTPException(status_code=404, detail="Relationship not found")
    if rel.follower_id != current_user.id and rel.followed_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your relationship to revoke")

    follower_id = rel.follower_id
    followed_id = rel.followed_id
    other_party = followed_id if current_user.id == follower_id else follower_id

    # Revoke dependent delegations (follower → followed only; follower chose to delegate)
    revoked_ids = _revoke_dependent_delegations(db, follower_id, followed_id, current_user.id)

    log_audit_event(
        db, action="follow.revoked",
        target_type="follow_relationship", target_id=relationship_id,
        actor_id=current_user.id,
        details={
            "other_party_id": other_party,
            "revoked_by": current_user.id,
            "delegations_revoked": revoked_ids,
        },
    )
    db.delete(rel)
    db.commit()
