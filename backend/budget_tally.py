"""budget_tally.py — Phase 73/74 budget-voting tallies (pure, no DB).

Phase 73 ships the **allocation** tally (Mode A: continuous buckets). Phase 74
will add ``tally_project()`` (Mode B: discrete ranked items) to this same
module — do not be surprised when a second tally lands here.

Everything in this module is a pure function over plain data: no SQLAlchemy,
no Session, no I/O. The route/service layer lifts ``Proposal.budget_config``
and the option cost columns into the simple containers below and calls in.

------------------------------------------------------------------------------
Allocation tally (Mode A) — why this is safe
------------------------------------------------------------------------------
*Median default = strategyproof.* A voter's honest allocation is their best
move: you cannot pull a bucket's median past where half the voters sit by
inflating your own number. (Raw mean is trivially gameable — max-your-favorite
/ zero-the-rest drags the average — so it is deliberately NOT offered.)

*Proportional normalization is legitimate here* (unlike Mode B): every bucket
is continuously divisible and *meant* to share the pool, so scaling the
per-bucket central tendencies to sum to the envelope is the goal, not an
override of an all-or-nothing choice.

*Everything with support gets a share.* There is no priority cutoff; a bucket
whose central tendency is > 0 receives a positive amount. (This is the explicit
Mode-A product requirement.)

Rounding rule: final amounts are whole currency units (an HOA reads a budget in
whole dollars, not fractional cents). We use **largest-remainder** rounding so
the rounded per-bucket amounts still sum to exactly the rounded allocated total.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


# Float wobble tolerance for the cap/reflow comparisons.
_EPS = 1e-9


@dataclass
class BucketSpec:
    """One continuously-fundable bucket. ``max_amount`` None => the bucket can
    absorb the whole envelope (ceiling = envelope)."""

    option_id: str
    max_amount: Optional[float] = None


@dataclass
class AllocationTally:
    """Result of an allocation-budget tally.

    Carries NO ``winners`` / ``tied`` fields — allocation has no winner set, so
    the dispatch must never route it to ``tie_resolution.py``.
    """

    amounts: dict = field(default_factory=dict)  # {option_id: int dollars}
    total_allocated: float = 0.0
    unallocated_remainder: float = 0.0
    degenerate_no_support: bool = False
    total_ballots_cast: int = 0
    total_eligible: int = 0
    not_cast: int = 0
    aggregation: str = "median"
    envelope: float = 0.0

    @property
    def votes_cast(self) -> int:
        return self.total_ballots_cast

    def quorum_met(self, threshold: float) -> bool:
        if self.total_eligible == 0:
            return False
        return self.total_ballots_cast / self.total_eligible >= threshold


# ---------------------------------------------------------------------------
# Central-tendency helpers
# ---------------------------------------------------------------------------

def _median(values: list[float]) -> float:
    """Standard median. Even count → mean of the two middle values."""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return float(s[mid])
    return (s[mid - 1] + s[mid]) / 2.0


def _trimmed_mean(values: list[float], trim_frac: float = 0.10) -> float:
    """Drop the top and bottom ``trim_frac`` of values *by count* (rounded
    half-up), then mean the rest.

    With < 5 voters the trim count rounds to 0, so this degrades to a plain
    mean of the bucket — acceptable because at < 5 voters strategyproofness is
    moot. If a (pathological) trim would remove everything, fall back to the
    plain mean so we never divide by zero.
    """
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    k = int(n * trim_frac + 0.5)  # round half-up: n=4→0, n=5→1, n=10→1
    if k * 2 >= n:
        return sum(s) / n
    trimmed = s[k: n - k]
    return sum(trimmed) / len(trimmed)


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------

def _largest_remainder_round(amounts: dict, target_total: int) -> dict:
    """Round each float amount to a whole dollar so the rounded values sum to
    exactly ``target_total``. Surplus dollars go to the largest fractional
    remainders first (deterministic tiebreak on option_id for audit
    stability)."""
    floors = {k: int(math.floor(v)) for k, v in amounts.items()}
    base = sum(floors.values())
    remainder = target_total - base
    result = dict(floors)
    if remainder <= 0 or not amounts:
        return result
    order = sorted(
        amounts.keys(),
        key=lambda k: (-(amounts[k] - math.floor(amounts[k])), k),
    )
    i = 0
    while remainder > 0 and order:
        result[order[i % len(order)]] += 1
        remainder -= 1
        i += 1
    return result


# ---------------------------------------------------------------------------
# Allocation tally (Mode A)
# ---------------------------------------------------------------------------

def tally_allocation(
    *,
    envelope: float,
    buckets: list[BucketSpec],
    ballots: list[dict],
    aggregation: str = "median",
    total_eligible: Optional[int] = None,
) -> AllocationTally:
    """Tally an allocation-budget proposal.

    ``ballots`` is one ``{option_id: amount}`` dict per cast voter (an omitted
    bucket is a $0 allocation for that voter and counts as 0 in the central
    tendency). ``buckets`` defines the bucket set + per-bucket ceilings.

    The output always sums to exactly ``envelope`` UNLESS the bucket ceilings
    collectively sum below the envelope, in which case the shortfall is
    reported in ``unallocated_remainder`` and no ceiling is exceeded.
    """
    bucket_ids = [b.option_id for b in buckets]
    caps = {
        b.option_id: (b.max_amount if b.max_amount is not None else envelope)
        for b in buckets
    }
    n_cast = len(ballots)
    if total_eligible is None:
        total_eligible = n_cast
    not_cast = max(0, total_eligible - n_cast)

    def _empty(degenerate: bool) -> AllocationTally:
        return AllocationTally(
            amounts={bid: 0 for bid in bucket_ids},
            total_allocated=0.0,
            unallocated_remainder=0.0,
            degenerate_no_support=degenerate,
            total_ballots_cast=n_cast,
            total_eligible=total_eligible,
            not_cast=not_cast,
            aggregation=aggregation,
            envelope=envelope,
        )

    if envelope <= 0 or not bucket_ids:
        return _empty(degenerate=True)

    # Step 1 — per-bucket central tendency, clamped to [0, cap].
    per_bucket: dict = {}
    for bid in bucket_ids:
        vals = [float(b.get(bid, 0) or 0) for b in ballots]
        if aggregation == "trimmed_mean":
            v = _trimmed_mean(vals)
        else:
            v = _median(vals)
        per_bucket[bid] = max(0.0, min(v, caps[bid]))

    raw_total = sum(per_bucket.values())

    # Step 2 — degenerate: nobody allocated anything anywhere.
    if raw_total <= _EPS:
        return _empty(degenerate=True)

    # Step 3 — scale to the envelope with cap-aware reflow. Each round
    # distributes the still-unallocated envelope across the not-yet-capped
    # buckets in proportion to their central tendency; any bucket that would
    # exceed its ceiling is pinned to the ceiling and the residual reflows to
    # the rest. Terminates when a round caps nobody (clean proportional split)
    # or every supported bucket is at its ceiling (ceilings < envelope).
    final = {bid: 0.0 for bid in bucket_ids}
    active = [bid for bid in bucket_ids if per_bucket[bid] > _EPS]
    allocated_to_capped = 0.0

    while active:
        wsum = sum(per_bucket[b] for b in active)
        remaining = envelope - allocated_to_capped
        if wsum <= _EPS or remaining <= _EPS:
            break
        scale = remaining / wsum
        newly_capped = [b for b in active if per_bucket[b] * scale > caps[b] + _EPS]
        if newly_capped:
            for b in newly_capped:
                final[b] = caps[b]
                allocated_to_capped += caps[b]
                active.remove(b)
            continue
        # No ceiling bit this round — clean proportional split, done.
        for b in active:
            final[b] = per_bucket[b] * scale
        break

    total_final = sum(final.values())

    # Step 4 — whole-dollar rounding via largest remainder, preserving the
    # allocated-total sum exactly.
    target_total = int(round(total_final))
    rounded = _largest_remainder_round(final, target_total)
    total_allocated = sum(rounded.values())
    unallocated_remainder = max(0, int(round(envelope)) - total_allocated)

    return AllocationTally(
        amounts=rounded,
        total_allocated=float(total_allocated),
        unallocated_remainder=float(unallocated_remainder),
        degenerate_no_support=False,
        total_ballots_cast=n_cast,
        total_eligible=total_eligible,
        not_cast=not_cast,
        aggregation=aggregation,
        envelope=envelope,
    )
