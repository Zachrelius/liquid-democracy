"""Phase 32 S cluster — resolution for the three new deliberation-engagement
config knobs (write-ins, pre-voting, author edits).

Each knob has the same shape:
  - Optional per-proposal override column on ``Proposal`` (added in the
    Phase 32 migration; null = inherit org default).
  - Org-level default under ``Organization.settings`` JSONB (nested dict
    per feature: ``settings.write_ins.*``, ``settings.pre_voting.*``,
    ``settings.proposal_edits.*``).
  - Platform-wide fallback (constants below) when neither org nor
    proposal supply a value.

Resolution order (mirrors the Phase 12.5 threshold helper pattern):
  1. proposal-level column (if not None) → use directly.
  2. org settings[feature][key] (if present) → use.
  3. platform default → use.

These helpers read but never write. The ``Organization.settings`` JSONB
is updated by the org-settings PATCH route (or seed_pipeline for demo
orgs); per-proposal overrides land via the existing proposal PATCH
endpoint that this pass extends.

Spec: phase32_deliberation_engagement_spec.md §S
"""
from __future__ import annotations

from typing import Optional

import models


# ----- Platform defaults --------------------------------------------------

PLATFORM_DEFAULT_WRITE_INS_ALLOWED: bool = False
PLATFORM_DEFAULT_WRITE_INS_DURING_VOTING: bool = True
PLATFORM_DEFAULT_MAX_WRITE_INS: int = 10
PLATFORM_DEFAULT_PRE_VOTING_ALLOWED: bool = False
PLATFORM_DEFAULT_SHOW_VOTES_DURING_DELIBERATION: bool = False
PLATFORM_DEFAULT_EDIT_LOCKOUT_FRACTION: float = 0.75


def _org_setting(
    org: Optional[models.Organization],
    section: str,
    key: str,
    fallback,
):
    """Look up ``settings[section][key]`` on the org; return fallback if
    section/key missing or the section isn't a dict."""
    if org is None:
        return fallback
    settings = getattr(org, "settings", None) or {}
    section_dict = settings.get(section)
    if not isinstance(section_dict, dict):
        return fallback
    return section_dict.get(key, fallback)


# ----- Write-ins ----------------------------------------------------------

def resolve_allow_write_in_options(
    proposal: models.Proposal,
    org: Optional[models.Organization],
) -> bool:
    if proposal.allow_write_in_options is not None:
        return bool(proposal.allow_write_in_options)
    return bool(_org_setting(
        org, "write_ins", "allowed_default",
        PLATFORM_DEFAULT_WRITE_INS_ALLOWED,
    ))


def resolve_allow_write_ins_during_voting(
    proposal: models.Proposal,
    org: Optional[models.Organization],
) -> bool:
    if proposal.allow_write_ins_during_voting is not None:
        return bool(proposal.allow_write_ins_during_voting)
    return bool(_org_setting(
        org, "write_ins", "during_voting_default",
        PLATFORM_DEFAULT_WRITE_INS_DURING_VOTING,
    ))


def resolve_max_write_ins(
    proposal: models.Proposal,
    org: Optional[models.Organization],
) -> int:
    if proposal.max_write_ins is not None:
        return int(proposal.max_write_ins)
    return int(_org_setting(
        org, "write_ins", "max_per_proposal",
        PLATFORM_DEFAULT_MAX_WRITE_INS,
    ))


# ----- Pre-voting ---------------------------------------------------------

def resolve_allow_pre_voting(
    proposal: models.Proposal,
    org: Optional[models.Organization],
) -> bool:
    if proposal.allow_pre_voting is not None:
        return bool(proposal.allow_pre_voting)
    return bool(_org_setting(
        org, "pre_voting", "allowed_default",
        PLATFORM_DEFAULT_PRE_VOTING_ALLOWED,
    ))


def resolve_show_votes_during_deliberation(
    proposal: models.Proposal,
    org: Optional[models.Organization],
) -> bool:
    if proposal.show_votes_during_deliberation is not None:
        return bool(proposal.show_votes_during_deliberation)
    return bool(_org_setting(
        org, "pre_voting", "show_votes_during_deliberation_default",
        PLATFORM_DEFAULT_SHOW_VOTES_DURING_DELIBERATION,
    ))


# ----- Author edits -------------------------------------------------------

def resolve_edit_lockout_fraction(
    proposal: models.Proposal,
    org: Optional[models.Organization],
) -> float:
    if proposal.edit_lockout_fraction is not None:
        return float(proposal.edit_lockout_fraction)
    return float(_org_setting(
        org, "proposal_edits", "lockout_fraction",
        PLATFORM_DEFAULT_EDIT_LOCKOUT_FRACTION,
    ))
