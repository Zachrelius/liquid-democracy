"""Phase 13 — notification emission helper + 90-day cleanup.

The single entry point ``emit_notification`` is invoked from the 12 event
sites listed in §B3 of the Phase 13 spec. It consults the recipient's
opt-in preferences and:

  1. Inserts an in-app ``Notification`` row when the
     ``(event_type, "in_app")`` preference is enabled.
  2. Queues a real-time email send via ``BackgroundTasks`` when the
     ``(event_type, "email")`` preference is enabled AND the user's
     ``digest_cadence == "real_time"`` AND we're not currently inside the
     user's quiet-hours window.
  3. For digest cadences (``"daily"`` / ``"weekly"``) the in-app row is
     still inserted; the digest job (Cluster E) picks it up later.

Critically, this helper is wrapped at every call site by ``try/except`` so
a notification failure never sinks the originating request — the user's
primary action (commenting, voting, etc.) takes priority. See spec §B3
"Critical try/except".

Cluster E coupling
------------------

The real-time email path goes through ``_queue_email_for_event``, a thin
shim that lazily imports ``email_service.send_event_email``. Cluster E
will implement that function; until then the shim is a logged no-op. The
in-app path (the load-bearing piece for the F1 notification center)
works regardless of Cluster E's status.
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

# Quiet-hours window (in the user's local timezone). Real-time emails
# during this window are suppressed and re-queued for the next 9am by
# Cluster E's digest/queue logic; the in-app row still goes through
# regardless.
QUIET_HOURS_START: int = 21  # 9pm
QUIET_HOURS_END: int = 9     # 9am


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
    """Return True iff ``local_hour`` falls in the 9pm-9am suppression
    window. The window wraps midnight: hours >= 21 OR hours < 9."""
    return local_hour >= QUIET_HOURS_START or local_hour < QUIET_HOURS_END


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

    Behavior summary:

      * If the user has the ``(event_type, "in_app")`` preference enabled
        an in-app ``Notification`` row is inserted (and returned). Absent
        row = disabled (opt-in default).
      * If the user has the ``(event_type, "email")`` preference enabled
        AND ``digest_cadence == "real_time"`` AND we're not in the user's
        quiet-hours window, a real-time email send is queued via
        ``background_tasks``.
      * For ``digest_cadence in ("daily", "weekly")`` the in-app row is
        still inserted; the digest job (Cluster E) picks it up later.
      * For ``digest_cadence == "off"`` no real-time email is queued.
      * Quiet hours suppress only the real-time email — the in-app row
        always goes through. Cluster E's digest/queue logic delivers the
        email later (typically at 9am local).

    Returns the inserted ``Notification`` row if one was created, else
    ``None``. Either way the caller MUST wrap this in ``try/except`` per
    spec §B3 — a DB error in this path must not sink the originating
    request.

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
    email_enabled = _is_channel_enabled(db, user_id, event_type, "email")

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

    # Real-time email path. Digest cadences ("daily"/"weekly") rely on
    # the in-app row being present; the digest job aggregates them at
    # the cadence boundary. "off" suppresses email entirely.
    if email_enabled and user.digest_cadence == "real_time":
        if user.quiet_hours_enabled and _in_quiet_hours(_user_local_hour(user)):
            log.debug(
                "emit_notification: suppressing real-time email for user=%s "
                "event=%s — inside quiet hours; Cluster E queue will deliver",
                user_id, event_type,
            )
        else:
            _queue_email_for_event(
                background_tasks, user_id, event_type, payload,
            )

    return notification


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
