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

# Phase 52e E1 — full-name → 2-letter code map for the
# ``parsed_address.region`` path Didit emits (e.g.
# ``"Massachusetts"`` → ``"MA"``). The 2026-06-05 captured payload
# put the holder's residency as the FULL state name string under
# ``decision.id_verifications[0].parsed_address.region``; the
# previous 2-letter-only normalize_jurisdiction returned None for
# this and the rung never escalated to ``address_on_id``.
_US_STATE_NAME_TO_CODE = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT",
    "delaware": "DE", "district of columbia": "DC", "florida": "FL",
    "georgia": "GA", "hawaii": "HI", "idaho": "ID", "illinois": "IL",
    "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY",
    "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT",
    "nebraska": "NE", "nevada": "NV", "new hampshire": "NH",
    "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH",
    "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD",
    "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY",
}


def normalize_jurisdiction(raw: Optional[str]) -> Optional[str]:
    """Coerce a Didit-supplied region value to our canonical US-state
    two-letter code. Accepts either a 2-letter code (``"CA"``) or a
    full state name (``"California"``, case-insensitive); returns
    None for international, malformed, or unrecognized values.

    The gate predicate compares jurisdictions by exact-string
    equality (``verification.subsumes`` rule 2), so this is the
    load-bearing normalization point — values written here MUST
    match values an org admin enters when setting a jurisdiction
    floor. The OrgSettings UI uses a 2-letter-code picker so admin
    input is constrained to the canonical form.
    """
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s:
        return None
    upper = s.upper()
    if upper in _US_STATE_CODES:
        return upper
    # Full state name — case-insensitive lookup.
    code = _US_STATE_NAME_TO_CODE.get(s.lower())
    if code:
        return code
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
# Phase 52d — D4: session purge (process-and-purge)
# ---------------------------------------------------------------------------


def delete_session(session_id: str) -> bool:
    """Tell Didit to delete a verification session after we've
    extracted the OCR fields we need to hash. Returns True ONLY on a
    confirmed 2xx delete; False on anything else (including the
    404-but-session-still-retained case from the 52d round-trip).

    **Phase 52e E1b — 404 is NOT success.** Z confirmed in the Didit
    portal (2026-06-05) that session ``66a70eb2`` is still fully
    retained even though our DELETE call got a 404. The 52d version
    treated non-2xx as failure but had no candidate-path fallback;
    the v2 here tries multiple plausible endpoints from a comma-
    separated env list, so an operator can extend the candidate set
    once the Didit rep confirms the exact endpoint without a code
    deploy.

    Fail-toward-keeping the verification: callers MUST NOT condition
    the user's verification record on this returning True. A False
    return logs + records ``purge_failed`` on the bookkeeping row,
    surfacing the failure for a retry sweep rather than swallowing it.

    Env:
      * ``DIDIT_SESSION_DELETE_PATHS`` — comma-separated path
        templates. Each ``{id}`` is replaced with the session id.
        Defaults to a list of plausible candidates; the rep's
        confirmation gets prepended via a single env update once
        known.
      * ``DIDIT_SESSION_DELETE_PATH`` (legacy single-path) is honored
        as the FIRST candidate when set, so the existing prod env
        setting continues to work and a single-path override remains
        an option.
    """
    try:
        api_key = _require_env("DIDIT_API_KEY")
    except RuntimeError:
        logger.warning("delete_session: DIDIT_API_KEY unset; cannot purge")
        return False

    # Build candidate path list: legacy single env first (if set),
    # then DIDIT_SESSION_DELETE_PATHS (comma-separated), then the
    # built-in defaults. Dedupe while preserving order.
    candidates: list[str] = []
    legacy = os.environ.get("DIDIT_SESSION_DELETE_PATH")
    if legacy:
        candidates.append(legacy)
    plural = os.environ.get("DIDIT_SESSION_DELETE_PATHS")
    if plural:
        candidates.extend([p.strip() for p in plural.split(",") if p.strip()])
    candidates.extend([
        "/session/{id}/",
        "/sessions/{id}/",
        "/session/{id}",
        "/sessions/{id}",
        "/v3/session/{id}/",          # absolute paths (override base)
        "/v3/sessions/{id}/",
    ])
    seen: set[str] = set()
    unique_candidates: list[str] = []
    for p in candidates:
        if p not in seen:
            seen.add(p)
            unique_candidates.append(p)

    headers = {"x-api-key": api_key}
    last_status: Optional[int] = None
    for path in unique_candidates:
        # If the candidate is an absolute path starting with /v3, use
        # the host as-is; otherwise concatenate with DIDIT_API_BASE.
        if path.startswith("/v3/"):
            host = DIDIT_API_BASE.rsplit("/v3", 1)[0]
            url = f"{host}{path.format(id=session_id)}"
        else:
            url = f"{DIDIT_API_BASE}{path.format(id=session_id)}"
        try:
            with httpx.Client(timeout=10.0) as client:
                r = client.delete(url, headers=headers)
        except Exception as e:  # noqa: BLE001 — purge must never raise to caller
            logger.warning("delete_session: %s -> %s", path, e)
            continue
        last_status = r.status_code
        if 200 <= r.status_code < 300:
            logger.info(
                "delete_session: confirmed delete via %s for %s (%s)",
                path, session_id, r.status_code,
            )
            return True
        # 404 is NOT success: Z confirmed via the Didit portal that
        # a 404'd session can still be fully retained. Try the next
        # candidate; if all fail, return False.
        logger.warning(
            "delete_session: %s returned %s for %s",
            path, r.status_code, session_id,
        )
    logger.warning(
        "delete_session: all candidate endpoints failed for %s "
        "(last status=%s). Session may still be retained at Didit; "
        "schedule a retry / surface to ops.",
        session_id, last_status,
    )
    return False


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
    """Phase 52e E1 — extract the holder's residency jurisdiction
    (a US two-letter state code) from a Didit decision payload,
    normalized via :func:`normalize_jurisdiction`.

    The real payload (captured 2026-06-05) carries the parsed address
    at ``decision.id_verifications[0].parsed_address``:
      * ``parsed_address.region`` — full state name string (e.g.
        ``"Massachusetts"``). This is the HOLDER's residence — what
        ``address_on_id`` means.
      * ``parsed_address.country`` — 2-char country code (e.g.
        ``"US"``); we don't currently use it but record it for the
        provider-swap seam.

    NOT used as jurisdiction:
      * ``id_verifications[0].issuing_state`` (3-char code) — that's
        the document's ISSUING authority, not residence.
      * ``id_verifications[0].address`` / ``formatted_address``
        (free-text strings) — region is parsed structurally and is
        more stable.

    Returns the normalized two-letter code or None. None means the
    state ladder doesn't escalate to ``address_on_id`` (the safe
    failure direction — a non-US or unrecognized region misses
    rather than over-claims).

    Legacy back-compat candidates (the singular ``id_verification``
    paths the 52d-shipped extractor probed) are KEPT as fallbacks
    so a future Custom KYC workflow variant that uses the singular
    shape doesn't break. They run last; the real plural path takes
    precedence.
    """
    if not isinstance(decision, dict):
        return None

    candidates: list[Any] = []

    # Phase 52e — REAL path from the 2026-06-05 captured manifest.
    iv_list = decision.get("id_verifications")
    if isinstance(iv_list, list) and iv_list:
        first = iv_list[0]
        if isinstance(first, dict):
            pa = first.get("parsed_address")
            if isinstance(pa, dict):
                v = pa.get("region")
                if v is not None:
                    candidates.append(v)

    # Legacy back-compat — the 52d-shipped singular probes. Real
    # workflows don't currently emit this shape, but a future
    # Custom KYC variant or a different provider might. Kept so
    # a swap is "rewrite this module," not "and also fix the
    # extractor in every route."
    iv_singular = decision.get("id_verification")
    if isinstance(iv_singular, dict):
        for key in ("address_state", "region", "state", "subdivision"):
            v = iv_singular.get(key)
            if v is not None:
                candidates.append(v)
        addr = iv_singular.get("address")
        if isinstance(addr, dict):
            for key in ("state", "region", "subdivision"):
                v = addr.get(key)
                if v is not None:
                    candidates.append(v)
    for key in ("address_state", "state", "subdivision"):
        v = decision.get(key)
        if v is not None:
            candidates.append(v)

    for c in candidates:
        normalized = normalize_jurisdiction(c if isinstance(c, str) else None)
        if normalized:
            return normalized
    return None


def _decision_passed_id(decision: dict) -> bool:
    """True iff the decision indicates a passed ID-verification check.

    Real Didit shape (captured in Phase 52c/52e): the per-feature
    status lives at ``decision.id_verifications[0].status`` (plural
    array). Back-compat: also accept the documented singular
    ``decision.id_verification.status`` and the overall
    ``decision.status``.
    """
    if not isinstance(decision, dict):
        return False
    overall = str(decision.get("status") or "").strip().lower()
    # Phase 52h Stage 2 — the rest of the mapper reads the plural
    # ``id_verifications`` array; this consistency fix matches that.
    iv_plural = decision.get("id_verifications")
    iv_plural_status = ""
    if isinstance(iv_plural, list) and iv_plural:
        first = iv_plural[0]
        if isinstance(first, dict):
            iv_plural_status = str(first.get("status") or "").strip().lower()
    # Legacy singular path.
    iv = decision.get("id_verification")
    iv_status = ""
    if isinstance(iv, dict):
        iv_status = str(iv.get("status") or "").strip().lower()
    return (
        iv_plural_status == "approved"
        or iv_status == "approved"
        or overall == "approved"
    )


def map_decision_to_state(decision: dict) -> dict:
    """Pure mapper from Didit's ``decision`` payload to our record
    fields. The single place where provider-specific response shape
    is interpreted.

    Returns a dict with keys:
      * ``verification_state`` — one of EMAIL_ONLY / IDENTITY /
        ADDRESS_ON_ID. (RESIDENCY_VERIFIED requires a residency-
        proof feature beyond the Custom KYC workflow and is not
        produced by this mapper. IDENTITY_UNIQUE is NO LONGER
        produced — see Phase 52h Stage 2 note below.)
      * ``verification_jurisdiction`` — US-state two-letter code or
        None. Only set when state is ADDRESS_ON_ID.
      * ``verification_attestation_id`` — Didit's session id (for
        audit + record-keeping; never serialized to clients).

    Failure / declined / missing fields → EMAIL_ONLY with everything
    else None. The webhook handler treats EMAIL_ONLY as "do not write
    a real verification" (the user's existing state stays put).

    Phase 52d precedence fix retained — the state ladder is
    **ordinal** (``address_on_id`` rung 3 subsumes lower rungs), so
    a passed ID with a parsed jurisdiction lands at
    ``address_on_id`` directly.

    **Phase 52h Stage 2 — uniqueness rung removed (Z-locked Option
    A).** The platform-wide doc-number hard block was retired
    because the locked principle (confidence-determines-scope,
    harm is org-scoped) makes cross-org duplicate accounts for
    the same person a non-harm we don't prevent at the platform
    layer. With the doc-block gone, the auto-assignment of
    ``IDENTITY_UNIQUE`` was either (a) lying (rung says "unique"
    but nothing enforces uniqueness — a footgun) or (b) gone.
    Z picked Option A: gone. Post-removal, verification proves
    identity + residency only; uniqueness within an org is
    handled by the org-scoped name-based flag system (Phase 52e
    Stage 2 + Phase 52h Stage 1), and biometric stays the
    deferred stronger tier for orgs that need real Sybil
    resistance.

    Sequence of decisions encoded:
      * ID check passed? → at least IDENTITY.
      * Jurisdiction parsed from address? → ADDRESS_ON_ID.
    """
    if not isinstance(decision, dict) or not _decision_passed_id(decision):
        return {
            "verification_state": EMAIL_ONLY,
            "verification_jurisdiction": None,
            "verification_attestation_id": None,
        }
    jurisdiction = _extract_jurisdiction(decision)
    # Ordinal pick: highest satisfied rung. IDENTITY_UNIQUE is no
    # longer reachable from this mapper (Phase 52h Stage 2).
    state = ADDRESS_ON_ID if jurisdiction else IDENTITY
    attestation_id = decision.get("session_id") or decision.get("id")
    if attestation_id is not None:
        attestation_id = str(attestation_id)
    return {
        "verification_state": state,
        "verification_jurisdiction": jurisdiction,
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

# Opaque-id pattern: alnum + dash + underscore + dot, length ≥ 16.
# This matches UUIDs (with or without dashes), hex tokens, and the
# kind of slug-like handle Didit uses for nullifiers / session ids.
# Spaces / commas / @-symbols are NOT matched, so emails or names
# longer than 16 chars still redact.
#
# Pattern alone is not enough: real document numbers (driver's
# licenses, passport numbers, alien registration numbers) can also
# look like alnum-dash strings of ≥16 chars. To stay fail-closed, an
# opaque-id-shaped value is only kept when the KEY it sits under is
# on the safe-key allow-list (``_SAFE_ID_KEYS``). Any other ≥16-char
# alnum string redacts to ``<str:N>`` like normal PII.
_OPAQUE_ID_RE = re.compile(r"^[A-Za-z0-9._\-]+$")
_OPAQUE_ID_MIN_LEN = 16

# Keys whose VALUE we trust to keep verbatim when it has the opaque-
# id shape. Add to this set only when a Phase 52c/52d capture has
# revealed a new dedup-related key whose value is genuinely an opaque
# handle — never add a key that could carry PII (a document_number /
# license_number / passport_number / etc.). Comparison is
# case-insensitive on the lowercased key.
_SAFE_ID_KEYS: frozenset[str] = frozenset({
    "session_id",
    "provider_session_id",
    "attestation_id",
    "id",                  # Top-level didit id
    "nullifier",
    "identity_handle",
    "identity_id",
    "face_search_id",
    "dedup_id",
    "request_id",
    "transaction_id",
})

# Recursion guard. Real Didit payloads are ≤ a few levels deep; anything
# beyond this is either pathological or malicious, and the redactor
# treats it as ``"<truncated>"``.
_MAX_DEPTH = 20


def _redact_string(s: str, *, key: Optional[str] = None) -> str:
    """Single-string allow-list decision. Pure (no side effects).

    ``key`` is the dict key (if any) the string sits under. An
    opaque-id-shaped value only survives when ``key`` is on the
    ``_SAFE_ID_KEYS`` allow-list — without this gate, real document
    numbers (which are alnum + dash + ≥16 chars) leak through. See
    the canary leak that drove the 52c hotfix.
    """
    stripped = s.strip()
    if not stripped:
        return ""
    # Known status / enum value.
    if stripped.lower() in _SAFE_ENUM_VALUES:
        return stripped
    # Opaque id / handle / nullifier-like token. Only kept when the
    # parent key is on the safe-key allow-list.
    if (
        key is not None
        and key.lower() in _SAFE_ID_KEYS
        and len(stripped) >= _OPAQUE_ID_MIN_LEN
        and _OPAQUE_ID_RE.match(stripped)
    ):
        return stripped
    # Could be PII — emit type + length only.
    return f"<str:{len(s)}>"


def redact_payload(value: Any, _depth: int = 0, _key: Optional[str] = None) -> Any:
    """Walk a Didit decision payload and return a PII-safe skeleton.

    See module-level note. Caller (the webhook receiver) hands the
    parsed JSON dict here AFTER signature verification; the return
    value is JSON-safe and goes into a single structured log line.

    The ``_key`` argument carries the dict key the value sits under
    so :func:`_redact_string` can apply the safe-key allow-list
    rule. Top-level values have ``_key=None`` and will never be
    treated as opaque ids (which is fine — top-level strings in
    Didit payloads are status / type strings handled by the enum
    allow-list).
    """
    if _depth > _MAX_DEPTH:
        return "<truncated>"
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return _redact_string(value, key=_key)
    if isinstance(value, dict):
        return {
            str(k): redact_payload(v, _depth=_depth + 1, _key=str(k))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        # List items inherit the parent key (so a list of session_ids
        # under a "session_ids" key still passes through, but a list
        # of document numbers under "document_numbers" still redacts).
        return [redact_payload(item, _depth=_depth + 1, _key=_key) for item in value]
    # Unknown type — type label only.
    return f"<{type(value).__name__}>"


# ---------------------------------------------------------------------------
# Phase 52d — D1: key-path manifest (PII-safe by construction)
# ---------------------------------------------------------------------------
#
# A manifest is keys + value-types only — never any value-string. By
# construction it cannot leak PII: there is no path through
# ``key_path_manifest`` where a value-string ends up in the output.
# This is stronger than the redactor's allow-list (the redactor emits
# status enums + safe-key opaque ids verbatim; the manifest emits
# NOTHING but key-paths + type labels).
#
# The use case is grounding Phase 52e: the 52c redactor showed WHERE
# the OCR fields sit but redacted the string values to "<str:N>".
# 52e needs the exact key paths from a real payload to wire the
# hashing module's field extraction. The manifest gives 52e (and any
# future provider swap) those paths without the team ever seeing a
# value.


def _type_label(value: Any) -> str:
    """Short type label used in the manifest output. Strings collapse
    to ``"str"`` regardless of value, integers to ``"int"``, etc.,
    so the manifest reveals ZERO information about the actual leaf
    contents.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, (list, tuple)):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return type(value).__name__


def key_path_manifest(value: Any, *, _prefix: str = "", _depth: int = 0) -> dict[str, str]:
    """Walk a Didit decision payload and return a flat mapping of
    dotted key-paths → type labels.

    Example:

      input  = {"decision": {"id_verification": {"first_name": "Alice",
                                                  "status": "Approved"}}}
      output = {
        "decision":                              "dict",
        "decision.id_verification":              "dict",
        "decision.id_verification.first_name":   "str",
        "decision.id_verification.status":       "str",
      }

    Output is JSON-safe + PII-safe by construction (every value is one
    of "dict" / "list" / "str" / "int" / "float" / "bool" / "null" /
    "<typename>"). List indices are NOT enumerated — only the list
    itself is emitted (so an arbitrarily-long PII-bearing list cannot
    leak via a giant index manifest). The first list element's shape
    can be reached via the manifest by walking a representative item;
    that's left to the caller if needed.
    """
    if _depth > _MAX_DEPTH:
        return {_prefix or "<root>": "<truncated>"}
    out: dict[str, str] = {}
    if _prefix:
        out[_prefix] = _type_label(value)
    if isinstance(value, dict):
        if not _prefix:
            out["<root>"] = "dict"
        for k, v in value.items():
            child = f"{_prefix}.{k}" if _prefix else str(k)
            out.update(key_path_manifest(v, _prefix=child, _depth=_depth + 1))
    elif isinstance(value, (list, tuple)) and value:
        # Recurse into the FIRST item only (its shape is representative
        # of the homogeneous-list case Didit uses; we don't enumerate
        # indices to keep output bounded + PII-safe).
        child = f"{_prefix}[0]" if _prefix else "[0]"
        out.update(key_path_manifest(value[0], _prefix=child, _depth=_depth + 1))
    return out
