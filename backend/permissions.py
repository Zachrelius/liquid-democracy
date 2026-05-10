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
# Phase 8.5 — Sub-org permission helper (Phase 15 — role_id FK now)
# ---------------------------------------------------------------------------

# Phase 15 Cluster S — SubOrgMembership.role is now an FK to Role
# (parent's matrix wholesale); compare via role.system_key. The
# admin-tier set is the same {admin, steward} as for parent
# OrgMembership; "owner" was retired by the Phase 12 rename.
_SUB_ORG_ADMIN_TIER_SYSTEM_KEYS = ("admin", "steward")
_SUB_ORG_PROPOSAL_CREATOR_TIERS = ("moderator", "admin", "steward")
_PARENT_ADMIN_TIER_SYSTEM_KEYS = ("admin", "steward")


def _sub_membership_role_system_key(
    sub_membership: models.SubOrgMembership | None,
) -> str | None:
    """Resolve a SubOrgMembership row to its role.system_key, or None.

    Phase 15 Cluster S: SubOrgMembership.role is now an FK relationship
    to Role (parent-org's matrix). The string column is gone; callers
    that previously compared ``sub_membership.role == 'admin'`` should
    use this helper or the explicit ``role.system_key`` chain.
    """
    if sub_membership is None or sub_membership.role is None:
        return None
    return sub_membership.role.system_key


def is_sub_org_admin(
    db: Session, user_id: str, sub_org: models.Organization
) -> bool:
    """Decision 6 + Phase 15 Cluster S: True iff ``user_id`` can act as
    admin of ``sub_org``.

    A user qualifies if any of:
      (a) They have an active SubOrgMembership in ``sub_org`` with the
          role.system_key in {'admin', 'steward'}, OR
      (b) They have an active OrgMembership in the parent org whose
          role.system_key is in {'admin', 'steward'} AND that role
          transfers to sub-orgs (Phase 15 transferability config — see
          ``role_permissions.role_transfers_to_sub_orgs``). The
          configurability is new in Phase 15: previously parent admins
          ALWAYS got implicit sub-org admin power; now parent-Steward
          always transfers (locked on) and parent-Admin defaults ON but
          is configurable via ``Organization.settings``.

    Note: this helper retains its narrow contract ("admin tier on this
    sub-org"); callers checking a specific permission should use
    ``role_permissions.has_permission_on_sub_org`` instead, which
    consults the parent's matrix at the resolved role.

    Raises ValueError if ``sub_org`` is not actually a sub-org.
    """
    if sub_org.parent_org_id is None:
        raise ValueError(
            "is_sub_org_admin called on a non-sub-org "
            f"(organization id={sub_org.id} has parent_org_id=NULL). "
            "This helper is only valid for sub-orgs."
        )

    # (a) Direct sub-org admin tier — SubOrgMembership.role is now an
    # FK to Role; check via the related row's system_key.
    sub_membership = db.query(models.SubOrgMembership).filter(
        models.SubOrgMembership.user_id == user_id,
        models.SubOrgMembership.sub_org_id == sub_org.id,
        models.SubOrgMembership.status == "active",
    ).first()
    sub_sk = _sub_membership_role_system_key(sub_membership)
    if sub_sk in _SUB_ORG_ADMIN_TIER_SYSTEM_KEYS:
        return True

    # (b) Parent-org admin/Steward (implicit power), gated by Phase 15
    # transferability config. Steward always transfers; Admin
    # configurable via Organization.settings.sub_org_role_transferability.
    # Imported lazily to avoid a circular import (role_permissions
    # imports models which is also where SubOrgMembership lives).
    from role_permissions import role_transfers_to_sub_orgs
    parent_org = db.get(models.Organization, sub_org.parent_org_id)
    parent_membership = db.query(models.OrgMembership).filter(
        models.OrgMembership.user_id == user_id,
        models.OrgMembership.org_id == sub_org.parent_org_id,
        models.OrgMembership.status == "active",
    ).first()
    if (
        parent_membership is not None
        and parent_membership.role is not None
        and parent_membership.role.system_key in _PARENT_ADMIN_TIER_SYSTEM_KEYS
        and parent_org is not None
        and role_transfers_to_sub_orgs(
            parent_org, parent_membership.role.system_key,
        )
    ):
        return True

    return False


def can_create_proposal_in_sub_org(
    db: Session, user_id: str, sub_org: models.Organization,
) -> bool:
    """Decision 6 + Session 3 clarification + Phase 15 transferability.

    A user can create proposals scoped to a sub-org if EITHER:
      - they have an active SubOrgMembership with role.system_key in
        {'moderator', 'admin', 'steward'}; OR
      - they have an inherited governance role that grants them admin
        power on the sub-org (via ``is_sub_org_admin``).

    A sub-org `member` (no elevated role) cannot create proposals.

    Raises ValueError if ``sub_org.parent_org_id IS NULL`` — programmer
    error.
    """
    if sub_org.parent_org_id is None:
        raise ValueError(
            "can_create_proposal_in_sub_org called on a non-sub-org "
            f"(organization id={sub_org.id} has parent_org_id=NULL). "
            "This helper is only valid for sub-orgs; use the existing "
            "org-moderator gate for parent-org-scoped proposals."
        )

    # (a) Active sub-org membership with moderator+ role.system_key.
    sub_membership = db.query(models.SubOrgMembership).filter(
        models.SubOrgMembership.user_id == user_id,
        models.SubOrgMembership.sub_org_id == sub_org.id,
        models.SubOrgMembership.status == "active",
    ).first()
    sub_sk = _sub_membership_role_system_key(sub_membership)
    if sub_sk in _SUB_ORG_PROPOSAL_CREATOR_TIERS:
        return True

    # (b) Inherited admin tier via is_sub_org_admin (parent admin/Steward
    # path, gated by transferability per Phase 15).
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
    if membership is None or membership.role is None:
        return False
    # Phase 12 — moderator+ tier on the Role.system_key (renamed from the
    # legacy 'owner' string column).
    return membership.role.system_key in ("moderator", "admin", "steward")


# ---------------------------------------------------------------------------
# Phase 19 — vote rationale visibility
# ---------------------------------------------------------------------------

def can_view_vote_rationale(
    viewer: Optional[models.User],
    vote: models.Vote,
    db: Session,
) -> bool:
    """Centralized visibility gate for ``DelegateVoteRationale`` rows
    (spec §B6 line 219; spec line 326 — single source of truth).

    Returns True iff:

      * ``viewer`` is the vote owner (always sees their own rationale),
        OR
      * the vote owner has at least one of the proposal's topics in a
        non-``private`` ``DelegateProfile.visibility`` state in the
        proposal's org, AND ``viewer`` has access to the org (active
        member, OR — for publicly-listed orgs — anonymous viewers).

    "Access to the org" mirrors the public-delegate-page rule: anyone
    can view if the org is publicly listed, otherwise an active
    OrgMembership is required. The vote-owner bypass takes precedence so
    the owner's own writeable surface always shows the rationale even
    if the topic is currently private.

    The "primary topic" wording in the spec is interpreted as ANY of the
    proposal's topics in non-private state — the author of a multi-topic
    proposal may have made one topic public and another private; we
    surface the rationale if AT LEAST ONE intersects with a public-or-
    public_accepting profile. This matches D5: "becoming a public
    delegate on Housing makes Housing votes visible without making
    Transportation votes visible."
    """
    if viewer is not None and viewer.id == vote.user_id:
        return True

    proposal = db.get(models.Proposal, vote.proposal_id)
    if proposal is None or proposal.org_id is None:
        # Defensive — votes always belong to a proposal in an org.
        return False

    # Vote owner's per-topic visibility on the proposal's topics.
    topic_ids = [pt.topic_id for pt in proposal.proposal_topics]
    if not topic_ids:
        # Proposal has no topics — there's no public-delegate surface to
        # gate visibility against. Default closed (no rationale visible
        # to non-owners).
        return False

    has_public_topic = (
        db.query(models.DelegateProfile.id)
        .filter(
            models.DelegateProfile.user_id == vote.user_id,
            models.DelegateProfile.org_id == proposal.org_id,
            models.DelegateProfile.topic_id.in_(topic_ids),
            models.DelegateProfile.visibility != "private",
        )
        .first()
        is not None
    )
    if not has_public_topic:
        return False

    # Org access check.
    org = db.get(models.Organization, proposal.org_id)
    if org is None:
        return False

    # Publicly-listed orgs allow anonymous + non-member viewing.
    # Mirror the Phase 14 ``public_org_router`` rule: org is "public"
    # iff ``join_policy != 'invite_only_secret'`` (those secret orgs are
    # designed to be indistinguishable from non-existent ones from an
    # unauthenticated probe perspective).
    if org.join_policy != "invite_only_secret":
        return True

    if viewer is None:
        return False

    membership = (
        db.query(models.OrgMembership)
        .filter(
            models.OrgMembership.user_id == viewer.id,
            models.OrgMembership.org_id == proposal.org_id,
            models.OrgMembership.status == "active",
        )
        .first()
    )
    return membership is not None
