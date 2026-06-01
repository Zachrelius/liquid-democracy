"""Phase 46 — Cosign-gated proposals (petition threshold).

Per-org ``proposal_creation_mode`` (Phase 46 B1) has three values:

  * ``open`` (default — pre-46 behavior preserved): any holder of
    ``proposal.create`` creates proposals that go live immediately.
  * ``cosign_required`` (opt-in): a member-tier creator's proposal
    enters the cosign-gathering state (``deliberation`` status with
    ``is_cosign_gated=True``); the proposal advances to ``voting`` when
    the signature count reaches the threshold (D2/D3). Holders of
    ``proposal.advance_phase`` create normally (the mode is a floor
    for ordinary members, not a ceiling on admins).
  * ``admin_only``: only callers holding ``proposal.advance_phase`` can
    create. Members (no advance permission) get 403.

The cosign config lives in ``Organization.settings.cosign`` as::

    {
      "threshold": 3,         # minimum signatures including the author (D3)
      "expiry_hours": 168,    # gathering window in hours (default 7 days)
    }

The threshold + expiry are snapshotted onto the Proposal row at create
time so later org-config changes don't move the goalposts mid-petition.

Phase 47 (elections) will consume this module as one election-trigger
option but must not couple it (D5). Keep the API proposal-type-agnostic.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

import models


OPEN = "open"
COSIGN_REQUIRED = "cosign_required"
ADMIN_ONLY = "admin_only"

VALID_MODES: frozenset[str] = frozenset({OPEN, COSIGN_REQUIRED, ADMIN_ONLY})

# Defaults match the spec's "sensible defaults" — threshold of 3 + a
# 7-day window. Orgs override via Organization.settings.cosign.
_DEFAULT_THRESHOLD = 3
_DEFAULT_EXPIRY_HOURS = 24 * 7  # 168 hours = 7 days
_MIN_THRESHOLD = 1
_MIN_EXPIRY_HOURS = 1


def mode_of(org: Optional[models.Organization]) -> str:
    """Read the org's proposal_creation_mode. Defaults to OPEN if the
    field is missing or invalid (defensive — the column is NOT NULL with
    server_default, but test fixtures may bypass it)."""
    if org is None:
        return OPEN
    mode = getattr(org, "proposal_creation_mode", None)
    if mode in VALID_MODES:
        return mode
    return OPEN


def get_cosign_config(org: Optional[models.Organization]) -> dict:
    """Return ``{threshold, expiry_hours}`` for the org, applying
    defaults + clamping invalid values."""
    cfg = {}
    if org is not None:
        raw = (org.settings or {}).get("cosign")
        if isinstance(raw, dict):
            cfg = raw
    threshold = cfg.get("threshold", _DEFAULT_THRESHOLD)
    if not isinstance(threshold, int) or threshold < _MIN_THRESHOLD:
        threshold = _DEFAULT_THRESHOLD
    expiry_hours = cfg.get("expiry_hours", _DEFAULT_EXPIRY_HOURS)
    if not isinstance(expiry_hours, (int, float)) or expiry_hours < _MIN_EXPIRY_HOURS:
        expiry_hours = _DEFAULT_EXPIRY_HOURS
    return {"threshold": int(threshold), "expiry_hours": int(expiry_hours)}


def normalize_config_input(raw: dict) -> dict:
    """Validate a config dict submitted via PATCH /api/orgs/{slug}.
    Returns the normalized shape; raises HTTPException(400) on bad values.
    """
    if not isinstance(raw, dict):
        raise HTTPException(
            status_code=400,
            detail="cosign config must be an object",
        )
    out: dict = {}
    if "threshold" in raw:
        t = raw["threshold"]
        if not isinstance(t, int) or t < _MIN_THRESHOLD:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"cosign.threshold must be an integer >= {_MIN_THRESHOLD}"
                ),
            )
        out["threshold"] = t
    if "expiry_hours" in raw:
        h = raw["expiry_hours"]
        if not isinstance(h, (int, float)) or h < _MIN_EXPIRY_HOURS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"cosign.expiry_hours must be a positive number "
                    f">= {_MIN_EXPIRY_HOURS}"
                ),
            )
        out["expiry_hours"] = int(h)
    return out


def caller_can_bypass_cosign(
    db: Session, user_id: str, org: models.Organization,
) -> bool:
    """True if the caller holds ``proposal.advance_phase`` on this org —
    the canonical "can advance proposals" permission. Such users create
    proposals directly even in ``cosign_required`` mode (the mode is a
    floor for ordinary members, not a ceiling on admins).
    """
    from role_permissions import has_permission
    return has_permission(db, user_id, org.id, "proposal.advance_phase")


def gate_proposal_creation(
    db: Session, user_id: str, org: models.Organization,
) -> str:
    """Return one of:
      - 'direct': the proposal goes live (standard flow).
      - 'cosign_gated': the proposal enters cosign gathering.
    Raises HTTPException(403) when ``admin_only`` mode blocks the caller.
    """
    mode = mode_of(org)
    if mode == OPEN:
        return "direct"
    if mode == COSIGN_REQUIRED:
        return "direct" if caller_can_bypass_cosign(db, user_id, org) else "cosign_gated"
    # ADMIN_ONLY
    if caller_can_bypass_cosign(db, user_id, org):
        return "direct"
    raise HTTPException(
        status_code=403,
        detail=(
            "This organization only allows admins/moderators to create "
            "proposals (proposal_creation_mode='admin_only')."
        ),
    )


def signature_count(db: Session, proposal_id: str) -> int:
    """Headcount of signers on a proposal. Phase 46a — kept as a
    distinct surface from ``cosign_weight`` so the UI can show both
    ("Signed by 4 members · 8.5 of 12 weight needed")."""
    return (
        db.query(models.ProposalCosignature)
        .filter(models.ProposalCosignature.proposal_id == proposal_id)
        .count()
    )


def signer_ids_for(db: Session, proposal_id: str) -> set[str]:
    """Return the user_ids of everyone who has signed this proposal."""
    rows = (
        db.query(models.ProposalCosignature.user_id)
        .filter(models.ProposalCosignature.proposal_id == proposal_id)
        .all()
    )
    return {r.user_id for r in rows}


def cosign_weight(
    db: Session, proposal: models.Proposal,
) -> int:
    """Phase 46a Item 1 — total cosign weight = number of eligible
    voters whose vote on this proposal would resolve to ANY current
    signer's ballot if those signers had cast direct ballots and no
    one else had.

    Reuses the platform's tally/delegation engine (not a parallel
    implementation): builds a ProposalContext with the real delegation
    graph + topic precedences, overrides ``direct_ballots`` /
    ``direct_votes`` with synthetic ballots for the signers only, and
    counts users whose ``resolve_vote_pure`` result lands on a signer's
    ``cast_by_id``.

    Properties:
      * A direct signer with no inbound delegation contributes weight 1
        (themselves).
      * A signer who is the topic-relevant delegate for N users
        contributes weight 1 + N (themselves + N delegators).
      * Multiple signers do not double-count overlapping delegators:
        a user who would resolve to ANY one signer counts once.
      * Weight resolves live against the current delegation graph —
        not snapshotted at signing time. The window-end gate (Item 2)
        evaluates against this live weight.
    """
    signers = signer_ids_for(db, proposal.id)
    return resolve_cosign_weight_for_signers(db, proposal, signers)


def resolve_cosign_weight_for_signers(
    db: Session,
    proposal: models.Proposal,
    signer_ids: set[str],
) -> int:
    """Same computation as ``cosign_weight`` but with an explicit signer
    set. Used by the weight resolution itself + by the UI to project
    "what if I signed?" weights (the FE may surface the viewer's own
    resolved weight on the gathering panel).
    """
    if not signer_ids:
        return 0

    # Late import — delegation_engine imports models too; circular if
    # we top-level import.
    from delegation_engine import (
        DelegationService, resolve_vote_pure, Ballot,
        eligible_voter_ids_for_proposal,
    )

    try:
        eligible_ids = eligible_voter_ids_for_proposal(db, proposal)
    except Exception:
        # Defensive: if eligibility resolution errors for any reason,
        # fall back to headcount semantics for this proposal so the
        # cosign machinery keeps working. Cheap on real prod orgs.
        return len(signer_ids)

    ctx = DelegationService._build_context(
        proposal, db, eligible_ids=eligible_ids,
    )
    # Override real direct ballots with synthetic ones for ONLY the
    # signers. The real ballots aren't relevant to the cosign-weight
    # question (we're asking "what weight would these signers' votes
    # carry if cast now?"), and during cosign gathering there are no
    # real votes anyway. Synthetic ballot shape is voting-method-
    # specific so the resolver's dispatch finds a non-empty ballot.
    ctx.direct_votes = {}
    ctx.direct_ballots = {}
    voting_method = ctx.voting_method
    for sid in signer_ids:
        if voting_method == "approval":
            ctx.direct_ballots[sid] = Ballot(approvals=["__cosign__"])
        elif voting_method == "ranked_choice":
            ctx.direct_ballots[sid] = Ballot(ranking=["__cosign__"])
        else:
            # Binary — use a non-null vote_value so the resolver
            # recognizes the direct ballot at step 1.
            ctx.direct_votes[sid] = "yes"

    weight = 0
    for uid in eligible_ids:
        try:
            result = resolve_vote_pure(uid, ctx)
        except Exception:
            continue
        if result is not None and result.cast_by_id in signer_ids:
            weight += 1
    return weight


def add_signature(
    db: Session,
    proposal: models.Proposal,
    user_id: str,
) -> tuple[bool, int]:
    """Insert a cosignature row for ``user_id`` on ``proposal``. Idempotent:
    if the user has already signed, returns ``(False, current_count)``
    without mutation. Otherwise inserts and returns ``(True, new_count)``.

    Caller is responsible for any external validation (active member of
    the org, proposal is currently cosign-gated, etc.) and for committing.
    """
    existing = (
        db.query(models.ProposalCosignature)
        .filter(
            models.ProposalCosignature.proposal_id == proposal.id,
            models.ProposalCosignature.user_id == user_id,
        )
        .first()
    )
    if existing is not None:
        return False, signature_count(db, proposal.id)
    row = models.ProposalCosignature(proposal_id=proposal.id, user_id=user_id)
    db.add(row)
    db.flush()
    return True, signature_count(db, proposal.id)


def remove_signature(
    db: Session,
    proposal: models.Proposal,
    user_id: str,
) -> tuple[bool, int]:
    """Delete the cosignature row for ``user_id``. The author may not
    withdraw their implicit first signature (D4) — call sites must check
    ``user_id == proposal.author_id`` before invoking and reject with 400.

    Returns ``(removed, new_count)``. If the user hadn't signed,
    ``removed=False`` and ``new_count`` is the unchanged count.
    """
    existing = (
        db.query(models.ProposalCosignature)
        .filter(
            models.ProposalCosignature.proposal_id == proposal.id,
            models.ProposalCosignature.user_id == user_id,
        )
        .first()
    )
    if existing is None:
        return False, signature_count(db, proposal.id)
    db.delete(existing)
    db.flush()
    return True, signature_count(db, proposal.id)


def threshold_for(proposal: models.Proposal) -> Optional[int]:
    """Return the proposal's snapshot threshold; None for non-cosign-gated
    proposals."""
    return getattr(proposal, "cosign_threshold_snapshot", None)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def init_cosign_gated_proposal(
    db: Session,
    proposal: models.Proposal,
    org: models.Organization,
) -> None:
    """Stamp the cosign markers on ``proposal`` + insert the author's
    implicit first signature (D3). Caller invokes this when the create
    handler routes the proposal to cosign-gathering state.

    Sets:
      - is_cosign_gated = True
      - cosign_threshold_snapshot = org's current configured threshold
      - cosign_expires_at = now + expiry_hours
      - deliberation_start = now (we entered the deliberation phase)
    The proposal's ``status`` is the caller's concern (typically left at
    'deliberation').
    """
    cfg = get_cosign_config(org)
    proposal.is_cosign_gated = True
    proposal.cosign_threshold_snapshot = cfg["threshold"]
    now = _now()
    proposal.deliberation_start = now
    proposal.cosign_expires_at = now + timedelta(hours=cfg["expiry_hours"])
    # Author's implicit first signature (D3 — author counts as 1).
    add_signature(db, proposal, proposal.author_id)


def threshold_met(db: Session, proposal: models.Proposal) -> bool:
    """Phase 46a Item 1 — True iff the proposal's current cosign WEIGHT
    meets or exceeds its snapshot threshold. Phase 46 used headcount;
    46a switched to weight to honor delegation (a topic-trusted delegate
    can advance with proportionally less raw headcount).
    """
    threshold = threshold_for(proposal)
    if threshold is None:
        return False
    return cosign_weight(db, proposal) >= threshold
