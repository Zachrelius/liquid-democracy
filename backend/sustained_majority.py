"""
Stable-Result-Required — pure evaluation module (Phase 20 redesign).

A proposal with "Stable Result Required" enabled must produce a stable result
across the closing portion of its voting window. The mechanic is unified across
voting methods:

  - Binary: every snapshot in the stable window must have
    ``support_fraction >= pass_threshold``.
  - Multi-option (approval / ranked_choice): every adjacent pair of snapshots
    in the stable window must have ``frozenset(prev.winners) &
    frozenset(curr.winners) != frozenset()`` (non-empty intersection).

The "stable window" is the final ``stable_window_fraction`` (default 0.25) of
the original voting period. Destabilization in the stable window triggers an
extension equal to ``stable_window_fraction * original_voting_duration``. The
total cumulative extension time across all extensions cannot exceed
``max_extension_fraction * original_voting_duration``.

During an extension the worker uses a sliding-window check
(``evaluate_extension_stability``): voting can close as soon as the proposal
has demonstrated stability for the most recent ``stable_window_duration`` of
snapshots, rather than waiting for the extension's natural ``voting_end``.

Pure module: no DB access, no I/O. Callers feed snapshot rows + config + the
proposal's voting timestamps and read back a decision.

Phase 20 removes (D1, D13):
  - The binary "floor" mechanic (``support_ever_established``, ``is_above_floor``,
    ``is_approaching_floor``, ``FLOOR_APPROACH_DELTA``)
  - The ``failure_mode`` axis (``fail`` / ``extend`` / ``escalate``); only the
    extension path remains, plus a force-close on exhausted extension budget.
  - ``evaluate_binary``, ``evaluate_multi_option``, ``should_trigger_failure``,
    ``extension_window_for``, ``STABLE_RESULT_FRACTION`` constant.

The filename ``sustained_majority.py`` is preserved for one pass; rename to
``stable_result.py`` is deferred to a future cleanup (per spec §B4).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
#
# Phase 20 D13: drop ``sustained_majority_floor``,
# ``sustained_majority_failure_mode``, and ``sustained_majority_threshold``
# entirely. Add ``stable_window_fraction`` and ``max_extension_fraction``.
# Rename ``sustained_majority_enabled_default`` ->
# ``stable_result_enabled_default`` and
# ``sustained_majority_per_proposal_override`` ->
# ``stable_result_per_proposal_override``.
#
# Old keys present in an org's settings JSON are silently ignored (no migration
# of values, per spec §G).

DEFAULTS: dict[str, Any] = {
    "stable_result_enabled_default": False,
    "stable_result_per_proposal_override": True,
    "stable_window_fraction": 0.25,
    "max_extension_fraction": 0.25,
}


@dataclass(frozen=True)
class StableResultConfig:
    enabled_default: bool
    per_proposal_override: bool
    stable_window_fraction: float       # 0.05 to 0.50
    max_extension_fraction: float       # 0.0 to 1.0

    @property
    def is_default(self) -> bool:
        """True when the config matches all DEFAULTS verbatim."""
        return (
            self.enabled_default == DEFAULTS["stable_result_enabled_default"]
            and self.per_proposal_override == DEFAULTS["stable_result_per_proposal_override"]
            and abs(self.stable_window_fraction - DEFAULTS["stable_window_fraction"]) < 1e-9
            and abs(self.max_extension_fraction - DEFAULTS["max_extension_fraction"]) < 1e-9
        )


def _clamp(value: float, lo: float, hi: float) -> float:
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def get_stable_result_config(org_or_settings: Any) -> StableResultConfig:
    """
    Lazy, defaults-applying accessor for org-level Stable Result Required config.

    Accepts either an Organization model (uses ``.settings``, walking the
    parent-org chain via :func:`org_config.get_org_config` per Phase 8.5) or
    a raw settings dict. Missing keys fall back to ``DEFAULTS`` so pre-Phase-20
    orgs read clean values without a backfill.

    Old (pre-Phase-20) ``sustained_majority_*`` keys present in the settings
    JSON are silently ignored — no automatic value migration.
    """
    is_org = hasattr(org_or_settings, "settings") and not isinstance(
        org_or_settings, dict
    )
    if is_org:
        from org_config import get_org_config

        def _read(key: str) -> Any:
            return get_org_config(org_or_settings, key, DEFAULTS[key])

        swf = float(_read("stable_window_fraction"))
        mef = float(_read("max_extension_fraction"))
        return StableResultConfig(
            enabled_default=bool(_read("stable_result_enabled_default")),
            per_proposal_override=bool(_read("stable_result_per_proposal_override")),
            # Bound stable_window_fraction to [0.05, 0.50] per D2.
            stable_window_fraction=_clamp(swf, 0.05, 0.50),
            # Bound max_extension_fraction to [0.0, 1.0] per D9.
            max_extension_fraction=_clamp(mef, 0.0, 1.0),
        )

    raw = org_or_settings if isinstance(org_or_settings, dict) else {}
    swf = float(raw.get("stable_window_fraction", DEFAULTS["stable_window_fraction"]))
    mef = float(raw.get("max_extension_fraction", DEFAULTS["max_extension_fraction"]))
    return StableResultConfig(
        enabled_default=bool(raw.get(
            "stable_result_enabled_default",
            DEFAULTS["stable_result_enabled_default"],
        )),
        per_proposal_override=bool(raw.get(
            "stable_result_per_proposal_override",
            DEFAULTS["stable_result_per_proposal_override"],
        )),
        stable_window_fraction=_clamp(swf, 0.05, 0.50),
        max_extension_fraction=_clamp(mef, 0.0, 1.0),
    )


def is_proposal_stable_result_active(
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
# Pure-module shapes. The worker lifts ``VoteSnapshot`` rows into these so the
# evaluation logic stays decoupled from the ORM.


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
        """Fraction of votes_cast that are 'yes'."""
        cast = self.yes + self.no + self.abstain
        return self.yes / cast if cast else 0.0

    @property
    def participation_fraction(self) -> float:
        if self.total_eligible <= 0:
            return 0.0
        return self.votes_cast / self.total_eligible


@dataclass(frozen=True)
class MultiOptionSnapshotPoint:
    """One sample of an approval / ranked_choice winner set at a point in time.

    ``winners`` is the list of option_ids the tally would currently elect (sorted
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

def binary_snapshot_is_stable(
    snapshot: BinarySnapshotPoint,
    pass_threshold: float,
) -> bool:
    """True iff this snapshot has support >= pass_threshold.

    Zero-votes-cast snapshots return True (no destabilizing signal yet).
    Per spec D3 (binary stability test, strict per-snapshot).
    """
    if snapshot.votes_cast == 0:
        return True
    return snapshot.support_fraction >= pass_threshold


def winner_set_overlaps(
    snapshot: MultiOptionSnapshotPoint,
    previous_snapshot: MultiOptionSnapshotPoint,
) -> bool:
    """True iff the two snapshots' winner sets are compatible — i.e. one is a
    subset of the other. This captures the spec D4 worked examples cleanly:

      - ``{A}`` -> ``{A}`` -> True (no change)
      - ``{A}`` -> ``{A, B}`` -> True (A still in; ambiguity emerged)
      - ``{A, B}`` -> ``{A}`` -> True (resolution; A wins)
      - ``{A, B}`` -> ``{B}`` -> True (resolution; B wins)
      - ``{A}`` -> ``{B}`` -> False (winner swap; unstable)
      - ``{A, B}`` -> ``{B, C}`` -> False (A displaced; C new; unstable)
      - ``{A, B}`` -> ``{C}`` -> False (both A and B displaced; unstable)
      - ``{A, B, C}`` -> ``{C, D}`` -> False (A and B displaced; unstable)

    **Spec note (judgment call):** Spec D4 line 1 codifies the rule as
    ``frozenset(previous.winners) & frozenset(current.winners) != frozenset()``
    (non-empty intersection). The 8 worked examples below D4 — particularly
    ``{A,B} -> {B,C}`` and ``{A,B,C} -> {C,D}`` — would be STABLE under that
    rule (each pair has at least one common element) but the spec text labels
    them UNSTABLE.

    The two interpretations diverge on cases like ``{A,B} -> {B,C}``. The
    consistent reading of all 8 examples is **subset-or-superset**: the new
    winner set must either contain or be contained by the old. That captures
    the spec's intuition (winner additions, winner resolutions, no change ->
    stable; any displacement of a previous winner -> unstable) and matches
    every worked example. We implement subset-or-superset and document the
    judgment call here.

    The function name is preserved (``winner_set_overlaps``) per spec §B2 even
    though the semantics are slightly stricter than naive intersection.
    """
    prev = frozenset(previous_snapshot.winners)
    curr = frozenset(snapshot.winners)
    return prev.issubset(curr) or curr.issubset(prev)


def in_stable_result_window(
    now: datetime,
    voting_start: datetime,
    voting_end: datetime,
    fraction: float,
) -> bool:
    """True iff ``now`` falls inside the final ``fraction`` of the voting window.

    Boundary: at exactly ``start + (1-fraction)*duration`` the window opens;
    earlier instants return False, equal-or-later return True.

    ``fraction`` is required (no default per spec §B2; callers pass the org's
    ``stable_window_fraction``).
    """
    if voting_end <= voting_start:
        return False
    duration = (voting_end - voting_start).total_seconds()
    if duration <= 0:
        return False
    elapsed = (now - voting_start).total_seconds()
    return (elapsed / duration) >= (1.0 - fraction)


# ---------------------------------------------------------------------------
# Destabilization decisions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DestabilizationDecision:
    """Outcome of an in-window stability evaluation.

    ``destabilized = True`` means the worker should fire an extension (or, if
    the extension budget is exhausted, log the destabilization and let the
    proposal continue to its current voting_end).

    ``reason`` is an audit-friendly description of what destabilized.

    ``breach_sample`` is an opaque payload describing the breach. For binary
    it's a snapshot dict; for multi-option it's a previous/current winners
    pair. Used for audit-log detail payloads.
    """
    destabilized: bool
    reason: str = ""
    breach_sample: Any = None


def evaluate_original_window_stability(
    voting_method: str,
    snapshots: list,
    pass_threshold: float,
    voting_start: datetime,
    voting_end: datetime,
    now: datetime,
    stable_window_fraction: float,
) -> DestabilizationDecision:
    """Stability check during the original voting period (pre-extension).

    Per spec §B2 + D5 + D10:

      - Filter snapshots to those inside the stable window (final
        ``stable_window_fraction`` of the voting period).
      - If no snapshots in the stable window: not yet in window; return
        ``destabilized=False``.
      - Binary: if any in-window snapshot's
        ``binary_snapshot_is_stable(snap, pass_threshold)`` is False, return
        ``destabilized=True`` with that snapshot as ``breach_sample``.
      - Multi-option: walk the in-window snapshots in order. For each pair,
        compare to its predecessor (which may be the last out-of-window
        snapshot, per D10's first-snapshot baseline rule). If any pair fails
        ``winner_set_overlaps``, return ``destabilized=True``.
    """
    if not snapshots:
        return DestabilizationDecision(destabilized=False)

    # Compute the stable-window threshold: stable_window_starts_at.
    if voting_end <= voting_start:
        return DestabilizationDecision(destabilized=False)
    duration = voting_end - voting_start
    if duration.total_seconds() <= 0:
        return DestabilizationDecision(destabilized=False)
    stable_window_starts_at = voting_start + duration * (1.0 - stable_window_fraction)

    # Are we even in the stable window yet?
    if now < stable_window_starts_at:
        return DestabilizationDecision(destabilized=False)

    in_window = [s for s in snapshots if s.simulated_time >= stable_window_starts_at]
    if not in_window:
        # In-window time has been reached but no snapshot has been captured
        # in it yet. Nothing to evaluate.
        return DestabilizationDecision(destabilized=False)

    if voting_method == "binary":
        for snap in in_window:
            if not binary_snapshot_is_stable(snap, pass_threshold):
                return DestabilizationDecision(
                    destabilized=True,
                    reason=(
                        f"Binary support {snap.support_fraction:.3f} below "
                        f"pass_threshold {pass_threshold:.3f} at "
                        f"{snap.simulated_time.isoformat()} "
                        f"(within final {stable_window_fraction:.0%} of voting period)"
                    ),
                    breach_sample={
                        "simulated_time": snap.simulated_time.isoformat(),
                        "support_fraction": round(snap.support_fraction, 4),
                        "pass_threshold": pass_threshold,
                        "yes": snap.yes,
                        "no": snap.no,
                        "abstain": snap.abstain,
                        "total_eligible": snap.total_eligible,
                        "stable_window_fraction": stable_window_fraction,
                    },
                )
        return DestabilizationDecision(destabilized=False)

    # Multi-option: walk adjacent pairs. Per D10, the first in-window snapshot
    # has no previous-in-window — compare it to the last out-of-window snapshot
    # if one exists.
    out_of_window = [s for s in snapshots if s.simulated_time < stable_window_starts_at]
    last_out = out_of_window[-1] if out_of_window else None

    pairs: list[tuple[Any, Any]] = []  # (previous, current)
    if last_out is not None:
        pairs.append((last_out, in_window[0]))
    for i in range(1, len(in_window)):
        pairs.append((in_window[i - 1], in_window[i]))

    for prev, curr in pairs:
        if not winner_set_overlaps(curr, prev):
            return DestabilizationDecision(
                destabilized=True,
                reason=(
                    f"Multi-option winner set changed from "
                    f"{sorted(prev.winners)} to {sorted(curr.winners)} at "
                    f"{curr.simulated_time.isoformat()} "
                    f"(within final {stable_window_fraction:.0%} of voting period)"
                ),
                breach_sample={
                    "simulated_time": curr.simulated_time.isoformat(),
                    "previous_winners": sorted(prev.winners),
                    "current_winners": sorted(curr.winners),
                    "stable_window_fraction": stable_window_fraction,
                },
            )

    return DestabilizationDecision(destabilized=False)


def evaluate_extension_stability(
    voting_method: str,
    snapshots: list,
    pass_threshold: float,
    now: datetime,
    stable_window_duration: timedelta,
) -> bool:
    """Sliding-window stability check during an extension.

    Per spec §B2 + D8: returns True iff the proposal has demonstrated
    stability for the most recent ``stable_window_duration``. When True, the
    caller (worker) closes the proposal at this snapshot.

    Logic:

      - Filter snapshots to those with ``simulated_time >=
        (now - stable_window_duration)``.
      - If fewer than 2 snapshots in the lookback: return False
        (insufficient evidence; per D10 we need at least 2 to verify any
        stability claim).
      - For binary: every snapshot in the lookback must satisfy
        ``binary_snapshot_is_stable``. Any failure -> return False.
      - For multi-option: every adjacent pair in the lookback must have
        overlapping winners. Any disjoint pair -> return False.
      - Otherwise: return True (stability demonstrated).
    """
    if not snapshots:
        return False
    cutoff = now - stable_window_duration
    lookback = [s for s in snapshots if s.simulated_time >= cutoff]
    if len(lookback) < 2:
        return False

    if voting_method == "binary":
        for snap in lookback:
            if not binary_snapshot_is_stable(snap, pass_threshold):
                return False
        return True

    # Multi-option: every adjacent pair in lookback must overlap.
    for i in range(1, len(lookback)):
        if not winner_set_overlaps(lookback[i], lookback[i - 1]):
            return False
    return True
