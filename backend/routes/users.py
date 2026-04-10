from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import auth as auth_utils
import models
import schemas
from database import get_db
from delegation_engine import graph_store

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/{user_id}", response_model=schemas.UserOut)
def get_user(user_id: str, db: Session = Depends(get_db)):
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.get("/{user_id}/delegation-tree", response_model=schemas.DelegationGraph)
def delegation_tree(user_id: str, db: Session = Depends(get_db)):
    """
    Return the delegation neighbourhood (one hop in/out) for a given user,
    for use in the profile/tree visualisation.
    """
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    node_ids, edges = graph_store.get_neighborhood(user_id)

    nodes = []
    for uid in node_ids:
        u = db.get(models.User, uid)
        if u:
            nodes.append(
                schemas.GraphNode(
                    id=uid,
                    display_name=u.display_name,
                    username=u.username,
                    weight=graph_store.compute_voting_weight(uid),
                )
            )

    graph_edges = []
    for src, tgt, tid in edges:
        topic_name = None
        if tid:
            t = db.get(models.Topic, tid)
            topic_name = t.name if t else None
        # Look up chain_behavior
        d = (
            db.query(models.Delegation)
            .filter(
                models.Delegation.delegator_id == src,
                models.Delegation.delegate_id == tgt,
                models.Delegation.topic_id == tid,
            )
            .first()
        )
        graph_edges.append(
            schemas.GraphEdge(
                source=src,
                target=tgt,
                topic_id=tid,
                topic_name=topic_name,
                chain_behavior=d.chain_behavior if d else "accept_sub",
            )
        )

    return schemas.DelegationGraph(nodes=nodes, edges=graph_edges)


@router.get("/{user_id}/votes", response_model=list[schemas.VoteOut])
def user_votes(user_id: str, db: Session = Depends(get_db)):
    """Public voting record for a user."""
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return (
        db.query(models.Vote)
        .filter(models.Vote.user_id == user_id, models.Vote.is_direct.is_(True))
        .order_by(models.Vote.cast_at.desc())
        .all()
    )
