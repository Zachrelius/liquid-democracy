"""Phase 17 - Org-configurable tie resolution.

Pure layer: method identifiers, eligibility tuples, platform defaults, and
the per-method resolver functions. The resolution dispatcher is invoked
from the route layer (``routes/proposals.py::advance_proposal`` and the
org-scoped equivalent in ``routes/organizations.py``) when a tally returns
``tally.tied=True`` AND ``len(tally.winners) > 1``. The resolver writes its
result to ``Proposal.tie_resolution`` JSON as a verifiable audit trail and
overwrites ``tally.winners`` with the resolved set so downstream consumers
(the results page, ``ProposalResults`` schema) see the post-resolution
winners.

Design notes
------------

- ``tally.tied`` stays ``True`` after resolution for transparency (D9):
  the results page surfaces "this proposal had a tie, resolved via X"
  alongside the resolved winner.
- ``random_seed`` derives an int seed from ``int(hex_digest, 16) %
  (2**32)`` before passing to ``random.Random()`` (per spec operational
  notes: the canonical reproducibility pattern; ``random.Random(<long
  hex string>)`` works but the mod-32 idiom is what's documented).
- ``broader_approval_base`` reads ``tally.ballots`` (a list of approval-
  set lists). That field is added to ``ApprovalTally`` in Phase 17 B3
  (Wave 2); this resolver is written assuming the field will be present.
- ``expand_winners`` always seats ALL tied options, even when
  ``num_winners=1`` (D11). This is documented in the help page so authors
  know to configure a different method if they need exactly one winner
  per seat.
- ``random_seed``'s seed input includes ``proposal.voting_end``. If
  ``voting_end`` is ``None`` at resolution time, a ``RuntimeError`` is
  raised: the route's ``next_status == "voting"`` branch sets
  ``voting_end``, so by the time we hit ``next_status == "passed"`` the
  field must be non-null. A null value here indicates a bug elsewhere.
"""
from __future__ import annotations

import hashlib
import logging
import random
from dataclasses import dataclass
from typing import Literal, Optional, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    import models
    from delegation_engine import ApprovalTally, RCVTally


_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Method identifiers, eligibility tuples, platform defaults
# ---------------------------------------------------------------------------

# Method identifier strings - used in settings JSON, audit records, and
# frontend dropdown values. Order here is alphabetical-ish for the canonical
# list; UI dropdown order is enforced by the eligibility tuples below.
TIE_RESOLUTION_METHODS = (
    "broader_approval_base",
    "expand_winners",
    "earliest_decisive_vote",
    "random_seed",
)

ApprovalMethod = Literal[
    "broader_approval_base", "expand_winners",
    "earliest_decisive_vote", "random_seed",
]
RankedChoiceMethod = Literal[
    "expand_winners", "earliest_decisive_vote", "random_seed",
]

# Platform defaults per voting method. Mirror D4:
#   - approval -> broader_approval_base (single winner, leverages approval
#     semantics).
#   - ranked_choice -> random_seed (single winner per seat, conservative).
#     NOT expand_winners: Z's stated concern: "may not be viable for some
#     decisions."
PLATFORM_DEFAULT_TIE_RESOLUTION_APPROVAL: ApprovalMethod = (
    "broader_approval_base"
)
PLATFORM_DEFAULT_TIE_RESOLUTION_RANKED_CHOICE: RankedChoiceMethod = (
    "random_seed"
)

# Eligible methods per voting method. Order matches D3 dropdown order
# (method-specific first, then earliest_decisive_vote, then random_seed
# last - deterministic option last in the dropdown).
ELIGIBLE_METHODS_APPROVAL = (
    "broader_approval_base",
    "expand_winners",
    "earliest_decisive_vote",
    "random_seed",
)
ELIGIBLE_METHODS_RANKED_CHOICE = (
    "expand_winners",
    "earliest_decisive_vote",
    "random_seed",
)


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class ResolutionResult:
    """Output of a tie-resolution run.

    Persisted by the route layer to ``Proposal.tie_resolution`` as a
    verifiable audit record:

        proposal.tie_resolution = {
            "method": result.method,
            "input_winners": result.input_winners,
            "chosen_winners": result.chosen_winners,
            "seed": result.seed,                  # null for non-random
            "metadata": result.metadata,          # null when absent
            "applied_at": <iso timestamp>,
        }
    """

    method: str                                   # which method fired
    input_winners: list[str]                      # the tied set as input
    chosen_winners: list[str]                     # post-resolution winner(s)
    seed: Optional[str] = None                    # only for random_seed
    metadata: Optional[dict] = None               # method-specific extras


# ---------------------------------------------------------------------------
# Public dispatcher
# ---------------------------------------------------------------------------

def resolve_tie(
    method: str,
    input_winners: list[str],
    proposal: "models.Proposal",
    tally: "Union[ApprovalTally, RCVTally]",
    db: "Session",
) -> ResolutionResult:
    """Dispatch on ``method``; return the resolution result.

    ``input_winners`` is the post-tally tied set (same as
    ``tally.winners`` when ``tally.tied=True``). ``proposal`` and
    ``tally`` are passed so individual methods can read what they need
    (e.g., ``earliest_decisive_vote`` walks vote rows;
    ``broader_approval_base`` reads the approval ballots from the tally).

    Raises ``ValueError`` if ``method`` is unknown.
    """
    if method == "random_seed":
        return _resolve_random_seed(input_winners, proposal)
    if method == "earliest_decisive_vote":
        return _resolve_earliest_decisive_vote(
            input_winners, proposal, tally, db,
        )
    if method == "broader_approval_base":
        return _resolve_broader_approval_base(input_winners, tally, proposal)
    if method == "expand_winners":
        return _resolve_expand_winners(input_winners)
    raise ValueError(
        f"Unknown tie-resolution method: {method!r}. Expected one of "
        f"{TIE_RESOLUTION_METHODS}."
    )


# ---------------------------------------------------------------------------
# Per-method resolvers
# ---------------------------------------------------------------------------

def _resolve_random_seed(
    input_winners: list[str],
    proposal: "models.Proposal",
) -> ResolutionResult:
    """Deterministic random selection seeded by (proposal.id, voting_end).

    The seed string is the hex sha256 of ``f"{proposal.id}:{voting_end}"``.
    Anyone can verify the result by recomputing the hash. Picks one option
    from ``sorted(input_winners)`` (sort ensures reproducibility regardless
    of dict-ordering variation upstream).

    Raises ``RuntimeError`` if ``proposal.voting_end is None`` - the
    route layer's ``next_status == "voting"`` branch sets ``voting_end``,
    so a null value at resolution time indicates a bug elsewhere.
    """
    if proposal.voting_end is None:
        raise RuntimeError(
            f"random_seed tie resolution requires proposal.voting_end "
            f"to be set; got None for proposal id={proposal.id}. The "
            f"route layer must populate voting_end before advancing to "
            f"the passed state. This indicates a bug in the advance "
            f"path."
        )
    seed_hex = hashlib.sha256(
        f"{proposal.id}:{proposal.voting_end.isoformat()}".encode()
    ).hexdigest()
    # Derive an int seed via mod-32 (canonical reproducibility pattern
    # per spec operational notes line 435).
    seed_int = int(seed_hex, 16) % (2 ** 32)
    rng = random.Random(seed_int)
    sorted_inputs = sorted(input_winners)
    picked = rng.choice(sorted_inputs)
    return ResolutionResult(
        method="random_seed",
        input_winners=list(input_winners),
        chosen_winners=[picked],
        seed=seed_hex,
        metadata=None,
    )


def _resolve_earliest_decisive_vote(
    input_winners: list[str],
    proposal: "models.Proposal",
    tally: "Union[ApprovalTally, RCVTally]",
    db: "Session",
) -> ResolutionResult:
    """The tied option whose support reached its tied-final count earliest wins.

    Walks the proposal's direct votes in cast_at order and tracks per-option
    running counts. For each tied option, records the cast_at of the vote
    that incremented it to its final count (the LAST vote that reached the
    final count, not the first - "decisive" = the one that crossed the
    threshold, accounting for any later-arriving votes that stayed at that
    count).

    Tiebreak (two tied options reach their final count at literally the
    same cast_at): falls back to ``_resolve_random_seed``.

    Metadata: ``{"decisive_timestamps": {oid: iso_str, ...}}``.
    """
    import models  # local import: avoid circular at module import time.

    # We need each tied option's final count. For ApprovalTally, that's
    # tally.option_approvals[oid]. For RCVTally, "final count" is fuzzier
    # (round-by-round elimination); we approximate by counting first-choice
    # appearances in direct ballots, which is the right semantic for
    # tie-at-elimination scenarios. The per-method specifics here matter
    # less than the deterministic ordering by cast_at.
    tied_set = set(input_winners)

    # Build per-option final counts from the approval-tally style accessor
    # if available, else fall back to counting from votes.
    final_counts: dict[str, int] = {}
    if hasattr(tally, "option_approvals") and getattr(tally, "option_approvals"):
        for oid in tied_set:
            final_counts[oid] = int(tally.option_approvals.get(oid, 0))
    else:
        # RCV path: count first-preference appearances among direct votes.
        # Conservative: this gives a deterministic tiebreak ordering that
        # mirrors "who got their final tied count earliest" semantically.
        rows = (
            db.query(models.Vote)
            .filter(
                models.Vote.proposal_id == proposal.id,
                models.Vote.is_direct == True,  # noqa: E712
            )
            .all()
        )
        for v in rows:
            ranking = getattr(v, "ranking", None) or []
            if ranking and ranking[0] in tied_set:
                final_counts[ranking[0]] = final_counts.get(ranking[0], 0) + 1
        for oid in tied_set:
            final_counts.setdefault(oid, 0)

    # Now walk votes in cast_at order, tracking running counts per tied
    # option; record the cast_at of the LAST vote that brought the running
    # count up to the option's final count.
    votes = (
        db.query(models.Vote)
        .filter(
            models.Vote.proposal_id == proposal.id,
            models.Vote.is_direct == True,  # noqa: E712
        )
        .order_by(models.Vote.cast_at.asc())
        .all()
    )

    running: dict[str, int] = {oid: 0 for oid in tied_set}
    decisive_at: dict[str, object] = {}  # oid -> datetime
    for v in votes:
        cast_at = v.cast_at
        # An approval vote bumps every approved option; an RCV vote bumps
        # its first-choice option (matching the final_counts logic above);
        # a binary vote bumps "yes"/"no" (not relevant here since binary
        # has no tie path).
        bumped: list[str] = []
        approvals = getattr(v, "approvals", None)
        ranking = getattr(v, "ranking", None)
        if approvals:
            bumped = [oid for oid in approvals if oid in tied_set]
        elif ranking:
            if ranking and ranking[0] in tied_set:
                bumped = [ranking[0]]
        for oid in bumped:
            running[oid] += 1
            if running[oid] == final_counts.get(oid, 0):
                # Last vote that brought us to the final count. Overwrite
                # is intentional: a later vote that stays at that count
                # implies the count was hit and stayed; a later vote that
                # exceeds and then is undone (vote retraction) wouldn't
                # show up in is_direct=True ballots anyway since
                # retracted votes are typically removed/replaced.
                decisive_at[oid] = cast_at

    # Pick the option with the earliest decisive timestamp. If two options
    # share the literal same cast_at, fall back to random_seed for a
    # deterministic tiebreak.
    if not decisive_at:
        # Pathological: no votes recorded for any tied option. Fall back
        # to random_seed deterministically.
        result = _resolve_random_seed(input_winners, proposal)
        return ResolutionResult(
            method="earliest_decisive_vote",
            input_winners=list(input_winners),
            chosen_winners=result.chosen_winners,
            seed=result.seed,
            metadata={"decisive_timestamps": {}, "fallback": "random_seed"},
        )

    # Sort tied options by their decisive cast_at (None = absent => infinity).
    # If multiple share the earliest timestamp, fall back to random_seed
    # among those tied-on-timestamp options.
    timestamps = [
        (oid, decisive_at.get(oid)) for oid in tied_set
        if decisive_at.get(oid) is not None
    ]
    if not timestamps:
        result = _resolve_random_seed(input_winners, proposal)
        return ResolutionResult(
            method="earliest_decisive_vote",
            input_winners=list(input_winners),
            chosen_winners=result.chosen_winners,
            seed=result.seed,
            metadata={"decisive_timestamps": {}, "fallback": "random_seed"},
        )

    timestamps.sort(key=lambda pair: pair[1])
    earliest_ts = timestamps[0][1]
    earliest_options = [oid for oid, ts in timestamps if ts == earliest_ts]

    metadata_ts = {
        oid: ts.isoformat() if ts is not None else None
        for oid, ts in decisive_at.items()
    }

    if len(earliest_options) > 1:
        # Random_seed tiebreak across the timestamp-tied subset.
        fallback = _resolve_random_seed(earliest_options, proposal)
        return ResolutionResult(
            method="earliest_decisive_vote",
            input_winners=list(input_winners),
            chosen_winners=fallback.chosen_winners,
            seed=fallback.seed,
            metadata={
                "decisive_timestamps": metadata_ts,
                "fallback": "random_seed",
                "fallback_input_winners": earliest_options,
            },
        )

    return ResolutionResult(
        method="earliest_decisive_vote",
        input_winners=list(input_winners),
        chosen_winners=[earliest_options[0]],
        seed=None,
        metadata={"decisive_timestamps": metadata_ts},
    )


def _resolve_broader_approval_base(
    input_winners: list[str],
    tally: "Union[ApprovalTally, RCVTally]",
    proposal: "models.Proposal",
) -> ResolutionResult:
    """Among tied options, the one co-approved with the most OTHER options wins.

    For each tied option, count how many other options it co-occurs with
    across all approval ballots (sum of "ballot has this option AND any
    other option"). The option with the highest co-approval breadth wins.

    Reads ``tally.ballots: list[list[str]]`` - each inner list is one
    voter's approval set. **Note: the ``ballots`` field is added to
    ``ApprovalTally`` in Phase 17 B3 (Wave 2). This resolver is written
    assuming the field will be present**; it falls back gracefully (random
    seed) if the field is absent or empty.

    Tiebreak: falls back to ``_resolve_random_seed``.

    Metadata: ``{"co_approval_counts": {oid: int, ...}}``.
    """
    ballots = getattr(tally, "ballots", None)
    tied_set = set(input_winners)

    if not ballots:
        # Defensive: ApprovalTally without populated ballots (pre-B3 or
        # an RCV tally that somehow ends up here). Fall back to
        # random_seed.
        result = _resolve_random_seed(input_winners, proposal)
        return ResolutionResult(
            method="broader_approval_base",
            input_winners=list(input_winners),
            chosen_winners=result.chosen_winners,
            seed=result.seed,
            metadata={"co_approval_counts": {}, "fallback": "random_seed"},
        )

    # Count co-approval breadth per tied option:
    #   for each ballot containing this option, count how many OTHER
    #   options on the same ballot. Sum across ballots.
    co_counts: dict[str, int] = {oid: 0 for oid in tied_set}
    for ballot in ballots:
        ballot_set = set(ballot or [])
        if not ballot_set:
            continue
        for oid in tied_set:
            if oid in ballot_set:
                # Number of OTHER options on this ballot.
                co_counts[oid] += len(ballot_set) - 1

    metadata = {"co_approval_counts": dict(co_counts)}

    # Find the option(s) with the highest co-approval count.
    max_count = max(co_counts.values())
    leaders = [oid for oid, c in co_counts.items() if c == max_count]

    if len(leaders) == 1:
        return ResolutionResult(
            method="broader_approval_base",
            input_winners=list(input_winners),
            chosen_winners=[leaders[0]],
            seed=None,
            metadata=metadata,
        )

    # Tiebreak across co-approval-tied leaders via random_seed.
    fallback = _resolve_random_seed(leaders, proposal)
    return ResolutionResult(
        method="broader_approval_base",
        input_winners=list(input_winners),
        chosen_winners=fallback.chosen_winners,
        seed=fallback.seed,
        metadata={
            **metadata,
            "fallback": "random_seed",
            "fallback_input_winners": leaders,
        },
    )


def _resolve_expand_winners(input_winners: list[str]) -> ResolutionResult:
    """All tied options become winners. No tiebreak needed.

    Per D11: this always seats all tied options regardless of the
    proposal's ``num_winners``. A ``num_winners=1`` IRV proposal that
    ties between 2 options with ``expand_winners`` configured returns
    2 winners. Help-page copy warns authors that this can produce
    multiple winners on single-seat proposals.
    """
    return ResolutionResult(
        method="expand_winners",
        input_winners=list(input_winners),
        chosen_winners=list(input_winners),
        seed=None,
        metadata=None,
    )
