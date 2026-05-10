from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

import auth as auth_utils
import models
import schemas
from audit_utils import log_audit_event
from database import get_db
from delegation_engine import engine as delegation_engine, eligible_voter_ids_for_proposal
from permissions import can_view_vote_rationale
from websocket import manager as ws_manager

router = APIRouter(prefix="/api/proposals", tags=["votes"])

# Phase 19 (B6) — vote rationale CRUD lives on a separate APIRouter so the
# URL prefix can be ``/api/votes/{vote_id}/rationale`` (the spec's chosen
# shape) without colliding with the proposal-prefixed routes above.
rationale_router = APIRouter(prefix="/api/votes", tags=["vote-rationale"])


def _proposal_or_404(proposal_id: str, db: Session) -> models.Proposal:
    p = db.get(models.Proposal, proposal_id)
    if not p:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return p


def _require_voting_open(proposal: models.Proposal) -> None:
    if proposal.status != "voting":
        raise HTTPException(status_code=400, detail="Proposal is not in voting phase")


@router.post("/{proposal_id}/vote", response_model=schemas.VoteOut, status_code=status.HTTP_200_OK)
async def cast_vote(
    proposal_id: str,
    body: schemas.VoteCast,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    proposal = _proposal_or_404(proposal_id, db)
    _require_voting_open(proposal)

    if not current_user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email before voting.",
        )

    # Phase 10.1: eligibility check. Pre-fix, parent-org members could vote on
    # sub-org proposals they weren't members of, and cross-org users could
    # vote on any proposal whose ID they knew. The new gate uses the same
    # eligible_voter_ids_for_proposal helper that compute_tally and
    # get_vote_graph use, so the three call sites stay in lockstep.
    eligible_ids = eligible_voter_ids_for_proposal(db, proposal)
    if current_user.id not in eligible_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not eligible to vote on this proposal.",
        )

    # -- Method-specific validation --
    if proposal.voting_method == "binary":
        if body.approvals is not None or body.ranking is not None:
            raise HTTPException(status_code=400, detail="Use vote_value for binary proposals")
        if body.vote_value is None:
            raise HTTPException(status_code=400, detail="vote_value is required for binary proposals")
        vote_value = body.vote_value
        ballot = None
    elif proposal.voting_method == "approval":
        if body.vote_value is not None or body.ranking is not None:
            raise HTTPException(status_code=400, detail="Use approvals for approval proposals")
        if body.approvals is None:
            raise HTTPException(status_code=400, detail="approvals is required for approval proposals")
        # Validate option IDs belong to this proposal
        valid_option_ids = {opt.id for opt in proposal.options}
        for oid in body.approvals:
            if oid not in valid_option_ids:
                raise HTTPException(status_code=400, detail=f"Option {oid} does not belong to this proposal")
        vote_value = None
        ballot = {"approvals": body.approvals}
    elif proposal.voting_method == "ranked_choice":
        if body.vote_value is not None or body.approvals is not None:
            raise HTTPException(status_code=400, detail="Use ranking for ranked-choice proposals")
        if body.ranking is None:
            raise HTTPException(status_code=400, detail="ranking is required for ranked-choice proposals")
        valid_option_ids = {opt.id for opt in proposal.options}
        if len(body.ranking) > len(valid_option_ids):
            raise HTTPException(
                status_code=400,
                detail="Ranking length exceeds proposal option count",
            )
        for oid in body.ranking:
            if oid not in valid_option_ids:
                raise HTTPException(status_code=400, detail=f"Option {oid} does not belong to this proposal")
        vote_value = None
        ballot = {"ranking": body.ranking}
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported voting method: {proposal.voting_method}")

    existing = (
        db.query(models.Vote)
        .filter(
            models.Vote.proposal_id == proposal_id,
            models.Vote.user_id == current_user.id,
        )
        .first()
    )

    ip = request.client.host if request.client else None

    if existing:
        previous_value = existing.vote_value
        previous_ballot = existing.ballot
        existing.vote_value = vote_value
        existing.ballot = ballot
        existing.is_direct = True
        existing.delegate_chain = None
        existing.cast_by_id = current_user.id
        db.flush()
        log_audit_event(
            db,
            action="vote.cast",
            target_type="vote",
            target_id=existing.id,
            actor_id=current_user.id,
            details={
                "proposal_id": proposal_id,
                "vote_value": vote_value,
                "ballot": ballot,
                "is_direct": True,
                "previous_value": previous_value,
                "delegate_chain": None,
            },
            ip_address=ip,
        )
        db.commit()
        db.refresh(existing)
        vote = existing
    else:
        vote = models.Vote(
            proposal_id=proposal_id,
            user_id=current_user.id,
            vote_value=vote_value,
            ballot=ballot,
            is_direct=True,
            delegate_chain=None,
            cast_by_id=current_user.id,
        )
        db.add(vote)
        db.flush()
        log_audit_event(
            db,
            action="vote.cast",
            target_type="vote",
            target_id=vote.id,
            actor_id=current_user.id,
            details={
                "proposal_id": proposal_id,
                "vote_value": vote_value,
                "ballot": ballot,
                "is_direct": True,
                "previous_value": None,
                "delegate_chain": None,
            },
            ip_address=ip,
        )
        db.commit()
        db.refresh(vote)

    # Broadcast updated tally via WebSocket
    tally = delegation_engine.compute_tally(proposal, db)
    await ws_manager.broadcast_tally(proposal_id, tally)

    return vote


@router.delete("/{proposal_id}/vote", status_code=status.HTTP_204_NO_CONTENT)
async def retract_vote(
    proposal_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    proposal = _proposal_or_404(proposal_id, db)
    _require_voting_open(proposal)

    # Phase 10.1: same eligibility gate as cast_vote — a non-eligible user
    # shouldn't be able to retract a vote they shouldn't have been able to
    # cast. See cast_vote for the bug history.
    eligible_ids = eligible_voter_ids_for_proposal(db, proposal)
    if current_user.id not in eligible_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not eligible to vote on this proposal.",
        )

    vote = (
        db.query(models.Vote)
        .filter(
            models.Vote.proposal_id == proposal_id,
            models.Vote.user_id == current_user.id,
            models.Vote.is_direct.is_(True),
        )
        .first()
    )
    if not vote:
        raise HTTPException(status_code=404, detail="No direct vote to retract")

    previous_value = vote.vote_value
    vote_id = vote.id

    log_audit_event(
        db,
        action="vote.retracted",
        target_type="vote",
        target_id=vote_id,
        actor_id=current_user.id,
        details={"proposal_id": proposal_id, "previous_value": previous_value},
        ip_address=request.client.host if request.client else None,
    )
    db.delete(vote)
    db.commit()

    tally = delegation_engine.compute_tally(proposal, db)
    await ws_manager.broadcast_tally(proposal_id, tally)


# ---------------------------------------------------------------------------
# Phase 19 (B6) — Vote rationale CRUD
# ---------------------------------------------------------------------------
#
# All three endpoints operate on the optional one-to-one
# ``DelegateVoteRationale`` row attached to a ``Vote``. The vote-owner
# bypass for visibility lives in ``can_view_vote_rationale`` (centralized
# in ``permissions.py`` per spec line 326). Write endpoints are vote-
# owner-only and validate non-empty content via the schema.


def _vote_or_404(db: Session, vote_id: str) -> models.Vote:
    vote = db.get(models.Vote, vote_id)
    if vote is None:
        raise HTTPException(status_code=404, detail="Vote not found")
    return vote


@rationale_router.get(
    "/{vote_id}/rationale",
    response_model=schemas.DelegateVoteRationaleOut,
)
def get_vote_rationale(
    vote_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Return the rationale for ``vote_id`` if the caller has visibility.

    Visibility is gated by ``can_view_vote_rationale`` — vote owner
    always; others only when (a) the proposal's primary topic is in
    non-private state for the vote owner AND (b) viewer has access to
    the org. 404 (not 403) when visibility is denied to avoid leaking
    rationale existence to unauthorized callers.
    """
    vote = _vote_or_404(db, vote_id)
    if not can_view_vote_rationale(current_user, vote, db):
        raise HTTPException(status_code=404, detail="Rationale not found")

    rationale = (
        db.query(models.DelegateVoteRationale)
        .filter(models.DelegateVoteRationale.vote_id == vote_id)
        .first()
    )
    if rationale is None:
        raise HTTPException(status_code=404, detail="Rationale not found")
    return rationale


@rationale_router.put(
    "/{vote_id}/rationale",
    response_model=schemas.DelegateVoteRationaleOut,
)
def upsert_vote_rationale(
    vote_id: str,
    body: schemas.DelegateVoteRationaleUpsert,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Vote-owner-only — create or update the rationale on this vote.
    Markdown sanitization happens at render time (matches comment
    behavior per spec §B6) — content stored verbatim.
    """
    vote = _vote_or_404(db, vote_id)
    if vote.user_id != current_user.id:
        # 404 not 403: treat the rationale as if it doesn't exist for
        # non-owners so the surface doesn't leak which votes have
        # rationale via 403-vs-404 timing differences.
        raise HTTPException(status_code=404, detail="Vote not found")

    rationale = (
        db.query(models.DelegateVoteRationale)
        .filter(models.DelegateVoteRationale.vote_id == vote_id)
        .first()
    )
    ip = request.client.host if request.client else None

    if rationale is None:
        rationale = models.DelegateVoteRationale(
            vote_id=vote_id,
            content=body.content,
        )
        db.add(rationale)
        db.flush()
        log_audit_event(
            db,
            action="delegate_vote_rationale.created",
            target_type="delegate_vote_rationale",
            target_id=rationale.id,
            actor_id=current_user.id,
            details={
                "vote_id": vote_id,
                "proposal_id": vote.proposal_id,
            },
            ip_address=ip,
        )
    else:
        rationale.content = body.content
        db.flush()
        log_audit_event(
            db,
            action="delegate_vote_rationale.updated",
            target_type="delegate_vote_rationale",
            target_id=rationale.id,
            actor_id=current_user.id,
            details={
                "vote_id": vote_id,
                "proposal_id": vote.proposal_id,
            },
            ip_address=ip,
        )

    db.commit()
    db.refresh(rationale)
    return rationale


@rationale_router.delete(
    "/{vote_id}/rationale",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_vote_rationale(
    vote_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Vote-owner-only — remove the rationale row on this vote. Returns
    explicit ``Response(status_code=204)`` per Phase 18.5 lesson (FastAPI
    implicit-None-on-204 quirk causes Cloudflare 503).
    """
    vote = _vote_or_404(db, vote_id)
    if vote.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Vote not found")

    rationale = (
        db.query(models.DelegateVoteRationale)
        .filter(models.DelegateVoteRationale.vote_id == vote_id)
        .first()
    )
    if rationale is None:
        raise HTTPException(status_code=404, detail="Rationale not found")

    rationale_id = rationale.id
    log_audit_event(
        db,
        action="delegate_vote_rationale.deleted",
        target_type="delegate_vote_rationale",
        target_id=rationale_id,
        actor_id=current_user.id,
        details={
            "vote_id": vote_id,
            "proposal_id": vote.proposal_id,
        },
        ip_address=request.client.host if request.client else None,
    )
    db.delete(rationale)
    db.commit()
    # Phase 18.5 B2 — explicit Response so the 204 doesn't carry a
    # ``content-type: application/json`` header that Cloudflare/Railway's
    # edge proxy rejects with a 503.
    return Response(status_code=204)
