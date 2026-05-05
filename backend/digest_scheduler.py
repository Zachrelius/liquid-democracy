"""Phase 13 E3 — daily/weekly digest scheduler + quiet-hours flush.

Scheduling implementation: an asyncio task started in main.py's startup
hook that wakes every hour. Each tick:

  1. For all users with ``digest_cadence == "daily"`` whose user-local
     time has just hit 9am, aggregate the unread, undelivered
     notifications from the last 24 hours, send a digest email, and mark
     the included rows as ``payload["delivered_in_digest"] = True``.

  2. For all users with ``digest_cadence == "weekly"`` whose user-local
     time has just hit Monday 9am, do the same over the last 7 days.

  3. For users with quiet hours enabled whose local time has just hit
     9am, flush any real-time emails that were suppressed during their
     9pm-9am window (rows tagged ``payload["queued_for_quiet_hours_end"]
     = True`` by the emit-time path).

  4. Tail-step: ``cleanup_expired_notifications(db)`` deletes
     90+-day-old rows.

Empty digests (zero qualifying notifications) do not send.

The loop is gated on ``DISABLE_DIGEST_SCHEDULER`` env var so the test
suite doesn't accidentally launch it. Tests exercise
``aggregate_for_user`` and ``run_one_tick`` directly without spinning
the loop.

DEPLOYMENT.md note: this approach is documented there. If the scheduler
needs to be disabled (e.g. while diagnosing a runaway-email incident),
set ``DISABLE_DIGEST_SCHEDULER=1`` and redeploy; the FastAPI process
itself stays up.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from string import Template
from typing import Optional

from sqlalchemy.orm import Session

import models
from database import SessionLocal
from email_service import (
    PLATFORM_DEFAULT_PRIMARY_COLOR,
    TEMPLATE_DIR,
    _build_event_template_vars,
    _format_subject,
    _resolve_org_primary_color,
    _run_async,
    send_email,
    send_org_email,
)
from notification_emit import (
    QUIET_HOURS_END,
    _user_local_hour,
    cleanup_expired_notifications,
)
from settings import settings


log = logging.getLogger(__name__)


DAILY_DIGEST_HOUR: int = QUIET_HOURS_END  # 9 — same as quiet-hours end
WEEKLY_DIGEST_HOUR: int = QUIET_HOURS_END
WEEKLY_DIGEST_WEEKDAY: int = 0  # Monday (datetime.weekday() returns 0 for Mon)
TICK_SECONDS: int = 3600  # one hour


# ---------------------------------------------------------------------------
# Disable flag (test suite + ops kill switch)
# ---------------------------------------------------------------------------

def is_disabled() -> bool:
    """Whether the scheduler should NOT run.

    Driven by ``DISABLE_DIGEST_SCHEDULER`` env var so tests can opt out
    of the background loop and ops can disable it without a code change.
    Truthy values: '1', 'true', 'yes' (case-insensitive).
    """
    raw = (os.environ.get("DISABLE_DIGEST_SCHEDULER") or "").strip().lower()
    return raw in {"1", "true", "yes"}


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

@dataclass
class DigestEvent:
    """One notification rendered into the digest body."""
    notification_id: str
    event_type: str
    actor_display_name: str
    summary_text: str          # one-line context
    cta_url: str               # link to the relevant page
    created_at: datetime


@dataclass
class DigestOrgGroup:
    """All events for one org in one digest."""
    org_id: Optional[str]
    org_name: str
    org_slug: Optional[str]
    primary_color: str
    events_by_type: dict[str, list[DigestEvent]] = field(default_factory=dict)


@dataclass
class DigestAggregate:
    """Output of ``aggregate_for_user`` — passed to the renderer."""
    user: models.User
    cadence: str  # "daily" | "weekly"
    cutoff: datetime
    groups: list[DigestOrgGroup]
    notification_ids: list[str]  # for marking delivered after send

    @property
    def is_empty(self) -> bool:
        return not self.groups


def aggregate_for_user(
    db: Session,
    user: models.User,
    cadence: str,
    *,
    now: Optional[datetime] = None,
) -> DigestAggregate:
    """Collect digest-eligible notifications for ``user`` over the cadence
    window.

    Eligible = unread, undelivered, and within the cadence window
    (24h for daily, 7d for weekly). Already-delivered notifications
    (``payload["delivered_in_digest"] == True``) are excluded so a
    rolling cron doesn't double-count.

    Quiet-hours queued real-time emails (``payload["queued_for_quiet_
    hours_end"] == True``) are NOT included in digests — they're
    flushed separately by ``flush_quiet_hours_queue``.
    """
    now = (now or datetime.now(timezone.utc)).replace(tzinfo=None) if now else datetime.now(timezone.utc).replace(tzinfo=None)
    if cadence == "daily":
        cutoff = now - timedelta(days=1)
    elif cadence == "weekly":
        cutoff = now - timedelta(days=7)
    else:
        return DigestAggregate(user=user, cadence=cadence, cutoff=now, groups=[], notification_ids=[])

    rows = (
        db.query(models.Notification)
        .filter(
            models.Notification.user_id == user.id,
            models.Notification.created_at >= cutoff,
            models.Notification.read_at.is_(None),
        )
        .order_by(models.Notification.created_at.asc())
        .all()
    )

    by_org: dict[Optional[str], DigestOrgGroup] = {}
    notification_ids: list[str] = []
    for row in rows:
        payload = row.payload or {}
        if payload.get("delivered_in_digest"):
            continue
        if payload.get("queued_for_quiet_hours_end"):
            continue

        # Resolve org context lazily (per-org once).
        org_key = row.org_id
        group = by_org.get(org_key)
        if group is None:
            org = db.get(models.Organization, row.org_id) if row.org_id else None
            primary_color = _resolve_org_primary_color(org)
            group = DigestOrgGroup(
                org_id=row.org_id,
                org_name=org.name if org else "Account",
                org_slug=org.slug if org else None,
                primary_color=primary_color,
            )
            by_org[org_key] = group

        # Build the per-event summary.
        actor_display = payload.get("actor_display_name") or "Someone"
        summary = _summarize_event(row.event_type, payload)
        cta_url = _digest_cta(row, user.id)
        evt = DigestEvent(
            notification_id=row.id,
            event_type=row.event_type,
            actor_display_name=actor_display,
            summary_text=summary,
            cta_url=cta_url,
            created_at=row.created_at,
        )
        group.events_by_type.setdefault(row.event_type, []).append(evt)
        notification_ids.append(row.id)

    # Order: account-level first (no org_id), then orgs alphabetically.
    groups = sorted(
        by_org.values(),
        key=lambda g: (g.org_id is not None, (g.org_name or "").lower()),
    )
    return DigestAggregate(
        user=user, cadence=cadence, cutoff=cutoff,
        groups=groups, notification_ids=notification_ids,
    )


def _summarize_event(event_type: str, payload: dict) -> str:
    """One-line summary text for the digest, per event type."""
    actor = payload.get("actor_display_name") or "Someone"
    if event_type == "comment.replied":
        return f"{actor} replied to your comment on '{payload.get('proposal_title') or 'a proposal'}'."
    if event_type == "comment.posted_on_your_proposal":
        return f"{actor} commented on your proposal '{payload.get('proposal_title') or ''}'."
    if event_type == "proposal.entered_voting":
        return f"Voting opened on '{payload.get('proposal_title') or ''}'."
    if event_type == "proposal.closed":
        return f"'{payload.get('proposal_title') or ''}' closed: {payload.get('outcome') or 'resolved'}."
    if event_type == "sustained_majority.floor_approached":
        return f"Support is approaching the floor on '{payload.get('proposal_title') or ''}'."
    if event_type == "member.join_request":
        return f"{actor} requested to join {payload.get('org_name') or 'the org'}."
    if event_type == "invitation.accepted":
        return f"{actor} accepted your invitation to {payload.get('org_name') or 'the org'}."
    if event_type == "delegate.applied":
        return f"{actor} applied to delegate on {payload.get('topic_name') or 'a topic'}."
    if event_type == "delegate.application_decided":
        decision = payload.get("decision") or "decided"
        return f"Your delegate application was {decision}."
    if event_type == "follow.requested":
        return f"{actor} requested to follow you."
    if event_type == "follow.approved":
        return f"{actor} approved your follow request."
    if event_type == "polis.created":
        return f"{actor} started a new Polis: '{payload.get('title') or ''}'."
    return f"{event_type} event."


def _digest_cta(row: models.Notification, recipient_user_id: str) -> str:
    """Compute a CTA URL for a digest row using the same routing as
    real-time emails (``email_service._build_cta_url``)."""
    from email_service import _build_cta_url
    base_url = (settings.base_url or "").rstrip("/")
    return _build_cta_url(row.event_type, base_url, row.payload or {})


# ---------------------------------------------------------------------------
# Render + send
# ---------------------------------------------------------------------------

def render_and_send_digest(
    db: Session, aggregate: DigestAggregate,
) -> bool:
    """Render the digest HTML + dispatch via send_email.

    Returns True iff the email was sent. Atomically claims the included
    rows BEFORE sending (Phase 13.2 W-DEPLOY-3 Option C), so multi-worker
    scheduler launches can't double-send the same digest. On send failure
    after a successful claim, the rows stay marked-delivered and the
    email is silently lost — the user retains the in-app notifications
    and the next tick won't retry the digest. This is the accepted
    tradeoff (per spec): one lost email is better than 4 duplicate ones.
    """
    if aggregate.is_empty:
        return False
    user = aggregate.user
    if not user.email or not user.email_verified:
        log.debug(
            "render_and_send_digest: user %s has no verified email; skipping",
            user.id,
        )
        return False

    # Atomic claim: mark all rows as delivered_in_digest=True, but only
    # for rows that aren't already marked. If another worker beat us to
    # it, we get back zero claimed IDs and abort the send.
    claimed_ids = _atomic_claim_digest_rows(db, aggregate.notification_ids)
    if not claimed_ids:
        log.debug(
            "render_and_send_digest: another worker already claimed user %s's digest; skipping",
            user.id,
        )
        return False
    db.commit()  # release the row lock before the slow email send

    template_key = "digest_daily" if aggregate.cadence == "daily" else "digest_weekly"
    try:
        raw = (TEMPLATE_DIR / f"{template_key}.html").read_text(encoding="utf-8")
    except FileNotFoundError:
        log.error("digest template missing: %s", template_key)
        return False

    body_html = _render_digest_body(aggregate)
    base_url = (settings.base_url or "").rstrip("/")
    cta_url = f"{base_url}/notifications"
    prefs_url = f"{base_url}/settings/notifications"

    # Use the most-prominent group's primary color (account-level falls
    # back to platform default). The digest is cross-org so we can't
    # honor every org's branding; use the first org's primary color or
    # the platform default.
    primary_color = PLATFORM_DEFAULT_PRIMARY_COLOR
    for g in aggregate.groups:
        if g.org_id is not None:
            primary_color = g.primary_color
            break

    html_body = Template(raw).safe_substitute(
        PRIMARY_COLOR=primary_color,
        DIGEST_BODY=body_html,
        CTA_URL=cta_url,
        PREFS_URL=prefs_url,
    )
    subject = _format_subject(
        f"digest.{aggregate.cadence}", {"user_id": user.id},
    )

    sent = _run_async(send_email(user.email, subject, html_body))
    if not sent:
        log.warning(
            "render_and_send_digest: send_email failed for user %s after atomic claim; "
            "%d rows marked delivered but email not sent (accepted tradeoff)",
            user.id, len(claimed_ids),
        )
    return bool(sent)


def _atomic_claim_digest_rows(db: Session, notification_ids: list[str]) -> list[str]:
    """Phase 13.2 W-DEPLOY-3 Option C — atomic per-row claim for digest delivery.

    Locks the candidate rows with FOR UPDATE SKIP LOCKED on PostgreSQL so
    two workers running the digest tick at the same hour can't both
    process the same notification. Filters out any row already marked
    delivered_in_digest, marks the remainder, flushes the changes (the
    caller commits to release the lock).

    SQLite (test-only) doesn't honor SKIP LOCKED but doesn't run a
    multi-worker scheduler either — its degraded behavior is benign for
    the test suite.

    Returns the list of IDs actually claimed by this call. An empty list
    means another worker beat us; the caller should skip sending.
    """
    if not notification_ids:
        return []
    q = db.query(models.Notification).filter(
        models.Notification.id.in_(notification_ids),
    )
    # PostgreSQL: FOR UPDATE SKIP LOCKED — other workers' SELECTs skip
    # rows we're holding. SQLite: option ignored, falls back to SELECT.
    try:
        q = q.with_for_update(skip_locked=True)
    except Exception:  # noqa: BLE001 — older SQLAlchemy versions / SQLite
        pass

    rows = q.all()
    claimed: list[str] = []
    for r in rows:
        payload = dict(r.payload or {})
        if payload.get("delivered_in_digest"):
            continue  # already claimed by another worker's earlier tick
        payload["delivered_in_digest"] = True
        r.payload = payload
        claimed.append(r.id)
    db.flush()  # holds the lock until commit; caller commits
    return claimed


def _render_digest_body(aggregate: DigestAggregate) -> str:
    """Build the per-org / per-event HTML body block."""
    parts: list[str] = []
    for group in aggregate.groups:
        parts.append(
            f'<h3 style="color: {group.primary_color}; margin-top: 24px;">'
            f'{group.org_name}</h3>'
        )
        for event_type, events in group.events_by_type.items():
            parts.append(
                f'<p style="font-weight: 600; margin: 16px 0 4px;">'
                f'{_event_label(event_type)} ({len(events)})</p>'
            )
            parts.append('<ul style="padding-left: 20px; margin: 4px 0 12px;">')
            for evt in events:
                parts.append(
                    f'<li><a href="{evt.cta_url}" style="color: {group.primary_color};">'
                    f'{_html_escape(evt.summary_text)}</a></li>'
                )
            parts.append("</ul>")
    return "\n".join(parts)


def _event_label(event_type: str) -> str:
    """Short label for the digest section header."""
    from notification_events import EVENT_REGISTRY_BY_KEY
    ev = EVENT_REGISTRY_BY_KEY.get(event_type)
    return ev.label if ev else event_type


def _html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _mark_delivered_in_digest(db: Session, notification_ids: list[str]) -> None:
    """Set ``payload["delivered_in_digest"] = True`` on each row so the
    next digest tick doesn't re-include them.

    Reads + writes the JSON column in-place. SQLAlchemy's JSON column
    requires the new dict to be assigned (mutating in-place doesn't
    always trigger a dirty-flag); we build a new dict per row.
    """
    if not notification_ids:
        return
    rows = (
        db.query(models.Notification)
        .filter(models.Notification.id.in_(notification_ids))
        .all()
    )
    for r in rows:
        new_payload = dict(r.payload or {})
        new_payload["delivered_in_digest"] = True
        r.payload = new_payload


# ---------------------------------------------------------------------------
# Quiet-hours queue + flush
# ---------------------------------------------------------------------------

def flush_quiet_hours_queue(
    db: Session, user: models.User,
) -> int:
    """Send the email for any notification rows queued during this
    user's quiet hours window.

    Rows are tagged at emit time with ``payload["queued_for_quiet_
    hours_end"] = True``. This function loads them, dispatches the
    real-time email for each via the same path as
    ``send_event_email``, and clears the flag on success.

    Returns the number of rows flushed.
    """
    rows = (
        db.query(models.Notification)
        .filter(models.Notification.user_id == user.id)
        .all()
    )
    flushed = 0
    for row in rows:
        payload = row.payload or {}
        if not payload.get("queued_for_quiet_hours_end"):
            continue
        # Send via the same template path as real-time. Reuses the
        # email_service helpers so the rendered email is identical to a
        # non-quiet-hours real-time send.
        template_vars = _build_event_template_vars(
            db, row.event_type, payload, user.id,
        )
        ok = send_org_email(
            db, user_id=user.id, org_id=row.org_id,
            template_key=row.event_type, template_vars=template_vars,
        )
        if ok:
            new_payload = dict(payload)
            new_payload["queued_for_quiet_hours_end"] = False
            new_payload["queue_flushed_at"] = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
            row.payload = new_payload
            flushed += 1
    if flushed:
        db.commit()
    return flushed


# ---------------------------------------------------------------------------
# Hourly tick
# ---------------------------------------------------------------------------

def run_one_tick(
    db: Session, *, now: Optional[datetime] = None,
) -> dict:
    """One hour's processing.

    Returns a small report dict ``{daily: N, weekly: N, quiet: N,
    cleaned: N}`` for logging / tests.
    """
    now = now or datetime.now(timezone.utc)
    counts = {"daily": 0, "weekly": 0, "quiet": 0, "cleaned": 0}

    # Single user-set query — small enough at v1 scale to iterate in
    # Python. If this becomes hot, slice by tz/cadence with an SQL JOIN.
    users = db.query(models.User).all()

    for user in users:
        try:
            local_hour = _user_local_hour(user, now_utc=now)
        except Exception as e:  # noqa: BLE001
            log.warning(
                "digest tick: user %s tz error %s; treating as UTC",
                user.id, e,
            )
            local_hour = now.astimezone(timezone.utc).hour

        # Daily digest at 9am local.
        if user.digest_cadence == "daily" and local_hour == DAILY_DIGEST_HOUR:
            try:
                aggregate = aggregate_for_user(db, user, "daily", now=now)
                if not aggregate.is_empty:
                    if render_and_send_digest(db, aggregate):
                        counts["daily"] += 1
            except Exception:  # noqa: BLE001
                log.exception("digest tick: daily failed for user=%s", user.id)
                db.rollback()

        # Weekly digest on Monday 9am local.
        if user.digest_cadence == "weekly" and local_hour == WEEKLY_DIGEST_HOUR:
            try:
                local_now = _user_local_now(user, now)
                if local_now.weekday() == WEEKLY_DIGEST_WEEKDAY:
                    aggregate = aggregate_for_user(db, user, "weekly", now=now)
                    if not aggregate.is_empty:
                        if render_and_send_digest(db, aggregate):
                            counts["weekly"] += 1
            except Exception:  # noqa: BLE001
                log.exception("digest tick: weekly failed for user=%s", user.id)
                db.rollback()

        # Quiet-hours queue flush at 9am local.
        if user.quiet_hours_enabled and local_hour == QUIET_HOURS_END:
            try:
                n = flush_quiet_hours_queue(db, user)
                counts["quiet"] += n
            except Exception:  # noqa: BLE001
                log.exception(
                    "digest tick: quiet-hours flush failed for user=%s", user.id,
                )
                db.rollback()

    # Tail step: 90-day cleanup.
    try:
        counts["cleaned"] = cleanup_expired_notifications(db)
        db.commit()
    except Exception:  # noqa: BLE001
        log.exception("digest tick: cleanup_expired_notifications failed")
        db.rollback()

    return counts


def _user_local_now(user: models.User, now_utc: datetime) -> datetime:
    """Return a naive local-time datetime for the user."""
    tz_name = (user.timezone or "").strip()
    if not tz_name:
        return now_utc.astimezone(timezone.utc).replace(tzinfo=None)
    try:
        from zoneinfo import ZoneInfo
        return now_utc.astimezone(ZoneInfo(tz_name)).replace(tzinfo=None)
    except Exception:  # noqa: BLE001
        return now_utc.astimezone(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Async loop entry point
# ---------------------------------------------------------------------------

async def digest_loop() -> None:
    """The long-running asyncio task.

    Wakes hourly. Skips work if ``is_disabled()`` returns True (so ops
    can flip the kill switch with an env var + restart).
    """
    log.info(
        "digest_loop: starting (DISABLE_DIGEST_SCHEDULER=%s)",
        os.environ.get("DISABLE_DIGEST_SCHEDULER", ""),
    )
    while True:
        if is_disabled():
            log.info("digest_loop: disabled; sleeping until next tick")
        else:
            try:
                db = SessionLocal()
                try:
                    counts = run_one_tick(db)
                    log.info("digest_loop: tick complete %s", counts)
                finally:
                    db.close()
            except Exception:  # noqa: BLE001
                log.exception("digest_loop: tick crashed; continuing")
        try:
            await asyncio.sleep(TICK_SECONDS)
        except asyncio.CancelledError:
            log.info("digest_loop: cancelled; exiting")
            return
