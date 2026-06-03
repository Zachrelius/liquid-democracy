"""Phase 52a — verification session initiation + Didit webhook receiver.

Two endpoints:

  * ``POST /api/verification/session`` (authenticated) — opens a
    Didit hosted-flow session for the current user. Persists a
    ``VerificationSession`` row so the webhook receiver can resolve
    the inbound ``session_id`` back to a user and dedupe replays.

  * ``POST /api/webhooks/didit`` (signature-authenticated) — accepts
    Didit's signed webhook, verifies HMAC + freshness, dedupes by
    ``(provider_session_id, webhook_type_last)``, and updates the
    target user's verification record on Approved. On nullifier
    collision (the same opaque handle on a different existing user)
    the second account is left at its prior state and a
    ``verification.nullifier_collision`` audit row is written; the
    webhook returns 200 (we accepted; we declined to apply).

Hybrid-pattern invariant (spec): only state + nullifier +
attestation id + coarse jurisdiction are stored. Raw decision body
is consumed and discarded.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from slowapi import Limiter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import auth as auth_utils
import models
import verification
import verification_provider
from audit_utils import log_audit_event
from database import get_db
from rate_limit_utils import bypass_or_remote_address

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["verification"])
limiter = Limiter(key_func=bypass_or_remote_address)


# ---------------------------------------------------------------------------
# Disclosure copy returned to the FE before the redirect
# ---------------------------------------------------------------------------

CONSENT_DISCLOSURE = (
    "We send your ID to our identity-verification partner to confirm "
    "who you are. We do not keep a copy of your documents or selfie — "
    "only a record that the check happened and the result. You can "
    "cancel the verification at any time before completing it."
)


class _SessionCreateBody(BaseModel):
    # Reserved for future fields (e.g. preferred locale). Empty body
    # is accepted; the user is taken from the auth context.
    pass


class _SessionOut(BaseModel):
    session_url: str
    session_id: str
    consent_disclosure: str


# ---------------------------------------------------------------------------
# C-SESSION — initiate a Didit verification session for current_user
# ---------------------------------------------------------------------------


@router.post("/verification/session", response_model=_SessionOut)
@limiter.limit("5/minute")
def create_verification_session(
    request: Request,
    body: Optional[_SessionCreateBody] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Open a Didit verification session for ``current_user``.

    Calls the provider, persists a bookkeeping row, returns the
    hosted-flow URL + an opaque session id + consent disclosure
    copy the FE shows immediately before redirecting / opening the
    Didit modal.
    """
    try:
        result = verification_provider.create_session(current_user.id)
    except RuntimeError as e:
        # Missing env config in this environment.
        logger.warning(
            "verification_session: provider misconfigured: %s", e,
        )
        raise HTTPException(
            status_code=503,
            detail="Verification is temporarily unavailable. Please try again later.",
        )
    except Exception as e:  # noqa: BLE001 — upstream failure
        logger.warning(
            "verification_session: provider call failed: %s", e,
        )
        raise HTTPException(
            status_code=502,
            detail="Could not start verification. Please try again.",
        )

    session_row = models.VerificationSession(
        user_id=current_user.id,
        provider_session_id=result["session_id"],
        status="initiated",
    )
    db.add(session_row)
    db.commit()

    log_audit_event(
        db,
        action="verification.session_initiated",
        target_type="user",
        target_id=current_user.id,
        actor_id=current_user.id,
        details={
            "provider": "didit",
            "provider_session_id": result["session_id"],
        },
        ip_address=request.client.host if request.client else None,
    )

    return _SessionOut(
        session_url=result["session_url"],
        session_id=result["session_id"],
        consent_disclosure=CONSENT_DISCLOSURE,
    )


# ---------------------------------------------------------------------------
# C-WEBHOOK — Didit signed webhook
# ---------------------------------------------------------------------------


async def _read_raw_body(request: Request) -> bytes:
    body = await request.body()
    return body if isinstance(body, (bytes, bytearray)) else b""


def _apply_decision(
    db: Session,
    *,
    target_user: models.User,
    decision: dict,
    session_row: models.VerificationSession,
    request: Request,
) -> None:
    """Translate a Didit decision into our internal record fields and
    write them to ``target_user``. Performs nullifier collision check
    BEFORE the write — on collision the user row is untouched and an
    audit event is written.

    Hybrid-pattern: only the derived fields land; the decision dict
    is not persisted anywhere.
    """
    mapped = verification_provider.map_decision_to_state(decision)
    new_state = mapped["verification_state"]
    new_jurisdiction = mapped["verification_jurisdiction"]
    new_nullifier = mapped["verification_nullifier"]
    new_attestation = mapped["verification_attestation_id"]

    if new_state == verification.EMAIL_ONLY:
        # Decision didn't pass the ID-verification check — leave the
        # user's state untouched. The webhook is acknowledged either
        # way; the bookkeeping row's status reflects the outcome.
        session_row.status = "declined"
        session_row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        log_audit_event(
            db,
            action="verification.declined",
            target_type="user",
            target_id=target_user.id,
            actor_id=target_user.id,
            details={
                "provider": "didit",
                "provider_session_id": session_row.provider_session_id,
            },
            ip_address=request.client.host if request.client else None,
        )
        return

    # Nullifier collision check — only when we have a non-NULL
    # nullifier from the provider. If the SAME nullifier already sits
    # on a DIFFERENT user, this is "one human, two accounts." Spec
    # policy (locked Z-fork): reject the second; do not overwrite,
    # do not merge; audit + leave the second account unchanged.
    if new_nullifier:
        existing = db.execute(
            select(models.User).where(
                models.User.verification_nullifier == new_nullifier,
            ),
        ).scalars().first()
        if existing is not None and existing.id != target_user.id:
            session_row.status = "collision_rejected"
            session_row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            log_audit_event(
                db,
                action="verification.nullifier_collision",
                target_type="user",
                target_id=target_user.id,
                actor_id=target_user.id,
                details={
                    "provider": "didit",
                    "provider_session_id": session_row.provider_session_id,
                    "collided_with_user_id": existing.id,
                },
                ip_address=request.client.host if request.client else None,
            )
            return

    # Apply the verification onto the target user.
    old_state = target_user.verification_state
    old_provenance = target_user.verification_provenance

    target_user.verification_state = new_state
    target_user.verification_jurisdiction = new_jurisdiction
    target_user.verification_nullifier = new_nullifier
    target_user.verification_attestation_id = new_attestation
    target_user.verification_provenance = verification.PROV_DIDIT
    target_user.verification_updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

    session_row.status = "approved"
    session_row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

    log_audit_event(
        db,
        action="verification.completed",
        target_type="user",
        target_id=target_user.id,
        actor_id=target_user.id,
        details={
            "provider": "didit",
            "provider_session_id": session_row.provider_session_id,
            "old_state": old_state,
            "new_state": new_state,
            "old_provenance": old_provenance,
            "new_provenance": verification.PROV_DIDIT,
            "jurisdiction": new_jurisdiction,
        },
        ip_address=request.client.host if request.client else None,
    )


@router.post("/webhooks/didit")
async def didit_webhook(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Didit webhook receiver. Signature + freshness verified;
    idempotent on ``(provider_session_id, webhook_type)``.

    Returns 200 with ``{"ok": True}`` on accept (including the
    deduped no-op and the explicitly-declined-to-apply paths).
    Returns 401 on signature / freshness failure. Returns 200 with
    ``{"ok": False, "reason": "..."}`` on payload shape issues we
    can't usefully reject (so Didit doesn't retry a malformed body
    indefinitely).
    """
    raw_body = await _read_raw_body(request)
    signature = request.headers.get("x-signature") or request.headers.get("X-Signature")
    timestamp = request.headers.get("x-timestamp") or request.headers.get("X-Timestamp")

    if not verification_provider.verify_webhook(raw_body, signature, timestamp):
        raise HTTPException(status_code=401, detail="invalid signature")

    try:
        import json
        payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception:
        return {"ok": False, "reason": "malformed_payload"}

    if not isinstance(payload, dict):
        return {"ok": False, "reason": "malformed_payload"}

    # Phase 52c — emit a single structured log line carrying the
    # PII-safe skeleton of this payload so 52d can fix the mapper
    # against ground truth instead of guesses. The redactor's
    # allow-list is the load-bearing PII boundary; see
    # verification_provider.redact_payload. This is pure
    # instrumentation — NO state writes are gated on it; if logging
    # itself raises (unlikely), the receiver continues to apply the
    # decision normally so live verification is never blocked by the
    # capture path.
    try:
        skeleton = verification_provider.redact_payload(payload)
        logger.info(
            "didit_webhook_payload_capture skeleton=%s",
            json.dumps(skeleton, default=str, sort_keys=True),
        )
    except Exception as e:  # noqa: BLE001 — instrumentation must never break the receiver
        logger.warning("didit_webhook_payload_capture failed: %s", e)

    webhook_type = str(payload.get("webhook_type") or payload.get("event") or "")
    session_id = (
        payload.get("session_id")
        or payload.get("id")
        or (payload.get("session") or {}).get("id")
    )
    if not session_id:
        return {"ok": False, "reason": "missing_session_id"}

    session_row = db.execute(
        select(models.VerificationSession).where(
            models.VerificationSession.provider_session_id == str(session_id),
        ),
    ).scalars().first()

    if session_row is None:
        # We don't recognize this session — could be a probe or a
        # stale replay from a different env. Acknowledge to avoid
        # retries; do not fabricate state.
        return {"ok": False, "reason": "unknown_session"}

    # Idempotency: same (session, webhook_type) twice is a no-op 200.
    if session_row.webhook_type_last == webhook_type and session_row.status in (
        "approved", "declined", "collision_rejected",
    ):
        return {"ok": True, "deduped": True}

    target_user = db.get(models.User, session_row.user_id)
    if target_user is None:
        # User was deleted between session and webhook. Audit + ack.
        session_row.webhook_type_last = webhook_type
        session_row.status = "user_missing"
        session_row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
        return {"ok": False, "reason": "user_missing"}

    decision = payload.get("decision")
    if not isinstance(decision, dict):
        # Status updates without a decision body (e.g. "session.opened"):
        # just record the webhook_type and ack.
        session_row.webhook_type_last = webhook_type
        session_row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
        return {"ok": True}

    try:
        _apply_decision(
            db,
            target_user=target_user,
            decision=decision,
            session_row=session_row,
            request=request,
        )
        session_row.webhook_type_last = webhook_type
        db.commit()
    except IntegrityError:
        # Nullifier collision raced past our pre-check (unique index
        # at DB layer caught it). Treat the same as the pre-check
        # collision path — audit + leave existing state.
        db.rollback()
        session_row = db.get(
            models.VerificationSession, session_row.id,
        )
        if session_row is not None:
            session_row.webhook_type_last = webhook_type
            session_row.status = "collision_rejected"
            session_row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        log_audit_event(
            db,
            action="verification.nullifier_collision",
            target_type="user",
            target_id=target_user.id,
            actor_id=target_user.id,
            details={
                "provider": "didit",
                "provider_session_id": str(session_id),
                "race": True,
            },
            ip_address=request.client.host if request.client else None,
        )
        db.commit()

    return {"ok": True}
