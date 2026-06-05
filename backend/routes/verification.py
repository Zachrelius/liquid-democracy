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
import verification_hashing
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


def _extract_ocr_fields(decision: dict) -> dict:
    """Phase 52e E1 — extract OCR fields from a Didit decision payload.

    REWRITTEN against the real payload captured in the 52d-grounding
    Z re-verify (manifest at 2026-06-05). The 52d-shipped version
    probed ``decision.id_verification`` (singular object) but Didit
    actually emits ``decision.id_verifications`` (PLURAL ARRAY) — so
    52d's extractor returned all-None on the real payload and Z's
    row sat at ``identity`` with NULL hashes. This rewrite hits the
    real paths.

    Real paths confirmed from the 2026-06-05 captured manifest
    (the redacted skeleton emitted by ``redact_payload``):
      * ``decision.id_verifications`` is a list of objects.
      * The first element carries the OCR fields:
        - ``document_number`` (str)
        - ``first_name`` / ``last_name`` / ``full_name`` (str)
        - ``date_of_birth`` (str, ISO-shape ``YYYY-MM-DD``)
        - ``parsed_address`` (structured object — preferred for the
          name+DOB+address hash because it's stable across re-
          verifications)
        - ``issuing_state`` (str, 3-char) is the document's ISSUING
          authority, NOT the holder's residence — do NOT use for
          jurisdiction. Use ``parsed_address.region``.

    Returns a dict shaped exactly as ``verification_hashing.
    compute_hashes`` expects. Missing array / element / sub-fields
    all → None for that field; ``compute_hashes`` returns None for
    any hash whose required fields aren't present. Fail-safe: empty
    array, missing element, ``parsed_address`` null, decision
    malformed — all → empty dict with None values, never a crash.
    """
    if not isinstance(decision, dict):
        return {}

    id_verifications = decision.get("id_verifications")
    iv: dict = {}
    if isinstance(id_verifications, list) and id_verifications:
        first = id_verifications[0]
        if isinstance(first, dict):
            iv = first

    def _str_or_none(v):
        if isinstance(v, str) and v.strip():
            return v
        return None

    document_number = _str_or_none(iv.get("document_number"))
    first_name = _str_or_none(iv.get("first_name"))
    last_name = _str_or_none(iv.get("last_name"))
    date_of_birth = _str_or_none(iv.get("date_of_birth"))

    # Structured address from parsed_address. Prefer structured over
    # the freeform ``address`` / ``formatted_address`` strings — the
    # parsed form is more stable across re-verifications, and
    # ``normalize_address`` expects a dict with street/city/state/zip
    # keys. Map Didit's keys to the hashing module's expected shape.
    pa = iv.get("parsed_address")
    address = None
    if isinstance(pa, dict):
        # Region is the holder's address state (full name string per
        # the captured payload). ``normalize_address`` will upper-case
        # + match against ``normalize_jurisdiction`` indirectly when
        # the address is hashed; for the residency jurisdiction
        # specifically, we extract via ``_extract_jurisdiction`` which
        # already runs through ``normalize_jurisdiction``.
        # Compose the dict in the shape ``normalize_address`` consumes.
        address = {
            "street": pa.get("street_1"),
            "city": pa.get("city"),
            "state": pa.get("region"),  # Didit's "region" = state name
            "zip": pa.get("postal_code"),
        }
        # Drop the dict entirely if every component is missing —
        # ``compute_hashes`` then returns None for the
        # name_dob_address_hash, which is the correct fail-safe
        # rather than hashing a dict full of Nones.
        if not any(address.values()):
            address = None

    return {
        "document_number": document_number,
        "first_name": first_name,
        "last_name": last_name,
        "date_of_birth": date_of_birth,
        "address": address,
    }


def _apply_decision(
    db: Session,
    *,
    target_user: models.User,
    decision: dict,
    session_row: models.VerificationSession,
    request: Request,
) -> None:
    """Phase 52d D4 + D5 — translate a Didit decision into our
    internal record fields, perform the document-number HARD BLOCK
    against the platform-wide ``doc_number_hash`` uniqueness
    invariant, and write the user record.

    Hybrid-pattern: only the derived fields land; the decision dict
    is not persisted anywhere; the Didit session is purged after
    extraction (best-effort, fail-toward-keeping-the-verification —
    see ``_purge_session_best_effort``).

    Document-number hard block:
      * If ``doc_number_hash`` is set AND already on a DIFFERENT
        existing user → REJECT this write, leave target_user
        unchanged, audit ``verification.duplicate_document``,
        update bookkeeping row to ``collision_rejected``.
      * If the existing user is the SAME user → idempotent re-verify:
        proceed normally. (This is the critical correctness property
        — a legitimate re-verify must not self-block.)
    """
    # Phase 52d D6 — fields the mapper used to read from a Didit 1:N
    # block are gone; the mapper now derives "unique" from doc-number
    # hash dedup. Compute hashes first so we can drive the mapper.
    ocr_fields = _extract_ocr_fields(decision)
    try:
        hashes = verification_hashing.compute_hashes(ocr_fields)
    except RuntimeError as e:
        # Pepper missing in this environment — fail-closed at the
        # config layer (52d invariant). We log + return a "config
        # error" status on the bookkeeping row; the user's record is
        # untouched. The webhook receiver returns 200 to Didit.
        logger.warning(
            "didit_webhook: pepper-missing, skipping hash + state write: %s", e,
        )
        session_row.status = "config_error"
        session_row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        return

    doc_number_hash = hashes["doc_number_hash"]
    name_dob_address_hash = hashes["name_dob_address_hash"]
    name_dob_hash = hashes["name_dob_hash"]

    # Pre-mapper collision lookup: is doc_number_hash on a DIFFERENT
    # existing user? This is the platform-wide hard block, and it
    # ALSO informs the mapper's uniqueness rung (no collision → the
    # user IS unique on document; mapper can hand back
    # IDENTITY_UNIQUE).
    collided_with_user: Optional[models.User] = None
    if doc_number_hash:
        collided_with_user = db.execute(
            select(models.User).where(
                models.User.doc_number_hash == doc_number_hash,
                models.User.id != target_user.id,
            ),
        ).scalars().first()

    doc_number_unique = bool(doc_number_hash) and collided_with_user is None

    mapped = verification_provider.map_decision_to_state(
        decision, doc_number_unique=doc_number_unique,
    )
    new_state = mapped["verification_state"]
    new_jurisdiction = mapped["verification_jurisdiction"]
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

    # Phase 52d D5 — document-number hard block. Same hash on a
    # different user is a "one human, two accounts" platform-wide
    # block. Same user is idempotent re-verify, NOT a block — already
    # handled by the ``id != target_user.id`` predicate in the
    # collision lookup above.
    if collided_with_user is not None:
        session_row.status = "collision_rejected"
        session_row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        log_audit_event(
            db,
            action="verification.duplicate_document",
            target_type="user",
            target_id=target_user.id,
            actor_id=target_user.id,
            details={
                "provider": "didit",
                "provider_session_id": session_row.provider_session_id,
                "collided_with_user_id": collided_with_user.id,
                "tier": verification_hashing.UNIQUENESS_DOCUMENT_HASH,
            },
            ip_address=request.client.host if request.client else None,
        )
        return

    # Apply the verification onto the target user.
    old_state = target_user.verification_state
    old_provenance = target_user.verification_provenance

    target_user.verification_state = new_state
    target_user.verification_jurisdiction = new_jurisdiction
    target_user.verification_attestation_id = new_attestation
    target_user.verification_provenance = verification.PROV_DIDIT
    target_user.verification_updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    # Phase 52d hash dedup write. ``doc_number_hash`` carries the
    # platform-wide uniqueness invariant; the two name-based hashes
    # support the Phase 52e org-scoped soft flag lookup.
    if doc_number_hash:
        target_user.doc_number_hash = doc_number_hash
        target_user.uniqueness_strength = verification_hashing.UNIQUENESS_DOCUMENT_HASH
    if name_dob_address_hash:
        target_user.name_dob_address_hash = name_dob_address_hash
    if name_dob_hash:
        target_user.name_dob_hash = name_dob_hash

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
            "uniqueness_strength": target_user.uniqueness_strength,
            "doc_hash_written": bool(doc_number_hash),
        },
        ip_address=request.client.host if request.client else None,
    )


def _purge_session_best_effort(session_id: str, target_user: models.User) -> bool:
    """Phase 52d D4 — purge the Didit session after extraction.

    Fail-toward-keeping the verification: a DELETE failure does NOT
    affect the user's already-written verification record. Returns
    True if Didit returned 2xx; False otherwise (the bookkeeping
    row's ``status`` records it; a future sweep can retry).

    demo_stub never reaches this path — the C-DEMO guard in the
    webhook receiver ensures only real ``PROV_DIDIT`` provenance
    rows ever call into the purge.
    """
    if getattr(target_user, "verification_provenance", None) != verification.PROV_DIDIT:
        return False
    return verification_provider.delete_session(session_id)


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
    # Phase 52e — adds ``approved_purged`` + ``approved_purge_failed``
    # so a replay after the purge step has run still dedupes (the
    # state-write was the load-bearing action; the purge outcome
    # doesn't change the verification record).
    if session_row.webhook_type_last == webhook_type and session_row.status in (
        "approved", "approved_purged", "approved_purge_failed",
        "declined", "collision_rejected",
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
        # Phase 52d D5 — doc_number_hash partial-unique index at the
        # DB layer caught a collision our pre-check missed (race
        # between two webhooks for two users with the same OCR doc
        # number). Treat the same as the pre-check hard-block path:
        # audit + leave existing state.
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
            action="verification.duplicate_document",
            target_type="user",
            target_id=target_user.id,
            actor_id=target_user.id,
            details={
                "provider": "didit",
                "provider_session_id": str(session_id),
                "race": True,
                "tier": verification_hashing.UNIQUENESS_DOCUMENT_HASH,
            },
            ip_address=request.client.host if request.client else None,
        )
        db.commit()

    # Phase 52e E1b — purge the Didit session after we've extracted
    # what we need. Fail-toward-keeping-the-verification: a purge
    # error is logged but does NOT touch the already-committed user
    # record. demo_stub never reaches this branch (the helper
    # short-circuits on provenance check). The Didit response is
    # already 200 — the purge runs after the commit and the receiver
    # acks regardless.
    #
    # Phase 52e adds bookkeeping-row distinction: a confirmed-deleted
    # session lands ``status = 'approved_purged'``; a delete that
    # failed (including 404 — the 52d round-trip showed 404 does NOT
    # mean "already deleted" on Didit's side) lands
    # ``status = 'approved_purge_failed'``. A later sweep can find
    # failed-purge rows and retry. The pre-purge ``approved`` status
    # is still set so the idempotency replay path keeps working
    # (status in the deduped-set).
    try:
        if session_row is not None and session_row.status == "approved":
            db.refresh(target_user)
            purged = _purge_session_best_effort(str(session_id), target_user)
            session_row = db.get(
                models.VerificationSession, session_row.id,
            )
            if session_row is not None:
                session_row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                session_row.status = (
                    "approved_purged" if purged else "approved_purge_failed"
                )
                db.commit()
            if not purged:
                logger.warning(
                    "didit_webhook: session purge unsuccessful for %s "
                    "(verification record stands; bookkeeping row marked "
                    "approved_purge_failed for retry sweep)",
                    session_id,
                )
    except Exception as e:  # noqa: BLE001 — purge must NEVER raise to the receiver
        logger.warning("didit_webhook: purge wrapper failed: %s", e)

    return {"ok": True}
