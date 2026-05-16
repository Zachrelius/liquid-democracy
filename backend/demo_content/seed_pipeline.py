"""Phase 23 — bible→DB seed orchestrator.

Called once per is_demo=True org by ``demo_reset_job.run_demo_reset_if_due``
after the wipe phase. Each call is idempotent — running it on an already-
empty demo org produces the bible's specified state.

Scope (per spec D11/D12/D13/D14/D15/D16 + Amendment A/B/C/D/E):
- Upsert ``Organization`` row by slug; flip ``is_demo=True``, set
  ``governance_type``/``display_order``/``personas`` from
  ``ORG_SEED_CONFIG`` + bible.
- Resolve cross-org user IDs (Marcus/Dana/Janet) per Stage 8 §5 so each
  real person has exactly one ``User`` row spanning their two orgs.
- Create ``User`` + ``OrgMembership`` rows for named characters AND
  filler members. Defaults role to "member" (system_key).
- Create ``Topic`` rows (from delegate-page topic visibilities +
  proposal candidate statements + proposal options).
- Create ``DelegateProfile`` + ``OrgDelegateProfile`` rows from bible
  ``delegate_pages``.
- Create ``Proposal`` rows (passed/voting/deliberation/draft) with
  backdated timestamps per ``state_at_reset``.
- For voting+post-voting proposals: invoke the snapshot generator + the
  filler-vote allocator.
- Seed named-character votes from delegate-page ``vote_rationales``.
- Create ``Comment`` rows with backdated ``created_at`` per Amendment B
  bulk-insert pattern.
- Seed Janet's 8 Local votes (Stage 8 §3 — hardcoded mapping).
- Create ``Notification`` rows from each ``NotificationFeed`` per the
  Amendment A template table.

The pipeline is intentionally robust to missing/sparse bible fields. Any
unknown ``state_at_reset`` parse falls back to "passed". Any missing
trajectory entry skips snapshot/filler seeding but doesn't error.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from .filler_generator import (
    FillerMember,
    allocate_filler_votes,
    generate_filler_members,
)
from .persona_descriptions import QUICK_LOGIN_DESCRIPTIONS
from .schema import (
    Comment as BibleComment,
    DelegatePage,
    Member,
    NotificationEvent,
    OrgBible,
    Proposal as BibleProposal,
    TopicVisibility,
)

log = logging.getLogger(__name__)


# =============================================================================
# Seed config (Amendment E)
# =============================================================================


ORG_SEED_CONFIG: dict[str, dict] = {
    "demo-cedar-hollow": {
        "governance_type": "Homeowners' Association",
        "display_order": 1,
    },
    "demo-local-4021": {
        "governance_type": "Labor Union Local",
        "display_order": 2,
    },
    "demo-westgate-coalition": {
        "governance_type": "Civic Advocacy Group",
        "display_order": 3,
    },
}


# =============================================================================
# Cross-org user mapping (Stage 8 §5)
# =============================================================================


# (per-org-user-id) → underlying User.username
CROSS_ORG_USER_MAP: dict[str, str] = {
    # Marcus Pham — HOA + Coalition
    "hoa_marcus": "marcus_pham",
    "coalition_marcus": "marcus_pham",
    # Dana Whitfield — Local + Coalition
    "local_dana": "dana_whitfield",
    "coalition_dana": "dana_whitfield",
    # Janet Reilly — HOA + Local
    "hoa_janet": "janet_reilly",
    "local_janet": "janet_reilly",
}


# Phase 23.1 B2: explicit display-name mapping for non-quick-login
# candidate user_ids whose title-case fallback ("Local Trustee Marcus
# Reeves") would render confusingly in the ProposalOption.label / candidate
# card surfaces. Keys are bible user_ids; values are the desired
# User.display_name on first seed. Existing bible Member rows (Frank
# Boczek, Marisol Vega, etc.) don't need entries here because they're
# already in the MEMBERS list and seeded with their canonical display_name.
CANDIDATE_DISPLAY_NAMES: dict[str, str] = {
    # P-L-06 STV trustee candidates (4 of 5; Frank Boczek is a bible
    # MEMBER and uses his existing display_name)
    "local_trustee_marcus_reeves": "Marcus Reeves",
    "local_trustee_diana_sosa": "Diana Sosa",
    "local_trustee_will_park": "Will Park",
    "local_trustee_maria_santos": "Maria Santos",
}


def _candidate_display_name(bible_user_id: str) -> str:
    """Best display name for a non-bible-member candidate user_id.

    Falls back to title-case-with-spaces if no explicit mapping. The
    fallback works for one-word user_ids ("local_marisol" → "Local
    Marisol") but is awkward for the longer "local_trustee_*" pattern,
    which is why ``CANDIDATE_DISPLAY_NAMES`` exists.
    """
    if bible_user_id in CANDIDATE_DISPLAY_NAMES:
        return CANDIDATE_DISPLAY_NAMES[bible_user_id]
    return bible_user_id.replace("_", " ").title()


def _underlying_username(bible_user_id: str) -> str:
    """Map per-org user_id → underlying User.username.

    Non-cross-org IDs pass through unchanged.
    """
    return CROSS_ORG_USER_MAP.get(bible_user_id, bible_user_id)


# =============================================================================
# Janet's Local 4021 votes (Stage 8 §3)
# =============================================================================


# Proposal ID → vote_value (for binary proposals). Janet votes on most major
# Local proposals but rarely engages publicly (private delegate visibility).
# P-L-03 / P-L-08 (sub-org-only) and P-L-06 (STV at reset) skipped.
JANET_LOCAL_VOTES: dict[str, str] = {
    "P-L-01": "yes",
    "P-L-02": "yes",
    "P-L-05": "yes",
    "P-L-07": "yes",
    "P-L-09": "yes",
    "P-L-10": "yes",
}
# P-L-04 (Aisha Robinson first-choice) + P-L-06 are handled separately if
# the seed pipeline reaches the multi-option allocation path; the binary
# table above is the load-bearing subset for Stage 8's "centrist Local
# voting record" contrast with her HOA fiscal moderation.


# =============================================================================
# Notification message templates (Amendment A)
# =============================================================================


NOTIFICATION_MESSAGE_TEMPLATES: dict[str, str] = {
    "halfway_deadline":
        "Voting closes in {hours_remaining}h on '{proposal_title}'",
    "voting_open":
        "Voting is now open on '{proposal_title}'",
    "voting_closed":
        "Voting closed on '{proposal_title}' — {outcome}",
    "delegate_voted":
        "{delegate_display_name} voted on '{proposal_title}'",
    "delegate_vote_changed":
        "{delegate_display_name} changed their vote on '{proposal_title}'",
    "delegator_voted":
        "{delegator_display_name} voted directly on '{proposal_title}'",
    "delegator_vote_change":
        "{delegator_display_name} changed their vote on '{proposal_title}'",
    "delegate_posted_rationale":
        "{delegate_display_name} posted a rationale on '{proposal_title}'",
    "delegator_rationale":
        "{delegator_display_name} posted a rationale on '{proposal_title}'",
    "new_follow":
        "{follower_display_name} is now following you on {topic}",
    "new_follow_on_draft":
        "{follower_display_name} is following your draft '{proposal_title}'",
    "halfway_delegate_silent":
        "Your delegate {delegate_display_name} hasn't voted yet on "
        "'{proposal_title}' (voting halfway through)",
    "halfway_you_havent_voted":
        "You haven't voted yet on '{proposal_title}' (voting halfway through)",
    "proposal_advanced":
        "'{proposal_title}' has moved to {new_status}",
}


# =============================================================================
# State-at-reset parsing
# =============================================================================


_VOTING_HOUR_RE = re.compile(r"voting,?\s*hour\s+(\d+)\s+of\s+(\d+)", re.IGNORECASE)
_DELIB_HOUR_RE = re.compile(r"deliberation,?\s*hour\s+(\d+)\s+of\s+(\d+)", re.IGNORECASE)
_DAYS_AGO_RE = re.compile(r"(\d+)\s+days?\s+ago", re.IGNORECASE)


def _resolve_proposal_status_and_times(
    state_at_reset: str,
    voting_method: str,
    now: datetime,
) -> tuple[str, Optional[datetime], Optional[datetime], Optional[datetime]]:
    """Parse a ``state_at_reset`` string into status + timestamps.

    Returns ``(status, deliberation_start, voting_start, voting_end)``.
    Defaults to "passed" if nothing parseable.
    """
    s = (state_at_reset or "").lower().strip()

    if "draft" in s:
        return ("draft", None, None, None)

    if "failed quorum" in s:
        days_ago = 30
        m = _DAYS_AGO_RE.search(s)
        if m:
            days_ago = int(m.group(1))
        voting_start = now - timedelta(days=days_ago, hours=72)
        voting_end = now - timedelta(days=days_ago)
        return ("failed", voting_start - timedelta(days=7), voting_start, voting_end)

    if "deliberation" in s:
        # "deliberation, hour 36 of 168"
        m = _DELIB_HOUR_RE.search(s)
        if m:
            hour = int(m.group(1))
            of = int(m.group(2))
            delib_start = now - timedelta(hours=hour)
            voting_start = delib_start + timedelta(hours=of)
            # voting_end is when voting closes; voting is configured at advance-time
            return ("deliberation", delib_start, voting_start, None)
        return ("deliberation", now - timedelta(days=2), None, None)

    if "voting" in s and "ago" not in s:
        # "voting, hour 18 of 72"
        m = _VOTING_HOUR_RE.search(s)
        if m:
            hour = int(m.group(1))
            of = int(m.group(2))
            voting_start = now - timedelta(hours=hour)
            voting_end = voting_start + timedelta(hours=of)
            return ("voting", voting_start - timedelta(days=7), voting_start, voting_end)
        # Fallback: middle of a 72h window
        voting_start = now - timedelta(hours=36)
        voting_end = now + timedelta(hours=36)
        return ("voting", voting_start - timedelta(days=7), voting_start, voting_end)

    # "passed, 14 days ago" / "failed, 7 days ago"
    days_ago = 7
    m = _DAYS_AGO_RE.search(s)
    if m:
        days_ago = int(m.group(1))
    voting_start = now - timedelta(days=days_ago, hours=72)
    voting_end = now - timedelta(days=days_ago)
    if "failed" in s:
        return ("failed", voting_start - timedelta(days=7), voting_start, voting_end)
    return ("passed", voting_start - timedelta(days=7), voting_start, voting_end)


# =============================================================================
# Topic resolution
# =============================================================================


_TOPIC_COLOR_PALETTE = [
    "#6366f1", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6",
    "#06b6d4", "#84cc16", "#ec4899", "#0ea5e9", "#f97316",
]


def _collect_topic_names_from_bible(bible: OrgBible) -> list[str]:
    """Walk the bible to collect every topic name referenced.

    Drawn from ``DelegatePage.topics`` + ``DelegatePage.position_statements``
    (each carries a ``topic`` field). Returns a sorted-deduped list.
    """
    names: set[str] = set()
    for dp in bible.delegate_pages:
        for tv in (dp.topics or []):
            if tv.topic:
                names.add(tv.topic)
        for ps in (dp.position_statements or []):
            if ps.topic:
                names.add(ps.topic)
    return sorted(names)


# =============================================================================
# Trajectory lookup
# =============================================================================


def _trajectory_for_proposal(proposal_id: str):
    """Look up ``Trajectory`` by proposal_id from ``trajectory_waypoints``.

    Returns None when not found (e.g., draft proposals with no waypoints).
    """
    from . import trajectory_waypoints as tw
    # Convert "P-H-01" → "P_H_01"
    attr = proposal_id.replace("-", "_")
    return getattr(tw, attr, None)


# =============================================================================
# User + role helpers
# =============================================================================


def _ensure_user(
    db: Session,
    username: str,
    display_name: str,
    *,
    is_admin: bool = False,
) -> "models.User":
    """Find-or-create a User by username. Persists with a dummy password."""
    import models
    from auth import hash_password

    user = db.query(models.User).filter(
        models.User.username == username,
    ).first()
    if user:
        return user
    user = models.User(
        username=username,
        display_name=display_name,
        password_hash=hash_password(f"demo-{username}-noop"),
        is_admin=is_admin,
        email=f"{username}@demo.example",
        email_verified=True,
    )
    db.add(user)
    db.flush()
    return user


def _member_role_for_org(db: Session, org_id: str) -> Optional[str]:
    """Return the ``member`` role ID for this org, or None if not seeded."""
    import models
    role = db.query(models.Role).filter(
        models.Role.org_id == org_id,
        models.Role.system_key == "member",
    ).first()
    return role.id if role else None


def _ensure_membership(
    db: Session, user_id: str, org_id: str, role_id: str,
) -> "models.OrgMembership":
    """Find-or-create OrgMembership row.

    Phase 23.2 B2.2: if an existing membership has a different role_id
    than the bible currently specifies (e.g. seed re-runs without a
    full wipe), update it. This keeps role assignment authoritative
    relative to the bible, which is what the seed pipeline is meant to
    enforce.
    """
    import models
    m = db.query(models.OrgMembership).filter(
        models.OrgMembership.user_id == user_id,
        models.OrgMembership.org_id == org_id,
    ).first()
    if m:
        if m.role_id != role_id:
            m.role_id = role_id
            db.flush()
        return m
    m = models.OrgMembership(
        user_id=user_id, org_id=org_id, role_id=role_id, status="active",
    )
    db.add(m)
    db.flush()
    return m


def _seed_relationships(
    db: Session,
    bible: OrgBible,
    org,
    bible_uid_to_user: dict,
    topics_by_name: dict,
    now: datetime,
) -> None:
    """Phase 29 C4 — seed follows + private delegations from the bible.

    Follows produce FollowRequest rows (and FollowRelationship rows for
    approved entries). Private delegations require a matching
    delegation_allowed follow above (or a public_accepting DelegateProfile
    on the topic); entries without a path are logged and skipped.

    Each Delegation also gets a TopicPrecedence row per Phase 28 B1.
    Priority assignment uses 100 + per-delegator index so concurrent
    delegations sort deterministically without colliding on the unique
    (user_id, topic_id) key.
    """
    import models

    org_id = org.id

    # ---- Follows -------------------------------------------------------
    for fs in bible.follows:
        follower = bible_uid_to_user.get(fs.follower_user_id)
        followed = bible_uid_to_user.get(fs.followed_user_id)
        if follower is None or followed is None:
            log.warning(
                "seed_pipeline._seed_relationships: skipping follow "
                "(%s → %s) — unknown bible user_id",
                fs.follower_user_id, fs.followed_user_id,
            )
            continue
        if fs.status == "approved" and fs.permission_level is None:
            log.warning(
                "seed_pipeline._seed_relationships: approved follow "
                "(%s → %s) missing permission_level; skipping",
                fs.follower_user_id, fs.followed_user_id,
            )
            continue

        req = models.FollowRequest(
            requester_id=follower.id,
            target_id=followed.id,
            org_id=org_id,
            status=fs.status,
            permission_level=fs.permission_level,
            requested_at=now,
            responded_at=now if fs.status == "approved" else None,
        )
        db.add(req)

        if fs.status == "approved":
            rel = models.FollowRelationship(
                follower_id=follower.id,
                followed_id=followed.id,
                org_id=org_id,
                permission_level=fs.permission_level,
                created_at=now,
            )
            db.add(rel)
    db.flush()

    # ---- Private delegations ------------------------------------------
    # Track per-delegator topic-precedence priority counter so new
    # private-delegation rows assign monotonically-increasing priorities
    # that won't collide with whatever Phase 28's auto-precedence logic
    # will create later for the public delegations.
    precedence_counters: dict[str, int] = {}

    for pds in bible.private_delegations:
        delegator = bible_uid_to_user.get(pds.delegator_user_id)
        delegate = bible_uid_to_user.get(pds.delegate_user_id)
        if delegator is None or delegate is None:
            log.warning(
                "seed_pipeline._seed_relationships: skipping private "
                "delegation %s → %s — unknown bible user_id",
                pds.delegator_user_id, pds.delegate_user_id,
            )
            continue

        # topics_by_name is keyed by the bible's unscoped topic name
        # (e.g. "Budget"), not the slug-scoped DB name.
        topic = topics_by_name.get(pds.topic)
        if topic is None:
            log.warning(
                "seed_pipeline._seed_relationships: skipping private "
                "delegation %s → %s on topic %r — topic not seeded",
                pds.delegator_user_id, pds.delegate_user_id, pds.topic,
            )
            continue

        # Verify a matching delegation_allowed follow exists in THIS
        # bible's follows list. Cheap O(N) over the FOLLOWS list; this
        # is seed-time, not request-time.
        has_follow = any(
            fs.follower_user_id == pds.delegator_user_id
            and fs.followed_user_id == pds.delegate_user_id
            and fs.status == "approved"
            and fs.permission_level == "delegation_allowed"
            for fs in bible.follows
        )
        if not has_follow:
            log.warning(
                "seed_pipeline._seed_relationships: skipping private "
                "delegation %s → %s — no backing delegation_allowed follow",
                pds.delegator_user_id, pds.delegate_user_id,
            )
            continue

        deleg = models.Delegation(
            delegator_id=delegator.id,
            delegate_id=delegate.id,
            org_id=org_id,
            topic_id=topic.id,
            chain_behavior=pds.chain_behavior,
            created_at=now,
            updated_at=now,
        )
        db.add(deleg)

        # Phase 28 B1 — every delegation gets a TopicPrecedence row.
        next_pri = precedence_counters.get(delegator.id, 100)
        precedence_counters[delegator.id] = next_pri + 1
        existing = db.query(models.TopicPrecedence).filter(
            models.TopicPrecedence.user_id == delegator.id,
            models.TopicPrecedence.topic_id == topic.id,
        ).first()
        if existing is None:
            db.add(models.TopicPrecedence(
                user_id=delegator.id,
                topic_id=topic.id,
                priority=next_pri,
            ))
    db.flush()


def _seed_persona_delegations(
    db: Session,
    bible: OrgBible,
    org,
    bible_uid_to_user: dict,
    topics_by_name: dict,
) -> None:
    """Phase 29.1 B1.3 — seed quick-login persona delegations from the
    bible's ``persona_delegations`` list.

    For each spec:
      1. Write ``delegation_strategy`` to ``User.delegation_strategy``
         (overriding the Phase 27 migration default of
         ``relevance_weighted`` where the bible disagrees — Don is the
         only such case in Cedar Hollow).
      2. Create one ``TopicPrecedence`` row per entry in
         ``topic_precedence`` (priority = index, lower wins).
      3. Create one ``Delegation`` row per entry in ``delegations``.

    Validation is strict — raises ``ValueError`` on missing topics or
    unknown delegate user_ids so content-authoring mistakes surface at
    seed time rather than as silent runtime bugs. Don's empty
    delegations/precedence is correct and just skips the inner loops.
    """
    import models

    for spec in bible.persona_delegations:
        delegator = bible_uid_to_user.get(spec.delegator_user_id)
        if delegator is None:
            log.warning(
                "seed_pipeline._seed_persona_delegations: unknown "
                "delegator_user_id %r — skipping",
                spec.delegator_user_id,
            )
            continue

        # B2 — override Phase 27's migrated default per the bible.
        delegator.delegation_strategy = spec.delegation_strategy

        # Validate every delegated topic appears in topic_precedence.
        precedence_set = set(spec.topic_precedence)
        for topic_name, _ in spec.delegations:
            if topic_name not in precedence_set:
                raise ValueError(
                    f"persona_delegations for {spec.delegator_user_id}: "
                    f"topic {topic_name!r} in delegations but not in "
                    f"topic_precedence. Add it to topic_precedence with "
                    f"the desired priority order."
                )

        # Wipe any existing TopicPrecedence rows for this user before
        # writing the bible-specified ordering. Without this, a re-seed
        # would hit the unique (user_id, topic_id) constraint when the
        # bible reuses topics the user already has precedence rows on
        # (e.g., Brenda's Phase 28 B3 backfill rows).
        if spec.topic_precedence:
            existing_topic_ids = [
                topics_by_name[t].id for t in spec.topic_precedence
                if t in topics_by_name
            ]
            if existing_topic_ids:
                db.query(models.TopicPrecedence).filter(
                    models.TopicPrecedence.user_id == delegator.id,
                    models.TopicPrecedence.topic_id.in_(existing_topic_ids),
                ).delete(synchronize_session=False)

        for idx, topic_name in enumerate(spec.topic_precedence):
            topic = topics_by_name.get(topic_name)
            if topic is None:
                raise ValueError(
                    f"persona_delegations: unknown topic "
                    f"{topic_name!r} in precedence for "
                    f"{spec.delegator_user_id}"
                )
            db.add(models.TopicPrecedence(
                user_id=delegator.id,
                topic_id=topic.id,
                priority=idx,
            ))

        for topic_name, delegate_uid in spec.delegations:
            delegate = bible_uid_to_user.get(delegate_uid)
            if delegate is None:
                raise ValueError(
                    f"persona_delegations: unknown delegate "
                    f"{delegate_uid!r} in delegations for "
                    f"{spec.delegator_user_id}"
                )
            topic = topics_by_name[topic_name]
            db.add(models.Delegation(
                delegator_id=delegator.id,
                delegate_id=delegate.id,
                org_id=org.id,
                topic_id=topic.id,
                chain_behavior="accept_sub",
            ))

        db.flush()
        log.info(
            "seed_pipeline: persona %s strategy=%s — %d delegations, "
            "%d precedence rows",
            spec.delegator_user_id,
            spec.delegation_strategy,
            len(spec.delegations),
            len(spec.topic_precedence),
        )


# =============================================================================
# Main orchestrator
# =============================================================================


def seed_org_from_bible(
    db: Session,
    bible: OrgBible,
    config: Optional[dict] = None,
    *,
    now: Optional[datetime] = None,
) -> dict:
    """Idempotently seed one demo org from its bible.

    The wipe step is the caller's responsibility (``demo_reset_job``);
    this function is purely additive. Returns a counts dict for the
    audit-log entry.
    """
    import models
    from role_seed import seed_default_roles_for_org

    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    config = config or ORG_SEED_CONFIG.get(bible.slug, {})

    counts = {
        "users_created": 0,
        "members_created": 0,
        "topics_created": 0,
        "proposals_created": 0,
        "comments_created": 0,
        "votes_created": 0,
        "snapshots_created": 0,
        "notifications_created": 0,
        "fillers_created": 0,
    }

    # ---- 1. Organization upsert ------------------------------------------
    org = db.query(models.Organization).filter(
        models.Organization.slug == bible.slug,
    ).first()
    # ``org.is_demo`` is the wipe/seed boundary — must stay True for any
    # bible-seeded org so the daily reset cycle keeps catching it. The
    # Phase 29 C1 "hide from /demo listing" semantic is layered on top via
    # ``settings['hidden_from_demo_listing']`` (set below).
    if org is None:
        org = models.Organization(
            slug=bible.slug,
            name=bible.display_name,
            description=bible.charter,
            join_policy="open",
            is_demo=True,
        )
        db.add(org)
        db.flush()
        seed_default_roles_for_org(db, org.id)
    else:
        org.name = bible.display_name
        org.description = bible.charter
        org.is_demo = True
        org.is_demo_resetting = False

    # Phase 29 C1 + C5: bible-controlled cosmetics. Both go through
    # Organization.settings so no schema migration is needed.
    settings = dict(org.settings or {})

    # C1 — hide from /demo public listing without breaking the seed/wipe
    # cycle. The bible field ``is_demo`` is misnamed for back-compat —
    # despite the name it controls listing visibility, not the wipe
    # boundary (which is org.is_demo).
    bible_listed = getattr(bible, "is_demo", True)
    settings["hidden_from_demo_listing"] = (not bible_listed)

    # C5 — brand color → user-facing branding slot consumed by
    # BrandingThemeApplier (Phase 12.7). None leaves branding untouched.
    # 29.1 B3.2 — logo_url joins it in the same branding sub-dict.
    brand_color = getattr(bible, "brand_color", None)
    logo_path = getattr(bible, "logo_path", None)
    if brand_color or logo_path:
        branding = dict(settings.get("branding") or {})
        if brand_color:
            branding["primary_color"] = brand_color
        if logo_path:
            branding["logo_url"] = logo_path
        settings["branding"] = branding

    org.settings = settings

    org.governance_type = config.get("governance_type")
    org.display_order = config.get("display_order")
    # Personas populated below once members are created (so display_name is canonical)

    member_role_id = _member_role_for_org(db, org.id)
    if member_role_id is None:
        # Defensive: seed_default_roles_for_org should have created this.
        seed_default_roles_for_org(db, org.id)
        member_role_id = _member_role_for_org(db, org.id)

    # ---- 2. Named members (with cross-org mapping) -----------------------
    # Map per-org bible user_id → ORM User instance for this seed pass.
    bible_uid_to_user: dict[str, "models.User"] = {}

    for m in bible.members:
        underlying = _underlying_username(m.user_id)
        user = _ensure_user(db, underlying, m.display_name)
        bible_uid_to_user[m.user_id] = user

        # Phase 29 C6 — wire portrait. Only HOA bible carries portraits;
        # files live at ``frontend/public/demo_assets/portraits/<uid>.jpg``
        # and serve from ``/demo_assets/portraits/<uid>.jpg`` at runtime.
        # Other bibles (Local 4021, Coalition) leave avatar_url untouched
        # so cross-org users keep the HOA portrait the HOA seed assigned.
        if bible.slug == "demo-cedar-hollow":
            user.avatar_url = f"/demo_assets/portraits/{m.user_id}.jpg"

        # Phase 23.2 B2.2 — look up the per-org Role that matches this
        # member's bible-declared platform_role. Cross-org users (Marcus,
        # Dana, Janet) get separate OrgMembership rows per org with
        # potentially different role_ids — naturally handled by this loop
        # since each bible seeds its own org.
        target_role_key = (m.platform_role or "member").strip().lower()
        target_role = db.query(models.Role).filter(
            models.Role.org_id == org.id,
            models.Role.system_key == target_role_key,
        ).first()
        if target_role is None:
            log.warning(
                "seed_pipeline: platform_role %r not found in org %s; "
                "falling back to 'member'",
                target_role_key, bible.slug,
            )
            target_role = db.query(models.Role).filter(
                models.Role.org_id == org.id,
                models.Role.system_key == "member",
            ).first()

        _ensure_membership(db, user.id, org.id, target_role.id)
        counts["users_created"] += 1
        counts["members_created"] += 1

    # ---- 3. Personas JSON (D22, Amendment D) -----------------------------
    # Phase 23.1 (C4): description sourced from QUICK_LOGIN_DESCRIPTIONS
    # (Stage 8 §6 verbatim) keyed on bible user_id; falls back to role for
    # any quick-login member not in the dict (defensive — Stage 8 covers all
    # 18 current quick-login characters).
    org.personas = [
        {
            "username": bible_uid_to_user[m.user_id].username,
            "display_name": m.display_name,
            "role": m.role or "Member",
            "description": QUICK_LOGIN_DESCRIPTIONS.get(
                m.user_id, m.role or "Member",
            ),
            # Phase 30 B3: surface the User.avatar_url (wired by Phase 29 C6)
            # into the personas JSONB so /demo's quick-login tiles render
            # the AI-illustration portrait. None falls back to the default
            # initials circle in Avatar.jsx.
            "avatar_url": bible_uid_to_user[m.user_id].avatar_url,
        }
        for m in bible.members if m.quick_login
        and m.user_id in bible_uid_to_user
    ]

    # ---- 4. Topics --------------------------------------------------------
    topic_names = _collect_topic_names_from_bible(bible)
    topics_by_name: dict[str, "models.Topic"] = {}
    for idx, name in enumerate(topic_names):
        # Topic name has a global unique constraint; prefix with org slug to
        # avoid cross-org collisions while keeping the bible's intent.
        scoped_name = f"{bible.slug}:{name}"
        topic = db.query(models.Topic).filter(
            models.Topic.name == scoped_name,
        ).first()
        if topic is None:
            topic = models.Topic(
                name=scoped_name,
                description=name,
                color=_TOPIC_COLOR_PALETTE[idx % len(_TOPIC_COLOR_PALETTE)],
                org_id=org.id,
            )
            db.add(topic)
            db.flush()
            counts["topics_created"] += 1
        topics_by_name[name] = topic

    # ---- 5. Delegate pages (DelegateProfile + OrgDelegateProfile) --------
    for dp in bible.delegate_pages:
        user = bible_uid_to_user.get(dp.member_user_id)
        if not user:
            log.warning("seed: delegate_page references unknown user %r", dp.member_user_id)
            continue
        # OrgDelegateProfile (per-org identity intro)
        odp = db.query(models.OrgDelegateProfile).filter(
            models.OrgDelegateProfile.user_id == user.id,
            models.OrgDelegateProfile.org_id == org.id,
        ).first()
        if odp is None:
            # Map page_visibility 'public' → 'private' on stored col (effective
            # public comes from non-private topic profiles per D3).
            stored_pv = dp.page_visibility if dp.page_visibility in (
                "private", "private_delegators",
            ) else "private"
            odp = models.OrgDelegateProfile(
                user_id=user.id,
                org_id=org.id,
                intro=dp.intro or "",
                page_visibility=stored_pv,
            )
            db.add(odp)
            db.flush()
        else:
            odp.intro = dp.intro or odp.intro

        # Per-topic DelegateProfile rows
        for tv in (dp.topics or []):
            topic = topics_by_name.get(tv.topic)
            if topic is None:
                continue
            dp_row = db.query(models.DelegateProfile).filter(
                models.DelegateProfile.user_id == user.id,
                models.DelegateProfile.topic_id == topic.id,
            ).first()
            if dp_row is None:
                # Look up position statement for this topic
                pos_stmt = next(
                    (ps.text for ps in (dp.position_statements or [])
                     if ps.topic == tv.topic),
                    None,
                )
                dp_row = models.DelegateProfile(
                    user_id=user.id,
                    topic_id=topic.id,
                    org_id=org.id,
                    bio=dp.intro or "",
                    visibility=tv.state,
                    position_statement=pos_stmt,
                    is_active=True,
                )
                if tv.state == "public_accepting":
                    dp_row.public_accepting_submitted_at = now
                    dp_row.public_accepting_approved_at = now
                db.add(dp_row)
                db.flush()

    # ---- 5.5 Phase 29 C4 — follows + private delegations -----------------
    # Named-only relationships. Each FollowSeed becomes a FollowRequest
    # row (status/permission per the seed); approved ones additionally
    # produce a FollowRelationship. Each PrivateDelegationSeed becomes
    # a Delegation row + the matching TopicPrecedence row (Phase 28 B1).
    _seed_relationships(
        db=db,
        bible=bible,
        org=org,
        bible_uid_to_user=bible_uid_to_user,
        topics_by_name=topics_by_name,
        now=now,
    )

    # ---- 5.6 Phase 29.1 B1.3 — quick-login persona delegations -----------
    # Strict validation; raises if any delegated topic isn't in the
    # corresponding topic_precedence list.
    _seed_persona_delegations(
        db=db,
        bible=bible,
        org=org,
        bible_uid_to_user=bible_uid_to_user,
        topics_by_name=topics_by_name,
    )

    # ---- 6. Proposals (PROPOSALS + DRAFTS) -------------------------------
    proposals_by_bible_id: dict[str, "models.Proposal"] = {}
    proposal_records: list[BibleProposal] = list(bible.proposals) + list(bible.drafts)

    for bp in proposal_records:
        author = bible_uid_to_user.get(bp.proposer_user_id)
        if not author:
            # Some election proposals reference non-quick-login candidates
            # by user_id; make sure we have a user for them.
            author = _ensure_user(
                db, bp.proposer_user_id, bp.proposer_user_id.replace("_", " ").title(),
            )
            _ensure_membership(db, author.id, org.id, member_role_id)
            bible_uid_to_user[bp.proposer_user_id] = author

        status, delib_start, vote_start, vote_end = (
            _resolve_proposal_status_and_times(bp.state_at_reset, bp.voting_method, now)
        )

        # Phase 23.2 B3 — translate the bible's voting_method string to a
        # value the cast_vote endpoint accepts. The bible vocabulary
        # ('binary' | 'approval' | 'rcv' | 'stv') is content-author-
        # friendly. The DB / vote handler vocabulary is
        # ('binary' | 'approval' | 'ranked_choice'). RCV and STV both ride
        # ranked_choice; STV is distinguished by Proposal.num_winners > 1
        # at tally time.
        bible_method = bp.voting_method
        if bible_method in ('rcv', 'stv'):
            db_voting_method = 'ranked_choice'
        else:
            db_voting_method = bible_method  # 'binary' or 'approval' pass through

        proposal = models.Proposal(
            title=bp.title,
            body=bp.body,
            author_id=author.id,
            org_id=org.id,
            status=status,
            voting_method=db_voting_method,
            num_winners=bp.num_winners,
            deliberation_start=delib_start,
            voting_start=vote_start,
            voting_end=vote_end,
            pass_threshold=0.50,
            quorum_threshold=bible.quorum_threshold_default,
        )
        db.add(proposal)
        db.flush()
        proposals_by_bible_id[bp.proposal_id] = proposal
        counts["proposals_created"] += 1

        # Proposal options for multi-option proposals
        if bp.options:
            for idx, label in enumerate(bp.options):
                opt = models.ProposalOption(
                    proposal_id=proposal.id,
                    label=label,
                    display_order=idx,
                )
                db.add(opt)
            db.flush()

        # Candidate statements (RCV/STV): make sure each candidate has a
        # user, then (Phase 23.1 B1) create one ProposalOption per
        # candidate when ``bp.options`` is empty. Without these rows the
        # voting UI has nothing to rank and falls back to Yes/No.
        candidate_order: list[tuple[str, "models.User"]] = []
        for cand_uid, statement in (bp.candidate_statements or {}).items():
            if cand_uid not in bible_uid_to_user:
                underlying = _underlying_username(cand_uid)
                cand_user = _ensure_user(
                    db, underlying, _candidate_display_name(cand_uid),
                )
                _ensure_membership(db, cand_user.id, org.id, member_role_id)
                bible_uid_to_user[cand_uid] = cand_user
            candidate_order.append((cand_uid, bible_uid_to_user[cand_uid]))

        if not bp.options and candidate_order:
            for idx, (cand_uid, cand_user) in enumerate(candidate_order):
                statement = (bp.candidate_statements or {}).get(cand_uid, "")
                opt = models.ProposalOption(
                    proposal_id=proposal.id,
                    label=cand_user.display_name,
                    description=statement or "",
                    display_order=idx,
                )
                db.add(opt)
            db.flush()

        # ---- B2.1 — ProposalTopic associations from bp.topics ----
        # Phase 23.2 replaces the previous Phase 23.1 B3a-extra
        # backwards-inference heuristic (which built proposal→topic links
        # from delegate-page vote_rationales) with explicit bp.topics
        # metadata authored in the bibles. First topic in the list is the
        # primary topic; secondary topics fall off in `relevance`.
        # Unknown topic names log a loud error and are skipped — the seed
        # still completes for the rest of the org. Production-shape note:
        # ProposalTopic has composite PK (proposal_id, topic_id) +
        # relevance: Float default 1.0 (see models.py:545). The relevance
        # ordering signal is what the delegation engine inspects when
        # resolving multi-topic delegators.
        for idx, topic_name in enumerate(bp.topics or []):
            topic = topics_by_name.get(topic_name)
            if topic is None:
                log.error(
                    "seed_pipeline: proposal %s references unknown topic %r "
                    "(org %s); skipping association",
                    bp.proposal_id, topic_name, bible.slug,
                )
                continue
            existing_pt = db.query(models.ProposalTopic).filter(
                models.ProposalTopic.proposal_id == proposal.id,
                models.ProposalTopic.topic_id == topic.id,
            ).first()
            if existing_pt is not None:
                continue
            # First topic = primary (relevance 1.0). Secondaries fall off
            # by 0.2 per position, floored at 0.1.
            relevance = 1.0 if idx == 0 else max(0.1, 1.0 - 0.2 * idx)
            db.add(models.ProposalTopic(
                proposal_id=proposal.id,
                topic_id=topic.id,
                relevance=relevance,
            ))
        db.flush()

    # ---- 7. Named-character votes (from DelegatePage.vote_rationales) ----
    new_votes: list = []
    for dp in bible.delegate_pages:
        voter = bible_uid_to_user.get(dp.member_user_id)
        if not voter:
            continue
        for vr in (dp.vote_rationales or []):
            proposal = proposals_by_bible_id.get(vr.proposal_id)
            if not proposal or proposal.voting_start is None:
                continue
            # Skip if a vote already exists (idempotency).
            existing = db.query(models.Vote).filter(
                models.Vote.proposal_id == proposal.id,
                models.Vote.user_id == voter.id,
            ).first()
            if existing:
                continue

            # Decode vote string per bible convention.
            vote_value = None
            ballot = None
            v = (vr.vote or "").lower().strip()
            if v in ("yes", "no", "abstain"):
                vote_value = v
            elif v.startswith("approval_") or v.startswith("rcv_") or v.startswith("stv_"):
                # Parse e.g. "approval_1_2_3" → option indices 1, 2, 3
                tail = v.split("_", 1)[1]
                indices = [int(x) for x in tail.split("_") if x.isdigit()]
                option_ids = []
                for i in indices:
                    if 1 <= i <= len(proposal.options or []):
                        option_ids.append(proposal.options[i - 1].id)
                if v.startswith("approval_"):
                    ballot = {"approvals": option_ids}
                else:
                    ballot = {"ranking": option_ids}

            # Backdated cast_at: midway through voting window
            cast_at = proposal.voting_start + (
                (proposal.voting_end - proposal.voting_start) / 2
                if proposal.voting_end
                else timedelta(hours=12)
            )
            new_votes.append(models.Vote(
                proposal_id=proposal.id,
                user_id=voter.id,
                vote_value=vote_value,
                ballot=ballot,
                is_direct=True,
                cast_by_id=voter.id,
                cast_at=cast_at,
            ))
            counts["votes_created"] += 1

    # ---- 8. Janet's Local 4021 votes (Stage 8 §3) -----------------------
    if bible.slug == "demo-local-4021":
        janet_user = db.query(models.User).filter(
            models.User.username == "janet_reilly",
        ).first()
        if janet_user:
            # Ensure she has membership in Local
            _ensure_membership(db, janet_user.id, org.id, member_role_id)
            for pid, value in JANET_LOCAL_VOTES.items():
                proposal = proposals_by_bible_id.get(pid)
                if not proposal or proposal.voting_start is None:
                    continue
                existing = db.query(models.Vote).filter(
                    models.Vote.proposal_id == proposal.id,
                    models.Vote.user_id == janet_user.id,
                ).first()
                if existing:
                    continue
                cast_at = proposal.voting_start + (
                    (proposal.voting_end - proposal.voting_start) / 2
                    if proposal.voting_end
                    else timedelta(hours=12)
                )
                new_votes.append(models.Vote(
                    proposal_id=proposal.id,
                    user_id=janet_user.id,
                    vote_value=value,
                    ballot=None,
                    is_direct=True,
                    cast_by_id=janet_user.id,
                    cast_at=cast_at,
                ))
                counts["votes_created"] += 1

    # Bulk persist named votes before computing filler vote allocation
    if new_votes:
        db.bulk_save_objects(new_votes)
        db.flush()

    # ---- 9. Filler members ----------------------------------------------
    # Build delegate_pool from bible delegate_pages that have public_accepting topics.
    delegate_pool: list[tuple[str, str]] = []
    for dp in bible.delegate_pages:
        for tv in (dp.topics or []):
            if tv.state == "public_accepting":
                u = bible_uid_to_user.get(dp.member_user_id)
                if u:
                    delegate_pool.append((u.id, tv.topic))

    fillers = generate_filler_members(
        bible, target_count=55, delegate_pool=delegate_pool,
    )
    filler_user_ids: dict[str, str] = {}  # bible filler_user_id → DB User.id
    for f in fillers:
        u = _ensure_user(db, f.username, f.display_name)
        filler_user_ids[f.user_id] = u.id
        _ensure_membership(db, u.id, org.id, member_role_id)
        counts["fillers_created"] += 1
        counts["users_created"] += 1
    # Bulk-flush via SQLAlchemy already done in each _ensure_user above.

    # Filler delegations
    for f in fillers:
        if not f.delegates_to:
            continue
        delegator_uid = filler_user_ids.get(f.user_id)
        delegate_user_db_id, topic_name = f.delegates_to
        if not delegator_uid:
            continue
        topic = topics_by_name.get(topic_name)
        # No-op if topic missing.
        if not topic:
            continue
        existing = db.query(models.Delegation).filter(
            models.Delegation.delegator_id == delegator_uid,
            models.Delegation.delegate_id == delegate_user_db_id,
            models.Delegation.org_id == org.id,
            models.Delegation.topic_id == topic.id,
        ).first()
        if existing:
            continue
        db.add(models.Delegation(
            delegator_id=delegator_uid,
            delegate_id=delegate_user_db_id,
            org_id=org.id,
            topic_id=topic.id,
            chain_behavior="accept_sub",
        ))
    db.flush()

    # ---- 10. Filler vote allocation + snapshot generation ----------------
    from demo_snapshot_generator import generate_snapshots

    member_count_for_org = (
        db.query(models.OrgMembership)
        .filter(models.OrgMembership.org_id == org.id)
        .count()
    )

    # Phase 23.1 B3a: build the set of filler bible user_ids that have ANY
    # active delegation in this org. The seed pipeline does NOT create
    # ProposalTopic rows (proposals carry no explicit topic association),
    # so we cannot intersect the filler's delegation topics with the
    # proposal's topics. Per the dispatch's "conservative fallback"
    # provision, any filler with a delegation is excluded from direct
    # vote allocation - the tally resolver will follow the delegation to
    # the delegate's vote at tally time. The named-character delegate's
    # direct vote DOES get cast normally.
    fillers_with_delegations: set[str] = {
        f.user_id for f in fillers if f.delegates_to
    }

    all_snapshots: list = []
    all_filler_votes: list = []

    def _filler_resolver(filler_uid: str) -> Optional[str]:
        return filler_user_ids.get(filler_uid)

    for bp in proposal_records:
        proposal = proposals_by_bible_id.get(bp.proposal_id)
        if not proposal:
            continue
        trajectory = _trajectory_for_proposal(bp.proposal_id)
        # Snapshots: only for proposals in voting / past-voting status
        if (
            trajectory is not None
            and proposal.voting_start is not None
            and proposal.voting_end is not None
            and trajectory.waypoints
        ):
            snaps = generate_snapshots(
                proposal=proposal,
                trajectory=trajectory,
                voting_start=proposal.voting_start,
                voting_end=proposal.voting_end,
                cadence_seconds=1800,
                total_eligible=member_count_for_org,
            )
            all_snapshots.extend(snaps)

        # Filler votes (binary only — multi-option fallback in allocator)
        if (
            trajectory is not None
            and proposal.voting_start is not None
            and proposal.voting_end is not None
            and proposal.status in ("voting", "passed", "failed")
        ):
            # Determine participation: ~50% of fillers vote on this
            # proposal. Phase 23.1 B3a: filter out fillers with any
            # delegation so their delegate's vote is what shows in the
            # tally (defect C1).
            base_pool = fillers[: max(1, len(fillers) // 2)]
            participating = [
                f for f in base_pool
                if f.user_id not in fillers_with_delegations
            ]
            # Named-voter summary (yes/no/abstain counts already in new_votes)
            named_summary: dict = {"yes": 0, "no": 0, "abstain": 0}
            for v in new_votes:
                if v.proposal_id == proposal.id and v.vote_value in named_summary:
                    named_summary[v.vote_value] += 1
            filler_votes = allocate_filler_votes(
                proposal,
                trajectory,
                participating,
                named_voter_summary=named_summary,
                voting_start=proposal.voting_start,
                voting_end=proposal.voting_end,
                cast_by_resolver=_filler_resolver,
            )
            all_filler_votes.extend(filler_votes)

    if all_snapshots:
        db.bulk_save_objects(all_snapshots)
        counts["snapshots_created"] += len(all_snapshots)
        db.flush()
    if all_filler_votes:
        db.bulk_save_objects(all_filler_votes)
        counts["votes_created"] += len(all_filler_votes)
        db.flush()

    # ---- 11. Comments ----------------------------------------------------
    comments_to_add: list = []
    for c in bible.comments:
        proposal = proposals_by_bible_id.get(c.proposal_id)
        if not proposal:
            continue
        author = bible_uid_to_user.get(c.author_user_id)
        if not author:
            continue
        # Backdated created_at based on relative_timestamp text
        created_at = _parse_relative_timestamp(
            c.relative_timestamp, proposal, now,
        )
        comments_to_add.append(models.Comment(
            proposal_id=proposal.id,
            author_id=author.id,
            body=c.body,
            created_at=created_at,
        ))
    if comments_to_add:
        db.bulk_save_objects(comments_to_add)
        counts["comments_created"] = len(comments_to_add)
        db.flush()

    # ---- 12. Notifications (Amendment A) ---------------------------------
    notifications_to_add: list = []
    for nf in bible.notification_feeds:
        recipient = bible_uid_to_user.get(nf.member_user_id)
        if not recipient:
            continue
        for evt in nf.events:
            related_proposal = (
                proposals_by_bible_id.get(evt.related_proposal_id)
                if evt.related_proposal_id else None
            )
            related_member = (
                bible_uid_to_user.get(evt.related_member_user_id)
                if evt.related_member_user_id else None
            )
            template = NOTIFICATION_MESSAGE_TEMPLATES.get(evt.event_type)
            if template is None:
                log.warning(
                    "seed_pipeline: unknown notification event_type=%r "
                    "(falling back to plain)", evt.event_type,
                )
                template = f"{evt.event_type}: {{note}}"

            payload = {
                "proposal_title": related_proposal.title if related_proposal else "",
                "proposal_id": related_proposal.id if related_proposal else None,
                "delegate_display_name": (
                    related_member.display_name if related_member else ""
                ),
                "delegator_display_name": (
                    related_member.display_name if related_member else ""
                ),
                "follower_display_name": (
                    related_member.display_name if related_member else ""
                ),
                "topic": "",
                "hours_remaining": 12,
                "outcome": "resolved",
                "new_status": "voting",
                "note": evt.note or "",
            }
            try:
                message = template.format(**payload)
            except Exception:
                message = f"{evt.event_type}: {evt.note or ''}"
            payload["message"] = message

            notifications_to_add.append(models.Notification(
                user_id=recipient.id,
                event_type=evt.event_type,
                org_id=org.id,
                target_type="proposal" if related_proposal else None,
                target_id=related_proposal.id if related_proposal else None,
                payload=payload,
                created_at=now - timedelta(hours=1),
            ))
    if notifications_to_add:
        db.bulk_save_objects(notifications_to_add)
        counts["notifications_created"] = len(notifications_to_add)
        db.flush()

    # ---- B2.3 — Coalition: grant proposal.create to the member role ----
    # The Westgate Tenants Coalition is the grassroots / member-led
    # demo org; its narrative requires open proposal authorship. This
    # is a demo-org-specific policy (not a universal default), so it
    # lives in the seed pipeline rather than role_seed.py. Idempotent:
    # the existence check prevents duplicate rows on repeated resets.
    if bible.slug == "demo-westgate-coalition":
        member_role = db.query(models.Role).filter(
            models.Role.org_id == org.id,
            models.Role.system_key == "member",
        ).first()
        if member_role is not None:
            existing_grant = db.query(models.RolePermission).filter(
                models.RolePermission.role_id == member_role.id,
                models.RolePermission.permission_key == "proposal.create",
            ).first()
            if existing_grant is None:
                db.add(models.RolePermission(
                    role_id=member_role.id,
                    permission_key="proposal.create",
                    enabled=True,
                ))
                db.flush()
            elif not existing_grant.enabled:
                existing_grant.enabled = True
                db.flush()

    return counts


# =============================================================================
# Helpers
# =============================================================================


def _parse_relative_timestamp(
    rel: str, proposal, now: datetime,
) -> datetime:
    """Best-effort parse of strings like "voting hour 30" / "deliberation hour 12".

    Returns a backdated datetime within the proposal's window when
    parseable; otherwise returns now-1d as a safe default.
    """
    if not rel:
        return now - timedelta(days=1)
    r = rel.lower()
    if "voting hour" in r and proposal.voting_start is not None:
        m = re.search(r"voting hour\s*(\d+)", r)
        if m:
            return proposal.voting_start + timedelta(hours=int(m.group(1)))
    if "deliberation hour" in r and proposal.deliberation_start is not None:
        m = re.search(r"deliberation hour\s*(\d+)", r)
        if m:
            return proposal.deliberation_start + timedelta(hours=int(m.group(1)))
    return (proposal.voting_start or proposal.deliberation_start or now) - timedelta(hours=1)


__all__ = [
    "seed_org_from_bible",
    "ORG_SEED_CONFIG",
    "CROSS_ORG_USER_MAP",
    "JANET_LOCAL_VOTES",
    "NOTIFICATION_MESSAGE_TEMPLATES",
]
