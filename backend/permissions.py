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


# ---------------------------------------------------------------------------
# Phase 8.5 — Sub-org permission helper
# ---------------------------------------------------------------------------

_ADMIN_ROLES = ("admin", "owner")
_SUB_ORG_PROPOSAL_CREATOR_ROLES = ("moderator", "admin", "owner")


def is_sub_org_admin(
    db: Session, user_id: str, sub_org: models.Organization
) -> bool:
    """Decision 6: True iff ``user_id`` can act as admin of ``sub_org``.

    A user qualifies if EITHER:
      (a) They have an active SubOrgMembership in ``sub_org`` with role
          'admin' or 'owner', OR
      (b) They have an active OrgMembership in the parent org
          (``sub_org.parent_org_id``) with role 'admin' or 'owner' — the
          implicit-admin pattern (parent-org admins govern all sub-orgs).

    Sub-org admins do NOT have powers outside their sub-org. This helper
    only answers "can this user admin THIS specific sub-org?". The implicit-
    admin pattern is read-time, not stored — no row says "alice is admin of
    every sub-org"; we just check her parent-org role at each call site.

    Raises ValueError if ``sub_org`` is not actually a sub-org
    (parent_org_id IS NULL). The helper is for sub-orgs only; callers
    asking about parent-org admin powers should use the existing
    OrgMembership-based checks in routes/organizations.py.
    """
    if sub_org.parent_org_id is None:
        raise ValueError(
            "is_sub_org_admin called on a non-sub-org "
            f"(organization id={sub_org.id} has parent_org_id=NULL). "
            "This helper is only valid for sub-orgs."
        )

    # (a) Direct sub-org admin/owner
    sub_membership = db.query(models.SubOrgMembership).filter(
        models.SubOrgMembership.user_id == user_id,
        models.SubOrgMembership.sub_org_id == sub_org.id,
        models.SubOrgMembership.status == "active",
    ).first()
    if sub_membership is not None and sub_membership.role in _ADMIN_ROLES:
        return True

    # (b) Parent-org admin/owner (implicit power)
    parent_membership = db.query(models.OrgMembership).filter(
        models.OrgMembership.user_id == user_id,
        models.OrgMembership.org_id == sub_org.parent_org_id,
        models.OrgMembership.status == "active",
    ).first()
    if parent_membership is not None and parent_membership.role in _ADMIN_ROLES:
        return True

    return False


def can_create_proposal_in_sub_org(
    db: Session, user_id: str, sub_org: models.Organization,
) -> bool:
    """Decision 6 + Session 3 clarification.

    A user can create proposals scoped to a sub-org if EITHER:
      - they have an active SubOrgMembership in the sub-org with role
        IN ('moderator', 'admin', 'owner'); OR
      - they are a parent-org admin/owner (implicit sub-org admin via
        is_sub_org_admin already covers this — we just call through).

    A sub-org `member` (no elevated role) cannot create proposals;
    they can vote on existing ones. This matches how parent-org
    proposal creation already works (parent-org moderator+ required).

    Raises ValueError if ``sub_org.parent_org_id IS NULL`` — programmer
    error; use the existing org-moderator gate for parent-org-scoped
    proposals.
    """
    if sub_org.parent_org_id is None:
        raise ValueError(
            "can_create_proposal_in_sub_org called on a non-sub-org "
            f"(organization id={sub_org.id} has parent_org_id=NULL). "
            "This helper is only valid for sub-orgs; use the existing "
            "org-moderator gate for parent-org-scoped proposals."
        )

    # (a) Active sub-org membership with moderator+ role
    sub_membership = db.query(models.SubOrgMembership).filter(
        models.SubOrgMembership.user_id == user_id,
        models.SubOrgMembership.sub_org_id == sub_org.id,
        models.SubOrgMembership.status == "active",
    ).first()
    if (
        sub_membership is not None
        and sub_membership.role in _SUB_ORG_PROPOSAL_CREATOR_ROLES
    ):
        return True

    # (b) Implicit parent-org-admin path. Decision 6: parent-org admin/owner
    # has implicit sub-org admin power, which includes proposal creation.
    return is_sub_org_admin(db, user_id, sub_org)


# ---------------------------------------------------------------------------
# Phase 9 — Polis admin permission helper
# ---------------------------------------------------------------------------

def is_polis_admin(
    db: Session, user_id: str, polis: models.Polis,
) -> bool:
    """Phase 9 Decision 6 — True iff ``user_id`` can admin a Polis.

    A user qualifies if ANY of:
      (a) They are the Polis creator (``polis.created_by``).
      (b) For sub-org Polises, they pass ``is_sub_org_admin`` for the
          Polis's sub-org (covers both direct sub-org admins/owners AND
          parent-org admins/owners via Decision 6 implicit power).
      (c) For org-wide Polises, they have an active OrgMembership in
          ``polis.org_id`` with role IN ('moderator', 'admin', 'owner') —
          matching the org-wide topic-creation tier.

    Edge case: if a user creates a Polis and then loses their
    moderator+ role, they remain admin of THAT Polis via (a). This
    matches how proposal authors retain edit power on their drafts.
    """
    if polis.created_by == user_id:
        return True

    if polis.sub_org_id is not None:
        # Sub-org Polis.
        sub_org = polis.sub_organization
        if sub_org is None:
            sub_org = db.query(models.Organization).filter(
                models.Organization.id == polis.sub_org_id,
            ).first()
        if sub_org is None:
            return False
        return is_sub_org_admin(db, user_id, sub_org)

    # Org-wide Polis.
    membership = db.query(models.OrgMembership).filter(
        models.OrgMembership.user_id == user_id,
        models.OrgMembership.org_id == polis.org_id,
        models.OrgMembership.status == "active",
    ).first()
    if membership is None:
        return False
    return membership.role in ("moderator", "admin", "owner")
