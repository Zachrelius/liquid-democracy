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
from sqlalchemy.orm import Session

import auth as auth_utils
import models
import verification
import verification_hashing
import verification_metering
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
    # Phase 52b — optional triggering org id. When the user arrives
    # at "Start verification" via an org's gate (Phase 52e Mode 1 or
    # Mode 2 prompts), the FE includes that org_id so per-org
    # consumption can be recorded. Settings-initiated verifications
    # without an org context leave it None (counted toward the
    # shared pool but not attributed to any org).
    org_id: Optional[str] = None


class _SessionOut(BaseModel):
    session_url: str
    session_id: str
    consent_disclosure: str


class _PoolUnavailableOut(BaseModel):
    """Phase 52b B3 — structured response on empty-pool block.
    Surfaces enough info for the FE to render the message with the
    real reset date. The FE keys on ``error='pool_unavailable'``."""
    error: str
    reset_date: str
    days_until_reset: int


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

    Phase 52b — the authoritative empty-pool hard stop. Checks
    capacity BEFORE calling Didit. If the shared monthly free pool
    is exhausted, returns 503 with a structured ``pool_unavailable``
    body the FE renders as the "unavailable this month" message.
    NO Didit session is created (no spend, fail-safe toward not
    consuming).
    """
    # Phase 52b B2 — capacity check at the authoritative gate.
    # The gate-display check (FE) reads the same predicate via the
    # /api/verification/pool-status endpoint, but the pool could
    # empty between display and click; this is the real hard stop.
    if not verification_metering.has_capacity(db):
        status = verification_metering.capacity_status(db)
        raise HTTPException(
            status_code=503,
            detail={
                "error": "pool_unavailable",
                "reset_date": status["reset_date"],
                "days_until_reset": status["days_until_reset"],
            },
        )

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

    # Phase 52e Stage 1 hotfix — Didit returns the SAME session_id
    # for back-to-back create-session calls from the same vendor_data
    # while a session is still in-flight (its server-side recognition
    # of "you already have an open session for this user"). Our
    # ``provider_session_id`` carries a unique constraint, so a naive
    # INSERT on the second call hits a UniqueViolation → 500. Real
    # users abandon verifications (camera issue, interruption) and
    # come back; they must get a clean retry, not a 500.
    #
    # Idempotency: look up by ``provider_session_id`` first. If the
    # row already exists AND it's for this same user, reuse it
    # (refresh ``updated_at`` so the bookkeeping reflects the most
    # recent attempt). If somehow the same session id maps to a
    # DIFFERENT user, refuse — that's a vendor_data scoping break
    # at Didit's side and the safe action is to surface, not to
    # silently re-point.
    existing_row = db.execute(
        select(models.VerificationSession).where(
            models.VerificationSession.provider_session_id == result["session_id"],
        ),
    ).scalars().first()
    if existing_row is not None:
        if existing_row.user_id != current_user.id:
            logger.warning(
                "verification_session: session_id %s already exists for a "
                "DIFFERENT user (%s vs current %s). Refusing to reassign.",
                result["session_id"], existing_row.user_id, current_user.id,
            )
            raise HTTPException(
                status_code=502,
                detail="Could not start verification. Please try again.",
            )
        existing_row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        # Phase 52b — refresh the triggering org context if the user
        # came back via a different gate. If body org_id is None this
        # leaves the prior value intact (don't accidentally erase a
        # known triggering org because the user re-clicked from
        # Settings).
        body_org_id = body.org_id if body is not None else None
        if body_org_id and existing_row.triggering_org_id != body_org_id:
            existing_row.triggering_org_id = body_org_id
        db.commit()
        session_row = existing_row
    else:
        session_row = models.VerificationSession(
            user_id=current_user.id,
            provider_session_id=result["session_id"],
            status="initiated",
            # Phase 52b — capture the triggering org if the FE knows
            # which gate sent the user here. Null when initiated from
            # Settings without an org context.
            triggering_org_id=(body.org_id if body is not None else None),
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


# ---------------------------------------------------------------------------
# Phase 52b — pool status (B2 gate-display + B4 admin visibility)
# ---------------------------------------------------------------------------


class _PoolStatusOut(BaseModel):
    """Light pool-status surface for the FE gate-display check.
    Public (any authenticated user) — exposes only the boolean
    capacity + reset date, not the actual count. Per-org breakdown
    is the admin-only endpoint below."""
    has_capacity: bool
    reset_date: str
    days_until_reset: int


@router.get("/verification/pool-status", response_model=_PoolStatusOut)
def get_pool_status(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Phase 52b B2 call site 1 — gate-display check. Any
    authenticated user can read this. The FE keys verification gates
    + the "Start verification" button on ``has_capacity``: when
    False, render the unavailable-this-month copy instead of a live
    button.

    Deliberately does NOT expose the actual used / cap count to
    non-admins (that's the admin endpoint below) — a non-admin user
    doesn't need to see the exact remaining count to decide whether
    the gate is live.
    """
    status = verification_metering.capacity_status(db)
    return _PoolStatusOut(
        has_capacity=status["has_capacity"],
        reset_date=status["reset_date"],
        days_until_reset=status["days_until_reset"],
    )


class _AdminPoolStatusOut(BaseModel):
    year_month: str
    cap: int
    used: int
    remaining: int
    has_capacity: bool
    reset_date: str
    days_until_reset: int
    per_org: list[dict]


@router.get(
    "/admin/verification/pool-status",
    response_model=_AdminPoolStatusOut,
)
def admin_get_pool_status(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_admin),
):
    """Phase 52b B4 — platform-admin read of pool consumption.
    Returns shared total + per-org breakdown. Read-only. Reuses the
    existing ``get_current_admin`` gate."""
    status = verification_metering.capacity_status(db)
    breakdown = verification_metering.per_org_breakdown(
        db, year_month=status["year_month"],
    )
    return _AdminPoolStatusOut(
        year_month=status["year_month"],
        cap=status["cap"],
        used=status["used"],
        remaining=status["remaining"],
        has_capacity=status["has_capacity"],
        reset_date=status["reset_date"],
        days_until_reset=status["days_until_reset"],
        per_org=breakdown,
    )


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
    # Phase 52f — full_name is the canonical readable legal-name
    # field Didit emits (name conventions vary across IDs; better
    # to store Didit's rendering than to reconstruct from first +
    # last).
    full_name = _str_or_none(iv.get("full_name"))
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
        "full_name": full_name,
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

    # Phase 52h Stage 2 — the platform-wide document-number hard
    # block is REMOVED. ``compute_hashes`` no longer returns a
    # doc_number_hash; the collision lookup, the IntegrityError
    # catch in the webhook handler, and the IDENTITY_UNIQUE
    # rung's auto-assignment all go with it (Z-locked Option A —
    # verification proves identity + residency only; uniqueness
    # within an org is handled by the name-based flag system,
    # biometric stays the deferred stronger tier).
    name_dob_address_hash = hashes.get("name_dob_address_hash")
    name_dob_hash = hashes.get("name_dob_hash")

    mapped = verification_provider.map_decision_to_state(decision)
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

    # Apply the verification onto the target user.
    old_state = target_user.verification_state
    old_provenance = target_user.verification_provenance

    target_user.verification_state = new_state
    target_user.verification_jurisdiction = new_jurisdiction
    target_user.verification_attestation_id = new_attestation
    target_user.verification_provenance = verification.PROV_DIDIT
    target_user.verification_updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    # Phase 52h Stage 2 — only the two name-based hashes are
    # written; the deprecated ``doc_number_hash`` column stays in
    # place (model marked deprecated; future cleanup batches its
    # drop with the deprecated ``verification_nullifier`` column),
    # but nothing writes to it from this stage onward.
    if name_dob_address_hash:
        target_user.name_dob_address_hash = name_dob_address_hash
    if name_dob_hash:
        target_user.name_dob_hash = name_dob_hash

    # Phase 52f — capture legal name (readable, NOT hashed). The
    # display-name-match gate compares user-entered display names
    # against this; a hash can't support partial / first-only
    # matching. Privacy disclosure lives on the consent + Settings
    # copy. demo_stub / backdoor never reach this branch — only
    # PROV_DIDIT writes do.
    legal_first = ocr_fields.get("first_name")
    legal_last = ocr_fields.get("last_name")
    legal_full = ocr_fields.get("full_name")
    if isinstance(legal_first, str) and legal_first.strip():
        target_user.legal_first_name = legal_first.strip()
    if isinstance(legal_last, str) and legal_last.strip():
        target_user.legal_last_name = legal_last.strip()
    if isinstance(legal_full, str) and legal_full.strip():
        target_user.legal_full_name = legal_full.strip()

    # Phase 52g — derive age band from the DOB, then discard the DOB
    # (it's only a hash input + band-derivation input; never stored).
    # Month-aligned promotes_at so the value can't reconstruct the
    # exact birth day.
    dob_str = ocr_fields.get("date_of_birth")
    if isinstance(dob_str, str) and dob_str.strip():
        try:
            met, promotes_at = verification.compute_age_bands(dob_str)
            if met or promotes_at:
                target_user.verification_age_bands = (
                    verification.serialize_age_bands(met)
                )
                target_user.verification_age_promotes_at = promotes_at
        except Exception as e:  # noqa: BLE001 — never block the verification write on band derivation
            logger.warning(
                "age band derivation failed for user %s: %s",
                target_user.id, e,
            )

    # Phase 52i — compute the city/locality hash from the same
    # parsed_address that drives the name+DOB+address hash. The
    # readable city is consumed here and discarded; only the hash
    # is stored. State is included in the hash (cross-state
    # disambiguation — Springfield, MA ≠ Springfield, IL).
    address_dict = ocr_fields.get("address")
    if isinstance(address_dict, dict):
        try:
            locality_hash = verification_hashing.compute_locality_hash(
                address_dict.get("city"),
                address_dict.get("state"),
            )
            if locality_hash:
                target_user.verification_locality_hash = locality_hash
        except Exception as e:  # noqa: BLE001 — never block the verification write on locality hash
            logger.warning(
                "locality hash derivation failed for user %s: %s",
                target_user.id, e,
            )

    session_row.status = "approved"
    session_row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

    # Phase 52b B1 — record consumption against the shared free pool.
    # Only fires for ``didit`` provenance (the function rejects
    # demo_stub and backdoor — Phase 51 forward-constraint). Same-user
    # re-verifies that DO advance state count as a new consumption
    # (Didit charged us for the session); the receiver's idempotency
    # check prevents counting twice on a webhook replay.
    verification_metering.record_consumption(
        db,
        user_id=target_user.id,
        provenance=verification.PROV_DIDIT,
        provider_session_id=session_row.provider_session_id,
        org_id=session_row.triggering_org_id,
    )

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
        },
        ip_address=request.client.host if request.client else None,
    )

    # Phase 52h Stage 1 H1 — verify-time duplicate-flag detection.
    # Now that the user's name-based hashes are written (the
    # ``name_dob_address_hash`` / ``name_dob_hash`` columns above),
    # evaluate them against every active org membership they hold.
    # This closes the join-then-verify gap (someone joins an org,
    # later verifies, was never checked against the org population).
    #
    # Behavioral asymmetry vs join-time detection (locked Z policy):
    # at verify-time we ONLY record the flag — we do NOT flip an
    # existing active membership to ``pending_approval``. Suspending
    # a sitting member without warning would be more disruptive than
    # the join-time block-pending-appeal case. The flag is enough
    # to flip ``is_org_verified`` to False (per H3), gating the
    # verified-only actions; the admin sees it in the open-flags
    # list and acts manually.
    #
    # demo_stub never reaches this path — the receiver only invokes
    # ``_apply_decision`` for PROV_DIDIT writes; demo personas have
    # no real verifications and produce no hashes.
    try:
        import verification_flags
        verification_flags.evaluate_duplicate_flags_for_user_orgs(
            db, user=target_user,
            actor_id=target_user.id,
            ip_address=request.client.host if request.client else None,
        )
    except Exception as e:  # noqa: BLE001 — never block the verification write on flag eval
        logger.warning(
            "verification_flags verify-time eval failed for user %s: %s",
            target_user.id, e,
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

    # Phase 52h Stage 2 — the IntegrityError catch that wrapped this
    # block to handle the doc_number_hash partial-unique-index race
    # is REMOVED. The index is dropped in migration e6f7a8b9c0d1 and
    # the column is no longer written, so an IntegrityError on this
    # path would be a genuine bug rather than the expected dedup
    # race — let it surface to the caller (FastAPI will 500 and the
    # log captures it).
    _apply_decision(
        db,
        target_user=target_user,
        decision=decision,
        session_row=session_row,
        request=request,
    )
    session_row.webhook_type_last = webhook_type
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
