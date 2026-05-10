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
import logging
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
    "proposal.entered_voting": "Voting has opened on '{proposal_title}'",
    "proposal.closed": "Proposal '{proposal_title}' has closed",
    "sustained_majority.floor_approached": "Vote support nearing floor: '{proposal_title}'",
    "member.join_request": "New member request to join {org_name}",
    "invitation.accepted": "{actor_display_name} joined {org_name}",
    "delegate.applied": "New delegate application in {org_name}",
    "delegate.application_decided": "Your delegate application was {decision}",
    "follow.requested": "{actor_display_name} requested to follow you",
    "follow.approved": "{actor_display_name} approved your follow request",
    "polis.created": "New deliberation in {org_name}",
    "invitation": "You're invited to join {org_name} — Liquid Democracy",
    "digest.daily": "Your Liquid Democracy daily digest",
    "digest.weekly": "Your Liquid Democracy weekly digest",
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
    return color or PLATFORM_DEFAULT_PRIMARY_COLOR


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

def send_org_email(
    db: Session,
    user_id: str,
    org_id: Optional[str],
    template_key: str,
    template_vars: dict[str, Any],
) -> bool:
    """Render and send an email for the given user + template_key.

    Steps:
      1. Look up the user. If user has no email or hasn't verified it,
         skip silently (returns False) — preserves the existing
         send_invitation_email behavior of not delivering to unverified
         addresses except the invitation flow which targets a literal
         email address (handled separately by ``send_invitation_email``).
      2. Look up the org (if ``org_id`` is non-null) and resolve its
         branded primary color.
      3. Load the HTML template + substitute ``${PRIMARY_COLOR}`` and the
         caller-provided ``template_vars``.
      4. Format the subject line.
      5. Dispatch ``send_email`` (Resend / SMTP / console) via
         ``asyncio.run`` since this entry point is sync.

    Returns the boolean from the transport. Sync wrapper around the
    async transport so callers (notification_emit's BackgroundTasks
    queue, the digest scheduler) don't need to manage event loops.
    """
    user = db.get(models.User, user_id)
    if user is None:
        log.warning("send_org_email: user %s not found; skipping", user_id)
        return False
    if not user.email:
        log.debug("send_org_email: user %s has no email; skipping", user_id)
        return False
    if not user.email_verified:
        log.debug(
            "send_org_email: user %s email not verified; skipping",
            user_id,
        )
        return False

    org = db.get(models.Organization, org_id) if org_id else None
    primary_color = _resolve_org_primary_color(org)

    try:
        raw_template = _load_template(template_key)
    except FileNotFoundError:
        log.error(
            "send_org_email: template not found for key %r; skipping",
            template_key,
        )
        return False

    subs: dict[str, str] = {"PRIMARY_COLOR": primary_color}
    # Translate template_vars keys to UPPER_CASE for ${VAR_NAME} substitution.
    for k, v in template_vars.items():
        if v is None:
            subs[k.upper()] = ""
        else:
            subs[k.upper()] = str(v)

    # safe_substitute leaves unknown placeholders as-is rather than KeyError;
    # surfaces missing-key bugs in dev (visible in the rendered email) but
    # never crashes a send.
    html_body = Template(raw_template).safe_substitute(subs)
    subject = _format_subject(template_key, template_vars)

    return _run_async(send_email(user.email, subject, html_body))


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
        "polis_title": payload.get("title") or "",
        "polis_id": polis_id,
        "support_fraction": payload.get("support_fraction") or "",
        "floor": payload.get("floor") or "",
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
    "delegate.applied": "Review application",
    "delegate.application_decided": "Open organization",
    "follow.requested": "Review request",
    "follow.approved": "View profile",
    "polis.created": "Open Polis",
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
        "proposal.entered_voting",
        "proposal.closed",
        "sustained_majority.floor_approached",
    ):
        if not org_slug or not proposal_id:
            return fallback
        return f"{base_url}/{org_slug}/proposals/{proposal_id}"
    if event_type == "polis.created":
        if not org_slug or not polis_id:
            return fallback
        return f"{base_url}/{org_slug}/polises/{polis_id}"
    if event_type in ("member.join_request", "invitation.accepted"):
        if not org_slug:
            return fallback
        return f"{base_url}/{org_slug}/members"
    if event_type in ("delegate.applied", "delegate.application_decided"):
        if not org_slug:
            return fallback
        return f"{base_url}/{org_slug}/delegates"
    if event_type == "follow.requested":
        return f"{base_url}/follows/incoming"
    if event_type == "follow.approved":
        return f"{base_url}/follows/following"
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
    color = (primary_color or "").strip() or PLATFORM_DEFAULT_PRIMARY_COLOR
    cta_url = f"{base_url}/invite/{token}"
    subject = _format_subject("invitation", {"org_name": org_name})
    try:
        raw = _load_template("invitation")
    except FileNotFoundError:
        log.error("send_invitation_email: invitation template missing")
        return False
    html_body = Template(raw).safe_substitute(
        PRIMARY_COLOR=color,
        ORG_NAME=org_name,
        ORG_SLUG=org_slug,
        CTA_URL=cta_url,
    )
    return await send_email(email, subject, html_body)
