"""Phase 13 / 13.3 — notification emission helper + 90-day cleanup.

The single entry point ``emit_notification`` is invoked from each event
site. It consults the recipient's opt-in preferences and:

  1. Inserts an in-app ``Notification`` row when the
     ``(event_type, "in_app")`` preference is enabled.
  2. Queues a real-time email send via ``BackgroundTasks`` when the
     ``(event_type, "email_immediate")`` preference is enabled AND we're
     not currently inside the user's quiet-hours window.
  3. For digest channels (``email_daily`` / ``email_weekly``) the in-app
     row is still inserted; the digest job picks it up later.

Phase 13.3 retired the global ``digest_cadence`` column on User in favor
of per-event channel rows; see ``backend/notification_events.py`` and
the migration ``b9e2f4a17c83_phase_13_3_preferences_refinements.py``.

Critically, this helper is wrapped at every call site by ``try/except`` so
a notification failure never sinks the originating request — the user's
primary action (commenting, voting, etc.) takes priority.

Cluster E coupling
------------------

The real-time email path goes through ``_queue_email_for_event``, a thin
shim that lazily imports ``email_service.send_event_email``. The in-app
path is the load-bearing piece for the F1 notification center.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

import models
from notification_events import is_known_event_type


log = logging.getLogger(__name__)


# How long notification rows live before the cleanup function deletes them.
# 90 days per spec Q6.
NOTIFICATION_RETENTION_DAYS: int = 90

# Phase 21 D7 — dedup window for delegate-action notifications. When a
# delegate changes their vote three times in 30 minutes, only the first
# notification fires per delegator; subsequent changes within this window
# are suppressed. The constant is a code-level UX knob, NOT an env var —
# changing it requires a redeploy. 1 hour balances "real signal" against
# "spam."
DELEGATE_NOTIFICATION_DEDUP_HOURS: int = 1

# Default quiet-hours window (in the user's local timezone). Phase 13.3
# made this per-user adjustable via ``User.quiet_hours_start`` /
# ``User.quiet_hours_end`` (HH:MM strings). These constants remain for
# backwards-compatible imports (digest_scheduler uses QUIET_HOURS_END as
# the daily digest hour default) and as fallbacks if the per-user fields
# are unset.
QUIET_HOURS_START: int = 21  # 9pm
QUIET_HOURS_END: int = 9     # 9am

# Channels that represent email delivery (any one of these enabled means
# the user accepts email for the given event_type). Phase 13.3 split the
# legacy "email" channel into three.
_EMAIL_CHANNELS: tuple[str, ...] = (
    "email_immediate", "email_daily", "email_weekly",
)
_ALL_CHANNELS: tuple[str, ...] = ("in_app",) + _EMAIL_CHANNELS


def _now_naive() -> datetime:
    """UTC timestamp without tzinfo. Matches the rest of the codebase's
    DateTime columns that don't use ``timezone=True``."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Preference lookup
# ---------------------------------------------------------------------------

def _is_channel_enabled(
    db: Session, user_id: str, event_type: str, channel: str,
) -> bool:
    """Return True iff the user has explicitly enabled this
    (event_type, channel) pair. Absent row = False (opt-in default per spec
    Q3 — Z's override)."""
    pref = (
        db.query(models.NotificationPreference)
        .filter(
            models.NotificationPreference.user_id == user_id,
            models.NotificationPreference.event_type == event_type,
            models.NotificationPreference.channel == channel,
        )
        .first()
    )
    return bool(pref and pref.enabled)


def user_has_any_channel_enabled(
    db: Session, user_id: str, event_type: str,
) -> bool:
    """Phase 13.3 helper: True iff the user has at least one of the four
    channels (in_app / email_immediate / email_daily / email_weekly)
    enabled for this event_type.

    Used by the proposal-entered-voting priority resolution in
    ``routes/proposals.py::_emit_proposal_status_notifications`` to pick
    the highest-priority candidate event the recipient is opted into.
    """
    pref = (
        db.query(models.NotificationPreference)
        .filter(
            models.NotificationPreference.user_id == user_id,
            models.NotificationPreference.event_type == event_type,
            models.NotificationPreference.channel.in_(_ALL_CHANNELS),
            models.NotificationPreference.enabled == True,  # noqa: E712
        )
        .first()
    )
    return pref is not None


# ---------------------------------------------------------------------------
# Quiet-hours computation
# ---------------------------------------------------------------------------

def _user_local_hour(user: models.User, now_utc: Optional[datetime] = None) -> int:
    """Return the current hour (0-23) in the user's local timezone.

    Falls back to UTC if ``user.timezone`` is unset or unparseable.
    Implementation uses ``zoneinfo`` from the stdlib (PY 3.9+).
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    tz_name = (user.timezone or "").strip()
    if not tz_name:
        return now_utc.astimezone(timezone.utc).hour
    try:
        from zoneinfo import ZoneInfo
        return now_utc.astimezone(ZoneInfo(tz_name)).hour
    except Exception:
        # Bad/unknown tz string — degrade to UTC rather than failing the
        # notification path.
        log.debug(
            "emit_notification: user %s has unknown timezone %r; "
            "falling back to UTC for quiet-hours check",
            user.id, tz_name,
        )
        return now_utc.astimezone(timezone.utc).hour


def _in_quiet_hours(local_hour: int) -> bool:
    """Return True iff ``local_hour`` falls in the default 9pm-9am
    suppression window. The window wraps midnight: hours >= 21 OR hours
    < 9. Kept as a back-compat shim used by tests; the live emission
    path now goes through ``_in_user_quiet_hours`` for per-user windows.
    """
    return local_hour >= QUIET_HOURS_START or local_hour < QUIET_HOURS_END


def _parse_hhmm_hour(value: str | None, fallback: int) -> int:
    """Extract the hour-of-day from a HH:MM string. Falls back on parse
    errors so a bad value never breaks the emission path.
    """
    if not value:
        return fallback
    try:
        h, _ = value.split(":", 1)
        return int(h)
    except Exception:  # noqa: BLE001
        return fallback


def _in_user_quiet_hours(user: models.User, local_hour: int) -> bool:
    """Phase 13.3: per-user quiet-hours window with HH:MM start/end.

    The ``User.quiet_hours_start`` / ``quiet_hours_end`` columns hold
    HH:MM strings (e.g. "21:00", "09:00"). We compare on the hour of day
    only — minute-grained windows are out of scope for v1.

    The window is closed-open ``[start_hour, end_hour)`` and wraps
    midnight when ``start_hour >= end_hour``.
    """
    start_h = _parse_hhmm_hour(getattr(user, "quiet_hours_start", None), QUIET_HOURS_START)
    end_h = _parse_hhmm_hour(getattr(user, "quiet_hours_end", None), QUIET_HOURS_END)
    if start_h == end_h:
        return False  # zero-length window = always off
    if start_h < end_h:
        return start_h <= local_hour < end_h
    # Wraparound: e.g. 21:00..09:00.
    return local_hour >= start_h or local_hour < end_h


# ---------------------------------------------------------------------------
# Cluster E shim — real-time email queueing
# ---------------------------------------------------------------------------

def _queue_email_for_event(
    background_tasks: BackgroundTasks,
    user_id: str,
    event_type: str,
    payload: Optional[dict],
) -> None:
    """Queue a real-time email send for this event via background tasks.

    Lazily imports ``email_service.send_event_email`` so this module loads
    cleanly even before Cluster E ships. If the function isn't available
    yet, this is a logged no-op — the in-app row has already been inserted
    by the caller, so the user still sees the notification on next page
    load.

    Cluster E will replace this shim's import target with the real
    template-rendering + Resend send call.
    """
    try:
        from email_service import send_event_email  # type: ignore[attr-defined]
    except ImportError:
        log.debug(
            "emit_notification: email_service.send_event_email not yet "
            "implemented; skipping real-time email for event=%s user=%s",
            event_type, user_id,
        )
        return

    background_tasks.add_task(
        send_event_email, user_id=user_id, event_type=event_type, payload=payload,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def emit_notification(
    db: Session,
    background_tasks: BackgroundTasks,
    event_type: str,
    user_id: str,
    org_id: Optional[str] = None,
    actor_id: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
) -> Optional[models.Notification]:
    """Emit a single notification to ``user_id`` for ``event_type``.

    Behavior summary (Phase 13.3 per-event channel model):

      * If the user has the ``(event_type, "in_app")`` preference enabled
        an in-app ``Notification`` row is inserted (and returned). Absent
        row = disabled (opt-in default).
      * If the user has ``(event_type, "email_immediate")`` enabled AND
        we're not in the user's quiet-hours window, a real-time email
        send is queued via ``background_tasks``.
      * For ``email_daily`` / ``email_weekly`` the in-app row is still
        inserted; the digest job picks it up later via
        ``digest_scheduler.aggregate_for_user``.
      * Quiet hours suppress only the immediate email — the in-app row
        always goes through. The digest/quiet-hours flush logic delivers
        the suppressed email at end-of-quiet-hours.

    Returns the inserted ``Notification`` row if one was created, else
    ``None``. Either way the caller MUST wrap this in ``try/except`` —
    a DB error in this path must not sink the originating request.

    Unknown ``event_type`` strings raise ``ValueError`` so a typo at a
    call site fails loudly in tests; production call sites pass keys from
    ``backend/notification_events.EVENT_REGISTRY``.
    """
    if not is_known_event_type(event_type):
        raise ValueError(
            f"emit_notification: unknown event_type {event_type!r}; "
            f"expected a key from backend/notification_events.EVENT_REGISTRY"
        )

    user = db.get(models.User, user_id)
    if user is None:
        log.warning(
            "emit_notification: recipient user %s not found; skipping "
            "event=%s", user_id, event_type,
        )
        return None

    in_app_enabled = _is_channel_enabled(db, user_id, event_type, "in_app")
    email_immediate = _is_channel_enabled(db, user_id, event_type, "email_immediate")

    notification: Optional[models.Notification] = None
    if in_app_enabled:
        notification = models.Notification(
            user_id=user_id,
            event_type=event_type,
            org_id=org_id,
            actor_id=actor_id,
            target_type=target_type,
            target_id=target_id,
            payload=payload,
        )
        db.add(notification)
        db.flush()

    # Real-time email path. Phase 13.3: gated only on the per-event
    # email_immediate channel. ``email_daily`` / ``email_weekly`` rows
    # rely on the in-app row being present; the digest job aggregates
    # them at the cadence boundary.
    if email_immediate:
        if user.quiet_hours_enabled and _in_user_quiet_hours(user, _user_local_hour(user)):
            log.debug(
                "emit_notification: suppressing real-time email for user=%s "
                "event=%s — inside quiet hours; flagging payload so the "
                "end-of-window digest tick flushes the queued email",
                user_id, event_type,
            )
            # Tag the in-app row so digest_scheduler.flush_quiet_hours_queue
            # can pick it up. If in_app was disabled (no row was
            # inserted) the email is forfeited — quiet hours is an
            # email-channel feature; in-app is the SoT feed.
            if notification is not None:
                merged = dict(payload or {})
                merged["queued_for_quiet_hours_end"] = True
                notification.payload = merged
                db.flush()
        else:
            _queue_email_for_event(
                background_tasks, user_id, event_type, payload,
            )

    return notification


# ---------------------------------------------------------------------------
# Phase 21 — dedup / idempotency helpers
# ---------------------------------------------------------------------------
#
# The five Phase 21 events (delegate.voted, delegate.vote_changed,
# delegate.posted_rationale, voting.halfway_delegate_silent,
# voting.halfway_you_havent_voted) target ``proposal`` rows and can be
# emitted multiple times in response to an underlying state change. Two
# helpers prevent notification storms:
#
#   * ``should_emit_with_dedup`` — time-windowed dedup. Returns True iff a
#     notification of the same (user, event_type, proposal) tuple has NOT
#     been emitted within the past ``hours``. Used by the
#     delegate-action events (D7).
#
#   * ``has_ever_emitted`` — permanent idempotency. Returns True iff a
#     notification of the same tuple has ever been emitted. Used by the
#     halfway-deadline events (D9), which fire at most once per
#     (user, proposal) pair.
#
# Both filter on ``target_type == "proposal"`` because all five Phase 21
# events target proposal rows. If a future Phase 21-style event targets a
# different row type, add a ``target_type`` parameter.

def should_emit_with_dedup(
    db: Session,
    user_id: str,
    event_type: str,
    target_id: str,
    hours: int = DELEGATE_NOTIFICATION_DEDUP_HOURS,
) -> bool:
    """Return True iff a notification of ``event_type`` targeting the
    given proposal has NOT been emitted to ``user_id`` within the past
    ``hours`` hours.

    Used by the Phase 21 delegate-action events (D7) to prevent storms
    when an underlying state changes multiple times in quick succession.

    Caller is responsible for passing the right ``hours``;
    ``DELEGATE_NOTIFICATION_DEDUP_HOURS`` is the default and matches the
    spec's 1-hour window.
    """
    cutoff = _now_naive() - timedelta(hours=hours)
    recent = (
        db.query(models.Notification)
        .filter(
            models.Notification.user_id == user_id,
            models.Notification.event_type == event_type,
            models.Notification.target_type == "proposal",
            models.Notification.target_id == target_id,
            models.Notification.created_at >= cutoff,
        )
        .first()
    )
    return recent is None


def has_ever_emitted(
    db: Session,
    user_id: str,
    event_type: str,
    target_id: str,
) -> bool:
    """Return True iff a notification of ``event_type`` targeting the
    given proposal has ever been emitted to ``user_id``.

    Used by the Phase 21 halfway-deadline events (D9), which are one-shot
    per (user, proposal) pair — the scheduler re-runs every 30 min and
    must not duplicate. Stronger than ``should_emit_with_dedup``'s
    time-windowed check; this one has no cutoff.
    """
    return (
        db.query(models.Notification)
        .filter(
            models.Notification.user_id == user_id,
            models.Notification.event_type == event_type,
            models.Notification.target_type == "proposal",
            models.Notification.target_id == target_id,
        )
        .first()
        is not None
    )


# ---------------------------------------------------------------------------
# 90-day cleanup
# ---------------------------------------------------------------------------

def cleanup_expired_notifications(db: Session) -> int:
    """Delete ``Notification`` rows older than ``NOTIFICATION_RETENTION_DAYS``.

    Returns the number of rows deleted. Safe to call from a background
    job, a CLI script, or as a tail-step in the digest job (Cluster E
    chooses the wiring; the function itself is unit-testable on its own).
    """
    cutoff = _now_naive() - timedelta(days=NOTIFICATION_RETENTION_DAYS)
    # ``synchronize_session=False`` is the standard pattern for bulk
    # deletes when we don't need the in-session ORM state to reflect the
    # change — there's no follow-up read of these rows in the same
    # session.
    deleted = (
        db.query(models.Notification)
        .filter(models.Notification.created_at < cutoff)
        .delete(synchronize_session=False)
    )
    db.flush()
    log.info(
        "cleanup_expired_notifications: removed %d notifications older "
        "than %d days", deleted, NOTIFICATION_RETENTION_DAYS,
    )
    return int(deleted)
