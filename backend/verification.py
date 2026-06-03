"""Phase 51 — Verification state model + org gate configuration.

Foundation pass: pure-function logic for the ID-verification arc. No
enforcement is wired here (that's Phase 52); this module is the
single source of truth for:

  * The five-state lifecycle: ``email_only`` → ``identity`` →
    ``identity_unique`` → ``address_on_id`` → ``residency_verified``.
  * The subsumption rule "does state X satisfy required floor Y
    (with jurisdiction)?" — ``subsumes()``.
  * The org-level gate-config read helper
    ``get_org_verification_floor(org, scope, *, role_key=None)``.

Provenance markers track how a verification record was set:

  * ``none``      — never verified (the default).
  * ``persona``   — real verification via Persona (Phase 52+).
  * ``demo_stub`` — seeded demo-org persona, NEVER a real
    verification. Phase 52 enforcement + Phase 53 billing must treat
    this as "not real" and never count against the free pool / bill.
  * ``backdoor``  — set via the guarded platform-admin endpoint in
    this phase. Persists as an ops override path beyond Phase 52.

The module has NO DB access. The settings-read helper takes an
``Organization`` instance and reads its ``settings`` JSON via
``getattr`` — same pattern as ``org_config.py`` for thresholds and
durations.
"""
from __future__ import annotations

from typing import Optional, Tuple

# ---------------------------------------------------------------------------
# Verification states (ordered, weakest → strongest)
# ---------------------------------------------------------------------------

EMAIL_ONLY = "email_only"
IDENTITY = "identity"
IDENTITY_UNIQUE = "identity_unique"
ADDRESS_ON_ID = "address_on_id"
RESIDENCY_VERIFIED = "residency_verified"

ORDER: list[str] = [
    EMAIL_ONLY,
    IDENTITY,
    IDENTITY_UNIQUE,
    ADDRESS_ON_ID,
    RESIDENCY_VERIFIED,
]

VALID_STATES: frozenset[str] = frozenset(ORDER)


# ---------------------------------------------------------------------------
# Provenance markers
# ---------------------------------------------------------------------------

PROV_NONE = "none"
PROV_PERSONA = "persona"
PROV_DEMO_STUB = "demo_stub"
PROV_BACKDOOR = "backdoor"

VALID_PROVENANCES: frozenset[str] = frozenset({
    PROV_NONE, PROV_PERSONA, PROV_DEMO_STUB, PROV_BACKDOOR,
})


# ---------------------------------------------------------------------------
# Pure rank + subsumption
# ---------------------------------------------------------------------------

def rank(state: str) -> int:
    """Index of ``state`` in ``ORDER``; higher means stronger.

    Unknown / malformed values rank as ``-1`` (below the weakest
    state) so a downstream gate is never accidentally satisfied by a
    corrupt row. Treat -1 as "below floor for any required state."
    """
    try:
        return ORDER.index(state)
    except ValueError:
        return -1


def subsumes(
    current_state: str,
    current_jurisdiction: Optional[str],
    required_floor: str,
    required_jurisdiction: Optional[str],
) -> bool:
    """Does a user in ``current_state`` (with ``current_jurisdiction``)
    satisfy a gate requiring ``required_floor`` (optionally scoped to
    ``required_jurisdiction``)?

    Locked rules:

      1. **Ordinal floor:** ``rank(current_state) >= rank(required_
         floor)`` is necessary. A user below the required floor never
         satisfies it.
      2. **Jurisdiction dimension:** if ``required_floor`` is
         ``address_on_id`` or ``residency_verified`` AND
         ``required_jurisdiction`` is set, then additionally
         ``current_jurisdiction == required_jurisdiction`` is
         required. Exact-string-equality only — broader/narrower
         subsumption (state → county etc.) is a later-phase concern.
      3. **No downward implication of jurisdiction:** floors below
         ``address_on_id`` have no jurisdiction component; the
         jurisdiction-match check is skipped for those floors even
         if the user is at a higher state with a jurisdiction
         attached.
      4. ``email_only`` floor is satisfied by everyone (rank 0); this
         is the "not required" default.

    ``current_state`` or ``required_floor`` outside the known set =>
    rank -1 / unknown floor, both fail safely (the caller sees False).
    """
    current_rank = rank(current_state)
    required_rank = rank(required_floor)
    if required_rank < 0:
        # Unknown required floor — fail closed.
        return False
    if current_rank < required_rank:
        return False
    # Jurisdiction dimension only matters at address_on_id and above.
    if required_floor in (ADDRESS_ON_ID, RESIDENCY_VERIFIED) and required_jurisdiction:
        if current_jurisdiction != required_jurisdiction:
            return False
    return True


# ---------------------------------------------------------------------------
# Org gate configuration (read helper)
# ---------------------------------------------------------------------------

# Settings keys (single source of truth — also used by tests).
SETTING_MEMBERSHIP_FLOOR = "verification_membership_floor"
SETTING_MEMBERSHIP_JURISDICTION = "verification_membership_jurisdiction"
SETTING_ROLE_FLOORS = "verification_role_floors"


def get_org_verification_floor(
    org,
    scope: str,
    *,
    role_key: Optional[str] = None,
) -> Tuple[str, Optional[str]]:
    """Return ``(floor, jurisdiction)`` for the given gate scope.

    Scopes:
      * ``"membership"`` — required to join the org. Reads
        ``settings.verification_membership_floor`` +
        ``settings.verification_membership_jurisdiction``. Phase 52
        enforces at the join path.
      * ``"role"`` — required to hold a given platform role
        (``role_key`` is mandatory for this scope). Reads
        ``settings.verification_role_floors[role_key]`` for the
        floor; no jurisdiction at this scope (role membership is
        not jurisdictional). Phase 52 enforces at role-grant.

    Defaults-if-absent semantics: every unset key resolves to
    ``("email_only", None)`` — the "not required" sentinel. This
    matches ``org_config`` conventions for thresholds/durations and
    is the load-bearing parity guarantee for existing orgs (no
    backfill needed).

    No DB access; ``org`` is consulted via ``getattr(org, "settings",
    None)`` only. Sub-org parent-chain walking is deferred to a later
    phase (matches the threshold-helper posture in ``org_config.py``).
    """
    settings = getattr(org, "settings", None) or {}
    if not isinstance(settings, dict):
        return (EMAIL_ONLY, None)

    if scope == "membership":
        floor = settings.get(SETTING_MEMBERSHIP_FLOOR)
        if not isinstance(floor, str) or floor not in VALID_STATES:
            floor = EMAIL_ONLY
        jurisdiction = settings.get(SETTING_MEMBERSHIP_JURISDICTION)
        if not isinstance(jurisdiction, str) or not jurisdiction.strip():
            jurisdiction = None
        return (floor, jurisdiction)

    if scope == "role":
        if not role_key:
            return (EMAIL_ONLY, None)
        role_floors = settings.get(SETTING_ROLE_FLOORS) or {}
        if not isinstance(role_floors, dict):
            return (EMAIL_ONLY, None)
        floor = role_floors.get(role_key)
        if not isinstance(floor, str) or floor not in VALID_STATES:
            floor = EMAIL_ONLY
        return (floor, None)

    # Unknown scope — fail safe to "not required."
    return (EMAIL_ONLY, None)


# ---------------------------------------------------------------------------
# Jurisdiction-presence consistency (used by the backdoor + future setters)
# ---------------------------------------------------------------------------

def jurisdiction_required_for(state: str) -> bool:
    """True iff a state carries a jurisdiction claim. ``address_on_id``
    and ``residency_verified`` carry one; lower states do not. The
    backdoor setter (Phase 51 §6) + Phase 52 setters validate input
    consistency against this rule."""
    return state in (ADDRESS_ON_ID, RESIDENCY_VERIFIED)
