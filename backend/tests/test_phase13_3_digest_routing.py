"""Phase 13.3 §B6 — digest job channel routing tests.

The digest job no longer reads ``User.digest_cadence`` (retired); it
reads per-event ``email_daily`` / ``email_weekly`` preferences and
includes only events the recipient has opted into for that cadence.

Cases:
  * daily-only: notification's event_type opted into email_daily =>
    included in daily digest; not in weekly.
  * weekly-only: opted into email_weekly => included in weekly only.
  * both: opted into both daily AND weekly => included in both digests.
  * immediate-only: opted into email_immediate only => NOT in daily nor
    weekly digest (immediate is the real-time email path; digests are a
    separate channel).
  * no opt-in: neither daily nor weekly => excluded from both digests.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base
from digest_scheduler import aggregate_for_user
from role_seed import seed_default_roles_for_org


_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


@pytest.fixture(autouse=True)
def _disable_scheduler_env(monkeypatch):
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


def _opt_in(db: Session, user_id: str, event_type: str, channel: str) -> None:
    db.add(models.NotificationPreference(
        user_id=user_id, event_type=event_type,
        channel=channel, enabled=True,
    ))
    db.flush()


def _make_notification(
    db: Session, user_id: str, event_type: str, org_id: str | None = None,
) -> models.Notification:
    n = models.Notification(
        user_id=user_id, event_type=event_type, org_id=org_id,
        payload={"actor_display_name": "Tester"},
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(n)
    db.flush()
    return n


def test_daily_only_event_in_daily_digest_only(test_db):
    user = _make_user(test_db, "daily_only")
    org = _make_org(test_db, "do_org")
    _opt_in(test_db, user.id, "comment.replied", "email_daily")
    _make_notification(test_db, user.id, "comment.replied", org.id)
    test_db.commit()

    daily = aggregate_for_user(test_db, user, "daily")
    weekly = aggregate_for_user(test_db, user, "weekly")
    assert not daily.is_empty
    assert weekly.is_empty


def test_weekly_only_event_in_weekly_digest_only(test_db):
    user = _make_user(test_db, "weekly_only")
    org = _make_org(test_db, "wo_org")
    _opt_in(test_db, user.id, "comment.replied", "email_weekly")
    _make_notification(test_db, user.id, "comment.replied", org.id)
    test_db.commit()

    daily = aggregate_for_user(test_db, user, "daily")
    weekly = aggregate_for_user(test_db, user, "weekly")
    assert daily.is_empty
    assert not weekly.is_empty


def test_both_daily_and_weekly_included_in_both(test_db):
    user = _make_user(test_db, "both")
    org = _make_org(test_db, "both_org")
    _opt_in(test_db, user.id, "comment.replied", "email_daily")
    _opt_in(test_db, user.id, "comment.replied", "email_weekly")
    _make_notification(test_db, user.id, "comment.replied", org.id)
    test_db.commit()

    daily = aggregate_for_user(test_db, user, "daily")
    weekly = aggregate_for_user(test_db, user, "weekly")
    assert not daily.is_empty
    assert not weekly.is_empty


def test_immediate_only_excluded_from_digests(test_db):
    """email_immediate is the real-time email path; digests don't
    include events opted into immediate-only."""
    user = _make_user(test_db, "imm_only")
    org = _make_org(test_db, "io_org")
    _opt_in(test_db, user.id, "comment.replied", "email_immediate")
    _make_notification(test_db, user.id, "comment.replied", org.id)
    test_db.commit()

    daily = aggregate_for_user(test_db, user, "daily")
    weekly = aggregate_for_user(test_db, user, "weekly")
    assert daily.is_empty
    assert weekly.is_empty


def test_no_opt_in_excluded(test_db):
    user = _make_user(test_db, "no_optin")
    org = _make_org(test_db, "no_org")
    _make_notification(test_db, user.id, "comment.replied", org.id)
    test_db.commit()

    daily = aggregate_for_user(test_db, user, "daily")
    weekly = aggregate_for_user(test_db, user, "weekly")
    assert daily.is_empty
    assert weekly.is_empty


def test_per_event_filter_excludes_other_event_types(test_db):
    """Only events the user has opted into for THIS cadence are included.
    Other event types (even with notifications) stay out."""
    user = _make_user(test_db, "filter_user")
    org = _make_org(test_db, "filter_org")
    # Opted in for daily on comment.replied only.
    _opt_in(test_db, user.id, "comment.replied", "email_daily")
    # Notifications for two distinct event types.
    _make_notification(test_db, user.id, "comment.replied", org.id)
    _make_notification(test_db, user.id, "follow.requested", None)
    test_db.commit()

    daily = aggregate_for_user(test_db, user, "daily")
    # Only the comment.replied one shows up.
    assert len(daily.notification_ids) == 1


# ---------------------------------------------------------------------------
# Quiet-hours: per-user adjustable window
# ---------------------------------------------------------------------------

def test_quiet_hours_window_uses_per_user_fields(test_db, monkeypatch):
    """Phase 13.3: the quiet-hours check honors User.quiet_hours_start /
    quiet_hours_end (HH:MM strings) instead of the hardcoded 21:00-09:00.
    """
    from notification_emit import emit_notification
    from fastapi import BackgroundTasks

    user = _make_user(test_db, "qh_user")
    user.quiet_hours_enabled = True
    user.quiet_hours_start = "13:00"
    user.quiet_hours_end = "15:00"
    test_db.flush()

    _opt_in(test_db, user.id, "comment.replied", "in_app")
    _opt_in(test_db, user.id, "comment.replied", "email_immediate")
    test_db.commit()

    # 14:00 is INSIDE this user's custom 13:00-15:00 window.
    monkeypatch.setattr(
        "notification_emit._user_local_hour", lambda u, now_utc=None: 14,
    )
    bt = BackgroundTasks()
    n = emit_notification(
        test_db, bt, event_type="comment.replied",
        user_id=user.id, org_id=None,
        payload={"actor_display_name": "X"},
    )
    test_db.commit()
    assert n is not None
    assert n.payload.get("queued_for_quiet_hours_end") is True
    assert bt.tasks == []  # no real-time email queued

    # 16:00 is OUTSIDE the window — email sends normally.
    monkeypatch.setattr(
        "notification_emit._user_local_hour", lambda u, now_utc=None: 16,
    )
    bt2 = BackgroundTasks()
    n2 = emit_notification(
        test_db, bt2, event_type="comment.replied",
        user_id=user.id, org_id=None,
        payload={"actor_display_name": "Y"},
    )
    test_db.commit()
    assert n2 is not None
    assert not n2.payload.get("queued_for_quiet_hours_end")
    assert len(bt2.tasks) == 1
