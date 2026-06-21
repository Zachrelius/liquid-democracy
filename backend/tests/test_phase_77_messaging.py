"""Phase 77 — org-scoped direct messaging (Stage 1 backend).

Covers the B0-8 checklist: conversation creation per type + gate, message
send (bidirectional, block, rate limit, sanitization, reopen), org inbox
(multi-admin, notification routing), unread count, block CRUD, org-scope
enforcement, and notification emission.
"""
from __future__ import annotations

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
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
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


def _user(db, username):
    u = models.User(
        username=username, display_name=username.title(), password_hash=_DUMMY_HASH,
        email=f"{username}@t.ex", email_verified=True,
    )
    db.add(u)
    db.flush()
    return u


def _org(db, slug, *, dm_policy="follow_only"):
    o = models.Organization(
        name=slug.title(), slug=slug, description="",
        settings={"member_dm_policy": dm_policy},
    )
    db.add(o)
    db.flush()
    seed_default_roles_for_org(db, o.id)
    return o


def _auth(user):
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _topic(db, org, name="General"):
    t = models.Topic(org_id=org.id, name=name)
    db.add(t)
    db.flush()
    return t


def _delegate_profile(db, user, topic, org, visibility):
    p = models.DelegateProfile(
        user_id=user.id, topic_id=topic.id, org_id=org.id, visibility=visibility,
    )
    db.add(p)
    db.flush()
    return p


def _follow(db, follower, followed, org):
    f = models.FollowRelationship(
        follower_id=follower.id, followed_id=followed.id, org_id=org.id,
        permission_level="view_only",
    )
    db.add(f)
    db.flush()
    return f


def _enable_in_app(db, user, event_type):
    db.add(models.NotificationPreference(
        user_id=user.id, event_type=event_type, channel="in_app", enabled=True,
    ))
    db.flush()


def _notif_count(db, user_id, event_type):
    return (
        db.query(models.Notification)
        .filter(
            models.Notification.user_id == user_id,
            models.Notification.event_type == event_type,
        )
        .count()
    )


# ===========================================================================
# Delegate conversations
# ===========================================================================

def test_delegate_public_any_member_can_message(client, test_db):
    org = _org(test_db, "o1")
    sender = _user(test_db, "sender")
    deleg = _user(test_db, "deleg")
    make_org_membership(test_db, org_id=org.id, user_id=sender.id, role="member")
    make_org_membership(test_db, org_id=org.id, user_id=deleg.id, role="member")
    t = _topic(test_db, org)
    _delegate_profile(test_db, deleg, t, org, "public")
    test_db.commit()

    r = client.post(f"/api/orgs/{org.slug}/conversations", headers=_auth(sender), json={
        "conversation_type": "delegate", "recipient_id": deleg.id, "body": "Hi delegate",
    })
    assert r.status_code == 201, r.text
    assert r.json()["conversation_type"] == "delegate"


def test_delegate_followers_only_requires_follow(client, test_db):
    org = _org(test_db, "o1")
    sender = _user(test_db, "sender")
    deleg = _user(test_db, "deleg")
    make_org_membership(test_db, org_id=org.id, user_id=sender.id, role="member")
    make_org_membership(test_db, org_id=org.id, user_id=deleg.id, role="member")
    t = _topic(test_db, org)
    _delegate_profile(test_db, deleg, t, org, "followers_only")
    test_db.commit()

    # No follow → rejected.
    r = client.post(f"/api/orgs/{org.slug}/conversations", headers=_auth(sender), json={
        "conversation_type": "delegate", "recipient_id": deleg.id, "body": "Hi",
    })
    assert r.status_code == 403, r.text

    # sender follows delegate → allowed.
    _follow(test_db, sender, deleg, org)
    test_db.commit()
    r = client.post(f"/api/orgs/{org.slug}/conversations", headers=_auth(sender), json={
        "conversation_type": "delegate", "recipient_id": deleg.id, "body": "Hi",
    })
    assert r.status_code == 201, r.text


def test_delegate_private_not_messageable(client, test_db):
    org = _org(test_db, "o1")
    sender = _user(test_db, "sender")
    deleg = _user(test_db, "deleg")
    make_org_membership(test_db, org_id=org.id, user_id=sender.id, role="member")
    make_org_membership(test_db, org_id=org.id, user_id=deleg.id, role="member")
    t = _topic(test_db, org)
    _delegate_profile(test_db, deleg, t, org, "private")
    test_db.commit()
    r = client.post(f"/api/orgs/{org.slug}/conversations", headers=_auth(sender), json={
        "conversation_type": "delegate", "recipient_id": deleg.id, "body": "Hi",
    })
    assert r.status_code == 403, r.text


def test_delegate_dm_disabled_ignored(client, test_db):
    """Delegate messages ignore the recipient's dm_disabled opt-out."""
    org = _org(test_db, "o1")
    sender = _user(test_db, "sender")
    deleg = _user(test_db, "deleg")
    deleg.dm_disabled = True
    make_org_membership(test_db, org_id=org.id, user_id=sender.id, role="member")
    make_org_membership(test_db, org_id=org.id, user_id=deleg.id, role="member")
    t = _topic(test_db, org)
    _delegate_profile(test_db, deleg, t, org, "public")
    test_db.commit()
    r = client.post(f"/api/orgs/{org.slug}/conversations", headers=_auth(sender), json={
        "conversation_type": "delegate", "recipient_id": deleg.id, "body": "Hi",
    })
    assert r.status_code == 201, r.text


# ===========================================================================
# Direct conversations
# ===========================================================================

def _two_members(test_db, dm_policy="follow_only"):
    org = _org(test_db, "o1", dm_policy=dm_policy)
    a = _user(test_db, "alice")
    b = _user(test_db, "bob")
    make_org_membership(test_db, org_id=org.id, user_id=a.id, role="member")
    make_org_membership(test_db, org_id=org.id, user_id=b.id, role="member")
    return org, a, b


def test_direct_disabled_policy_403(client, test_db):
    org, a, b = _two_members(test_db, dm_policy="disabled")
    test_db.commit()
    r = client.post(f"/api/orgs/{org.slug}/conversations", headers=_auth(a), json={
        "conversation_type": "direct", "recipient_id": b.id, "body": "Hi",
    })
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "dm_policy_disabled"


def test_direct_follow_only_forward_and_reverse(client, test_db):
    org, a, b = _two_members(test_db, dm_policy="follow_only")
    test_db.commit()
    # No follow → rejected.
    r = client.post(f"/api/orgs/{org.slug}/conversations", headers=_auth(a), json={
        "conversation_type": "direct", "recipient_id": b.id, "body": "Hi",
    })
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "follow_required"
    # Reverse follow (b follows a) is sufficient for a to message b.
    _follow(test_db, b, a, org)
    test_db.commit()
    r = client.post(f"/api/orgs/{org.slug}/conversations", headers=_auth(a), json={
        "conversation_type": "direct", "recipient_id": b.id, "body": "Hi",
    })
    assert r.status_code == 201, r.text


def test_direct_open_policy_no_follow_ok(client, test_db):
    org, a, b = _two_members(test_db, dm_policy="open")
    test_db.commit()
    r = client.post(f"/api/orgs/{org.slug}/conversations", headers=_auth(a), json={
        "conversation_type": "direct", "recipient_id": b.id, "body": "Hi",
    })
    assert r.status_code == 201, r.text


def test_direct_recipient_dm_disabled_403(client, test_db):
    org, a, b = _two_members(test_db, dm_policy="open")
    b.dm_disabled = True
    test_db.commit()
    r = client.post(f"/api/orgs/{org.slug}/conversations", headers=_auth(a), json={
        "conversation_type": "direct", "recipient_id": b.id, "body": "Hi",
    })
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "recipient_unavailable"


def test_direct_block_generic_error(client, test_db):
    org, a, b = _two_members(test_db, dm_policy="open")
    # b blocks a.
    test_db.add(models.MessageBlock(blocker_id=b.id, blocked_id=a.id, org_id=org.id))
    test_db.commit()
    r = client.post(f"/api/orgs/{org.slug}/conversations", headers=_auth(a), json={
        "conversation_type": "direct", "recipient_id": b.id, "body": "Hi",
    })
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "unable_to_send"


def test_direct_dedup_both_orderings(client, test_db):
    org, a, b = _two_members(test_db, dm_policy="open")
    test_db.commit()
    r1 = client.post(f"/api/orgs/{org.slug}/conversations", headers=_auth(a), json={
        "conversation_type": "direct", "recipient_id": b.id, "body": "from a",
    })
    cid = r1.json()["id"]
    # b initiating to a resolves to the same conversation.
    r2 = client.post(f"/api/orgs/{org.slug}/conversations", headers=_auth(b), json={
        "conversation_type": "direct", "recipient_id": a.id, "body": "from b",
    })
    assert r2.status_code in (200, 201), r2.text
    assert r2.json()["id"] == cid


# ===========================================================================
# Message sending
# ===========================================================================

def _open_direct(client, test_db):
    org, a, b = _two_members(test_db, dm_policy="open")
    test_db.commit()
    r = client.post(f"/api/orgs/{org.slug}/conversations", headers=_auth(a), json={
        "conversation_type": "direct", "recipient_id": b.id, "body": "hello",
    })
    return org, a, b, r.json()["id"]


def test_both_participants_can_send(client, test_db):
    org, a, b, cid = _open_direct(client, test_db)
    # Recipient b replies.
    r = client.post(f"/api/orgs/{org.slug}/conversations/{cid}/messages", headers=_auth(b), json={"body": "reply"})
    assert r.status_code == 201, r.text


def test_block_prevents_send_in_existing_conversation(client, test_db):
    org, a, b, cid = _open_direct(client, test_db)
    # b blocks a; a can no longer send into the existing conversation.
    test_db.add(models.MessageBlock(blocker_id=b.id, blocked_id=a.id, org_id=org.id))
    test_db.commit()
    r = client.post(f"/api/orgs/{org.slug}/conversations/{cid}/messages", headers=_auth(a), json={"body": "still there?"})
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "unable_to_send"
    # b (the blocker) can still send.
    r2 = client.post(f"/api/orgs/{org.slug}/conversations/{cid}/messages", headers=_auth(b), json={"body": "go away"})
    assert r2.status_code == 201


def test_rate_limit_fires(client, test_db):
    org, a, b, cid = _open_direct(client, test_db)  # message #1
    # 19 more sends reach 20 total; the next is blocked.
    for i in range(19):
        r = client.post(f"/api/orgs/{org.slug}/conversations/{cid}/messages", headers=_auth(a), json={"body": f"m{i}"})
        assert r.status_code == 201, (i, r.text)
    r = client.post(f"/api/orgs/{org.slug}/conversations/{cid}/messages", headers=_auth(a), json={"body": "over"})
    assert r.status_code == 429, r.text


def test_body_sanitized(client, test_db):
    org, a, b, cid = _open_direct(client, test_db)
    r = client.post(f"/api/orgs/{org.slug}/conversations/{cid}/messages", headers=_auth(a),
                    json={"body": "<script>alert(1)</script>safe"})
    assert r.status_code == 201, r.text
    assert "<script>" not in r.json()["body"]
    assert "safe" in r.json()["body"]


def test_send_reopens_closed(client, test_db):
    org, a, b, cid = _open_direct(client, test_db)
    rc = client.post(f"/api/orgs/{org.slug}/conversations/{cid}/close", headers=_auth(a))
    assert rc.status_code == 200
    assert rc.json()["status"] == "closed"
    client.post(f"/api/orgs/{org.slug}/conversations/{cid}/messages", headers=_auth(b), json={"body": "back"})
    detail = client.get(f"/api/orgs/{org.slug}/conversations/{cid}", headers=_auth(b)).json()
    assert detail["conversation"]["status"] == "active"


def test_last_message_at_updated(client, test_db):
    org, a, b, cid = _open_direct(client, test_db)
    detail = client.get(f"/api/orgs/{org.slug}/conversations/{cid}", headers=_auth(a)).json()
    assert detail["conversation"]["last_message_at"] is not None


# ===========================================================================
# Org inbox
# ===========================================================================

def _org_with_admins(test_db):
    org = _org(test_db, "o1")
    member = _user(test_db, "member1")
    steward = _user(test_db, "steward1")
    admin = _user(test_db, "admin1")
    make_org_membership(test_db, org_id=org.id, user_id=member.id, role="member")
    make_org_membership(test_db, org_id=org.id, user_id=steward.id, role="steward")
    make_org_membership(test_db, org_id=org.id, user_id=admin.id, role="admin")
    return org, member, steward, admin


def test_org_inbox_create_and_multi_admin_visibility(client, test_db):
    org, member, steward, admin = _org_with_admins(test_db)
    test_db.commit()
    r = client.post(f"/api/orgs/{org.slug}/conversations", headers=_auth(member), json={
        "conversation_type": "org_inbox", "body": "Hello leadership",
    })
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    # Both steward and admin see it in the org inbox.
    for u in (steward, admin):
        inbox = client.get(f"/api/orgs/{org.slug}/org-inbox", headers=_auth(u))
        assert inbox.status_code == 200, inbox.text
        assert any(c["id"] == cid for c in inbox.json())
    # Plain member cannot view the org inbox.
    assert client.get(f"/api/orgs/{org.slug}/org-inbox", headers=_auth(member)).status_code == 403


def test_org_inbox_dedup_reopen(client, test_db):
    org, member, steward, admin = _org_with_admins(test_db)
    test_db.commit()
    r1 = client.post(f"/api/orgs/{org.slug}/conversations", headers=_auth(member), json={
        "conversation_type": "org_inbox", "body": "first",
    })
    cid = r1.json()["id"]
    client.post(f"/api/orgs/{org.slug}/conversations/{cid}/close", headers=_auth(steward))
    # Same member messaging again reopens the same thread.
    r2 = client.post(f"/api/orgs/{org.slug}/conversations", headers=_auth(member), json={
        "conversation_type": "org_inbox", "body": "again",
    })
    assert r2.json()["id"] == cid
    assert r2.json()["status"] == "active"


def test_org_inbox_notification_routing(client, test_db):
    org, member, steward, admin = _org_with_admins(test_db)
    _enable_in_app(test_db, steward, "message.org_inbox")
    _enable_in_app(test_db, admin, "message.org_inbox")
    _enable_in_app(test_db, member, "message.received")
    test_db.commit()

    r = client.post(f"/api/orgs/{org.slug}/conversations", headers=_auth(member), json={
        "conversation_type": "org_inbox", "body": "help please",
    })
    cid = r.json()["id"]
    # Initiator's message → org_inbox notification to both admins, not member.
    assert _notif_count(test_db, steward.id, "message.org_inbox") == 1
    assert _notif_count(test_db, admin.id, "message.org_inbox") == 1
    assert _notif_count(test_db, member.id, "message.org_inbox") == 0

    # Admin reply → message.received to the initiator, NOT message.org_inbox.
    client.post(f"/api/orgs/{org.slug}/conversations/{cid}/messages", headers=_auth(steward), json={"body": "on it"})
    assert _notif_count(test_db, member.id, "message.received") == 1
    # No new org_inbox notif from the admin reply.
    assert _notif_count(test_db, admin.id, "message.org_inbox") == 1


def test_direct_message_notification(client, test_db):
    org, a, b = _two_members(test_db, dm_policy="open")
    _enable_in_app(test_db, b, "message.received")
    test_db.commit()
    client.post(f"/api/orgs/{org.slug}/conversations", headers=_auth(a), json={
        "conversation_type": "direct", "recipient_id": b.id, "body": "hi",
    })
    assert _notif_count(test_db, b.id, "message.received") == 1
    # Sender does not get notified of their own message.
    assert _notif_count(test_db, a.id, "message.received") == 0


# ===========================================================================
# Unread count
# ===========================================================================

def test_unread_count(client, test_db):
    org, a, b, cid = _open_direct(client, test_db)  # a sent "hello"
    # b has 1 unread (a's message); a has 0 (own message).
    assert client.get(f"/api/orgs/{org.slug}/messages/unread-count", headers=_auth(b)).json()["unread_count"] == 1
    assert client.get(f"/api/orgs/{org.slug}/messages/unread-count", headers=_auth(a)).json()["unread_count"] == 0
    # b reads → 0.
    client.post(f"/api/orgs/{org.slug}/conversations/{cid}/read", headers=_auth(b))
    assert client.get(f"/api/orgs/{org.slug}/messages/unread-count", headers=_auth(b)).json()["unread_count"] == 0
    # a sends another → b has 1 again.
    client.post(f"/api/orgs/{org.slug}/conversations/{cid}/messages", headers=_auth(a), json={"body": "again"})
    assert client.get(f"/api/orgs/{org.slug}/messages/unread-count", headers=_auth(b)).json()["unread_count"] == 1


def test_get_conversation_marks_read(client, test_db):
    org, a, b, cid = _open_direct(client, test_db)
    client.get(f"/api/orgs/{org.slug}/conversations/{cid}", headers=_auth(b))
    assert client.get(f"/api/orgs/{org.slug}/messages/unread-count", headers=_auth(b)).json()["unread_count"] == 0


# ===========================================================================
# Blocks CRUD
# ===========================================================================

def test_block_crud(client, test_db):
    org, a, b = _two_members(test_db, dm_policy="open")
    test_db.commit()
    r = client.post(f"/api/orgs/{org.slug}/message-blocks", headers=_auth(a), json={"blocked_id": b.id})
    assert r.status_code == 201, r.text
    # Duplicate → 409.
    assert client.post(f"/api/orgs/{org.slug}/message-blocks", headers=_auth(a), json={"blocked_id": b.id}).status_code == 409
    # Listed.
    assert any(x["blocked_id"] == b.id for x in client.get(f"/api/orgs/{org.slug}/message-blocks", headers=_auth(a)).json())
    # Unblock.
    assert client.delete(f"/api/orgs/{org.slug}/message-blocks/{b.id}", headers=_auth(a)).status_code == 204
    # Re-block works.
    assert client.post(f"/api/orgs/{org.slug}/message-blocks", headers=_auth(a), json={"blocked_id": b.id}).status_code == 201


def test_dm_disabled_via_me_endpoint(client, test_db):
    """PATCH /api/auth/me persists dm_disabled and UserOut surfaces it;
    a direct-message initiation to that user is then blocked."""
    org, a, b = _two_members(test_db, dm_policy="open")
    test_db.commit()
    # b opts out of DMs via the account endpoint.
    r = client.patch("/api/auth/me", headers=_auth(b), json={"dm_disabled": True})
    assert r.status_code == 200, r.text
    assert r.json()["dm_disabled"] is True
    # a can no longer start a DM with b.
    r2 = client.post(f"/api/orgs/{org.slug}/conversations", headers=_auth(a), json={
        "conversation_type": "direct", "recipient_id": b.id, "body": "hi",
    })
    assert r2.status_code == 403
    assert r2.json()["detail"]["error"] == "recipient_unavailable"


def test_cannot_block_self(client, test_db):
    org, a, b = _two_members(test_db, dm_policy="open")
    test_db.commit()
    assert client.post(f"/api/orgs/{org.slug}/message-blocks", headers=_auth(a), json={"blocked_id": a.id}).status_code == 400


# ===========================================================================
# Org-scope enforcement + fresh-org permission grant
# ===========================================================================

def test_non_member_cannot_list_or_read(client, test_db):
    org, a, b, cid = _open_direct(client, test_db)
    outsider = _user(test_db, "outsider")
    test_db.commit()
    # Not a member → 404 (org hidden).
    assert client.get(f"/api/orgs/{org.slug}/conversations", headers=_auth(outsider)).status_code == 404
    assert client.get(f"/api/orgs/{org.slug}/conversations/{cid}", headers=_auth(outsider)).status_code == 404


def test_member_not_participant_cannot_read(client, test_db):
    org, a, b, cid = _open_direct(client, test_db)
    third = _user(test_db, "third")
    make_org_membership(test_db, org_id=org.id, user_id=third.id, role="member")
    test_db.commit()
    # Member of the org but not a participant in this direct conversation → 403.
    assert client.get(f"/api/orgs/{org.slug}/conversations/{cid}", headers=_auth(third)).status_code == 403


def test_fresh_org_steward_admin_have_org_inbox_view(client, test_db):
    """DEFAULT_GRANTS path: a freshly-seeded org's steward + admin can view
    the inbox (the migration backfill covers the existing-org population —
    see test_phase_77_migration_cycle)."""
    org, member, steward, admin = _org_with_admins(test_db)
    test_db.commit()
    from role_permissions import has_permission
    assert has_permission(test_db, steward.id, org.id, "org_inbox.view")
    assert has_permission(test_db, admin.id, org.id, "org_inbox.view")
    assert not has_permission(test_db, member.id, org.id, "org_inbox.view")
