"""
Delegation and visibility permission helpers.

All functions are pure DB queries — no side effects.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

import models


# ---------------------------------------------------------------------------
# Delegation permission
# ---------------------------------------------------------------------------

def can_delegate_to(
    db: Session,
    delegator_id: str,
    delegate_id: str,
    topic_id: Optional[str],
) -> bool:
    """
    Return True if delegator_id is permitted to delegate to delegate_id
    on the given topic (or globally if topic_id is None).

    Rules:
      1. Public delegate profile for the topic → allowed.
      2. follow_relationship with delegation_allowed → allowed.
      3. For global (topic_id=None): either a delegation_allowed follow OR
         the delegate has at least one active profile (any topic).
    """
    if topic_id is not None:
        # Rule 1: active delegate_profile for this specific topic
        profile = db.query(models.DelegateProfile).filter(
            models.DelegateProfile.user_id == delegate_id,
            models.DelegateProfile.topic_id == topic_id,
            models.DelegateProfile.is_active.is_(True),
        ).first()
        if profile:
            return True
    else:
        # Global delegation: any active profile is enough (public delegate on any topic)
        any_profile = db.query(models.DelegateProfile).filter(
            models.DelegateProfile.user_id == delegate_id,
            models.DelegateProfile.is_active.is_(True),
        ).first()
        if any_profile:
            return True

    # Rule 2: follow relationship with delegation_allowed
    rel = db.query(models.FollowRelationship).filter(
        models.FollowRelationship.follower_id == delegator_id,
        models.FollowRelationship.followed_id == delegate_id,
        models.FollowRelationship.permission_level == "delegation_allowed",
    ).first()
    return rel is not None


def delegation_denied_message(topic_id: Optional[str]) -> str:
    topic_clause = f"for topic {topic_id}" if topic_id else "globally"
    return (
        f"Cannot delegate to this user {topic_clause}. "
        "They are not a public delegate for this topic and you do not have a "
        "follow relationship with delegation permission. "
        "Send a follow request first, or browse public delegates."
    )


# ---------------------------------------------------------------------------
# Vote visibility
# ---------------------------------------------------------------------------

def can_see_votes(
    db: Session,
    viewer_id: Optional[str],
    target_user_id: str,
    topic_ids: list[str],
) -> bool:
    """
    Return True if viewer can see target_user_id's votes on proposals
    that include any of the given topic_ids.

    Rules:
      - viewer is the target themselves → always True
      - target is a public delegate for any of the proposal's topics → True
      - viewer has any follow relationship with target → True
    """
    if viewer_id == target_user_id:
        return True

    # Public delegate on a matching topic
    if topic_ids:
        profile = db.query(models.DelegateProfile).filter(
            models.DelegateProfile.user_id == target_user_id,
            models.DelegateProfile.topic_id.in_(topic_ids),
            models.DelegateProfile.is_active.is_(True),
        ).first()
        if profile:
            return True

    if viewer_id is None:
        return False

    # Any follow relationship (view_only or delegation_allowed)
    rel = db.query(models.FollowRelationship).filter(
        models.FollowRelationship.follower_id == viewer_id,
        models.FollowRelationship.followed_id == target_user_id,
    ).first()
    return rel is not None


def public_delegate_topic_ids(db: Session, user_id: str) -> set[str]:
    """Return the set of topic_ids for which user_id has an active delegate profile."""
    rows = db.query(models.DelegateProfile.topic_id).filter(
        models.DelegateProfile.user_id == user_id,
        models.DelegateProfile.is_active.is_(True),
    ).all()
    return {r.topic_id for r in rows}
