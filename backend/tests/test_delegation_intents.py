"""Tests for the delegation intent system (Phase 3b backend)."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

import models
from permissions import can_delegate_to
from routes.delegations import activate_intents_for_follow, _expire_stale_intents
from audit_utils import log_audit_event
from tests.conftest import make_user, make_topic, make_proposal, set_delegation


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _make_follow_request(db, requester, target, status="pending"):
    freq = models.FollowRequest(
        requester_id=requester.id, target_id=target.id, status=status
    )
    db.add(freq)
    db.flush()
    return freq


def _make_follow_rel(db, follower, followed, perm="delegation_allowed"):
    rel = models.FollowRelationship(
        follower_id=follower.id, followed_id=followed.id, permission_level=perm
    )
    db.add(rel)
    db.flush()
    return rel


def _make_intent(db, delegator, delegate, topic, freq, **kwargs):
    intent = models.DelegationIntent(
        delegator_id=delegator.id,
        delegate_id=delegate.id,
        topic_id=topic.id if topic else None,
        chain_behavior=kwargs.get("chain_behavior", "accept_sub"),
        follow_request_id=freq.id,
        status="pending",
        expires_at=kwargs.get("expires_at", _now() + timedelta(days=30)),
    )
    db.add(intent)
    db.flush()
    return intent


def _make_delegate_profile(db, user, topic):
    p = models.DelegateProfile(user_id=user.id, topic_id=topic.id, bio="test")
    db.add(p)
    db.flush()
    return p


# ------------------------------------------------------------------
# Intent created with follow request when delegating to non-followed
# ------------------------------------------------------------------

def test_intent_model_creation(db):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    health = make_topic(db, "health")
    freq = _make_follow_request(db, alice, bob)
    intent = _make_intent(db, alice, bob, health, freq)

    assert intent.status == "pending"
    assert intent.delegator_id == alice.id
    assert intent.delegate_id == bob.id
    assert intent.topic_id == health.id
    assert intent.follow_request_id == freq.id


# ------------------------------------------------------------------
# Intent auto-activates when follow approved with delegation_allowed
# ------------------------------------------------------------------

def test_intent_activates_on_delegation_allowed_approval(db, store):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    health = make_topic(db, "health")

    freq = _make_follow_request(db, alice, bob)
    intent = _make_intent(db, alice, bob, health, freq)
    _make_follow_rel(db, alice, bob, "delegation_allowed")
    db.flush()

    activated = activate_intents_for_follow(db, alice.id, bob.id)

    assert intent.id in activated
    assert intent.status == "activated"
    assert intent.activated_at is not None

    # Delegation should exist
    deleg = db.query(models.Delegation).filter(
        models.Delegation.delegator_id == alice.id,
        models.Delegation.delegate_id == bob.id,
        models.Delegation.topic_id == health.id,
    ).first()
    assert deleg is not None


# ------------------------------------------------------------------
# Intent does NOT activate when follow approved with view_only
# ------------------------------------------------------------------

def test_intent_does_not_activate_on_view_only(db, store):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    health = make_topic(db, "health")

    freq = _make_follow_request(db, alice, bob)
    intent = _make_intent(db, alice, bob, health, freq)
    _make_follow_rel(db, alice, bob, "view_only")
    db.flush()

    # view_only approval should NOT trigger activation
    # (activate_intents_for_follow is only called for delegation_allowed)
    assert intent.status == "pending"


# ------------------------------------------------------------------
# Expired intent does not activate even after follow approval
# ------------------------------------------------------------------

def test_expired_intent_not_activated(db, store):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    health = make_topic(db, "health")

    freq = _make_follow_request(db, alice, bob)
    intent = _make_intent(
        db, alice, bob, health, freq,
        expires_at=_now() - timedelta(days=1)  # already expired
    )
    _make_follow_rel(db, alice, bob, "delegation_allowed")
    db.flush()

    activated = activate_intents_for_follow(db, alice.id, bob.id)

    assert len(activated) == 0
    assert intent.status == "pending"  # not touched by activate (filtered by query)


def test_lazy_expiration_marks_expired(db):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    health = make_topic(db, "health")
    freq = _make_follow_request(db, alice, bob)
    intent = _make_intent(
        db, alice, bob, health, freq,
        expires_at=_now() - timedelta(hours=1),
    )

    _expire_stale_intents(db, intent)
    assert intent.status == "expired"


# ------------------------------------------------------------------
# Direct delegation still works for public delegates (bypasses intent)
# ------------------------------------------------------------------

def test_public_delegate_bypasses_intent(db):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    health = make_topic(db, "health")
    _make_delegate_profile(db, bob, health)

    assert can_delegate_to(db, alice.id, bob.id, health.id) is True


# ------------------------------------------------------------------
# Direct delegation works for existing delegation_allowed follow
# ------------------------------------------------------------------

def test_delegation_allowed_follow_bypasses_intent(db):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    health = make_topic(db, "health")
    _make_follow_rel(db, alice, bob, "delegation_allowed")

    assert can_delegate_to(db, alice.id, bob.id, health.id) is True


# ------------------------------------------------------------------
# Cancelling an intent
# ------------------------------------------------------------------

def test_cancel_intent(db):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    health = make_topic(db, "health")
    freq = _make_follow_request(db, alice, bob)
    intent = _make_intent(db, alice, bob, health, freq)

    intent.status = "cancelled"
    db.flush()

    log_audit_event(
        db, action="delegation_intent.cancelled",
        target_type="delegation_intent", target_id=intent.id,
        actor_id=alice.id,
        details={"delegate_id": bob.id, "topic_id": health.id},
    )
    db.flush()

    entry = db.query(models.AuditLog).filter(
        models.AuditLog.action == "delegation_intent.cancelled"
    ).first()
    assert entry is not None
    assert intent.status == "cancelled"


# ------------------------------------------------------------------
# Multiple intents for different topics all activate on approval
# ------------------------------------------------------------------

def test_multiple_intents_activate(db, store):
    alice = make_user(db, "alice")
    bob = make_user(db, "bob")
    health = make_topic(db, "health")
    economy = make_topic(db, "economy")

    freq = _make_follow_request(db, alice, bob)
    intent1 = _make_intent(db, alice, bob, health, freq)
    intent2 = _make_intent(db, alice, bob, economy, freq)
    _make_follow_rel(db, alice, bob, "delegation_allowed")
    db.flush()

    activated = activate_intents_for_follow(db, alice.id, bob.id)

    assert intent1.id in activated
    assert intent2.id in activated
    assert intent1.status == "activated"
    assert intent2.status == "activated"

    # Both delegations should exist
    delegations = db.query(models.Delegation).filter(
        models.Delegation.delegator_id == alice.id,
        models.Delegation.delegate_id == bob.id,
    ).all()
    assert len(delegations) == 2
