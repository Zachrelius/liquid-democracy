"""
Public delegate registration and browsing endpoints.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, distinct
from sqlalchemy.orm import Session

import auth as auth_utils
import models
import schemas
from audit_utils import log_audit_event
from database import get_db

router = APIRouter(prefix="/api/delegates", tags=["delegates"])

# Phase 19 B4 — org-scoped browse endpoint mounted under /api/orgs/{org_slug}.
# Kept as a separate APIRouter so the existing /api/delegates/* surface can
# stay intact (Cluster G handles deprecation in a later pass).
org_delegates_router = APIRouter(prefix="/api/orgs", tags=["delegates"])


def _delegation_count(
    db: Session,
    user_id: str,
    topic_id: str,
    org_id: Optional[str] = None,
) -> int:
    """Count delegations to ``user_id`` on ``topic_id``.

    Phase 18 (B2.2): adds an optional ``org_id`` filter so the public
    delegate's count reflects only delegations within the org scope of
    the corresponding ``DelegateProfile``. Pre-fix, a delegate active in
    two orgs got their counts summed across orgs, inflating "popular
    delegate" numbers (diagnostic §3 row for ``routes/delegates.py:19``).
    The optional default keeps any future caller that legitimately wants
    a cross-org count working.
    """
    q = db.query(models.Delegation).filter(
        models.Delegation.delegate_id == user_id,
        models.Delegation.topic_id == topic_id,
    )
    if org_id is not None:
        q = q.filter(models.Delegation.org_id == org_id)
    return q.count()


def _build_public_delegate(db: Session, user: models.User) -> schemas.PublicDelegateOut:
    profiles = [p for p in user.delegate_profiles if p.is_active]
    # Phase 18: pass each profile's ``org_id`` through so the per-topic
    # counts honor the profile's org scope. Profiles with ``org_id IS
    # NULL`` (legacy data, pre-Phase-4c) fall through to the no-filter
    # path and behave as before.
    counts = {
        p.topic_id: _delegation_count(db, user.id, p.topic_id, org_id=p.org_id)
        for p in profiles
    }
    return schemas.PublicDelegateOut(
        user=schemas.UserSearchResult(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            avatar_url=user.avatar_url,
        ),
        profiles=[schemas.DelegateProfileOut.model_validate(p) for p in profiles],
        delegation_counts=counts,
    )


@router.get("/public", response_model=list[schemas.PublicDelegateOut])
def list_public_delegates(
    topic_id: Optional[str] = Query(None),
    org_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(auth_utils.get_optional_user),
):
    """Browse public delegates, optionally filtered by topic and/or org.

    Phase 8.5 (Decision 5): when a `topic_id` is not specified and the viewer
    is authenticated, hide profiles whose ONLY active topics are sub-org topics
    the viewer isn't a member of (not a hard block — search-by-name still
    finds them; this is just browse-default scope filtering).

    Anonymous viewers continue to see all profiles, since we have no scope
    context to filter against.
    """
    q = db.query(models.User).join(
        models.DelegateProfile,
        models.DelegateProfile.user_id == models.User.id,
    ).filter(models.DelegateProfile.is_active.is_(True))

    if org_id:
        q = q.filter(models.DelegateProfile.org_id == org_id)
    if topic_id:
        q = q.filter(models.DelegateProfile.topic_id == topic_id)

    users = q.distinct().all()

    # Decision 5 scope filter: if the caller is authenticated and didn't
    # specify a topic, suppress delegates whose only active profiles are on
    # sub-org topics the viewer can't see.
    if current_user is not None and topic_id is None:
        viewer_sub_org_ids = {row.sub_org_id for row in db.query(
            models.SubOrgMembership.sub_org_id
        ).filter(
            models.SubOrgMembership.user_id == current_user.id,
            models.SubOrgMembership.status == "active",
        ).all()}

        # Pre-fetch each candidate's active profile topics joined with their
        # sub_org_id so we can decide visibility per user with one query.
        # Topic.sub_org_id is the source of truth for scope.
        rows = db.query(
            models.DelegateProfile.user_id,
            models.Topic.sub_org_id,
        ).join(
            models.Topic, models.Topic.id == models.DelegateProfile.topic_id,
        ).filter(
            models.DelegateProfile.is_active.is_(True),
            models.DelegateProfile.user_id.in_([u.id for u in users] or [""]),
        ).all()

        per_user_scopes: dict[str, set[Optional[str]]] = {}
        for user_id, sub_org_id in rows:
            per_user_scopes.setdefault(user_id, set()).add(sub_org_id)

        visible: list[models.User] = []
        for u in users:
            scopes = per_user_scopes.get(u.id, set())
            # Visible if at least one profile is parent-org-wide (None) OR
            # one is in a sub-org the viewer belongs to.
            if None in scopes or any(s in viewer_sub_org_ids for s in scopes if s):
                visible.append(u)
        users = visible

    return [_build_public_delegate(db, u) for u in users]


@router.get("/public/{topic_id}", response_model=list[schemas.PublicDelegateOut])
def public_delegates_for_topic(
    topic_id: str,
    db: Session = Depends(get_db),
):
    """Public delegates for a specific topic, sorted by delegation count."""
    topic = db.get(models.Topic, topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    users = db.query(models.User).join(
        models.DelegateProfile,
        models.DelegateProfile.user_id == models.User.id,
    ).filter(
        models.DelegateProfile.topic_id == topic_id,
        models.DelegateProfile.is_active.is_(True),
    ).all()

    results = [_build_public_delegate(db, u) for u in users]
    results.sort(key=lambda r: r.delegation_counts.get(topic_id, 0), reverse=True)
    return results


@router.post("/register", response_model=schemas.DelegateProfileOut, status_code=201)
def register_as_delegate(
    body: schemas.DelegateProfileCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Register as a public delegate for a topic (or reactivate if previously deactivated)."""
    topic = db.get(models.Topic, body.topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    existing = db.query(models.DelegateProfile).filter(
        models.DelegateProfile.user_id == current_user.id,
        models.DelegateProfile.topic_id == body.topic_id,
    ).first()

    if existing:
        existing.is_active = True
        existing.bio = body.bio
        db.flush()
        log_audit_event(
            db, action="delegate_profile.created",
            target_type="delegate_profile", target_id=existing.id,
            actor_id=current_user.id, details={"topic_id": body.topic_id},
        )
        db.commit()
        db.refresh(existing)
        return existing

    profile = models.DelegateProfile(
        user_id=current_user.id,
        topic_id=body.topic_id,
        bio=body.bio,
    )
    db.add(profile)
    db.flush()
    log_audit_event(
        db, action="delegate_profile.created",
        target_type="delegate_profile", target_id=profile.id,
        actor_id=current_user.id, details={"topic_id": body.topic_id},
    )
    db.commit()
    db.refresh(profile)
    return profile


@router.delete("/register/{topic_id}", status_code=204)
def deactivate_delegate_profile(
    topic_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Deactivate public delegate status for a topic. Existing delegations remain."""
    profile = db.query(models.DelegateProfile).filter(
        models.DelegateProfile.user_id == current_user.id,
        models.DelegateProfile.topic_id == topic_id,
        models.DelegateProfile.is_active.is_(True),
    ).first()
    if not profile:
        raise HTTPException(status_code=404, detail="No active delegate profile for this topic")

    profile.is_active = False
    db.flush()
    log_audit_event(
        db, action="delegate_profile.deactivated",
        target_type="delegate_profile", target_id=profile.id,
        actor_id=current_user.id, details={"topic_id": topic_id},
    )
    db.commit()


# ---------------------------------------------------------------------------
# Phase 19 B4 — Per-org public delegate browse
# ---------------------------------------------------------------------------


def _recent_rationale_ratio(
    db: Session, user_id: str, *, since: datetime,
) -> float:
    """Per spec D11 / B4: ratio of "votes with rationale" to "total votes
    in past N days" (default 30) for ``user_id``. Returns 0.0 when the
    user has no votes in the window (the secondary-sort key just sorts
    those delegates last among equal-delegation-count peers).

    The query joins ``Vote`` to ``DelegateVoteRationale`` via the
    one-to-one back-reference; we count the rationale rows by
    ``COUNT(rationale.id)`` so a vote without rationale doesn't inflate
    the numerator.
    """
    total_votes = (
        db.query(func.count(models.Vote.id))
        .filter(
            models.Vote.user_id == user_id,
            models.Vote.cast_at >= since,
        )
        .scalar()
    ) or 0
    if total_votes == 0:
        return 0.0
    rationale_votes = (
        db.query(func.count(models.DelegateVoteRationale.id))
        .join(models.Vote, models.Vote.id == models.DelegateVoteRationale.vote_id)
        .filter(
            models.Vote.user_id == user_id,
            models.Vote.cast_at >= since,
        )
        .scalar()
    ) or 0
    return float(rationale_votes) / float(total_votes)


@org_delegates_router.get("/{org_slug}/delegates")
def browse_org_delegates(
    org_slug: str,
    topic_id: Optional[str] = Query(None),
    active_within_days: Optional[int] = Query(None, ge=1),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(auth_utils.get_optional_user),
):
    """Phase 19 B4 — public delegate browse for an org.

    Returns delegates with at least one ``DelegateProfile`` row in this
    org where ``visibility='public_accepting'`` (per D11: ``public``-only
    transparent delegates are NOT surfaced on the browse page; they're
    discoverable via direct URL or vote graph).

    Response shape per row:
        {user_id, display_name, username, delegate_handle, avatar_url,
         intro, public_topics: [{topic_id, name, visibility}],
         delegation_count, recent_rationale_ratio}

    Default sort: ``delegation_count DESC, recent_rationale_ratio DESC``
    (D11 secondary tiebreak: "how transparent are they about their
    reasoning"). Pagination: offset-based, ``limit`` defaults to 20
    (existing platform pagination pattern; the spec mentioned cursor-
    based but the rest of the platform is offset-based — see
    ``routes/notifications.py`` line 22).

    Filters:
        ?topic_id=<uuid>             — only delegates ``public_accepting``
                                       for that specific topic.
        ?active_within_days=N        — only delegates with at least one
                                       vote in the past N days (Vote.cast_at).

    Permission:
        - Org members may always browse.
        - Non-members may browse only if the org is publicly listed (the
          existing ``join_policy != 'invite_only_secret'`` semantic;
          ``invite_only_secret`` orgs return 404 to non-members so their
          existence isn't confirmed by this endpoint either).
    """
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    is_member = False
    if current_user is not None:
        is_member = (
            db.query(models.OrgMembership)
            .filter(
                models.OrgMembership.user_id == current_user.id,
                models.OrgMembership.org_id == org.id,
                models.OrgMembership.status == "active",
            )
            .first()
            is not None
        )
    if not is_member:
        # Non-members may only browse publicly-listed orgs. Secret orgs
        # return 404 (matching the OrgPublicLanding pattern in routes/
        # organizations.py:802) so endpoint existence doesn't leak the
        # org's existence to unauthenticated probes.
        if org.join_policy == "invite_only_secret":
            raise HTTPException(status_code=404, detail="Organization not found")

    # ----- Find candidate user IDs: users with at least one
    # public_accepting topic in this org. -----
    base_q = (
        db.query(models.DelegateProfile.user_id)
        .filter(
            models.DelegateProfile.org_id == org.id,
            models.DelegateProfile.visibility == "public_accepting",
        )
    )
    if topic_id is not None:
        base_q = base_q.filter(models.DelegateProfile.topic_id == topic_id)
    candidate_user_ids = {row[0] for row in base_q.distinct().all()}

    if not candidate_user_ids:
        return []

    # ----- Apply activity-window filter if requested. -----
    if active_within_days is not None:
        since = (
            datetime.now(timezone.utc).replace(tzinfo=None)
            - timedelta(days=active_within_days)
        )
        active_user_ids = {
            row[0] for row in (
                db.query(models.Vote.user_id)
                .filter(
                    models.Vote.user_id.in_(candidate_user_ids),
                    models.Vote.cast_at >= since,
                )
                .distinct()
                .all()
            )
        }
        candidate_user_ids = candidate_user_ids & active_user_ids

    if not candidate_user_ids:
        return []

    # ----- Build per-user payloads. We pre-fetch the supporting data so
    # we don't issue N+1 queries inside the loop. -----
    users = (
        db.query(models.User)
        .filter(models.User.id.in_(candidate_user_ids))
        .all()
    )
    users_by_id = {u.id: u for u in users}

    # Per-user public topics (visibility IN ('public', 'public_accepting'))
    # joined with the topic name. D12: the page renders both public and
    # public_accepting topics, so the browse payload also surfaces both
    # so the FE can show the per-topic label correctly. The per-user
    # GROUP BY happens client-side in the loop below.
    topic_rows = (
        db.query(
            models.DelegateProfile.user_id,
            models.DelegateProfile.topic_id,
            models.DelegateProfile.visibility,
            models.Topic.name,
        )
        .join(models.Topic, models.Topic.id == models.DelegateProfile.topic_id)
        .filter(
            models.DelegateProfile.user_id.in_(candidate_user_ids),
            models.DelegateProfile.org_id == org.id,
            models.DelegateProfile.visibility.in_(("public", "public_accepting")),
        )
        .all()
    )
    topics_by_user: dict[str, list[dict]] = {}
    for uid, tid, vis, name in topic_rows:
        topics_by_user.setdefault(uid, []).append(
            {"topic_id": tid, "name": name, "visibility": vis}
        )

    # Per-user delegation count in this org (D11: per-org count, not
    # cross-org).
    delegation_count_rows = (
        db.query(
            models.Delegation.delegate_id,
            func.count(models.Delegation.id),
        )
        .filter(
            models.Delegation.delegate_id.in_(candidate_user_ids),
            models.Delegation.org_id == org.id,
        )
        .group_by(models.Delegation.delegate_id)
        .all()
    )
    delegation_count_by_user = {uid: cnt for uid, cnt in delegation_count_rows}

    # Per-user OrgDelegateProfile (intro lookup).
    odp_rows = (
        db.query(models.OrgDelegateProfile)
        .filter(
            models.OrgDelegateProfile.user_id.in_(candidate_user_ids),
            models.OrgDelegateProfile.org_id == org.id,
        )
        .all()
    )
    odp_by_user = {odp.user_id: odp for odp in odp_rows}

    # Recent rationale ratio (past 30 days; D11 fixed window).
    rationale_window_start = (
        datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)
    )

    payload = []
    for uid in candidate_user_ids:
        user = users_by_id.get(uid)
        if user is None:
            continue  # defensive — should not happen
        odp = odp_by_user.get(uid)
        payload.append({
            "user_id": user.id,
            "display_name": user.display_name,
            "username": user.username,
            "delegate_handle": user.delegate_handle,
            "avatar_url": user.avatar_url,
            "intro": odp.intro if odp is not None else None,
            "public_topics": topics_by_user.get(uid, []),
            "delegation_count": delegation_count_by_user.get(uid, 0),
            "recent_rationale_ratio": _recent_rationale_ratio(
                db, uid, since=rationale_window_start,
            ),
        })

    # ----- Default sort: delegation_count DESC, recent_rationale_ratio DESC.
    payload.sort(
        key=lambda r: (r["delegation_count"], r["recent_rationale_ratio"]),
        reverse=True,
    )

    # ----- Pagination (offset-based, matches notifications.py:262). -----
    return payload[offset : offset + limit]


@org_delegates_router.get(
    "/{org_slug}/delegates/{handle_or_username}",
    response_model=schemas.PublicDelegatePageOut,
)
def public_delegate_page(
    org_slug: str,
    handle_or_username: str,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(auth_utils.get_optional_user),
):
    """Phase 19 — public read of any delegate's per-org page.

    Resolves ``handle_or_username`` against ``User.delegate_handle`` first
    (D10 — handle takes precedence), falling back to ``User.username``.
    Per D12: page renders both ``public`` and ``public_accepting`` topics;
    ``private`` topics are hidden. The browse endpoint surfaces only
    ``public_accepting`` users (D11), but a transparent-only delegate is
    still reachable via this single-page endpoint.

    Auth gate via ``OrgDelegateProfile.effective_page_visibility(db)``:
      - ``public``  → anyone may view (anonymous OK).
      - ``private_delegators`` → must be approved follower in this org
        (Phase 18 follow-org-scoping: ``FollowRelationship`` row with
        ``org_id = page_org_id`` AND status approved).
      - ``private`` → 404 (owner uses ``/delegate-profile`` instead).

    404 covers both "no such user/page" and "page exists but you can't
    see it" so existence isn't leaked.
    """
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    # Handle takes precedence; fall back to username (D10).
    target = (
        db.query(models.User)
        .filter(models.User.delegate_handle == handle_or_username)
        .first()
    )
    if target is None:
        target = (
            db.query(models.User)
            .filter(models.User.username == handle_or_username)
            .first()
        )
    if target is None:
        raise HTTPException(status_code=404, detail="Delegate not found")

    odp = (
        db.query(models.OrgDelegateProfile)
        .filter(
            models.OrgDelegateProfile.user_id == target.id,
            models.OrgDelegateProfile.org_id == org.id,
        )
        .first()
    )
    if odp is None:
        raise HTTPException(status_code=404, detail="Delegate page not found")

    effective = odp.effective_page_visibility(db)
    if effective == "private":
        raise HTTPException(status_code=404, detail="Delegate page not found")
    if effective == "private_delegators":
        # Owner sees their own page; otherwise must be an approved follower
        # in this org.
        if current_user is None or current_user.id != target.id:
            if current_user is None:
                raise HTTPException(status_code=404, detail="Delegate page not found")
            is_approved_follower = (
                db.query(models.FollowRelationship)
                .filter(
                    models.FollowRelationship.follower_id == current_user.id,
                    models.FollowRelationship.followed_id == target.id,
                    models.FollowRelationship.org_id == org.id,
                )
                .first()
                is not None
            )
            if not is_approved_follower:
                raise HTTPException(status_code=404, detail="Delegate page not found")

    # Topics: only non-private (public + public_accepting per D12).
    topic_rows = (
        db.query(models.DelegateProfile)
        .filter(
            models.DelegateProfile.user_id == target.id,
            models.DelegateProfile.org_id == org.id,
            models.DelegateProfile.visibility.in_(("public", "public_accepting")),
        )
        .all()
    )
    # Resolve topic names in one query.
    topic_ids = [tp.topic_id for tp in topic_rows]
    name_by_topic_id: dict[str, str] = {}
    if topic_ids:
        for tid, name in (
            db.query(models.Topic.id, models.Topic.name)
            .filter(models.Topic.id.in_(topic_ids))
            .all()
        ):
            name_by_topic_id[tid] = name

    topics_out = [
        schemas._OrgDelegateProfileTopicOut(
            id=tp.id,
            topic_id=tp.topic_id,
            topic_name=name_by_topic_id.get(tp.topic_id),
            bio=tp.bio or "",
            position_statement=tp.position_statement,
            visibility=tp.visibility,
            public_accepting_submitted_at=tp.public_accepting_submitted_at,
            public_accepting_approved_at=tp.public_accepting_approved_at,
            public_accepting_approved_by_id=tp.public_accepting_approved_by_id,
            public_accepting_denied_comment=tp.public_accepting_denied_comment,
        )
        for tp in topic_rows
    ]

    return schemas.PublicDelegatePageOut(
        user_id=target.id,
        username=target.username,
        display_name=target.display_name,
        avatar_url=target.avatar_url,
        delegate_handle=target.delegate_handle,
        org_id=org.id,
        org_slug=org.slug,
        org_name=org.name,
        intro=odp.intro,
        topics=topics_out,
    )
