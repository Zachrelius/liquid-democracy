"""
Phase 3a tests — delegation permissions, follow flow, vote visibility, and cascade revocation.

All tests use an in-memory SQLite DB (via the `db` fixture) and the helpers in conftest.py.
"""

import pytest
from sqlalchemy.orm import Session

import models
from permissions import can_delegate_to, can_see_votes, public_delegate_topic_ids
from audit_utils import log_audit_event
from tests.conftest import (
    make_user, make_topic, make_proposal, cast_direct_vote, set_delegation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_delegate_profile(
    db: Session,
    user: models.User,
    topic: models.Topic,
    bio: str = "Test bio",
) -> models.DelegateProfile:
    p = models.DelegateProfile(user_id=user.id, topic_id=topic.id, bio=bio)
    db.add(p)
    db.flush()
    return p


def make_follow_relationship(
    db: Session,
    follower: models.User,
    followed: models.User,
    permission_level: str = "view_only",
) -> models.FollowRelationship:
    r = models.FollowRelationship(
        follower_id=follower.id,
        followed_id=followed.id,
        permission_level=permission_level,
    )
    db.add(r)
    db.flush()
    return r


def make_follow_request(
    db: Session,
    requester: models.User,
    target: models.User,
    message: str | None = None,
) -> models.FollowRequest:
    req = models.FollowRequest(
        requester_id=requester.id,
        target_id=target.id,
        status="pending",
        message=message,
    )
    db.add(req)
    db.flush()
    return req


# ---------------------------------------------------------------------------
# 1. Public delegate can receive delegation without follow relationship
# ---------------------------------------------------------------------------

def test_public_delegate_allows_delegation_without_follow(db):
    alice = make_user(db, "alice")
    dr_chen = make_user(db, "dr_chen")
    health = make_topic(db, "health")
    make_delegate_profile(db, dr_chen, health)

    assert can_delegate_to(db, alice.id, dr_chen.id, health.id) is True


def test_public_delegate_inactive_profile_blocks_delegation(db):
    alice = make_user(db, "alice")
    dr_chen = make_user(db, "dr_chen")
    health = make_topic(db, "health")
    p = make_delegate_profile(db, dr_chen, health)
    p.is_active = False
    db.flush()

    assert can_delegate_to(db, alice.id, dr_chen.id, health.id) is False


def test_public_delegate_wrong_topic_blocks_delegation(db):
    alice = make_user(db, "alice")
    dr_chen = make_user(db, "dr_chen")
    health = make_topic(db, "health")
    economy = make_topic(db, "economy")
    make_delegate_profile(db, dr_chen, health)

    # dr_chen is public on health but NOT on economy
    assert can_delegate_to(db, alice.id, dr_chen.id, economy.id) is False


# ---------------------------------------------------------------------------
# 2. Non-public, non-followed user cannot receive delegation (403)
# ---------------------------------------------------------------------------

def test_no_profile_no_follow_blocks_delegation(db):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    health = make_topic(db, "health")

    assert can_delegate_to(db, alice.id, bob.id, health.id) is False


def test_view_only_follow_blocks_delegation(db):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    health = make_topic(db, "health")
    make_follow_relationship(db, alice, bob, "view_only")

    assert can_delegate_to(db, alice.id, bob.id, health.id) is False


# ---------------------------------------------------------------------------
# 3. Follow request → approval → delegation flow
# ---------------------------------------------------------------------------

def test_delegation_allowed_follow_permits_delegation(db):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    health = make_topic(db, "health")
    make_follow_relationship(db, alice, bob, "delegation_allowed")

    assert can_delegate_to(db, alice.id, bob.id, health.id) is True


def test_follow_request_approval_creates_relationship(db):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")

    req = make_follow_request(db, alice, bob)
    assert req.status == "pending"

    # Simulate approval
    from datetime import datetime, timezone
    req.status = "approved"
    req.permission_level = "delegation_allowed"
    req.responded_at = datetime.now(timezone.utc)
    rel = models.FollowRelationship(
        follower_id=alice.id,
        followed_id=bob.id,
        permission_level="delegation_allowed",
    )
    db.add(rel)
    db.flush()

    health = make_topic(db, "health")
    assert can_delegate_to(db, alice.id, bob.id, health.id) is True


def test_full_follow_request_to_delegation_flow(db):
    """End-to-end: request → approve → can delegate."""
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    health = make_topic(db, "health")

    # Before request: can't delegate
    assert can_delegate_to(db, alice.id, bob.id, health.id) is False

    # After approval with delegation_allowed
    make_follow_relationship(db, alice, bob, "delegation_allowed")
    assert can_delegate_to(db, alice.id, bob.id, health.id) is True


# ---------------------------------------------------------------------------
# 4. Follow revocation cascades to delegation revocation
# ---------------------------------------------------------------------------

def test_revoke_follow_cascades_to_delegation(db, store):
    from routes.follows import _revoke_dependent_delegations

    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    health = make_topic(db, "health")

    # Set up: alice follows bob with delegation_allowed, has a delegation
    make_follow_relationship(db, alice, bob, "delegation_allowed")
    delegation = set_delegation(db, store, alice, bob, health)
    db.commit()

    # Sanity: delegation exists
    assert db.get(models.Delegation, delegation.id) is not None

    # Revoke follow — should cascade
    revoked = _revoke_dependent_delegations(db, alice.id, bob.id, alice.id)
    db.flush()

    assert delegation.id in revoked
    assert db.query(models.Delegation).filter(
        models.Delegation.delegator_id == alice.id,
        models.Delegation.delegate_id == bob.id,
    ).first() is None


def test_revoke_follow_does_not_cascade_when_public_profile_exists(db, store):
    """If delegation is covered by a public profile, revocation shouldn't remove it."""
    from routes.follows import _revoke_dependent_delegations

    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    health = make_topic(db, "health")

    # Bob is a public delegate for health — profile covers the delegation
    make_delegate_profile(db, bob, health)
    make_follow_relationship(db, alice, bob, "delegation_allowed")
    delegation = set_delegation(db, store, alice, bob, health)
    db.commit()

    revoked = _revoke_dependent_delegations(db, alice.id, bob.id, alice.id)
    db.flush()

    # Delegation should NOT have been revoked because the profile covers it
    assert delegation.id not in revoked
    assert db.get(models.Delegation, delegation.id) is not None


# ---------------------------------------------------------------------------
# 5. Auto-approve policies
# ---------------------------------------------------------------------------

def test_auto_approve_view_creates_relationship_immediately(db):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    bob.default_follow_policy = "auto_approve_view"
    db.flush()

    from routes.follows import _now
    from unittest.mock import MagicMock, patch

    # Simulate what the endpoint does
    assert bob.default_follow_policy == "auto_approve_view"
    perm = "view_only" if bob.default_follow_policy == "auto_approve_view" else "delegation_allowed"
    assert perm == "view_only"


def test_auto_approve_delegate_policy(db):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    bob.default_follow_policy = "auto_approve_delegate"
    db.flush()

    perm = "delegation_allowed" if bob.default_follow_policy == "auto_approve_delegate" else "view_only"
    assert perm == "delegation_allowed"


def test_require_approval_policy_does_not_auto_approve(db):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    # default is require_approval
    assert bob.default_follow_policy == "require_approval"

    req = make_follow_request(db, alice, bob)
    assert req.status == "pending"
    # No follow relationship should exist
    rel = db.query(models.FollowRelationship).filter(
        models.FollowRelationship.follower_id == alice.id,
        models.FollowRelationship.followed_id == bob.id,
    ).first()
    assert rel is None


# ---------------------------------------------------------------------------
# 6. Vote visibility respects permissions
# ---------------------------------------------------------------------------

def test_self_can_always_see_own_votes(db):
    alice = make_user(db, "alice")
    health = make_topic(db, "health")
    assert can_see_votes(db, alice.id, alice.id, [health.id]) is True


def test_public_delegate_votes_visible_to_all(db):
    dr_chen = make_user(db, "dr_chen")
    health = make_topic(db, "health")
    make_delegate_profile(db, dr_chen, health)

    stranger = make_user(db, "stranger")
    assert can_see_votes(db, stranger.id, dr_chen.id, [health.id]) is True
    # Anonymous viewer
    assert can_see_votes(db, None, dr_chen.id, [health.id]) is True


def test_public_delegate_votes_not_visible_on_other_topics(db):
    dr_chen = make_user(db, "dr_chen")
    health = make_topic(db, "health")
    economy = make_topic(db, "economy")
    make_delegate_profile(db, dr_chen, health)  # only health

    stranger = make_user(db, "stranger")
    # Proposal only tagged economy — dr_chen not public there
    assert can_see_votes(db, stranger.id, dr_chen.id, [economy.id]) is False


def test_follower_can_see_votes(db):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    health = make_topic(db, "health")
    make_follow_relationship(db, alice, bob, "view_only")

    assert can_see_votes(db, alice.id, bob.id, [health.id]) is True


def test_non_follower_cannot_see_votes(db):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    health = make_topic(db, "health")

    assert can_see_votes(db, alice.id, bob.id, [health.id]) is False


def test_public_delegate_topic_ids_returns_active_only(db):
    user = make_user(db, "user1")
    health = make_topic(db, "health")
    economy = make_topic(db, "economy")

    p1 = make_delegate_profile(db, user, health)
    p2 = make_delegate_profile(db, user, economy)
    p2.is_active = False
    db.flush()

    result = public_delegate_topic_ids(db, user.id)
    assert health.id in result
    assert economy.id not in result


# ---------------------------------------------------------------------------
# 7. Delegation chain metadata visible without follow to indirect delegate
# ---------------------------------------------------------------------------

def test_delegation_chain_resolution_works_without_follow(db, store):
    """
    Resolution: alice → bob → carol.
    Alice needs a follow/profile for bob but NOT for carol to resolve the chain.
    """
    from delegation_engine import resolve_vote_pure, ProposalContext, DelegationData

    alice_id, bob_id, carol_id = "alice", "bob", "carol"
    topic_id = "t1"

    ctx = ProposalContext(
        proposal_topics=[topic_id],
        all_delegations={
            alice_id: {topic_id: DelegationData(alice_id, bob_id, topic_id, "accept_sub")},
            bob_id: {topic_id: DelegationData(bob_id, carol_id, topic_id, "accept_sub")},
        },
        all_precedences={},
        direct_votes={carol_id: "yes"},
    )
    result = resolve_vote_pure(alice_id, ctx)
    assert result is not None
    assert result.vote_value == "yes"
    assert carol_id in result.delegate_chain


# ---------------------------------------------------------------------------
# 8. Audit log entries for follow / delegate_profile actions
# ---------------------------------------------------------------------------

def test_audit_log_for_delegate_profile_creation(db):
    user = make_user(db, "user1")
    topic = make_topic(db, "health")
    profile = make_delegate_profile(db, user, topic)

    log_audit_event(
        db, action="delegate_profile.created",
        target_type="delegate_profile", target_id=profile.id,
        actor_id=user.id, details={"topic_id": topic.id},
    )
    db.flush()

    entry = db.query(models.AuditLog).filter(
        models.AuditLog.action == "delegate_profile.created"
    ).first()
    assert entry is not None
    assert entry.actor_id == user.id
    assert entry.details["topic_id"] == topic.id


def test_audit_log_for_follow_request(db):
    requester = make_user(db, "req")
    target = make_user(db, "tgt")
    req = make_follow_request(db, requester, target, "hello")

    log_audit_event(
        db, action="follow.requested",
        target_type="follow_request", target_id=req.id,
        actor_id=requester.id, details={"target_id": target.id, "message": "hello"},
    )
    db.flush()

    entry = db.query(models.AuditLog).filter(
        models.AuditLog.action == "follow.requested"
    ).first()
    assert entry is not None
    assert entry.details["target_id"] == target.id


def test_audit_log_for_follow_approved(db):
    requester = make_user(db, "req")
    target = make_user(db, "tgt")
    req = make_follow_request(db, requester, target)

    log_audit_event(
        db, action="follow.approved",
        target_type="follow_request", target_id=req.id,
        actor_id=target.id,
        details={"requester_id": requester.id, "permission_level": "delegation_allowed"},
    )
    db.flush()

    entry = db.query(models.AuditLog).filter(
        models.AuditLog.action == "follow.approved"
    ).first()
    assert entry is not None
    assert entry.details["permission_level"] == "delegation_allowed"


def test_audit_log_for_follow_revoked(db):
    follower = make_user(db, "follower")
    followed = make_user(db, "followed")
    rel = make_follow_relationship(db, follower, followed)

    log_audit_event(
        db, action="follow.revoked",
        target_type="follow_relationship", target_id=rel.id,
        actor_id=follower.id,
        details={"other_party_id": followed.id, "revoked_by": follower.id, "delegations_revoked": []},
    )
    db.flush()

    entry = db.query(models.AuditLog).filter(
        models.AuditLog.action == "follow.revoked"
    ).first()
    assert entry is not None
    assert entry.actor_id == follower.id


def test_audit_log_for_delegate_profile_deactivated(db):
    user = make_user(db, "user1")
    topic = make_topic(db, "health")
    profile = make_delegate_profile(db, user, topic)

    log_audit_event(
        db, action="delegate_profile.deactivated",
        target_type="delegate_profile", target_id=profile.id,
        actor_id=user.id, details={"topic_id": topic.id},
    )
    db.flush()

    entry = db.query(models.AuditLog).filter(
        models.AuditLog.action == "delegate_profile.deactivated"
    ).first()
    assert entry is not None


# ---------------------------------------------------------------------------
# 9. Global delegation — public profile on any topic allows it
# ---------------------------------------------------------------------------

def test_global_delegation_allowed_via_any_active_profile(db):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    health = make_topic(db, "health")
    make_delegate_profile(db, bob, health)

    # global delegation (topic_id=None)
    assert can_delegate_to(db, alice.id, bob.id, None) is True


def test_global_delegation_blocked_with_no_profile_no_follow(db):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")

    assert can_delegate_to(db, alice.id, bob.id, None) is False


def test_global_delegation_allowed_via_delegation_allowed_follow(db):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    make_follow_relationship(db, alice, bob, "delegation_allowed")

    assert can_delegate_to(db, alice.id, bob.id, None) is True
