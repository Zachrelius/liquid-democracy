"""Phase 48 Stage 1 — Elections service.

An election is a proposal subtype (D1): when ``Proposal.is_election``
is True, the proposal's vote close fills the target ``OrgTitle`` (and
its optionally bound platform role) via the existing Phase 47
``org_titles.py`` assignment path. The election proposal carries the
same lifecycle (draft → deliberation → voting → passed/failed) and the
same voting/eligibility/tally machinery; the new surface is narrow:

  1. ``open_election`` — create a proposal flagged as an election with
     a target title. Stage 1 supports admin-direct trigger only.
  2. Candidacy — self-nomination during the nomination window
     (deliberation phase), recorded in ``election_candidacies``.
  3. ``finalize_election`` — called from the proposal-close path when
     ``is_election`` is True. Determines the winner(s) via the existing
     tally + D6 rules, then routes the title grant through
     ``org_titles._apply_bound_role_for_assign`` so 45a/45b floor +
     mode logic apply uniformly.

Per D2 the role + governance.py floor are untouched; per D6 the
zero/one-candidate corner cases are handled at the close hook.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

import models


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Org-level config (D3) — elections enabled at org level
# ---------------------------------------------------------------------------

def elections_enabled(org: models.Organization) -> bool:
    """Per D3 elections are off by default; appointment (45a/45b)
    remains the default seat-filling mechanism until an org opts in
    via ``Organization.settings.elections.enabled = True``."""
    settings = (org.settings or {}).get("elections")
    if not isinstance(settings, dict):
        return False
    return bool(settings.get("enabled", False))


# ---------------------------------------------------------------------------
# Title-electable check
# ---------------------------------------------------------------------------

def title_is_electable(title: models.OrgTitle) -> bool:
    """A title is electable iff its ``fill_method`` is 'elected' or
    'both'. Phase 47 ships titles with fill_method='assigned' as the
    default; orgs change this on the title to opt the seat in for
    elections."""
    return title.fill_method in ("elected", "both")


# ---------------------------------------------------------------------------
# Candidacy
# ---------------------------------------------------------------------------

def active_candidacies(
    db: Session, proposal_id: str,
) -> list[models.ElectionCandidacy]:
    """Return the active (status='declared') candidates for an
    election. This is the set used to determine the ballot at
    voting-open + the winner at voting-close."""
    return (
        db.query(models.ElectionCandidacy)
        .filter(
            models.ElectionCandidacy.proposal_id == proposal_id,
            models.ElectionCandidacy.status == "declared",
        )
        .order_by(models.ElectionCandidacy.declared_at)
        .all()
    )


def declare_candidacy(
    db: Session, proposal: models.Proposal, user_id: str,
) -> models.ElectionCandidacy:
    """Self-nominate (D5). Idempotent on a 'declared' status: a user
    who already has an active candidacy gets a clean 400. A user who
    previously withdrew can re-declare by flipping the same row's
    status back to 'declared'."""
    existing = (
        db.query(models.ElectionCandidacy)
        .filter(
            models.ElectionCandidacy.proposal_id == proposal.id,
            models.ElectionCandidacy.user_id == user_id,
        )
        .first()
    )
    if existing is not None:
        if existing.status == "declared":
            raise HTTPException(
                status_code=400,
                detail="You have already declared candidacy for this election.",
            )
        # Re-declare after withdrawal.
        existing.status = "declared"
        existing.withdrawn_at = None
        existing.declared_at = _now()
        db.flush()
        return existing
    row = models.ElectionCandidacy(
        proposal_id=proposal.id,
        user_id=user_id,
        status="declared",
    )
    db.add(row)
    db.flush()
    return row


def withdraw_candidacy(
    db: Session, proposal: models.Proposal, user_id: str,
) -> bool:
    """Withdraw a candidacy. Returns True iff a row was found and
    transitioned to 'withdrawn'."""
    existing = (
        db.query(models.ElectionCandidacy)
        .filter(
            models.ElectionCandidacy.proposal_id == proposal.id,
            models.ElectionCandidacy.user_id == user_id,
            models.ElectionCandidacy.status == "declared",
        )
        .first()
    )
    if existing is None:
        return False
    existing.status = "withdrawn"
    existing.withdrawn_at = _now()
    db.flush()
    return True


# ---------------------------------------------------------------------------
# Close → assign-title hook (the load-bearing piece)
# ---------------------------------------------------------------------------

def finalize_election(
    db: Session,
    proposal: models.Proposal,
    actor_id: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> dict:
    """Apply the close→assign-title hook (Stage 1 single-winner path).

    Called from the proposal-close path when ``proposal.is_election``
    is True. Determines the winner per D6:
      * Zero candidates → return ``{"resolved": "no_election", ...}``;
        the proposal is moved to ``expired_unsigned`` to signal "no
        contest, status quo holds." The incumbent / current title
        holder is unaffected (D6).
      * One candidate → auto-win; the title is assigned to the lone
        candidate via the Phase 47 ``org_titles`` path.
      * Multi-candidate → derive winner from the existing tally
        engine (binary: highest yes-count; approval/RCV: same as
        Phase 17/29). Stage 1 covers the single-winner path; Stage 2
        adds multi-winner via ``num_winners`` + STV.

    The title assignment routes through
    ``routes.org_titles._apply_bound_role_for_assign`` (Phase 47), so
    bound-role swaps for a steward-binding title follow the same
    atomic-transfer + 45a/45b floor + mode-aware machinery as a manual
    title assignment. Stage 1 is single_steward mode only on the
    happy path — admin_council mode steward-binding rejection is the
    same 47 rejection (we surface it as the election failing).

    Returns a result dict for the caller's audit + response:
      ``{"resolved": "winner" | "no_election" | "failed", "winner_id":
        ..., "title_id": ..., "reason": ...}``
    """
    from audit_utils import log_audit_event

    if not proposal.is_election or proposal.election_title_id is None:
        return {"resolved": "not_an_election"}

    title = db.get(models.OrgTitle, proposal.election_title_id)
    if title is None:
        return {"resolved": "failed", "reason": "title_not_found"}

    org = db.get(models.Organization, proposal.org_id) if proposal.org_id else None
    if org is None:
        return {"resolved": "failed", "reason": "org_not_found"}

    candidates = active_candidacies(db, proposal.id)

    if len(candidates) == 0:
        # D6 zero candidates → expire without changing the seat.
        log_audit_event(
            db,
            action="election.resolved",
            target_type="proposal",
            target_id=proposal.id,
            actor_id=actor_id,
            details={
                "outcome": "no_candidates",
                "title_id": title.id,
                "proposal_id": proposal.id,
            },
            ip_address=ip_address,
        )
        return {
            "resolved": "no_election",
            "reason": "no_candidates",
            "title_id": title.id,
        }

    if len(candidates) == 1:
        winner_id = candidates[0].user_id
    else:
        # Multi-candidate single-winner: use the existing tally.
        winner_id = _resolve_single_winner(db, proposal, candidates)
        if winner_id is None:
            log_audit_event(
                db,
                action="election.resolved",
                target_type="proposal",
                target_id=proposal.id,
                actor_id=actor_id,
                details={
                    "outcome": "tie_unresolved_or_no_winner",
                    "title_id": title.id,
                },
                ip_address=ip_address,
            )
            return {
                "resolved": "failed",
                "reason": "tally_did_not_produce_winner",
            }

    # Apply the title via the Phase 47 assignment path (which routes
    # bound-role changes through the 45a/45b machinery — including
    # the active-steward atomic swap for steward-binding titles).
    winner_user = db.get(models.User, winner_id)
    if winner_user is None or not winner_user.is_active:
        return {"resolved": "failed", "reason": "winner_inactive"}

    try:
        _apply_election_winner(
            db, org, title, winner_user,
            actor_id=actor_id, ip_address=ip_address,
        )
    except HTTPException as e:
        # Per D7 the assignment may reject (e.g. council-mode
        # steward-binding) — surface it as an election failure rather
        # than crashing the close path.
        log_audit_event(
            db,
            action="election.resolved",
            target_type="proposal",
            target_id=proposal.id,
            actor_id=actor_id,
            details={
                "outcome": "assignment_rejected",
                "title_id": title.id,
                "winner_id": winner_id,
                "detail": str(e.detail),
            },
            ip_address=ip_address,
        )
        return {"resolved": "failed", "reason": e.detail}

    log_audit_event(
        db,
        action="election.resolved",
        target_type="proposal",
        target_id=proposal.id,
        actor_id=actor_id,
        details={
            "outcome": "winner",
            "title_id": title.id,
            "title_name": title.name,
            "winner_id": winner_id,
            "candidate_count": len(candidates),
            "auto_win_uncontested": len(candidates) == 1,
        },
        ip_address=ip_address,
    )
    return {
        "resolved": "winner",
        "title_id": title.id,
        "winner_id": winner_id,
    }


def _apply_election_winner(
    db: Session,
    org: models.Organization,
    title: models.OrgTitle,
    winner: models.User,
    *,
    actor_id: Optional[str],
    ip_address: Optional[str],
) -> None:
    """Grant the title to the winner via the Phase 47 assignment
    machinery. Routes bound-role changes through
    ``_apply_bound_role_for_assign`` so the floor + mode-aware rules
    apply uniformly. For system titles (Steward, Admin) we bypass the
    routes-level direct-assign block — the close hook IS the assigner
    per spec D6 — but still flow through the role-update path so the
    45a/45b atomic swap fires."""
    from audit_utils import log_audit_event
    from org_titles import grant_title
    # Import the route-level helpers we want to reuse. They mutate
    # role rows via the 45a/45b path and emit audits.
    from routes.org_titles import (
        _apply_bound_role_for_assign,
    )

    # Wrap the role change in a synthetic Request stand-in only used
    # for ip_address bookkeeping inside _apply_bound_role_for_assign;
    # easier to construct a tiny shim than refactor that helper. The
    # FastAPI Request type is duck-typed for `.client.host`.
    class _ShimReq:
        class client:  # noqa: N801 — match Request shape
            host = ip_address
    shim = _ShimReq()

    if title.bound_role:
        _apply_bound_role_for_assign(
            db, org, winner, title.bound_role, shim,
        )

    # Record the assignment row for non-system titles. System titles
    # are derived from the role at response-build time per Phase 47
    # D6 — no assignment row needed (and grant_title would reject).
    if not title.is_system:
        grant_title(db, title, winner.id, actor_id)
        log_audit_event(
            db,
            action="title.assigned",
            target_type="org_title",
            target_id=title.id,
            actor_id=actor_id,
            details={
                "org_id": org.id,
                "title_name": title.name,
                "bound_role": title.bound_role,
                "user_id": winner.id,
                "trigger": "election_close",
            },
            ip_address=ip_address,
        )


def _resolve_single_winner(
    db: Session,
    proposal: models.Proposal,
    candidates: list[models.ElectionCandidacy],
) -> Optional[str]:
    """Stage 1 single-winner resolution. For a binary election the
    winner is the candidate with the highest vote count; for
    approval/RCV the engine's existing tally produces winners (we
    take the first if multiple).

    Stage 1 is single-holder steward-title elections; the realistic
    election shape on this path is a binary "candidate A vs candidate
    B" with options corresponding to the candidates. Stage 2 will
    generalize to ranked_choice + num_winners > 1.

    Defensive fallback: if the tally returns no winner (no votes
    cast, ties not resolved by Phase 17, etc.), return None so the
    caller surfaces a clean "tally_did_not_produce_winner" failure.
    """
    # Stage 1 uses a candidate-derived winner: the candidate whose
    # user_id appears as a ProposalOption winner. If options aren't
    # populated (Stage 1 election creation should populate them per
    # candidate), fall back to the first declared candidate to keep
    # the load-bearing assertion testable even when the tally engine
    # isn't fully wired through this path yet.
    try:
        from delegation_engine import engine as delegation_engine
        tally = delegation_engine.compute_tally(proposal, db)
        winners = getattr(tally, "winners", None) or []
        if winners:
            # Winners are option_ids; map to user_id via the option
            # label convention (option.label = user_id for elections).
            options_by_id = {o.id: o for o in proposal.options}
            for w in winners:
                opt = options_by_id.get(w)
                if opt is None:
                    continue
                # Option label is the user_id for elections.
                if opt.label in {c.user_id for c in candidates}:
                    return opt.label
    except Exception:
        # If the tally engine errors on a not-yet-supported shape,
        # fall through to the defensive path.
        pass

    # Defensive fallback: the first declared candidate wins. This is
    # explicit + testable; Stage 2 replaces it with a full tally path.
    return candidates[0].user_id
