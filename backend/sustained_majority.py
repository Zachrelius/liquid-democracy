"""
Sustained-Majority Voting Windows — pure evaluation module (Phase 8).

A proposal with sustained-majority enabled must MAINTAIN support across the
voting window rather than just pass at a single moment. The evaluation here is
data-in / data-out: callers pass snapshot tallies, configuration values, and
proposal metadata; this module returns whether failure should fire and which
mode to apply. No DB access, no I/O — fully testable.

Three failure modes:
  - "fail":     proposal moves directly to `failed` once the floor is breached
  - "extend":   voting_end is pushed once; a second breach fails the proposal
  - "escalate": proposal moves to `unresolved` for org-admin resolution

Multi-option semantics (approval / ranked_choice):
  Floor doesn't map cleanly. Instead we lock the *result* during the final
  STABLE_RESULT_FRACTION (default 0.25) of the voting window: any change to the
  computed winner during that window triggers the configured failure mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULTS: dict[str, Any] = {
    "sustained_majority_enabled_default": False,
    "sustained_majority_per_proposal_override": True,
    "sustained_majority_threshold": 0.5,
    "sustained_majority_floor": 0.45,
    "sustained_majority_failure_mode": "fail",   # fail | extend | escalate
}

ALLOWED_FAILURE_MODES = ("fail", "extend", "escalate")

# Final fraction of the voting window during which the multi-option winner is
# locked. Outside this window, winner-changes are ignored.
STABLE_RESULT_FRACTION = 0.25

# How close to the floor (in absolute support fraction) qualifies as
# "approaching the floor" for the in-app banner.
FLOOR_APPROACH_DELTA = 0.05


@dataclass(frozen=True)
class SustainedMajorityConfig:
    enabled_default: bool
    per_proposal_override: bool
    threshold: float
    floor: float
    failure_mode: str

    @property
    def is_default(self) -> bool:
        """True when the config matches all DEFAULTS verbatim."""
        return (
            self.enabled_default == DEFAULTS["sustained_majority_enabled_default"]
            and self.per_proposal_override == DEFAULTS["sustained_majority_per_proposal_override"]
            and abs(self.threshold - DEFAULTS["sustained_majority_threshold"]) < 1e-9
            and abs(self.floor - DEFAULTS["sustained_majority_floor"]) < 1e-9
            and self.failure_mode == DEFAULTS["sustained_majority_failure_mode"]
        )


def get_sustained_majority_config(org_or_settings: Any) -> SustainedMajorityConfig:
    """
    Lazy, defaults-applying accessor for org-level sustained-majority config.

    Accepts either an Organization model (uses .settings) or a raw settings
    dict, which keeps callers simple. Missing keys fall back to DEFAULTS so
    pre-Phase-8 orgs read clean values without a backfill.
    """
    if hasattr(org_or_settings, "settings"):
        raw = org_or_settings.settings or {}
    elif isinstance(org_or_settings, dict):
        raw = org_or_settings
    else:
        raw = {}

    failure_mode = raw.get(
        "sustained_majority_failure_mode",
        DEFAULTS["sustained_majority_failure_mode"],
    )
    if failure_mode not in ALLOWED_FAILURE_MODES:
        # Defensive: corrupt config falls back to fail-safe ("fail").
        failure_mode = "fail"

    return SustainedMajorityConfig(
        enabled_default=bool(raw.get(
            "sustained_majority_enabled_default",
            DEFAULTS["sustained_majority_enabled_default"],
        )),
        per_proposal_override=bool(raw.get(
            "sustained_majority_per_proposal_override",
            DEFAULTS["sustained_majority_per_proposal_override"],
        )),
        threshold=float(raw.get(
            "sustained_majority_threshold",
            DEFAULTS["sustained_majority_threshold"],
        )),
        floor=float(raw.get(
            "sustained_majority_floor",
            DEFAULTS["sustained_majority_floor"],
        )),
        failure_mode=failure_mode,
    )


def is_proposal_sustained_majority_active(
    proposal_override: Optional[bool],
    org_default_enabled: bool,
) -> bool:
    """
    Resolve the three-state per-proposal override against the org default.
    None on the proposal means "inherit"; True/False is explicit.
    """
    if proposal_override is None:
        return org_default_enabled
    return bool(proposal_override)


# ---------------------------------------------------------------------------
# Snapshot abstraction
# ---------------------------------------------------------------------------
#
# We deliberately don't import models — these dataclasses describe the shape
# that callers (the worker, tests) feed us. A real VoteSnapshot row maps onto
# BinarySnapshotPoint by reading yes/no/abstain/total_eligible directly; an
# approval/RCV "snapshot" is reconstructed from the live tally each run since
# VoteSnapshot only stores binary aggregates today.


@dataclass(frozen=True)
class BinarySnapshotPoint:
    """One sample of binary support level at a point in time."""
    simulated_time: datetime
    yes: int
    no: int
    abstain: int
    total_eligible: int

    @property
    def votes_cast(self) -> int:
        return self.yes + self.no + self.abstain

    @property
    def support_fraction(self) -> float:
        """Fraction of votes_cast that are 'yes'. Matches the existing
        threshold_met semantics (yes_pct, abstain excluded by intent)."""
        cast = self.yes + self.no + self.abstain
        return self.yes / cast if cast else 0.0

    @property
    def participation_fraction(self) -> float:
        if self.total_eligible <= 0:
            return 0.0
        return self.votes_cast / self.total_eligible


@dataclass(frozen=True)
class MultiOptionSnapshotPoint:
    """One sample of an approval / ranked_choice winner at a point in time.

    `winners` is the list of option_ids the tally would currently elect (sorted
    deterministically by the caller — typically by option_id). For approval and
    IRV this is normally length 1; ties produce length > 1.
    """
    simulated_time: datetime
    winners: tuple[str, ...]
    total_ballots_cast: int
    total_eligible: int


# ---------------------------------------------------------------------------
# Pure evaluation primitives
# ---------------------------------------------------------------------------

def is_above_floor(
    snapshot: BinarySnapshotPoint,
    config: SustainedMajorityConfig,
) -> bool:
    """
    True iff the snapshot's support level is at or above the configured floor.

    Edge case: zero ballots cast counts as ABOVE the floor — the floor is a
    drop-detector, not a participation gate. Quorum is enforced separately at
    proposal-close time.
    """
    if snapshot.votes_cast == 0:
        return True
    return snapshot.support_fraction >= config.floor


def winner_stable(
    snapshot: MultiOptionSnapshotPoint,
    previous_snapshot: MultiOptionSnapshotPoint,
) -> bool:
    """
    True iff the computed winner set is the same in both snapshots.

    Order-insensitive; we compare as a frozenset so a 1-element [A] vs [A]
    matches even if the underlying tally re-ordered ties differently.
    """
    return frozenset(snapshot.winners) == frozenset(previous_snapshot.winners)


def in_stable_result_window(
    now: datetime,
    voting_start: datetime,
    voting_end: datetime,
    fraction: float = STABLE_RESULT_FRACTION,
) -> bool:
    """
    True iff `now` falls inside the final `fraction` of the voting window.

    Boundary: at exactly `start + (1-fraction)*duration` the window opens;
    earlier instants return False, equal-or-later return True.
    """
    if voting_end <= voting_start:
        return False
    duration = (voting_end - voting_start).total_seconds()
    if duration <= 0:
        return False
    elapsed = (now - voting_start).total_seconds()
    return (elapsed / duration) >= (1.0 - fraction)


# ---------------------------------------------------------------------------
# Trigger evaluation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FailureDecision:
    """What the worker should do in response to the latest snapshot.

    `should_fire` is True iff the configured failure mode should be applied.
    `mode` is the failure mode that fired (matches config.failure_mode for
    convenience). `reason` is an audit-friendly summary string.
    """
    should_fire: bool
    mode: Optional[str] = None
    reason: str = ""
    # For binary: the breach sample. For multi-option: the snapshot whose
    # winner changed. Used for audit-log detail payloads.
    breach_sample: Any = None


def evaluate_binary(
    latest: BinarySnapshotPoint,
    config: SustainedMajorityConfig,
) -> FailureDecision:
    """Evaluate one binary snapshot against the floor. Pure."""
    if is_above_floor(latest, config):
        return FailureDecision(should_fire=False)
    return FailureDecision(
        should_fire=True,
        mode=config.failure_mode,
        reason=(
            f"Support {latest.support_fraction:.3f} below floor {config.floor:.3f} "
            f"at {latest.simulated_time.isoformat()}"
        ),
        breach_sample={
            "simulated_time": latest.simulated_time.isoformat(),
            "support_fraction": round(latest.support_fraction, 4),
            "floor": config.floor,
            "yes": latest.yes,
            "no": latest.no,
            "abstain": latest.abstain,
            "total_eligible": latest.total_eligible,
        },
    )


def evaluate_multi_option(
    latest: MultiOptionSnapshotPoint,
    previous: Optional[MultiOptionSnapshotPoint],
    config: SustainedMajorityConfig,
    voting_start: datetime,
    voting_end: datetime,
    now: datetime,
    fraction: float = STABLE_RESULT_FRACTION,
) -> FailureDecision:
    """
    Evaluate a multi-option snapshot. Outside the stable-result window we never
    fire; inside, any winner change versus the previous snapshot triggers the
    configured failure mode.
    """
    if not in_stable_result_window(now, voting_start, voting_end, fraction):
        return FailureDecision(should_fire=False)
    if previous is None:
        return FailureDecision(should_fire=False)
    if winner_stable(latest, previous):
        return FailureDecision(should_fire=False)
    return FailureDecision(
        should_fire=True,
        mode=config.failure_mode,
        reason=(
            f"Winner changed from {sorted(previous.winners)} to "
            f"{sorted(latest.winners)} at {latest.simulated_time.isoformat()} "
            f"(within final {fraction:.0%} of window)"
        ),
        breach_sample={
            "simulated_time": latest.simulated_time.isoformat(),
            "previous_winners": sorted(previous.winners),
            "current_winners": sorted(latest.winners),
            "fraction_window": fraction,
        },
    )


def should_trigger_failure(
    voting_method: str,
    snapshots: list,
    config: SustainedMajorityConfig,
    voting_start: datetime,
    voting_end: datetime,
    now: datetime,
    extension_count: int = 0,
) -> FailureDecision:
    """
    Top-level decision: combine the binary/multi-option logic with the
    failure-mode rules (extend bumps the deadline once; escalate moves to
    unresolved; fail closes the proposal).

    `extension_count` is how many times this proposal has already been
    extended — for `extend` mode, we fire the extension only when count == 0
    and otherwise return `fail`.
    """
    if not snapshots:
        return FailureDecision(should_fire=False)

    latest = snapshots[-1]

    if voting_method == "binary":
        decision = evaluate_binary(latest, config)
    else:
        previous = snapshots[-2] if len(snapshots) >= 2 else None
        decision = evaluate_multi_option(
            latest, previous, config, voting_start, voting_end, now,
        )

    if not decision.should_fire:
        return decision

    # Apply the failure_mode escalation logic — `extend` only extends once,
    # then promotes to `fail` on the second breach.
    if decision.mode == "extend" and extension_count >= 1:
        return FailureDecision(
            should_fire=True,
            mode="fail",
            reason=decision.reason + " (second breach after one extension)",
            breach_sample=decision.breach_sample,
        )

    return decision


# ---------------------------------------------------------------------------
# Floor-approach detection (for in-app banner)
# ---------------------------------------------------------------------------

def is_approaching_floor(
    snapshot: BinarySnapshotPoint,
    config: SustainedMajorityConfig,
    delta: float = FLOOR_APPROACH_DELTA,
) -> bool:
    """
    True iff support is currently within `delta` percentage points above the
    floor (or at/below the floor). Drives the in-app warning banner.
    """
    if snapshot.votes_cast == 0:
        return False
    return snapshot.support_fraction <= config.floor + delta


# ---------------------------------------------------------------------------
# Helpers for callers
# ---------------------------------------------------------------------------

def extension_window_for(
    voting_start: datetime,
    voting_end: datetime,
) -> timedelta:
    """
    Default extension length = the original voting window's duration. This is
    aggressive but matches the spec intent: an extension gives voters as much
    time as they originally had to recover support.
    """
    return voting_end - voting_start
