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

# Phase 34.2 D1 — distinct palette for sub-org topics so visitors can
# visually distinguish them from main-org topics in shared listing views
# (e.g., the main-org proposals page that surfaces sub-org proposals too).
# Same hue family but darker/saturated variants of the main palette,
# rotated so the first sub-org topic doesn't collide with the first
# main-org topic.
_SUB_ORG_TOPIC_COLOR_PALETTE = [
    "#7c3aed",  # purple
    "#0891b2",  # cyan/teal
    "#b45309",  # amber/brown
    "#be185d",  # pink/magenta
    "#15803d",  # darker green
    "#9333ea",  # violet
    "#0e7490",  # dark cyan
    "#a16207",  # ochre
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


def _tally_to_dict(tally, fallback_total_eligible: int) -> Optional[dict]:
    """Phase 36 B2: convert a ProposalTally / ApprovalTally / RCVTally
    into the ``terminal_tally`` dict shape consumed by
    ``demo_snapshot_generator.generate_snapshots(terminal_tally=...)``.

    Returns None for tally shapes we don't recognise.
    """
    from delegation_engine import ApprovalTally, ProposalTally, RCVTally

    eligible = int(
        getattr(tally, "total_eligible", 0) or fallback_total_eligible or 0
    )

    if isinstance(tally, ProposalTally):
        yes = int(tally.yes or 0)
        no = int(tally.no or 0)
        abstain = int(tally.abstain or 0)
        total_cast = yes + no + abstain
        return {
            "method": "binary",
            "yes": yes,
            "no": no,
            "abstain": abstain,
            "total_cast": total_cast,
            "not_cast": max(0, eligible - total_cast - abstain),
            "total_eligible": eligible,
        }

    if isinstance(tally, ApprovalTally):
        option_totals = {
            str(oid): int(count or 0)
            for oid, count in (tally.option_approvals or {}).items()
        }
        return {
            "method": "approval",
            "option_totals": option_totals,
            "winners": list(tally.winners or []),
            "total_cast": int(tally.total_ballots_cast or 0),
            "total_abstain": int(tally.total_abstain or 0),
            "not_cast": int(tally.not_cast or 0),
            "total_eligible": eligible,
        }

    if isinstance(tally, RCVTally):
        # Use first-round per-option counts as the "option_totals" for the
        # trajectory chart — that's the raw vote count for each option,
        # which is what the per-option line should grow toward.
        option_totals: dict = {}
        if tally.rounds:
            first_round = tally.rounds[0]
            option_totals = {
                str(oid): int(count or 0)
                for oid, count in (
                    getattr(first_round, "counts", {}) or {}
                ).items()
            }
        return {
            "method": "ranked_choice",
            "option_totals": option_totals,
            "winners": list(tally.winners or []),
            "total_cast": int(tally.total_ballots_cast or 0),
            "total_abstain": int(tally.total_abstain or 0),
            "not_cast": int(tally.not_cast or 0),
            "total_eligible": eligible,
        }

    return None


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


def _stamp_notification_preset(
    db: Session, user_id: str, preset: Optional[str],
) -> None:
    """Phase 31 N1.b — stamp a notification preset on a demo user,
    replacing any existing rows.

    Bible members + fillers may persist across resets (named bible
    members always do; fillers are wiped + recreated). To keep the
    bible's preset declaration authoritative on every reset, we drop
    any existing ``NotificationPreference`` rows for ``user_id`` and
    insert the preset's stamped row set.

    ``preset`` of None or empty string is a no-op (preserves the
    user's existing prefs).
    """
    if not preset:
        return
    import models
    from notification_events import (
        PRESET_STAMP_RULES, build_preset_preference_rows,
    )
    if preset not in PRESET_STAMP_RULES:
        log.warning(
            "_stamp_notification_preset: unknown preset %r for user %s; "
            "skipping",
            preset, user_id,
        )
        return
    (
        db.query(models.NotificationPreference)
        .filter(models.NotificationPreference.user_id == user_id)
        .delete(synchronize_session=False)
    )
    for row in build_preset_preference_rows(user_id, preset):
        db.add(row)
    db.flush()


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


def _seed_phase_32_2_demo_extras(
    db: Session,
    *,
    proposals_by_bible_id: dict,
    bible_uid_to_user: dict,
    org,
    now: datetime,
) -> None:
    """Phase 32.2 D1 + D2 — Cedar Hollow demo seeds.

    **D1 — ProposalRevision rows on P-H-10 (EV Charging).** Two
    revisions by Marcus (the author): a small title clarification +
    a description tweak. Shape mirrors what the PATCH-proposal
    endpoint writes via ``_snapshot_revisable_fields`` so the
    change-log accordion renders cleanly.

    **D2 — Spam write-in on P-H-13 (Community Garden) added + removed.**
    Adds an audit-log entry recording a filler member's write-in plus
    a steward's immediate removal. NO ProposalOption row is left
    behind (the removal happens at seed time); the audit trail is the
    artifact. P-H-13 already has its four committee options seeded;
    this just leaves a "Removed: 'buy now click here'" entry visible
    in the audit log surface.
    """
    import models
    from audit_utils import log_audit_event

    ev_proposal = proposals_by_bible_id.get("P-H-10")
    marcus = bible_uid_to_user.get("hoa_marcus")
    if ev_proposal is not None and marcus is not None:
        # D1 — only seed if no revisions already exist (idempotency).
        existing = (
            db.query(models.ProposalRevision)
            .filter(models.ProposalRevision.proposal_id == ev_proposal.id)
            .count()
        )
        if existing == 0:
            r1_before = {"title": "EV Charging Stations — Common Areas"}
            r1_after = {"title": ev_proposal.title}  # current canonical title
            db.add(models.ProposalRevision(
                proposal_id=ev_proposal.id,
                org_id=org.id,
                edited_by_user_id=marcus.id,
                edited_at=now - timedelta(hours=18),
                snapshot_before=r1_before,
                snapshot_after=r1_after,
                changed_fields=["title"],
            ))
            r2_before = {"body": ev_proposal.body[:120] + " [...]"}
            r2_after = {"body": ev_proposal.body[:120] + " [...] (clarified rationale)"}
            db.add(models.ProposalRevision(
                proposal_id=ev_proposal.id,
                org_id=org.id,
                edited_by_user_id=marcus.id,
                edited_at=now - timedelta(hours=6),
                snapshot_before=r2_before,
                snapshot_after=r2_after,
                changed_fields=["body"],
            ))
            db.flush()

    # D2 — spam write-in audit entries on P-H-13.
    cg_proposal = proposals_by_bible_id.get("P-H-13")
    janet = bible_uid_to_user.get("hoa_janet")  # admin who removes the spam
    if cg_proposal is not None and janet is not None:
        # Idempotency: check for the load-bearing audit-log entry.
        from sqlalchemy import or_, and_
        existing = (
            db.query(models.AuditLog)
            .filter(
                models.AuditLog.action == "proposal.option_removed",
                models.AuditLog.target_type == "proposal_option",
            )
            .filter(
                models.AuditLog.details.cast(models.JSON).is_not(None)
            )
            .all()
        )
        already_seeded = any(
            isinstance(a.details, dict)
            and a.details.get("proposal_id") == cg_proposal.id
            and a.details.get("label", "").lower().startswith("buy now")
            for a in existing
        )
        if not already_seeded:
            # Fake "added by spam_filler" — use a real filler user; the
            # add audit entry references a since-removed option_id.
            spam_label = "buy now click here"
            fake_option_id = f"removed-{cg_proposal.id[:8]}-spam"
            log_audit_event(
                db,
                action="proposal.option_added",
                target_type="proposal_option",
                target_id=fake_option_id,
                actor_id=janet.id,  # actor info-only; this is a seed
                details={
                    "proposal_id": cg_proposal.id,
                    "label": spam_label,
                    "is_write_in": True,
                    "_seed_note": "Phase 32.2 D2 — spam write-in demo seed.",
                },
            )
            log_audit_event(
                db,
                action="proposal.option_removed",
                target_type="proposal_option",
                target_id=fake_option_id,
                actor_id=janet.id,
                details={
                    "proposal_id": cg_proposal.id,
                    "label": spam_label,
                    "removed_by_role": "admin",
                    "_seed_note": "Phase 32.2 D2 — admin removed spam write-in.",
                },
            )
            db.flush()


def _seed_sub_org(
    db: Session,
    *,
    parent_org,
    sub_bible,
    bible_uid_to_user: dict,
    counts: dict,
    now: datetime,
) -> None:
    """Phase 34 B2/B3 — seed one sub-org from a bible SubOrg dataclass.

    Idempotent: re-runs find existing sub-org by slug + parent_org_id and
    refresh-update rather than create.

    Creates:
    - Organization with parent_org_id pointing at parent
    - SubOrgMembership rows for each declared member (FK uses parent's
      Role rows — Phase 15 Cluster S pattern; sub-orgs inherit the
      parent's matrix wholesale)
    - Sub-org admin gets the parent's 'admin' Role; others 'member'
    - Topic rows scoped via Topic.org_id=parent + Topic.sub_org_id=sub_org
    - DelegateProfile rows for visibilities, with sub_org_id set
    - Delegation rows for declared delegations, with sub_org_id set
      (exercises Phase 18's sub_org_id retrofit on relationship tables)
    - Proposal rows scoped via Proposal.org_id=parent + sub_org_id=sub_org
    """
    import models
    from role_seed import seed_default_roles_for_org

    # ---- Sub-org Organization row ----
    sub_org = db.query(models.Organization).filter(
        models.Organization.slug == sub_bible.slug,
        models.Organization.parent_org_id == parent_org.id,
    ).first()
    if sub_org is None:
        sub_org = models.Organization(
            slug=sub_bible.slug,
            name=sub_bible.name,
            description=sub_bible.description,
            join_policy="open",
            is_demo=True,
            parent_org_id=parent_org.id,
            governance_type=sub_bible.governance_type or None,
        )
        db.add(sub_org)
        db.flush()
    else:
        sub_org.name = sub_bible.name
        sub_org.description = sub_bible.description
        sub_org.governance_type = sub_bible.governance_type or sub_org.governance_type
        sub_org.is_demo = True

    # Phase 34.4 D1 — propagate sub-org's `private` bible field into
    # Organization.settings['private']. When True, Decision 7 visibility
    # filter (routes/sub_organizations.py:393) hides the sub-org from
    # non-members. Re-applied on every seed so the bible is the source
    # of truth (flipping `private` in the bible + reset reflects on prod).
    sub_settings = dict(sub_org.settings or {})
    sub_settings["private"] = bool(getattr(sub_bible, "private", False))
    sub_org.settings = sub_settings

    # Sub-orgs use the PARENT org's Role table (Phase 15 Cluster S).
    parent_member_role = (
        db.query(models.Role).filter(
            models.Role.org_id == parent_org.id,
            models.Role.system_key == "member",
        ).first()
    )
    parent_admin_role = (
        db.query(models.Role).filter(
            models.Role.org_id == parent_org.id,
            models.Role.system_key == "admin",
        ).first()
    )
    if parent_member_role is None or parent_admin_role is None:
        # Defensive: parent roles should exist by this point.
        seed_default_roles_for_org(db, parent_org.id)
        parent_member_role = (
            db.query(models.Role).filter(
                models.Role.org_id == parent_org.id,
                models.Role.system_key == "member",
            ).first()
        )
        parent_admin_role = (
            db.query(models.Role).filter(
                models.Role.org_id == parent_org.id,
                models.Role.system_key == "admin",
            ).first()
        )

    # ---- SubOrgMembership AND OrgMembership rows ----
    # The existing sub-org infrastructure (Phase 8.5 era) wired
    # SubOrgMembership for permission/role resolution but the standard
    # /api/orgs surface (org switcher, require_org_membership middleware,
    # OrgMembership-backed routes) only inspects OrgMembership. Real users
    # creating a sub-org via the UI got a SubOrgMembership but not an
    # OrgMembership, so they couldn't access /api/orgs/{sub_slug}/topics
    # etc. — the FE worked around this with the dedicated
    # /api/orgs/{parent}/sub-orgs/{sub}/* URL pattern.
    #
    # Phase 34 seeds BOTH SubOrgMembership (so the parent's Role matrix
    # applies to sub-org permission checks via effective_role_on_sub_org)
    # AND OrgMembership on the sub-org Organization itself (so /api/orgs
    # surfaces the sub-org in the user's org list and require_org_membership
    # passes for sub-org-prefixed routes). The seed-pipeline-side
    # duplication is intentional — it lets the demo exercise the full
    # sub-org UX without requiring a backend refactor of the existing
    # middleware patterns.
    for uid in sub_bible.member_user_ids:
        user = bible_uid_to_user.get(uid)
        if user is None:
            log.warning(
                "sub-org seed: unknown bible user_id %r in sub_org %r",
                uid, sub_bible.slug,
            )
            continue
        role_id = (
            parent_admin_role.id if uid == sub_bible.admin_user_id
            else parent_member_role.id
        )
        # SubOrgMembership (for sub-org-aware permission resolution)
        existing_sub = db.query(models.SubOrgMembership).filter(
            models.SubOrgMembership.user_id == user.id,
            models.SubOrgMembership.sub_org_id == sub_org.id,
        ).first()
        if existing_sub is None:
            db.add(models.SubOrgMembership(
                user_id=user.id,
                sub_org_id=sub_org.id,
                role_id=role_id,
                status="active",
            ))
        elif existing_sub.role_id != role_id:
            existing_sub.role_id = role_id
        # OrgMembership on the sub-org Organization (for /api/orgs +
        # require_org_membership). _ensure_membership upserts; safe to
        # re-call on re-seed.
        _ensure_membership(db, user.id, sub_org.id, role_id)
    db.flush()

    # ---- Topics (scoped to parent_org_id + sub_org_id) ----
    sub_topics_by_name: dict[str, "models.Topic"] = {}
    for idx, name in enumerate(sub_bible.topic_names):
        # Phase 34.2 D1 — sub-org topics use the dedicated sub-org palette so
        # they visually differentiate from the main org's topics in shared
        # listing surfaces. Color refreshed on re-seed (was a no-op on
        # update path which made the palette change invisible on re-runs).
        sub_color = _SUB_ORG_TOPIC_COLOR_PALETTE[idx % len(_SUB_ORG_TOPIC_COLOR_PALETTE)]
        topic = db.query(models.Topic).filter(
            models.Topic.name == name,
            models.Topic.org_id == parent_org.id,
            models.Topic.sub_org_id == sub_org.id,
        ).first()
        if topic is None:
            topic = models.Topic(
                name=name,
                color=sub_color,
                org_id=parent_org.id,
                sub_org_id=sub_org.id,
            )
            db.add(topic)
            db.flush()
            counts["topics_created"] += 1
        else:
            topic.color = sub_color
            db.flush()
        sub_topics_by_name[name] = topic

    # ---- DelegateProfile per (member, topic) with sub_org_id ----
    for (uid, topic_name, vis_state) in sub_bible.delegate_topic_visibilities:
        user = bible_uid_to_user.get(uid)
        topic = sub_topics_by_name.get(topic_name)
        if user is None or topic is None:
            log.warning(
                "sub-org seed: skipping delegate visibility (uid=%r topic=%r)",
                uid, topic_name,
            )
            continue
        dp_row = db.query(models.DelegateProfile).filter(
            models.DelegateProfile.user_id == user.id,
            models.DelegateProfile.topic_id == topic.id,
        ).first()
        if dp_row is None:
            dp_row = models.DelegateProfile(
                user_id=user.id,
                topic_id=topic.id,
                org_id=parent_org.id,
                sub_org_id=sub_org.id,
                bio="",
                visibility=vis_state,
            )
            if vis_state == "public_accepting":
                dp_row.public_accepting_submitted_at = now
                dp_row.public_accepting_approved_at = now
            db.add(dp_row)
            db.flush()

    # ---- Delegations with sub_org_id (Phase 18 retrofit verification) ----
    for (delegator_uid, delegate_uid, topic_name) in sub_bible.delegations:
        delegator = bible_uid_to_user.get(delegator_uid)
        delegate = bible_uid_to_user.get(delegate_uid)
        topic = sub_topics_by_name.get(topic_name)
        if delegator is None or delegate is None or topic is None:
            log.warning(
                "sub-org seed: skipping delegation (%r → %r on %r)",
                delegator_uid, delegate_uid, topic_name,
            )
            continue
        existing_d = db.query(models.Delegation).filter(
            models.Delegation.delegator_id == delegator.id,
            models.Delegation.delegate_id == delegate.id,
            models.Delegation.org_id == parent_org.id,
            models.Delegation.sub_org_id == sub_org.id,
            models.Delegation.topic_id == topic.id,
        ).first()
        if existing_d is None:
            db.add(models.Delegation(
                delegator_id=delegator.id,
                delegate_id=delegate.id,
                org_id=parent_org.id,
                sub_org_id=sub_org.id,
                topic_id=topic.id,
            ))
            db.flush()

    # ---- Sub-org Proposals ----
    for sp in (sub_bible.proposals or []):
        author = bible_uid_to_user.get(sp.proposer_user_id)
        if author is None:
            log.warning(
                "sub-org seed: proposal %r references unknown user %r",
                sp.proposal_id, sp.proposer_user_id,
            )
            continue
        status, delib_start, vote_start, vote_end = (
            _resolve_proposal_status_and_times(sp.state_at_reset, sp.voting_method, now)
        )
        bible_method = sp.voting_method
        db_voting_method = (
            "ranked_choice" if bible_method in ("rcv", "stv") else bible_method
        )
        existing_p = db.query(models.Proposal).filter(
            models.Proposal.org_id == parent_org.id,
            models.Proposal.sub_org_id == sub_org.id,
            models.Proposal.title == sp.title,
        ).first()
        if existing_p is not None:
            continue
        proposal = models.Proposal(
            title=sp.title,
            body=sp.body,
            author_id=author.id,
            org_id=parent_org.id,
            sub_org_id=sub_org.id,
            status=status,
            voting_method=db_voting_method,
            num_winners=sp.num_winners,
            deliberation_start=delib_start,
            voting_start=vote_start,
            voting_end=vote_end,
            pass_threshold=0.50,
            quorum_threshold=0.35,
        )
        db.add(proposal)
        db.flush()
        counts["proposals_created"] += 1

        if sp.options:
            for idx, label in enumerate(sp.options):
                db.add(models.ProposalOption(
                    proposal_id=proposal.id,
                    label=label,
                    display_order=idx,
                ))
            db.flush()

        # ProposalTopic associations
        for idx, topic_name in enumerate(sp.topics or []):
            topic = sub_topics_by_name.get(topic_name)
            if topic is None:
                continue
            relevance = 1.0 if idx == 0 else max(0.1, 1.0 - 0.2 * idx)
            db.add(models.ProposalTopic(
                proposal_id=proposal.id,
                topic_id=topic.id,
                relevance=relevance,
            ))
        db.flush()


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
        # Phase 49b — seed the Phase 47 system titles (Steward, Admin)
        # alongside the default roles so the label layer is present from
        # the first reset cycle. Idempotent: ``seed_system_titles_for_
        # org`` upserts.
        from org_titles import seed_system_titles_for_org
        seed_system_titles_for_org(db, org.id)
    else:
        org.name = bible.display_name
        org.description = bible.charter
        org.is_demo = True
        org.is_demo_resetting = False
        # Ensure system titles exist on resets too (idempotent).
        from org_titles import seed_system_titles_for_org
        seed_system_titles_for_org(db, org.id)

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

    # Phase 34 B1 — surface bible's voting_methods_used into the canonical
    # `allowed_voting_methods` setting that proposal creation consults. The
    # bible uses 'rcv'/'stv' aliases; the runtime expects 'ranked_choice'
    # (Phase 23.2 B3 alias mapping). 'stv' has no runtime equivalent today
    # so it's dropped here (the demo seed pipeline already maps stv→
    # ranked_choice for proposal voting_method per Phase 23.2 B3).
    _vm_alias = {"rcv": "ranked_choice", "stv": "ranked_choice"}
    bible_methods = getattr(bible, "voting_methods_used", None) or []
    if bible_methods:
        normalized = []
        for m in bible_methods:
            mapped = _vm_alias.get(m, m)
            if mapped not in normalized:
                normalized.append(mapped)
        settings["allowed_voting_methods"] = normalized

    # Phase 49b — bible-driven org-level flags that the title/cosign
    # showcase depends on. Setting these in settings keeps the seed
    # idempotent across resets without a schema change.
    if getattr(bible, "elections_enabled", None) is not None:
        elec_cfg = dict(settings.get("elections") or {})
        elec_cfg["enabled"] = bool(bible.elections_enabled)
        # Default trigger_sources include 'admin_direct' so the Open
        # Election button is wired immediately. 'member_cosign' is
        # added when allow_cosign_petition is True (the natural pair).
        triggers = list(elec_cfg.get("trigger_sources") or ["admin_direct"])
        if getattr(bible, "allow_cosign_petition", None) and "member_cosign" not in triggers:
            triggers.append("member_cosign")
        elec_cfg["trigger_sources"] = triggers
        settings["elections"] = elec_cfg
    if getattr(bible, "allow_cosign_petition", None) is not None:
        settings["allow_cosign_petition"] = bool(bible.allow_cosign_petition)

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

        # Phase 31 N1.b — stamp the bible-declared notification preset
        # onto this member. Idempotent across resets: any existing
        # NotificationPreference rows for this user are dropped before
        # the new preset is applied, so a bible edit takes effect on
        # the next reset without leaving stale rows behind.
        _stamp_notification_preset(db, user.id, m.notification_preset)

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
        # Phase 30.1 B5 — Topic.name is now scoped to (org_id, name), so
        # demo orgs no longer need the {bible.slug}: prefix the old
        # global-unique constraint required. The description field
        # stays populated for back-compat with code still reading it;
        # a future pass can drop the column entirely.
        topic = db.query(models.Topic).filter(
            models.Topic.name == name,
            models.Topic.org_id == org.id,
        ).first()
        if topic is None:
            topic = models.Topic(
                name=name,
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
            # Phase 30.3: dp.page_visibility is accepted-and-ignored in
            # the bible schema for back-compat. Per-topic visibility
            # below is the sole audience control.
            odp = models.OrgDelegateProfile(
                user_id=user.id,
                org_id=org.id,
                intro=dp.intro or "",
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

    # ---- 5.6 Phase 49b — bible-declared Phase 47 titles -------------------
    # Creates ``OrgTitle`` rows + assigns holders. For bound-role
    # titles we bump the holder's membership role_id to at least the
    # bound tier (the seed runs OUTSIDE a request context, so we
    # don't route through routes/org_titles.py's _apply_bound_role_for_
    # assign — the bump semantics are equivalent, the floor is
    # checked manually below). System titles (Steward, Admin) are
    # untouched — they're a label layer over the existing role per
    # Phase 47 D6.
    bible_titles = getattr(bible, "titles", None) or []
    for tseed in bible_titles:
        existing = db.query(models.OrgTitle).filter_by(
            org_id=org.id, name=tseed.name,
        ).first()
        if existing is None:
            title = models.OrgTitle(
                org_id=org.id,
                name=tseed.name,
                bound_role=tseed.bound_role,
                cardinality_mode=tseed.cardinality_mode,
                fill_method=tseed.fill_method,
                display_order=tseed.display_order,
                term_length_days=tseed.term_length_days,
                election_lead_time_days=tseed.election_lead_time_days,
                is_system=False,
            )
            if tseed.term_length_days and tseed.term_length_days > 0:
                title.next_election_due_at = (
                    datetime.utcnow() + timedelta(days=int(tseed.term_length_days))
                )
            db.add(title)
            db.flush()
        else:
            existing.bound_role = tseed.bound_role
            existing.cardinality_mode = tseed.cardinality_mode
            existing.fill_method = tseed.fill_method
            existing.display_order = tseed.display_order
            existing.term_length_days = tseed.term_length_days
            existing.election_lead_time_days = tseed.election_lead_time_days
            title = existing

        if tseed.holder_user_id:
            holder = bible_uid_to_user.get(tseed.holder_user_id)
            if holder is None:
                log.warning(
                    "seed_pipeline: title %r holder %r not found in bible_uid_to_user; skipping assignment",
                    tseed.name, tseed.holder_user_id,
                )
                continue
            assignment = db.query(models.OrgTitleAssignment).filter_by(
                title_id=title.id, user_id=holder.id,
            ).first()
            if assignment is None:
                db.add(models.OrgTitleAssignment(
                    title_id=title.id, user_id=holder.id,
                ))
            # Bound-role bump: if the title binds a role and the holder
            # currently holds a lower tier, bump them. Tier order:
            # member < moderator < admin < steward. We only ever bump
            # UP — the seed never demotes (avoids accidentally
            # violating the floor on a steward currently bound to a
            # custom title).
            if tseed.bound_role:
                m = db.query(models.OrgMembership).filter_by(
                    org_id=org.id, user_id=holder.id, status="active",
                ).first()
                if m is not None and m.role_id is not None:
                    current_role = db.get(models.Role, m.role_id)
                    target_role = db.query(models.Role).filter_by(
                        org_id=org.id, system_key=tseed.bound_role,
                    ).first()
                    tier_order = {"member": 0, "moderator": 1, "admin": 2, "steward": 3}
                    cur_tier = tier_order.get(
                        getattr(current_role, "system_key", "member"), 0,
                    )
                    target_tier = tier_order.get(tseed.bound_role, 0)
                    if target_tier > cur_tier and target_role is not None:
                        m.role_id = target_role.id
        db.flush()

    # ---- 5.7 Phase 49b — bible-declared cosign-petition seed --------------
    # Creates a Proposal in deliberation status with is_cosign_gated=True
    # + N ProposalCosignature rows (sub-threshold) so a demo visitor
    # sees the cosign-gathering UI in action.
    cosign_seed = getattr(bible, "cosign_petition", None)
    if cosign_seed is not None:
        author = bible_uid_to_user.get(cosign_seed.author_user_id)
        if author is None:
            log.warning(
                "seed_pipeline: cosign_petition author %r not found; skipping",
                cosign_seed.author_user_id,
            )
        else:
            # Idempotency — if an existing proposal with this title
            # exists for this org, refresh its fields rather than
            # creating a duplicate.
            existing_petition = db.query(models.Proposal).filter_by(
                org_id=org.id, title=cosign_seed.title,
            ).first()
            now = datetime.utcnow()
            if existing_petition is None:
                petition = models.Proposal(
                    title=cosign_seed.title,
                    body=cosign_seed.body,
                    author_id=author.id,
                    org_id=org.id,
                    voting_method="binary",
                    num_winners=1,
                    status="deliberation",
                    deliberation_start=now,
                    deliberation_days=7,
                    voting_days=7,
                    pass_threshold=0.50,
                    quorum_threshold=0.40,
                    is_cosign_gated=True,
                    cosign_threshold_snapshot=cosign_seed.cosign_threshold,
                    cosign_expires_at=now + timedelta(hours=cosign_seed.cosign_expiry_hours),
                )
                db.add(petition)
                db.flush()
            else:
                petition = existing_petition
                petition.body = cosign_seed.body
                petition.is_cosign_gated = True
                petition.cosign_threshold_snapshot = cosign_seed.cosign_threshold
                petition.cosign_expires_at = now + timedelta(hours=cosign_seed.cosign_expiry_hours)
                petition.status = "deliberation"
            # Attach the requested topics (if any).
            for tname in cosign_seed.topic_names:
                topic = topics_by_name.get(tname)
                if topic is None:
                    continue
                existing_pt = db.query(models.ProposalTopic).filter_by(
                    proposal_id=petition.id, topic_id=topic.id,
                ).first()
                if existing_pt is None:
                    db.add(models.ProposalTopic(
                        proposal_id=petition.id, topic_id=topic.id,
                    ))
            # Author's implicit first signature.
            author_sig = db.query(models.ProposalCosignature).filter_by(
                proposal_id=petition.id, user_id=author.id,
            ).first()
            if author_sig is None:
                db.add(models.ProposalCosignature(
                    proposal_id=petition.id, user_id=author.id,
                ))
            # Additional signers.
            for sig_uid in cosign_seed.signer_user_ids:
                signer = bible_uid_to_user.get(sig_uid)
                if signer is None or signer.id == author.id:
                    continue
                existing_sig = db.query(models.ProposalCosignature).filter_by(
                    proposal_id=petition.id, user_id=signer.id,
                ).first()
                if existing_sig is None:
                    db.add(models.ProposalCosignature(
                        proposal_id=petition.id, user_id=signer.id,
                    ))
            db.flush()

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
            # Phase 32 — per-proposal overrides for the deliberation-
            # engagement features. Bible entries leave these None unless
            # the proposal explicitly exercises a feature (D23 demo).
            allow_write_in_options=bp.allow_write_in_options,
            allow_write_ins_during_voting=bp.allow_write_ins_during_voting,
            max_write_ins=bp.max_write_ins,
            allow_pre_voting=bp.allow_pre_voting,
            show_votes_during_deliberation=bp.show_votes_during_deliberation,
            edit_lockout_fraction=bp.edit_lockout_fraction,
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

    # ---- 6.5 Phase 32.2 D-cluster demo content (HOA only) ----------------
    # D1 — seed two ProposalRevision rows on P-H-10 (EV Charging) so the
    # change-log accordion has demo content. D2 — add a spammy write-in
    # to P-H-13 (Community Garden), then immediately mark it removed
    # via an audit-log entry while leaving NO ProposalOption row behind.
    if bible.slug == "demo-cedar-hollow":
        _seed_phase_32_2_demo_extras(
            db,
            proposals_by_bible_id=proposals_by_bible_id,
            bible_uid_to_user=bible_uid_to_user,
            org=org,
            now=now,
        )

    # ---- 6.6 Phase 34 B2/B3 — sub-org content (HOA only as of Phase 34) ----
    # Walk bible.sub_orgs_structured and seed each child Organization with
    # its members (SubOrgMembership rows), topics (Topic with sub_org_id),
    # delegate-profile visibilities (DelegateProfile with sub_org_id),
    # delegations (Delegation with sub_org_id — exercises Phase 18 retrofit),
    # and proposals (Proposal with sub_org_id).
    for sub_bible in getattr(bible, "sub_orgs_structured", []) or []:
        _seed_sub_org(
            db,
            parent_org=org,
            sub_bible=sub_bible,
            bible_uid_to_user=bible_uid_to_user,
            counts=counts,
            now=now,
        )

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

        # Phase 31 N1.b — stamp the filler's PRNG-derived notification
        # preset (~50% low / ~30% medium / ~20% high).
        _stamp_notification_preset(db, u.id, f.notification_preset)
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

    # Phase 36 B2: two-pass restructure. The trajectory chart now rebases
    # to the actual computed tally (D1), so filler votes MUST be inserted
    # and flushed before snapshot generation — compute_tally needs to see
    # the just-inserted Vote rows. Per-proposal seed_cap (Phase 31 B1) is
    # cached on the proposal record for re-use in pass 2.
    seed_caps_by_pid: dict = {}

    # ---- Pass 1: allocate filler votes for every proposal ----------------
    for bp in proposal_records:
        proposal = proposals_by_bible_id.get(bp.proposal_id)
        if not proposal:
            continue
        trajectory = _trajectory_for_proposal(bp.proposal_id)
        is_currently_voting = proposal.status == "voting"
        seed_cap = now if is_currently_voting else None
        seed_caps_by_pid[proposal.id] = seed_cap

        if (
            trajectory is not None
            and proposal.voting_start is not None
            and proposal.voting_end is not None
            and proposal.status in ("voting", "passed", "failed")
        ):
            base_pool = fillers[: max(1, len(fillers) // 2)]
            participating = [
                f for f in base_pool
                if f.user_id not in fillers_with_delegations
            ]
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
                cast_at_cap=seed_cap,
            )
            all_filler_votes.extend(filler_votes)

    # Flush filler votes before snapshot pass so compute_tally sees them.
    if all_filler_votes:
        db.bulk_save_objects(all_filler_votes)
        counts["votes_created"] += len(all_filler_votes)
        db.flush()

    # ---- Pass 2: compute terminal tally + generate snapshots ----------
    from delegation_engine import engine as delegation_engine_singleton

    for bp in proposal_records:
        proposal = proposals_by_bible_id.get(bp.proposal_id)
        if not proposal:
            continue
        trajectory = _trajectory_for_proposal(bp.proposal_id)
        if (
            trajectory is None
            or proposal.voting_start is None
            or proposal.voting_end is None
            or not trajectory.waypoints
        ):
            continue

        seed_cap = seed_caps_by_pid.get(proposal.id)
        # Phase 36 B2: compute terminal tally against the just-inserted
        # filler vote rows. compute_tally chains delegation, so named-
        # character + filler delegations resolve correctly. Defensive
        # try/except: fall back to legacy waypoint-only generation if
        # tally computation fails for any reason.
        terminal_tally: Optional[dict] = None
        try:
            tally = delegation_engine_singleton.compute_tally(proposal, db)
            terminal_tally = _tally_to_dict(tally, member_count_for_org)
        except Exception as e:  # pragma: no cover - defensive
            log.warning(
                "seed_pipeline: compute_tally failed for proposal=%s; "
                "falling back to legacy snapshot shape (err=%r)",
                proposal.id, e,
            )
            terminal_tally = None

        snaps = generate_snapshots(
            proposal=proposal,
            trajectory=trajectory,
            voting_start=proposal.voting_start,
            voting_end=proposal.voting_end,
            cadence_seconds=1800,
            total_eligible=member_count_for_org,
            seed_until=seed_cap,
            terminal_tally=terminal_tally,
        )
        all_snapshots.extend(snaps)

    if all_snapshots:
        db.bulk_save_objects(all_snapshots)
        counts["snapshots_created"] += len(all_snapshots)
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
