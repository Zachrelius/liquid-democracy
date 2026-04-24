"""
Email service — delivers via Resend HTTP API (preferred for cloud deploys),
falls back to SMTP via aiosmtplib, or logs to console when neither is
configured.
"""

import logging

import httpx

from settings import settings

log = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"


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


async def send_invitation_email(
    email: str, token: str, org_name: str, org_slug: str, base_url: str
) -> bool:
    """Send an organization invitation email. (Stub for Phase 4c.)"""
    link = f"{base_url}/{org_slug}/join?token={token}"
    subject = f"You're invited to join {org_name} — Liquid Democracy"
    html_body = f"""\
<!DOCTYPE html>
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
  <h2 style="color: #1B3A5C;">You're invited!</h2>
  <p>You've been invited to join <strong>{org_name}</strong> on Liquid Democracy.</p>
  <p style="margin: 24px 0;">
    <a href="{link}" style="background-color: #1B3A5C; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; display: inline-block;">
      Join {org_name}
    </a>
  </p>
  <p style="color: #666; font-size: 14px;">Or copy and paste this link into your browser:</p>
  <p style="color: #666; font-size: 14px; word-break: break-all;">{link}</p>
  <p style="color: #999; font-size: 12px; margin-top: 32px;">This invitation expires in 7 days.</p>
</body>
</html>"""
    return await send_email(email, subject, html_body)
