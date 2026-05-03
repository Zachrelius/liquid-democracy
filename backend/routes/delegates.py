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
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            avatar_url=user.avatar_url,
        ),
        profiles=[schemas.DelegateProfileOut.model_validate(p) for p in profiles],
        delegation_counts=counts,
    )


@router.get("/public", response_model=list[schemas.PublicDelegateOut])
def list_public_delegates(
    topic_id: Optional[str] = Query(None),
    org_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(auth_utils.get_optional_user),
):
    """Browse public delegates, optionally filtered by topic and/or org.

    Phase 8.5 (Decision 5): when a `topic_id` is not specified and the viewer
    is authenticated, hide profiles whose ONLY active topics are sub-org topics
    the viewer isn't a member of (not a hard block — search-by-name still
    finds them; this is just browse-default scope filtering).

    Anonymous viewers continue to see all profiles, since we have no scope
    context to filter against.
    """
    q = db.query(models.User).join(
        models.DelegateProfile,
        models.DelegateProfile.user_id == models.User.id,
    ).filter(models.DelegateProfile.is_active.is_(True))

    if org_id:
        q = q.filter(models.DelegateProfile.org_id == org_id)
    if topic_id:
        q = q.filter(models.DelegateProfile.topic_id == topic_id)

    users = q.distinct().all()

    # Decision 5 scope filter: if the caller is authenticated and didn't
    # specify a topic, suppress delegates whose only active profiles are on
    # sub-org topics the viewer can't see.
    if current_user is not None and topic_id is None:
        viewer_sub_org_ids = {row.sub_org_id for row in db.query(
            models.SubOrgMembership.sub_org_id
        ).filter(
            models.SubOrgMembership.user_id == current_user.id,
            models.SubOrgMembership.status == "active",
        ).all()}

        # Pre-fetch each candidate's active profile topics joined with their
        # sub_org_id so we can decide visibility per user with one query.
        # Topic.sub_org_id is the source of truth for scope.
        rows = db.query(
            models.DelegateProfile.user_id,
            models.Topic.sub_org_id,
        ).join(
            models.Topic, models.Topic.id == models.DelegateProfile.topic_id,
        ).filter(
            models.DelegateProfile.is_active.is_(True),
            models.DelegateProfile.user_id.in_([u.id for u in users] or [""]),
        ).all()

        per_user_scopes: dict[str, set[Optional[str]]] = {}
        for user_id, sub_org_id in rows:
            per_user_scopes.setdefault(user_id, set()).add(sub_org_id)

        visible: list[models.User] = []
        for u in users:
            scopes = per_user_scopes.get(u.id, set())
            # Visible if at least one profile is parent-org-wide (None) OR
            # one is in a sub-org the viewer belongs to.
            if None in scopes or any(s in viewer_sub_org_ids for s in scopes if s):
                visible.append(u)
        users = visible

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
