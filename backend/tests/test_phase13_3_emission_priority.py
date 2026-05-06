"""Phase 13.3 §B3 — proposal-entered-voting priority resolution +
single-notification-per-recipient invariant tests.

Four core cases (per spec §B7):
  1. Recipient is a delegate-target AND opted into all three voting
     events => receives delegated_to_you only.
  2. Recipient has delegated away AND opted into all three => receives
     proposal.entered_voting (generic) — NOT you_vote (they delegated)
     and NOT delegated_to_you (no one delegated to them).
  3. Recipient is opted ONLY into proposal.entered_voting (legacy
     behavior) => receives the generic event regardless of delegation
     state.
  4. Recipient is opted into NONE of the three voting events => no
     notification.

Plus:
  * Single-notification-per-recipient invariant: no recipient receives
    more than one notification per advance trigger, even when opted into
    all three.
  * Topicless proposals: delegated_to_you never fires; you_vote applies
    to all opted-in recipients.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from database import Base, get_db
from main import app
from role_seed import seed_default_roles_for_org
from tests.conftest import make_org_membership


_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


@pytest.fixture(scope="function")
def test_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def client(test_db: Session):
    def _get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _make_user(db: Session, username: str) -> models.User:
    u = models.User(
        username=username, display_name=username,
        password_hash=_DUMMY_HASH,
        email=f"{username}@test.example",
        email_verified=True,
    )
    db.add(u)
    db.flush()
    return u


def _make_org(db: Session, slug: str) -> models.Organization:
    o = models.Organization(name=slug.title(), slug=slug, description="", settings={})
    db.add(o)
    db.flush()
    seed_default_roles_for_org(db, o.id)
    return o


def _auth(user: models.User) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _opt_in_all_voting_events(db: Session, user: models.User) -> None:
    """Opt user into in_app for all three voting-opened events."""
    for ev in (
        "proposal.entered_voting",
        "proposal.entered_voting.you_vote",
        "proposal.entered_voting.delegated_to_you",
    ):
        db.add(models.NotificationPreference(
            user_id=user.id, event_type=ev,
            channel="in_app", enabled=True,
        ))
    db.flush()


def _opt_in(db: Session, user: models.User, event_type: str) -> None:
    db.add(models.NotificationPreference(
        user_id=user.id, event_type=event_type,
        channel="in_app", enabled=True,
    ))
    db.flush()


def _make_topic(db: Session, org: models.Organization, name: str) -> models.Topic:
    t = models.Topic(org_id=org.id, name=f"{org.slug}-{name}", description="")
    db.add(t)
    db.flush()
    return t


def _make_proposal_with_topic(
    db: Session, author: models.User, org: models.Organization,
    topic: models.Topic | None = None, *, status: str = "deliberation",
) -> models.Proposal:
    p = models.Proposal(
        title="Voting test", body="Body",
        author_id=author.id, org_id=org.id, status=status,
        voting_method="binary",
    )
    db.add(p)
    db.flush()
    if topic is not None:
        db.add(models.ProposalTopic(proposal_id=p.id, topic_id=topic.id, relevance=1.0))
        db.flush()
    return p


def _delegate(
    db: Session, *, delegator: models.User, delegate_user: models.User,
    topic: models.Topic | None,
) -> None:
    db.add(models.Delegation(
        delegator_id=delegator.id, delegate_id=delegate_user.id,
        topic_id=topic.id if topic else None,
    ))
    db.flush()


def _notifs_for(
    db: Session, user: models.User, event_type: str | None = None,
) -> list[models.Notification]:
    q = db.query(models.Notification).filter(
        models.Notification.user_id == user.id,
    )
    if event_type:
        q = q.filter(models.Notification.event_type == event_type)
    return q.all()


# ---------------------------------------------------------------------------
# Case 1: delegate-target + opted into all three => delegated_to_you only
# ---------------------------------------------------------------------------

def test_priority_case_1_delegate_target_gets_delegated_to_you(client, test_db):
    org = _make_org(test_db, "p131")
    author = _make_user(test_db, "p131_author")
    target = _make_user(test_db, "p131_target")  # someone delegates TO this user
    delegator = _make_user(test_db, "p131_delegator")
    make_org_membership(test_db, org_id=org.id, user_id=author.id, role="admin")
    make_org_membership(test_db, org_id=org.id, user_id=target.id, role="member")
    make_org_membership(test_db, org_id=org.id, user_id=delegator.id, role="member")

    topic = _make_topic(test_db, org, "budget")
    _delegate(test_db, delegator=delegator, delegate_user=target, topic=topic)
    proposal = _make_proposal_with_topic(test_db, author, org, topic=topic, status="deliberation")
    _opt_in_all_voting_events(test_db, target)
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/proposals/{proposal.id}/advance",
        json={}, headers=_auth(author),
    )
    assert resp.status_code == 200, resp.text

    rows = _notifs_for(test_db, target)
    # Single-notification-per-recipient invariant.
    assert len(rows) == 1, [r.event_type for r in rows]
    assert rows[0].event_type == "proposal.entered_voting.delegated_to_you"


# ---------------------------------------------------------------------------
# Case 2: has delegated away + opted into all three => generic event
# ---------------------------------------------------------------------------

def test_priority_case_2_delegated_away_gets_generic(client, test_db):
    org = _make_org(test_db, "p132")
    author = _make_user(test_db, "p132_author")
    delegator = _make_user(test_db, "p132_dgtr")  # has delegated away
    delegate_user = _make_user(test_db, "p132_dgte")
    make_org_membership(test_db, org_id=org.id, user_id=author.id, role="admin")
    make_org_membership(test_db, org_id=org.id, user_id=delegator.id, role="member")
    make_org_membership(test_db, org_id=org.id, user_id=delegate_user.id, role="member")

    topic = _make_topic(test_db, org, "policy")
    _delegate(test_db, delegator=delegator, delegate_user=delegate_user, topic=topic)
    proposal = _make_proposal_with_topic(test_db, author, org, topic=topic, status="deliberation")
    _opt_in_all_voting_events(test_db, delegator)
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/proposals/{proposal.id}/advance",
        json={}, headers=_auth(author),
    )
    assert resp.status_code == 200, resp.text

    rows = _notifs_for(test_db, delegator)
    assert len(rows) == 1, [r.event_type for r in rows]
    assert rows[0].event_type == "proposal.entered_voting"


# ---------------------------------------------------------------------------
# Case 3: opted only into proposal.entered_voting => generic event
# ---------------------------------------------------------------------------

def test_priority_case_3_opted_only_into_generic(client, test_db):
    org = _make_org(test_db, "p133")
    author = _make_user(test_db, "p133_author")
    voter = _make_user(test_db, "p133_voter")
    make_org_membership(test_db, org_id=org.id, user_id=author.id, role="admin")
    make_org_membership(test_db, org_id=org.id, user_id=voter.id, role="member")

    topic = _make_topic(test_db, org, "topic_gen")
    proposal = _make_proposal_with_topic(test_db, author, org, topic=topic, status="deliberation")
    _opt_in(test_db, voter, "proposal.entered_voting")
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/proposals/{proposal.id}/advance",
        json={}, headers=_auth(author),
    )
    assert resp.status_code == 200, resp.text

    rows = _notifs_for(test_db, voter)
    assert len(rows) == 1
    assert rows[0].event_type == "proposal.entered_voting"


# ---------------------------------------------------------------------------
# Case 4: opted into NONE => no notification
# ---------------------------------------------------------------------------

def test_priority_case_4_opted_into_nothing(client, test_db):
    org = _make_org(test_db, "p134")
    author = _make_user(test_db, "p134_author")
    voter = _make_user(test_db, "p134_voter")
    make_org_membership(test_db, org_id=org.id, user_id=author.id, role="admin")
    make_org_membership(test_db, org_id=org.id, user_id=voter.id, role="member")

    topic = _make_topic(test_db, org, "topic_none")
    proposal = _make_proposal_with_topic(test_db, author, org, topic=topic, status="deliberation")
    # No opt-ins.
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/proposals/{proposal.id}/advance",
        json={}, headers=_auth(author),
    )
    assert resp.status_code == 200, resp.text

    rows = _notifs_for(test_db, voter)
    assert rows == []


# ---------------------------------------------------------------------------
# Single-notification-per-recipient invariant — exhaustive
# ---------------------------------------------------------------------------

def test_single_notification_per_recipient_three_audiences(client, test_db):
    """Three users with different delegation states, all opted into all
    three voting events, all receive at most ONE notification each."""
    org = _make_org(test_db, "p135")
    author = _make_user(test_db, "p135_author")
    target = _make_user(test_db, "p135_target")     # delegate-target
    delegator = _make_user(test_db, "p135_dgtr")    # has delegated away
    plain = _make_user(test_db, "p135_plain")       # no delegation
    make_org_membership(test_db, org_id=org.id, user_id=author.id, role="admin")
    make_org_membership(test_db, org_id=org.id, user_id=target.id, role="member")
    make_org_membership(test_db, org_id=org.id, user_id=delegator.id, role="member")
    make_org_membership(test_db, org_id=org.id, user_id=plain.id, role="member")

    topic = _make_topic(test_db, org, "topic_inv")
    _delegate(test_db, delegator=delegator, delegate_user=target, topic=topic)
    proposal = _make_proposal_with_topic(test_db, author, org, topic=topic, status="deliberation")

    for u in (target, delegator, plain):
        _opt_in_all_voting_events(test_db, u)
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/proposals/{proposal.id}/advance",
        json={}, headers=_auth(author),
    )
    assert resp.status_code == 200, resp.text

    target_rows = _notifs_for(test_db, target)
    delegator_rows = _notifs_for(test_db, delegator)
    plain_rows = _notifs_for(test_db, plain)

    # Exactly one notification each.
    assert len(target_rows) == 1
    assert len(delegator_rows) == 1
    assert len(plain_rows) == 1

    # Correct event for each delegation state.
    assert target_rows[0].event_type == "proposal.entered_voting.delegated_to_you"
    assert delegator_rows[0].event_type == "proposal.entered_voting"
    assert plain_rows[0].event_type == "proposal.entered_voting.you_vote"


def test_topicless_proposal_emits_you_vote_when_opted_in(client, test_db):
    """Topicless proposals: delegated_to_you never fires (no topic to
    scope on). Recipients get you_vote if opted in."""
    org = _make_org(test_db, "p136")
    author = _make_user(test_db, "p136_author")
    voter = _make_user(test_db, "p136_voter")
    make_org_membership(test_db, org_id=org.id, user_id=author.id, role="admin")
    make_org_membership(test_db, org_id=org.id, user_id=voter.id, role="member")

    proposal = _make_proposal_with_topic(test_db, author, org, topic=None, status="deliberation")
    _opt_in_all_voting_events(test_db, voter)
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/proposals/{proposal.id}/advance",
        json={}, headers=_auth(author),
    )
    assert resp.status_code == 200, resp.text

    rows = _notifs_for(test_db, voter)
    assert len(rows) == 1
    # Topicless proposals: no delegated_to_you possible; you_vote wins.
    assert rows[0].event_type == "proposal.entered_voting.you_vote"


# ---------------------------------------------------------------------------
# user_has_any_channel_enabled helper
# ---------------------------------------------------------------------------

def test_user_has_any_channel_enabled_helper(test_db):
    from notification_emit import user_has_any_channel_enabled

    user = _make_user(test_db, "uhace")
    test_db.commit()

    # Default: no rows -> False.
    assert user_has_any_channel_enabled(
        test_db, user.id, "comment.replied",
    ) is False

    # Add a disabled row -> still False.
    test_db.add(models.NotificationPreference(
        user_id=user.id, event_type="comment.replied",
        channel="in_app", enabled=False,
    ))
    test_db.flush()
    assert user_has_any_channel_enabled(
        test_db, user.id, "comment.replied",
    ) is False

    # Enable it -> True.
    row = test_db.query(models.NotificationPreference).filter(
        models.NotificationPreference.user_id == user.id,
    ).first()
    row.enabled = True
    test_db.flush()
    assert user_has_any_channel_enabled(
        test_db, user.id, "comment.replied",
    ) is True

    # Test all four channels.
    for ch in ("email_immediate", "email_daily", "email_weekly"):
        u2 = _make_user(test_db, f"uhace_{ch}")
        test_db.add(models.NotificationPreference(
            user_id=u2.id, event_type="follow.requested",
            channel=ch, enabled=True,
        ))
        test_db.flush()
        assert user_has_any_channel_enabled(
            test_db, u2.id, "follow.requested",
        ) is True
