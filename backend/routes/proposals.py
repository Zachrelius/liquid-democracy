from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

import auth as auth_utils
import models
import schemas
from database import get_db
from delegation_engine import engine as delegation_engine

router = APIRouter(prefix="/api/proposals", tags=["proposals"])

STATUS_TRANSITIONS = {
    "draft": "deliberation",
    "deliberation": "voting",
    "voting": "passed",  # actual pass/fail determined at close; admin forces
}


def _proposal_or_404(proposal_id: str, db: Session) -> models.Proposal:
    p = db.get(models.Proposal, proposal_id)
    if not p:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return p


def _build_proposal_out(proposal: models.Proposal) -> schemas.ProposalOut:
    topics = [pt.topic for pt in proposal.proposal_topics]
    return schemas.ProposalOut(
        id=proposal.id,
        title=proposal.title,
        body=proposal.body,
        author_id=proposal.author_id,
        author=proposal.author,
        status=proposal.status,
        deliberation_start=proposal.deliberation_start,
        voting_start=proposal.voting_start,
        voting_end=proposal.voting_end,
        pass_threshold=proposal.pass_threshold,
        quorum_threshold=proposal.quorum_threshold,
        created_at=proposal.created_at,
        updated_at=proposal.updated_at,
        topics=topics,
    )


@router.get("", response_model=list[schemas.ProposalOut])
def list_proposals(
    status_filter: Optional[str] = Query(None, alias="status"),
    topic_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(models.Proposal)
    if status_filter:
        q = q.filter(models.Proposal.status == status_filter)
    if topic_id:
        q = q.join(models.ProposalTopic).filter(models.ProposalTopic.topic_id == topic_id)
    proposals = q.order_by(models.Proposal.created_at.desc()).all()
    return [_build_proposal_out(p) for p in proposals]


@router.post("", response_model=schemas.ProposalOut, status_code=status.HTTP_201_CREATED)
def create_proposal(
    body: schemas.ProposalCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    # Validate topic IDs
    for tid in body.topic_ids:
        if not db.get(models.Topic, tid):
            raise HTTPException(status_code=400, detail=f"Topic {tid} not found")

    proposal = models.Proposal(
        title=body.title,
        body=body.body,
        author_id=current_user.id,
        pass_threshold=body.pass_threshold,
        quorum_threshold=body.quorum_threshold,
    )
    db.add(proposal)
    db.flush()

    for tid in body.topic_ids:
        db.add(models.ProposalTopic(proposal_id=proposal.id, topic_id=tid))

    db.commit()
    db.refresh(proposal)
    return _build_proposal_out(proposal)


@router.get("/{proposal_id}", response_model=schemas.ProposalOut)
def get_proposal(proposal_id: str, db: Session = Depends(get_db)):
    return _build_proposal_out(_proposal_or_404(proposal_id, db))


@router.patch("/{proposal_id}", response_model=schemas.ProposalOut)
def update_proposal(
    proposal_id: str,
    body: schemas.ProposalUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    proposal = _proposal_or_404(proposal_id, db)

    if proposal.status != "draft":
        raise HTTPException(status_code=400, detail="Only draft proposals can be edited")
    if proposal.author_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Not the proposal author")

    if body.title is not None:
        proposal.title = body.title
    if body.body is not None:
        proposal.body = body.body
    if body.topic_ids is not None:
        for pt in list(proposal.proposal_topics):
            db.delete(pt)
        db.flush()
        for tid in body.topic_ids:
            if not db.get(models.Topic, tid):
                raise HTTPException(status_code=400, detail=f"Topic {tid} not found")
            db.add(models.ProposalTopic(proposal_id=proposal.id, topic_id=tid))

    db.commit()
    db.refresh(proposal)
    return _build_proposal_out(proposal)


@router.post("/{proposal_id}/advance", response_model=schemas.ProposalOut)
def advance_proposal(
    proposal_id: str,
    body: schemas.AdvanceProposalRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    proposal = _proposal_or_404(proposal_id, db)

    if proposal.author_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Not the proposal author or admin")

    next_status = STATUS_TRANSITIONS.get(proposal.status)
    if next_status is None:
        raise HTTPException(status_code=400, detail=f"Cannot advance from status '{proposal.status}'")

    now = datetime.now(timezone.utc)

    if next_status == "deliberation":
        proposal.deliberation_start = now
    elif next_status == "voting":
        proposal.voting_start = now
        if body.voting_end:
            proposal.voting_end = body.voting_end
    elif next_status == "passed":
        # Admin is closing the vote; determine actual outcome
        tally = delegation_engine.compute_tally(proposal, db)
        if tally.threshold_met(proposal.pass_threshold) and tally.quorum_met(proposal.quorum_threshold):
            next_status = "passed"
        else:
            next_status = "failed"

    proposal.status = next_status
    db.commit()
    db.refresh(proposal)
    return _build_proposal_out(proposal)


@router.get("/{proposal_id}/results", response_model=schemas.ProposalResults)
def get_results(proposal_id: str, db: Session = Depends(get_db)):
    proposal = _proposal_or_404(proposal_id, db)
    tally = delegation_engine.compute_tally(proposal, db)

    snapshots = (
        db.query(models.VoteSnapshot)
        .filter(models.VoteSnapshot.proposal_id == proposal_id)
        .order_by(models.VoteSnapshot.simulated_time)
        .all()
    )
    time_series = [
        schemas.SnapshotPoint(
            simulated_time=s.simulated_time,
            yes=s.yes_count,
            no=s.no_count,
            abstain=s.abstain_count,
            not_cast=s.not_cast_count,
            total_eligible=s.total_eligible,
        )
        for s in snapshots
    ]

    return schemas.ProposalResults(
        proposal_id=proposal_id,
        yes=tally.yes,
        no=tally.no,
        abstain=tally.abstain,
        not_cast=tally.not_cast,
        total_eligible=tally.total_eligible,
        yes_pct=round(tally.yes_pct, 4),
        no_pct=round(tally.no_pct, 4),
        abstain_pct=round(tally.abstain_pct, 4),
        quorum_met=tally.quorum_met(proposal.quorum_threshold),
        threshold_met=tally.threshold_met(proposal.pass_threshold),
        time_series=time_series,
    )


@router.get("/{proposal_id}/my-vote", response_model=schemas.MyVoteStatus)
def my_vote_status(
    proposal_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    proposal = _proposal_or_404(proposal_id, db)
    result = delegation_engine.resolve_vote(current_user.id, proposal.id, db)

    if result is None:
        delegate_result = delegation_engine.find_delegate(current_user.id, proposal.id, db)
        if delegate_result:
            _, delegation = delegate_result
            delegate = db.get(models.User, delegation.delegate_id)
            msg = (
                f"Your delegate {delegate.display_name} has not voted. "
                f"Chain behavior: {delegation.chain_behavior}."
            )
        else:
            msg = "You have not voted and have no delegation covering this proposal."
        return schemas.MyVoteStatus(
            vote_value=None,
            is_direct=None,
            delegate_chain=None,
            cast_by=None,
            message=msg,
        )

    cast_by_user = db.get(models.User, result.cast_by_id)
    if result.is_direct:
        msg = f"You voted {result.vote_value.upper()} directly."
    else:
        chain_names = []
        for uid in result.delegate_chain:
            u = db.get(models.User, uid)
            chain_names.append(u.display_name if u else uid)
        msg = f"Your vote is {result.vote_value.upper()} via {' → '.join(chain_names)}."

    return schemas.MyVoteStatus(
        vote_value=result.vote_value,
        is_direct=result.is_direct,
        delegate_chain=result.delegate_chain,
        cast_by=cast_by_user,
        message=msg,
    )
