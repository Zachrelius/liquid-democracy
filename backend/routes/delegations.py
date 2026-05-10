"""
Phase 18 (D3 / B3) — Delegation routes are now mounted under
``/api/orgs/{org_slug}/delegations/*``. Org context is structural via the
URL prefix, not a query parameter / header / fallback. Every read filter
queries by ``org_id == org.id`` and every write constructor sets
``org_id`` (plus optional ``sub_org_id`` for the D4 sub-org-wide-global
case).

The frontend's API client must update accordingly (Frontend Agent F1/F3).
This is a clean break — there are no compat aliases at the old
``/api/delegations/*`` prefix.

Helpers exposed for cross-route reuse:
- ``activate_intents_for_follow(db, follower_id, followed_id, org_id)`` —
  called by ``routes/follows.py`` when a follow request is approved with
  ``delegation_allowed``. Per D5, the intent's ``org_id`` propagates into
  the activated ``Delegation`` row.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

import auth as auth_utils
import models
import schemas
from audit_utils import log_audit_event
from database import get_db
from delegation_engine import graph_store
from org_middleware import require_org_membership
from permissions import can_delegate_to, delegation_denied_message

router = APIRouter(prefix="/api/orgs", tags=["delegations"])

INTENT_EXPIRY_DAYS = 30


def _now():
    """Naive UTC datetime — SQLite strips timezone info on storage, so
    comparisons between stored and fresh values must both be naive."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _validate_sub_org_for_org(
    db: Session, org_id: str, sub_org_id: Optional[str]
) -> Optional[str]:
    """Phase 18 (D4): when a delegate request body carries ``sub_org_id``,
    verify it's actually a sub-org of ``org_id``. Returns the validated
    id (so the caller's mypy-ish flow stays clean) or raises 400 / 404.
    """
    if sub_org_id is None:
        return None
    sub = db.query(models.Organization).filter(
        models.Organization.id == sub_org_id,
        models.Organization.parent_org_id == org_id,
    ).first()
    if sub is None:
        raise HTTPException(
            status_code=400,
            detail="sub_org_id is not a sub-org of this organization",
        )
    return sub.id


def _validate_topic_for_org(
    db: Session, org_id: str, topic_id: Optional[str]
) -> None:
    """When a delegation specifies a topic, the topic MUST belong to the
    URL-prefix org. Cross-org topic delegations were the original Phase 4c
    leak; explicit guard prevents the foot-gun even if the FE misbehaves.
    """
    if topic_id is None:
        return
    topic = db.get(models.Topic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    if topic.org_id != org_id:
        raise HTTPException(
            status_code=400,
            detail="topic_id belongs to a different organization",
        )


# ---------------------------------------------------------------------------
# CRUD: list / upsert / revoke
# ---------------------------------------------------------------------------

@router.get(
    "/{org_slug}/delegations",
    response_model=list[schemas.DelegationOut],
)
def list_my_delegations(
    org_slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """Caller's delegations scoped to the URL-prefix org."""
    org_id = membership.org_id
    return (
        db.query(models.Delegation)
        .filter(
            models.Delegation.delegator_id == current_user.id,
            models.Delegation.org_id == org_id,
        )
        .all()
    )


@router.put(
    "/{org_slug}/delegations",
    response_model=schemas.DelegationOut,
    status_code=status.HTTP_200_OK,
)
def upsert_delegation(
    org_slug: str,
    body: schemas.DelegationUpsert,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    org_id = membership.org_id

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

    # Phase 18: topic + sub-org must belong to the URL-prefix org.
    _validate_topic_for_org(db, org_id, body.topic_id)
    sub_org_id = _validate_sub_org_for_org(db, org_id, body.sub_org_id)

    if not can_delegate_to(db, current_user.id, body.delegate_id, body.topic_id):
        raise HTTPException(
            status_code=403,
            detail=delegation_denied_message(body.topic_id),
        )

    if graph_store.would_create_cycle(
        current_user.id, body.delegate_id, body.topic_id, org_id=org_id,
    ):
        raise HTTPException(
            status_code=409,
            detail="This delegation would create a cycle in the delegation graph",
        )

    ip = request.client.host if request.client else None

    # Phase 18: uniqueness key is (delegator, org, sub_org, topic). Two
    # users in different orgs are distinct rows; "global within org X" is
    # distinct from "global within org Y."
    existing = (
        db.query(models.Delegation)
        .filter(
            models.Delegation.delegator_id == current_user.id,
            models.Delegation.org_id == org_id,
            models.Delegation.sub_org_id == sub_org_id,
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
                "org_id": org_id,
                "sub_org_id": sub_org_id,
                "chain_behavior": body.chain_behavior,
                "previous_delegate_id": prev_delegate_id,
                "previous_chain_behavior": prev_chain_behavior,
            },
            ip_address=ip,
        )
        db.commit()
        db.refresh(existing)
        graph_store.remove_delegation(current_user.id, body.topic_id, org_id=org_id)
        graph_store.add_delegation(
            current_user.id, body.delegate_id, body.topic_id, org_id=org_id,
        )
        return existing
    else:
        delegation = models.Delegation(
            delegator_id=current_user.id,
            delegate_id=body.delegate_id,
            org_id=org_id,
            sub_org_id=sub_org_id,
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
                "org_id": org_id,
                "sub_org_id": sub_org_id,
                "chain_behavior": body.chain_behavior,
            },
            ip_address=ip,
        )
        db.commit()
        db.refresh(delegation)
        graph_store.add_delegation(
            current_user.id, body.delegate_id, body.topic_id, org_id=org_id,
        )
        return delegation


@router.delete(
    "/{org_slug}/delegations/{topic_or_global}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_delegation(
    org_slug: str,
    topic_or_global: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """Revoke a delegation in this org.

    URL shape:
      ``/api/orgs/{slug}/delegations/{topic_or_global}``

    The ``topic_or_global`` segment is either an actual topic UUID or the
    literal string ``"global"`` to revoke the org-wide global delegation
    (``topic_id IS NULL``). Per Phase 18 D3, the org context is in the
    URL prefix so the legacy ``"global"`` literal is unambiguous (no
    cross-org collision possible).
    """
    org_id = membership.org_id
    resolved_topic_id: Optional[str] = (
        None if topic_or_global == "global" else topic_or_global
    )

    delegation = (
        db.query(models.Delegation)
        .filter(
            models.Delegation.delegator_id == current_user.id,
            models.Delegation.org_id == org_id,
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
        details={
            "previous_delegate_id": prev_delegate_id,
            "topic_id": resolved_topic_id,
            "org_id": org_id,
        },
        ip_address=request.client.host if request.client else None,
    )
    db.delete(delegation)
    db.commit()
    graph_store.remove_delegation(current_user.id, resolved_topic_id, org_id=org_id)


# ---------------------------------------------------------------------------
# Graph + personal network
# ---------------------------------------------------------------------------

@router.get(
    "/{org_slug}/delegations/graph",
    response_model=schemas.DelegationGraph,
)
def delegation_graph(
    org_slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    org_id = membership.org_id
    # Phase 18: get_neighborhood is now per-org partitioned (B2.1). Pass
    # org_id so we read from the right bucket — without it, the unscoped
    # legacy bucket is consulted and the user's edges look invisible
    # post-Phase-18b.
    node_ids, edges = graph_store.get_neighborhood(current_user.id, org_id=org_id)

    nodes = []
    for uid in node_ids:
        user = db.get(models.User, uid)
        if user:
            nodes.append(
                schemas.GraphNode(
                    id=uid,
                    display_name=user.display_name,
                    username=user.username,
                    weight=graph_store.compute_voting_weight(uid, org_id=org_id),
                    avatar_url=user.avatar_url,
                )
            )

    graph_edges = []
    for src, tgt, tid in edges:
        topic_name = None
        if tid:
            t = db.get(models.Topic, tid)
            # Phase 18: only surface edges whose topic is in this org.
            if t is None or t.org_id != org_id:
                continue
            topic_name = t.name
        graph_edges.append(
            schemas.GraphEdge(
                source=src,
                target=tgt,
                topic_id=tid,
                topic_name=topic_name,
                chain_behavior=_get_chain_behavior(src, tgt, tid, db, org_id),
            )
        )

    return schemas.DelegationGraph(nodes=nodes, edges=graph_edges)


@router.get(
    "/{org_slug}/delegations/network",
    response_model=schemas.PersonalDelegationNetwork,
)
def personal_delegation_network(
    org_slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """
    Returns the current user's personal delegation network — one hop out
    in both directions (who they delegate to and who delegates to them),
    scoped to the URL-prefix org.
    """
    org_id = membership.org_id

    # Outgoing delegations (user delegates TO these people) IN THIS ORG.
    outgoing = db.query(models.Delegation).filter(
        models.Delegation.delegator_id == current_user.id,
        models.Delegation.org_id == org_id,
    ).all()

    # Incoming delegations (these people delegate TO the user) IN THIS ORG.
    incoming = db.query(models.Delegation).filter(
        models.Delegation.delegate_id == current_user.id,
        models.Delegation.org_id == org_id,
    ).all()

    # Topic map (org-scoped — topics outside this org won't appear in
    # the rows above so this is a defensive narrowing).
    topics = {
        t.id: t for t in db.query(models.Topic)
        .filter(models.Topic.org_id == org_id)
        .all()
    }

    # Public delegate IDs
    pub_profiles = db.query(models.DelegateProfile).filter(
        models.DelegateProfile.is_active.is_(True),
    ).all()
    pub_delegate_ids = {p.user_id for p in pub_profiles}

    # Count delegators per user IN THIS ORG (how many people delegate to
    # them in the current org). Pre-Phase-18 this counted across all orgs
    # and was the source of inflated visualization counts.
    delegator_counts: dict[str, int] = {}
    org_delegations = db.query(models.Delegation).filter(
        models.Delegation.org_id == org_id,
    ).all()
    for d in org_delegations:
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
                avatar_url=user.avatar_url,
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
                avatar_url=user.avatar_url,
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
            avatar_url=current_user.avatar_url,
        ),
        nodes=nodes,
        edges=edges,
    )


def _get_chain_behavior(
    delegator_id: str,
    delegate_id: str,
    topic_id: Optional[str],
    db: Session,
    org_id: Optional[str] = None,
) -> str:
    q = (
        db.query(models.Delegation)
        .filter(
            models.Delegation.delegator_id == delegator_id,
            models.Delegation.delegate_id == delegate_id,
            models.Delegation.topic_id == topic_id,
        )
    )
    if org_id is not None:
        q = q.filter(models.Delegation.org_id == org_id)
    d = q.first()
    return d.chain_behavior if d else "accept_sub"


# ---------------------------------------------------------------------------
# Topic precedence — kept account-level (Phase 18: precedence is a
# user-side ordering preference, not org-scoped data; no leak shape).
# Mounted at the same /api/orgs/{slug}/delegations/precedence prefix for
# discoverability with the rest of the delegation surface.
# ---------------------------------------------------------------------------

@router.get(
    "/{org_slug}/delegations/precedence",
    response_model=list[schemas.TopicPrecedenceOut],
)
def get_topic_precedence(
    org_slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    return (
        db.query(models.TopicPrecedence)
        .filter(models.TopicPrecedence.user_id == current_user.id)
        .order_by(models.TopicPrecedence.priority)
        .all()
    )


@router.put(
    "/{org_slug}/delegations/precedence",
    response_model=list[schemas.TopicPrecedenceOut],
)
def set_topic_precedence(
    org_slug: str,
    body: schemas.TopicPrecedenceSet,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    org_id = membership.org_id
    # Phase 18 hardening: every topic in the precedence list must belong
    # to this org. (Previously unfiltered.)
    for tid in body.ordered_topic_ids:
        topic = db.get(models.Topic, tid)
        if not topic:
            raise HTTPException(status_code=404, detail=f"Topic {tid} not found")
        if topic.org_id != org_id:
            raise HTTPException(
                status_code=400,
                detail=f"Topic {tid} belongs to a different organization",
            )

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
                details={
                    "delegate_id": intent.delegate_id,
                    "topic_id": intent.topic_id,
                    "org_id": getattr(intent, "org_id", None),
                },
            )
    db.flush()


def activate_intents_for_follow(
    db: Session,
    follower_id: str,
    followed_id: str,
    org_id: Optional[str] = None,
) -> list[str]:
    """
    Phase 18 (D5 / B3): called when a follow request is approved with
    ``delegation_allowed`` permission. Activates pending non-expired
    intents from follower → followed.

    Org propagation: when ``org_id`` is provided (the caller knows the
    follow's org context), only intents in that org are activated. The
    activated ``Delegation`` row inherits the intent's ``org_id`` and
    ``sub_org_id`` (per D5 — intents already carry the scope they were
    requested in, so the activation is a faithful materialization).

    Backward-compat note: ``org_id=None`` activates intents regardless
    of org. This is the pre-Phase-18 behavior path; new call sites in
    routes/follows.py always pass the org_id explicitly. Once the
    backend rev-bumps in B1b, the intents themselves are NOT NULL on
    org_id and the follow approval routes filter by the follow's
    org_id, so the ``None`` codepath is effectively dead — kept only
    for safety during the deploy window.

    Returns list of activated intent IDs.
    """
    now = _now()
    q = db.query(models.DelegationIntent).filter(
        models.DelegationIntent.delegator_id == follower_id,
        models.DelegationIntent.delegate_id == followed_id,
        models.DelegationIntent.status == "pending",
        models.DelegationIntent.expires_at >= now,
    )
    if org_id is not None:
        q = q.filter(models.DelegationIntent.org_id == org_id)
    intents = q.all()

    activated = []
    for intent in intents:
        intent_org_id = getattr(intent, "org_id", None)
        intent_sub_org_id = getattr(intent, "sub_org_id", None)

        # Phase 18: existence check uses (delegator, org, sub_org, topic)
        # to mirror the new unique constraint shape on Delegation.
        existing = db.query(models.Delegation).filter(
            models.Delegation.delegator_id == intent.delegator_id,
            models.Delegation.org_id == intent_org_id,
            models.Delegation.sub_org_id == intent_sub_org_id,
            models.Delegation.topic_id == intent.topic_id,
        ).first()
        if existing:
            existing.delegate_id = intent.delegate_id
            existing.chain_behavior = intent.chain_behavior
        else:
            db.add(models.Delegation(
                delegator_id=intent.delegator_id,
                delegate_id=intent.delegate_id,
                org_id=intent_org_id,
                sub_org_id=intent_sub_org_id,
                topic_id=intent.topic_id,
                chain_behavior=intent.chain_behavior,
            ))
        db.flush()
        graph_store.add_delegation(
            intent.delegator_id,
            intent.delegate_id,
            intent.topic_id,
            org_id=intent_org_id,
        )

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
                "org_id": intent_org_id,
                "sub_org_id": intent_sub_org_id,
                "chain_behavior": intent.chain_behavior,
            },
        )
        activated.append(intent.id)

    return activated


@router.post(
    "/{org_slug}/delegations/request",
    response_model=schemas.DelegationRequestResult,
)
def request_delegation(
    org_slug: str,
    body: schemas.DelegationIntentCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """
    Smart delegation: creates directly if permitted, otherwise queues
    a follow_request + delegation_intent. Phase 18 — both rows carry
    the URL-prefix ``org_id`` (and the body's optional ``sub_org_id``).
    """
    org_id = membership.org_id

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

    _validate_topic_for_org(db, org_id, body.topic_id)
    sub_org_id = _validate_sub_org_for_org(db, org_id, body.sub_org_id)

    # ── Has permission already? Create directly ──────────────────────────
    if can_delegate_to(db, current_user.id, body.delegate_id, body.topic_id):
        if graph_store.would_create_cycle(
            current_user.id, body.delegate_id, body.topic_id, org_id=org_id,
        ):
            raise HTTPException(status_code=409, detail="Would create a delegation cycle")

        existing = db.query(models.Delegation).filter(
            models.Delegation.delegator_id == current_user.id,
            models.Delegation.org_id == org_id,
            models.Delegation.sub_org_id == sub_org_id,
            models.Delegation.topic_id == body.topic_id,
        ).first()
        if existing:
            existing.delegate_id = body.delegate_id
            existing.chain_behavior = body.chain_behavior
        else:
            existing = models.Delegation(
                delegator_id=current_user.id,
                delegate_id=body.delegate_id,
                org_id=org_id,
                sub_org_id=sub_org_id,
                topic_id=body.topic_id,
                chain_behavior=body.chain_behavior,
            )
            db.add(existing)
        db.flush()
        graph_store.add_delegation(
            current_user.id, body.delegate_id, body.topic_id, org_id=org_id,
        )
        log_audit_event(
            db, action="delegation.created",
            target_type="delegation", target_id=existing.id,
            actor_id=current_user.id,
            details={
                "delegate_id": body.delegate_id,
                "topic_id": body.topic_id,
                "org_id": org_id,
                "sub_org_id": sub_org_id,
            },
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

    # Phase 18: follow requests are now org-scoped — look up by (requester,
    # target, org). A user can have separate follow requests in different
    # orgs.
    freq = db.query(models.FollowRequest).filter(
        models.FollowRequest.requester_id == current_user.id,
        models.FollowRequest.target_id == body.delegate_id,
        models.FollowRequest.org_id == org_id,
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
                org_id=org_id,
            )
            db.add(freq)
        db.flush()

        log_audit_event(
            db, action="follow.requested",
            target_type="follow_request", target_id=freq.id,
            actor_id=current_user.id,
            details={"target_id": body.delegate_id, "org_id": org_id},
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
                org_id=org_id,
                permission_level=perm,
            ))
            db.flush()
            log_audit_event(
                db, action="follow.approved",
                target_type="follow_request", target_id=freq.id,
                actor_id=body.delegate_id,
                details={
                    "requester_id": current_user.id,
                    "permission_level": perm,
                    "org_id": org_id,
                    "auto": True,
                },
            )
            if perm == "delegation_allowed" and not graph_store.would_create_cycle(
                current_user.id, body.delegate_id, body.topic_id, org_id=org_id,
            ):
                d = models.Delegation(
                    delegator_id=current_user.id,
                    delegate_id=body.delegate_id,
                    org_id=org_id,
                    sub_org_id=sub_org_id,
                    topic_id=body.topic_id,
                    chain_behavior=body.chain_behavior,
                )
                db.add(d)
                db.flush()
                graph_store.add_delegation(
                    current_user.id, body.delegate_id, body.topic_id, org_id=org_id,
                )
                log_audit_event(
                    db, action="delegation.created",
                    target_type="delegation", target_id=d.id,
                    actor_id=current_user.id,
                    details={
                        "delegate_id": body.delegate_id,
                        "topic_id": body.topic_id,
                        "org_id": org_id,
                        "sub_org_id": sub_org_id,
                    },
                )
                db.commit()
                db.refresh(d)
                return schemas.DelegationRequestResult(
                    status="delegated",
                    message=f"Delegation to {delegate.display_name} created (auto-approved).",
                    delegation=schemas.DelegationOut.model_validate(d),
                )

    # Check for existing pending intent (org-scoped uniqueness).
    existing_intent = db.query(models.DelegationIntent).filter(
        models.DelegationIntent.delegator_id == current_user.id,
        models.DelegationIntent.delegate_id == body.delegate_id,
        models.DelegationIntent.org_id == org_id,
        models.DelegationIntent.sub_org_id == sub_org_id,
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
        org_id=org_id,
        sub_org_id=sub_org_id,
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
        details={
            "delegate_id": body.delegate_id,
            "topic_id": body.topic_id,
            "org_id": org_id,
            "sub_org_id": sub_org_id,
        },
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


@router.get(
    "/{org_slug}/delegations/intents",
    response_model=list[schemas.DelegationIntentOut],
)
def list_intents(
    org_slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    org_id = membership.org_id
    intents = db.query(models.DelegationIntent).filter(
        models.DelegationIntent.delegator_id == current_user.id,
        models.DelegationIntent.org_id == org_id,
    ).order_by(models.DelegationIntent.created_at.desc()).all()
    _expire_stale_intents(db, *[i for i in intents if i.status == "pending"])
    db.commit()
    return intents


@router.delete(
    "/{org_slug}/delegations/intents/{intent_id}",
    status_code=204,
)
def cancel_intent(
    org_slug: str,
    intent_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    org_id = membership.org_id
    intent = db.get(models.DelegationIntent, intent_id)
    if not intent:
        raise HTTPException(status_code=404, detail="Intent not found")
    if intent.delegator_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your intent")
    # Phase 18: an intent in org X can only be cancelled via the org X
    # URL prefix. Cross-org access becomes a 404 (looks like the intent
    # doesn't exist from this org's vantage).
    if intent.org_id is not None and intent.org_id != org_id:
        raise HTTPException(status_code=404, detail="Intent not found")
    if intent.status != "pending":
        raise HTTPException(status_code=409, detail=f"Intent is already {intent.status}")

    intent.status = "cancelled"
    db.flush()
    log_audit_event(
        db, action="delegation_intent.cancelled",
        target_type="delegation_intent", target_id=intent.id,
        actor_id=current_user.id,
        details={
            "delegate_id": intent.delegate_id,
            "topic_id": intent.topic_id,
            "org_id": getattr(intent, "org_id", None),
        },
    )
    db.commit()
