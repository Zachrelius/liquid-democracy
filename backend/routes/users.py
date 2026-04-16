from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

import auth as auth_utils
import models
import schemas
from database import get_db
from delegation_engine import graph_store
from permissions import can_see_votes, public_delegate_topic_ids

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/search", response_model=list[schemas.UserSearchResultWithContext])
def search_users(
    q: str = Query("", description="Search by display name or username"),
    topic_id: Optional[str] = Query(None, description="Filter to public delegates for topic"),
    limit: int = Query(20, le=100),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Search users by name/username with follow/delegate context."""
    query = db.query(models.User).filter(models.User.id != current_user.id)
    if q:
        like = f"%{q}%"
        query = query.filter(
            models.User.display_name.ilike(like) | models.User.username.ilike(like)
        )
    if topic_id:
        query = query.join(
            models.DelegateProfile,
            models.DelegateProfile.user_id == models.User.id,
        ).filter(
            models.DelegateProfile.topic_id == topic_id,
            models.DelegateProfile.is_active.is_(True),
        )
    users = query.order_by(models.User.display_name).limit(limit).all()
    return [_enrich_user_result(db, u, current_user.id) for u in users]


def _enrich_user_result(db: Session, user: models.User, viewer_id: str):
    # Active delegate profiles
    profiles = [p for p in user.delegate_profiles if p.is_active]

    # Follow relationship
    rel = db.query(models.FollowRelationship).filter(
        models.FollowRelationship.follower_id == viewer_id,
        models.FollowRelationship.followed_id == user.id,
    ).first()

    # Pending follow request
    pending_req = db.query(models.FollowRequest).filter(
        models.FollowRequest.requester_id == viewer_id,
        models.FollowRequest.target_id == user.id,
        models.FollowRequest.status == "pending",
    ).first()

    # Pending delegation intent
    has_intent = db.query(models.DelegationIntent).filter(
        models.DelegationIntent.delegator_id == viewer_id,
        models.DelegationIntent.delegate_id == user.id,
        models.DelegationIntent.status == "pending",
    ).first() is not None

    follow_status = None
    follow_permission = None
    rel_id = None
    if rel:
        follow_status = "following"
        follow_permission = rel.permission_level
        rel_id = rel.id
    elif pending_req:
        follow_status = "pending"

    return schemas.UserSearchResultWithContext(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        delegate_profiles=[schemas.DelegateProfileOut.model_validate(p) for p in profiles],
        follow_status=follow_status,
        follow_permission=follow_permission,
        follow_relationship_id=rel_id,
        pending_request_id=pending_req.id if pending_req else None,
        has_pending_intent=has_intent,
    )


# Keep backward-compatible GET /api/users?q= endpoint too
@router.get("", response_model=list[schemas.UserSearchResultWithContext])
def search_users_compat(
    q: str = Query("", description="Search by display name or username"),
    limit: int = Query(20, le=100),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    return search_users(q=q, limit=limit, db=db, current_user=current_user)


@router.get("/{user_id}/profile", response_model=schemas.PublicProfileOut)
def get_user_profile(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(auth_utils.get_optional_user),
):
    """
    Public profile. Shows delegate registrations and vote history only for
    public delegate topics.
    """
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    viewer_id = current_user.id if current_user else None
    active_profiles = [p for p in user.delegate_profiles if p.is_active]
    pub_topic_ids = {p.topic_id for p in active_profiles}

    # Collect visible votes (only those on public delegate topics, unless viewer = self)
    votes_out: list[schemas.VoteVisibility] = []
    direct_votes = db.query(models.Vote).filter(
        models.Vote.user_id == user_id,
        models.Vote.is_direct.is_(True),
    ).order_by(models.Vote.cast_at.desc()).all()

    for v in direct_votes:
        proposal = db.get(models.Proposal, v.proposal_id)
        proposal_topics = [pt.topic_id for pt in (proposal.proposal_topics if proposal else [])]
        visible = can_see_votes(db, viewer_id, user_id, proposal_topics)
        if visible:
            votes_out.append(schemas.VoteVisibility(
                id=v.id,
                proposal_id=v.proposal_id,
                proposal_title=proposal.title if proposal else None,
                vote_value=v.vote_value,
                is_direct=v.is_direct,
                cast_at=v.cast_at,
                visible=True,
            ))
        elif pub_topic_ids.intersection(proposal_topics):
            # Public delegate topic — always show
            votes_out.append(schemas.VoteVisibility(
                id=v.id,
                proposal_id=v.proposal_id,
                proposal_title=proposal.title if proposal else None,
                vote_value=v.vote_value,
                is_direct=v.is_direct,
                cast_at=v.cast_at,
                visible=True,
            ))
        else:
            # Hidden vote — include with visible=False so frontend can show privacy message
            votes_out.append(schemas.VoteVisibility(
                id=v.id,
                proposal_id=v.proposal_id,
                proposal_title=proposal.title if proposal else None,
                vote_value=None,
                is_direct=v.is_direct,
                cast_at=v.cast_at,
                visible=False,
            ))

    return schemas.PublicProfileOut(
        user=schemas.UserSearchResult(
            id=user.id, username=user.username, display_name=user.display_name
        ),
        delegate_profiles=[schemas.DelegateProfileOut.model_validate(p) for p in active_profiles],
        votes=votes_out,
    )


@router.get("/{user_id}", response_model=schemas.UserOut)
def get_user(user_id: str, db: Session = Depends(get_db)):
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.get("/{user_id}/delegation-tree", response_model=schemas.DelegationGraph)
def delegation_tree(user_id: str, db: Session = Depends(get_db)):
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    node_ids, edges = graph_store.get_neighborhood(user_id)

    nodes = []
    for uid in node_ids:
        u = db.get(models.User, uid)
        if u:
            nodes.append(schemas.GraphNode(
                id=uid,
                display_name=u.display_name,
                username=u.username,
                weight=graph_store.compute_voting_weight(uid),
            ))

    graph_edges = []
    for src, tgt, tid in edges:
        topic_name = None
        if tid:
            t = db.get(models.Topic, tid)
            topic_name = t.name if t else None
        d = db.query(models.Delegation).filter(
            models.Delegation.delegator_id == src,
            models.Delegation.delegate_id == tgt,
            models.Delegation.topic_id == tid,
        ).first()
        graph_edges.append(schemas.GraphEdge(
            source=src, target=tgt,
            topic_id=tid, topic_name=topic_name,
            chain_behavior=d.chain_behavior if d else "accept_sub",
        ))

    return schemas.DelegationGraph(nodes=nodes, edges=graph_edges)


@router.get("/{user_id}/votes", response_model=list[schemas.VoteVisibility])
def user_votes(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(auth_utils.get_optional_user),
):
    """
    Voting record with permission-aware visibility.
    Returns votes the requester can see; others are returned with visible=False
    and vote_value=None.
    """
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    viewer_id = current_user.id if current_user else None
    pub_topic_ids = public_delegate_topic_ids(db, user_id)

    direct_votes = db.query(models.Vote).filter(
        models.Vote.user_id == user_id,
        models.Vote.is_direct.is_(True),
    ).order_by(models.Vote.cast_at.desc()).all()

    result = []
    for v in direct_votes:
        proposal = db.get(models.Proposal, v.proposal_id)
        proposal_topics = [pt.topic_id for pt in (proposal.proposal_topics if proposal else [])]

        # Visible if: self, follower, OR public delegate topic
        visible = (
            can_see_votes(db, viewer_id, user_id, proposal_topics)
            or bool(pub_topic_ids.intersection(proposal_topics))
        )
        result.append(schemas.VoteVisibility(
            id=v.id,
            proposal_id=v.proposal_id,
            proposal_title=proposal.title if proposal else None,
            vote_value=v.vote_value if visible else None,
            is_direct=v.is_direct if visible else None,
            cast_at=v.cast_at if visible else None,
            visible=visible,
        ))

    return result
