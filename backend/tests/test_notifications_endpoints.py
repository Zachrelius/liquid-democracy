"""Phase 13 — backend Cluster B endpoint tests.

Covers:
  - GET /api/notifications: empty, with rows, ?unread filter, pagination,
    Item 22 routing (org_slug resolution).
  - POST /api/notifications/{id}/read: happy path, idempotent, 404 on
    cross-user attempts.
  - POST /api/notifications/mark-all-read.
  - GET /api/notifications/preferences: default-state (all-False), shape.
  - PATCH /api/notifications/preferences: partial update + audit log
    entry + validation (unknown event_type, bad cadence).
  - GET /api/notifications/registry: 12 entries with metadata.

Plus:
  - cleanup_expired_notifications(db) deletes 90+ day rows.
  - emit_notification: opt-in default = no in_app row inserted; with
    pref enabled = row inserted with the right shape; quiet hours
    suppress real-time email (in_app still inserted).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import BackgroundTasks
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from database import Base, get_db
from main import app
from notification_emit import (
    cleanup_expired_notifications,
    emit_notification,
)
from notification_events import EVENT_REGISTRY
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
        username=username,
        display_name=username,
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


def _make_notification(
    db: Session,
    *,
    user_id: str,
    event_type: str = "comment.replied",
    org_id: str | None = None,
    actor_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    payload: dict | None = None,
    read_at: datetime | None = None,
    created_at: datetime | None = None,
) -> models.Notification:
    n = models.Notification(
        user_id=user_id,
        event_type=event_type,
        org_id=org_id,
        actor_id=actor_id,
        target_type=target_type,
        target_id=target_id,
        payload=payload,
        read_at=read_at,
        created_at=created_at or datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(n)
    db.flush()
    return n


# ---------------------------------------------------------------------------
# GET /api/notifications
# ---------------------------------------------------------------------------

def test_get_notifications_empty_when_no_rows(client, test_db):
    user = _make_user(test_db, "no_notifs_user")
    test_db.commit()

    resp = client.get("/api/notifications", headers=_auth(user))
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["has_more"] is False
    assert body["next_offset"] is None


def test_get_notifications_returns_rows_newest_first(client, test_db):
    user = _make_user(test_db, "feed_user")
    older = _make_notification(
        test_db, user_id=user.id, event_type="comment.replied",
        created_at=datetime(2026, 5, 1, 12, 0, 0),
    )
    newer = _make_notification(
        test_db, user_id=user.id, event_type="follow.requested",
        created_at=datetime(2026, 5, 4, 12, 0, 0),
    )
    test_db.commit()

    resp = client.get("/api/notifications", headers=_auth(user))
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 2
    assert items[0]["id"] == newer.id
    assert items[1]["id"] == older.id


def test_get_notifications_unread_filter(client, test_db):
    user = _make_user(test_db, "unread_user")
    read_row = _make_notification(
        test_db, user_id=user.id, read_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    unread_row = _make_notification(test_db, user_id=user.id, event_type="follow.requested")
    test_db.commit()

    resp = client.get("/api/notifications?unread=true", headers=_auth(user))
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == unread_row.id


def test_get_notifications_pagination(client, test_db):
    user = _make_user(test_db, "page_user")
    rows = []
    for i in range(5):
        rows.append(_make_notification(
            test_db, user_id=user.id,
            created_at=datetime(2026, 5, 1, 12, 0, 0) + timedelta(minutes=i),
        ))
    test_db.commit()

    # Limit 2: should see has_more=True and 2 items.
    resp = client.get("/api/notifications?limit=2&offset=0", headers=_auth(user))
    body = resp.json()
    assert len(body["items"]) == 2
    assert body["has_more"] is True
    assert body["next_offset"] == 2

    # Last page: limit 2, offset 4 — only 1 item, no more.
    resp = client.get("/api/notifications?limit=2&offset=4", headers=_auth(user))
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["has_more"] is False


def test_get_notifications_isolates_per_user(client, test_db):
    """A user only sees their own notifications, never another user's."""
    me = _make_user(test_db, "iso_me")
    them = _make_user(test_db, "iso_them")
    _make_notification(test_db, user_id=me.id, event_type="comment.replied")
    _make_notification(test_db, user_id=them.id, event_type="follow.requested")
    test_db.commit()

    resp = client.get("/api/notifications", headers=_auth(me))
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["event_type"] == "comment.replied"


def test_get_notifications_resolves_org_slug_for_routing_item22(client, test_db):
    """Item 22 resolution: a notification with org_id set surfaces
    org_slug in the response so the frontend routes to the correct org
    rather than 'first parent org'."""
    user = _make_user(test_db, "item22_user")
    org_a = _make_org(test_db, "gamenights")
    org_b = _make_org(test_db, "gloomhaven")
    make_org_membership(test_db, org_id=org_a.id, user_id=user.id, role="member")
    make_org_membership(test_db, org_id=org_b.id, user_id=user.id, role="member")
    n_b = _make_notification(
        test_db, user_id=user.id, event_type="comment.replied",
        org_id=org_b.id, target_type="proposal", target_id="some-proposal-id",
    )
    test_db.commit()

    resp = client.get("/api/notifications", headers=_auth(user))
    items = resp.json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item["id"] == n_b.id
    assert item["org_id"] == org_b.id
    # Critical: org_slug resolves to gloomhaven, NOT gamenights (the
    # legacy "first parent org" bug).
    assert item["org_slug"] == "gloomhaven"


def test_get_notifications_account_level_has_null_slug(client, test_db):
    """Account-level events (org_id=None) carry org_slug=None."""
    user = _make_user(test_db, "account_lvl_user")
    _make_notification(test_db, user_id=user.id, event_type="follow.approved", org_id=None)
    test_db.commit()

    resp = client.get("/api/notifications", headers=_auth(user))
    item = resp.json()["items"][0]
    assert item["org_id"] is None
    assert item["org_slug"] is None


# ---------------------------------------------------------------------------
# POST /api/notifications/{id}/read
# ---------------------------------------------------------------------------

def test_mark_read_happy_path(client, test_db):
    user = _make_user(test_db, "mr_user")
    n = _make_notification(test_db, user_id=user.id)
    test_db.commit()
    assert n.read_at is None

    resp = client.post(f"/api/notifications/{n.id}/read", headers=_auth(user))
    assert resp.status_code == 204

    test_db.refresh(n)
    assert n.read_at is not None


def test_mark_read_idempotent(client, test_db):
    user = _make_user(test_db, "mr_idem_user")
    n = _make_notification(test_db, user_id=user.id)
    test_db.commit()

    resp1 = client.post(f"/api/notifications/{n.id}/read", headers=_auth(user))
    assert resp1.status_code == 204
    test_db.refresh(n)
    first_read = n.read_at
    assert first_read is not None

    # Second call: still 204; read_at unchanged.
    resp2 = client.post(f"/api/notifications/{n.id}/read", headers=_auth(user))
    assert resp2.status_code == 204
    test_db.refresh(n)
    assert n.read_at == first_read


def test_mark_read_cant_mark_another_users(client, test_db):
    """A user cannot mark another user's notification read — returns 404
    (not 403, to avoid leaking the existence of a foreign id)."""
    me = _make_user(test_db, "mark_me")
    them = _make_user(test_db, "mark_them")
    foreign = _make_notification(test_db, user_id=them.id)
    test_db.commit()

    resp = client.post(f"/api/notifications/{foreign.id}/read", headers=_auth(me))
    assert resp.status_code == 404
    test_db.refresh(foreign)
    assert foreign.read_at is None


def test_mark_read_404_unknown_id(client, test_db):
    user = _make_user(test_db, "mr_404")
    test_db.commit()

    resp = client.post("/api/notifications/no-such-id/read", headers=_auth(user))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/notifications/mark-all-read
# ---------------------------------------------------------------------------

def test_mark_all_read_marks_only_callers_unread(client, test_db):
    me = _make_user(test_db, "mar_me")
    them = _make_user(test_db, "mar_them")
    my_unread = [
        _make_notification(test_db, user_id=me.id, event_type="comment.replied"),
        _make_notification(test_db, user_id=me.id, event_type="follow.requested"),
    ]
    my_read = _make_notification(
        test_db, user_id=me.id,
        read_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    their_unread = _make_notification(test_db, user_id=them.id)
    test_db.commit()

    resp = client.post("/api/notifications/mark-all-read", headers=_auth(me))
    assert resp.status_code == 200
    assert resp.json() == {"marked": 2}

    for n in my_unread:
        test_db.refresh(n)
        assert n.read_at is not None
    test_db.refresh(their_unread)
    assert their_unread.read_at is None  # the other user's row is untouched


def test_mark_all_read_zero_unread_returns_zero(client, test_db):
    user = _make_user(test_db, "mar_zero")
    test_db.commit()

    resp = client.post("/api/notifications/mark-all-read", headers=_auth(user))
    assert resp.status_code == 200
    assert resp.json() == {"marked": 0}


# ---------------------------------------------------------------------------
# GET /api/notifications/preferences
# ---------------------------------------------------------------------------

def test_get_preferences_default_state_all_false(client, test_db):
    """Opt-in default: a user with no NotificationPreference rows sees
    every event-channel pair as False."""
    user = _make_user(test_db, "pref_default")
    test_db.commit()

    resp = client.get("/api/notifications/preferences", headers=_auth(user))
    assert resp.status_code == 200
    body = resp.json()

    # All 12 events present; every channel is False.
    assert set(body["preferences"].keys()) == {ev.key for ev in EVENT_REGISTRY}
    for prefs in body["preferences"].values():
        assert prefs == {"in_app": False, "email": False}

    # Top-level defaults match the User model defaults.
    assert body["digest_cadence"] == "real_time"
    assert body["quiet_hours_enabled"] is False
    assert body["timezone"] is None
    assert body["notification_intro_dismissed"] is False


def test_get_preferences_reflects_existing_rows(client, test_db):
    user = _make_user(test_db, "pref_existing")
    test_db.add(models.NotificationPreference(
        user_id=user.id, event_type="comment.replied",
        channel="in_app", enabled=True,
    ))
    test_db.add(models.NotificationPreference(
        user_id=user.id, event_type="comment.replied",
        channel="email", enabled=True,
    ))
    user.timezone = "America/Los_Angeles"
    test_db.commit()

    resp = client.get("/api/notifications/preferences", headers=_auth(user))
    body = resp.json()
    assert body["preferences"]["comment.replied"] == {"in_app": True, "email": True}
    assert body["preferences"]["follow.requested"] == {"in_app": False, "email": False}
    assert body["timezone"] == "America/Los_Angeles"


# ---------------------------------------------------------------------------
# PATCH /api/notifications/preferences
# ---------------------------------------------------------------------------

def test_patch_preferences_partial_update_creates_audit_event(client, test_db):
    user = _make_user(test_db, "pref_patch")
    test_db.commit()

    resp = client.patch(
        "/api/notifications/preferences",
        json={
            "preferences": {
                "comment.replied": {"in_app": True, "email": True},
                "follow.requested": {"in_app": True},
            },
            "digest_cadence": "daily",
            "quiet_hours_enabled": True,
            "timezone": "America/Los_Angeles",
            "notification_intro_dismissed": True,
        },
        headers=_auth(user),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["preferences"]["comment.replied"] == {"in_app": True, "email": True}
    assert body["preferences"]["follow.requested"] == {"in_app": True, "email": False}
    assert body["digest_cadence"] == "daily"
    assert body["quiet_hours_enabled"] is True
    assert body["timezone"] == "America/Los_Angeles"
    assert body["notification_intro_dismissed"] is True

    # Audit event surfaced.
    audit = (
        test_db.query(models.AuditLog)
        .filter(models.AuditLog.action == "notifications.preferences_updated")
        .all()
    )
    assert len(audit) == 1
    details = audit[0].details
    assert "changes" in details
    changes = details["changes"]
    assert changes["digest_cadence"] == {"old": "real_time", "new": "daily"}
    assert changes["quiet_hours_enabled"] == {"old": False, "new": True}
    assert "preferences" in changes
    assert changes["preferences"]["comment.replied"]["in_app"] == {
        "old": False, "new": True,
    }


def test_patch_preferences_no_change_no_audit(client, test_db):
    user = _make_user(test_db, "pref_noop")
    test_db.commit()

    # PATCH with values matching defaults — no diff, no audit event.
    resp = client.patch(
        "/api/notifications/preferences",
        json={
            "digest_cadence": "real_time",   # already the default
            "quiet_hours_enabled": False,    # already the default
        },
        headers=_auth(user),
    )
    assert resp.status_code == 200

    audit = (
        test_db.query(models.AuditLog)
        .filter(models.AuditLog.action == "notifications.preferences_updated")
        .all()
    )
    assert audit == []


def test_patch_preferences_unknown_event_type_400(client, test_db):
    user = _make_user(test_db, "pref_bad_event")
    test_db.commit()

    resp = client.patch(
        "/api/notifications/preferences",
        json={"preferences": {"some.nonexistent_event": {"in_app": True}}},
        headers=_auth(user),
    )
    assert resp.status_code == 400
    assert "Unknown event_type" in resp.json()["detail"]


def test_patch_preferences_bad_cadence_400(client, test_db):
    user = _make_user(test_db, "pref_bad_cadence")
    test_db.commit()

    resp = client.patch(
        "/api/notifications/preferences",
        json={"digest_cadence": "hourly"},
        headers=_auth(user),
    )
    assert resp.status_code == 400
    assert "digest_cadence" in resp.json()["detail"]


def test_patch_preferences_idempotent_upsert(client, test_db):
    """Toggling the same event twice doesn't create duplicate rows
    (uniqueness is on (user_id, event_type, channel))."""
    user = _make_user(test_db, "pref_upsert")
    test_db.commit()

    for value in (True, False, True):
        resp = client.patch(
            "/api/notifications/preferences",
            json={"preferences": {"comment.replied": {"in_app": value}}},
            headers=_auth(user),
        )
        assert resp.status_code == 200

    rows = (
        test_db.query(models.NotificationPreference)
        .filter(
            models.NotificationPreference.user_id == user.id,
            models.NotificationPreference.event_type == "comment.replied",
            models.NotificationPreference.channel == "in_app",
        )
        .all()
    )
    assert len(rows) == 1
    assert rows[0].enabled is True


# ---------------------------------------------------------------------------
# GET /api/notifications/registry
# ---------------------------------------------------------------------------

def test_get_registry_returns_12_entries(client, test_db):
    user = _make_user(test_db, "reg_user")
    test_db.commit()

    resp = client.get("/api/notifications/registry", headers=_auth(user))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["events"]) == 12
    keys = {ev["key"] for ev in body["events"]}
    expected = {ev.key for ev in EVENT_REGISTRY}
    assert keys == expected
    # Every entry has non-empty label, description, category.
    for ev in body["events"]:
        assert ev["label"] and ev["description"] and ev["category"]
    # Categories are the documented five.
    assert set(body["categories"]) == {
        "Comments", "Proposals", "Membership", "Delegation", "Polis",
    }


# ---------------------------------------------------------------------------
# emit_notification helper — opt-in default + opt-in flow
# ---------------------------------------------------------------------------

def test_emit_notification_opt_in_default_no_row(test_db):
    """Default-state user (no preferences) gets no in_app row."""
    user = _make_user(test_db, "emit_default")
    test_db.commit()
    bg = BackgroundTasks()

    result = emit_notification(
        test_db, bg,
        event_type="comment.replied",
        user_id=user.id,
    )
    test_db.commit()

    assert result is None
    rows = test_db.query(models.Notification).filter(
        models.Notification.user_id == user.id,
    ).all()
    assert rows == []


def test_emit_notification_inserts_row_when_preference_enabled(test_db):
    user = _make_user(test_db, "emit_optin")
    test_db.add(models.NotificationPreference(
        user_id=user.id, event_type="comment.replied",
        channel="in_app", enabled=True,
    ))
    test_db.commit()
    bg = BackgroundTasks()

    result = emit_notification(
        test_db, bg,
        event_type="comment.replied",
        user_id=user.id,
        org_id=None,
        target_type="comment",
        target_id="comment-123",
        payload={"excerpt": "Hello there"},
    )
    test_db.commit()

    assert result is not None
    assert result.user_id == user.id
    assert result.event_type == "comment.replied"
    assert result.target_type == "comment"
    assert result.target_id == "comment-123"
    assert result.payload == {"excerpt": "Hello there"}
    assert result.read_at is None


def test_emit_notification_unknown_event_type_raises(test_db):
    user = _make_user(test_db, "emit_bad")
    test_db.commit()
    bg = BackgroundTasks()

    with pytest.raises(ValueError, match="unknown event_type"):
        emit_notification(
            test_db, bg,
            event_type="some.fake.event",
            user_id=user.id,
        )


def test_emit_notification_unknown_user_returns_none(test_db):
    """A missing user_id is logged-and-skipped, not a hard error."""
    bg = BackgroundTasks()
    result = emit_notification(
        test_db, bg,
        event_type="comment.replied",
        user_id="nonexistent-user-id",
    )
    assert result is None


# ---------------------------------------------------------------------------
# 90-day cleanup
# ---------------------------------------------------------------------------

def test_cleanup_expired_notifications_deletes_old_rows(test_db):
    user = _make_user(test_db, "cleanup_user")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    old = _make_notification(
        test_db, user_id=user.id,
        created_at=now - timedelta(days=91),
    )
    edge = _make_notification(
        test_db, user_id=user.id, event_type="follow.requested",
        created_at=now - timedelta(days=89),  # within 90-day window
    )
    fresh = _make_notification(
        test_db, user_id=user.id, event_type="follow.approved",
        created_at=now,
    )
    old_id, edge_id, fresh_id = old.id, edge.id, fresh.id
    test_db.commit()

    deleted = cleanup_expired_notifications(test_db)
    test_db.commit()

    assert deleted == 1
    remaining_ids = {
        n.id for n in test_db.query(models.Notification).all()
    }
    assert old_id not in remaining_ids
    assert edge_id in remaining_ids
    assert fresh_id in remaining_ids


def test_cleanup_expired_notifications_zero_when_all_fresh(test_db):
    user = _make_user(test_db, "cleanup_fresh")
    _make_notification(test_db, user_id=user.id)
    test_db.commit()

    deleted = cleanup_expired_notifications(test_db)
    assert deleted == 0
