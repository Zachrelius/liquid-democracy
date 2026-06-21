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
# Phase 52f — display-name-match: ``off`` (default) / ``first`` /
# ``last`` / ``full``. Enum form per the spec (mutually exclusive
# modes; combinable flags can be added later by switching to a list).
SETTING_REQUIRE_NAME_MATCH = "verification_require_name_match"
# Phase 52f — action on a non-matching display-name write: ``block``
# (hard-reject the write) or ``flag`` (allow + audit-log + admin
# sees it). Per Z's locked decision, both are offered per-org.
SETTING_NAME_MATCH_ACTION = "verification_name_match_action"
# Phase 52g — minimum age to join the org. Integer ∈
# ``SUPPORTED_AGE_THRESHOLDS`` or NULL/None for no age gate.
SETTING_MEMBERSHIP_MIN_AGE = "verification_membership_min_age"
# Phase 52i — city/locality residency gate. The admin enters the
# readable city name; it's hashed together with the org's
# ``SETTING_MEMBERSHIP_JURISDICTION`` at gate-check time and compared
# to the member's stored ``verification_locality_hash``. SETTING THIS
# REQUIRES THE JURISDICTION SETTING TOO — a city alone is ambiguous
# (Springfield collides across ~30 states); the gate refuses to fire
# without a state to disambiguate.
#
# DEPRECATED as of Phase 52j J1 — folded into
# ``SETTING_RESIDENCY_SCOPE``; the J1 normalizer migrates orgs that
# still carry this key. ``user_satisfies_residency_scope`` reads only
# the new key. Left in place for back-compat reads against historical
# rows that haven't been normalized; new writes go to the scope key.
SETTING_MEMBERSHIP_LOCALITY = "verification_membership_locality"

# Phase 52j J1 — org-level residency model. A list of allowed
# ``{state, city?}`` entries (OR-matched). City-bearing entries
# compare the user's ``verification_locality_hash`` against
# ``compute_locality_hash(entry.city, entry.state)``; state-only
# entries compare ``verification_jurisdiction == entry.state``. The
# two levels are INDEPENDENT (the 52i locked decision is preserved):
# a state-only entry is satisfied by jurisdiction match; a city
# entry requires the city hash. No subsumption between levels.
SETTING_RESIDENCY_SCOPE = "verification_residency_scope"

# Phase 52j J1 — per-gate "require residency" booleans. Each gate
# scope toggles WHETHER the org scope applies; the scope itself
# (WHERE) is the single org-level definition above.
SETTING_MEMBERSHIP_REQUIRE_RESIDENCY = "verification_membership_require_residency"
SETTING_ROLE_REQUIRE_RESIDENCY = "verification_role_require_residency"

# Phase 52f match-mode values
NAME_MATCH_OFF = "off"
NAME_MATCH_FIRST = "first"
NAME_MATCH_LAST = "last"
NAME_MATCH_FULL = "full"
# Phase 52j — J4. "Either first OR last token matches" — the looser
# "you're using at least one part of your real name" option Z asked for.
NAME_MATCH_EITHER = "either"
_VALID_NAME_MATCH_MODES: frozenset[str] = frozenset({
    NAME_MATCH_OFF, NAME_MATCH_FIRST, NAME_MATCH_LAST, NAME_MATCH_FULL,
    NAME_MATCH_EITHER,
})

# Phase 52f match-action values
NAME_MATCH_ACTION_BLOCK = "block"
NAME_MATCH_ACTION_FLAG = "flag"
_VALID_NAME_MATCH_ACTIONS: frozenset[str] = frozenset({
    NAME_MATCH_ACTION_BLOCK, NAME_MATCH_ACTION_FLAG,
})

# Phase 52g — supported age thresholds. Orgs may gate on any of
# these; adding a new threshold is a constant change. Sorted ascending.
SUPPORTED_AGE_THRESHOLDS: tuple[int, ...] = (13, 16, 18, 21)


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


# ---------------------------------------------------------------------------
# Phase 52a — demo_stub tightening (C-DEMO)
# ---------------------------------------------------------------------------
#
# ``demo_stub`` provenance must only ever sit on accounts that exist
# solely in the demo world. The instant a user holds any non-demo
# org membership, they cannot receive (or keep) ``demo_stub``. Phase
# 52b counts and Phase 53 billing rely on "demo_stub means never
# real" — a stub leaking onto a real account would distort both.
#
# Two enforcement points:
#   * ``ensure_demo_stub_writable`` — called from any path that's
#     about to stamp ``demo_stub`` on a user. Raises 422 if the user
#     has any real-org membership.
#   * ``ensure_can_join_real_org`` — called from the join paths to
#     block a ``demo_stub`` account from joining a non-demo org.
#     Demo personas shouldn't be joining real orgs anyway; blocking
#     keeps the demo world sealed.


def _user_has_real_org_membership(user, db) -> bool:
    """True iff ``user`` holds at least one ``OrgMembership`` in an
    org whose ``is_demo`` is False (or NULL). Uses an inline import
    of ``models`` to avoid circular import at module load.
    """
    import models
    from sqlalchemy import select
    rows = db.execute(
        select(models.Organization.is_demo)
        .join(
            models.OrgMembership,
            models.OrgMembership.org_id == models.Organization.id,
        )
        .where(models.OrgMembership.user_id == user.id),
    ).all()
    for (is_demo,) in rows:
        if not is_demo:
            return True
    return False


def ensure_demo_stub_writable(user, db) -> None:
    """Raise ``HTTPException(422)`` if ``user`` cannot legitimately
    receive ``demo_stub`` provenance — i.e. if they have any
    membership in a real (non-``is_demo``) org. The only legitimate
    callers are the demo-seed pipeline (writing onto demo-only
    accounts it owns) and the backdoor when an operator explicitly
    asks for ``demo_stub`` on a demo-only user. Backdoor writes of
    real provenances are unaffected.
    """
    from fastapi import HTTPException
    if _user_has_real_org_membership(user, db):
        raise HTTPException(
            status_code=422,
            detail=(
                "Cannot stamp demo_stub on a user with a real-org membership. "
                "demo_stub is reserved for accounts that exist only in the "
                "demo world."
            ),
        )


def ensure_can_join_real_org(user, org) -> None:
    """Block a ``demo_stub`` account from joining a non-demo org.
    Called from every join path AFTER the membership-floor check
    (so the verification structured-403 wins when both fire). No-op
    when the target org is itself a demo org or the user is not on
    ``demo_stub`` provenance.

    Phase 79 note: this is the backend half of demo session fencing and
    it gates ``demo_stub`` ONLY — the genuine demo personas seeded by
    the demo pipeline. ``backdoor`` provenance is deliberately NOT
    gated here: the admin verification-state endpoint stamps
    ``backdoor`` on REAL users to grant them verification (see
    routes/admin.py + the Phase 52 enforcement suite), so blocking it
    would lock real verified users out of joining. ``demo_stub`` is the
    only provenance that marks an actual demo identity on the backend.
    """
    from fastapi import HTTPException
    if getattr(org, "is_demo", False):
        return
    if getattr(user, "verification_provenance", None) != PROV_DEMO_STUB:
        return
    raise HTTPException(
        status_code=422,
        detail=(
            "Demo accounts cannot join real organizations. Sign in with a "
            "non-demo account to join this organization."
        ),
    )


# Phase 52j — J3. Org-level proposal verification policy. Controls
# how a proposal's per-proposal ``verification_floor`` interacts with
# an org-level policy: ``author`` (today's behavior — author sets the
# floor at creation), ``always`` (every proposal carries the org's
# floor regardless of author), ``never`` (proposals can't carry a
# verification floor; any stored value is ignored at enforcement).
SETTING_PROPOSAL_POLICY = "verification_proposal_policy"
SETTING_PROPOSAL_FLOOR = "verification_proposal_floor"
SETTING_PROPOSAL_JURISDICTION = "verification_proposal_jurisdiction"

PROPOSAL_POLICY_AUTHOR = "author"
PROPOSAL_POLICY_ALWAYS = "always"
PROPOSAL_POLICY_NEVER = "never"
_VALID_PROPOSAL_POLICIES: frozenset[str] = frozenset({
    PROPOSAL_POLICY_AUTHOR, PROPOSAL_POLICY_ALWAYS, PROPOSAL_POLICY_NEVER,
})


def get_org_proposal_policy(org) -> str:
    """Phase 52j J3 — returns one of ``author`` / ``always`` /
    ``never``. Defaults to ``author`` (today's behavior — author sets
    the floor at proposal creation; unconfigured orgs unchanged).
    """
    settings = getattr(org, "settings", None) or {}
    if not isinstance(settings, dict):
        return PROPOSAL_POLICY_AUTHOR
    val = settings.get(SETTING_PROPOSAL_POLICY)
    if val in _VALID_PROPOSAL_POLICIES:
        return val
    return PROPOSAL_POLICY_AUTHOR


def effective_proposal_floor(
    proposal, org,
) -> tuple[Optional[str], Optional[str]]:
    """Phase 52j J3 — resolves the EFFECTIVE (floor, jurisdiction)
    for a proposal under the org's policy. One helper so the vote
    path + the FE proposal-creation form agree.

      * ``author`` → ``(proposal.verification_floor, proposal.
        verification_jurisdiction)`` (today's behavior).
      * ``always`` → the org's chosen floor + jurisdiction. Applies
        to EVERY proposal in the org, regardless of any author-set
        value on the proposal.
      * ``never`` → ``(None, None)``. Any stored proposal floor is
        ignored at enforcement.
    """
    policy = get_org_proposal_policy(org) if org is not None else PROPOSAL_POLICY_AUTHOR

    if policy == PROPOSAL_POLICY_NEVER:
        return (None, None)

    if policy == PROPOSAL_POLICY_ALWAYS:
        settings = getattr(org, "settings", None) or {}
        if not isinstance(settings, dict):
            return (None, None)
        floor = settings.get(SETTING_PROPOSAL_FLOOR)
        if not isinstance(floor, str) or floor not in VALID_STATES:
            return (None, None)
        jurisdiction = settings.get(SETTING_PROPOSAL_JURISDICTION)
        if not isinstance(jurisdiction, str) or not jurisdiction.strip():
            jurisdiction = None
        return (floor, jurisdiction)

    # author (default)
    floor = getattr(proposal, "verification_floor", None)
    jurisdiction = getattr(proposal, "verification_jurisdiction", None)
    if not floor:
        return (None, None)
    return (floor, jurisdiction)


def check_vote_floor_for_proposal(user, proposal, org=None) -> None:
    """Raises 403 if the org-policy-resolved floor isn't satisfied.
    No-op when no floor applies (proposal's policy resolves to None).
    Called from the vote-cast route at the start of the handler,
    before any ``Vote`` row is written.

    ``org`` is optional for back-compat; when omitted, the proposal's
    own floor is used (== legacy ``author`` policy path). Call sites
    that have the Organization row should pass it so the org-policy
    resolution applies. Phase 52j J3.
    """
    from fastapi import HTTPException
    floor, jurisdiction = effective_proposal_floor(proposal, org)
    if not floor:
        return
    if user_satisfies_floor(user, floor, jurisdiction):
        return
    raise HTTPException(
        status_code=403,
        detail=verification_required_payload(
            floor=floor, jurisdiction=jurisdiction, scope="vote",
        ),
    )


# ---------------------------------------------------------------------------
# Phase 52g — age band derivation + lazy-promotion read predicate
# ---------------------------------------------------------------------------
#
# Derive a sorted list of met thresholds from a DOB and an "as-of"
# reference date. The DOB is the input ONLY; never stored. Each user
# row carries the derived list + the next-promotion month, both
# month-aligned so the storage layer can never reconstruct the exact
# birth day.


def _safe_parse_iso_date(s: str | None) -> Optional["date"]:
    """Pure ISO ``YYYY-MM-DD`` parser. Returns None on malformed
    input. Avoids dateutil to keep the dependency surface tight."""
    from datetime import date as _date
    if not isinstance(s, str):
        return None
    parts = s.strip().split("-")
    if len(parts) != 3:
        return None
    try:
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        return _date(y, m, d)
    except (ValueError, TypeError):
        return None


def _years_elapsed(birth_date: "date", as_of: "date") -> int:
    """How many full years have elapsed from ``birth_date`` to
    ``as_of``. Counts a birthday on ``as_of`` as completing the year."""
    years = as_of.year - birth_date.year
    if (as_of.month, as_of.day) < (birth_date.month, birth_date.day):
        years -= 1
    return years


def _first_of_month(year: int, month: int) -> "datetime":
    from datetime import datetime as _dt
    return _dt(year, month, 1)


def compute_age_bands(
    date_of_birth: str | None,
    *,
    as_of: Optional["date"] = None,
    supported: tuple[int, ...] = SUPPORTED_AGE_THRESHOLDS,
) -> tuple[list[int], Optional["datetime"]]:
    """Compute ``(met_thresholds, promotes_at)`` from a DOB.

    ``met_thresholds`` is a sorted ascending list of supported
    thresholds the user currently meets (e.g. ``[13, 16, 18]``).

    ``promotes_at`` is a month-aligned ``datetime`` (first of the
    month in which the user will cross the NEXT supported threshold),
    or None when the user already meets every supported threshold.

    Month-granularity is the load-bearing privacy property — never
    expose the user's exact birth day; ``promotes_at`` is always the
    1st of the relevant month.

    Returns ``([], None)`` on malformed / missing DOB so callers can
    skip the write cleanly (the column stays NULL).
    """
    from datetime import date as _date
    birth = _safe_parse_iso_date(date_of_birth)
    if birth is None:
        return ([], None)
    today = as_of or _date.today()
    age = _years_elapsed(birth, today)
    met = sorted(t for t in supported if age >= t)
    next_t = next((t for t in supported if t > age), None)
    if next_t is None:
        return (met, None)
    # The user turns ``next_t`` on (birth.year + next_t, birth.month,
    # birth.day). Round to first-of-that-month so we don't leak the
    # exact birth day.
    promote_year = birth.year + next_t
    promote_month = birth.month
    return (met, _first_of_month(promote_year, promote_month))


def serialize_age_bands(met: list[int]) -> str:
    """JSON-list string for the storage column."""
    import json
    return json.dumps(sorted(set(met)))


def deserialize_age_bands(raw: str | None) -> list[int]:
    """Best-effort deserialize. Returns ``[]`` on missing or
    malformed input."""
    import json
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        val = json.loads(raw)
        if isinstance(val, list):
            return sorted({int(x) for x in val if isinstance(x, int)})
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return []


def user_meets_age(user, threshold: int) -> bool:
    """Phase 52g — derived per-user predicate. True iff ``threshold``
    is in the user's met-thresholds set OR the lazy-promotion month
    has arrived (the spec's recommended Option A — no scheduler,
    promotion-on-read).

    Returns False when the user has no age band at all (the locked
    "existing users get a band only on re-verify" property).
    """
    raw = getattr(user, "verification_age_bands", None)
    met = deserialize_age_bands(raw)
    if threshold in met:
        return True
    # Lazy promotion: if the promotes_at month has arrived AND it
    # would push the user past ``threshold``, treat them as meeting it.
    promotes_at = getattr(user, "verification_age_promotes_at", None)
    if promotes_at is None:
        return False
    from datetime import datetime as _dt
    now = _dt.utcnow()
    if promotes_at > now:
        return False
    # The user has crossed the NEXT threshold beyond their current
    # met set. Compute what that next threshold is.
    next_supported = [t for t in SUPPORTED_AGE_THRESHOLDS if t not in met]
    if not next_supported:
        return False
    next_t = min(next_supported)
    return threshold <= next_t


def check_membership_min_age_for_join(user, org) -> None:
    """Raises 403 if ``user`` does not meet ``org``'s membership
    minimum age. No-op when the org has no min-age set. Composes
    with ``check_membership_floor_for_join`` — both checked at every
    join path."""
    from fastapi import HTTPException
    settings = getattr(org, "settings", None) or {}
    if not isinstance(settings, dict):
        return
    min_age = settings.get(SETTING_MEMBERSHIP_MIN_AGE)
    if min_age is None or min_age == 0:
        return
    try:
        threshold = int(min_age)
    except (TypeError, ValueError):
        return
    if threshold not in SUPPORTED_AGE_THRESHOLDS:
        return
    if user_meets_age(user, threshold):
        return
    raise HTTPException(
        status_code=403,
        detail={
            "error": "verification_required",
            "scope": "min_age",
            "min_age": threshold,
        },
    )


def check_vote_min_age_for_proposal(user, proposal) -> None:
    """Phase 52g — per-proposal min-age gate. Raises 403 if the
    proposal carries a ``min_age`` and the user does not meet it.
    No-op when the proposal has no age gate."""
    from fastapi import HTTPException
    min_age = getattr(proposal, "min_age", None)
    if min_age is None:
        return
    try:
        threshold = int(min_age)
    except (TypeError, ValueError):
        return
    if threshold not in SUPPORTED_AGE_THRESHOLDS:
        return
    if user_meets_age(user, threshold):
        return
    raise HTTPException(
        status_code=403,
        detail={
            "error": "verification_required",
            "scope": "min_age",
            "min_age": threshold,
        },
    )


# ---------------------------------------------------------------------------
# Phase 52f — per-org display name resolver + display-name-match
# ---------------------------------------------------------------------------


def display_name_for(user, org, *, membership=None) -> str:
    """Phase 52f — the resolver every org-context name-render must
    route through. Returns ``OrgMembership.display_name`` (if set
    for this user+org) or falls back to ``User.display_name``.

    ``membership`` is optional — pass it when the caller already has
    the row (member-list loops, etc.) to skip a redundant query.
    """
    if membership is not None:
        override = getattr(membership, "display_name", None)
        if override:
            return override
    elif user is not None and org is not None:
        # Defer the import to avoid a module-level cycle.
        import models
        # Walk the user's loaded org_memberships if available; the
        # caller usually pre-fetches.
        memberships = getattr(user, "org_memberships", None) or []
        for m in memberships:
            if getattr(m, "org_id", None) == org.id:
                if m.display_name:
                    return m.display_name
                break
    return getattr(user, "display_name", "") or ""


def _normalize_name_for_match(s: str | None) -> str:
    """Reuse the existing hashing-module normalization so match
    behavior tracks the hash-side conventions exactly (lowercase +
    NFKD + strip combining marks + strip punctuation + collapse
    whitespace)."""
    if not isinstance(s, str) or not s.strip():
        return ""
    # Local import to avoid a hard module-load dependency.
    import verification_hashing
    return verification_hashing.normalize_text(s)


def get_org_name_match_mode(org) -> str:
    """Returns one of ``off`` / ``first`` / ``last`` / ``full``.
    Defaults to ``off`` so unconfigured orgs behave byte-for-byte."""
    settings = getattr(org, "settings", None) or {}
    if not isinstance(settings, dict):
        return NAME_MATCH_OFF
    val = settings.get(SETTING_REQUIRE_NAME_MATCH)
    if val in _VALID_NAME_MATCH_MODES:
        return val
    return NAME_MATCH_OFF


def get_org_name_match_action(org) -> str:
    """Returns ``block`` (default) or ``flag``. The recommended
    default per the spec is hard-reject; an org admin can flip to
    flag-only if they want the softer posture."""
    settings = getattr(org, "settings", None) or {}
    if not isinstance(settings, dict):
        return NAME_MATCH_ACTION_BLOCK
    val = settings.get(SETTING_NAME_MATCH_ACTION)
    if val in _VALID_NAME_MATCH_ACTIONS:
        return val
    return NAME_MATCH_ACTION_BLOCK


def display_name_matches_legal(
    candidate_display_name: str | None,
    user,
    org,
) -> bool:
    """Phase 52f — does ``candidate_display_name`` match the user's
    legal name per the org's required match mode?

    Returns:
      * True if the org requires no match (``off``).
      * True if the user has no legal name on file (the gate only
        applies to verified users; an unverified user's display name
        is unconstrained — the membership floor is what forces
        verification first).
      * True if the candidate matches per the mode.
      * False otherwise.

    Match mode semantics (Phase 52j J4 — first-token philosophy):

      * ``first``: the candidate's FIRST normalized token equals the
        FIRST token of the legal first name. Handles Didit's habit
        of packing middle names into ``first_name`` ("Zachary Michael")
        — display "Zachary" still matches.
      * ``last``: the candidate's LAST normalized token equals the
        LAST token of the legal last name. Symmetric.
      * ``full``: relaxed first + last (Z-default — middle-name-
        tolerant). Display must have ≥2 tokens; its first matches
        legal-first's first token AND its last matches legal-last's
        last token. Falls back to whole-string equality only when
        legal_first / legal_last aren't separately set.
      * ``either``: passes if first OR last token matches. The
        loosest "you're using at least one part of your real name"
        option.
    """
    mode = get_org_name_match_mode(org)
    if mode == NAME_MATCH_OFF:
        return True
    legal_first = getattr(user, "legal_first_name", None)
    legal_last = getattr(user, "legal_last_name", None)
    legal_full = getattr(user, "legal_full_name", None)
    if not (legal_first or legal_last or legal_full):
        return True  # no legal name → no gate (verified-only constraint)

    normalized = _normalize_name_for_match(candidate_display_name)
    if not normalized:
        return False

    tokens = normalized.split()
    if not tokens:
        return False

    first_target_tokens = _normalize_name_for_match(legal_first).split()
    last_target_tokens = _normalize_name_for_match(legal_last).split()
    first_match = bool(first_target_tokens) and tokens[0] == first_target_tokens[0]
    last_match = bool(last_target_tokens) and tokens[-1] == last_target_tokens[-1]

    if mode == NAME_MATCH_FIRST:
        return first_match

    if mode == NAME_MATCH_LAST:
        return last_match

    if mode == NAME_MATCH_EITHER:
        return first_match or last_match

    if mode == NAME_MATCH_FULL:
        # Relaxed first+last (Z-default). Whole-string fallback only
        # when first/last aren't separately on file.
        if first_target_tokens and last_target_tokens:
            return len(tokens) >= 2 and first_match and last_match
        return normalized == _normalize_name_for_match(legal_full)

    return False


# ---------------------------------------------------------------------------
# Phase 52i — city/locality residency gate
# ---------------------------------------------------------------------------
#
# State-level (``verification_jurisdiction``) is the existing gate;
# city-level (``verification_locality_hash``) is the new one. The
# locked decision is that the two levels are INDEPENDENT — a state
# gate is NOT auto-satisfied by a city within it, and vice versa.
# Each is an exact match on its own level.


def _residency_scope_entries(org) -> list[dict]:
    """Phase 52j J1 — read + normalize the org's residency-scope
    entries. Returns ``[]`` on absent / malformed config (which the
    predicate treats as "no scope gate, parity").

    Each entry is a dict ``{"state": str, "city": Optional[str]}``
    with the state already upper-cased and stripped, the city left
    as-entered (it's hashed via the standard normalizer). Entries
    without a state are dropped (a city alone is ambiguous; same
    rule as 52i — the state is load-bearing for the hash).

    Back-compat fallback: if the new ``SETTING_RESIDENCY_SCOPE`` key
    is absent BUT the org carries the old 52i single-value keys
    (``verification_membership_jurisdiction`` + optional
    ``verification_membership_locality``), synthesize a one-entry
    scope from them. This keeps pre-J1-normalizer orgs behaving
    correctly until the migration runs. The 52i locality-only-with-
    state rule is preserved (a locality without a state is silently
    inert, matching the old behavior).
    """
    settings = getattr(org, "settings", None) or {}
    if not isinstance(settings, dict):
        return []
    raw = settings.get(SETTING_RESIDENCY_SCOPE)
    if isinstance(raw, list):
        normalized: list[dict] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            state = entry.get("state")
            state_clean: Optional[str] = (
                state.strip().upper()
                if isinstance(state, str) and state.strip() else None
            )
            # Phase 76c — optional ISO 3166-1 alpha-2 country. An entry
            # is kept if it carries a state (US state/city entry, the
            # existing shape) OR a country (country-level entry). An
            # entry with neither is ambiguous and dropped.
            country = entry.get("country")
            country_clean: Optional[str] = (
                country.strip().upper()
                if isinstance(country, str) and country.strip() else None
            )
            if not state_clean and not country_clean:
                continue
            city = entry.get("city")
            city_clean: Optional[str] = None
            if isinstance(city, str) and city.strip():
                city_clean = city.strip()
            # City is hashed with its state (US-only for now); a city
            # without a state can't be matched, so drop it.
            if city_clean and not state_clean:
                city_clean = None
            normalized.append({
                "country": country_clean,
                "state": state_clean,
                "city": city_clean,
            })
        return normalized

    # Back-compat: synthesize from old 52i single-value keys.
    old_state = settings.get(SETTING_MEMBERSHIP_JURISDICTION)
    if not isinstance(old_state, str) or not old_state.strip():
        return []
    old_city = settings.get(SETTING_MEMBERSHIP_LOCALITY)
    entry: dict = {"country": None, "state": old_state.strip().upper(), "city": None}
    if isinstance(old_city, str) and old_city.strip():
        entry["city"] = old_city.strip()
    return [entry]


def user_satisfies_residency_scope(user, org) -> bool:
    """Phase 52j J1 — the org-level residency predicate. True iff:

      * The org has no residency scope defined (defaults-if-absent →
        True; load-bearing additive-layer parity for unconfigured
        orgs).
      * OR the user satisfies AT LEAST ONE scope entry (OR semantics):
        - state-only entry → ``user.verification_jurisdiction``
          equals the entry's state (case-insensitive — both are
          upper-cased).
        - city entry → ``user.verification_locality_hash`` equals
          ``compute_locality_hash(entry.city, entry.state)``. State
          is in the hash (52i cross-state disambiguation preserved).

    Independent levels (52i locked decision): a state-only entry is
    satisfied by jurisdiction match; a city entry requires the city
    hash. NO subsumption between levels — each entry is matched on
    its own terms.

    A user with neither a jurisdiction nor a locality hash → False
    against any non-empty scope (safe direction).
    """
    entries = _residency_scope_entries(org)
    if not entries:
        return True

    user_jurisdiction = getattr(user, "verification_jurisdiction", None)
    user_jurisdiction_norm = (
        user_jurisdiction.strip().upper()
        if isinstance(user_jurisdiction, str) else None
    )
    user_country = getattr(user, "verification_country", None)
    user_country_norm = (
        user_country.strip().upper()
        if isinstance(user_country, str) else None
    )
    user_locality_hash = getattr(user, "verification_locality_hash", None)

    import verification_hashing
    for entry in entries:
        # Phase 76c — a state (US) entry is matched on its own terms
        # (jurisdiction / locality), as before; state takes precedence
        # when an entry carries both. An entry with only a country is a
        # country-level match against ``verification_country``.
        if not entry.get("state"):
            if entry.get("country"):
                if user_country_norm and user_country_norm == entry["country"]:
                    return True
            continue
        if entry["city"] is None:
            # State-only entry — jurisdiction match.
            if user_jurisdiction_norm == entry["state"]:
                return True
        else:
            if not user_locality_hash:
                continue
            gate_hash = verification_hashing.compute_locality_hash(
                entry["city"], entry["state"],
            )
            if gate_hash and gate_hash == user_locality_hash:
                return True
    return False


def membership_requires_residency(org) -> bool:
    """Phase 52j J1 — does the org's membership gate require
    residency-scope match? Defaults False (additive-layer parity)."""
    settings = getattr(org, "settings", None) or {}
    if not isinstance(settings, dict):
        return False
    return bool(settings.get(SETTING_MEMBERSHIP_REQUIRE_RESIDENCY, False))


def role_requires_residency(org, role_system_key: str) -> bool:
    """Phase 52j J1 — does the org require residency-scope match for
    holders of ``role_system_key``? Reads
    ``SETTING_ROLE_REQUIRE_RESIDENCY[role_key]``; defaults False."""
    settings = getattr(org, "settings", None) or {}
    if not isinstance(settings, dict):
        return False
    role_map = settings.get(SETTING_ROLE_REQUIRE_RESIDENCY) or {}
    if not isinstance(role_map, dict):
        return False
    return bool(role_map.get(role_system_key, False))


def _residency_payload(org) -> dict:
    """Structured-403 detail body for a residency-scope failure.
    Includes the readable scope so the FE can render a meaningful
    CTA ("must be a verified resident of MA / NH / Somerville MA").
    """
    entries = _residency_scope_entries(org)
    return {
        "error": "verification_required",
        "scope": "residency_scope",
        "residency_scope": [
            {"country": e.get("country"), "state": e["state"], "city": e["city"]}
            for e in entries
        ],
    }


def check_membership_residency_for_join(user, org) -> None:
    """Phase 52j J1 — raises 403 if the org's membership gate requires
    residency and the user doesn't satisfy the org scope. No-op when
    the membership gate doesn't require residency (default)."""
    from fastapi import HTTPException
    if not membership_requires_residency(org):
        return
    if user_satisfies_residency_scope(user, org):
        return
    raise HTTPException(status_code=403, detail=_residency_payload(org))


def check_role_residency_for_grant(user, org, role_system_key: str) -> None:
    """Phase 52j J1 — raises 403 if the org requires residency to
    hold ``role_system_key`` and the user doesn't satisfy the org
    scope. No-op when the role doesn't require residency.

    Cardinality-floor invariant: same construction as
    ``check_role_grant_floor`` — the check precedes the role-id write,
    so a residency block prevents the mutation; the existing role
    holder is never demoted by a config change.
    """
    from fastapi import HTTPException
    if not role_requires_residency(org, role_system_key):
        return
    if user_satisfies_residency_scope(user, org):
        return
    raise HTTPException(status_code=403, detail=_residency_payload(org))


# ---------------------------------------------------------------------------
# Phase 52i — back-compat shims (replaced by Phase 52j J1)
# ---------------------------------------------------------------------------
#
# ``check_membership_locality_for_join`` is kept as a thin shim that
# now delegates to the Phase 52j J1 residency-scope check. The shim
# preserves the import surface for any caller wired pre-J1 (org
# routes, tests) — the new model subsumes the old single-value city
# gate. A no-op when the org has no scope + no membership residency
# requirement (the parity case).


def check_membership_locality_for_join(user, org) -> None:
    """Back-compat shim. Phase 52j J1 unified the locality gate into
    the org-level residency scope + per-gate "require residency"
    boolean. Two fire-triggers cover pre- and post-migration orgs:

      1. The new model: ``verification_membership_require_residency=
         True`` AND there's a non-empty scope.
      2. The legacy model: ``verification_membership_locality`` set
         (with jurisdiction, per the 52i rule). The
         ``_residency_scope_entries`` helper synthesizes the
         equivalent scope; an org carrying the old single-value
         keys keeps enforcing exactly as it did pre-J1.

    Either trigger raises the scope-based 403 on mismatch.
    """
    from fastapi import HTTPException
    settings = getattr(org, "settings", None) or {}
    if not isinstance(settings, dict):
        return
    legacy_locality = settings.get(SETTING_MEMBERSHIP_LOCALITY)
    legacy_active = (
        isinstance(legacy_locality, str)
        and legacy_locality.strip()
        and isinstance(settings.get(SETTING_MEMBERSHIP_JURISDICTION), str)
        and settings.get(SETTING_MEMBERSHIP_JURISDICTION, "").strip()
    )
    if not (membership_requires_residency(org) or legacy_active):
        return
    if user_satisfies_residency_scope(user, org):
        return
    raise HTTPException(status_code=403, detail=_residency_payload(org))


def user_meets_locality(user, org) -> bool:
    """Back-compat shim. Returns True when no scope is set or the
    user satisfies the org's residency scope."""
    return user_satisfies_residency_scope(user, org)
