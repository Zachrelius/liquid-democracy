from datetime import datetime
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


# ---------------------------------------------------------------------------
# Access-log helpers (Phase 7.5)
# ---------------------------------------------------------------------------

# Indirect access-log actions: actions that, when performed by a user OTHER
# than the affected user, are surfaced in the affected user's access history.
# Each is mapped through `_filter_indirect_event` to decide whether a given
# row touches a specific user.
_INDIRECT_ACCESS_ACTIONS = (
    "admin.audit_ballot_viewed",
    "admin.delegation_graph_viewed",
    "admin.user_list_viewed",
)

# Direct access-log actions: target_type='user' AND target_id == user_id.
# Currently empty — `profile.viewed` etc. don't exist as audit events yet,
# but this set is the extension point for adding them later.
_DIRECT_ACCESS_ACTIONS: tuple[str, ...] = ()

# Human-readable action labels for the user-facing view.
_ACTION_TYPE_LABELS = {
    "admin.audit_ballot_viewed": "Viewed your ballot",
    "admin.delegation_graph_viewed": "Viewed system delegation graph",
    "admin.user_list_viewed": "Viewed full user list",
}


def _accessor_role(action: str) -> str:
    """Map an audit action to a human-readable role for the access-log."""
    if action.startswith("admin."):
        return "Platform admin"
    # Placeholder for future org-admin actions; none exist yet.
    if action.startswith("org_admin."):
        return "Org admin"
    return "User"


def _filter_indirect_event(entry: models.AuditLog, user_id: str) -> bool:
    """
    Return True if `entry` (an indirect-action audit row not authored by
    user_id) actually represents access to user_id's data.

    This is the Python-side JSON filter: querying the SQLAlchemy `JSON`
    column with cross-backend portability (SQLite vs PostgreSQL) is fragile,
    so we coarse-query by action+actor at the SQL layer and refine here.
    """
    if entry.action == "admin.audit_ballot_viewed":
        details = entry.details or {}
        return details.get("viewed_actor_id") == user_id
    if entry.action == "admin.delegation_graph_viewed":
        # The system graph touches every user's delegation data; surface to
        # all users in their access log.
        return True
    if entry.action == "admin.user_list_viewed":
        # The user list includes every user; surface to all users.
        return True
    return False


def get_user_access_log(
    user_id: str,
    db: Session,
    *,
    limit: int = 50,
    offset: int = 0,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
) -> list[schemas.AccessLogEntry]:
    """
    Build the access-log view for a single user.

    Trade-off: we apply the JSON-payload filter Python-side rather than at
    the SQL layer because SQLAlchemy JSON-path support diverges between
    SQLite and PostgreSQL. To keep the result correct under
    offset/limit pagination, we over-query the DB (a coarser bound) and then
    apply the filter + slice in Python. This is fine at audit-log scale; if
    the table grows past ~10^5 rows per user it should be revisited.
    """
    # Coarse over-query bound — we filter in Python afterward, so this must
    # be loose enough that the post-filter slice gets a full page when
    # possible without scanning the entire table.
    coarse_limit = min(1000, max(limit * 5 + offset * 5, 200))

    # ----- Direct events: target_type='user' AND target_id == user_id -----
    direct_rows: list[models.AuditLog] = []
    if _DIRECT_ACCESS_ACTIONS:
        dq = db.query(models.AuditLog).filter(
            models.AuditLog.target_type == "user",
            models.AuditLog.target_id == user_id,
            models.AuditLog.action.in_(_DIRECT_ACCESS_ACTIONS),
            models.AuditLog.actor_id != user_id,
        )
        if since:
            dq = dq.filter(models.AuditLog.timestamp >= since)
        if until:
            dq = dq.filter(models.AuditLog.timestamp <= until)
        direct_rows = (
            dq.order_by(models.AuditLog.timestamp.desc()).limit(coarse_limit).all()
        )

    # ----- Indirect events: action in indirect set AND actor != user -----
    iq = db.query(models.AuditLog).filter(
        models.AuditLog.action.in_(_INDIRECT_ACCESS_ACTIONS),
        models.AuditLog.actor_id != user_id,
    )
    if since:
        iq = iq.filter(models.AuditLog.timestamp >= since)
    if until:
        iq = iq.filter(models.AuditLog.timestamp <= until)
    indirect_rows = (
        iq.order_by(models.AuditLog.timestamp.desc()).limit(coarse_limit).all()
    )

    # Python-side filter on JSON details for indirect rows.
    filtered_indirect = [
        r for r in indirect_rows if _filter_indirect_event(r, user_id)
    ]

    combined = direct_rows + filtered_indirect
    combined.sort(key=lambda r: r.timestamp, reverse=True)
    page = combined[offset : offset + limit]

    # Resolve accessor display names with a single-batch lookup.
    accessor_ids = {r.actor_id for r in page if r.actor_id}
    name_map: dict[str, str] = {}
    if accessor_ids:
        for u in db.query(models.User).filter(models.User.id.in_(accessor_ids)).all():
            name_map[u.id] = u.display_name or u.username

    out: list[schemas.AccessLogEntry] = []
    for r in page:
        details = r.details or {}
        accessor_name = (
            name_map.get(r.actor_id) if r.actor_id else None
        ) or "Unknown"
        out.append(
            schemas.AccessLogEntry(
                timestamp=r.timestamp,
                accessor_id=r.actor_id,
                accessor_display_name=accessor_name,
                accessor_role=_accessor_role(r.action),
                action_type=_ACTION_TYPE_LABELS.get(r.action, r.action),
                reason=details.get("reason"),
                ip_address=r.ip_address,
            )
        )
    return out


@router.get("/me/access-log", response_model=list[schemas.AccessLogEntry])
def my_access_log(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    since: Optional[datetime] = Query(None, description="Filter entries at or after this datetime (ISO 8601)"),
    until: Optional[datetime] = Query(None, description="Filter entries at or before this datetime (ISO 8601)"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """
    Return audit events that represent access to the current user's data
    (Phase 7.5). Includes elevated ballot views (`admin.audit_ballot_viewed`
    targeting your ballot specifically), and system-wide views that touch
    every user (`admin.delegation_graph_viewed`, `admin.user_list_viewed`).
    """
    return get_user_access_log(
        current_user.id, db, limit=limit, offset=offset, since=since, until=until
    )


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
