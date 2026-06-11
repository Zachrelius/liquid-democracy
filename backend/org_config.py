"""Org config resolution that walks the parent chain.

Used by config reads where a sub-org should inherit from its parent unless it
sets its own override. See Phase 8.5 spec Decision 9.

Resolution order for a sub-org:
  1. Sub-org's own ``settings`` if the key is present
  2. Parent org's ``settings`` if the key is present
  3. Caller-supplied ``default``

For parent orgs (``parent_org_id IS NULL``), the walk degenerates to a single
lookup followed by the default — bit-for-bit equivalent to the existing
``org.settings.get(key, default)`` pattern, so call sites that don't yet know
about sub-orgs can safely migrate without behavioral change.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import models


_log = logging.getLogger(__name__)


# Two-level hierarchy is locked in by Decision 1, but the loop walks
# ``parent_org_id`` defensively until it hits None or this safety bound. A
# cycle or schema drift past 5 hops indicates a bug worth surfacing rather
# than silently returning the default.
_MAX_PARENT_WALK_DEPTH = 5


# Phase 16 — platform-default durations. Mirror the values in
# `routes/organizations.py::DEFAULT_ORG_SETTINGS` (default_deliberation_days=14,
# default_voting_days=7). Floats so callers can compare fractional values
# from POST/PATCH bodies without int-vs-float type confusion.
PLATFORM_DEFAULT_DELIBERATION_DAYS: float = 14.0
PLATFORM_DEFAULT_VOTING_DAYS: float = 7.0


def get_default_proposal_durations(
    org: Optional[models.Organization],
) -> tuple[float, float]:
    """Return ``(deliberation_days, voting_days)`` defaults for new
    proposals in this org.

    Phase 16 — central helper for org-level duration defaults. Reads
    ``Organization.settings['default_deliberation_days']`` and
    ``Organization.settings['default_voting_days']`` if present; falls
    back to the platform-wide defaults (14.0 / 7.0, matching
    ``routes/organizations.py::DEFAULT_ORG_SETTINGS``).

    Mirror of ``get_default_proposal_thresholds``: same Optional[org] +
    settings.get + cast-to-float pattern. NO migration backfill of these
    keys into existing org settings JSON — defaults-if-absent here covers
    every existing org transparently.

    Like the threshold helper, this does NOT walk the parent chain via
    ``get_org_config``: per-sub-org override is deferred (Phase 16
    "What this pass is NOT" §"Per-sub-org default durations"). Sub-orgs
    inherit parent defaults today.

    Returns floats unconditionally so callers can compare against
    request-body floats safely (a stored int 7 still resolves to 7.0).
    """
    if org is None:
        return (PLATFORM_DEFAULT_DELIBERATION_DAYS, PLATFORM_DEFAULT_VOTING_DAYS)
    settings = org.settings or {}
    delib = settings.get(
        "default_deliberation_days", PLATFORM_DEFAULT_DELIBERATION_DAYS,
    )
    vote = settings.get(
        "default_voting_days", PLATFORM_DEFAULT_VOTING_DAYS,
    )
    return (float(delib), float(vote))


def get_default_proposal_thresholds(
    org: Optional[models.Organization],
) -> tuple[float, float]:
    """Return ``(pass_threshold, quorum_threshold)`` defaults for new
    proposals in this org.

    Phase 12.5 — central helper for org-level threshold defaults. Reads
    ``Organization.settings['default_pass_threshold']`` and
    ``Organization.settings['default_quorum_threshold']`` if present;
    falls back to the platform-wide defaults (0.50 / 0.40, matching the
    pre-12.5 per-proposal defaults).

    Spec line 122 explicit: NO migration backfill of these keys into
    every existing org's settings JSON — defaults-if-absent here covers
    every existing org transparently. Only orgs whose Steward has
    customised the defaults via the new Org Settings UI will have these
    keys persisted.

    The helper does NOT walk the parent chain via ``get_org_config``:
    the spec's "What this pass is NOT" §"Per-sub-org thresholds" defers
    that to a future pass; sub-orgs inherit parent defaults today by
    virtue of new sub-org-scoped proposals reading the parent org's
    config when they don't have their own.
    """
    if org is None:
        return (0.50, 0.40)
    settings = org.settings or {}
    pass_t = settings.get("default_pass_threshold", 0.50)
    quorum_t = settings.get("default_quorum_threshold", 0.40)
    return (pass_t, quorum_t)


def get_org_tie_resolution_method(
    org: Optional[models.Organization],
    voting_method: str,
) -> str:
    """Return the configured tie-resolution method for this org and
    ``voting_method``. Falls back to platform defaults if the org's
    settings don't specify a value, or if the stored value isn't an
    eligible method (defensive fallback for direct-DB-poke / removed-
    method legacy values).

    ``voting_method`` must be ``'approval'`` or ``'ranked_choice'``.
    Binary doesn't have a tie-resolution path; callers must not invoke
    this for binary proposals.

    Mirror of ``get_default_proposal_thresholds`` /
    ``get_default_proposal_durations``: same Optional[org] +
    settings.get pattern. Like those helpers, this does NOT walk the
    parent chain via ``get_org_config`` - sub-orgs inherit parent's
    setting today (Phase 17 D2: per-sub-org override deferred).

    For ``org=None`` (global proposals - pre-multi-tenancy legacy
    rows), returns the platform default for the requested
    voting_method.
    """
    # Local import: keeps tie_resolution out of the module-import graph
    # for the threshold/duration callers that don't need it, and avoids
    # any possible circular if tie_resolution ever needs org_config.
    from tie_resolution import (
        ELIGIBLE_METHODS_APPROVAL,
        ELIGIBLE_METHODS_RANKED_CHOICE,
        PLATFORM_DEFAULT_TIE_RESOLUTION_APPROVAL,
        PLATFORM_DEFAULT_TIE_RESOLUTION_RANKED_CHOICE,
    )

    if voting_method == "approval":
        platform_default = PLATFORM_DEFAULT_TIE_RESOLUTION_APPROVAL
        eligible = ELIGIBLE_METHODS_APPROVAL
    elif voting_method == "ranked_choice":
        platform_default = PLATFORM_DEFAULT_TIE_RESOLUTION_RANKED_CHOICE
        eligible = ELIGIBLE_METHODS_RANKED_CHOICE
    else:
        # Defensive: caller passed an unsupported voting_method
        # (binary doesn't have tie resolution, or a future/typo value).
        # Log once and fall back to approval's platform default - safest
        # generic option.
        _log.warning(
            "get_org_tie_resolution_method called with unsupported "
            "voting_method=%r; falling back to approval platform default.",
            voting_method,
        )
        return PLATFORM_DEFAULT_TIE_RESOLUTION_APPROVAL

    if org is None:
        return platform_default

    settings = org.settings or {}
    tr_settings = settings.get("tie_resolution")
    if not isinstance(tr_settings, dict):
        return platform_default

    stored = tr_settings.get(voting_method)
    if stored is None:
        return platform_default

    if stored not in eligible:
        _log.warning(
            "Org id=%s has invalid tie-resolution method %r for "
            "voting_method=%r; falling back to platform default %r.",
            getattr(org, "id", None),
            stored,
            voting_method,
            platform_default,
        )
        return platform_default

    return stored


def get_intro_text(org: Optional[models.Organization]) -> Optional[str]:
    """Return the org's optional intro text for the public landing page.

    Phase 14 — markdown-supported text rendered on the org's public splash
    page below name + description. Lives on
    ``Organization.settings.intro_text`` (JSON key in the existing
    ``settings`` column; no schema column added).

    Empty string is treated as None (no section rendered) — the frontend
    hides the intro section entirely when the value is null/empty so
    stewards can clear the field by submitting an empty value.

    Does NOT walk the parent chain (intro is per-org self-presentation,
    not a config knob with sub-org inheritance semantics).
    """
    if org is None:
        return None
    settings = org.settings or {}
    val = settings.get("intro_text")
    if not val:
        return None
    return val


def delegation_enabled_for_org(org: Optional[models.Organization]) -> bool:
    """Return whether delegation is enabled org-wide (Phase 65 master
    switch).

    Reads ``Organization.settings['delegation']['enabled']`` with a
    read-time default of True — absent key, non-dict section, or
    non-bool value all resolve to True (delegation on). The read-time
    default deliberately sidesteps the existing-orgs backfill gotcha
    (Phase 65 D3): no settings key is written until an org explicitly
    flips the switch.

    ``org=None`` (legacy / pre-multi-tenancy proposals) returns True —
    the master switch is an org-level self-constraint and there is no
    org to have imposed it.

    Like the sibling resolvers above, this does NOT walk the parent
    chain via ``get_org_config``; sub-orgs inherit the parent org's
    behavior by virtue of proposals carrying the parent ``org_id``.
    """
    if org is None:
        return True
    settings = org.settings or {}
    section = settings.get("delegation")
    if not isinstance(section, dict):
        return True
    val = section.get("enabled")
    if not isinstance(val, bool):
        return True
    return val


def proposal_is_delegation_gated(
    proposal: models.Proposal,
    org: Optional[models.Organization],
    topics: list[models.Topic],
) -> bool:
    """Return True when the proposal is direct-vote-only (Phase 65).

    A proposal is delegation-gated when EITHER:
      * the org master switch is off (``delegation_enabled_for_org``), OR
      * ANY topic attached to the proposal has ``allow_delegation=False``
        (D1 — whole-proposal gating; blocking only the per-topic channel
        would let global delegations carry the vote, and tagging a second
        topic would re-enable delegation).

    Untagged proposals (``topics == []``) are only affected by the org
    master switch, never by per-topic flags (D4).

    ``topics`` is the list of Topic rows attached to the proposal —
    callers fetch them (the predicate stays query-free so it can run on
    already-loaded rows). ``getattr`` default True keeps duck-typed test
    shims and pre-migration rows on today's behavior.
    """
    if not delegation_enabled_for_org(org):
        return True
    for t in topics:
        if getattr(t, "allow_delegation", True) is False:
            return True
    return False


def get_org_config(
    org: Optional[models.Organization], key: str, default: Any = None,
) -> Any:
    """Resolve a config key for an org, walking the parent chain.

    Order: org's own settings if key present -> parent's settings if key
    present -> default. Two-level only by Decision 1; the loop is bounded
    by walking ``parent_org_id`` until None to be defensive.

    A ``None`` org argument returns the default immediately — useful for
    optional-org callers (e.g., proposals with org_id IS NULL).

    Raises RuntimeError if the parent walk exceeds _MAX_PARENT_WALK_DEPTH;
    that indicates a cycle or schema drift, both of which deserve loud
    failure over silent fallback.
    """
    current: Optional[models.Organization] = org
    depth = 0
    while current is not None:
        if depth >= _MAX_PARENT_WALK_DEPTH:
            raise RuntimeError(
                f"get_org_config exceeded max parent-walk depth "
                f"({_MAX_PARENT_WALK_DEPTH}) for key={key!r} starting at "
                f"org id={getattr(org, 'id', None)}. Cycle or schema drift?"
            )
        settings = getattr(current, "settings", None)
        if isinstance(settings, dict) and key in settings:
            return settings[key]
        # ``parent_org`` is the ORM relationship; duck-typed test objects
        # without this attribute behave as if they had no parent (the walk
        # stops cleanly at the bottom of the chain).
        current = getattr(current, "parent_org", None)
        depth += 1
    return default
