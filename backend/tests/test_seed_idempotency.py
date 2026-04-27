"""
Phase 7C.1 — Seed idempotency tests.

The seed helpers were refactored from "overwrite-on-existing" to "skip-if-
exists" so that the seed is safe to re-run additively on a populated DB.
These tests pin the new contract:

  - Re-running `_seed_demo` on a populated DB does not change row counts
    in users / votes / delegations / follows / delegate_profiles /
    topic_precedences.
  - A pre-existing visitor vote, delegation, follow, or precedence row
    survives a seed re-run unchanged (the seed must NEVER stomp on real
    visitor data).

Suite map:
  01: Double-run preserves row counts across all relevant tables.
  02: Pre-existing visitor vote on a seeded proposal survives re-run.
  03: Pre-existing visitor delegation survives re-run.
  04: Pre-existing visitor follow relationship survives re-run.
  05: Pre-existing topic precedence survives re-run (no mass-delete).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from database import Base
import models
from seed_data import _seed_demo


@pytest.fixture(scope="function")
def seed_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()

    # Reset the in-memory delegation graph so previous test runs don't pollute.
    from delegation_engine import graph_store
    graph_store._delegations.clear() if hasattr(graph_store, "_delegations") else None
    # graph_store may use different internals — best-effort reset.
    try:
        graph_store.clear()
    except Exception:
        pass

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def _row_counts(db: Session) -> dict[str, int]:
    return {
        "users": db.query(models.User).count(),
        "votes": db.query(models.Vote).count(),
        "delegations": db.query(models.Delegation).count(),
        "follow_relationships": db.query(models.FollowRelationship).count(),
        "delegate_profiles": db.query(models.DelegateProfile).count(),
        "topic_precedences": db.query(models.TopicPrecedence).count(),
        "proposals": db.query(models.Proposal).count(),
        "proposal_options": db.query(models.ProposalOption).count(),
        "topics": db.query(models.Topic).count(),
        "org_memberships": db.query(models.OrgMembership).count(),
    }


def test_01_seed_double_run_no_duplicates(seed_db):
    """Re-running _seed_demo on populated DB leaves all row counts unchanged."""
    _seed_demo(seed_db)
    first = _row_counts(seed_db)
    _seed_demo(seed_db)
    second = _row_counts(seed_db)

    assert first == second, (
        f"Seed re-run changed row counts.\n  first={first}\n  second={second}"
    )
    # Sanity: first run produced reasonable volume.
    assert first["users"] >= 25, f"Expected 25+ users, got {first['users']}"
    assert first["votes"] >= 60, f"Expected 60+ votes, got {first['votes']}"


def test_02_seed_preserves_visitor_vote(seed_db):
    """A vote cast on a seeded proposal between runs survives re-run unchanged."""
    _seed_demo(seed_db)

    # Find the Universal Healthcare proposal and a user who hasn't voted yet
    # on it (we'll cast a vote as them, then re-seed and assert preserved).
    healthcare_prop = seed_db.query(models.Proposal).filter(
        models.Proposal.title == "Universal Healthcare Coverage Act",
    ).one()
    # Pick a user with no existing vote on this proposal — frank fits.
    frank = seed_db.query(models.User).filter(models.User.username == "frank").one()
    existing = seed_db.query(models.Vote).filter(
        models.Vote.proposal_id == healthcare_prop.id,
        models.Vote.user_id == frank.id,
    ).first()
    assert existing is None, "frank should not already have voted on healthcare"

    # Cast a "visitor" vote.
    visitor_vote = models.Vote(
        proposal_id=healthcare_prop.id,
        user_id=frank.id,
        vote_value="abstain",
        is_direct=True,
        cast_by_id=frank.id,
    )
    seed_db.add(visitor_vote)
    seed_db.commit()
    visitor_vote_id = visitor_vote.id

    # Re-run the seed.
    _seed_demo(seed_db)
    seed_db.expire_all()

    # The visitor vote must still be there, with the original value.
    surviving = seed_db.query(models.Vote).filter(
        models.Vote.id == visitor_vote_id,
    ).one_or_none()
    assert surviving is not None, "visitor vote was deleted by seed re-run"
    assert surviving.vote_value == "abstain", (
        f"visitor vote value changed: {surviving.vote_value}"
    )
    assert surviving.user_id == frank.id


def test_03_seed_preserves_visitor_delegation(seed_db):
    """A delegation set between runs survives re-run unchanged."""
    _seed_demo(seed_db)

    # Frank doesn't have any seeded delegations. Use frank → carol on civil_rights.
    frank = seed_db.query(models.User).filter(models.User.username == "frank").one()
    carol = seed_db.query(models.User).filter(models.User.username == "carol").one()
    civil_rights = seed_db.query(models.Topic).filter(
        models.Topic.name == "Civil Rights",
    ).one()
    existing = seed_db.query(models.Delegation).filter(
        models.Delegation.delegator_id == frank.id,
        models.Delegation.topic_id == civil_rights.id,
    ).first()
    assert existing is None, "frank should not have a civil_rights delegation"

    visitor_del = models.Delegation(
        delegator_id=frank.id,
        delegate_id=carol.id,
        topic_id=civil_rights.id,
        chain_behavior="abstain",  # distinctive (seed default is accept_sub)
    )
    seed_db.add(visitor_del)
    seed_db.commit()
    del_id = visitor_del.id

    _seed_demo(seed_db)
    seed_db.expire_all()

    surviving = seed_db.query(models.Delegation).filter(
        models.Delegation.id == del_id,
    ).one_or_none()
    assert surviving is not None, "visitor delegation was deleted by seed re-run"
    assert surviving.delegate_id == carol.id
    assert surviving.chain_behavior == "abstain", (
        f"chain_behavior changed: {surviving.chain_behavior}"
    )


def test_04_seed_preserves_visitor_follow(seed_db):
    """A follow relationship created between runs survives re-run unchanged."""
    _seed_demo(seed_db)

    frank = seed_db.query(models.User).filter(models.User.username == "frank").one()
    rights_raj = seed_db.query(models.User).filter(
        models.User.username == "rights_raj",
    ).one()

    existing = seed_db.query(models.FollowRelationship).filter(
        models.FollowRelationship.follower_id == frank.id,
        models.FollowRelationship.followed_id == rights_raj.id,
    ).first()
    assert existing is None, "frank should not already follow rights_raj"

    visitor_follow = models.FollowRelationship(
        follower_id=frank.id,
        followed_id=rights_raj.id,
        permission_level="delegation_allowed",
    )
    seed_db.add(visitor_follow)
    seed_db.commit()
    fid = visitor_follow.id

    _seed_demo(seed_db)
    seed_db.expire_all()

    surviving = seed_db.query(models.FollowRelationship).filter(
        models.FollowRelationship.id == fid,
    ).one_or_none()
    assert surviving is not None, "visitor follow was deleted by seed re-run"
    assert surviving.permission_level == "delegation_allowed", (
        f"permission_level changed: {surviving.permission_level}"
    )


def test_05_seed_preserves_visitor_precedence(seed_db):
    """A topic precedence set between runs survives re-run.

    Phase 7C.1 trade-off: _set_precedence skips entirely if any precedence
    row exists for the user. This means a single visitor-set precedence
    blocks the seed from also adding seeded ones — but it preserves real
    visitor data, which is the never-overwrite priority.
    """
    _seed_demo(seed_db)

    # frank has no precedences in seed; assign him one and verify it survives.
    frank = seed_db.query(models.User).filter(models.User.username == "frank").one()
    existing = seed_db.query(models.TopicPrecedence).filter(
        models.TopicPrecedence.user_id == frank.id,
    ).first()
    assert existing is None, "frank should not have any precedences"

    healthcare = seed_db.query(models.Topic).filter(
        models.Topic.name == "Healthcare",
    ).one()
    visitor_prec = models.TopicPrecedence(
        user_id=frank.id,
        topic_id=healthcare.id,
        priority=42,  # distinctive value
    )
    seed_db.add(visitor_prec)
    seed_db.commit()
    pid = visitor_prec.id

    _seed_demo(seed_db)
    seed_db.expire_all()

    surviving = seed_db.query(models.TopicPrecedence).filter(
        models.TopicPrecedence.id == pid,
    ).one_or_none()
    assert surviving is not None, "visitor precedence was deleted by seed re-run"
    assert surviving.priority == 42, f"priority changed: {surviving.priority}"
