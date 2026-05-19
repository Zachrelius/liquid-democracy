"""Phase 23 (B3, D6 updated 2026-05-12) — snapshot generator.

Helper module that takes a content-bible ``Trajectory`` and emits a list
of backdated ``VoteSnapshot`` ORM instances matching its waypoints. The
seed pipeline calls this once per proposal that's in / past voting at
reset moment.

Phase 31 B1: ``seed_until`` parameter clamps snapshot emission to
[voting_start, seed_until]. For currently-voting proposals, callers pass
``seed_until=reset_moment`` so the seed pipeline doesn't pre-populate
the future portion of the voting window — the live worker takes over
from there. Without this clamp, the chart drew a sharp boundary spike at
the reset-moment x-position because the live worker's first post-reset
snapshot counted ALL stored filler votes (including those whose
``cast_at`` was uniformly distributed across the full window — and thus
many in the future) while adjacent seed snapshots only reflected the
elapsed-fraction tally.

Phase 31 B5: ``_lumpy_fraction_voted_at`` replaces the prior linear
``_fraction_voted_at`` with a segmented + per-proposal-seeded cumulative
curve (~30% / ~30% / ~40% across the three quarters of the voting
window), producing realistic organization-voting shape rather than a
perfect ramp.

D6 (UPDATED 2026-05-12) shape consumed:

    Trajectory:
        proposal_id: str
        voting_method: 'binary' | 'approval' | 'rcv' | 'stv'
        duration_hours: float
        waypoints: list[Waypoint(hour, support_pct)]
        final_result: str
        events: list[TrajectoryEvent]

Emitted ``VoteSnapshot`` fields:
    - ``simulated_time``  = backdated per the seeded voting window
    - ``recorded_at``     = now (seed time), per spec
    - Binary: ``yes_count`` / ``no_count`` / ``abstain_count`` / ``total_eligible``
    - Multi-option: ``multi_option_winners`` JSON with Phase 22 shape:
      ``{"winners": [...], "total_ballots_cast": int, "option_totals": {oid: int}}``

Cadence default = 1800s (30 min) per Z's decree. With ~72h voting
windows this produces ~144 snapshots/proposal × ~30 proposals × 3 orgs
≈ 13k rows — well within PG insert capacity using ``bulk_save_objects``.
"""
from __future__ import annotations

import hashlib
import logging
import random
from datetime import datetime, timedelta
from typing import Callable, Optional

from demo_content.schema import Trajectory, Waypoint

log = logging.getLogger(__name__)


# =============================================================================
# Waypoint interpolation
# =============================================================================


def _interpolate_support(
    waypoints: list[Waypoint],
    hour: float,
    duration_hours: float,
) -> float:
    """Linear-interpolate ``support_pct`` at ``hour`` along the waypoint list.

    Out-of-range hours clamp to the nearest endpoint. Empty waypoints
    return 0.0.
    """
    if not waypoints:
        return 0.0
    ordered = sorted(waypoints, key=lambda w: w.hour)
    if hour <= ordered[0].hour:
        return float(ordered[0].support_pct)
    if hour >= ordered[-1].hour:
        return float(ordered[-1].support_pct)
    # Find bracketing pair.
    for i in range(len(ordered) - 1):
        lo, hi = ordered[i], ordered[i + 1]
        if lo.hour <= hour <= hi.hour:
            span = hi.hour - lo.hour
            if span <= 0:
                return float(lo.support_pct)
            t = (hour - lo.hour) / span
            return float(lo.support_pct + t * (hi.support_pct - lo.support_pct))
    # Shouldn't reach here; safety fallback.
    return float(ordered[-1].support_pct)


def _lumpy_fraction_voted_at(
    hour: float,
    duration_hours: float,
    proposal_id: str,
) -> float:
    """Phase 31 B5: cumulative-vote fraction at ``hour`` with realistic shape.

    Three-segment monotone curve, per-proposal-seeded slope variability
    within each segment to produce organic lumpiness:

    - First 25% of voting period: ~30% of total votes (launch burst)
    - Middle 50% of voting period: ~30% of total votes (sparse middle)
    - Final 25% of voting period: ~40% of total votes (deadline surge)

    Each segment is split into 3-4 piecewise-linear sub-segments whose
    slopes are sampled deterministically from the proposal_id seed; the
    cumulative curve stays monotone but no longer looks like a ramp.
    Segment proportions also carry ±5% jitter per proposal.
    """
    if duration_hours <= 0:
        return 1.0
    if hour <= 0:
        return 0.0
    elapsed = max(0.0, min(1.0, hour / duration_hours))

    seed_int = int.from_bytes(
        hashlib.sha256(f"lumpy:{proposal_id}".encode("utf-8")).digest()[:8],
        "big",
    )
    rng = random.Random(seed_int)

    # Segment proportions — target 30/30/40 with ±5pt jitter, summing to 1.0.
    burst = rng.uniform(0.25, 0.35)
    middle = rng.uniform(0.25, 0.35)
    surge = 1.0 - burst - middle

    def _sub_segment_curve(x: float, n_sub: int, sub_rng: random.Random) -> float:
        """Map ``x`` ∈ [0, 1] through ``n_sub`` piecewise-linear sub-segments
        with random positive slopes summing to 1.0. Monotone non-decreasing.
        """
        # Sample n_sub weights ∈ [0.4, 1.6]; normalize.
        weights = [sub_rng.uniform(0.4, 1.6) for _ in range(n_sub)]
        total = sum(weights) or 1.0
        weights = [w / total for w in weights]
        seg_size = 1.0 / n_sub
        cumul = 0.0
        for i, w in enumerate(weights):
            seg_end = (i + 1) * seg_size
            if x <= seg_end:
                seg_start = i * seg_size
                seg_progress = (x - seg_start) / seg_size if seg_size > 0 else 0.0
                return cumul + w * seg_progress
            cumul += w
        return cumul

    if elapsed <= 0.25:
        sub_rng = random.Random(seed_int ^ 0xA1)
        sub_x = elapsed / 0.25
        return burst * _sub_segment_curve(sub_x, 3, sub_rng)
    elif elapsed <= 0.75:
        sub_rng = random.Random(seed_int ^ 0xB2)
        sub_x = (elapsed - 0.25) / 0.50
        return burst + middle * _sub_segment_curve(sub_x, 4, sub_rng)
    else:
        sub_rng = random.Random(seed_int ^ 0xC3)
        sub_x = (elapsed - 0.75) / 0.25
        return burst + middle + surge * _sub_segment_curve(sub_x, 3, sub_rng)


def _fraction_voted_at(hour: float, duration_hours: float) -> float:
    """Phase 23 linear ramp — kept for callers that don't have proposal_id.

    Phase 31 B5: prefer ``_lumpy_fraction_voted_at`` when proposal_id is
    available. This linear version remains as a safety fallback.
    """
    if duration_hours <= 0:
        return 1.0
    return max(0.0, min(1.0, hour / duration_hours))


# =============================================================================
# Generator
# =============================================================================


def generate_snapshots(
    proposal,
    trajectory: Trajectory,
    voting_start: datetime,
    voting_end: datetime,
    *,
    cadence_seconds: int = 1800,
    total_eligible: int = 60,
    option_id_resolver: Optional[Callable[[str], str]] = None,
    seed_until: Optional[datetime] = None,
) -> list:
    """Emit ``VoteSnapshot`` ORM instances per the trajectory.

    Parameters
    ----------
    proposal : ORM Proposal instance
        Used for ``proposal.id``. Must be flushed (have an ID) before
        snapshots reference it.
    trajectory : Trajectory
        From ``trajectory_waypoints.py``. ``trajectory.waypoints`` and
        ``trajectory.duration_hours`` drive the per-snapshot values.
    voting_start, voting_end : datetime
        Backdated values used to compute each snapshot's ``simulated_time``.
    cadence_seconds : int
        Spacing between snapshots; default 1800 (30 min) per D6 update.
    total_eligible : int
        Roster size for the org; used in reverse-engineering counts.
        Caller passes the actual org member count.
    option_id_resolver : callable | None
        Function ``(option_label: str) -> option_id`` for approval/RCV/STV
        proposals. When None, multi-option snapshots use labels directly
        as option IDs (acceptable for seed-only data).
    seed_until : datetime | None
        Phase 31 B1: when set, skip snapshots whose ``simulated_time`` is
        strictly greater than ``seed_until``. Callers should pass
        ``seed_until=reset_moment`` for currently-voting proposals so the
        live worker — not the seed — populates the post-reset region of
        the chart. Without this, the live worker's first post-reset
        snapshot (which counts ALL stored votes regardless of
        ``cast_at``) collides with the seed's already-emitted future
        snapshots and draws a vertical boundary spike.

    Returns
    -------
    list[models.VoteSnapshot]
        Ready for ``db.bulk_save_objects(...)`` per Amendment B.
    """
    import models  # local to avoid circular import at module load

    if voting_end <= voting_start:
        log.warning(
            "generate_snapshots: empty voting window for proposal=%s; skipping",
            getattr(proposal, "id", "?"),
        )
        return []

    duration = trajectory.duration_hours or (
        (voting_end - voting_start).total_seconds() / 3600.0
    )

    window_seconds = (voting_end - voting_start).total_seconds()
    n_snaps = max(2, int(window_seconds // cadence_seconds) + 1)

    method = trajectory.voting_method
    snapshots: list = []

    # Pre-compute final result counts for multi-option proposals so each
    # snapshot can interpolate toward them.
    final_winners: list[str] = []
    final_option_totals: dict[str, int] = {}
    if method != "binary":
        # Per spec D6: pragmatic fallback when per-method shape is ambiguous.
        # Derive final_winners from proposal.options (first num_winners), and
        # spread option_totals proportionally based on display_order.
        opts = list(getattr(proposal, "options", []) or [])
        num_winners = getattr(proposal, "num_winners", 1) or 1
        if opts:
            # Sort by display_order so winners are stable.
            sorted_opts = sorted(
                opts, key=lambda o: getattr(o, "display_order", 0),
            )
            final_winners = [o.id for o in sorted_opts[:num_winners]]
            # Approximate final tally: heavier weight on earlier options.
            n_opts = len(sorted_opts)
            for idx, opt in enumerate(sorted_opts):
                # Weight decays linearly; first option gets ~highest support.
                weight = max(1, n_opts - idx)
                final_option_totals[opt.id] = int(
                    round(total_eligible * 0.6 * weight / sum(range(1, n_opts + 1)))
                )

    proposal_id_for_seed = str(getattr(proposal, "id", "") or "")

    for i in range(n_snaps):
        # Spread snapshots evenly across the window (last snap == voting_end).
        if n_snaps == 1:
            t_frac = 1.0
        else:
            t_frac = i / (n_snaps - 1)
        simulated_time = voting_start + timedelta(
            seconds=t_frac * window_seconds,
        )
        # Phase 31 B1: clamp to elapsed portion for currently-voting proposals.
        if seed_until is not None and simulated_time > seed_until:
            break
        hour = t_frac * duration

        support_pct = _interpolate_support(
            trajectory.waypoints, hour, duration,
        )
        # Phase 31 B5: lumpy cumulative-vote curve replaces linear ramp.
        fraction_voted = _lumpy_fraction_voted_at(
            hour, duration, proposal_id_for_seed,
        )
        ballots_so_far = max(0, int(round(fraction_voted * total_eligible)))

        if method == "binary":
            yes_count = int(round((support_pct / 100.0) * ballots_so_far))
            no_count = max(0, ballots_so_far - yes_count)
            abstain_count = 0
            not_cast = max(0, total_eligible - ballots_so_far)
            snapshots.append(models.VoteSnapshot(
                proposal_id=proposal.id,
                simulated_time=simulated_time,
                yes_count=yes_count,
                no_count=no_count,
                abstain_count=abstain_count,
                not_cast_count=not_cast,
                total_eligible=total_eligible,
                multi_option_winners=None,
            ))
        else:
            # Multi-option: scale final_option_totals by fraction_voted so
            # the chart's per-option lines ramp up over the voting window.
            scaled_totals = {
                oid: int(round(count * fraction_voted))
                for oid, count in final_option_totals.items()
            }
            snapshots.append(models.VoteSnapshot(
                proposal_id=proposal.id,
                simulated_time=simulated_time,
                yes_count=0,
                no_count=0,
                abstain_count=0,
                not_cast_count=max(0, total_eligible - ballots_so_far),
                total_eligible=total_eligible,
                multi_option_winners={
                    "winners": list(final_winners),
                    "total_ballots_cast": ballots_so_far,
                    "option_totals": scaled_totals,
                },
            ))
    return snapshots


__all__ = ["generate_snapshots"]
