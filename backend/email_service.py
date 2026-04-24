"""
Email service — sends emails via SMTP or logs to console in dev mode.
"""

import logging

from settings import settings

log = logging.getLogger(__name__)


async def send_email(to: str, subject: str, html_body: str) -> bool:
    """Send an email. If SMTP is not configured, log to console instead."""
    if not settings.smtp_host:
        # Dev mode — print email to console so devs can see links
        log.info("=" * 60)
        log.info("EMAIL (console mode — SMTP not configured)")
        log.info(f"  To:      {to}")
        log.info(f"  Subject: {subject}")
        log.info(f"  Body:")
        print(html_body)
        log.info("=" * 60)
        return True

    try:
        import aiosmtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.from_email
        msg["To"] = to
        msg.attach(MIMEText(html_body, "html"))

        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user or None,
            password=settings.smtp_password or None,
            start_tls=True,
            timeout=20,
        )
        log.info(f"Email sent to {to}: {subject}")
        return True
    except Exception as e:
        # Single-line error first (Railway's log viewer flattens multi-line).
        log.error(
            f"Failed to send email to {to}: {subject} | "
            f"{type(e).__name__}: {e} | "
            f"host={settings.smtp_host}:{settings.smtp_port} user={settings.smtp_user}"
        )
        # Full traceback as a separate entry for when the viewer preserves it.
        log.exception(f"Failed to send email to {to}: {subject}")
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
