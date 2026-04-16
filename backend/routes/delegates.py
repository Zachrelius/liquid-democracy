"""
Public delegate registration and browsing endpoints.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

import auth as auth_utils
import models
import schemas
from audit_utils import log_audit_event
from database import get_db

router = APIRouter(prefix="/api/delegates", tags=["delegates"])


def _delegation_count(db: Session, user_id: str, topic_id: str) -> int:
    return db.query(models.Delegation).filter(
        models.Delegation.delegate_id == user_id,
        models.Delegation.topic_id == topic_id,
    ).count()


def _build_public_delegate(db: Session, user: models.User) -> schemas.PublicDelegateOut:
    profiles = [p for p in user.delegate_profiles if p.is_active]
    counts = {p.topic_id: _delegation_count(db, user.id, p.topic_id) for p in profiles}
    return schemas.PublicDelegateOut(
        user=schemas.UserSearchResult(
            id=user.id, username=user.username, display_name=user.display_name
        ),
        profiles=[schemas.DelegateProfileOut.model_validate(p) for p in profiles],
        delegation_counts=counts,
    )


@router.get("/public", response_model=list[schemas.PublicDelegateOut])
def list_public_delegates(
    topic_id: Optional[str] = Query(None),
    org_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Browse public delegates, optionally filtered by topic and/or org."""
    q = db.query(models.User).join(
        models.DelegateProfile,
        models.DelegateProfile.user_id == models.User.id,
    ).filter(models.DelegateProfile.is_active.is_(True))

    if org_id:
        q = q.filter(models.DelegateProfile.org_id == org_id)
    if topic_id:
        q = q.filter(models.DelegateProfile.topic_id == topic_id)

    users = q.distinct().all()
    return [_build_public_delegate(db, u) for u in users]


@router.get("/public/{topic_id}", response_model=list[schemas.PublicDelegateOut])
def public_delegates_for_topic(
    topic_id: str,
    db: Session = Depends(get_db),
):
    """Public delegates for a specific topic, sorted by delegation count."""
    topic = db.get(models.Topic, topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    users = db.query(models.User).join(
        models.DelegateProfile,
        models.DelegateProfile.user_id == models.User.id,
    ).filter(
        models.DelegateProfile.topic_id == topic_id,
        models.DelegateProfile.is_active.is_(True),
    ).all()

    results = [_build_public_delegate(db, u) for u in users]
    results.sort(key=lambda r: r.delegation_counts.get(topic_id, 0), reverse=True)
    return results


@router.post("/register", response_model=schemas.DelegateProfileOut, status_code=201)
def register_as_delegate(
    body: schemas.DelegateProfileCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Register as a public delegate for a topic (or reactivate if previously deactivated)."""
    topic = db.get(models.Topic, body.topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    existing = db.query(models.DelegateProfile).filter(
        models.DelegateProfile.user_id == current_user.id,
        models.DelegateProfile.topic_id == body.topic_id,
    ).first()

    if existing:
        existing.is_active = True
        existing.bio = body.bio
        db.flush()
        log_audit_event(
            db, action="delegate_profile.created",
            target_type="delegate_profile", target_id=existing.id,
            actor_id=current_user.id, details={"topic_id": body.topic_id},
        )
        db.commit()
        db.refresh(existing)
        return existing

    profile = models.DelegateProfile(
        user_id=current_user.id,
        topic_id=body.topic_id,
        bio=body.bio,
    )
    db.add(profile)
    db.flush()
    log_audit_event(
        db, action="delegate_profile.created",
        target_type="delegate_profile", target_id=profile.id,
        actor_id=current_user.id, details={"topic_id": body.topic_id},
    )
    db.commit()
    db.refresh(profile)
    return profile


@router.delete("/register/{topic_id}", status_code=204)
def deactivate_delegate_profile(
    topic_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Deactivate public delegate status for a topic. Existing delegations remain."""
    profile = db.query(models.DelegateProfile).filter(
        models.DelegateProfile.user_id == current_user.id,
        models.DelegateProfile.topic_id == topic_id,
        models.DelegateProfile.is_active.is_(True),
    ).first()
    if not profile:
        raise HTTPException(status_code=404, detail="No active delegate profile for this topic")

    profile.is_active = False
    db.flush()
    log_audit_event(
        db, action="delegate_profile.deactivated",
        target_type="delegate_profile", target_id=profile.id,
        actor_id=current_user.id, details={"topic_id": topic_id},
    )
    db.commit()
