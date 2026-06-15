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


# ===========================================================================
# Project tally (Mode B) — Phase 74 Stage 74 (CORE: plain discrete items)
# ===========================================================================
#
# The knapsack-under-scarcity world: discrete all-or-nothing items, ranked by
# CUMULATIVE SPEND (not ordinal slot), funded in group-priority order, stopping
# at the group's chosen spend level. Structurally different from allocation
# (Mode A), which is why it's a separate method + tally.
#
# Core machinery (this stage):
#  1. Cumulative-spend ranking — a voter's priority for an item is the running
#     total of spend that precedes it in their list (dollars-already-committed-
#     when-this-item-is-reached), NOT its ordinal position.
#  2. Omission = ranked at the proposal `max_spend` — a strong "don't spend on
#     this" signal (strictly harsher than "after my own total").
#  3. Group priority = median of per-item cumulative positions (omitters
#     contributing max_spend), breadth-first tiebreak on ties.
#  4. Group desired-total = median of per-voter implied spends, clamped to
#     [min_spend, max_spend] — the stop point. This makes min_spend=0 usable
#     ("spend nothing if it's not worth it") without stopping after one item.
#  5. HARD-STOP walk (the genuine values choice — see test): when the highest-
#     priority not-yet-funded item doesn't fit, STOP the walk — do not skip it
#     to fund cheaper lower-priority items. Protects big-ticket high-priority
#     projects from being leapfrogged.
#
# NOT in core (Phase 74a/74b): mandatory-off-the-top, cost tiers, Mode C
# continuous-as-discrete. Those columns exist on the model but the core tally
# treats every item as a plain discrete item funded at its floor.


@dataclass
class ProjectItemSpec:
    """One discrete fundable item. ``floor_amount`` is its all-or-nothing cost
    (funded at this or $0). ``kind`` is carried for forward-compat but the core
    tally treats every item as plain discrete."""

    option_id: str
    floor_amount: float
    kind: str = "discrete"


@dataclass
class ProjectTally:
    """Result of a project-budget tally. No winners/tied fields — funds a SET,
    never routes to tie_resolution.py (priority ties break inside the tally)."""

    funded: list = field(default_factory=list)          # [{option_id, amount}]
    unfunded: list = field(default_factory=list)         # option_ids
    total_committed: float = 0.0
    stop_point: float = 0.0
    group_desired_total: float = 0.0
    halt_reason: str = "queue_exhausted"  # stop_point | item_did_not_fit | queue_exhausted
    group_positions: dict = field(default_factory=dict)  # {option_id: position}
    breadth: dict = field(default_factory=dict)          # {option_id: rank_count}
    priority_order: list = field(default_factory=list)   # option_ids, highest priority first
    total_ballots_cast: int = 0
    total_eligible: int = 0
    not_cast: int = 0
    envelope: float = 0.0

    @property
    def votes_cast(self) -> int:
        return self.total_ballots_cast

    def quorum_met(self, threshold: float) -> bool:
        if self.total_eligible == 0:
            return False
        return self.total_ballots_cast / self.total_eligible >= threshold


def tally_project(
    *,
    envelope: float,
    min_spend: float,
    max_spend: float,
    items: list[ProjectItemSpec],
    ballots: list[list[str]],   # each = ordered list of option_ids (highest priority first)
    total_eligible: Optional[int] = None,
) -> ProjectTally:
    """Tally a project-budget proposal (core: plain discrete items).

    ``ballots`` is one ordered ``[option_id, ...]`` list per cast voter (order
    IS the ranking; an omitted item is ranked at ``max_spend``).
    """
    item_ids = [it.option_id for it in items]
    cost = {it.option_id: float(it.floor_amount or 0) for it in items}
    n_cast = len(ballots)
    if total_eligible is None:
        total_eligible = n_cast
    not_cast = max(0, total_eligible - n_cast)

    # Step 1 — per-item group priority position + breadth.
    positions: dict = {}
    breadth: dict = {}
    for iid in item_ids:
        per_voter_pos: list[float] = []
        ranked_count = 0
        for ballot in ballots:
            if iid in ballot:
                ranked_count += 1
                idx = ballot.index(iid)
                # cumulative position = sum of costs of items BEFORE iid.
                per_voter_pos.append(sum(cost.get(o, 0) for o in ballot[:idx]))
            else:
                per_voter_pos.append(max_spend)  # omission = max_spend
        positions[iid] = _median(per_voter_pos) if per_voter_pos else max_spend
        breadth[iid] = ranked_count

    # Step 2 — total order: group position asc, breadth desc, option_id asc.
    order = sorted(item_ids, key=lambda i: (positions[i], -breadth[i], i))

    # Step 3 — group desired-total = median of per-voter implied spends.
    desired = [sum(cost.get(o, 0) for o in ballot) for ballot in ballots]
    group_desired = _median(desired) if desired else 0.0
    stop_point = max(min_spend, min(group_desired, max_spend))

    # Step 4 — the funding walk (HARD-STOP on the top unfunded item).
    funded: list = []
    committed = 0.0
    halt_reason = "queue_exhausted"
    for iid in order:
        if committed >= stop_point - _EPS:
            halt_reason = "stop_point"
            break
        c = cost[iid]
        if committed + c <= envelope + _EPS and committed + c <= max_spend + _EPS:
            funded.append({"option_id": iid, "amount": c})
            committed += c
        else:
            # Highest-priority not-yet-funded item doesn't fit → STOP (do not
            # skip past it to fund a cheaper lower-priority item).
            halt_reason = "item_did_not_fit"
            break

    funded_ids = {f["option_id"] for f in funded}
    unfunded = [i for i in item_ids if i not in funded_ids]

    return ProjectTally(
        funded=funded,
        unfunded=unfunded,
        total_committed=float(committed),
        stop_point=float(stop_point),
        group_desired_total=float(group_desired),
        halt_reason=halt_reason,
        group_positions=positions,
        breadth=breadth,
        priority_order=order,
        total_ballots_cast=n_cast,
        total_eligible=total_eligible,
        not_cast=not_cast,
        envelope=envelope,
    )
