"""Phase 13 E3 — digest aggregation + quiet-hours queue tests.

Covers:
  - aggregate_for_user groups events by org then by event_type.
  - Empty digests return ``DigestAggregate.is_empty == True``.
  - Already-delivered notifications (payload.delivered_in_digest=True)
    are excluded from the next digest.
  - Quiet-hours queued rows are excluded from digests (they're flushed
    separately by flush_quiet_hours_queue).
  - flush_quiet_hours_queue clears the flag after a successful send.
  - Quiet-hours-end-to-end: emit at 11pm local with quiet_hours_enabled +
    email pref ON => in_app row exists, payload tagged for queue, no
    real-time email sent. Then the flush sends + clears the flag.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base
from digest_scheduler import (
    DigestAggregate,
    aggregate_for_user,
    flush_quiet_hours_queue,
    is_disabled,
    render_and_send_digest,
)
from notification_emit import emit_notification
from role_seed import seed_default_roles_for_org


_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


@pytest.fixture(autouse=True)
def _disable_scheduler_during_tests(monkeypatch):
    """Make sure no test accidentally launches the digest loop."""
    monkeypatch.setenv("DISABLE_DIGEST_SCHEDULER", "1")


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


def _make_user(
    db: Session, username: str, *, digest_cadence: str = "daily",
    timezone_name: str | None = None, quiet_hours_enabled: bool = False,
    email_verified: bool = True,
) -> models.User:
    u = models.User(
        username=username, display_name=username,
        password_hash=_DUMMY_HASH,
        email=f"{username}@test.example",
        email_verified=email_verified,
        digest_cadence=digest_cadence,
        timezone=timezone_name,
        quiet_hours_enabled=quiet_hours_enabled,
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


def _make_notification(
    db: Session, user_id: str, *,
    event_type: str = "comment.replied",
    org_id: str | None = None,
    payload: dict | None = None,
    read_at: datetime | None = None,
    created_at: datetime | None = None,
) -> models.Notification:
    n = models.Notification(
        user_id=user_id,
        event_type=event_type,
        org_id=org_id,
        payload=payload or {},
        read_at=read_at,
        created_at=created_at or datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(n)
    db.flush()
    return n


# ---------------------------------------------------------------------------
# is_disabled
# ---------------------------------------------------------------------------

def test_is_disabled_respects_env_var():
    assert is_disabled() is True  # set by autouse fixture


def test_is_disabled_returns_false_for_unset(monkeypatch):
    monkeypatch.delenv("DISABLE_DIGEST_SCHEDULER", raising=False)
    assert is_disabled() is False


# ---------------------------------------------------------------------------
# aggregate_for_user
# ---------------------------------------------------------------------------

def test_aggregate_groups_by_org_then_event_type(test_db):
    user = _make_user(test_db, "agg_user")
    org_a = _make_org(test_db, "agg_a")
    org_b = _make_org(test_db, "agg_b")

    # Org A: 2 comment.replied + 1 follow.requested
    _make_notification(test_db, user.id, event_type="comment.replied", org_id=org_a.id,
        payload={"actor_display_name": "Alice", "proposal_title": "P1"})
    _make_notification(test_db, user.id, event_type="comment.replied", org_id=org_a.id,
        payload={"actor_display_name": "Bob", "proposal_title": "P1"})
    # Org B: 1 proposal.entered_voting
    _make_notification(test_db, user.id, event_type="proposal.entered_voting", org_id=org_b.id,
        payload={"proposal_title": "P2"})
    # Account-level: 1 follow.requested
    _make_notification(test_db, user.id, event_type="follow.requested", org_id=None,
        payload={"actor_display_name": "Charlie"})
    test_db.commit()

    agg = aggregate_for_user(test_db, user, "daily")
    assert not agg.is_empty
    # 3 groups: account-level, org_a, org_b — sorted account-first then alpha
    assert len(agg.groups) == 3
    assert agg.groups[0].org_id is None
    org_ids = {g.org_id for g in agg.groups[1:]}
    assert org_ids == {org_a.id, org_b.id}
    # Find org_a
    g_a = next(g for g in agg.groups if g.org_id == org_a.id)
    assert "comment.replied" in g_a.events_by_type
    assert len(g_a.events_by_type["comment.replied"]) == 2


def test_aggregate_empty_returns_is_empty(test_db):
    user = _make_user(test_db, "empty_user")
    test_db.commit()
    agg = aggregate_for_user(test_db, user, "daily")
    assert agg.is_empty is True
    assert agg.groups == []


def test_aggregate_excludes_already_delivered(test_db):
    user = _make_user(test_db, "delivered_user")
    org = _make_org(test_db, "del_org")
    # One delivered, one fresh.
    _make_notification(test_db, user.id, event_type="comment.replied",
        org_id=org.id,
        payload={"actor_display_name": "X", "delivered_in_digest": True})
    fresh = _make_notification(test_db, user.id, event_type="comment.replied",
        org_id=org.id,
        payload={"actor_display_name": "Y"})
    test_db.commit()

    agg = aggregate_for_user(test_db, user, "daily")
    assert len(agg.notification_ids) == 1
    assert agg.notification_ids[0] == fresh.id


def test_aggregate_excludes_quiet_hours_queue(test_db):
    """Rows tagged for quiet-hours flush are NOT included in digests."""
    user = _make_user(test_db, "qh_excl_user")
    org = _make_org(test_db, "qh_excl_org")
    queued = _make_notification(test_db, user.id, event_type="comment.replied",
        org_id=org.id,
        payload={"actor_display_name": "Z", "queued_for_quiet_hours_end": True})
    fresh = _make_notification(test_db, user.id, event_type="comment.replied",
        org_id=org.id, payload={"actor_display_name": "A"})
    test_db.commit()

    agg = aggregate_for_user(test_db, user, "daily")
    assert len(agg.notification_ids) == 1
    assert agg.notification_ids[0] == fresh.id


def test_aggregate_excludes_read_rows(test_db):
    user = _make_user(test_db, "read_user")
    org = _make_org(test_db, "read_org")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    _make_notification(test_db, user.id, event_type="comment.replied",
        org_id=org.id, read_at=now,
        payload={"actor_display_name": "Read"})
    fresh = _make_notification(test_db, user.id, event_type="comment.replied",
        org_id=org.id, payload={"actor_display_name": "New"})
    test_db.commit()

    agg = aggregate_for_user(test_db, user, "daily")
    assert len(agg.notification_ids) == 1
    assert agg.notification_ids[0] == fresh.id


def test_aggregate_only_includes_events_in_window(test_db):
    user = _make_user(test_db, "win_user")
    org = _make_org(test_db, "win_org")
    old = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=2)
    new = datetime.now(timezone.utc).replace(tzinfo=None)
    _make_notification(test_db, user.id, event_type="comment.replied",
        org_id=org.id, created_at=old, payload={"actor_display_name": "Old"})
    fresh = _make_notification(test_db, user.id, event_type="comment.replied",
        org_id=org.id, created_at=new, payload={"actor_display_name": "Fresh"})
    test_db.commit()

    agg = aggregate_for_user(test_db, user, "daily")
    assert len(agg.notification_ids) == 1
    assert agg.notification_ids[0] == fresh.id

    # Weekly window includes both.
    agg_week = aggregate_for_user(test_db, user, "weekly")
    assert len(agg_week.notification_ids) == 2


# ---------------------------------------------------------------------------
# render_and_send_digest marks delivered
# ---------------------------------------------------------------------------

def test_render_marks_delivered_after_send(test_db):
    user = _make_user(test_db, "rmark_user")
    org = _make_org(test_db, "rmark_org")
    n = _make_notification(test_db, user.id, event_type="comment.replied",
        org_id=org.id,
        payload={"actor_display_name": "Sender", "proposal_title": "Prop"})
    test_db.commit()

    agg = aggregate_for_user(test_db, user, "daily")
    assert not agg.is_empty
    # Patch the transport (send_email) to a no-op success.
    with patch("digest_scheduler.send_email") as mock_send:
        async def _ok(*a, **kw):
            return True
        mock_send.side_effect = _ok
        sent = render_and_send_digest(test_db, agg)
    assert sent is True

    test_db.refresh(n)
    assert n.payload.get("delivered_in_digest") is True

    # Subsequent aggregate for same window should now be empty.
    agg2 = aggregate_for_user(test_db, user, "daily")
    assert agg2.is_empty is True


# ---------------------------------------------------------------------------
# Quiet hours — emit-time + flush
# ---------------------------------------------------------------------------

def test_quiet_hours_flag_set_at_emit_time_when_in_window(test_db, monkeypatch):
    """11pm local + quiet_hours_enabled + email pref ON => in_app row
    inserted, payload tagged for quiet-hours-end delivery, no real-time
    email sent."""
    user = _make_user(test_db, "qh_emit_user", quiet_hours_enabled=True,
        timezone_name="UTC", digest_cadence="real_time")
    # Opt in to both channels for comment.replied.
    test_db.add(models.NotificationPreference(
        user_id=user.id, event_type="comment.replied", channel="in_app",
        enabled=True,
    ))
    test_db.add(models.NotificationPreference(
        user_id=user.id, event_type="comment.replied", channel="email",
        enabled=True,
    ))
    test_db.commit()

    # Force the local-hour helper to return 23 (11pm).
    monkeypatch.setattr(
        "notification_emit._user_local_hour", lambda u, now_utc=None: 23,
    )
    bt = BackgroundTasks()
    n = emit_notification(
        test_db, bt, event_type="comment.replied",
        user_id=user.id, org_id=None, actor_id=None,
        payload={"actor_display_name": "Quiet", "proposal_title": "P"},
    )
    test_db.commit()
    assert n is not None
    assert n.payload.get("queued_for_quiet_hours_end") is True
    # No background task added (real-time email was suppressed).
    assert bt.tasks == []


def test_quiet_hours_normal_send_outside_window(test_db, monkeypatch):
    """Outside quiet hours, emit triggers the email background task."""
    user = _make_user(test_db, "qh_norm_user", quiet_hours_enabled=True,
        timezone_name="UTC", digest_cadence="real_time")
    test_db.add(models.NotificationPreference(
        user_id=user.id, event_type="comment.replied", channel="in_app",
        enabled=True,
    ))
    test_db.add(models.NotificationPreference(
        user_id=user.id, event_type="comment.replied", channel="email",
        enabled=True,
    ))
    test_db.commit()

    # Force local hour to 14 (2pm) — outside 9pm-9am window.
    monkeypatch.setattr(
        "notification_emit._user_local_hour", lambda u, now_utc=None: 14,
    )
    bt = BackgroundTasks()
    n = emit_notification(
        test_db, bt, event_type="comment.replied",
        user_id=user.id, org_id=None, actor_id=None,
        payload={"actor_display_name": "Day", "proposal_title": "P"},
    )
    test_db.commit()
    assert n is not None
    assert not n.payload.get("queued_for_quiet_hours_end")
    # A background task was scheduled.
    assert len(bt.tasks) == 1


def test_flush_quiet_hours_queue_sends_and_clears_flag(test_db):
    user = _make_user(test_db, "qh_flush_user")
    org = _make_org(test_db, "qh_org")
    n = _make_notification(
        test_db, user.id, event_type="comment.replied", org_id=org.id,
        payload={
            "actor_display_name": "X",
            "proposal_title": "T",
            "proposal_id": "p1",
            "org_slug": org.slug,
            "queued_for_quiet_hours_end": True,
        },
    )
    test_db.commit()

    # Patch send_org_email to record calls + return True.
    with patch("digest_scheduler.send_org_email") as mock_send:
        mock_send.return_value = True
        flushed = flush_quiet_hours_queue(test_db, user)
    assert flushed == 1
    test_db.refresh(n)
    assert n.payload.get("queued_for_quiet_hours_end") is False
    assert "queue_flushed_at" in n.payload


def test_flush_quiet_hours_queue_skips_non_queued_rows(test_db):
    user = _make_user(test_db, "qh_skip_user")
    org = _make_org(test_db, "qh_skip_org")
    _make_notification(
        test_db, user.id, event_type="comment.replied", org_id=org.id,
        payload={"actor_display_name": "Normal"},  # no queue flag
    )
    test_db.commit()

    with patch("digest_scheduler.send_org_email") as mock_send:
        flushed = flush_quiet_hours_queue(test_db, user)
    assert flushed == 0
    mock_send.assert_not_called()
