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
# Weighted central-tendency helpers (Phase 88b)
# ---------------------------------------------------------------------------
#
# Parity property (tested): with all weights equal to 1,
# ``_weighted_median(v, [1]*n) == _median(v)`` and the trimmed-mean helper's
# structure matches the unweighted path closely enough that the unweighted
# code path is preserved verbatim (weights=None routes to _median/_trimmed_mean,
# never through these helpers). A weighted median cannot be pulled past where
# half the total weight sits, so honest allocation stays strategyproof.

def _weighted_median(values: list[float], weights: list[float]) -> float:
    """Weighted median. Walk cumulative weight over value-sorted pairs and
    return the first value where cumulative weight passes half the total; if a
    prefix lands exactly on W/2, return the mean of that value and the next
    distinct value (mirrors ``_median``'s even-count midpoint). Zero-weight
    entries are skipped; all-zero (or empty) → 0.0.
    """
    pairs = [(float(v), float(w)) for v, w in zip(values, weights) if w > 0]
    if not pairs:
        return 0.0
    pairs.sort(key=lambda p: p[0])
    total = sum(w for _v, w in pairs)
    half = total / 2.0
    cum = 0.0
    for i, (v, w) in enumerate(pairs):
        cum += w
        if abs(cum - half) <= _EPS:
            # Exactly half at this boundary → midpoint with the immediate next
            # entry, mirroring _median's even-count mean of the two middle
            # values (equal-value neighbors collapse to v, so this matches
            # _median byte-for-byte at equal weights, including duplicates).
            if i + 1 < len(pairs):
                return (v + pairs[i + 1][0]) / 2.0
            return v
        if cum > half:
            return v
    return pairs[-1][0]


def _weighted_trimmed_mean(
    values: list[float], weights: list[float], trim_frac: float = 0.10,
) -> float:
    """Weighted trimmed mean: trim ``trim_frac`` of the TOTAL weight from each
    tail (discounting the boundary entry fractionally — an entry straddling the
    trim line keeps its residual weight), then take the weighted mean of what
    remains. If trimming would remove everything, fall back to the plain
    weighted mean. Zero-weight entries skipped; empty → 0.0.

    Intentionally does not reproduce ``_trimmed_mean``'s count-based
    round-half-up behavior at equal weights — parity for unweighted orgs is
    structural (weights=None never routes here), not numerical.
    """
    pairs = [(float(v), float(w)) for v, w in zip(values, weights) if w > 0]
    if not pairs:
        return 0.0
    pairs.sort(key=lambda p: p[0])
    total = sum(w for _v, w in pairs)
    trim = trim_frac * total

    def _mean(seq):
        wsum = sum(w for _v, w in seq)
        if wsum <= _EPS:
            return 0.0
        return sum(v * w for v, w in seq) / wsum

    if trim * 2 >= total - _EPS:
        return _mean(pairs)

    def _drop_front(seq, amount):
        # Remove ``amount`` weight from the front, keeping the fractional
        # residual of the straddling entry.
        out = []
        removed = 0.0
        for v, w in seq:
            if removed >= amount - _EPS:
                out.append((v, w))
            elif removed + w <= amount + _EPS:
                removed += w  # fully trimmed
            else:
                out.append((v, removed + w - amount))  # residual kept
                removed = amount
        return out

    low = _drop_front(pairs, trim)
    high = _drop_front(list(reversed(low)), trim)
    remaining = list(reversed(high))
    if not remaining:
        return _mean(pairs)
    return _mean(remaining)


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
    weights: Optional[list] = None,
) -> AllocationTally:
    """Tally an allocation-budget proposal.

    ``ballots`` is one ``{option_id: amount}`` dict per cast voter (an omitted
    bucket is a $0 allocation for that voter and counts as 0 in the central
    tendency). ``buckets`` defines the bucket set + per-bucket ceilings.

    Phase 88b — ``weights`` is an optional list parallel to ``ballots`` (one
    weight per cast voter, same order). ``None`` ⇒ the existing code path runs
    byte-for-byte (this is the parity mechanism; unweighted calls are never
    routed through the weighted helpers). When provided, per-bucket central
    tendency uses the weighted median / weighted trimmed mean, and the
    counters are weight-denominated (``total_ballots_cast = sum(weights)``,
    ``total_eligible`` is passed as TOTAL ELIGIBLE WEIGHT by the caller). Steps
    2-4 (degenerate check, cap-aware reflow, largest-remainder rounding) are
    count-free and unchanged.

    The output always sums to exactly ``envelope`` UNLESS the bucket ceilings
    collectively sum below the envelope, in which case the shortfall is
    reported in ``unallocated_remainder`` and no ceiling is exceeded.
    """
    bucket_ids = [b.option_id for b in buckets]
    caps = {
        b.option_id: (b.max_amount if b.max_amount is not None else envelope)
        for b in buckets
    }
    weighted = weights is not None
    # total_ballots_cast: headcount in the legacy path, summed weight when
    # weighted. Integer weights keep this an int.
    cast_count = sum(weights) if weighted else len(ballots)
    if total_eligible is None:
        total_eligible = cast_count
    not_cast = max(0, total_eligible - cast_count)

    def _empty(degenerate: bool) -> AllocationTally:
        return AllocationTally(
            amounts={bid: 0 for bid in bucket_ids},
            total_allocated=0.0,
            unallocated_remainder=0.0,
            degenerate_no_support=degenerate,
            total_ballots_cast=cast_count,
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
        if weighted:
            if aggregation == "trimmed_mean":
                v = _weighted_trimmed_mean(vals, weights)
            else:
                v = _weighted_median(vals, weights)
        elif aggregation == "trimmed_mean":
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
        total_ballots_cast=cast_count,
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
class TierSpec:
    """Phase 74b — one mutually-exclusive variant of a tier-parent item
    (e.g. "6ft pool $300k"). ``cost`` is what funding this tier spends."""

    tier_id: str
    cost: float


@dataclass
class ProjectItemSpec:
    """One fundable item.

    - Plain discrete / Mode C continuous-as-discrete: ``floor_amount`` is its
      all-or-nothing cost (funded at this or $0); ``tiers`` empty.
    - Tier parent (``kind == "tier_parent"``, Phase 74b): carries no cost of its
      own; ``tiers`` lists its variants and ``tier_allow_fallback`` controls
      whether the walk steps down to a cheaper affordable tier when the
      group-preferred one doesn't fit.
    """

    option_id: str
    floor_amount: float = 0.0
    kind: str = "discrete"
    tiers: list = field(default_factory=list)        # list[TierSpec] (tier parents)
    tier_allow_fallback: bool = True


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


def _normalize_ballot_entry(entry):
    """Phase 74b — accept a ballot entry as a bare option_id str (non-tiered),
    a ``(option_id, tier_id)`` tuple/list, or a ``{option_id, tier_id}`` dict.
    Returns ``(option_id, tier_id_or_None)``. Keeps the core's bare-string
    ballots working unchanged (backward-compat)."""
    if isinstance(entry, str):
        return (entry, None)
    if isinstance(entry, dict):
        return (entry.get("option_id"), entry.get("tier_id"))
    # tuple / list
    if len(entry) >= 2:
        return (entry[0], entry[1])
    return (entry[0], None)


def tally_project(
    *,
    envelope: float,
    min_spend: float,
    max_spend: float,
    items: list[ProjectItemSpec],
    ballots: list,   # per voter: ordered list of option_id str | (option_id, tier_id) | {option_id, tier_id}
    total_eligible: Optional[int] = None,
    weights: Optional[list] = None,
) -> ProjectTally:
    """Tally a project-budget proposal (discrete + Mode C + cost tiers).

    ``ballots`` is one ordered list per cast voter, highest priority first.
    Each entry is a bare option_id (non-tiered item) or carries a ``tier_id``
    naming the voter's chosen variant of a tier-parent item. An omitted item is
    ranked at ``max_spend``.

    Phase 88b — ``weights`` is an optional list parallel to ``ballots``.
    ``None`` ⇒ the existing code path runs byte-for-byte (parity mechanism).
    When provided: group positions + desired-total use the weighted median,
    breadth becomes the summed weight of voters who ranked an item, tier
    plurality counts voter weight, and counters are weight-denominated. The
    sort key and the funding walk (cost arithmetic only) are unchanged.

    Tiers (Phase 74b): a tier parent carries no cost itself; the voter's
    "chosen cost" for it is the cost of the tier they selected. When the walk
    reaches a tier parent it funds the GROUP-PREFERRED tier (plurality among
    voters who ranked it; tiebreak lower cost then id), stepping down to the
    most-preferred affordable tier if the preferred one doesn't fit and
    ``tier_allow_fallback`` is True — else the item doesn't fit and the walk
    hard-stops. At most one tier per parent is ever funded.
    """
    item_ids = [it.option_id for it in items]
    is_parent: dict = {}
    fixed_cost: dict = {}
    tier_cost: dict = {}        # parent_id -> {tier_id: cost}
    allow_fallback: dict = {}
    for it in items:
        if it.kind == "tier_parent":
            is_parent[it.option_id] = True
            tier_cost[it.option_id] = {
                ts.tier_id: float(ts.cost or 0) for ts in (it.tiers or [])
            }
            allow_fallback[it.option_id] = bool(it.tier_allow_fallback)
        else:
            is_parent[it.option_id] = False
            fixed_cost[it.option_id] = float(it.floor_amount or 0)

    # Normalize ballots once → list of (ordered_ids, tier_selection_map).
    voters: list = []
    for ballot in ballots:
        norm = [_normalize_ballot_entry(e) for e in ballot]
        ordered = [oid for oid, _ in norm]
        tmap = {oid: tid for oid, tid in norm if tid is not None}
        voters.append((ordered, tmap))
    n_cast = len(voters)
    # Phase 88b — parallel per-voter weights (default 1 each in the unweighted
    # path so the weighted branches below reduce to the legacy behavior when a
    # test passes weights=[1]*n; the None path skips them entirely).
    weighted = weights is not None
    voter_weights = [float(w) for w in weights] if weighted else [1.0] * n_cast
    cast_count = sum(weights) if weighted else n_cast
    if total_eligible is None:
        total_eligible = cast_count
    not_cast = max(0, total_eligible - cast_count)

    def chosen_cost(iid: str, tmap: dict) -> float:
        """A voter's all-or-nothing cost for one item — for a tier parent, the
        cost of the tier THIS voter selected (defensively the cheapest tier if
        they ranked it without a valid selection)."""
        if is_parent.get(iid):
            tcosts = tier_cost.get(iid, {})
            tid = tmap.get(iid)
            if tid is not None and tid in tcosts:
                return tcosts[tid]
            return min(tcosts.values()) if tcosts else 0.0
        return fixed_cost.get(iid, 0.0)

    # Step 1 — per-item group priority position + breadth. Phase 88b: position
    # is the weighted median over per-voter cumulative positions (omitters at
    # max_spend, at their weight), and breadth is the summed weight of the
    # voters who ranked the item.
    positions: dict = {}
    breadth: dict = {}
    for iid in item_ids:
        per_voter_pos: list[float] = []
        ranked_count = 0
        ranked_weight = 0.0
        for (ordered, tmap), vw in zip(voters, voter_weights):
            if iid in ordered:
                ranked_count += 1
                ranked_weight += vw
                idx = ordered.index(iid)
                # cumulative position = sum of THIS voter's chosen costs of the
                # items before iid (tier parents contribute their chosen tier).
                per_voter_pos.append(sum(chosen_cost(o, tmap) for o in ordered[:idx]))
            else:
                per_voter_pos.append(max_spend)  # omission = max_spend
        if not per_voter_pos:
            positions[iid] = max_spend
        elif weighted:
            positions[iid] = _weighted_median(per_voter_pos, voter_weights)
        else:
            positions[iid] = _median(per_voter_pos)
        # Unweighted path keeps the int headcount breadth (byte-for-byte);
        # weighted path uses the summed voter weight.
        breadth[iid] = ranked_weight if weighted else ranked_count

    # Step 2 — total order: group position asc, breadth desc, option_id asc.
    order = sorted(item_ids, key=lambda i: (positions[i], -breadth[i], i))

    # Step 3 — group desired-total = (weighted) median of per-voter implied spends.
    desired = [sum(chosen_cost(o, tmap) for o in ordered) for ordered, tmap in voters]
    if not desired:
        group_desired = 0.0
    elif weighted:
        group_desired = _weighted_median(desired, voter_weights)
    else:
        group_desired = _median(desired)
    stop_point = max(min_spend, min(group_desired, max_spend))

    # Step 4 — the funding walk (HARD-STOP on the top unfunded item).
    cap = min(envelope, max_spend)
    funded: list = []
    committed = 0.0
    halt_reason = "queue_exhausted"
    for iid in order:
        if committed >= stop_point - _EPS:
            halt_reason = "stop_point"
            break
        if is_parent.get(iid):
            tcosts = tier_cost.get(iid, {})
            # Group-preferred order: plurality among voters who ranked the
            # parent; tiebreak lower cost, then deterministic id. Phase 88b:
            # plurality counts voter weight (each voter contributes their
            # shares, not a flat 1).
            counts: dict = {}
            for (ordered, tmap), vw in zip(voters, voter_weights):
                if iid in ordered:
                    tid = tmap.get(iid)
                    if tid is not None and tid in tcosts:
                        counts[tid] = counts.get(tid, 0) + vw
            pref_order = sorted(
                tcosts.keys(), key=lambda t: (-counts.get(t, 0), tcosts[t], t)
            )
            candidates = pref_order if allow_fallback.get(iid, True) else pref_order[:1]
            chosen = next(
                (t for t in candidates if committed + tcosts[t] <= cap + _EPS), None
            )
            if chosen is not None:
                funded.append({"option_id": iid, "tier_id": chosen, "amount": tcosts[chosen]})
                committed += tcosts[chosen]
            else:
                halt_reason = "item_did_not_fit"
                break
        else:
            c = fixed_cost.get(iid, 0.0)
            if committed + c <= envelope + _EPS and committed + c <= max_spend + _EPS:
                funded.append({"option_id": iid, "tier_id": None, "amount": c})
                committed += c
            else:
                # Highest-priority not-yet-funded item doesn't fit → STOP (do
                # not skip past it to fund a cheaper lower-priority item).
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
