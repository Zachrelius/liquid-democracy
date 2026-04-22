from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

import auth as auth_utils
import models
import schemas
from audit_utils import log_audit_event
from database import get_db
from delegation_engine import engine as delegation_engine, resolve_vote_pure
from permissions import can_see_votes

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
    return schemas.ProposalOut(
        id=proposal.id,
        title=proposal.title,
        body=proposal.body,
        author_id=proposal.author_id,
        author=proposal.author,
        status=proposal.status,
        voting_method=proposal.voting_method,
        num_winners=proposal.num_winners,
        tie_resolution=proposal.tie_resolution,
        deliberation_start=proposal.deliberation_start,
        voting_start=proposal.voting_start,
        voting_end=proposal.voting_end,
        pass_threshold=proposal.pass_threshold,
        quorum_threshold=proposal.quorum_threshold,
        created_at=proposal.created_at,
        updated_at=proposal.updated_at,
        topics=proposal.proposal_topics,
        options=proposal.options,
    )


def _validate_proposal_creation(body: schemas.ProposalCreate, org: Optional[models.Organization] = None):
    """Validate voting_method and options for proposal creation."""
    if body.voting_method == "ranked_choice":
        raise HTTPException(
            status_code=400,
            detail="Ranked-choice voting is planned for a future release",
        )
    # Check org allowed_voting_methods
    if org and org.settings:
        allowed = org.settings.get("allowed_voting_methods", ["binary", "approval"])
        if body.voting_method not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Voting method '{body.voting_method}' is not allowed by this organization",
            )
    if body.voting_method == "binary":
        if body.options:
            raise HTTPException(
                status_code=400,
                detail="Binary proposals must not have options",
            )
    elif body.voting_method == "approval":
        if len(body.options) < 2:
            raise HTTPException(
                status_code=400,
                detail="Approval proposals require at least 2 options",
            )
        if len(body.options) > 20:
            raise HTTPException(
                status_code=400,
                detail="Approval proposals may have at most 20 options",
            )
        seen_labels: set[str] = set()
        for opt in body.options:
            lower = opt.label.strip().lower()
            if lower in seen_labels:
                raise HTTPException(
                    status_code=400,
                    detail=f"Duplicate option label: {opt.label}",
                )
            seen_labels.add(lower)
    if body.num_winners != 1:
        raise HTTPException(
            status_code=400,
            detail="num_winners must be 1",
        )


def _create_proposal_options(db: Session, proposal_id: str, options: list[schemas.OptionCreate]):
    """Create ProposalOption rows for an approval proposal."""
    for i, opt in enumerate(options):
        db.add(models.ProposalOption(
            proposal_id=proposal_id,
            label=opt.label.strip(),
            description=opt.description,
            display_order=i,
        ))
    db.flush()


def _validate_and_update_options(
    db: Session,
    proposal: models.Proposal,
    options: list[schemas.OptionCreate],
):
    """Replace options on an approval proposal (draft/deliberation only)."""
    if proposal.status in ("voting", "passed", "failed", "withdrawn"):
        raise HTTPException(
            status_code=409,
            detail="Options cannot be edited after voting has started",
        )
    if len(options) < 2:
        raise HTTPException(status_code=400, detail="Approval proposals require at least 2 options")
    if len(options) > 20:
        raise HTTPException(status_code=400, detail="Approval proposals may have at most 20 options")
    seen_labels: set[str] = set()
    for opt in options:
        lower = opt.label.strip().lower()
        if lower in seen_labels:
            raise HTTPException(status_code=400, detail=f"Duplicate option label: {opt.label}")
        seen_labels.add(lower)
    # Delete existing options
    for existing_opt in list(proposal.options):
        db.delete(existing_opt)
    db.flush()
    _create_proposal_options(db, proposal.id, options)


@router.get("", response_model=list[schemas.ProposalOut])
def list_proposals(
    status_filter: Optional[str] = Query(None, alias="status"),
    topic_id: Optional[str] = Query(None),
    org_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(models.Proposal)
    if org_id:
        q = q.filter(models.Proposal.org_id == org_id)
    if status_filter:
        q = q.filter(models.Proposal.status == status_filter)
    if topic_id:
        q = q.join(models.ProposalTopic).filter(models.ProposalTopic.topic_id == topic_id)
    proposals = q.order_by(models.Proposal.created_at.desc()).all()
    return [_build_proposal_out(p) for p in proposals]


@router.post("", response_model=schemas.ProposalOut, status_code=status.HTTP_201_CREATED)
def create_proposal(
    body: schemas.ProposalCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    _validate_proposal_creation(body)

    for t in body.topics:
        if not db.get(models.Topic, t.topic_id):
            raise HTTPException(status_code=400, detail=f"Topic {t.topic_id} not found")

    proposal = models.Proposal(
        title=body.title,
        body=body.body,
        author_id=current_user.id,
        voting_method=body.voting_method,
        num_winners=body.num_winners,
        pass_threshold=body.pass_threshold,
        quorum_threshold=body.quorum_threshold,
    )
    db.add(proposal)
    db.flush()

    for t in body.topics:
        db.add(models.ProposalTopic(
            proposal_id=proposal.id, topic_id=t.topic_id, relevance=t.relevance
        ))
    db.flush()

    if body.voting_method == "approval" and body.options:
        _create_proposal_options(db, proposal.id, body.options)

    log_audit_event(
        db,
        action="proposal.created",
        target_type="proposal",
        target_id=proposal.id,
        actor_id=current_user.id,
        details={"title": proposal.title, "topic_ids": [t.topic_id for t in body.topics]},
        ip_address=request.client.host if request.client else None,
    )

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

    if proposal.status not in ("draft", "deliberation"):
        raise HTTPException(status_code=400, detail="Only draft or deliberation proposals can be edited")
    if proposal.author_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Not the proposal author")

    if body.title is not None:
        proposal.title = body.title
    if body.body is not None:
        proposal.body = body.body
    if body.topics is not None:
        for pt in list(proposal.proposal_topics):
            db.delete(pt)
        db.flush()
        for t in body.topics:
            if not db.get(models.Topic, t.topic_id):
                raise HTTPException(status_code=400, detail=f"Topic {t.topic_id} not found")
            db.add(models.ProposalTopic(
                proposal_id=proposal.id, topic_id=t.topic_id, relevance=t.relevance
            ))

    if body.options is not None:
        if proposal.voting_method != "approval":
            raise HTTPException(status_code=400, detail="Options can only be set on approval proposals")
        _validate_and_update_options(db, proposal, body.options)

    db.commit()
    db.refresh(proposal)
    return _build_proposal_out(proposal)


@router.post("/{proposal_id}/advance", response_model=schemas.ProposalOut)
def advance_proposal(
    proposal_id: str,
    body: schemas.AdvanceProposalRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    # Permissions: platform admin, org admin/owner, proposal author, or org
    # moderator (own proposals only). Moderators get 403 on others' proposals.
    proposal = _proposal_or_404(proposal_id, db)

    is_author = proposal.author_id == current_user.id
    is_platform_admin = current_user.is_admin
    is_org_admin_or_owner = False
    is_org_moderator = False
    if proposal.org_id:
        membership = db.query(models.OrgMembership).filter(
            models.OrgMembership.org_id == proposal.org_id,
            models.OrgMembership.user_id == current_user.id,
            models.OrgMembership.status == "active",
        ).first()
        if membership:
            if membership.role in ("admin", "owner"):
                is_org_admin_or_owner = True
            elif membership.role == "moderator":
                is_org_moderator = True

    if is_org_moderator and not is_author:
        raise HTTPException(status_code=403, detail="Moderators can only advance proposals they created")
    if not (is_author or is_platform_admin or is_org_admin_or_owner or is_org_moderator):
        raise HTTPException(status_code=403, detail="Not the proposal author or admin")

    next_status = STATUS_TRANSITIONS.get(proposal.status)
    if next_status is None:
        raise HTTPException(status_code=400, detail=f"Cannot advance from status '{proposal.status}'")

    old_status = proposal.status
    now = datetime.now(timezone.utc)

    if next_status == "deliberation":
        proposal.deliberation_start = now
    elif next_status == "voting":
        proposal.voting_start = now
        if body.voting_end:
            proposal.voting_end = body.voting_end
    elif next_status == "passed":
        tally = delegation_engine.compute_tally(proposal, db)
        if tally.threshold_met(proposal.pass_threshold) and tally.quorum_met(proposal.quorum_threshold):
            next_status = "passed"
        else:
            next_status = "failed"

    proposal.status = next_status
    db.flush()

    log_audit_event(
        db,
        action="proposal.status_changed",
        target_type="proposal",
        target_id=proposal.id,
        actor_id=current_user.id,
        details={"proposal_id": proposal.id, "old_status": old_status, "new_status": next_status},
        ip_address=request.client.host if request.client else None,
    )

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


@router.get("/{proposal_id}/vote-graph", response_model=schemas.VoteFlowGraph)
def get_vote_graph(
    proposal_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """
    Returns the delegation network for a specific proposal showing how every
    vote was cast or delegated, with privacy-aware node labelling.
    """
    proposal = _proposal_or_404(proposal_id, db)
    if proposal.status not in ("voting", "passed", "failed"):
        raise HTTPException(status_code=400, detail="Vote graph only available for voting/passed/failed proposals")

    # Build context for vote resolution
    ctx = delegation_engine._build_context(proposal, db)
    all_users = db.query(models.User).all()
    user_map = {u.id: u for u in all_users}
    proposal_topic_ids = [pt.topic_id for pt in proposal.proposal_topics]

    # Identify public delegates for this proposal's topics
    pub_delegate_ids: set[str] = set()
    for pt in proposal.proposal_topics:
        profiles = db.query(models.DelegateProfile).filter(
            models.DelegateProfile.topic_id == pt.topic_id,
            models.DelegateProfile.is_active.is_(True),
        ).all()
        for p in profiles:
            pub_delegate_ids.add(p.user_id)

    # Follow relationships of the current user (for visibility)
    following_ids: set[str] = set()
    for rel in db.query(models.FollowRelationship).filter(
        models.FollowRelationship.follower_id == current_user.id,
    ).all():
        following_ids.add(rel.followed_id)

    # Users who privately delegate TO the current user via a follow relationship
    # (not through a public delegate profile — those stay anonymous)
    private_follow_ids: set[str] = set()
    for rel in db.query(models.FollowRelationship).filter(
        models.FollowRelationship.followed_id == current_user.id,
        models.FollowRelationship.permission_level == "delegation_allowed",
    ).all():
        private_follow_ids.add(rel.follower_id)

    delegators_to_me: set[str] = set()
    for d in db.query(models.Delegation).filter(
        models.Delegation.delegate_id == current_user.id,
    ).all():
        # Only reveal name if they delegate via a private follow relationship
        if d.delegator_id in private_follow_ids:
            delegators_to_me.add(d.delegator_id)

    # Resolve every user's vote
    vote_results: dict[str, Optional[object]] = {}
    for uid in user_map:
        vote_results[uid] = resolve_vote_pure(uid, ctx)

    # Build delegation edges: for each user who delegates, find their delegate
    edges: list[schemas.VoteFlowEdge] = []
    delegator_counts: dict[str, int] = {}  # delegate_id -> count of delegators

    # Topic map for edge colours
    topic_map: dict[str, models.Topic] = {}
    for t in db.query(models.Topic).all():
        topic_map[t.id] = t

    for uid, result in vote_results.items():
        if result and not result.is_direct and result.delegate_chain:
            # This user's vote comes via delegation
            direct_delegate_id = result.delegate_chain[0]

            # Determine which topic matched this delegation
            user_delegations = ctx.all_delegations.get(uid, {})
            user_precedences = ctx.all_precedences.get(uid, {})
            from delegation_engine import find_delegate_pure
            matched_delegation = find_delegate_pure(uid, proposal_topic_ids, user_precedences, user_delegations)
            matched_topic_id = matched_delegation.topic_id if matched_delegation else None

            topic_name = None
            topic_color = "#95a5a6"
            if matched_topic_id and matched_topic_id in topic_map:
                topic_name = topic_map[matched_topic_id].name
                topic_color = topic_map[matched_topic_id].color
            elif matched_topic_id is None:
                topic_name = "Global"
                topic_color = "#95a5a6"

            # Privacy: only show edge if current user is involved, or delegate is public
            can_see_edge = (
                uid == current_user.id
                or direct_delegate_id == current_user.id
                or direct_delegate_id in pub_delegate_ids
            )
            if can_see_edge:
                edges.append(schemas.VoteFlowEdge(
                    source=uid,
                    target=direct_delegate_id,
                    topic=topic_name,
                    topic_color=topic_color,
                    is_active=True,
                ))

            delegator_counts[direct_delegate_id] = delegator_counts.get(direct_delegate_id, 0) + 1

            # Chain edges (A->B->C)
            if len(result.delegate_chain) > 1:
                for i in range(len(result.delegate_chain) - 1):
                    chain_src = result.delegate_chain[i]
                    chain_tgt = result.delegate_chain[i + 1]
                    can_see_chain = (
                        chain_src == current_user.id
                        or chain_tgt == current_user.id
                        or chain_tgt in pub_delegate_ids
                    )
                    if can_see_chain:
                        edges.append(schemas.VoteFlowEdge(
                            source=chain_src,
                            target=chain_tgt,
                            topic=topic_name,
                            topic_color=topic_color,
                            is_active=True,
                        ))

    # Build nodes
    nodes: list[schemas.VoteFlowNode] = []

    for uid, result in vote_results.items():
        user = user_map.get(uid)
        if not user:
            continue

        is_self = uid == current_user.id
        is_pub = uid in pub_delegate_ids
        is_followed = uid in following_ids
        is_delegator_to_me = uid in delegators_to_me

        # Privacy: show real name if self, public delegate, followed, or they privately delegate to you
        can_see_identity = is_self or is_pub or is_followed or is_delegator_to_me
        label = user.display_name if can_see_identity else ""

        if result is None:
            node_type = "non_voter"
            vote = None
            vote_source = None
            weight = 0
        elif result.is_direct:
            node_type = "direct_voter"
            vote = result.vote_value
            vote_source = "direct"
            weight = 1 + delegator_counts.get(uid, 0)
        else:
            node_type = "delegator"
            vote = result.vote_value
            vote_source = "delegation"
            weight = 1

        nodes.append(schemas.VoteFlowNode(
            id=uid,
            label=label,
            type=node_type,
            vote=vote,
            vote_source=vote_source,
            is_public_delegate=is_pub,
            is_current_user=is_self,
            delegator_count=delegator_counts.get(uid, 0),
            total_vote_weight=weight,
        ))

    # Build clusters
    clusters = {"yes": {"count": 0, "direct": 0, "delegated": 0},
                "no": {"count": 0, "direct": 0, "delegated": 0},
                "abstain": {"count": 0, "direct": 0, "delegated": 0},
                "not_cast": {"count": 0}}

    for uid, result in vote_results.items():
        if result is None:
            clusters["not_cast"]["count"] += 1
        else:
            bucket = clusters.get(result.vote_value, clusters["abstain"])
            bucket["count"] += 1
            if result.is_direct:
                bucket["direct"] += 1
            else:
                bucket["delegated"] += 1

    return schemas.VoteFlowGraph(
        proposal_id=proposal.id,
        proposal_title=proposal.title,
        total_eligible=len(all_users),
        nodes=nodes,
        edges=edges,
        clusters=schemas.VoteFlowClusters(**clusters),
    )
