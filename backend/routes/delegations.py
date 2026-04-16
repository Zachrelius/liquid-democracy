from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

import auth as auth_utils
import models
import schemas
from audit_utils import log_audit_event
from database import get_db
from delegation_engine import graph_store
from permissions import can_delegate_to, delegation_denied_message

router = APIRouter(prefix="/api/delegations", tags=["delegations"])

INTENT_EXPIRY_DAYS = 30


def _now():
    return datetime.now(timezone.utc)


@router.get("", response_model=list[schemas.DelegationOut])
def list_my_delegations(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    return (
        db.query(models.Delegation)
        .filter(models.Delegation.delegator_id == current_user.id)
        .all()
    )


@router.put("", response_model=schemas.DelegationOut, status_code=status.HTTP_200_OK)
def upsert_delegation(
    body: schemas.DelegationUpsert,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    if not current_user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email before creating delegations.",
        )

    if body.delegate_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delegate to yourself")

    delegate = db.get(models.User, body.delegate_id)
    if not delegate:
        raise HTTPException(status_code=404, detail="Delegate user not found")

    if body.topic_id:
        if not db.get(models.Topic, body.topic_id):
            raise HTTPException(status_code=404, detail="Topic not found")

    if not can_delegate_to(db, current_user.id, body.delegate_id, body.topic_id):
        raise HTTPException(
            status_code=403,
            detail=delegation_denied_message(body.topic_id),
        )

    if graph_store.would_create_cycle(current_user.id, body.delegate_id, body.topic_id):
        raise HTTPException(
            status_code=409,
            detail="This delegation would create a cycle in the delegation graph",
        )

    ip = request.client.host if request.client else None

    existing = (
        db.query(models.Delegation)
        .filter(
            models.Delegation.delegator_id == current_user.id,
            models.Delegation.topic_id == body.topic_id,
        )
        .first()
    )

    if existing:
        prev_delegate_id = existing.delegate_id
        prev_chain_behavior = existing.chain_behavior
        existing.delegate_id = body.delegate_id
        existing.chain_behavior = body.chain_behavior
        db.flush()
        log_audit_event(
            db,
            action="delegation.updated",
            target_type="delegation",
            target_id=existing.id,
            actor_id=current_user.id,
            details={
                "delegate_id": body.delegate_id,
                "topic_id": body.topic_id,
                "chain_behavior": body.chain_behavior,
                "previous_delegate_id": prev_delegate_id,
                "previous_chain_behavior": prev_chain_behavior,
            },
            ip_address=ip,
        )
        db.commit()
        db.refresh(existing)
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
        db.flush()
        log_audit_event(
            db,
            action="delegation.created",
            target_type="delegation",
            target_id=delegation.id,
            actor_id=current_user.id,
            details={
                "delegate_id": body.delegate_id,
                "topic_id": body.topic_id,
                "chain_behavior": body.chain_behavior,
            },
            ip_address=ip,
        )
        db.commit()
        db.refresh(delegation)
        graph_store.add_delegation(current_user.id, body.delegate_id, body.topic_id)
        return delegation


@router.delete("/{topic_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_delegation(
    topic_id: str,
    request: Request,
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

    prev_delegate_id = delegation.delegate_id
    delegation_id = delegation.id

    log_audit_event(
        db,
        action="delegation.revoked",
        target_type="delegation",
        target_id=delegation_id,
        actor_id=current_user.id,
        details={"previous_delegate_id": prev_delegate_id, "topic_id": resolved_topic_id},
        ip_address=request.client.host if request.client else None,
    )
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


@router.get("/network", response_model=schemas.PersonalDelegationNetwork)
def personal_delegation_network(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """
    Returns the current user's personal delegation network — one hop out
    in both directions (who they delegate to and who delegates to them).
    """
    # Outgoing delegations (user delegates TO these people)
    outgoing = db.query(models.Delegation).filter(
        models.Delegation.delegator_id == current_user.id,
    ).all()

    # Incoming delegations (these people delegate TO the user)
    incoming = db.query(models.Delegation).filter(
        models.Delegation.delegate_id == current_user.id,
    ).all()

    # Topic map
    topics = {t.id: t for t in db.query(models.Topic).all()}

    # Public delegate IDs
    pub_profiles = db.query(models.DelegateProfile).filter(
        models.DelegateProfile.is_active.is_(True),
    ).all()
    pub_delegate_ids = {p.user_id for p in pub_profiles}

    # Count delegators per user (how many people delegate to them total)
    delegator_counts: dict[str, int] = {}
    all_delegations = db.query(models.Delegation).all()
    for d in all_delegations:
        delegator_counts[d.delegate_id] = delegator_counts.get(d.delegate_id, 0) + 1

    # Build node and edge structures
    nodes: list[schemas.PersonalNetworkNode] = []
    edges: list[schemas.PersonalNetworkEdge] = []
    seen_nodes: set[str] = set()

    # Group outgoing by delegate
    outgoing_by_delegate: dict[str, list[models.Delegation]] = {}
    for d in outgoing:
        outgoing_by_delegate.setdefault(d.delegate_id, []).append(d)

    for delegate_id, dels in outgoing_by_delegate.items():
        user = db.get(models.User, delegate_id)
        if not user:
            continue
        topic_names = []
        edge_topics = []
        for d in dels:
            if d.topic_id and d.topic_id in topics:
                t = topics[d.topic_id]
                topic_names.append(t.name)
                edge_topics.append(schemas.PersonalNetworkEdgeTopic(name=t.name, color=t.color))
            else:
                topic_names.append("Global")
                edge_topics.append(schemas.PersonalNetworkEdgeTopic(name="Global", color="#95a5a6"))

        if delegate_id not in seen_nodes:
            nodes.append(schemas.PersonalNetworkNode(
                id=delegate_id,
                label=user.display_name,
                relationship="delegate",
                topics=topic_names,
                is_public_delegate=delegate_id in pub_delegate_ids,
                total_delegators=delegator_counts.get(delegate_id, 0),
            ))
            seen_nodes.add(delegate_id)

        edges.append(schemas.PersonalNetworkEdge(
            source=current_user.id,
            target=delegate_id,
            topics=edge_topics,
            direction="outgoing",
        ))

    # Group incoming by delegator
    incoming_by_delegator: dict[str, list[models.Delegation]] = {}
    for d in incoming:
        incoming_by_delegator.setdefault(d.delegator_id, []).append(d)

    for delegator_id, dels in incoming_by_delegator.items():
        user = db.get(models.User, delegator_id)
        if not user:
            continue
        topic_names = []
        edge_topics = []
        for d in dels:
            if d.topic_id and d.topic_id in topics:
                t = topics[d.topic_id]
                topic_names.append(t.name)
                edge_topics.append(schemas.PersonalNetworkEdgeTopic(name=t.name, color=t.color))
            else:
                topic_names.append("Global")
                edge_topics.append(schemas.PersonalNetworkEdgeTopic(name="Global", color="#95a5a6"))

        if delegator_id not in seen_nodes:
            nodes.append(schemas.PersonalNetworkNode(
                id=delegator_id,
                label=user.display_name,
                relationship="delegator",
                topics=topic_names,
                is_public_delegate=delegator_id in pub_delegate_ids,
                total_delegators=delegator_counts.get(delegator_id, 0),
            ))
            seen_nodes.add(delegator_id)

        edges.append(schemas.PersonalNetworkEdge(
            source=delegator_id,
            target=current_user.id,
            topics=edge_topics,
            direction="incoming",
        ))

    return schemas.PersonalDelegationNetwork(
        center=schemas.PersonalNetworkCenter(
            id=current_user.id,
            label=current_user.display_name,
            delegating_to=len(outgoing_by_delegate),
            delegated_from=len(incoming_by_delegator),
        ),
        nodes=nodes,
        edges=edges,
    )


def _get_chain_behavior(
    delegator_id: str, delegate_id: str, topic_id: Optional[str], db: Session
) -> str:
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


@router.get("/precedence", response_model=list[schemas.TopicPrecedenceOut])
def get_topic_precedence(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    return (
        db.query(models.TopicPrecedence)
        .filter(models.TopicPrecedence.user_id == current_user.id)
        .order_by(models.TopicPrecedence.priority)
        .all()
    )


@router.put("/precedence", response_model=list[schemas.TopicPrecedenceOut])
def set_topic_precedence(
    body: schemas.TopicPrecedenceSet,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    for tid in body.ordered_topic_ids:
        if not db.get(models.Topic, tid):
            raise HTTPException(status_code=404, detail=f"Topic {tid} not found")

    db.query(models.TopicPrecedence).filter(
        models.TopicPrecedence.user_id == current_user.id
    ).delete()
    db.flush()

    for priority, tid in enumerate(body.ordered_topic_ids):
        db.add(
            models.TopicPrecedence(
                user_id=current_user.id,
                topic_id=tid,
                priority=priority,
            )
        )

    db.commit()

    return (
        db.query(models.TopicPrecedence)
        .filter(models.TopicPrecedence.user_id == current_user.id)
        .order_by(models.TopicPrecedence.priority)
        .all()
    )


# ---------------------------------------------------------------------------
# Delegation intents
# ---------------------------------------------------------------------------

def _expire_stale_intents(db: Session, *intents: models.DelegationIntent) -> None:
    """Lazy expiration — mark as expired if past expires_at."""
    now = _now()
    for intent in intents:
        if intent.status == "pending" and intent.expires_at < now:
            intent.status = "expired"
            log_audit_event(
                db, action="delegation_intent.expired",
                target_type="delegation_intent", target_id=intent.id,
                actor_id=intent.delegator_id,
                details={"delegate_id": intent.delegate_id, "topic_id": intent.topic_id},
            )
    db.flush()


def activate_intents_for_follow(db: Session, follower_id: str, followed_id: str) -> list[str]:
    """
    Called when a follow request is approved with delegation_allowed.
    Activates all pending non-expired intents from follower -> followed.
    Returns list of activated intent IDs.
    """
    now = _now()
    intents = db.query(models.DelegationIntent).filter(
        models.DelegationIntent.delegator_id == follower_id,
        models.DelegationIntent.delegate_id == followed_id,
        models.DelegationIntent.status == "pending",
        models.DelegationIntent.expires_at >= now,
    ).all()

    activated = []
    for intent in intents:
        existing = db.query(models.Delegation).filter(
            models.Delegation.delegator_id == intent.delegator_id,
            models.Delegation.topic_id == intent.topic_id,
        ).first()
        if existing:
            existing.delegate_id = intent.delegate_id
            existing.chain_behavior = intent.chain_behavior
        else:
            db.add(models.Delegation(
                delegator_id=intent.delegator_id,
                delegate_id=intent.delegate_id,
                topic_id=intent.topic_id,
                chain_behavior=intent.chain_behavior,
            ))
        db.flush()
        graph_store.add_delegation(intent.delegator_id, intent.delegate_id, intent.topic_id)

        intent.status = "activated"
        intent.activated_at = now
        db.flush()

        log_audit_event(
            db, action="delegation_intent.activated",
            target_type="delegation_intent", target_id=intent.id,
            actor_id=intent.delegator_id,
            details={
                "delegate_id": intent.delegate_id,
                "topic_id": intent.topic_id,
                "chain_behavior": intent.chain_behavior,
            },
        )
        activated.append(intent.id)

    return activated


@router.post("/request", response_model=schemas.DelegationRequestResult)
def request_delegation(
    body: schemas.DelegationIntentCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """
    Smart delegation: creates directly if permitted, otherwise queues
    a follow_request + delegation_intent.
    """
    if not current_user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email before creating delegations.",
        )

    if body.delegate_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delegate to yourself")

    delegate = db.get(models.User, body.delegate_id)
    if not delegate:
        raise HTTPException(status_code=404, detail="Delegate user not found")

    if body.topic_id and not db.get(models.Topic, body.topic_id):
        raise HTTPException(status_code=404, detail="Topic not found")

    # ── Has permission already? Create directly ──────────────────────────
    if can_delegate_to(db, current_user.id, body.delegate_id, body.topic_id):
        if graph_store.would_create_cycle(current_user.id, body.delegate_id, body.topic_id):
            raise HTTPException(status_code=409, detail="Would create a delegation cycle")

        existing = db.query(models.Delegation).filter(
            models.Delegation.delegator_id == current_user.id,
            models.Delegation.topic_id == body.topic_id,
        ).first()
        if existing:
            existing.delegate_id = body.delegate_id
            existing.chain_behavior = body.chain_behavior
        else:
            existing = models.Delegation(
                delegator_id=current_user.id,
                delegate_id=body.delegate_id,
                topic_id=body.topic_id,
                chain_behavior=body.chain_behavior,
            )
            db.add(existing)
        db.flush()
        graph_store.add_delegation(current_user.id, body.delegate_id, body.topic_id)
        log_audit_event(
            db, action="delegation.created",
            target_type="delegation", target_id=existing.id,
            actor_id=current_user.id,
            details={"delegate_id": body.delegate_id, "topic_id": body.topic_id},
            ip_address=request.client.host if request.client else None,
        )
        db.commit()
        db.refresh(existing)
        return schemas.DelegationRequestResult(
            status="delegated",
            message=f"Delegation to {delegate.display_name} created.",
            delegation=schemas.DelegationOut.model_validate(existing),
        )

    # ── No permission — create follow request + intent ───────────────────
    ip = request.client.host if request.client else None

    freq = db.query(models.FollowRequest).filter(
        models.FollowRequest.requester_id == current_user.id,
        models.FollowRequest.target_id == body.delegate_id,
    ).first()

    if freq and freq.status == "approved":
        raise HTTPException(
            status_code=403,
            detail="You follow this user but don't have delegation permission. "
                   "Ask them to upgrade your permission level.",
        )

    if not freq or freq.status == "denied":
        if freq and freq.status == "denied":
            freq.status = "pending"
            freq.message = None
            freq.requested_at = _now()
            freq.responded_at = None
            freq.permission_level = None
        else:
            freq = models.FollowRequest(
                requester_id=current_user.id,
                target_id=body.delegate_id,
            )
            db.add(freq)
        db.flush()

        log_audit_event(
            db, action="follow.requested",
            target_type="follow_request", target_id=freq.id,
            actor_id=current_user.id,
            details={"target_id": body.delegate_id},
            ip_address=ip,
        )

        # Auto-approve check
        policy = delegate.default_follow_policy
        if policy in ("auto_approve_view", "auto_approve_delegate"):
            perm = "delegation_allowed" if policy == "auto_approve_delegate" else "view_only"
            freq.status = "approved"
            freq.permission_level = perm
            freq.responded_at = _now()
            db.flush()
            db.add(models.FollowRelationship(
                follower_id=current_user.id,
                followed_id=body.delegate_id,
                permission_level=perm,
            ))
            db.flush()
            log_audit_event(
                db, action="follow.approved",
                target_type="follow_request", target_id=freq.id,
                actor_id=body.delegate_id,
                details={"requester_id": current_user.id, "permission_level": perm, "auto": True},
            )
            if perm == "delegation_allowed" and not graph_store.would_create_cycle(
                current_user.id, body.delegate_id, body.topic_id
            ):
                d = models.Delegation(
                    delegator_id=current_user.id,
                    delegate_id=body.delegate_id,
                    topic_id=body.topic_id,
                    chain_behavior=body.chain_behavior,
                )
                db.add(d)
                db.flush()
                graph_store.add_delegation(current_user.id, body.delegate_id, body.topic_id)
                log_audit_event(
                    db, action="delegation.created",
                    target_type="delegation", target_id=d.id,
                    actor_id=current_user.id,
                    details={"delegate_id": body.delegate_id, "topic_id": body.topic_id},
                )
                db.commit()
                db.refresh(d)
                return schemas.DelegationRequestResult(
                    status="delegated",
                    message=f"Delegation to {delegate.display_name} created (auto-approved).",
                    delegation=schemas.DelegationOut.model_validate(d),
                )

    # Check for existing pending intent
    existing_intent = db.query(models.DelegationIntent).filter(
        models.DelegationIntent.delegator_id == current_user.id,
        models.DelegationIntent.delegate_id == body.delegate_id,
        models.DelegationIntent.topic_id == body.topic_id,
        models.DelegationIntent.status == "pending",
    ).first()
    if existing_intent:
        _expire_stale_intents(db, existing_intent)
        if existing_intent.status == "pending":
            raise HTTPException(status_code=409, detail="Delegation intent already pending")

    intent = models.DelegationIntent(
        delegator_id=current_user.id,
        delegate_id=body.delegate_id,
        topic_id=body.topic_id,
        chain_behavior=body.chain_behavior,
        follow_request_id=freq.id,
        status="pending",
        expires_at=_now() + timedelta(days=INTENT_EXPIRY_DAYS),
    )
    db.add(intent)
    db.flush()
    log_audit_event(
        db, action="delegation_intent.created",
        target_type="delegation_intent", target_id=intent.id,
        actor_id=current_user.id,
        details={"delegate_id": body.delegate_id, "topic_id": body.topic_id},
        ip_address=ip,
    )
    db.commit()
    db.refresh(intent)
    return schemas.DelegationRequestResult(
        status="requested",
        message=f"Follow request sent to {delegate.display_name}. "
                "Delegation will activate automatically if approved within 30 days.",
        intent=schemas.DelegationIntentOut.model_validate(intent),
    )


@router.get("/intents", response_model=list[schemas.DelegationIntentOut])
def list_intents(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    intents = db.query(models.DelegationIntent).filter(
        models.DelegationIntent.delegator_id == current_user.id,
    ).order_by(models.DelegationIntent.created_at.desc()).all()
    _expire_stale_intents(db, *[i for i in intents if i.status == "pending"])
    db.commit()
    return intents


@router.delete("/intents/{intent_id}", status_code=204)
def cancel_intent(
    intent_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    intent = db.get(models.DelegationIntent, intent_id)
    if not intent:
        raise HTTPException(status_code=404, detail="Intent not found")
    if intent.delegator_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your intent")
    if intent.status != "pending":
        raise HTTPException(status_code=409, detail=f"Intent is already {intent.status}")

    intent.status = "cancelled"
    db.flush()
    log_audit_event(
        db, action="delegation_intent.cancelled",
        target_type="delegation_intent", target_id=intent.id,
        actor_id=current_user.id,
        details={"delegate_id": intent.delegate_id, "topic_id": intent.topic_id},
    )
    db.commit()
