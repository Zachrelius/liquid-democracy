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
# Phase 52 — Didit replaced Persona as the real provider (per
# id_verification_research.md §12 addendum). ``PROV_PERSONA`` is
# kept defined-but-unused so existing import sites + audit
# downstream stay byte-for-byte; zero existing rows carry
# ``"persona"`` (confirmed via prod SELECT DISTINCT). Real
# verifications produced from Phase 52a onward stamp ``"didit"``.
PROV_DIDIT = "didit"

VALID_PROVENANCES: frozenset[str] = frozenset({
    PROV_NONE, PROV_PERSONA, PROV_DEMO_STUB, PROV_BACKDOOR, PROV_DIDIT,
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


# ---------------------------------------------------------------------------
# Phase 52 Stage 1 — the gate predicate (single chokepoint)
# ---------------------------------------------------------------------------

def user_satisfies_floor(
    user,
    floor: Optional[str],
    jurisdiction: Optional[str] = None,
) -> bool:
    """Return True iff ``user`` satisfies a verification gate at
    ``(floor, jurisdiction)``.

    One chokepoint for every enforcement point (join, role-grant,
    per-vote, delegation-eligibility narrowing). Never reimplement
    ``subsumes`` at the call site — funnel through this helper.

    Resolution rules:

      * ``floor`` of None / empty / ``email_only`` → satisfied by
        everyone (no gate). This is the load-bearing "ungated
        behaves byte-for-byte as pre-arc" contract: a None floor
        returns True without inspecting the user at all.
      * Otherwise: delegate to ``subsumes(user.verification_state,
        user.verification_jurisdiction, floor, jurisdiction)``.

    User shape: any object exposing ``verification_state`` +
    ``verification_jurisdiction`` attributes (the ORM ``User`` row
    is the canonical caller, but tests can pass a SimpleNamespace
    shim).
    """
    if floor is None or floor == "" or floor == EMAIL_ONLY:
        return True
    current_state = getattr(user, "verification_state", None) or EMAIL_ONLY
    current_jurisdiction = getattr(user, "verification_jurisdiction", None)
    return subsumes(current_state, current_jurisdiction, floor, jurisdiction)


# ---------------------------------------------------------------------------
# Phase 52 Stage 1 — delegation-fork org setting (C4)
# ---------------------------------------------------------------------------

SETTING_DELEGATION_CARRIES_WEIGHT = "verification_delegation_carries_weight"


def delegation_carries_unverified_weight(org) -> bool:
    """Return True iff the org has opted in to the "Yes — delegated
    weight from unverified principals carries on a gated proposal"
    setting. Defaults False (the locked decision: "default No").

    Same defaults-if-absent posture as ``get_org_verification_
    floor``. An org that has never touched the setting reads False —
    the additive-layer invariant means ungated proposals are
    unchanged regardless of this flag.
    """
    settings = getattr(org, "settings", None) or {}
    if not isinstance(settings, dict):
        return False
    return bool(settings.get(SETTING_DELEGATION_CARRIES_WEIGHT, False))


# ---------------------------------------------------------------------------
# Phase 52 Stage 1 — structured 403 payload
# ---------------------------------------------------------------------------

def verification_required_payload(
    floor: str,
    jurisdiction: Optional[str] = None,
    scope: Optional[str] = None,
) -> dict:
    """Structured detail body the route layer raises as the 403 detail
    so the FE renders a "verify to {join/vote/hold-role}" prompt
    without parsing prose. ``scope`` is one of "membership" / "role"
    / "vote" — the FE keys CTA copy on it.
    """
    return {
        "error": "verification_required",
        "floor": floor,
        "jurisdiction": jurisdiction,
        "scope": scope,
    }


# ---------------------------------------------------------------------------
# Phase 52 Stage 1 — enforcement helpers (raise structured 403)
# ---------------------------------------------------------------------------
#
# Each helper:
#   * Resolves the relevant floor via the shipped Phase 51 helpers
#     (``get_org_verification_floor`` for membership + role; the
#     ``Proposal.verification_floor`` column for per-vote).
#   * Calls ``user_satisfies_floor``; if it returns False, raises
#     ``HTTPException(status_code=403, detail=verification_required_
#     payload(...))``.
#
# These are the only call sites the rest of the codebase should use
# for verification enforcement — keeping the "one chokepoint" rule
# the spec calls out. Re-implementing the rank/floor logic at a
# route is a regression and should be caught in review.


def check_membership_floor_for_join(user, org) -> None:
    """Raises 403 if ``user`` doesn't satisfy ``org``'s membership
    floor. No-op when the org has no floor set (default for every
    org). Called by every join path that creates a new
    ``OrgMembership`` row for the caller.
    """
    from fastapi import HTTPException
    floor, jurisdiction = get_org_verification_floor(org, "membership")
    if user_satisfies_floor(user, floor, jurisdiction):
        return
    raise HTTPException(
        status_code=403,
        detail=verification_required_payload(
            floor=floor, jurisdiction=jurisdiction, scope="membership",
        ),
    )


def check_role_grant_floor(user, org, role_system_key: str) -> None:
    """Raises 403 if ``user`` doesn't satisfy the floor required to
    hold ``role_system_key`` in ``org``. Called by every role-mutation
    path: ``change_member_role``, ``transfer_stewardship``,
    ``change_governance_mode`` (successor branch), and the Phase 47
    title-assign ``_apply_bound_role_for_assign`` before any role-id
    write.

    Cardinality-floor interaction (governance.py):
    The verification block prevents the *mutation*, not the existing
    role-holder. The existing holder keeps their role, so the
    governance-floor count_active_governors invariant is preserved
    by construction — verification can never strand an org with zero
    governors because the block aborts before any demote happens.
    This is why the check goes at the TOP of every role-mutation
    path, before any role-id write.
    """
    from fastapi import HTTPException
    floor, jurisdiction = get_org_verification_floor(
        org, "role", role_key=role_system_key,
    )
    if user_satisfies_floor(user, floor, jurisdiction):
        return
    raise HTTPException(
        status_code=403,
        detail=verification_required_payload(
            floor=floor, jurisdiction=jurisdiction, scope="role",
        ),
    )


def check_vote_floor_for_proposal(user, proposal) -> None:
    """Raises 403 if ``proposal`` carries a ``verification_floor`` and
    ``user`` doesn't satisfy it. No-op when the proposal has no gate
    set (``verification_floor IS NULL`` — today's behavior for every
    pre-Phase-52 row). Called from the vote-cast route at the start
    of the handler, before any ``Vote`` row is written.
    """
    from fastapi import HTTPException
    floor = getattr(proposal, "verification_floor", None)
    if not floor:
        return
    jurisdiction = getattr(proposal, "verification_jurisdiction", None)
    if user_satisfies_floor(user, floor, jurisdiction):
        return
    raise HTTPException(
        status_code=403,
        detail=verification_required_payload(
            floor=floor, jurisdiction=jurisdiction, scope="vote",
        ),
    )
