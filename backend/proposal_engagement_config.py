"""Phase 32.2 S cluster — 4-option mode resolution for the four
deliberation-engagement boolean flags (write-ins allowed, write-ins
during voting, pre-voting allowed, vote-totals visibility during
deliberation). Phase 32 + 32.1 shipped these as boolean defaults; the
Phase 32.2 migration (``e7a3d1c84920``) rewrote them to enum-typed
mode strings: ``always_off`` / ``default_off`` / ``default_on`` /
``always_on``.

Resolution semantics (per spec D4):

    always_off  → effective=False, overridable=False
    default_off → effective=(override if not None else False), overridable=True
    default_on  → effective=(override if not None else True),  overridable=True
    always_on   → effective=True,  overridable=False

The numeric settings (``write_ins.max_per_proposal``,
``proposal_edits.lockout_fraction``) and the per-proposal-override
fields they back stay numeric — they did not migrate. Their resolvers
keep their Phase 32 shape: per-proposal override beats org setting
beats platform default.

This module returns BOTH the effective value and the overridable flag
so the create/edit form can render the toggle correctly (hidden /
disabled when ``always_*``, visible + pre-filled when ``default_*``).

Spec: phase32_2_org_controls_and_bug_fixes_spec.md §B1
"""
from __future__ import annotations

from typing import NamedTuple, Optional

import models


# ----- Modes --------------------------------------------------------------

MODE_ALWAYS_OFF = "always_off"
MODE_DEFAULT_OFF = "default_off"
MODE_DEFAULT_ON = "default_on"
MODE_ALWAYS_ON = "always_on"
ALL_MODES = (MODE_ALWAYS_OFF, MODE_DEFAULT_OFF, MODE_DEFAULT_ON, MODE_ALWAYS_ON)


# Platform defaults — used when the org settings JSONB doesn't supply a
# mode for a given knob. Phase 32's platform defaults map cleanly to the
# new mode enum:
#   write_ins allowed → off-by-default → default_off
#   write_ins during voting → on-by-default → default_on
#   pre_voting allowed → off-by-default → default_off
#   pre_voting visibility → off-by-default → default_off
PLATFORM_DEFAULT_WRITE_INS_MODE: str = MODE_DEFAULT_OFF
PLATFORM_DEFAULT_WRITE_INS_DURING_VOTING_MODE: str = MODE_DEFAULT_ON
PLATFORM_DEFAULT_PRE_VOTING_MODE: str = MODE_DEFAULT_OFF
PLATFORM_DEFAULT_VISIBILITY_MODE: str = MODE_DEFAULT_OFF

# Numeric platform defaults — unchanged from Phase 32.
PLATFORM_DEFAULT_MAX_WRITE_INS: int = 10
PLATFORM_DEFAULT_EDIT_LOCKOUT_FRACTION: float = 0.75


class ResolvedFlag(NamedTuple):
    """Effective boolean for a deliberation-engagement flag, plus whether
    a proposal can override it. ``overridable=False`` when the org has
    locked the flag with ``always_off`` or ``always_on``; the create/
    edit form should hide or disable the per-proposal toggle in that
    case. Per-proposal override fields with a non-null value still
    exist on the DB row but are ignored at resolution time when the
    org mode is locked."""
    effective: bool
    overridable: bool
    mode: str


def _resolve_mode(
    mode: Optional[str],
    proposal_override: Optional[bool],
    platform_default: str,
) -> ResolvedFlag:
    """Apply the four-mode resolution table. Unknown / missing modes
    fall back to the platform default."""
    if mode not in ALL_MODES:
        mode = platform_default
    if mode == MODE_ALWAYS_OFF:
        return ResolvedFlag(False, False, mode)
    if mode == MODE_ALWAYS_ON:
        return ResolvedFlag(True, False, mode)
    if mode == MODE_DEFAULT_OFF:
        eff = bool(proposal_override) if proposal_override is not None else False
        return ResolvedFlag(eff, True, mode)
    # MODE_DEFAULT_ON
    eff = bool(proposal_override) if proposal_override is not None else True
    return ResolvedFlag(eff, True, mode)


def _org_mode(
    org: Optional[models.Organization],
    section: str,
    key: str,
    platform_default: str,
) -> str:
    if org is None:
        return platform_default
    settings = getattr(org, "settings", None) or {}
    section_dict = settings.get(section)
    if not isinstance(section_dict, dict):
        return platform_default
    val = section_dict.get(key)
    return val if val in ALL_MODES else platform_default


def _assert_org_loaded_for(proposal: "models.Proposal", org: Optional["models.Organization"]) -> None:
    """Phase 33 B1 — loud-failure guard for the recurring Phase 32/32.1/32.2
    bug pattern.

    The bug was: a response builder accepted ``db: Optional[Session] = None``,
    callers omitted db, builder couldn't load Organization, resolver received
    ``org=None``, resolver silently fell back to the platform default —
    invisible at test time, visible only as "the always_on mode does nothing"
    in prod. Hotfix #1 made db required at the builder layer. This guard
    closes the resolver-layer half: when a proposal HAS an org_id but the
    caller passed ``org=None`` anyway, the resolver raises rather than
    silently returning the platform default.

    Proposals with ``org_id=None`` (pre-Phase-4c legacy rows) legitimately
    have no org; the resolver should still fall back to the platform default
    for them — that path stays valid.
    """
    if getattr(proposal, "org_id", None) is not None and org is None:
        raise ValueError(
            f"resolve_*: proposal {getattr(proposal, 'id', '?')!r} has "
            f"org_id={proposal.org_id!r} but org was not loaded. This is "
            "the recurring Phase 32/32.1/32.2 bug pattern — the response "
            "builder must load the Organization row and pass it through "
            "to the resolver. See feedback_response_builder_db_required.md."
        )


# ----- Write-ins ----------------------------------------------------------

def resolve_allow_write_in_options_full(
    proposal: models.Proposal,
    org: Optional[models.Organization],
) -> ResolvedFlag:
    _assert_org_loaded_for(proposal, org)
    return _resolve_mode(
        _org_mode(org, "write_ins", "allowed_mode", PLATFORM_DEFAULT_WRITE_INS_MODE),
        proposal.allow_write_in_options,
        PLATFORM_DEFAULT_WRITE_INS_MODE,
    )


def resolve_allow_write_in_options(
    proposal: models.Proposal,
    org: Optional[models.Organization],
) -> bool:
    return resolve_allow_write_in_options_full(proposal, org).effective


def resolve_allow_write_ins_during_voting_full(
    proposal: models.Proposal,
    org: Optional[models.Organization],
) -> ResolvedFlag:
    _assert_org_loaded_for(proposal, org)
    return _resolve_mode(
        _org_mode(
            org, "write_ins", "during_voting_mode",
            PLATFORM_DEFAULT_WRITE_INS_DURING_VOTING_MODE,
        ),
        proposal.allow_write_ins_during_voting,
        PLATFORM_DEFAULT_WRITE_INS_DURING_VOTING_MODE,
    )


def resolve_allow_write_ins_during_voting(
    proposal: models.Proposal,
    org: Optional[models.Organization],
) -> bool:
    return resolve_allow_write_ins_during_voting_full(proposal, org).effective


def resolve_max_write_ins(
    proposal: models.Proposal,
    org: Optional[models.Organization],
) -> int:
    if proposal.max_write_ins is not None:
        return int(proposal.max_write_ins)
    _assert_org_loaded_for(proposal, org)
    if org is None:
        return PLATFORM_DEFAULT_MAX_WRITE_INS
    settings = getattr(org, "settings", None) or {}
    section = settings.get("write_ins")
    if isinstance(section, dict):
        v = section.get("max_per_proposal", PLATFORM_DEFAULT_MAX_WRITE_INS)
        try:
            return int(v)
        except (TypeError, ValueError):
            return PLATFORM_DEFAULT_MAX_WRITE_INS
    return PLATFORM_DEFAULT_MAX_WRITE_INS


# ----- Pre-voting ---------------------------------------------------------

def resolve_allow_pre_voting_full(
    proposal: models.Proposal,
    org: Optional[models.Organization],
) -> ResolvedFlag:
    _assert_org_loaded_for(proposal, org)
    return _resolve_mode(
        _org_mode(
            org, "pre_voting", "allowed_mode", PLATFORM_DEFAULT_PRE_VOTING_MODE,
        ),
        proposal.allow_pre_voting,
        PLATFORM_DEFAULT_PRE_VOTING_MODE,
    )


def resolve_allow_pre_voting(
    proposal: models.Proposal,
    org: Optional[models.Organization],
) -> bool:
    return resolve_allow_pre_voting_full(proposal, org).effective


def resolve_show_votes_during_deliberation_full(
    proposal: models.Proposal,
    org: Optional[models.Organization],
) -> ResolvedFlag:
    _assert_org_loaded_for(proposal, org)
    return _resolve_mode(
        _org_mode(
            org, "pre_voting", "visibility_mode",
            PLATFORM_DEFAULT_VISIBILITY_MODE,
        ),
        proposal.show_votes_during_deliberation,
        PLATFORM_DEFAULT_VISIBILITY_MODE,
    )


def resolve_show_votes_during_deliberation(
    proposal: models.Proposal,
    org: Optional[models.Organization],
) -> bool:
    return resolve_show_votes_during_deliberation_full(proposal, org).effective


# ----- Author edits -------------------------------------------------------

def resolve_edit_lockout_fraction(
    proposal: models.Proposal,
    org: Optional[models.Organization],
) -> float:
    if proposal.edit_lockout_fraction is not None:
        return float(proposal.edit_lockout_fraction)
    _assert_org_loaded_for(proposal, org)
    if org is None:
        return PLATFORM_DEFAULT_EDIT_LOCKOUT_FRACTION
    settings = getattr(org, "settings", None) or {}
    section = settings.get("proposal_edits")
    if isinstance(section, dict):
        v = section.get("lockout_fraction", PLATFORM_DEFAULT_EDIT_LOCKOUT_FRACTION)
        try:
            return float(v)
        except (TypeError, ValueError):
            return PLATFORM_DEFAULT_EDIT_LOCKOUT_FRACTION
    return PLATFORM_DEFAULT_EDIT_LOCKOUT_FRACTION
