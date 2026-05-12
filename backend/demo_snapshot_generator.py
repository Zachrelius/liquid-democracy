"""Phase 23 (B3, D6 updated 2026-05-12) — snapshot generator.

Helper module that takes a content-bible ``Trajectory`` and emits a list
of backdated ``VoteSnapshot`` ORM instances matching its waypoints. The
seed pipeline calls this once per proposal that's in / past voting at
reset moment.

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

import logging
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


def _fraction_voted_at(hour: float, duration_hours: float) -> float:
    """Heuristic for what fraction of total voters have voted by ``hour``.

    Simple linear-ramp model: 0% at hour 0, 100% at duration_hours. Used
    to reverse-engineer plausible per-snapshot counts from a support_pct.
    Real live voting has a more S-shaped curve; for chart-rendering
    purposes the linear approximation is sufficient.
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

    for i in range(n_snaps):
        # Spread snapshots evenly across the window (last snap == voting_end).
        if n_snaps == 1:
            t_frac = 1.0
        else:
            t_frac = i / (n_snaps - 1)
        simulated_time = voting_start + timedelta(
            seconds=t_frac * window_seconds,
        )
        hour = t_frac * duration

        support_pct = _interpolate_support(
            trajectory.waypoints, hour, duration,
        )
        fraction_voted = _fraction_voted_at(hour, duration)
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
