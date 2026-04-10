from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

import auth as auth_utils
import models
import schemas
from database import get_db
from delegation_engine import graph_store

router = APIRouter(prefix="/api/delegations", tags=["delegations"])


@router.get("", response_model=list[schemas.DelegationOut])
def list_my_delegations(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    delegations = (
        db.query(models.Delegation)
        .filter(models.Delegation.delegator_id == current_user.id)
        .all()
    )
    return delegations


@router.put("", response_model=schemas.DelegationOut, status_code=status.HTTP_200_OK)
def upsert_delegation(
    body: schemas.DelegationUpsert,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    if body.delegate_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delegate to yourself")

    delegate = db.get(models.User, body.delegate_id)
    if not delegate:
        raise HTTPException(status_code=404, detail="Delegate user not found")

    if body.topic_id:
        if not db.get(models.Topic, body.topic_id):
            raise HTTPException(status_code=404, detail="Topic not found")

    # Cycle check
    if graph_store.would_create_cycle(current_user.id, body.delegate_id, body.topic_id):
        raise HTTPException(
            status_code=409,
            detail="This delegation would create a cycle in the delegation graph",
        )

    # Upsert
    existing = (
        db.query(models.Delegation)
        .filter(
            models.Delegation.delegator_id == current_user.id,
            models.Delegation.topic_id == body.topic_id,
        )
        .first()
    )

    if existing:
        old_delegate_id = existing.delegate_id
        existing.delegate_id = body.delegate_id
        existing.chain_behavior = body.chain_behavior
        db.commit()
        db.refresh(existing)
        # Update graph: remove old edge, add new one
        graph_store.remove_delegation(current_user.id, body.topic_id)
        graph_store.add_delegation(current_user.id, body.delegate_id, body.topic_id)
        return existing
    else:
        delegation = models.Delegation(
            delegator_id=current_user.id,
            delegate_id=body.delegate_id,
            topic_id=body.topic_id,
            chain_behavior=body.chain_behavior,
        )
        db.add(delegation)
        db.commit()
        db.refresh(delegation)
        graph_store.add_delegation(current_user.id, body.delegate_id, body.topic_id)
        return delegation


@router.delete("/{topic_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_delegation(
    topic_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """
    topic_id can be an actual topic UUID or the literal string "global"
    to revoke the global (topic=None) delegation.
    """
    resolved_topic_id: Optional[str] = None if topic_id == "global" else topic_id

    delegation = (
        db.query(models.Delegation)
        .filter(
            models.Delegation.delegator_id == current_user.id,
            models.Delegation.topic_id == resolved_topic_id,
        )
        .first()
    )
    if not delegation:
        raise HTTPException(status_code=404, detail="Delegation not found")

    db.delete(delegation)
    db.commit()
    graph_store.remove_delegation(current_user.id, resolved_topic_id)


@router.get("/graph", response_model=schemas.DelegationGraph)
def delegation_graph(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    node_ids, edges = graph_store.get_neighborhood(current_user.id)

    nodes = []
    for uid in node_ids:
        user = db.get(models.User, uid)
        if user:
            nodes.append(
                schemas.GraphNode(
                    id=uid,
                    display_name=user.display_name,
                    username=user.username,
                    weight=graph_store.compute_voting_weight(uid),
                )
            )

    graph_edges = []
    for src, tgt, tid in edges:
        topic_name = None
        if tid:
            t = db.get(models.Topic, tid)
            topic_name = t.name if t else None
        graph_edges.append(
            schemas.GraphEdge(
                source=src,
                target=tgt,
                topic_id=tid,
                topic_name=topic_name,
                chain_behavior=_get_chain_behavior(src, tgt, tid, db),
            )
        )

    return schemas.DelegationGraph(nodes=nodes, edges=graph_edges)


def _get_chain_behavior(delegator_id: str, delegate_id: str, topic_id: Optional[str], db: Session) -> str:
    d = (
        db.query(models.Delegation)
        .filter(
            models.Delegation.delegator_id == delegator_id,
            models.Delegation.delegate_id == delegate_id,
            models.Delegation.topic_id == topic_id,
        )
        .first()
    )
    return d.chain_behavior if d else "accept_sub"


@router.put("/precedence", response_model=list[schemas.TopicPrecedenceOut])
def set_topic_precedence(
    body: schemas.TopicPrecedenceSet,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Set the topic precedence ordering for the current user."""
    # Validate all topic IDs
    for tid in body.ordered_topic_ids:
        if not db.get(models.Topic, tid):
            raise HTTPException(status_code=404, detail=f"Topic {tid} not found")

    # Delete existing precedences
    db.query(models.TopicPrecedence).filter(
        models.TopicPrecedence.user_id == current_user.id
    ).delete()
    db.flush()

    # Insert new ones
    for priority, tid in enumerate(body.ordered_topic_ids):
        db.add(
            models.TopicPrecedence(
                user_id=current_user.id,
                topic_id=tid,
                priority=priority,
            )
        )

    db.commit()

    rows = (
        db.query(models.TopicPrecedence)
        .filter(models.TopicPrecedence.user_id == current_user.id)
        .order_by(models.TopicPrecedence.priority)
        .all()
    )
    return rows
