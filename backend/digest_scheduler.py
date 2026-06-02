"""Phase 13 / 13.3 — daily/weekly digest scheduler + quiet-hours flush.

Scheduling implementation: an asyncio task started in main.py's startup
hook that wakes every hour. Each tick:

  1. For each user, at their local 9am, aggregate any
     ``email_daily``-enabled events from the last 24 hours, send a digest
     email, mark the included rows as ``payload["delivered_in_digest"] =
     True``.

  2. For each user, at their local Monday 9am, do the same over the last
     7 days for ``email_weekly``-enabled events.

  3. For users with quiet hours enabled whose local time has just hit
     their ``quiet_hours_end``, flush any immediate emails suppressed
     during the window (rows tagged ``payload["queued_for_quiet_hours_end"]
     = True`` by the emit-time path).

  4. Tail-step: ``cleanup_expired_notifications(db)`` deletes
     90+-day-old rows.

Empty digests (zero qualifying notifications) do not send.

Phase 13.3: the global ``digest_cadence`` column on User was retired.
Daily / weekly opt-in is now a per-event channel preference
(``email_daily`` / ``email_weekly``). The aggregator filters
notifications by joining the user's per-event preference rows; the tick
driver iterates all users (cheap at v1 scale) instead of slicing by the
old global column.

The loop is gated on ``DISABLE_DIGEST_SCHEDULER`` env var so the test
suite doesn't accidentally launch it. Tests exercise
``aggregate_for_user`` and ``run_one_tick`` directly without spinning
the loop.
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
    send_email,
    send_org_email_async,
)
from notification_emit import (
    QUIET_HOURS_END,
    _user_local_hour,
    cleanup_expired_notifications,
    emit_notification,
    has_ever_emitted,
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


def _user_cadence_event_types(
    db: Session, user_id: str, cadence_channel: str,
) -> set[str]:
    """Return the set of event_types the user has the given digest
    channel (``email_daily`` or ``email_weekly``) enabled for.
    """
    rows = (
        db.query(models.NotificationPreference.event_type)
        .filter(
            models.NotificationPreference.user_id == user_id,
            models.NotificationPreference.channel == cadence_channel,
            models.NotificationPreference.enabled == True,  # noqa: E712
        )
        .all()
    )
    return {r.event_type for r in rows}


def aggregate_for_user(
    db: Session,
    user: models.User,
    cadence: str,
    *,
    now: Optional[datetime] = None,
) -> DigestAggregate:
    """Collect digest-eligible notifications for ``user`` over the cadence
    window.

    Phase 13.3: only notifications whose ``event_type`` matches the
    user's enabled per-event cadence channel (``email_daily`` for daily,
    ``email_weekly`` for weekly) are included. Eligible = unread,
    undelivered, within the cadence window, AND user opted into that
    cadence channel for that event_type.

    Already-delivered notifications (``payload["delivered_in_digest"] ==
    True``) are excluded so a rolling cron doesn't double-count.

    Quiet-hours queued real-time emails (``payload["queued_for_quiet_
    hours_end"] == True``) are NOT included in digests — they're
    flushed separately by ``flush_quiet_hours_queue``.
    """
    now = (now or datetime.now(timezone.utc)).replace(tzinfo=None) if now else datetime.now(timezone.utc).replace(tzinfo=None)
    if cadence == "daily":
        cutoff = now - timedelta(days=1)
        cadence_channel = "email_daily"
    elif cadence == "weekly":
        cutoff = now - timedelta(days=7)
        cadence_channel = "email_weekly"
    else:
        return DigestAggregate(user=user, cadence=cadence, cutoff=now, groups=[], notification_ids=[])

    # Phase 13.3: filter to event_types the user has explicitly opted
    # into for this cadence channel. Empty set => empty digest (nothing
    # qualifies).
    cadence_events = _user_cadence_event_types(db, user.id, cadence_channel)
    if not cadence_events:
        return DigestAggregate(user=user, cadence=cadence, cutoff=cutoff, groups=[], notification_ids=[])

    rows = (
        db.query(models.Notification)
        .filter(
            models.Notification.user_id == user.id,
            models.Notification.created_at >= cutoff,
            models.Notification.read_at.is_(None),
            models.Notification.event_type.in_(cadence_events),
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
    if event_type == "proposal.entered_voting.you_vote":
        return f"Voting opened on '{payload.get('proposal_title') or ''}' — you vote directly."
    if event_type == "proposal.entered_voting.delegated_to_you":
        return f"Voting opened on '{payload.get('proposal_title') or ''}' — you vote on others' behalf."
    if event_type == "proposal.closed":
        # Phase 24 — prefer per-method outcome_detail (e.g. "passed (5-3)",
        # "passed — Tuesday won") when set. Falls back to the generic
        # outcome value for older notifications + SRR-stable closes that
        # don't carry the detail field.
        outcome_str = payload.get("outcome_detail") or payload.get("outcome") or "resolved"
        return f"'{payload.get('proposal_title') or ''}' closed: {outcome_str}."
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

async def render_and_send_digest(
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

    Phase 48.1 — async-native. The digest tick runs inside uvicorn's
    asyncio loop; we ``await send_email`` directly instead of bouncing
    through ``_run_async`` (the self-deadlock that wedged prod). The
    DB work (atomic claim + commit) stays sync against the sync
    SQLAlchemy session — only the transport call is awaited.
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

    sent = await send_email(user.email, subject, html_body)
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

async def flush_quiet_hours_queue(
    db: Session, user: models.User,
) -> int:
    """Send the email for any notification rows queued during this
    user's quiet hours window.

    Rows are tagged at emit time with ``payload["queued_for_quiet_
    hours_end"] = True``. This function loads them, dispatches the
    real-time email for each via the same path as
    ``send_event_email``, and clears the flag on success.

    Returns the number of rows flushed.

    Phase 48.1 — async-native. ``send_org_email_async`` is the
    real-impl entry point; the sync ``send_org_email`` would
    re-introduce the self-deadlock when called from this tick (which
    runs inside uvicorn's loop).
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
        ok = await send_org_email_async(
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
# Phase 21 (B3 / D5 / D6 / D8 / D9) — halfway-deadline check
# ---------------------------------------------------------------------------
#
# Periodic task that runs on the existing digest scheduler cadence (every
# tick). For each proposal currently in ``voting`` status whose voting
# window is between 50% and 100% elapsed, find:
#
#   * Users with an active delegation on one of the proposal's topics (or
#     an org-wide global delegation) whose delegate hasn't voted yet ->
#     emit ``voting.halfway_delegate_silent`` once per (user, proposal)
#     pair (idempotent via ``has_ever_emitted``).
#   * Users without delegation on the proposal's topics who haven't voted
#     themselves -> emit ``voting.halfway_you_havent_voted``. Same
#     idempotency check.
#
# D5/D6 are mutually exclusive: a user with delegation gets the silent
# variant; a user without delegation gets the havent_voted variant. Never
# both per (user, proposal).
#
# Implementation note on BackgroundTasks: the scheduler runs outside a
# request context. ``emit_notification`` requires a ``BackgroundTasks``
# parameter for its email-immediate path. We pass a fresh in-process
# instance per emission; its ``.add_task`` list is never executed (no
# starlette response cycle), so email_immediate sends are forfeit at
# emit time. The in-app row IS inserted, and digest aggregators
# (email_daily / email_weekly) pick it up on their next pass. This
# matches the spec's "halfway events fire from a scheduled job, not from
# request context" framing.


def run_halfway_deadline_check(
    db: Session, *, now: Optional[datetime] = None,
) -> dict:
    """Detect proposals at 50%+ voting elapsed; emit halfway-deadline
    notifications to qualifying users.

    Returns ``{halfway_delegate_silent: N, halfway_you_havent_voted: N}``.

    Idempotent: ``has_ever_emitted`` is checked per (user, event_type,
    proposal) before each emit so re-running the task does not duplicate
    notifications. Per-proposal try/except so one proposal's error
    doesn't break the iteration.
    """
    from sqlalchemy import or_ as _or_  # local to keep scheduler imports tidy

    counts = {
        "halfway_delegate_silent": 0,
        "halfway_you_havent_voted": 0,
    }
    now_naive = (
        (now or datetime.now(timezone.utc))
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )

    proposals = (
        db.query(models.Proposal)
        .filter(
            models.Proposal.status == "voting",
            models.Proposal.voting_start.isnot(None),
            models.Proposal.voting_end.isnot(None),
        )
        .all()
    )

    # Lazy import to avoid circulars at module load.
    try:
        from delegation_engine import eligible_voter_ids_for_proposal
    except Exception:  # noqa: BLE001
        log.exception("halfway_deadline_check: failed to import eligible_voter_ids_for_proposal")
        return counts

    for p in proposals:
        try:
            window = (p.voting_end - p.voting_start).total_seconds()
            if window <= 0:
                continue
            elapsed = (now_naive - p.voting_start).total_seconds()
            percent_elapsed = elapsed / window
            if percent_elapsed < 0.5 or percent_elapsed > 1.0:
                continue

            topic_ids = [pt.topic_id for pt in p.proposal_topics]
            try:
                eligible_ids = eligible_voter_ids_for_proposal(db, p)
            except Exception:  # noqa: BLE001
                log.exception(
                    "halfway_deadline_check: eligible_voter_ids failed for proposal=%s",
                    p.id,
                )
                continue

            for uid in eligible_ids:
                try:
                    # Skip if user already voted directly.
                    direct_vote = (
                        db.query(models.Vote)
                        .filter(
                            models.Vote.proposal_id == p.id,
                            models.Vote.user_id == uid,
                        )
                        .first()
                    )
                    if direct_vote is not None:
                        continue

                    # Find this user's delegation that covers the proposal
                    # (org-scoped + topic-or-global). If multiple match
                    # (e.g. global + topic-specific), the topic-specific
                    # one is the conceptual winner — but for the silent /
                    # not-silent decision either suffices. We just need
                    # to know there's at least one and pick a delegate.
                    delegation_q = db.query(models.Delegation).filter(
                        models.Delegation.delegator_id == uid,
                        models.Delegation.org_id == p.org_id,
                    )
                    if topic_ids:
                        delegation_q = delegation_q.filter(
                            _or_(
                                models.Delegation.topic_id.is_(None),
                                models.Delegation.topic_id.in_(topic_ids),
                            )
                        )
                    else:
                        delegation_q = delegation_q.filter(
                            models.Delegation.topic_id.is_(None)
                        )
                    delegation = delegation_q.first()

                    if delegation is not None:
                        # User has delegation — emit silent variant only
                        # if the delegate hasn't voted.
                        delegate_vote = (
                            db.query(models.Vote)
                            .filter(
                                models.Vote.proposal_id == p.id,
                                models.Vote.user_id == delegation.delegate_id,
                            )
                            .first()
                        )
                        if delegate_vote is not None:
                            continue
                        if has_ever_emitted(
                            db, uid, "voting.halfway_delegate_silent", p.id,
                        ):
                            continue
                        delegate_user = db.get(models.User, delegation.delegate_id)
                        delegate_display = (
                            (delegate_user.display_name or delegate_user.username)
                            if delegate_user else "your delegate"
                        )
                        payload = {
                            "proposal_id": p.id,
                            "proposal_title": p.title,
                            "delegate_user_id": delegation.delegate_id,
                            "delegate_display_name": delegate_display,
                            "voting_end": (
                                p.voting_end.isoformat() if p.voting_end else None
                            ),
                            "percent_elapsed": round(percent_elapsed, 4),
                        }
                        emit_notification(
                            db,
                            _scheduler_background_tasks(),
                            event_type="voting.halfway_delegate_silent",
                            user_id=uid,
                            org_id=p.org_id,
                            actor_id=None,
                            target_type="proposal",
                            target_id=p.id,
                            payload=payload,
                        )
                        counts["halfway_delegate_silent"] += 1
                    else:
                        # No delegation, user hasn't voted -> havent_voted
                        if has_ever_emitted(
                            db, uid, "voting.halfway_you_havent_voted", p.id,
                        ):
                            continue
                        payload = {
                            "proposal_id": p.id,
                            "proposal_title": p.title,
                            "voting_end": (
                                p.voting_end.isoformat() if p.voting_end else None
                            ),
                            "percent_elapsed": round(percent_elapsed, 4),
                        }
                        emit_notification(
                            db,
                            _scheduler_background_tasks(),
                            event_type="voting.halfway_you_havent_voted",
                            user_id=uid,
                            org_id=p.org_id,
                            actor_id=None,
                            target_type="proposal",
                            target_id=p.id,
                            payload=payload,
                        )
                        counts["halfway_you_havent_voted"] += 1
                except Exception:  # noqa: BLE001
                    log.exception(
                        "halfway_deadline_check: per-user emission failed "
                        "(proposal=%s user=%s); continuing",
                        p.id, uid,
                    )
            # Commit per-proposal so a later proposal's failure can't
            # roll back successful emissions from earlier proposals.
            db.commit()
        except Exception:  # noqa: BLE001
            log.exception(
                "halfway_deadline_check: per-proposal failure (proposal=%s); continuing",
                p.id,
            )
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass

    return counts


def _scheduler_background_tasks():
    """Return a fresh ``BackgroundTasks`` instance whose task list is
    discarded after emission. The scheduler is outside a request context,
    so any tasks added here never execute — the email-immediate path is
    a no-op. The in-app row insertion (the load-bearing path for digest
    aggregation) happens before any background task would run.
    """
    from fastapi import BackgroundTasks as _BG
    return _BG()


# ---------------------------------------------------------------------------
# Hourly tick
# ---------------------------------------------------------------------------

async def run_one_tick(
    db: Session, *, now: Optional[datetime] = None,
) -> dict:
    """One hour's processing.

    Returns a small report dict ``{daily: N, weekly: N, quiet: N,
    cleaned: N}`` for logging / tests.

    Phase 48.1 — async-native. The function itself is ``async`` so it
    can ``await`` the email transport calls inside
    ``render_and_send_digest`` and ``flush_quiet_hours_queue``.
    Everything else — DB scans, pending-actions expiry,
    halfway-deadline check, demo-reset check, cleanup — remains
    synchronous against the sync SQLAlchemy session, which is fine
    (the deadlock was specifically about the email coroutine, not
    DB work). The tick's ordering + try/except isolation are
    unchanged from pre-Phase-48.1.
    """
    now = now or datetime.now(timezone.utc)
    counts = {
        "daily": 0,
        "weekly": 0,
        "quiet": 0,
        "cleaned": 0,
        "halfway_delegate_silent": 0,
        "halfway_you_havent_voted": 0,
        "pending_actions_expired": 0,
    }

    # Phase 44 (B5) — expire any pending admin actions whose window has
    # elapsed. Cheap short-circuit when none are due; wrapped in
    # try/except so an expiry failure doesn't break the rest of the
    # tick. Lazy expire-on-read inside engine paths is the secondary
    # guard; this is the source of truth.
    try:
        from pending_actions.engine import expire_due_pending_actions
        now_naive = (
            now.astimezone(timezone.utc).replace(tzinfo=None)
            if now.tzinfo is not None
            else now
        )
        counts["pending_actions_expired"] = expire_due_pending_actions(
            db, now=now_naive,
        )
    except Exception:  # noqa: BLE001
        log.exception("digest tick: pending_actions expiry failed")
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass

    # Phase 21 (B3 / D8) — halfway-deadline check runs on every tick. No
    # hour-of-day gate; idempotency via has_ever_emitted guarantees a
    # given (user, proposal) pair fires at most once. Wrapped in
    # try/except so a halfway-check failure doesn't break the rest of
    # the tick (digests, cleanup).
    try:
        halfway_counts = run_halfway_deadline_check(db, now=now)
        counts["halfway_delegate_silent"] = halfway_counts.get(
            "halfway_delegate_silent", 0,
        )
        counts["halfway_you_havent_voted"] = halfway_counts.get(
            "halfway_you_havent_voted", 0,
        )
    except Exception:  # noqa: BLE001
        log.exception("digest tick: halfway_deadline_check failed")
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass

    # Phase 49 B3 — scheduled / fixed-term election trigger. Cheap when
    # no titles have term clocks set (the default for any org that
    # didn't opt in). Per-title try/except inside the helper isolates
    # bad titles; this outer try/except guards against catastrophic
    # failure poisoning the rest of the tick.
    counts["scheduled_elections_opened"] = 0
    try:
        from elections import open_due_term_elections
        sched_counts = open_due_term_elections(db, now=now)
        counts["scheduled_elections_opened"] = sched_counts.get("opened", 0)
        counts["scheduled_elections_idempotent_skips"] = (
            sched_counts.get("skipped_idempotent", 0)
        )
        counts["scheduled_elections_errors"] = sched_counts.get("errors", 0)
    except Exception:  # noqa: BLE001
        log.exception("digest tick: open_due_term_elections failed")
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass

    # Single user-set query — small enough at v1 scale to iterate in
    # Python. Phase 13.3: we no longer slice by ``digest_cadence`` (that
    # column is gone); aggregate_for_user filters by per-event channel
    # preferences and returns an empty aggregate if the user is opted
    # into nothing for the cadence in question, so the tick is cheap.
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

        # Daily digest at 9am local. Phase 13.3: aggregate_for_user
        # checks per-event email_daily preferences; users with no
        # email_daily opt-ins produce an empty aggregate and skip.
        if local_hour == DAILY_DIGEST_HOUR:
            try:
                aggregate = aggregate_for_user(db, user, "daily", now=now)
                if not aggregate.is_empty:
                    if await render_and_send_digest(db, aggregate):
                        counts["daily"] += 1
            except Exception:  # noqa: BLE001
                log.exception("digest tick: daily failed for user=%s", user.id)
                db.rollback()

        # Weekly digest on Monday 9am local. Same per-event channel
        # filter as daily but using email_weekly opt-ins.
        if local_hour == WEEKLY_DIGEST_HOUR:
            try:
                local_now = _user_local_now(user, now)
                if local_now.weekday() == WEEKLY_DIGEST_WEEKDAY:
                    aggregate = aggregate_for_user(db, user, "weekly", now=now)
                    if not aggregate.is_empty:
                        if await render_and_send_digest(db, aggregate):
                            counts["weekly"] += 1
            except Exception:  # noqa: BLE001
                log.exception("digest tick: weekly failed for user=%s", user.id)
                db.rollback()

        # Quiet-hours queue flush at the user's configured end-of-window
        # hour. Phase 13.3: per-user adjustable via User.quiet_hours_end
        # (HH:MM string); fall back to the platform default if unset.
        if user.quiet_hours_enabled:
            try:
                from notification_emit import _parse_hhmm_hour as _hh
                user_end_hour = _hh(getattr(user, "quiet_hours_end", None), QUIET_HOURS_END)
            except Exception:  # noqa: BLE001
                user_end_hour = QUIET_HOURS_END
            if local_hour == user_end_hour:
                try:
                    n = await flush_quiet_hours_queue(db, user)
                    counts["quiet"] += n
                except Exception:  # noqa: BLE001
                    log.exception(
                        "digest tick: quiet-hours flush failed for user=%s", user.id,
                    )
                    db.rollback()

    # Phase 23 (B2) — demo reset check. Cheap when not due (one PlatformSetting
    # read + a timezone compare). Wrapped so a reset failure doesn't break
    # the rest of the tick (digests, cleanup).
    #
    # Phase 33 C2 — added observability. Pre-Phase-33 the reset block ran
    # silently regardless of outcome (no info log on skip OR on success);
    # the only signal was the demo_reset_job's own internal "Graph store
    # refreshed after demo reset" line buried deep in the seed pipeline.
    # The tick metrics dict didn't surface a `demo_reset` field. Net effect:
    # in 4-worker prod, you couldn't tell whether scheduled resets were
    # firing without DB introspection. Now the tick logs the result code
    # at INFO and counts["demo_reset"] reflects the per-tick outcome.
    counts["demo_reset"] = "not_attempted"
    try:
        from demo_reset_job import run_demo_reset_if_due
        result = run_demo_reset_if_due(db, force=False)
        if result.skipped:
            counts["demo_reset"] = f"skipped:{result.reason or 'unspecified'}"
        elif result.success:
            counts["demo_reset"] = (
                f"completed orgs={len(result.orgs_reset)} "
                f"wiped={result.rows_wiped} seeded={result.rows_seeded}"
            )
            log.info(
                "digest tick: demo reset completed: orgs=%s wiped=%d seeded=%d",
                result.orgs_reset, result.rows_wiped, result.rows_seeded,
            )
        else:
            counts["demo_reset"] = f"failed:{result.error or 'unknown'}"
            log.error(
                "digest tick: demo reset failed: %s", result.error,
            )
    except Exception:  # noqa: BLE001
        counts["demo_reset"] = "exception"
        log.exception("digest tick: demo reset check failed")
        try:
            db.rollback()
        except Exception:
            pass

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

# ---------------------------------------------------------------------------
# Phase 40 B4 — health endpoint state
# ---------------------------------------------------------------------------
# In-process module-level state. Safe because the digest_loop runs in the
# uvicorn asyncio loop (same process as the /api/health/scheduler handler).
_LAST_SUCCESSFUL_TICK_AT: Optional[datetime] = None
_TICKS_SINCE_LAST_SUCCESS: int = 0


def get_scheduler_state() -> dict:
    """Phase 40 B4 — current digest-loop health state for the
    /api/health/scheduler endpoint. No DB roundtrip; no lock with the
    worker loop, so the read works even when a tick is mid-execution or
    stuck."""
    return {
        "last_successful_tick_at": (
            _LAST_SUCCESSFUL_TICK_AT.isoformat()
            if _LAST_SUCCESSFUL_TICK_AT else None
        ),
        "ticks_since_last_success": _TICKS_SINCE_LAST_SUCCESS,
    }


async def digest_loop() -> None:
    """The long-running asyncio task.

    Wakes hourly. Skips work if ``is_disabled()`` returns True (so ops
    can flip the kill switch with an env var + restart).
    """
    global _LAST_SUCCESSFUL_TICK_AT, _TICKS_SINCE_LAST_SUCCESS
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
                    # Phase 35 A2 — wrap tick in instrument_tick so the
                    # audit log captures duration + peak RSS + work units
                    # when SCALABILITY_AUDIT_INSTRUMENTATION_ENABLED=true.
                    from scalability_instrumentation import instrument_tick
                    with instrument_tick("digest_scheduler") as _ctx:
                        counts = await run_one_tick(db)
                        _ctx["work_units"] = counts
                    log.info("digest_loop: tick complete %s", counts)
                    # Phase 40 B4 — record successful tick.
                    _LAST_SUCCESSFUL_TICK_AT = datetime.now(timezone.utc)
                    _TICKS_SINCE_LAST_SUCCESS = 0
                finally:
                    db.close()
            except Exception:  # noqa: BLE001
                log.exception("digest_loop: tick crashed; continuing")
                _TICKS_SINCE_LAST_SUCCESS += 1
        try:
            await asyncio.sleep(TICK_SECONDS)
        except asyncio.CancelledError:
            log.info("digest_loop: cancelled; exiting")
            return
