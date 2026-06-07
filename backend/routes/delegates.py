"""
Public delegate registration and browsing endpoints.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, distinct
from sqlalchemy.orm import Session

import auth as auth_utils
import models
import schemas
from audit_utils import log_audit_event
from database import get_db

# Phase 19 G2 — module-level logger for deprecation warnings on the legacy
# /api/delegates/public endpoint. Replaced by the org-scoped browse at
# /api/orgs/{slug}/delegates (see ``org_delegates_router`` below). Full
# removal deferred to a future cleanup pass.
logger = logging.getLogger(__name__)

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
    # Phase 33 D1 — is_active column dropped; all rows behaved as active anyway.
    profiles = list(user.delegate_profiles)
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


@router.get("/public", response_model=list[schemas.PublicDelegateOut], deprecated=True)
def list_public_delegates(
    response: Response,
    topic_id: Optional[str] = Query(None),
    org_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(auth_utils.get_optional_user),
):
    """Browse public delegates, optionally filtered by topic and/or org.

    DEPRECATED (Phase 19 G2): use the org-scoped browse endpoint at
    ``GET /api/orgs/{slug}/delegates`` instead. The new endpoint is the
    canonical surface — it honors the per-topic visibility states added in
    Phase 19 (``private`` / ``public`` / ``public_accepting``), supports
    sort by delegation count + recent rationale ratio, and is the
    consumer-side surface for the new public delegate pages.

    This endpoint is preserved for one release to avoid breaking any
    existing API consumers; full removal is scheduled for a future cleanup
    pass. Callers receive a ``Deprecation: true`` response header (per
    draft-ietf-httpapi-deprecation-header) and a one-line server-side
    log warning per call.

    Phase 8.5 (Decision 5): when a `topic_id` is not specified and the viewer
    is authenticated, hide profiles whose ONLY active topics are sub-org topics
    the viewer isn't a member of (not a hard block — search-by-name still
    finds them; this is just browse-default scope filtering).

    Anonymous viewers continue to see all profiles, since we have no scope
    context to filter against.
    """
    # Phase 19 G2 — deprecation marker: response header (parseable by
    # API clients) + server-side log warning (visible in Railway logs
    # so we can track if any active consumers remain before full removal).
    response.headers["Deprecation"] = "true"
    response.headers["Link"] = (
        '</api/orgs/{slug}/delegates>; rel="successor-version"'
    )
    logger.warning(
        "DEPRECATED endpoint hit: GET /api/delegates/public — "
        "use GET /api/orgs/{slug}/delegates (Phase 19 G2)"
    )
    q = db.query(models.User).join(
        models.DelegateProfile,
        models.DelegateProfile.user_id == models.User.id,
    )

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
    ).all()

    results = [_build_public_delegate(db, u) for u in users]
    results.sort(key=lambda r: r.delegation_counts.get(topic_id, 0), reverse=True)
    return results


# ---------------------------------------------------------------------------
# Phase 33 D1 — legacy POST /api/delegates/register + DELETE /register/{topic_id}
# removed. Phase 19 introduced the per-org delegate profile lifecycle with
# the four-state visibility ladder (private / followers_only / public /
# public_accepting). Phase 30 B1 retired the frontend's caller (Settings.jsx
# now links to the canonical /{slug}/delegate-profile page); these endpoints
# carried no real callers, and their sole effect was to toggle the
# now-vestigial is_active column. The column drops in the Phase 33 migration.


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

    # Phase 32.2 B4 — `public_delegates.enabled` org toggle. When False,
    # the browse endpoint returns an empty list (per spec asymmetry with
    # the single-page 404: an org's existence is already known to anyone
    # who reached this route, so the empty-list response is more useful
    # than 404 here). Data preserved; re-enabling restores results.
    _org_settings = getattr(org, "settings", None) or {}
    _pd_settings = _org_settings.get("public_delegates")
    if (
        isinstance(_pd_settings, dict)
        and _pd_settings.get("enabled") is False
    ):
        return []

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
        # Non-members may only browse non-hidden orgs. Hidden orgs
        # (Phase 57; was `invite_only_secret`) return 404 — matching the
        # OrgPublicLanding pattern — so endpoint existence doesn't leak
        # the org's existence to unauthenticated probes.
        if org.discoverability == "hidden":
            raise HTTPException(status_code=404, detail="Organization not found")

    # ----- Find candidate user IDs: users with at least one
    # public_accepting topic in this org. -----
    # Phase 34.2 F3 — when org_slug resolves to a sub-org, DelegateProfile
    # rows are stored with org_id=parent + sub_org_id=this-sub (same
    # pattern as Phase 34.1 E3 for proposals + topics). Without this
    # branch the sub-org Delegates page came back empty even when
    # public_accepting profiles existed (Karen + Marcus on General
    # Issues in Cedar Court Condos).
    if org.parent_org_id is not None:
        base_q = (
            db.query(models.DelegateProfile.user_id)
            .filter(
                models.DelegateProfile.org_id == org.parent_org_id,
                models.DelegateProfile.sub_org_id == org.id,
                models.DelegateProfile.visibility == "public_accepting",
            )
        )
    else:
        base_q = (
            db.query(models.DelegateProfile.user_id)
            .filter(
                models.DelegateProfile.org_id == org.id,
                models.DelegateProfile.sub_org_id.is_(None),
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

    # Phase 52j J6 — per-org display name resolver. Build a
    # user_id -> effective display name map honoring per-org overrides
    # (``OrgMembership.display_name``). Avoids N+1 by pre-fetching the
    # membership rows for this org.
    from verification import display_name_for
    memberships_for_org = (
        db.query(models.OrgMembership)
        .filter(
            models.OrgMembership.org_id == org.id,
            models.OrgMembership.user_id.in_(candidate_user_ids),
        )
        .all()
    ) if candidate_user_ids else []
    membership_by_user = {m.user_id: m for m in memberships_for_org}

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
            "display_name": display_name_for(
                user, org, membership=membership_by_user.get(uid),
            ),
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
    """Phase 30.3 — public read of any delegate's per-org page.

    Resolves ``handle_or_username`` against ``User.delegate_handle`` first
    (D10 — handle takes precedence), falling back to ``User.username``.

    Auth gate (post-Phase-30.3): derived from the highest per-topic
    visibility in the org (see ``_highest_topic_visibility``):
      - ``public`` (at least one public / public_accepting topic) →
        anyone may view, including anonymous.
      - ``followers_only`` (at least one followers_only, none public) →
        author + approved followers in this org.
      - ``private`` (all topics private, or no topics) → author only;
        404 to everyone else.

    Topics in the response are filtered per viewer relationship:
    anonymous viewers see public + public_accepting only; approved
    followers also see followers_only; the author sees all (including
    private — but that's only the case when viewing their own page).

    404 covers both "no such user/page" and "page exists but you can't
    see it" so existence isn't leaked.
    """
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    # Phase 32.2 B4 — `public_delegates.enabled` org toggle. When False,
    # public delegate pages are hidden but the underlying data is
    # preserved. 404 matches the existing "not found" UX so toggling
    # the feature off doesn't leak existence. Re-enabling restores
    # without re-approval (no data was touched).
    org_settings = getattr(org, "settings", None) or {}
    pd_settings = org_settings.get("public_delegates")
    if (
        isinstance(pd_settings, dict)
        and pd_settings.get("enabled") is False
    ):
        raise HTTPException(
            status_code=404, detail="Public delegate pages disabled for this org",
        )

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

    viewer_id = current_user.id if current_user is not None else None
    is_author = viewer_id == target.id

    # Derive page reachability from per-topic state.
    all_topic_rows = (
        db.query(models.DelegateProfile)
        .filter(
            models.DelegateProfile.user_id == target.id,
            models.DelegateProfile.org_id == org.id,
        )
        .all()
    )
    visibilities = {p.visibility for p in all_topic_rows}
    has_public = bool(
        visibilities & {"public", "public_accepting"}
    )
    has_followers_only = "followers_only" in visibilities

    is_approved_follower = False
    if viewer_id is not None and not is_author:
        is_approved_follower = (
            db.query(models.FollowRelationship)
            .filter(
                models.FollowRelationship.follower_id == viewer_id,
                models.FollowRelationship.followed_id == target.id,
                models.FollowRelationship.org_id == org.id,
            )
            .first()
            is not None
        )

    if not is_author:
        if has_public:
            pass  # anyone may view
        elif has_followers_only:
            if not is_approved_follower:
                raise HTTPException(
                    status_code=404, detail="Delegate page not found",
                )
        else:
            # All private or no topics.
            raise HTTPException(
                status_code=404, detail="Delegate page not found",
            )

    # Filter topics for the viewer's relationship.
    if is_author:
        allowed_states = {"private", "followers_only", "public", "public_accepting"}
    elif is_approved_follower:
        allowed_states = {"followers_only", "public", "public_accepting"}
    else:
        allowed_states = {"public", "public_accepting"}
    topic_rows = [p for p in all_topic_rows if p.visibility in allowed_states]
    # Resolve topic display labels in one query. Phase 30.1 B5 — Topic.name
    # is now scoped per-org and display-safe; the Phase 26 D1 description
    # fallback workaround for the old global-unique constraint is no
    # longer needed.
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

    # Phase 52j J6 — per-org display name resolver. The delegate
    # page is org-scoped, so honor the per-org override when set.
    from verification import display_name_for
    return schemas.PublicDelegatePageOut(
        user_id=target.id,
        username=target.username,
        display_name=display_name_for(target, org),
        avatar_url=target.avatar_url,
        delegate_handle=target.delegate_handle,
        org_id=org.id,
        org_slug=org.slug,
        org_name=org.name,
        intro=odp.intro,
        topics=topics_out,
    )
