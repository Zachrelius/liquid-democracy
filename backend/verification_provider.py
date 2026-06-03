"""Phase 52a — Didit verification provider (swappable seam).

Single module that owns every call to the third-party verifier so a
future provider swap is "rewrite this file." The rest of the codebase
talks only to:

  * ``create_session(user_id)`` — initiates a verification session,
    returns ``(session_url, session_id)``. Wraps Didit's
    ``POST /v3/session/``. API key from env, server-side only.
  * ``verify_webhook(raw_body, signature, timestamp)`` — HMAC-SHA256
    over the raw body + ``X-Timestamp`` freshness ≤300s + constant-
    time signature compare. Returns False on any failure; callers
    return 401 on False.
  * ``map_decision_to_state(decision)`` — pure mapper from Didit's
    decision payload shape to our internal record fields. This is the
    one place provider-specific response interpretation lives — keep
    pure + unit-tested.

Hybrid pattern (load-bearing): the platform NEVER stores document
images, selfies, or raw PII. The mapper extracts ONLY the derived
state, the opaque nullifier (Didit's 1:N identity handle when
available), the attestation id (Didit's session id), and the coarse
jurisdiction (US state two-letter code, normalized via C-JURIS).

Env vars (set in Railway, never in code):
  * ``DIDIT_API_KEY`` — workspace API key for ``POST /v3/session/``.
  * ``DIDIT_WEBHOOK_SECRET`` — per-destination signing secret. Until
    set, ``verify_webhook`` returns False for every payload — that's
    the correct "fail closed" posture during the webhook-handoff
    sequence (build receiver → surface URL → Z sets secret → smoke).
  * ``DIDIT_WORKFLOW_ID`` — pre-created workflow uuid; required.
  * ``DIDIT_API_BASE`` (optional override) — defaults to the prod
    Didit base; tests stub by monkey-patching.

NOTHING in this module touches the DB.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import time
from typing import Any, Optional

import httpx

from verification import (
    ADDRESS_ON_ID,
    EMAIL_ONLY,
    IDENTITY,
    IDENTITY_UNIQUE,
)

logger = logging.getLogger(__name__)

DIDIT_API_BASE = os.environ.get(
    "DIDIT_API_BASE", "https://verification.didit.me/v3"
).rstrip("/")
WEBHOOK_FRESHNESS_SECONDS = 300


# ---------------------------------------------------------------------------
# C-JURIS — jurisdiction normalization
# ---------------------------------------------------------------------------

_US_STATE_CODES = frozenset({
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC",
})


def normalize_jurisdiction(raw: Optional[str]) -> Optional[str]:
    """Coerce a Didit-supplied region value to our canonical US-state
    two-letter code. Returns None for anything not on the allow-list
    (international addresses, missing values, malformed input). The
    gate predicate compares jurisdictions by exact-string equality
    (``verification.subsumes`` rule 2), so this is the load-bearing
    normalization point — values written here MUST match values an
    org admin enters when setting a jurisdiction floor.
    """
    if not isinstance(raw, str):
        return None
    s = raw.strip().upper()
    if not s:
        return None
    if s in _US_STATE_CODES:
        return s
    return None


# ---------------------------------------------------------------------------
# C-PROVIDER §1 — session initiation
# ---------------------------------------------------------------------------


def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(
            f"Provider env var {name!r} is not set. "
            "Configure it in Railway and redeploy."
        )
    return val


def create_session(user_id: str) -> dict[str, str]:
    """Initiate a Didit verification session for ``user_id``.

    Returns ``{"session_url": str, "session_id": str}``.

    Raises ``RuntimeError`` if env config is missing, or
    ``httpx.HTTPError`` subclasses if the upstream call fails — the
    route layer should catch and surface a friendly 502.
    """
    api_key = _require_env("DIDIT_API_KEY")
    workflow_id = _require_env("DIDIT_WORKFLOW_ID")
    url = f"{DIDIT_API_BASE}/session/"
    payload = {
        "workflow_id": workflow_id,
        "vendor_data": str(user_id),
    }
    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=15.0) as client:
        r = client.post(url, json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
    session_url = data.get("url") or data.get("session_url")
    session_id = data.get("session_id") or data.get("id")
    if not session_url or not session_id:
        raise RuntimeError(
            "Didit /session/ response missing session_url or session_id; "
            f"got keys={list(data.keys())}"
        )
    return {"session_url": session_url, "session_id": session_id}


# ---------------------------------------------------------------------------
# C-PROVIDER §2 — webhook signature verification
# ---------------------------------------------------------------------------


def verify_webhook(
    raw_body: bytes,
    signature: Optional[str],
    timestamp: Optional[str],
    *,
    now: Optional[float] = None,
) -> bool:
    """Verify a Didit webhook payload.

    Three checks (any failure → False):
      1. ``DIDIT_WEBHOOK_SECRET`` is set. (Pre-secret-handoff this
         returns False — the receiver must reject all traffic until
         Z lands the secret.)
      2. ``timestamp`` (the value of the ``X-Timestamp`` header) is
         a Unix epoch seconds value within ``WEBHOOK_FRESHNESS_SECONDS``
         of ``now`` (replay-protection window).
      3. HMAC-SHA256(secret, raw_body).hexdigest() compares
         constant-time-equal to ``signature``.

    ``raw_body`` MUST be the exact bytes received off the wire — no
    re-encoding or pretty-print, or HMAC fails. The route layer is
    responsible for getting the raw body via ``await request.body()``
    BEFORE FastAPI parses it.
    """
    secret = os.environ.get("DIDIT_WEBHOOK_SECRET")
    if not secret:
        return False
    if not signature or not timestamp:
        return False
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    current = float(now) if now is not None else time.time()
    if abs(current - ts) > WEBHOOK_FRESHNESS_SECONDS:
        return False
    mac = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256)
    expected = mac.hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())


# ---------------------------------------------------------------------------
# C-PROVIDER §3 — pure decision → state mapper
# ---------------------------------------------------------------------------


def _extract_jurisdiction(decision: dict) -> Optional[str]:
    """Best-effort extraction of a coarse jurisdiction from Didit's
    decision payload, normalized via :func:`normalize_jurisdiction`.

    Didit's ``decision`` shape (from §12 + their docs) carries a
    parsed address under ``id_verification`` / ``id_doc`` /
    ``extracted_fields`` depending on workflow version. We probe the
    common keys and bail to None on anything we don't recognize —
    None means the state never escalates to ``address_on_id``.
    """
    candidates: list[Any] = []
    iv = decision.get("id_verification") if isinstance(decision, dict) else None
    if isinstance(iv, dict):
        for key in ("address_state", "region", "state", "subdivision"):
            v = iv.get(key)
            if v is not None:
                candidates.append(v)
        addr = iv.get("address")
        if isinstance(addr, dict):
            for key in ("state", "region", "subdivision"):
                v = addr.get(key)
                if v is not None:
                    candidates.append(v)
    # Some payload variants put extracted fields at top level
    for key in ("address_state", "state", "subdivision"):
        v = decision.get(key) if isinstance(decision, dict) else None
        if v is not None:
            candidates.append(v)
    for c in candidates:
        normalized = normalize_jurisdiction(c if isinstance(c, str) else None)
        if normalized:
            return normalized
    return None


def _decision_passed_id(decision: dict) -> bool:
    """True iff the decision indicates a passed ID-verification check.

    Didit reports per-feature status under keys like
    ``id_verification.status`` and an overall ``decision.status``.
    We require the ID-verification feature to be ``Approved`` (and
    accept an overall ``Approved`` as the broader signal).
    """
    if not isinstance(decision, dict):
        return False
    overall = str(decision.get("status") or "").strip().lower()
    iv = decision.get("id_verification") if isinstance(decision, dict) else None
    iv_status = ""
    if isinstance(iv, dict):
        iv_status = str(iv.get("status") or "").strip().lower()
    # Either the dedicated ID-verification feature passed, or the
    # overall decision is Approved (back-compat for simpler workflows).
    return iv_status == "approved" or overall == "approved"


def _decision_passed_1n_dedup(decision: dict) -> bool:
    """True iff the decision indicates a passed 1:N cross-user
    biometric dedup (the IDENTITY_UNIQUE step).

    The free tier's Face Match is per-session (does the selfie match
    the document?) — not 1:N cross-user. Cross-user dedup typically
    surfaces under a different feature key (``aml`` / ``face_search``
    / ``identity_dedup``) when enabled. We probe the common keys and
    return False if absent — that is the deferred-uniqueness path
    when the workspace lacks the capability.
    """
    if not isinstance(decision, dict):
        return False
    for key in ("face_search", "identity_dedup", "biometric_dedup"):
        block = decision.get(key)
        if isinstance(block, dict):
            status = str(block.get("status") or "").strip().lower()
            if status == "approved":
                return True
    return False


def _extract_nullifier(decision: dict) -> Optional[str]:
    """Pull the opaque cross-user identity handle from Didit's payload
    when available. Without 1:N dedup this returns None and the
    nullifier column stays NULL — the uniqueness invariant only fires
    on non-NULL values (partial index, see C-MIGRATION).
    """
    if not isinstance(decision, dict):
        return None
    for path in (
        ("face_search", "identity_handle"),
        ("face_search", "nullifier"),
        ("identity_dedup", "nullifier"),
        ("biometric_dedup", "nullifier"),
    ):
        cur: Any = decision
        for key in path:
            if not isinstance(cur, dict):
                cur = None
                break
            cur = cur.get(key)
        if isinstance(cur, str) and cur.strip():
            return cur.strip()
    return None


def map_decision_to_state(decision: dict) -> dict:
    """Pure mapper from Didit's ``decision`` payload to our record
    fields. The single place where provider-specific response shape
    is interpreted.

    Returns a dict with keys:
      * ``verification_state`` — one of EMAIL_ONLY / IDENTITY /
        IDENTITY_UNIQUE / ADDRESS_ON_ID. (RESIDENCY_VERIFIED requires
        a residency-proof feature beyond the Custom KYC workflow and
        is not produced by this mapper.)
      * ``verification_jurisdiction`` — US-state two-letter code or
        None. Only set when state is ADDRESS_ON_ID.
      * ``verification_nullifier`` — opaque handle or None. Only set
        when 1:N dedup is available + approved.
      * ``verification_attestation_id`` — Didit's session id (for
        audit + record-keeping; never serialized to clients).

    Failure / declined / missing fields → EMAIL_ONLY with everything
    else None. The webhook handler treats EMAIL_ONLY as "do not write
    a real verification" (the user's existing state stays put).
    """
    if not isinstance(decision, dict) or not _decision_passed_id(decision):
        return {
            "verification_state": EMAIL_ONLY,
            "verification_jurisdiction": None,
            "verification_nullifier": None,
            "verification_attestation_id": None,
        }
    jurisdiction = _extract_jurisdiction(decision)
    nullifier = _extract_nullifier(decision)
    dedup_passed = _decision_passed_1n_dedup(decision)
    if jurisdiction:
        state = ADDRESS_ON_ID
    elif dedup_passed:
        state = IDENTITY_UNIQUE
    else:
        state = IDENTITY
    attestation_id = decision.get("session_id") or decision.get("id")
    if attestation_id is not None:
        attestation_id = str(attestation_id)
    return {
        "verification_state": state,
        "verification_jurisdiction": jurisdiction,
        "verification_nullifier": nullifier,
        "verification_attestation_id": attestation_id,
    }


# ---------------------------------------------------------------------------
# Phase 52c — PII-safe payload redactor
# ---------------------------------------------------------------------------
#
# Captures the STRUCTURE of a Didit decision payload (keys + key-paths
# + status enums + opaque ids) without persisting any of the raw PII
# fields the hybrid pattern forbids (document images, selfies, names,
# addresses, document numbers, birthdates). The strategy is an
# allow-list:
#
#   * Known status enum values are kept verbatim (so we can see
#     ``face_search.status == approved``).
#   * Opaque ids / handles that look like UUIDs / hex tokens / nullifier
#     handles (alnum+dash+underscore, ≥16 chars, no spaces) are kept —
#     they carry the dedup primitive we need to confirm the mapper
#     against.
#   * Booleans, numbers, nulls — kept (they're typically scores / flags
#     / counts).
#   * Every other string is REPLACED with ``"<str:N>"`` where N is the
#     original length. This reveals the KEY (and the fact that a string
#     sits there) without revealing the VALUE — exactly what the mapper
#     correction in Phase 52d needs to read the real shape.
#   * Unrecognized types fall through to ``"<typename>"`` — fail-closed.
#
# This is the single load-bearing PII-safety primitive of Phase 52c;
# the gating test ``test_phase_52c_payload_capture.py::TestRedactor``
# proves it.

# Status-like enum values we recognize as safe to keep. Lower-cased
# for comparison; original case preserved on output.
_SAFE_ENUM_VALUES: frozenset[str] = frozenset({
    # Decision / feature statuses.
    "approved", "declined", "review", "pending", "in_progress",
    "in_review", "passed", "failed", "skipped", "expired", "cancelled",
    "canceled", "rejected", "completed", "initiated", "created",
    "updated", "open", "closed", "success", "error", "ok",
    # Boolean-like strings some payloads carry as strings.
    "true", "false", "yes", "no",
    # Match / liveness verdicts.
    "match", "no_match", "live", "spoof", "uncertain",
    # Verification status flags.
    "verified", "unverified",
    # Known webhook_type values we've already observed in prod
    # (status.updated emitted by Didit during the 52a round-trip).
    "session.opened", "session.completed", "session.created",
    "status.updated", "decision.completed", "session.declined",
    "session.approved",
})

# Opaque-id pattern: alnum + dash + underscore + dot, length ≥ 16. This
# matches UUIDs (with or without dashes), hex tokens, and the kind of
# slug-like handle the nullifier is documented to be. Spaces / commas /
# at-signs / @-style email tokens are explicitly NOT matched, so an
# email or human name longer than 16 chars still redacts.
_OPAQUE_ID_RE = re.compile(r"^[A-Za-z0-9._\-]+$")
_OPAQUE_ID_MIN_LEN = 16

# Recursion guard. Real Didit payloads are ≤ a few levels deep; anything
# beyond this is either pathological or malicious, and the redactor
# treats it as ``"<truncated>"``.
_MAX_DEPTH = 20


def _redact_string(s: str) -> str:
    """Single-string allow-list decision. Pure (no side effects)."""
    stripped = s.strip()
    if not stripped:
        return ""
    # Known status / enum value.
    if stripped.lower() in _SAFE_ENUM_VALUES:
        return stripped
    # Opaque id / handle / nullifier-like token.
    if len(stripped) >= _OPAQUE_ID_MIN_LEN and _OPAQUE_ID_RE.match(stripped):
        return stripped
    # Could be PII — emit type + length only.
    return f"<str:{len(s)}>"


def redact_payload(value: Any, _depth: int = 0) -> Any:
    """Walk a Didit decision payload and return a PII-safe skeleton.

    See module-level note. Caller (the webhook receiver) hands the
    parsed JSON dict here AFTER signature verification; the return
    value is JSON-safe and goes into a single structured log line.
    """
    if _depth > _MAX_DEPTH:
        return "<truncated>"
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, dict):
        return {
            str(k): redact_payload(v, _depth=_depth + 1)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_payload(item, _depth=_depth + 1) for item in value]
    # Unknown type — type label only.
    return f"<{type(value).__name__}>"
