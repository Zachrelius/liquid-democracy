"""
Email service — delivers via Resend HTTP API (preferred for cloud deploys),
falls back to SMTP via aiosmtplib, or logs to console when neither is
configured.

Phase 13 E1+E2: a generalized ``send_org_email`` helper renders templates
from ``backend/email_templates/`` with org branding (Phase 12.7) and
sends via the existing transport. The Phase 12.7 invitation flow is
refactored to call ``send_org_email`` internally; its external signature
``send_invitation_email(email, token, org_name, org_slug, base_url,
primary_color=None)`` is preserved so the two call sites in
``routes/organizations.py`` need no change.

``send_event_email(user_id, event_type, payload)`` is the function that
``notification_emit._queue_email_for_event`` lazy-imports for the
real-time email path. It looks up the user, resolves the org branding
from ``payload["org_id"]`` (or the org_id field on the notification
event), builds template_vars, and calls ``send_org_email``.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
from pathlib import Path
from string import Template
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

import models
from database import SessionLocal
from settings import settings


log = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"

# Platform-default heading + button color used when the recipient's org
# has no branding configured (or the email is account-level / org_id is
# None). Matches the legacy 12.7 pre-branding default.
PLATFORM_DEFAULT_PRIMARY_COLOR = "#1B3A5C"

# All HTML templates live alongside this module under email_templates/.
TEMPLATE_DIR = Path(__file__).parent / "email_templates"


# ---------------------------------------------------------------------------
# Subjects + CTA labels per template_key
# ---------------------------------------------------------------------------
#
# Subjects use ASCII characters only (spec §E2 — no smart-quotes). Curly
# braces are Python format placeholders; the routing code substitutes
# them when the value is available in template_vars.
#
# CTA URLs are computed per template_key in ``_build_event_template_vars``;
# the body file's ``${CTA_URL}`` substitution receives the result.

_SUBJECTS: dict[str, str] = {
    "comment.replied": "New reply on your comment",
    "comment.posted_on_your_proposal": "New comment on '{proposal_title}'",
    # Phase 85 (B-1) — attributed moderator removal, emitted to the author.
    "comment.moderated": "Your comment on '{proposal_title}' was removed",
    "proposal.entered_voting": "Voting has opened on '{proposal_title}'",
    "proposal.closed": "Proposal '{proposal_title}' has closed",
    "sustained_majority.floor_approached": "Vote support nearing floor: '{proposal_title}'",
    "member.join_request": "New member request to join {org_name}",
    # Phase 88c — voting-model change (weighted <-> one member one vote).
    "org.voting_model_changed": "{org_name}'s voting model changed",
    # Phase 90a — auto-distribution grant.
    "shares.received": "You received shares in {org_name}",
    # Phase 90b — a member transferred shares to you.
    "shares.transfer_received": "{sender_display_name} transferred shares to you",
    # Phase 90d — a distribution rule was blocked by the authorized cap.
    "shares.cap_blocked": "A distribution rule in {org_name} was blocked by the share cap",
    # Phase 86 (B-4) — content report, to moderators.
    "report_created": "New content report in {org_name}",
    "invitation.accepted": "{actor_display_name} joined {org_name}",
    "delegate.applied": "New delegate application in {org_name}",
    "delegate.application_decided": "Your delegate application was {decision}",
    # Phase 19 — public-delegate-page approval workflow + hard-revert events.
    "delegate_application_submitted": "New public-delegate application in {org_name}",
    "delegate_application_approved": "Your public-delegate application on {topic_name} was approved",
    "delegate_application_denied": "Your public-delegate application on {topic_name} was denied",
    "delegation_revoked_by_delegate": "Your delegation to {delegate_display_name} on {topic_name} was revoked",
    "follow.requested": "{actor_display_name} requested to follow you",
    "follow.approved": "{actor_display_name} approved your follow request",
    "polis.created": "New deliberation in {org_name}",
    # Phase 21 — delegate-action + voting-deadline events.
    "delegate.voted": "Your delegate voted on '{proposal_title}'",
    "delegate.vote_changed": "Your delegate changed their vote on '{proposal_title}'",
    "delegate.posted_rationale": "{delegate_display_name} posted reasoning on '{proposal_title}'",
    "voting.halfway_delegate_silent": "Voting half-elapsed; your delegate hasn't voted on '{proposal_title}'",
    "voting.halfway_you_havent_voted": "Voting half-elapsed; you haven't voted on '{proposal_title}'",
    "invitation": "You're invited to join {org_name} — Liquid Democracy",
    "digest.daily": "Your Liquid Democracy daily digest",
    "digest.weekly": "Your Liquid Democracy weekly digest",
    # Phase 77 — messaging.
    "message.received": "New message from {sender_display_name} in {org_name}",
    "message.org_inbox": "New org inbox message in {org_name} from {sender_display_name}",
}


# ---------------------------------------------------------------------------
# Transport layer
# ---------------------------------------------------------------------------

async def send_email(to: str, subject: str, html_body: str) -> bool:
    """Send an email via Resend (preferred), SMTP (fallback), or console."""
    if settings.resend_api_key:
        return await _send_via_resend(to, subject, html_body)
    if settings.smtp_host:
        return await _send_via_smtp(to, subject, html_body)

    # Console mode — no provider configured. Log so devs see the link.
    log.info("=" * 60)
    log.info("EMAIL (console mode — no email provider configured)")
    log.info(f"  To:      {to}")
    log.info(f"  Subject: {subject}")
    log.info(f"  Body:")
    print(html_body)
    log.info("=" * 60)
    return True


async def _send_via_resend(to: str, subject: str, html_body: str) -> bool:
    """POST the email to Resend's HTTP API."""
    payload = {
        "from": settings.from_email,
        "to": [to],
        "subject": subject,
        "html": html_body,
    }
    headers = {
        "Authorization": f"Bearer {settings.resend_api_key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(RESEND_API_URL, json=payload, headers=headers)
        if resp.status_code >= 400:
            log.error(
                f"Resend API rejected send to {to}: {subject} | "
                f"HTTP {resp.status_code} | body={resp.text[:500]}"
            )
            return False
        log.info(f"Email sent via Resend to {to}: {subject} (id={resp.json().get('id')})")
        return True
    except Exception as e:
        log.error(
            f"Resend API call failed for {to}: {subject} | "
            f"{type(e).__name__}: {e}"
        )
        log.exception(f"Resend API call failed for {to}: {subject}")
        return False


async def _send_via_smtp(to: str, subject: str, html_body: str) -> bool:
    """Send via aiosmtplib. Used when Resend isn't configured."""
    try:
        import aiosmtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.from_email
        msg["To"] = to
        msg.attach(MIMEText(html_body, "html"))

        # Infer TLS mode from port: 465 is implicit SSL, everything else
        # (587, 2525, etc.) uses STARTTLS. Cloud providers sometimes block
        # port 587 but leave 465 open, so the env var determines the mode.
        use_ssl = settings.smtp_port == 465
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user or None,
            password=settings.smtp_password or None,
            use_tls=use_ssl,
            start_tls=not use_ssl,
            timeout=20,
        )
        log.info(f"Email sent via SMTP to {to}: {subject}")
        return True
    except Exception as e:
        log.error(
            f"Failed to send email via SMTP to {to}: {subject} | "
            f"{type(e).__name__}: {e} | "
            f"host={settings.smtp_host}:{settings.smtp_port} user={settings.smtp_user}"
        )
        log.exception(f"Failed to send email via SMTP to {to}: {subject}")
        return False


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------

def _load_template(template_key: str) -> str:
    """Load the raw HTML template for ``template_key`` from disk.

    Templates live at ``backend/email_templates/{template_key}.html``.
    Raises ``FileNotFoundError`` if the template is missing — that's a
    bug-on-the-template-set-up, not a runtime expected condition.
    """
    path = TEMPLATE_DIR / f"{template_key}.html"
    return path.read_text(encoding="utf-8")


_HEX_COLOR_RE = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})")


def _resolve_org_primary_color(org: Optional[models.Organization]) -> str:
    """Return the org's branded primary color, or the platform default.

    Mirrors the 12.7 ``_org_to_out`` branding extraction: looks at
    ``org.settings["branding"]["primary_color"]`` (str). Falls back to
    ``PLATFORM_DEFAULT_PRIMARY_COLOR`` for: no org, no settings, no
    branding key, or empty/whitespace value.
    """
    if org is None:
        return PLATFORM_DEFAULT_PRIMARY_COLOR
    settings_dict = org.settings or {}
    branding = settings_dict.get("branding") or {}
    color = (branding.get("primary_color") or "").strip()
    # Phase 63 (security): the color is interpolated into inline CSS in the
    # email templates without escaping — only accept a strict hex literal
    # here (same shape schemas.py validates at write time) so a value that
    # reached settings through any other path can't inject markup/CSS.
    if not _HEX_COLOR_RE.fullmatch(color):
        return PLATFORM_DEFAULT_PRIMARY_COLOR
    return color


def _format_subject(template_key: str, template_vars: dict[str, Any]) -> str:
    """Format the subject line for the given template key.

    Uses ``str.format_map`` with a ``defaultdict``-like fallback so a
    missing key in template_vars renders as an empty string rather than
    raising — defensive in case a payload is missing a usually-present
    field.
    """
    raw = _SUBJECTS.get(template_key, "Liquid Democracy notification")

    class _SafeDict(dict):
        def __missing__(self, key):
            return ""

    return raw.format_map(_SafeDict(template_vars))


# ---------------------------------------------------------------------------
# E1 — public API: send_org_email
# ---------------------------------------------------------------------------

def _prepare_org_email(
    db: Session,
    user_id: str,
    org_id: Optional[str],
    template_key: str,
    template_vars: dict[str, Any],
) -> Optional[tuple[str, str, str]]:
    """Resolve recipient + render subject + HTML body for an org email.

    Returns ``(recipient_email, subject, html_body)`` on success or
    ``None`` when the send should be skipped (user missing / no
    email / unverified / template missing). Pure rendering — no
    transport call. Shared by the sync ``send_org_email`` and the
    async ``send_org_email_async`` so they never diverge in
    templating behavior.
    """
    user = db.get(models.User, user_id)
    if user is None:
        log.warning("send_org_email: user %s not found; skipping", user_id)
        return None
    if not user.email:
        log.debug("send_org_email: user %s has no email; skipping", user_id)
        return None
    if not user.email_verified:
        log.debug(
            "send_org_email: user %s email not verified; skipping",
            user_id,
        )
        return None

    org = db.get(models.Organization, org_id) if org_id else None
    primary_color = _resolve_org_primary_color(org)

    try:
        raw_template = _load_template(template_key)
    except FileNotFoundError:
        log.error(
            "send_org_email: template not found for key %r; skipping",
            template_key,
        )
        return None

    subs: dict[str, str] = {"PRIMARY_COLOR": primary_color}
    # Translate template_vars keys to UPPER_CASE for ${VAR_NAME} substitution.
    # Phase 63 (security): HTML-escape every substitution value. The
    # templates interpolate user-controlled strings (display names,
    # proposal titles, org names, denial comments) directly into HTML;
    # pre-fix, a display name like '<a href="https://evil/">…</a>' rendered
    # as live markup in recipients' mail clients — a phishing vector from
    # the platform's own sending domain. PRIMARY_COLOR is exempt (strict
    # hex-validated above).
    for k, v in template_vars.items():
        if v is None:
            subs[k.upper()] = ""
        else:
            subs[k.upper()] = html.escape(str(v), quote=True)

    # safe_substitute leaves unknown placeholders as-is rather than KeyError;
    # surfaces missing-key bugs in dev (visible in the rendered email) but
    # never crashes a send.
    html_body = Template(raw_template).safe_substitute(subs)
    subject = _format_subject(template_key, template_vars)
    return user.email, subject, html_body


async def send_org_email_async(
    db: Session,
    user_id: str,
    org_id: Optional[str],
    template_key: str,
    template_vars: dict[str, Any],
) -> bool:
    """Async-native send for callers already running in an event loop.

    Phase 48.1 — the digest scheduler's tick runs inside uvicorn's
    asyncio loop. Bouncing email sends through ``_run_async`` from
    the running loop self-deadlocks (``future.result(timeout=30)``
    blocks the loop thread waiting for a coroutine that needs that
    same loop). The fix is to ``await`` the transport directly from
    the already-async tick. This function is the real implementation;
    ``send_org_email`` is now a thin sync wrapper for legacy sync
    callers.
    """
    prepared = _prepare_org_email(
        db, user_id, org_id, template_key, template_vars,
    )
    if prepared is None:
        return False
    recipient, subject, html_body = prepared
    return bool(await send_email(recipient, subject, html_body))


def send_org_email(
    db: Session,
    user_id: str,
    org_id: Optional[str],
    template_key: str,
    template_vars: dict[str, Any],
) -> bool:
    """Sync wrapper around ``send_org_email_async``.

    Kept for genuinely-sync callers — specifically the real-time
    ``send_event_email`` path invoked via FastAPI ``BackgroundTasks``
    (which runs sync tasks off the main loop in a threadpool, so
    ``_run_async``'s ``asyncio.run`` branch is correct + safe there).
    Phase 48.1 callers that already live in an async context must
    use ``send_org_email_async`` instead to avoid the self-deadlock
    that wedged prod (see ``send_org_email_async`` docstring).
    """
    prepared = _prepare_org_email(
        db, user_id, org_id, template_key, template_vars,
    )
    if prepared is None:
        return False
    recipient, subject, html_body = prepared
    return _run_async(send_email(recipient, subject, html_body))


def _run_async(coro) -> bool:
    """Run ``coro`` from sync context.

    BackgroundTasks invokes its tasks from a running event loop in some
    server modes; in others (worker scripts, tests) we may not have one.
    This helper handles both: if there's already a loop running we
    schedule the coroutine and wait synchronously; otherwise we use
    ``asyncio.run``.
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        # Inside a running loop — schedule and wait. This shouldn't happen
        # under FastAPI's BackgroundTasks (which runs sync tasks in a
        # threadpool), but keep the guard in case a caller invokes
        # send_org_email from an async route.
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            return bool(future.result(timeout=30))
        except Exception:  # noqa: BLE001
            log.exception("send_email coroutine failed under running loop")
            return False
    return bool(asyncio.run(coro))


# ---------------------------------------------------------------------------
# Cluster B / E coupling: send_event_email
# ---------------------------------------------------------------------------

def send_event_email(
    user_id: str,
    event_type: str,
    payload: Optional[dict[str, Any]],
) -> bool:
    """Real-time email for one notification event.

    Called by ``notification_emit._queue_email_for_event`` via
    BackgroundTasks. Opens its own DB session (BackgroundTasks runs
    after the originating request's session is closed), looks up the
    user + org, builds template_vars from the payload, and calls
    ``send_org_email``.

    Failures are logged but never raised — a notification email is
    fire-and-forget; the in-app row is the source-of-truth feed.
    """
    payload = payload or {}
    db = SessionLocal()
    try:
        org_id = payload.get("org_id")
        # Build template-vars for the body. The same dict is also used to
        # format the subject line (see _format_subject).
        template_vars = _build_event_template_vars(db, event_type, payload, user_id)
        return send_org_email(
            db, user_id=user_id, org_id=org_id,
            template_key=event_type, template_vars=template_vars,
        )
    except Exception as e:  # noqa: BLE001
        log.warning(
            "send_event_email failed for user=%s event=%s: %s: %s",
            user_id, event_type, type(e).__name__, e,
        )
        return False
    finally:
        db.close()


def _build_event_template_vars(
    db: Session,
    event_type: str,
    payload: dict[str, Any],
    recipient_user_id: str,
) -> dict[str, Any]:
    """Translate a notification payload into template_vars for the event's
    HTML template + subject line.

    Each event has a small fixed set of substitutions documented in
    ``backend/email_templates/{event_type}.html``. Missing payload keys
    surface as empty strings (see ``_format_subject`` and
    ``send_org_email``'s ``Template.safe_substitute``).
    """
    base_url = (settings.base_url or "").rstrip("/")
    org_slug = payload.get("org_slug") or ""
    proposal_id = payload.get("proposal_id") or ""
    polis_id = payload.get("polis_id") or ""
    target_id_for_unsub = payload.get("target_id") or ""

    cta_url = _build_cta_url(event_type, base_url, payload)
    prefs_url = f"{base_url}/settings/notifications"
    unsubscribe_url = (
        f"{base_url}/api/notifications/unsubscribe/"
        f"{generate_unsubscribe_token(recipient_user_id, event_type)}"
    )

    return {
        # Common across all templates
        "cta_url": cta_url,
        "prefs_url": prefs_url,
        "unsubscribe_url": unsubscribe_url,
        # Event-specific (empty string if the payload didn't supply it)
        "actor_display_name": payload.get("actor_display_name") or "Someone",
        "proposal_title": payload.get("proposal_title") or "",
        "proposal_id": proposal_id,
        "body_excerpt": payload.get("body_excerpt") or "",
        "org_id": payload.get("org_id") or "",
        "org_slug": org_slug,
        "org_name": payload.get("org_name") or "",
        "topic_name": payload.get("topic_name") or "",
        "topic_id": payload.get("topic_id") or "",
        "decision": payload.get("decision") or "",
        "outcome": payload.get("outcome") or "",
        # Phase 24 — close-trigger differentiation for proposal.closed.
        # ``outcome_detail`` is a per-method outcome string (e.g.
        # "passed (5-3)", "failed (quorum not met)", "passed — Tuesday won").
        # ``close_trigger`` is the payload.trigger value
        # (stable_result_achieved | voting_end_reached | voting_end_backfill);
        # templates can branch copy on it.
        "outcome_detail": payload.get("outcome_detail") or payload.get("outcome") or "",
        "close_trigger": payload.get("trigger") or "",
        "polis_title": payload.get("title") or "",
        "polis_id": polis_id,
        "support_fraction": payload.get("support_fraction") or "",
        "floor": payload.get("floor") or "",
        # Phase 19 — public-delegate-page workflow event payload keys.
        # ``delegate_display_name`` is the public delegate's display name
        # (used in delegation_revoked_by_delegate). ``denial_comment`` is
        # the required comment from the approver on a denial.
        "delegate_display_name": payload.get("delegate_display_name") or "",
        "denial_comment": payload.get("denial_comment") or "",
        # Phase 21 — delegate-action + voting-deadline event payload keys.
        # ``vote_value`` is the rendered vote (binary: "yes"/"no"/"abstain";
        # approval/RCV: a comma-joined option label list).
        # ``previous_vote_value`` is the same shape, only present on
        # ``delegate.vote_changed``. ``rationale_excerpt`` is the first
        # ~150 chars of a delegate's posted rationale. ``voting_end`` is a
        # human-readable ISO timestamp. ``percent_elapsed`` is a 0-100 int
        # (or empty) used in halfway-deadline templates.
        "vote_value": payload.get("vote_value") or "",
        "previous_vote_value": payload.get("previous_vote_value") or "",
        "rationale_excerpt": payload.get("rationale_excerpt") or "",
        "voting_end": payload.get("voting_end") or "",
        "percent_elapsed": payload.get("percent_elapsed") or "",
        # Phase 77 — messaging event payload keys.
        "sender_display_name": payload.get("sender_display_name") or "Someone",
        "preview": payload.get("preview") or "",
        # Phase 88c — voting-model-change event. ``voting_model_message`` is the
        # enabled/disabled-specific body sentence (kept consistent with the
        # weight-visibility model: members see their OWN weight + the org total,
        # not other members' weights).
        "unit_label": payload.get("unit_label") or "shares",
        # Phase 90a — shares.received grant amount.
        "amount": payload.get("amount") or "",
        "voting_model_message": (
            (
                f"Your vote is now weighted by your "
                f"{payload.get('unit_label') or 'shares'}. You can see your "
                f"{payload.get('unit_label') or 'shares'} and the "
                f"organization's total on the Members page."
            )
            if payload.get("enabled")
            else "Votes are now counted as one member, one vote."
        ),
        # CTA label is per-event but we don't currently use it as a
        # substitution slot in the templates (button text is hardcoded
        # per template). Kept here for future templates that want it.
        "cta_label": _DEFAULT_CTA_LABELS.get(event_type, "View"),
    }


_DEFAULT_CTA_LABELS: dict[str, str] = {
    "comment.replied": "View reply",
    "comment.posted_on_your_proposal": "View comment",
    "proposal.entered_voting": "Open proposal",
    "proposal.closed": "View results",
    "sustained_majority.floor_approached": "Open proposal",
    "member.join_request": "Review request",
    "invitation.accepted": "View members",
    "org.voting_model_changed": "View members",
    "shares.received": "View share activity",
    "shares.transfer_received": "View share activity",
    "shares.cap_blocked": "View share activity",
    "delegate.applied": "Review application",
    "delegate.application_decided": "Open organization",
    # Phase 19 — public-delegate-page workflow CTAs.
    "delegate_application_submitted": "Review application",
    "delegate_application_approved": "Open delegate page",
    "delegate_application_denied": "Open delegate profile",
    "delegation_revoked_by_delegate": "View delegations",
    "follow.requested": "Review request",
    "follow.approved": "View profile",
    "polis.created": "Open Polis",
    # Phase 21 — delegate-action + voting-deadline events all route to the
    # underlying proposal page so the recipient can act on the signal.
    "delegate.voted": "Open proposal",
    "delegate.vote_changed": "Open proposal",
    "delegate.posted_rationale": "Open proposal",
    "voting.halfway_delegate_silent": "Open proposal",
    "voting.halfway_you_havent_voted": "Open proposal",
    # Phase 77 — messaging.
    "message.received": "View message",
    "message.org_inbox": "Open org inbox",
}


def _build_cta_url(
    event_type: str, base_url: str, payload: dict[str, Any],
) -> str:
    """Compute the CTA URL for the given event.

    Org-scoped events route to ``/{org_slug}/...``; account-level events
    (follow.*) route to the platform notification feed. If the payload
    is missing required IDs the URL falls back to the notification feed
    so the email still has a working link.
    """
    org_slug = payload.get("org_slug") or ""
    proposal_id = payload.get("proposal_id") or ""
    polis_id = payload.get("polis_id") or ""

    fallback = f"{base_url}/notifications"
    if event_type in (
        "comment.replied",
        "comment.posted_on_your_proposal",
        "comment.moderated",
        "proposal.entered_voting",
        "proposal.closed",
        "sustained_majority.floor_approached",
        # Phase 21 — all 5 new events route to the proposal page so the
        # recipient can review the delegate's action or cast their own vote.
        "delegate.voted",
        "delegate.vote_changed",
        "delegate.posted_rationale",
        "voting.halfway_delegate_silent",
        "voting.halfway_you_havent_voted",
    ):
        if not org_slug or not proposal_id:
            return fallback
        return f"{base_url}/{org_slug}/proposals/{proposal_id}"
    if event_type == "polis.created":
        if not org_slug or not polis_id:
            return fallback
        return f"{base_url}/{org_slug}/polises/{polis_id}"
    if event_type in (
        "member.join_request",
        "invitation.accepted",
        # Phase 88c — voting-model change links members to the Members page
        # where their weight + the org total are shown.
        "org.voting_model_changed",
    ):
        if not org_slug:
            return fallback
        return f"{base_url}/{org_slug}/members"
    # Phase 90a/90b/90d — shares grant/transfer/cap-blocked link to the feed.
    if event_type in ("shares.received", "shares.transfer_received", "shares.cap_blocked"):
        if not org_slug:
            return fallback
        return f"{base_url}/{org_slug}/shares"
    # Phase 86 (B-4) — content report links to the moderator reports queue.
    if event_type == "report_created":
        if not org_slug:
            return fallback
        return f"{base_url}/{org_slug}/admin/reports"
    # Phase 30.1 B4 — legacy delegate.applied / delegate.application_decided
    # link-destination block removed alongside the legacy
    # DelegateApplication surface.
    # Phase 19 — public-delegate-page workflow events.
    if event_type == "delegate_application_submitted":
        if not org_slug:
            return fallback
        return f"{base_url}/{org_slug}/delegate-applications"
    if event_type in (
        "delegate_application_approved",
        "delegate_application_denied",
    ):
        if not org_slug:
            return fallback
        return f"{base_url}/{org_slug}/delegate-profile"
    if event_type == "delegation_revoked_by_delegate":
        if not org_slug:
            return fallback
        return f"{base_url}/{org_slug}/delegations"
    if event_type == "follow.requested":
        return f"{base_url}/follows/incoming"
    if event_type == "follow.approved":
        return f"{base_url}/follows/following"
    # Phase 77 — messaging. message.received deep-links to the conversation;
    # message.org_inbox lands on the messages page (org inbox tab).
    if event_type == "message.received":
        conversation_id = payload.get("conversation_id") or ""
        if not org_slug or not conversation_id:
            return fallback
        return f"{base_url}/{org_slug}/messages/{conversation_id}"
    if event_type == "message.org_inbox":
        if not org_slug:
            return fallback
        return f"{base_url}/{org_slug}/messages"
    return fallback


# ---------------------------------------------------------------------------
# Unsubscribe token (signed; HMAC w/ settings.secret_key; 30-day expiry)
# ---------------------------------------------------------------------------

UNSUBSCRIBE_TOKEN_TTL_DAYS: int = 30


def generate_unsubscribe_token(user_id: str, event_type: str) -> str:
    """Mint a signed token encoding (user_id, event_type, exp).

    Uses jose.jwt with ``settings.secret_key`` so we don't carry a
    second crypto stack. ``GET /api/notifications/unsubscribe/{token}``
    decodes + acts.
    """
    from datetime import datetime, timedelta, timezone
    from jose import jwt

    payload = {
        "sub": user_id,
        "event_type": event_type,
        "purpose": "unsubscribe",
        "exp": datetime.now(timezone.utc) + timedelta(days=UNSUBSCRIBE_TOKEN_TTL_DAYS),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_unsubscribe_token(token: str) -> Optional[tuple[str, str]]:
    """Verify the token and return ``(user_id, event_type)`` or None on
    invalid/expired/wrong-purpose tokens. Never raises."""
    from jose import jwt, JWTError

    try:
        decoded = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except JWTError:
        return None
    if decoded.get("purpose") != "unsubscribe":
        return None
    user_id = decoded.get("sub")
    event_type = decoded.get("event_type")
    if not user_id or not event_type:
        return None
    return user_id, event_type


# ---------------------------------------------------------------------------
# Account-level transactional emails (verification / reset) — unchanged
# ---------------------------------------------------------------------------

async def send_verification_email(email: str, token: str, base_url: str) -> bool:
    """Send an email verification link."""
    link = f"{base_url}/verify-email?token={token}"
    subject = "Verify your email — Liquid Democracy"
    html_body = f"""\
<!DOCTYPE html>
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
  <h2 style="color: #1B3A5C;">Verify your email</h2>
  <p>Welcome to Liquid Democracy! Please verify your email address to participate in votes and delegations.</p>
  <p style="margin: 24px 0;">
    <a href="{link}" style="background-color: #1B3A5C; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; display: inline-block;">
      Verify your email
    </a>
  </p>
  <p style="color: #666; font-size: 14px;">Or copy and paste this link into your browser:</p>
  <p style="color: #666; font-size: 14px; word-break: break-all;">{link}</p>
  <p style="color: #999; font-size: 12px; margin-top: 32px;">This link expires in 24 hours.</p>
</body>
</html>"""
    return await send_email(email, subject, html_body)


async def send_password_reset_email(email: str, token: str, base_url: str) -> bool:
    """Send a password reset link."""
    link = f"{base_url}/reset-password?token={token}"
    subject = "Reset your password — Liquid Democracy"
    html_body = f"""\
<!DOCTYPE html>
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
  <h2 style="color: #1B3A5C;">Reset your password</h2>
  <p>We received a request to reset your password. Click the button below to choose a new password.</p>
  <p style="margin: 24px 0;">
    <a href="{link}" style="background-color: #1B3A5C; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; display: inline-block;">
      Reset your password
    </a>
  </p>
  <p style="color: #666; font-size: 14px;">Or copy and paste this link into your browser:</p>
  <p style="color: #666; font-size: 14px; word-break: break-all;">{link}</p>
  <p style="color: #999; font-size: 12px; margin-top: 32px;">This link expires in 1 hour. If you didn't request this, you can safely ignore this email.</p>
</body>
</html>"""
    return await send_email(email, subject, html_body)


# ---------------------------------------------------------------------------
# Invitation email — refactored to flow through send_org_email
# ---------------------------------------------------------------------------
#
# Backward compatibility: the external signature stays exactly the same so
# the two call sites in routes/organizations.py (create_invitations,
# resend_invitation) need no edits. The function rebuilds the template_vars
# the new helper expects + dispatches send_email directly because the
# invitation flow targets a literal email address (the invitee may not
# yet have a User row — verified-flag check in send_org_email would skip
# them).

async def send_invitation_email(
    email: str,
    token: str,
    org_name: str,
    org_slug: str,
    base_url: str,
    primary_color: str | None = None,
) -> bool:
    """Send an organization invitation email.

    Phase 13 E1 refactor: routes through the ``invitation.html`` template
    file rather than inline HTML. External signature preserved so
    ``create_invitations`` + ``resend_invitation`` in
    ``routes/organizations.py`` are unchanged.
    """
    color = (primary_color or "").strip()
    # Phase 63 (security): same strict-hex + HTML-escape treatment as
    # _prepare_org_email — org_name is user-controlled.
    if not _HEX_COLOR_RE.fullmatch(color):
        color = PLATFORM_DEFAULT_PRIMARY_COLOR
    cta_url = f"{base_url}/invite/{token}"
    subject = _format_subject("invitation", {"org_name": org_name})
    try:
        raw = _load_template("invitation")
    except FileNotFoundError:
        log.error("send_invitation_email: invitation template missing")
        return False
    html_body = Template(raw).safe_substitute(
        PRIMARY_COLOR=color,
        ORG_NAME=html.escape(str(org_name), quote=True),
        ORG_SLUG=html.escape(str(org_slug), quote=True),
        CTA_URL=html.escape(cta_url, quote=True),
    )
    return await send_email(email, subject, html_body)
