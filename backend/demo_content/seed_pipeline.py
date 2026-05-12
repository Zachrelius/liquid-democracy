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
    """Find-or-create OrgMembership row."""
    import models
    m = db.query(models.OrgMembership).filter(
        models.OrgMembership.user_id == user_id,
        models.OrgMembership.org_id == org_id,
    ).first()
    if m:
        return m
    m = models.OrgMembership(
        user_id=user_id, org_id=org_id, role_id=role_id, status="active",
    )
    db.add(m)
    db.flush()
    return m


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
        _ensure_membership(db, user.id, org.id, member_role_id)
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

        proposal = models.Proposal(
            title=bp.title,
            body=bp.body,
            author_id=author.id,
            org_id=org.id,
            status=status,
            voting_method=bp.voting_method,
            num_winners=1,
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

        # Candidate statements (RCV/STV): make sure each candidate has a user
        for cand_uid, statement in (bp.candidate_statements or {}).items():
            if cand_uid not in bible_uid_to_user:
                underlying = _underlying_username(cand_uid)
                cand_user = _ensure_user(
                    db, underlying, cand_uid.replace("_", " ").title(),
                )
                _ensure_membership(db, cand_user.id, org.id, member_role_id)
                bible_uid_to_user[cand_uid] = cand_user

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
            # Determine participation: ~50% of fillers vote on this proposal
            participating = fillers[: max(1, len(fillers) // 2)]
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
