import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

import auth as auth_utils
import models
import schemas
from audit_utils import log_audit_event
from database import get_db
from email_service import send_verification_email, send_password_reset_email
from settings import settings

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)

DEMO_USERNAMES = ["alice", "admin", "dr_chen", "carol", "dave", "frank",
                  # Phase 8.5: voter02 is the canonical Decision-7 / Decision-8
                  # cross-scope persona (parent-org member, NOT in Engineering
                  # Team). Without quick-login, the sub-org demo flow is
                  # awkward to exercise from the public landing.
                  "voter02"]
DEMO_ORG_SLUG = "demo"


def _auto_join_demo_org(db: Session, user: models.User) -> None:
    """When is_public_demo is enabled, add the verified user to the demo org as
    a regular member. Missing demo org is logged and tolerated — verification
    should never fail because the demo fixtures are absent.

    Phase 9.7 W1: skip auto-join if the user is already an active member of any
    non-demo org. This prevents the regression where a user invited to a
    non-demo org via the new register-with-invitation flow gets silently
    auto-joined to demo at email-verification time. The invitation flow
    creates the inviting-org membership during registration, so by the time
    verification runs the user already has a real target org.
    """
    if not settings.is_public_demo:
        return
    demo_org = db.query(models.Organization).filter(
        models.Organization.slug == DEMO_ORG_SLUG
    ).first()
    if demo_org is None:
        log.warning(
            "is_public_demo is true but demo org (slug=%s) not found — skipping auto-join for user %s",
            DEMO_ORG_SLUG,
            user.id,
        )
        return
    # Skip auto-join when the user is already an active member of a non-demo
    # org — they came in through an invitation (or some other targeted path)
    # and shouldn't be backfilled into demo.
    other_membership = db.query(models.OrgMembership).filter(
        models.OrgMembership.user_id == user.id,
        models.OrgMembership.org_id != demo_org.id,
        models.OrgMembership.status == "active",
    ).first()
    if other_membership is not None:
        return
    existing = db.query(models.OrgMembership).filter(
        models.OrgMembership.user_id == user.id,
        models.OrgMembership.org_id == demo_org.id,
    ).first()
    if existing:
        return
    membership = models.OrgMembership(
        user_id=user.id,
        org_id=demo_org.id,
        role="member",
        status="active",
    )
    db.add(membership)
    db.flush()


def _consume_invitation(
    db: Session,
    *,
    invitation_token: str,
    user: models.User,
    request_email: str,
    via: str,
    request: Request,
) -> models.Invitation:
    """Validate + consume an invitation token in the context of register/login.

    Returns the Invitation row on success; raises HTTPException(400) on any
    validation failure (token not found, expired/revoked/accepted, or email
    mismatch). On success, this function:
      - Creates an active OrgMembership for `user` in the inviting org
        (skipped idempotently when one already exists active).
      - Marks the invitation `accepted` with `accepted_at = now`.
      - Logs an audit event with action `invitation.accepted_via_<via>`.

    The caller is responsible for the surrounding `db.commit()`.
    """
    inv = db.query(models.Invitation).filter(
        models.Invitation.token == invitation_token,
        models.Invitation.status == "pending",
    ).first()
    now = _now()
    if not inv or inv.expires_at < now:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired invitation token",
        )

    if inv.email.lower() != request_email.lower():
        raise HTTPException(
            status_code=400,
            detail=(
                f"This invitation is for {inv.email}, but you registered "
                f"with {request_email}. Ask the inviter to resend to your address."
            ),
        )

    # Idempotent OrgMembership: if the user is already active in the inviting
    # org, leave it alone. If suspended/pending, reactivate to the invitation's
    # role (matches the existing accept_invitation route's pattern).
    existing = db.query(models.OrgMembership).filter(
        models.OrgMembership.user_id == user.id,
        models.OrgMembership.org_id == inv.org_id,
    ).first()
    if existing:
        if existing.status != "active":
            existing.status = "active"
            existing.role = inv.role
    else:
        db.add(models.OrgMembership(
            user_id=user.id,
            org_id=inv.org_id,
            role=inv.role,
            status="active",
        ))

    inv.status = "accepted"
    inv.accepted_at = now
    db.flush()

    log_audit_event(
        db,
        action=f"invitation.accepted_via_{via}",
        target_type="invitation",
        target_id=inv.id,
        actor_id=user.id,
        details={
            "invitation_id": inv.id,
            "org_id": inv.org_id,
            "role": inv.role,
            "invited_email": inv.email,
            "accepting_user_id": user.id,
        },
        ip_address=request.client.host if request.client else None,
    )
    return inv


def _now() -> datetime:
    """Naive UTC datetime — SQLite strips timezone info on storage, so
    comparisons between stored and fresh values must both be naive."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _create_refresh_token(db: Session, user_id: str) -> str:
    """Create and persist a new refresh token for the given user."""
    token = secrets.token_urlsafe(48)
    rt = models.RefreshToken(
        user_id=user_id,
        token=token,
        expires_at=_now() + timedelta(days=7),
    )
    db.add(rt)
    db.flush()
    return token


def _revoke_all_refresh_tokens(db: Session, user_id: str) -> int:
    """Revoke all active refresh tokens for a user. Returns count revoked."""
    now = _now()
    tokens = db.query(models.RefreshToken).filter(
        models.RefreshToken.user_id == user_id,
        models.RefreshToken.revoked_at.is_(None),
    ).all()
    count = 0
    for t in tokens:
        t.revoked_at = now
        count += 1
    db.flush()
    return count


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

@router.post("/register", response_model=schemas.RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: schemas.RegisterRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    if db.query(models.User).filter(models.User.username == body.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")

    if db.query(models.User).filter(models.User.email == body.email).first():
        raise HTTPException(status_code=400, detail="Email already in use")

    # Phase 9.7 W1 — pre-validate the invitation token BEFORE creating the
    # user account so a bad token returns 400 without leaving an orphaned user
    # row behind. The full validation (including email match) happens again
    # inside _consume_invitation after the user is created.
    if body.invitation_token:
        pre_check = db.query(models.Invitation).filter(
            models.Invitation.token == body.invitation_token,
            models.Invitation.status == "pending",
        ).first()
        if not pre_check or pre_check.expires_at < _now():
            raise HTTPException(
                status_code=400,
                detail="Invalid or expired invitation token",
            )
        if pre_check.email.lower() != body.email.lower():
            raise HTTPException(
                status_code=400,
                detail=(
                    f"This invitation is for {pre_check.email}, but you registered "
                    f"with {body.email}. Ask the inviter to resend to your address."
                ),
            )

    # Check if this is the very first user (no users exist yet)
    is_first_user = db.query(models.User).count() == 0

    user = models.User(
        username=body.username,
        display_name=body.display_name,
        email=body.email,
        email_verified=is_first_user,  # Auto-verify first user
        password_hash=auth_utils.hash_password(body.password),
        is_admin=is_first_user,  # First user gets admin privileges
    )
    db.add(user)
    db.flush()

    # Create email verification record (skip sending for first user since auto-verified)
    token = secrets.token_urlsafe(48)
    verification = models.EmailVerification(
        user_id=user.id,
        email=body.email,
        token=token,
        expires_at=_now() + timedelta(hours=24),
    )
    if is_first_user:
        verification.verified_at = _now()
    db.add(verification)

    log_audit_event(
        db,
        action="user.registered",
        target_type="user",
        target_id=user.id,
        actor_id=user.id,
        details={"username": user.username, "email": user.email, "is_first_user": is_first_user},
        ip_address=request.client.host if request.client else None,
    )

    # Phase 9.7 W1 — consume the invitation in the same transaction as the
    # user-create. This creates the OrgMembership in the inviting org and
    # marks the invitation accepted; the resulting non-demo membership also
    # gates _auto_join_demo_org out of demo at email-verification time.
    if body.invitation_token:
        _consume_invitation(
            db,
            invitation_token=body.invitation_token,
            user=user,
            request_email=body.email,
            via="registration",
            request=request,
        )

    db.commit()
    db.refresh(user)

    # Send verification email out-of-band so a slow/failing SMTP doesn't
    # block the registration response (would 504 at the edge proxy).
    if not is_first_user:
        background_tasks.add_task(send_verification_email, body.email, token, settings.base_url)

    # Build response with is_first_user flag
    response = schemas.RegisterResponse.model_validate(user)
    response.is_first_user = is_first_user
    return response


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

@router.post("/login", response_model=schemas.TokenResponse)
def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    invitation_token: Optional[str] = Form(default=None),
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(models.User.username == form_data.username).first()
    if not user or not auth_utils.verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    log_audit_event(
        db,
        action="user.login",
        target_type="user",
        target_id=user.id,
        actor_id=user.id,
        details={"username": user.username},
        ip_address=request.client.host if request.client else None,
    )

    # Phase 9.7 W1 — optional invitation consumption. Mirrors register's
    # behavior: validate token, validate email match (using the user's
    # current email), then create-or-reuse OrgMembership and audit. If the
    # user is already a member of the inviting org, the invitation is still
    # marked accepted and a `invitation.accepted_via_login` event is logged
    # (idempotent membership; auditable consumption).
    if invitation_token:
        if not user.email:
            raise HTTPException(
                status_code=400,
                detail="Invalid or expired invitation token",
            )
        _consume_invitation(
            db,
            invitation_token=invitation_token,
            user=user,
            request_email=user.email,
            via="login",
            request=request,
        )

    access_token = auth_utils.create_access_token(user.id)
    refresh_token = _create_refresh_token(db, user.id)

    db.commit()

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
    }


# ---------------------------------------------------------------------------
# Token refresh
# ---------------------------------------------------------------------------

@router.post("/refresh", response_model=schemas.TokenResponse)
def refresh_token(
    body: schemas.RefreshTokenRequest,
    db: Session = Depends(get_db),
):
    now = _now()
    rt = db.query(models.RefreshToken).filter(
        models.RefreshToken.token == body.refresh_token,
    ).first()

    if not rt or rt.revoked_at is not None or rt.expires_at < now:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    # Rotate: revoke old, issue new
    rt.revoked_at = now
    db.flush()

    new_access = auth_utils.create_access_token(rt.user_id)
    new_refresh = _create_refresh_token(db, rt.user_id)
    db.commit()

    return {
        "access_token": new_access,
        "refresh_token": new_refresh,
    }


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

@router.post("/logout", status_code=200)
def logout(
    body: schemas.LogoutRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    rt = db.query(models.RefreshToken).filter(
        models.RefreshToken.token == body.refresh_token,
        models.RefreshToken.user_id == current_user.id,
    ).first()
    if rt and rt.revoked_at is None:
        rt.revoked_at = _now()

    log_audit_event(
        db,
        action="user.logout",
        target_type="user",
        target_id=current_user.id,
        actor_id=current_user.id,
        details={},
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return {"message": "Logged out successfully"}


@router.post("/logout-all", status_code=200)
def logout_all(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    count = _revoke_all_refresh_tokens(db, current_user.id)

    log_audit_event(
        db,
        action="user.logout_all",
        target_type="user",
        target_id=current_user.id,
        actor_id=current_user.id,
        details={"tokens_revoked": count},
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return {"message": f"Logged out of all devices ({count} sessions revoked)"}


# ---------------------------------------------------------------------------
# Email verification
# ---------------------------------------------------------------------------

@router.post("/verify-email", status_code=200)
def verify_email(
    body: schemas.VerifyEmailRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    now = _now()
    record = db.query(models.EmailVerification).filter(
        models.EmailVerification.token == body.token,
    ).first()

    if not record or record.verified_at is not None or record.expires_at < now:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired verification token",
        )

    record.verified_at = now
    user = db.get(models.User, record.user_id)
    if user:
        user.email_verified = True
        # Public-demo deployments: auto-add verified users to the demo org.
        _auto_join_demo_org(db, user)

    log_audit_event(
        db,
        action="user.email_verified",
        target_type="user",
        target_id=record.user_id,
        actor_id=record.user_id,
        details={"email": record.email},
        ip_address=request.client.host if request.client else None,
    )

    db.commit()
    return {"message": "Email verified successfully"}


@router.post("/resend-verification", status_code=200)
@limiter.limit("1/minute")
async def resend_verification(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    if current_user.email_verified:
        return {"message": "Email is already verified"}

    if not current_user.email:
        raise HTTPException(status_code=400, detail="No email address on file")

    # Check rate limit: no new token if one was created in the last minute
    one_min_ago = _now() - timedelta(minutes=1)
    recent = db.query(models.EmailVerification).filter(
        models.EmailVerification.user_id == current_user.id,
        models.EmailVerification.created_at > one_min_ago,
    ).first()
    if recent:
        raise HTTPException(status_code=429, detail="Please wait before requesting another verification email")

    token = secrets.token_urlsafe(48)
    verification = models.EmailVerification(
        user_id=current_user.id,
        email=current_user.email,
        token=token,
        expires_at=_now() + timedelta(hours=24),
    )
    db.add(verification)
    db.commit()

    await send_verification_email(current_user.email, token, settings.base_url)

    return {"message": "Verification email sent"}


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------

@router.post("/forgot-password", status_code=200)
@limiter.limit("3/hour")
async def forgot_password(
    body: schemas.ForgotPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    # Always return the same message to prevent account enumeration
    success_msg = {"message": "If that email is registered, we've sent a password reset link."}

    user = db.query(models.User).filter(models.User.email == body.email).first()
    if not user:
        return success_msg

    token = secrets.token_urlsafe(48)
    reset = models.PasswordReset(
        user_id=user.id,
        token=token,
        expires_at=_now() + timedelta(hours=1),
    )
    db.add(reset)

    log_audit_event(
        db,
        action="user.password_reset_requested",
        target_type="user",
        target_id=user.id,
        actor_id=user.id,
        details={"email": user.email},
        ip_address=request.client.host if request.client else None,
    )

    db.commit()

    await send_password_reset_email(user.email, token, settings.base_url)

    return success_msg


@router.post("/reset-password", status_code=200)
def reset_password(
    body: schemas.ResetPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    now = _now()
    record = db.query(models.PasswordReset).filter(
        models.PasswordReset.token == body.token,
    ).first()

    if not record or record.used_at is not None or record.expires_at < now:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired reset token",
        )

    record.used_at = now
    user = db.get(models.User, record.user_id)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    user.password_hash = auth_utils.hash_password(body.new_password)

    # Invalidate all refresh tokens
    _revoke_all_refresh_tokens(db, user.id)

    log_audit_event(
        db,
        action="user.password_reset_completed",
        target_type="user",
        target_id=user.id,
        actor_id=user.id,
        details={},
        ip_address=request.client.host if request.client else None,
    )

    db.commit()
    return {"message": "Password has been reset successfully"}


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@router.get("/demo-users")
def demo_users(db: Session = Depends(get_db)):
    """Return a list of demo users for quick-switch login.
    Available when either debug or is_public_demo is enabled.
    """
    if not (settings.debug or settings.is_public_demo):
        raise HTTPException(status_code=404, detail="Not found")
    users = db.query(models.User).filter(
        models.User.username.in_(DEMO_USERNAMES)
    ).all()
    return [
        {"username": u.username, "display_name": u.display_name}
        for u in users
    ]


@router.post("/demo-login", response_model=schemas.TokenResponse)
def demo_login(
    body: schemas.DemoLoginRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Passwordless login for whitelisted demo personas.
    Available when either debug or is_public_demo is enabled.
    """
    if not (settings.debug or settings.is_public_demo):
        raise HTTPException(status_code=404, detail="Not found")

    # 404 (not 403) so the endpoint reveals nothing about the allowlist when
    # the flag is off — and an unknown username gets the same response as a
    # real-but-not-allowlisted one.
    if body.username not in DEMO_USERNAMES:
        raise HTTPException(status_code=404, detail="Not found")

    user = db.query(models.User).filter(models.User.username == body.username).first()
    if user is None:
        raise HTTPException(status_code=404, detail="Not found")

    log_audit_event(
        db,
        action="user.demo_login",
        target_type="user",
        target_id=user.id,
        actor_id=user.id,
        details={"username": user.username},
        ip_address=request.client.host if request.client else None,
    )

    access_token = auth_utils.create_access_token(user.id)
    refresh_token = _create_refresh_token(db, user.id)

    db.commit()

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
    }


@router.get("/me", response_model=schemas.UserOut)
def me(current_user: models.User = Depends(auth_utils.get_current_user)):
    return current_user


@router.patch("/me", response_model=schemas.UserOut)
def update_me(
    body: schemas.UserUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    if body.display_name is not None:
        current_user.display_name = body.display_name
    if body.default_follow_policy is not None:
        current_user.default_follow_policy = body.default_follow_policy
    db.commit()
    db.refresh(current_user)
    return current_user


@router.post("/change-password", status_code=200)
def change_password(
    body: schemas.ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    if not auth_utils.verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    current_user.password_hash = auth_utils.hash_password(body.new_password)
    # Invalidate all refresh tokens after password change
    _revoke_all_refresh_tokens(db, current_user.id)
    db.commit()
    return {"message": "Password changed successfully"}
