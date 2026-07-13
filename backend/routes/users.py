from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

import auth as auth_utils
import models
import schemas
from database import get_db
from delegation_engine import graph_store
from eligibility import eligible_viewers_for_proposal
from org_restriction import effective_discoverability
from permissions import can_see_votes

router = APIRouter(prefix="/api/users", tags=["users"])


def _viewer_can_read_proposal(
    db: Session,
    viewer: Optional[models.User],
    proposal: Optional[models.Proposal],
) -> bool:
    """Apply proposal/org access before ballot-identity visibility.

    A public delegate profile makes a ballot public only within an artifact
    the viewer may read. It must not turn a members-only or hidden-org
    proposal into a public proposal-title/value side channel.
    """
    if proposal is None:
        return False
    if proposal.org_id is None:
        return True
    if viewer is not None:
        if viewer.is_admin:
            return True
        if viewer.id in eligible_viewers_for_proposal(db, proposal):
            return True

    # Match the anonymous public-activity surface. Public sub-org proposal
    # exposure is intentionally unsupported by that surface.
    if proposal.sub_org_id is not None:
        return False
    org = db.get(models.Organization, proposal.org_id)
    return bool(
        org is not None
        and effective_discoverability(org) != "hidden"
        and org.activity_visibility == "public"
    )


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


# ---------------------------------------------------------------------------
# Phase 27 — delegation strategy preference
# ---------------------------------------------------------------------------

_VALID_DELEGATION_STRATEGIES = ("strict_precedence", "relevance_weighted")


@router.patch("/me/delegation-strategy", response_model=schemas.UserOut)
def update_delegation_strategy(
    body: schemas.DelegationStrategyUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Phase 27 B4 — update the caller's delegation_strategy preference.

    Accepted values: ``"strict_precedence"`` | ``"relevance_weighted"``.
    Other values are rejected with 400. No audit log entry (this is a
    user preference, same shape as notification settings).

    Strategy choice is consumed by the delegation engine at tally time
    (DelegationService._build_context bulk-reads strategies for every
    eligible voter). A user toggling mid-tally picks up the new value
    on the next tally; the in-progress tally is unaffected.
    """
    new_strategy = body.strategy
    if new_strategy not in _VALID_DELEGATION_STRATEGIES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid delegation_strategy {new_strategy!r}. "
                f"Allowed values: {', '.join(_VALID_DELEGATION_STRATEGIES)}."
            ),
        )
    current_user.delegation_strategy = new_strategy
    db.commit()
    db.refresh(current_user)
    return current_user


@router.get("/search", response_model=list[schemas.UserSearchResultWithContext])
def search_users(
    q: str = Query("", description="Search by display name or username"),
    topic_id: Optional[str] = Query(None, description="Filter to public delegates for topic"),
    org_slug: Optional[str] = Query(
        None,
        description=(
            "Restrict results to active members of the org with this slug. "
            "Caller must themselves be an active member."
        ),
    ),
    limit: int = Query(20, le=100),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Search users by name/username with follow/delegate context.

    When ``org_slug`` is provided, results are restricted to active members of
    that org. The caller must themselves be an active member of the org or
    the request is rejected with 403 (defense in depth: prevents using this
    endpoint to enumerate other orgs' membership).

    Known limitation: when ``org_slug`` is omitted, results span the entire
    user base (legacy/backward-compat behavior). Most callers are expected
    to pass ``org_slug``; the unscoped path is preserved for admin/legacy
    usage and may be tightened in a follow-up.
    """
    query = db.query(models.User).filter(models.User.id != current_user.id)
    if q:
        like = f"%{q}%"
        query = query.filter(
            models.User.display_name.ilike(like) | models.User.username.ilike(like)
        )
    if org_slug:
        org = db.query(models.Organization).filter(
            models.Organization.slug == org_slug,
        ).first()
        if not org:
            # Treat unknown slug as not-a-member (don't leak org existence).
            raise HTTPException(
                status_code=403,
                detail="You are not a member of this organization",
            )
        # Caller must themselves be an active member of the org.
        caller_membership = db.query(models.OrgMembership).filter(
            models.OrgMembership.user_id == current_user.id,
            models.OrgMembership.org_id == org.id,
            models.OrgMembership.status == "active",
        ).first()
        if not caller_membership:
            raise HTTPException(
                status_code=403,
                detail="You are not a member of this organization",
            )
        query = query.join(
            models.OrgMembership,
            models.OrgMembership.user_id == models.User.id,
        ).filter(
            models.OrgMembership.org_id == org.id,
            models.OrgMembership.status == "active",
        )
    if topic_id:
        # DelegateProfile.org_id is already org-scoped, so when both org_slug
        # and topic_id are present this composes cleanly: results are users
        # who are active members of the org AND have an active delegate
        # profile for the topic in that same org.
        dp_filters = [
            models.DelegateProfile.topic_id == topic_id,
        ]
        if org_slug:
            # `org` is bound above when org_slug is truthy.
            dp_filters.append(models.DelegateProfile.org_id == org.id)
        query = query.join(
            models.DelegateProfile,
            models.DelegateProfile.user_id == models.User.id,
        ).filter(*dp_filters)
    users = query.order_by(models.User.display_name).limit(limit).all()
    return [_enrich_user_result(db, u, current_user.id) for u in users]


def _enrich_user_result(db: Session, user: models.User, viewer_id: str):
    # Phase 33 D1 — is_active column dropped; all rows behaved as active.
    profiles = list(user.delegate_profiles)

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
        avatar_url=user.avatar_url,
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
    org_slug: Optional[str] = Query(
        None,
        description=(
            "Restrict results to active members of the org with this slug. "
            "Caller must themselves be an active member."
        ),
    ),
    limit: int = Query(20, le=100),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    # Phase 10.2 W-FIX-A: explicitly pass topic_id=None so the inner
    # `search_users` (called as a plain Python function, bypassing FastAPI
    # dependency resolution) doesn't receive its `Query(None)` default
    # object as the value for topic_id. The Query placeholder is truthy in
    # boolean context, which would cause the route to attempt a join on
    # `DelegateProfile.topic_id == <Query object>` and explode at the
    # SQLite driver. Surfaced by the new compat-endpoint coverage tests.
    return search_users(
        q=q,
        topic_id=None,
        org_slug=org_slug,
        limit=limit,
        db=db,
        current_user=current_user,
    )


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
    # Phase 33 D1 — is_active column dropped; all rows behave as active.
    # Phase 91: registration metadata follows the same visibility ladder as
    # ballots. A profile marked private (or followers_only) must not leak its
    # topic, bio, or position statement on this anonymous endpoint.
    all_profiles = list(user.delegate_profiles)
    visible_profiles = [
        p for p in all_profiles
        if can_see_votes(
            db, viewer_id, user_id, [p.topic_id], org_id=p.org_id,
        )
    ]
    # Collect visible votes (only those on public delegate topics, unless viewer = self)
    votes_out: list[schemas.VoteVisibility] = []
    hidden_vote_count = 0
    direct_votes = db.query(models.Vote).filter(
        models.Vote.user_id == user_id,
        models.Vote.is_direct.is_(True),
    ).order_by(models.Vote.cast_at.desc()).all()

    for v in direct_votes:
        proposal = db.get(models.Proposal, v.proposal_id)
        proposal_topics = [pt.topic_id for pt in (proposal.proposal_topics if proposal else [])]
        # Phase 30.3 B4 — pass org_id so the follower-relationship check
        # is org-scoped (Phase 18 D2 was missing here).
        proposal_org_id = proposal.org_id if proposal else None
        visible = (
            _viewer_can_read_proposal(db, current_user, proposal)
            and can_see_votes(
                db, viewer_id, user_id, proposal_topics,
                org_id=proposal_org_id,
            )
        )
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
        else:
            # One placeholder per hidden ballot still disclosed the private
            # proposal and cast time. Preserve only an aggregate count.
            hidden_vote_count += 1

    return schemas.PublicProfileOut(
        user=schemas.UserSearchResult(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            avatar_url=user.avatar_url,
        ),
        delegate_profiles=[
            schemas.DelegateProfileOut.model_validate(p)
            for p in visible_profiles
        ],
        votes=votes_out,
        hidden_vote_count=hidden_vote_count,
    )


@router.get("/me", response_model=schemas.UserOut)
def get_me(
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Phase 33 C1 — self-fetch endpoint.

    ``GET /api/users/me`` was returning 404 "User not found" because the
    request matched the generic ``GET /api/users/{user_id}`` handler with
    ``user_id="me"``, which then missed the DB lookup. Adding this explicit
    handler above the generic route makes the URL behave like the natural
    self-fetch every other app expects. The canonical self-endpoint
    remains ``GET /api/auth/me`` (auth router) — this is the convenience
    alias for callers reaching for the ``/users/me`` pattern.
    """
    return current_user


@router.get("/{user_id}", response_model=schemas.PublicUserOut)
def get_user(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Return public-safe identity data for another account.

    Full account details are reserved for ``/api/users/me`` and
    ``/api/auth/me``; merely being authenticated does not grant access to
    another user's email, verification metadata, or account preferences.
    """
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.get("/{user_id}/delegation-tree", response_model=schemas.DelegationGraph)
def delegation_tree(
    user_id: str,
    org_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Phase 10.2 W-FIX-A BUG-2: gated behind ``Depends(get_current_user)``
    and applies identity-redaction parity with ``/api/delegations/graph``.

    Previously this endpoint was unauthenticated and returned the full
    delegation neighborhood (display names, usernames, avatar URLs) for any
    user ID a caller could guess, bypassing the per-relationship privacy
    rules. Per the Phase 10.2 test-depth audit (Class B BUG row for
    ``GET /api/users/{id}/delegation-tree``), the fix:
      - requires authentication
      - anonymizes nodes the viewer cannot see by the same rules used for
        ``can_see_votes`` (self / follower / public delegate). Nodes that
        fail the check are returned with a generic display name + ``None``
        username and avatar so the graph topology remains useful for the
        target's self-view but third-party identities don't leak.

    Phase 18 (B2.2): adds optional ``org_id`` query parameter so the
    response can be scoped to a single org's partition. The
    ``graph_store`` is partitioned per-org post-Phase-18; without an
    ``org_id`` the response would only show the legacy/unscoped bucket
    (effectively empty in production), so the frontend MUST pass
    ``org_id`` for the user's currently selected org. The endpoint stays
    at ``/api/users/...`` per spec line 46 — user identity is
    account-level even though the page rendering it is org-scoped.

    The chain_behavior lookup at the per-edge level also filters on
    ``org_id`` so the edge's chain_behavior comes from the correct
    Delegation row when a user has independent delegations per org.
    """
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    node_ids, edges = graph_store.get_neighborhood(user_id, org_id=org_id)

    # Pre-compute viewer's follow set and the set of public-delegate user
    # IDs across all topics. Both sets are used inline in the per-node
    # redaction check below.
    viewer_is_target = current_user.id == user_id
    viewer_follows: set[str] = {
        rel.followed_id
        for rel in db.query(models.FollowRelationship).filter(
            models.FollowRelationship.follower_id == current_user.id,
        ).all()
    }
    # Phase 41 (2026-05-28): use canonical eligibility.public_delegate_user_ids
    # helper. Original Phase 37 B3 fix lived inline here; Phase 41 followup
    # consolidates the visibility predicate so the vote-graph sibling at
    # routes/proposals.py:2227 + this delegation_tree site share one
    # implementation — defends against future drift if the public-tier
    # visibility values change.
    from eligibility import public_delegate_user_ids as _public_delegate_user_ids
    public_delegate_user_ids: set[str] = _public_delegate_user_ids(db)

    def _viewer_may_see(uid: str) -> bool:
        # When the viewer IS the target, every node in their own
        # neighborhood is by definition a relationship they're already
        # party to (delegations they made or that were made to them) —
        # no redaction needed for the self-view path.
        if viewer_is_target:
            return True
        if uid == current_user.id:
            return True
        if uid in public_delegate_user_ids:
            return True
        if uid in viewer_follows:
            return True
        return False

    nodes = []
    for uid in node_ids:
        u = db.get(models.User, uid)
        if not u:
            continue
        if _viewer_may_see(uid):
            nodes.append(schemas.GraphNode(
                id=uid,
                display_name=u.display_name,
                username=u.username,
                weight=graph_store.compute_voting_weight(uid, org_id=org_id),
                avatar_url=u.avatar_url,
            ))
        else:
            nodes.append(schemas.GraphNode(
                id=uid,
                display_name="Anonymous user",
                username="anonymous",
                weight=graph_store.compute_voting_weight(uid, org_id=org_id),
                avatar_url=None,
            ))

    graph_edges = []
    for src, tgt, tid in edges:
        topic_name = None
        if tid:
            t = db.get(models.Topic, tid)
            topic_name = t.name if t else None
        chain_q = db.query(models.Delegation).filter(
            models.Delegation.delegator_id == src,
            models.Delegation.delegate_id == tgt,
            models.Delegation.topic_id == tid,
        )
        if org_id is not None:
            chain_q = chain_q.filter(models.Delegation.org_id == org_id)
        d = chain_q.first()
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
    Returns only votes the requester can see. Hidden votes are omitted rather
    than represented by rows that disclose proposal IDs.
    """
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    viewer_id = current_user.id if current_user else None
    direct_votes = db.query(models.Vote).filter(
        models.Vote.user_id == user_id,
        models.Vote.is_direct.is_(True),
    ).order_by(models.Vote.cast_at.desc()).all()

    result = []
    for v in direct_votes:
        proposal = db.get(models.Proposal, v.proposal_id)
        proposal_topics = [pt.topic_id for pt in (proposal.proposal_topics if proposal else [])]
        # Phase 30.3 B4 — pass org_id for the org-scoped follower check.
        proposal_org_id = proposal.org_id if proposal else None
        visible = (
            _viewer_can_read_proposal(db, current_user, proposal)
            and can_see_votes(
                db, viewer_id, user_id, proposal_topics,
                org_id=proposal_org_id,
            )
        )
        if visible:
            result.append(schemas.VoteVisibility(
                id=v.id,
                proposal_id=v.proposal_id,
                proposal_title=proposal.title if proposal else None,
                vote_value=v.vote_value,
                is_direct=v.is_direct,
                cast_at=v.cast_at,
                visible=True,
            ))

    return result
