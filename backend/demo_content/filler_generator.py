"""Phase 23 (Amendment C, B9) — filler-member generator.

Bibles define ~6-8 named characters per org (quick-login + supporting).
For realistic vote splits + populated member lists, the seed mechanism
generates ~50-60 deterministic filler members per org. PRNG is seeded
by ``org_slug`` so the same neighborhood appears across resets.

Filler outputs are dataclass instances (``FillerMember``) the seed
pipeline persists as ``User`` + ``OrgMembership`` rows. Filler vote
allocations are produced by ``allocate_filler_votes`` per proposal —
ORM ``Vote`` instances ready for ``db.bulk_save_objects``.

The allocation logic is intentionally pragmatic:
- For binary proposals, parse trajectory.final_result like "58-42 passed"
  and allocate yes/no fillers to hit (yes_pct, no_pct) of ~60 voters.
- For approval / RCV / STV proposals, fall back to a sensible default
  (every filler approves one option weighted by trajectory leader) since
  the per-method analytic shape varies and the trajectory fields are
  not strictly machine-parseable per the Stage 8 §7 note.

Named-character votes are subtracted from the target so fillers don't
double-count. Timestamps spread across the voting window so the
trajectory chart shows realistic vote accumulation.
"""
from __future__ import annotations

import hashlib
import logging
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from .name_pool import NAME_POOL
from .schema import OrgBible, Proposal as BibleProposal, Trajectory

log = logging.getLogger(__name__)


# =============================================================================
# Dataclass
# =============================================================================


@dataclass
class FillerMember:
    """One filler member's identity + optional delegation target.

    The seed pipeline converts these into ``User`` + ``OrgMembership``
    rows (+ a ``Delegation`` row if ``delegates_to`` is non-None).
    """
    user_id: str            # f"filler_{org_slug}_{index:03d}"
    display_name: str
    username: str
    delegates_to: Optional[tuple[str, str]] = None  # (delegate_user_id, topic_name)


# =============================================================================
# Deterministic PRNG
# =============================================================================


def _seeded_rng(org_slug: str, member_index: int = 0) -> random.Random:
    """Deterministic PRNG per (org_slug, member_index).

    SHA256-based seed so output is stable across Python versions. We seed
    a fresh ``random.Random`` per call rather than the module-level
    global to avoid state pollution.
    """
    h = hashlib.sha256(f"{org_slug}:{member_index}".encode("utf-8")).digest()
    seed_int = int.from_bytes(h[:8], "big")
    return random.Random(seed_int)


# =============================================================================
# Filler member generation
# =============================================================================


def generate_filler_members(
    org_bible: OrgBible,
    *,
    target_count: int = 55,
    delegate_pool: Optional[list[tuple[str, str]]] = None,
) -> list[FillerMember]:
    """Generate ~target_count deterministic filler members for this org.

    Parameters
    ----------
    org_bible : OrgBible
        Drives the deterministic seed via ``org_bible.slug``.
    target_count : int
        Number of fillers to generate (default 55).
    delegate_pool : list[tuple[str, str]] | None
        ``[(delegate_user_id, topic_name), ...]`` of delegates accepting
        new delegations. Roughly 30% of fillers are wired up to delegate
        to a random member of this pool. None / empty list → no
        delegation assignments.

    Returns
    -------
    list[FillerMember]
        Length ``target_count``, names + usernames unique within the org.
    """
    rng = _seeded_rng(org_bible.slug)
    delegate_pool = list(delegate_pool or [])

    # Build a working pool of names — copy + shuffle deterministically so
    # different orgs draw different subsets of NAME_POOL.
    pool = list(NAME_POOL)
    rng.shuffle(pool)

    used_usernames: set[str] = set()
    fillers: list[FillerMember] = []

    for idx in range(target_count):
        first, last = pool[idx % len(pool)]
        # Username: first-initial + lowercased-last + per-index disambiguator
        # so collisions across recycled pool entries can't break the unique
        # constraint.
        base_username = f"{first[0].lower()}{last.lower()}_{idx:02d}"
        # Strip non-alphanumerics (e.g., apostrophes from O'Brien) for safety.
        base_username = re.sub(r"[^a-z0-9_]", "", base_username)
        username = base_username
        suffix = 0
        while username in used_usernames:
            suffix += 1
            username = f"{base_username}{suffix}"
        used_usernames.add(username)

        delegates_to: Optional[tuple[str, str]] = None
        # Phase 29 C3: bumped from 0.30 → 0.70 so Cedar Hollow's
        # delegation graph reads as dense in the showcase. ~70%
        # filler participation lands roughly 30 filler delegations
        # across the ~45-filler pool.
        if delegate_pool and rng.random() < 0.70:
            delegates_to = rng.choice(delegate_pool)

        fillers.append(FillerMember(
            user_id=f"filler_{org_bible.slug}_{idx:03d}",
            display_name=f"{first} {last}",
            username=username,
            delegates_to=delegates_to,
        ))

    return fillers


# =============================================================================
# Vote allocation
# =============================================================================


_FINAL_RESULT_BINARY_RE = re.compile(
    r"(\d{1,3})\s*[-/]\s*(\d{1,3})\s*(passed|failed)?",
    re.IGNORECASE,
)


def _parse_binary_final_result(final_result: str) -> Optional[tuple[float, float]]:
    """Parse ``"58-42 passed"`` → ``(0.58, 0.42)``.

    Returns None if no parseable percentage pair is found.
    """
    if not final_result:
        return None
    m = _FINAL_RESULT_BINARY_RE.search(final_result)
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    if a + b == 0:
        return None
    total = float(a + b)
    return (a / total, b / total)


def allocate_filler_votes(
    proposal,
    trajectory: Trajectory,
    fillers: list[FillerMember],
    named_voter_summary: Optional[dict] = None,
    *,
    voting_start: Optional[datetime] = None,
    voting_end: Optional[datetime] = None,
    cast_by_resolver=None,
) -> list:
    """Allocate filler votes for ``proposal`` to hit trajectory final result.

    Parameters
    ----------
    proposal : ORM Proposal instance
        Must have ``id``, ``voting_method``, ``options`` (if multi-option).
    trajectory : Trajectory
        Provides ``final_result``, ``voting_method``, ``duration_hours``.
    fillers : list[FillerMember]
        Filler members eligible to vote on this proposal. Caller filters
        to ~30-70% participation per filler (deterministic).
    named_voter_summary : dict | None
        Optional ``{"yes": int, "no": int, "abstain": int}`` (or
        ``{option_id: count}`` for multi-option) summarising the
        named-character votes already produced. Filler counts are
        adjusted to ``final_split * total_eligible - named_count`` per
        bucket so the final tally hits the trajectory.
    voting_start, voting_end : datetime | None
        If provided, filler ``cast_at`` timestamps are spread across this
        window. If omitted, falls back to ``proposal.voting_start`` /
        ``proposal.voting_end``.
    cast_by_resolver : callable | None
        Function ``(filler_user_id: str) -> str`` returning the ``User.id``
        for the seeded user. Required for inserting ORM Vote rows whose
        ``user_id`` / ``cast_by_id`` reference real DB IDs.

    Returns
    -------
    list[models.Vote]
        Vote ORM instances ready for ``db.bulk_save_objects``. Empty list
        when no fillers participate (e.g., draft / deliberation proposal).
    """
    import models  # local import to avoid cycle at module-load

    voting_start = voting_start or getattr(proposal, "voting_start", None)
    voting_end = voting_end or getattr(proposal, "voting_end", None)
    if not voting_start or not voting_end or voting_end <= voting_start:
        # No usable voting window (draft/deliberation/etc.); skip.
        return []

    if cast_by_resolver is None:
        # Without a resolver, we can't make valid ORM rows.
        log.warning(
            "allocate_filler_votes: no cast_by_resolver provided for "
            "proposal=%s; returning empty allocation",
            getattr(proposal, "id", "?"),
        )
        return []

    rng = _seeded_rng(f"{trajectory.proposal_id}:votes")
    window_seconds = (voting_end - voting_start).total_seconds()
    method = trajectory.voting_method

    votes: list = []

    if method == "binary":
        # Parse the final-result split.
        split = _parse_binary_final_result(trajectory.final_result or "")
        if split is None:
            # Failed-quorum or unparseable: skip to keep behavior safe.
            log.info(
                "allocate_filler_votes: binary final_result %r unparseable for %s; "
                "no filler votes allocated",
                trajectory.final_result, trajectory.proposal_id,
            )
            return []
        yes_frac, no_frac = split
        total_target = len(fillers)
        named_yes = (named_voter_summary or {}).get("yes", 0)
        named_no = (named_voter_summary or {}).get("no", 0)
        # Target counts among fillers = approximation; ±2 tolerance per B5#31.
        target_yes = max(0, int(round(yes_frac * (total_target + named_yes + named_no))) - named_yes)
        target_no = max(0, int(round(no_frac * (total_target + named_yes + named_no))) - named_no)
        # If targets exceed available fillers, scale down.
        if target_yes + target_no > total_target:
            scale = total_target / max(target_yes + target_no, 1)
            target_yes = int(target_yes * scale)
            target_no = total_target - target_yes

        bucket = (["yes"] * target_yes) + (["no"] * target_no)
        # Pad remainder with abstains (rare but possible).
        bucket += ["abstain"] * (total_target - len(bucket))
        rng.shuffle(bucket)

        for i, vote_value in enumerate(bucket):
            user_id = cast_by_resolver(fillers[i].user_id)
            if not user_id:
                continue
            # Distribute cast_at across the window with mild front/back loading.
            t_frac = rng.random()
            cast_at = voting_start + timedelta(seconds=t_frac * window_seconds)
            votes.append(models.Vote(
                proposal_id=proposal.id,
                user_id=user_id,
                vote_value=vote_value,
                ballot=None,
                is_direct=True,
                cast_by_id=user_id,
                cast_at=cast_at,
            ))
        return votes

    # Approval / RCV / STV — pragmatic fallback per spec D6 update.
    # Each filler approves 1-2 options (approval) or ranks the available
    # options in randomized order (RCV/STV). The trajectory's final result
    # text is too varied to parse reliably; the chart still renders via the
    # snapshot generator's option_totals interpolation.
    options = getattr(proposal, "options", []) or []
    if not options:
        return []
    option_labels = [o.label for o in options]
    option_ids_by_label = {o.label: o.id for o in options}

    for i, filler in enumerate(fillers):
        user_id = cast_by_resolver(filler.user_id)
        if not user_id:
            continue
        t_frac = rng.random()
        cast_at = voting_start + timedelta(seconds=t_frac * window_seconds)

        if method == "approval":
            # Filler approves 1-2 random options, weighted slightly toward
            # earlier options (which correlates with the "leader" pattern
            # in bibles where Option 1 / Item 1 typically leads).
            k = 1 if rng.random() < 0.4 else 2
            picks = rng.sample(option_labels, min(k, len(option_labels)))
            ballot = {
                "approvals": [option_ids_by_label[lbl] for lbl in picks],
            }
        else:  # rcv / stv
            # Filler submits a partial ranking (top 2-3 picks).
            shuffled = list(option_labels)
            rng.shuffle(shuffled)
            rank_depth = min(len(shuffled), rng.choice([2, 3, 3, 4]))
            ranking = [option_ids_by_label[lbl] for lbl in shuffled[:rank_depth]]
            ballot = {"ranking": ranking}

        votes.append(models.Vote(
            proposal_id=proposal.id,
            user_id=user_id,
            vote_value=None,
            ballot=ballot,
            is_direct=True,
            cast_by_id=user_id,
            cast_at=cast_at,
        ))
    return votes


__all__ = [
    "FillerMember",
    "generate_filler_members",
    "allocate_filler_votes",
    "_seeded_rng",  # exported for tests
]
