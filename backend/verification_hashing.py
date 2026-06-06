"""Phase 52d — document-hash dedup (Phase 52h Stage 2 removed the
platform-wide doc-number hard block).

Pure module — no DB, no provider calls. Caller (the webhook handler)
extracts OCR fields from a Didit decision payload, hands them here,
and persists the returned hashes onto the user. Two hashes are
produced (any may be ``None`` if its source field is absent):

  * ``name_dob_address_hash`` — name + DOB + address (the same
    canonical address form used by the residency / ``address_on_id``
    path). Org-scoped HIGH-CONFIDENCE flag (Phase 52e Stage 2 +
    Phase 52h Stage 1). Math in
    ``id_verification_arc_backlog.md`` shows near-zero false
    collisions at 1M users.

  * ``name_dob_hash`` — name + DOB only. Org-scoped LOWER-
    CONFIDENCE flag (the mover-catch). At ~100k+ users the birthday
    paradox makes false collisions almost certain, which is why
    this tier stays per-org only and never becomes a platform-wide
    rule.

The ``doc_number_hash`` key is retained on the returned dict for
backward compatibility (always ``None``) so any caller reading the
key explicitly doesn't break. Nothing writes it to the column from
Phase 52h Stage 2 onward; the column itself is deprecated (model
comment) and batched for a future cleanup pass alongside the
deprecated ``verification_nullifier`` column.

Each hash is HMAC-SHA256 keyed by a single platform-wide pepper read
from ``VERIFICATION_HASH_PEPPER`` in env. **Pepper is fail-closed:**
absent pepper → ``compute_hashes`` raises ``RuntimeError``, never
falls back to unsalted (which would let a DB leak alone be brute-
forced offline).

Normalization is **moderate** — lowercase + Unicode NFKD + strip
combining marks + collapse whitespace + strip punctuation. NOT
aggressive (no nickname collapse, no middle-name drop). The trade-off:
this accepts MORE misses to avoid false positives, because a false
block (rejecting a real user for sharing a name shape with someone
else) is disenfranchisement, while a miss is just imperfect dedup —
the safe failure direction.

DOB is canonicalized to ISO ``YYYY-MM-DD``. Address is canonicalized
to ``"<lower-stripped-street>|<lower-stripped-city>|<state-2-letter>|
<lower-stripped-zip>"`` — same components the residency check uses,
joined with a separator so re-arrangement doesn't accidentally make
two non-matching addresses hash the same.

Inputs come from Didit's OCR/MRZ extraction (NOT user free-text), so
name strings are document-stable.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import unicodedata
from typing import Optional

# Three field-presence requirements for the three hashes. If ANY required
# field is missing for a hash, that hash is None — the hash is not
# computed against an incomplete input (which would produce a stable
# wrong-key collision-magnet).
_REQUIRED_FIELDS = {
    "doc_number_hash": ("document_number",),
    "name_dob_hash": ("first_name", "last_name", "date_of_birth"),
    "name_dob_address_hash": (
        "first_name", "last_name", "date_of_birth", "address",
    ),
}

PEPPER_ENV = "VERIFICATION_HASH_PEPPER"


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")


def normalize_text(s: object) -> str:
    """Lowercase + Unicode NFKD + strip combining marks + strip
    punctuation (NOT replaced with space — ``"Al-ice"`` collapses to
    ``"alice"``, matching the spec's "strip" verb) + collapse
    internal whitespace + strip outer.

    Non-string / None → empty string. The empty string is a sentinel
    that propagates — a hash function called with an empty required
    field returns ``None`` rather than hashing the empty input.
    """
    if not isinstance(s, str):
        return ""
    decomposed = unicodedata.normalize("NFKD", s)
    no_marks = "".join(c for c in decomposed if not unicodedata.combining(c))
    lower = no_marks.lower()
    no_punct = _PUNCT_RE.sub("", lower)
    collapsed = _WS_RE.sub(" ", no_punct).strip()
    return collapsed


def normalize_dob(s: object) -> str:
    """Coerce a DOB to ISO ``YYYY-MM-DD``.

    Accepts ``"YYYY-MM-DD"``, ``"YYYY/MM/DD"``, ``"DD-MM-YYYY"``,
    ``"DD/MM/YYYY"``, ``"YYYYMMDD"``. Anything else → empty string.
    """
    if not isinstance(s, str):
        return ""
    raw = s.strip()
    if not raw:
        return ""
    # Already ISO.
    m = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", raw)
    if m:
        y, mo, d = m.groups()
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    # Day-first.
    m = re.match(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$", raw)
    if m:
        d, mo, y = m.groups()
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    # Compact YYYYMMDD.
    m = re.match(r"^(\d{4})(\d{2})(\d{2})$", raw)
    if m:
        y, mo, d = m.groups()
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    return ""


def normalize_address(addr: object) -> str:
    """Canonical address string for hashing. Expects a dict like
    ``{"street": ..., "city": ..., "state": ..., "zip": ...}`` — the
    shape Didit's OCR delivers under ``id_verification.address``.

    Returns ``""`` if any required component is missing — incomplete
    addresses don't hash (same reasoning as the empty-text sentinel).
    """
    if not isinstance(addr, dict):
        return ""
    street = normalize_text(addr.get("street") or addr.get("line1"))
    city = normalize_text(addr.get("city") or addr.get("locality"))
    state_raw = addr.get("state") or addr.get("region") or addr.get("subdivision")
    state = (state_raw or "").strip().upper() if isinstance(state_raw, str) else ""
    zip_raw = addr.get("zip") or addr.get("postal_code") or addr.get("postcode")
    zipv = normalize_text(zip_raw)
    if not (street and city and state and zipv):
        return ""
    return f"{street}|{city}|{state}|{zipv}"


# ---------------------------------------------------------------------------
# Pepper
# ---------------------------------------------------------------------------


def _require_pepper() -> bytes:
    """Read the platform pepper from env. Raises ``RuntimeError`` if
    missing — there is NO unsalted fallback path. A deploy without
    ``VERIFICATION_HASH_PEPPER`` set is a configuration error that
    must be surfaced immediately, not silently produce hash values
    that an attacker with the DB could trivially crack.
    """
    val = os.environ.get(PEPPER_ENV)
    if not val:
        raise RuntimeError(
            f"{PEPPER_ENV} is not set. Verification hashing cannot run "
            "without the platform pepper. Set the sealed Railway "
            "variable and redeploy."
        )
    return val.encode("utf-8")


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------


def _h(parts: list[str]) -> str:
    """HMAC-SHA256 the joined parts under the platform pepper. Parts
    are joined with a literal ``"\\x1f"`` (the ASCII unit-separator,
    which can't appear in a normalized string) so different field
    layouts don't collide on the same concatenation.
    """
    msg = "\x1f".join(parts).encode("utf-8")
    return hmac.new(_require_pepper(), msg, hashlib.sha256).hexdigest()


def _all_present(fields: dict, names: tuple[str, ...]) -> bool:
    """Returns True iff every required field has a non-empty value
    after normalization. Used to skip hashes whose inputs are
    incomplete (preventing accidental same-empty-hash collisions)."""
    for n in names:
        v = fields.get(n)
        if n == "address":
            if not normalize_address(v):
                return False
        elif n == "date_of_birth":
            if not normalize_dob(v):
                return False
        else:
            if not normalize_text(v):
                return False
    return True


def compute_hashes(fields: dict) -> dict[str, Optional[str]]:
    """Compute the three salted hashes from OCR fields. Pure (no DB,
    no provider calls). Caller passes in the extraction result —
    typically a dict like::

        {
            "document_number": "X9876543",
            "first_name": "Alice",
            "last_name": "Robertson",
            "date_of_birth": "1985-03-14",
            "address": {
                "street": "1234 Elm Street",
                "city": "Springfield",
                "state": "CA",
                "zip": "94114",
            },
        }

    Any required input absent → the corresponding hash is None.
    Pepper absent → raises ``RuntimeError`` BEFORE any hash is
    computed. The same input + same pepper always produces the same
    hash (load-bearing: dedup matching depends on stability).
    """
    if not isinstance(fields, dict):
        return {k: None for k in _REQUIRED_FIELDS}

    # Force-trigger pepper check up front so an absent pepper raises
    # at the call site instead of mid-computation.
    _require_pepper()

    out: dict[str, Optional[str]] = {}

    # Phase 52h Stage 2 — ``doc_number_hash`` is no longer computed.
    # The platform-wide doc-number hard block was removed; the
    # name-based hashes drive the org-scoped flag system instead.
    # The key remains in the output dict (always None) so callers
    # reading it explicitly don't break; the deprecated
    # ``users.doc_number_hash`` column is not written.
    out["doc_number_hash"] = None

    # name_dob_hash
    if _all_present(fields, _REQUIRED_FIELDS["name_dob_hash"]):
        out["name_dob_hash"] = _h([
            "name_dob_v1",
            normalize_text(fields["first_name"]),
            normalize_text(fields["last_name"]),
            normalize_dob(fields["date_of_birth"]),
        ])
    else:
        out["name_dob_hash"] = None

    # name_dob_address_hash
    if _all_present(fields, _REQUIRED_FIELDS["name_dob_address_hash"]):
        out["name_dob_address_hash"] = _h([
            "name_dob_address_v1",
            normalize_text(fields["first_name"]),
            normalize_text(fields["last_name"]),
            normalize_dob(fields["date_of_birth"]),
            normalize_address(fields["address"]),
        ])
    else:
        out["name_dob_address_hash"] = None

    return out


# ---------------------------------------------------------------------------
# Phase 52d — uniqueness-strength tier constants
# ---------------------------------------------------------------------------

# Document-hash dedup is the v1 tier. Biometric is architected here as
# a deferred stronger tier (id_verification_arc_backlog locked decision)
# — a future provider integration would set this and the gate predicate
# can require "biometric" specifically. Today we never write biometric.
UNIQUENESS_DOCUMENT_HASH = "document_hash"
UNIQUENESS_BIOMETRIC = "biometric"

VALID_UNIQUENESS_STRENGTHS: frozenset[str] = frozenset({
    UNIQUENESS_DOCUMENT_HASH,
    UNIQUENESS_BIOMETRIC,
})


# ---------------------------------------------------------------------------
# Phase 52i — city/locality residency hash
# ---------------------------------------------------------------------------


def compute_locality_hash(
    city: object, state: object,
) -> Optional[str]:
    """Phase 52i — hash a (city, state) pair for residency gating.

    Reuses the existing ``_h`` + ``normalize_text`` + the
    ``VERIFICATION_HASH_PEPPER``. The state is included in the hash
    so cities with the same name across states ("Springfield, MA"
    vs "Springfield, IL") produce DIFFERENT hashes — load-bearing
    correctness, otherwise a city gate would match residents of the
    wrong Springfield.

    Returns:
      * ``None`` if either ``city`` or ``state`` is missing or
        unnormalizable (fail-safe — a user with no parseable
        locality simply has no hash + fails any city gate, the
        safe direction).
      * The HMAC-SHA256 hex digest otherwise.

    Pepper is read lazily by ``_h``; absent pepper → ``RuntimeError``
    (fail-closed; same posture as the dedup hashes).
    """
    # Defer the import to avoid a module-level cycle.
    from verification_provider import normalize_jurisdiction

    normalized_city = normalize_text(city)
    if not normalized_city:
        return None
    normalized_state = normalize_jurisdiction(
        state if isinstance(state, str) else None,
    )
    if not normalized_state:
        return None
    return _h(["locality_v1", normalized_city, normalized_state])
