"""
Demo seed data — Phase 2 full scenario.

Creates:
  - 20 users (alice is the recommended demo login)
  - 6 topics
  - 5 proposals in various statuses
  - Delegation patterns showing topic precedence, chain behavior, and direct-vote override

All users have password: demo1234
"""

from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

import models
from auth import hash_password
from delegation_engine import graph_store

log = logging.getLogger(__name__)

DEMO_PASSWORD = "demo1234"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _admin_seed_password() -> str:
    """Phase 63 (security) — the platform-admin seed account must never get
    the publicly-committed DEMO_PASSWORD. Pre-fix, prod ran with
    admin/demo1234 — a full platform-admin login (incl. the ballot-
    unredaction endpoint) available to anyone who read this file.

    Resolution order:
      1. ``SEED_ADMIN_PASSWORD`` env var, when set (operator-provisioned).
      2. Otherwise a random throwaway — the account exists but is not
         log-in-able until an operator resets the password out-of-band.
    DEMO_PASSWORD is only ever used for non-admin demo personas.
    """
    provisioned = os.environ.get("SEED_ADMIN_PASSWORD", "").strip()
    if provisioned:
        return provisioned
    random_pw = secrets.token_urlsafe(32)
    log.warning(
        "Seeding platform-admin user with a random unusable password "
        "(set SEED_ADMIN_PASSWORD to provision a known one)."
    )
    return random_pw


def _get_or_create_user(
    db: Session, username: str, display_name: str, is_admin: bool = False
) -> models.User:
    """Idempotent: leave existing users alone (Phase 7C.1 additive seed).

    Previously this helper overwrote password/display_name/email/is_admin on
    every re-run, which would clobber real visitor edits. The new behavior is
    pure skip-if-exists.
    """
    user = db.query(models.User).filter(models.User.username == username).first()
    if user:
        return user
    email = f"{username}@demo.example"
    password = _admin_seed_password() if is_admin else DEMO_PASSWORD
    user = models.User(
        username=username,
        display_name=display_name,
        password_hash=hash_password(password),
        is_admin=is_admin,
        email=email,
        email_verified=True,
    )
    db.add(user)
    db.flush()
    return user


def _get_or_create_topic(
    db: Session, name: str, description: str, color: str,
    sub_org_id: Optional[str] = None,
) -> models.Topic:
    # Phase 58 Cluster T — `Topic.description` was dropped as a column
    # in Phase 33 (it had become a same-value clone of `Topic.name`;
    # `name` is now the canonical display name, uniquely scoped per-
    # org). The `description` parameter is preserved here for back-
    # compat with the many call sites below that still pass a string,
    # but it is NO LONGER persisted. Don't migrate to Phase 56
    # `purpose=` either — these seed strings predate the purpose
    # semantic and would silently change behavior.
    topic = db.query(models.Topic).filter(models.Topic.name == name).first()
    if not topic:
        topic = models.Topic(
            name=name, color=color,
            sub_org_id=sub_org_id,
        )
        db.add(topic)
        db.flush()
    return topic


def _get_or_create_proposal(
    db: Session,
    title: str,
    body: str,
    author_id: str,
    status: str,
    topic_relevances: list[tuple[models.Topic, float]],
    days_ago_deliberation: int = 7,
    days_ago_voting: int = 1,
    days_ahead_close: Optional[int] = 6,
    org_id: Optional[str] = None,
    voting_method: str = "binary",
    options: Optional[list[tuple[str, str]]] = None,  # [(label, description), ...]
    num_winners: int = 1,
    sub_org_id: Optional[str] = None,
) -> models.Proposal:
    proposal = db.query(models.Proposal).filter(models.Proposal.title == title).first()
    if proposal:
        if org_id and not proposal.org_id:
            proposal.org_id = org_id
            db.flush()
        return proposal

    now = datetime.now(timezone.utc)
    proposal = models.Proposal(
        title=title,
        body=body,
        author_id=author_id,
        org_id=org_id,
        sub_org_id=sub_org_id,
        status=status,
        voting_method=voting_method,
        num_winners=num_winners,
        deliberation_start=now - timedelta(days=days_ago_deliberation),
        deliberation_end=(
            now - timedelta(days=days_ago_voting)
            if status != "deliberation"
            else now + timedelta(days=max(0, 7 - days_ago_deliberation))
        ),
        voting_start=now - timedelta(days=days_ago_voting) if status != "deliberation" else None,
        voting_end=now + timedelta(days=days_ahead_close) if days_ahead_close and status == "voting" else None,
        pass_threshold=0.50,
        quorum_threshold=0.40,
    )
    db.add(proposal)
    db.flush()
    for topic, relevance in topic_relevances:
        db.add(models.ProposalTopic(
            proposal_id=proposal.id,
            topic_id=topic.id,
            relevance=relevance,
        ))
    if options:
        for i, (label, desc) in enumerate(options):
            db.add(models.ProposalOption(
                proposal_id=proposal.id,
                label=label,
                description=desc,
                display_order=i,
            ))
    db.flush()
    return proposal


def _set_delegation(
    db: Session,
    delegator: models.User,
    delegate: models.User,
    topic: Optional[models.Topic],
    chain_behavior: str = "accept_sub",
    org_id: Optional[str] = None,
    sub_org_id: Optional[str] = None,
) -> None:
    """Idempotent: skip if a delegation row already exists for (delegator, topic).

    Phase 7C.1: never overwrite existing delegations — the seed must not stomp
    on real visitor data when re-run additively.

    Phase 18 B5: thread ``org_id`` (and ``sub_org_id``) into the constructor.
    Topic-scoped rows derive the scope from the topic when not passed; global
    rows MUST have an explicit ``org_id`` (caller must supply it to keep the
    Phase 18b NOT NULL flip happy on a fresh-DB seed).
    """
    topic_id = topic.id if topic else None
    # Derive org_id / sub_org_id from the topic when present and the caller
    # didn't override. Topics carry org_id since Phase 4c.
    if topic is not None:
        if org_id is None:
            org_id = getattr(topic, "org_id", None)
        if sub_org_id is None:
            sub_org_id = getattr(topic, "sub_org_id", None)
    existing = db.query(models.Delegation).filter(
        models.Delegation.delegator_id == delegator.id,
        models.Delegation.topic_id == topic_id,
    ).first()
    if existing:
        # Skip in-memory graph add too — the row already exists in DB and the
        # graph_store will be repopulated from DB on next process boot.
        return
    db.add(models.Delegation(
        delegator_id=delegator.id,
        delegate_id=delegate.id,
        topic_id=topic_id,
        chain_behavior=chain_behavior,
        org_id=org_id,
        sub_org_id=sub_org_id,
    ))
    db.flush()
    graph_store.add_delegation(delegator.id, delegate.id, topic_id)


def _set_precedence(
    db: Session, user: models.User, ordered_topics: list[models.Topic]
) -> None:
    """Idempotent: if any TopicPrecedence row exists for this user, skip entirely.

    Trade-off (Phase 7C.1): the previous implementation deleted-and-replaced,
    which is destructive to real visitor data. The new "skip if any precedence
    exists" rule loses some flexibility (a real visitor with one topic-priority
    can't have a second seeded for them), but matches the never-overwrite-
    visitor-data principle. Acceptable because precedences are user-driven
    configuration, not seed-driven content; the seed sets initial precedences
    once and leaves them alone afterwards.
    """
    has_existing = db.query(models.TopicPrecedence).filter(
        models.TopicPrecedence.user_id == user.id
    ).first()
    if has_existing:
        return
    for priority, topic in enumerate(ordered_topics):
        db.add(models.TopicPrecedence(
            user_id=user.id, topic_id=topic.id, priority=priority
        ))
    db.flush()


def _register_delegate(
    db: Session, user: models.User, topic: models.Topic, bio: str,
    org_id: Optional[str] = None,
) -> models.DelegateProfile:
    """Idempotent: skip if a DelegateProfile already exists for (user, topic)."""
    existing = db.query(models.DelegateProfile).filter(
        models.DelegateProfile.user_id == user.id,
        models.DelegateProfile.topic_id == topic.id,
    ).first()
    if existing:
        return existing
    profile = models.DelegateProfile(
        user_id=user.id, topic_id=topic.id, bio=bio,
        org_id=org_id,
    )
    db.add(profile)
    db.flush()
    return profile


def _register_delegate_with_visibility(
    db: Session, user: models.User, topic: models.Topic, bio: str,
    visibility: str = "public_accepting",
    position_statement: Optional[str] = None,
    org_id: Optional[str] = None,
) -> models.DelegateProfile:
    """Phase 19 (B5) — like ``_register_delegate`` but threads the new
    visibility enum + optional position_statement. Idempotent.

    For ``visibility='public_accepting'``, also sets
    ``public_accepting_approved_at`` to ``now`` so the demo seed
    represents a delegate who has already passed the approval gate
    (otherwise the page would render in pending-approval state).
    """
    existing = db.query(models.DelegateProfile).filter(
        models.DelegateProfile.user_id == user.id,
        models.DelegateProfile.topic_id == topic.id,
    ).first()
    if existing:
        # Update visibility/position_statement on existing rows so the
        # seed is additive — re-running upgrades the row's metadata
        # without creating duplicates.
        existing.visibility = visibility
        if position_statement is not None:
            existing.position_statement = position_statement
        if visibility == "public_accepting" and not existing.public_accepting_approved_at:
            existing.public_accepting_approved_at = datetime.now(timezone.utc)
        db.flush()
        return existing
    profile = models.DelegateProfile(
        user_id=user.id,
        topic_id=topic.id,
        bio=bio,
        org_id=org_id,
        visibility=visibility,
        position_statement=position_statement,
        public_accepting_approved_at=(
            datetime.now(timezone.utc)
            if visibility == "public_accepting" else None
        ),
    )
    db.add(profile)
    db.flush()
    return profile


def _get_or_create_org_delegate_profile(
    db: Session, user: models.User, org: models.Organization,
    intro: Optional[str] = None,
    page_visibility: str = "private",  # accepted-and-ignored post-Phase-30.3
) -> models.OrgDelegateProfile:
    """Idempotent OrgDelegateProfile getter.

    Phase 30.3: ``page_visibility`` column dropped from the model;
    callers still pass the legacy kwarg (back-compat) but it's ignored.
    Per-topic ``DelegateProfile.visibility`` is now the sole audience
    control.
    """
    existing = db.query(models.OrgDelegateProfile).filter(
        models.OrgDelegateProfile.user_id == user.id,
        models.OrgDelegateProfile.org_id == org.id,
    ).first()
    if existing:
        if intro is not None:
            existing.intro = intro
        db.flush()
        return existing
    odp = models.OrgDelegateProfile(
        user_id=user.id, org_id=org.id, intro=intro,
    )
    db.add(odp)
    db.flush()
    return odp


def _add_vote_rationale(
    db: Session, user: models.User, proposal: models.Proposal, content: str,
) -> Optional[models.DelegateVoteRationale]:
    """Phase 19 (B5) — attach a rationale to the user's vote on the
    given proposal. Idempotent: skips if a rationale already exists,
    skips if the user has no vote on the proposal.
    """
    vote = db.query(models.Vote).filter(
        models.Vote.user_id == user.id,
        models.Vote.proposal_id == proposal.id,
    ).first()
    if not vote:
        return None
    existing = db.query(models.DelegateVoteRationale).filter(
        models.DelegateVoteRationale.vote_id == vote.id,
    ).first()
    if existing:
        return existing
    rationale = models.DelegateVoteRationale(
        vote_id=vote.id, content=content,
    )
    db.add(rationale)
    db.flush()
    return rationale


def _create_follow_relationship(
    db: Session,
    follower: models.User,
    followed: models.User,
    permission_level: str = "view_only",
    org_id: Optional[str] = None,
) -> models.FollowRelationship:
    """Idempotent: skip if a FollowRelationship row already exists.

    Phase 18 B5 (D2): follow rows are now org-scoped. Caller threads
    ``org_id`` from the surrounding context (e.g., the demo org).
    """
    existing = db.query(models.FollowRelationship).filter(
        models.FollowRelationship.follower_id == follower.id,
        models.FollowRelationship.followed_id == followed.id,
    ).first()
    if existing:
        return existing
    rel = models.FollowRelationship(
        follower_id=follower.id,
        followed_id=followed.id,
        permission_level=permission_level,
        org_id=org_id,
    )
    db.add(rel)
    db.flush()
    return rel


def _create_follow_request(
    db: Session,
    requester: models.User,
    target: models.User,
    message: Optional[str] = None,
    org_id: Optional[str] = None,
) -> models.FollowRequest:
    """Phase 18 B5 (D2): follow requests are now org-scoped. Threading
    ``org_id`` keeps the seed legal post-Phase-18b NOT NULL flip."""
    existing = db.query(models.FollowRequest).filter(
        models.FollowRequest.requester_id == requester.id,
        models.FollowRequest.target_id == target.id,
    ).first()
    if existing:
        return existing
    req = models.FollowRequest(
        requester_id=requester.id,
        target_id=target.id,
        status="pending",
        message=message,
        org_id=org_id,
    )
    db.add(req)
    db.flush()
    return req


def _cast_vote(
    db: Session, user: models.User, proposal: models.Proposal, value: str
) -> None:
    """Idempotent: leave existing votes alone (Phase 7C.1).

    The seed must NEVER overwrite real visitor ballots when re-run additively.
    """
    existing = db.query(models.Vote).filter(
        models.Vote.proposal_id == proposal.id,
        models.Vote.user_id == user.id,
    ).first()
    if existing:
        return
    db.add(models.Vote(
        proposal_id=proposal.id,
        user_id=user.id,
        vote_value=value,
        is_direct=True,
        cast_by_id=user.id,
    ))
    db.flush()


def _cast_approval_vote(
    db: Session, user: models.User, proposal: models.Proposal, option_ids: list[str]
) -> None:
    """Cast an approval ballot. Idempotent: skip if a vote row already exists."""
    existing = db.query(models.Vote).filter(
        models.Vote.proposal_id == proposal.id,
        models.Vote.user_id == user.id,
    ).first()
    if existing:
        return
    db.add(models.Vote(
        proposal_id=proposal.id,
        user_id=user.id,
        vote_value=None,
        ballot={"approvals": option_ids},
        is_direct=True,
        cast_by_id=user.id,
    ))
    db.flush()


def _cast_ranked_vote(
    db: Session, user: models.User, proposal: models.Proposal, ranking: list[str]
) -> None:
    """Cast a ranked ballot (first = highest preference). Idempotent: skip if exists."""
    existing = db.query(models.Vote).filter(
        models.Vote.proposal_id == proposal.id,
        models.Vote.user_id == user.id,
    ).first()
    if existing:
        return
    db.add(models.Vote(
        proposal_id=proposal.id,
        user_id=user.id,
        vote_value=None,
        ballot={"ranking": ranking},
        is_direct=True,
        cast_by_id=user.id,
    ))
    db.flush()


# ---------------------------------------------------------------------------
# Full demo scenario
# ---------------------------------------------------------------------------

def _get_or_create_org(
    db: Session, name: str, slug: str, description: str = "", join_policy: str = "approval_required"
) -> models.Organization:
    org = db.query(models.Organization).filter(models.Organization.slug == slug).first()
    if not org:
        org = models.Organization(
            name=name,
            slug=slug,
            description=description,
            join_policy=join_policy,
            settings={
                "default_deliberation_days": 14,
                "default_voting_days": 7,
                "default_pass_threshold": 0.50,
                "default_quorum_threshold": 0.40,
                "allow_public_delegates": True,
                # Phase 30.1 B4 — public_delegate_policy removed; the
                # legacy admin-approval flow was replaced by the
                # Phase 19 DelegateProfile lifecycle.
                "require_email_verification": True,
                # Phase 20: legacy ``sustained_majority_floor`` removed.
                # Stable Result Required defaults are picked up from
                # DEFAULTS in sustained_majority.py if absent.
                "allowed_voting_methods": ["binary", "approval", "ranked_choice"],
            },
        )
        db.add(org)
        db.flush()
    return org


def _add_org_membership(
    db: Session, user: models.User, org: models.Organization, role: str = "member"
) -> models.OrgMembership:
    """Idempotent: skip if membership exists. Never overwrite role/status.

    Phase 12 — resolve the legacy role string to a Role.id via the org's
    preset rows. Seeds the four presets defensively if missing (the
    production migration handles this for prod; this branch is only hit
    by ``python seed_data.py`` for QA / local-dev scenarios).
    """
    existing = db.query(models.OrgMembership).filter(
        models.OrgMembership.user_id == user.id,
        models.OrgMembership.org_id == org.id,
    ).first()
    if existing:
        return existing
    # Map legacy 'owner' → 'steward' for callers that still use the old name.
    system_key = {"owner": "steward"}.get(role, role)
    role_row = (
        db.query(models.Role)
        .filter(models.Role.org_id == org.id, models.Role.system_key == system_key)
        .first()
    )
    if role_row is None:
        from role_seed import seed_default_roles_for_org
        roles = seed_default_roles_for_org(db, org.id)
        role_row = roles.get(system_key)
    m = models.OrgMembership(
        user_id=user.id,
        org_id=org.id,
        role_id=role_row.id if role_row else None,
        status="active",
    )
    db.add(m)
    db.flush()
    return m


# ---------------------------------------------------------------------------
# Phase 8.5 — Sub-org helpers
# ---------------------------------------------------------------------------

def _get_or_create_sub_org(
    db: Session,
    parent: models.Organization,
    name: str,
    slug: str,
    description: str = "",
    join_policy: str = "approval_required",
    settings: Optional[dict] = None,
) -> models.Organization:
    """Idempotent: create a sub-org under ``parent`` if no org with this slug
    exists yet. Re-runs are no-ops."""
    existing = db.query(models.Organization).filter(
        models.Organization.slug == slug
    ).first()
    if existing:
        return existing
    sub_org = models.Organization(
        name=name,
        slug=slug,
        description=description,
        join_policy=join_policy,
        parent_org_id=parent.id,
        settings=settings or {},
    )
    db.add(sub_org)
    db.flush()
    return sub_org


def _add_sub_org_membership(
    db: Session,
    user: models.User,
    sub_org: models.Organization,
    role: str = "member",
) -> models.SubOrgMembership:
    """Idempotent: skip if membership exists. Never overwrite role/status."""
    existing = db.query(models.SubOrgMembership).filter(
        models.SubOrgMembership.user_id == user.id,
        models.SubOrgMembership.sub_org_id == sub_org.id,
    ).first()
    if existing:
        return existing
    # Phase 15 Cluster S: SubOrgMembership.role is now an FK to the
    # parent's Role row. Seed translates legacy ``"owner"`` to
    # ``"steward"`` (Phase 12.5 rename).
    rename = {"owner": "steward"}
    target_sk = rename.get(role, role)
    if sub_org.parent_org_id is None:
        raise ValueError(
            f"_get_or_create_sub_org_membership: sub_org.id={sub_org.id} "
            "has no parent_org_id; sub-org membership requires a real sub-org."
        )
    parent_role = (
        db.query(models.Role)
        .filter(
            models.Role.org_id == sub_org.parent_org_id,
            models.Role.system_key == target_sk,
        )
        .first()
    )
    if parent_role is None:
        raise ValueError(
            f"Parent org {sub_org.parent_org_id} missing the {target_sk!r} "
            "preset role; ensure role_seed.seed_default_roles_for_org has run."
        )
    m = models.SubOrgMembership(
        user_id=user.id,
        sub_org_id=sub_org.id,
        role_id=parent_role.id,
        status="active",
    )
    db.add(m)
    db.flush()
    return m


def _get_or_create_polis(
    db: Session,
    title: str,
    prompt: str,
    org_id: str,
    sub_org_id: Optional[str],
    created_by: str,
    polis_conversation_id: Optional[str] = None,
    status: str = "active",
    seed_statements_count: int = 10,
) -> models.Polis:
    """Phase 9: idempotent Polis seed.

    Skip-if-exists keyed on title + org_id + sub_org_id, so re-running
    seed never creates duplicates. ``seed_statements_count`` is metadata
    only — the seed doesn't actually call pol.is (no
    POLIS_AUTH_TOKEN in dev). Real-API seed insertion is Session 2/4.
    """
    existing = db.query(models.Polis).filter(
        models.Polis.title == title,
        models.Polis.org_id == org_id,
        models.Polis.sub_org_id == sub_org_id,
    ).first()
    if existing:
        return existing
    polis = models.Polis(
        title=title,
        prompt=prompt,
        org_id=org_id,
        sub_org_id=sub_org_id,
        created_by=created_by,
        polis_conversation_id=polis_conversation_id,
        status=status,
    )
    db.add(polis)
    db.flush()
    log.info(
        "Seeded Polis %r (id=%s, sub_org_id=%s, conv=%s, %d seed statements planned)",
        title, polis.id, sub_org_id, polis_conversation_id,
        seed_statements_count,
    )
    return polis


def _seed_demo(db: Session) -> dict:
    log.info("Seeding Phase 2 full demo scenario…")

    # ── Default organization ───────────────────────────────────────────────
    # Phase 59 Cluster E note: this legacy seed creates a `slug='demo'`
    # Organization that is UNREACHABLE on prod — the `/demo` route is
    # now the demo login/marketing page, NOT a per-org landing. The
    # cleanup script `backend/scripts/phase59_remove_orphaned_demo_org.py`
    # removes the orphan from prod data. The legacy seed itself only
    # runs when IS_PUBLIC_DEMO=true (via seed_if_empty.py at container
    # start). On prod that flag is false (today's demo lives in the
    # Phase 23 three-bible system at backend/demo_content/), so the
    # orphan should not re-appear after the cleanup script runs. The
    # legacy code path is retained for test_seed_idempotency coverage
    # + local-dev convenience.
    demo_org = _get_or_create_org(
        db,
        name="Demo Organization",
        slug="demo",
        description="A demonstration organization for exploring liquid democracy features.",
        join_policy="open",
    )

    # ── Users ──────────────────────────────────────────────────────────────
    admin   = _get_or_create_user(db, "admin",    "Admin User",            is_admin=True)
    alice   = _get_or_create_user(db, "alice",    "Alice Voter")
    dr_chen = _get_or_create_user(db, "dr_chen",  "Dr. Chen")
    econ_bob= _get_or_create_user(db, "econ_bob", "Bob the Economist")
    carol   = _get_or_create_user(db, "carol",    "Carol Direct")
    dave    = _get_or_create_user(db, "dave",     "Dave the Delegator")
    env_emma= _get_or_create_user(db, "env_emma", "Emma (Environment)")
    rights_raj = _get_or_create_user(db, "rights_raj", "Raj (Civil Rights)")

    # Phase 7C.1: replace the placeholder "Voter NN" users with realistically-
    # named diverse seed users. The list aims for the variety a real civic
    # organization might actually have — mixed first/last name combinations
    # spanning multiple naming traditions, no single-locale skew.
    #
    # NOTE: usernames are kept stable as voter01..voter27 so any historical
    # references in tests / persona-picker continue to work; only display_name
    # changes from "Voter NN" to a real name. (For empty-DB seeds, the user
    # gets the real name from the start.)
    seed_voter_names = [
        ("voter01", "Aiyana Adebayo"),
        ("voter02", "Bo Beauchamp"),
        ("voter03", "Carmen Cardoso"),
        ("voter04", "Devika Delacroix"),
        ("voter05", "Esi Eriksen"),
        ("voter06", "Felix Farahani"),
        ("voter07", "Gianna Gallego"),
        ("voter08", "Hiroshi Hwang"),
        ("voter09", "Imani Iverson"),
        ("voter10", "Joaquin Jeong"),
        ("voter11", "Kiana Kowalski"),
        ("voter12", "Lior Lindqvist"),
        ("voter13", "Malik Marchetti"),
        ("voter14", "Naomi Nakamura"),
        ("voter15", "Owen Okonkwo"),
        ("voter16", "Priya Pereira"),
        ("voter17", "Qadira Quinones"),
        ("voter18", "Rashid Reyes"),
        ("voter19", "Sasha Saito"),
        ("voter20", "Tobias Talwar"),
        ("voter21", "Uma Ueno"),
        ("voter22", "Vinod Velasquez"),
        ("voter23", "Wren Whitfield"),
        ("voter24", "Yara Yamamoto"),
        ("voter25", "Zane Zheng"),
        ("voter26", "Camille Bauer"),
        ("voter27", "Diego Donovan"),
    ]
    extra_users = [
        _get_or_create_user(db, username, display_name)
        for (username, display_name) in seed_voter_names
    ]
    all_non_expert_users = [alice, carol, dave] + extra_users

    # ── Org memberships ────────────────────────────────────────────────────
    _add_org_membership(db, admin, demo_org, "owner")
    _add_org_membership(db, alice, demo_org, "admin")
    for u in [dr_chen, econ_bob, carol, dave, env_emma, rights_raj]:
        _add_org_membership(db, u, demo_org, "member")
    # Phase 12.5 D1: voter02 (extra_users[1]) is the Moderator demo persona
    # so the four-tier role system is visible from the demo (Steward/Admin/
    # Moderator/Member). _add_org_membership is "never overwrite role/status"
    # for existing rows — for prod, the one-shot SQL UPDATE in the closeout
    # promotes the existing membership row in place.
    _add_org_membership(db, extra_users[1], demo_org, "moderator")
    for u in extra_users:
        _add_org_membership(db, u, demo_org, "member")

    # ── Topics ─────────────────────────────────────────────────────────────
    healthcare   = _get_or_create_topic(db, "Healthcare",   "Health policy and reform",              "#10b981")
    economy      = _get_or_create_topic(db, "Economy",      "Economic policy and fiscal matters",     "#3b82f6")
    environment  = _get_or_create_topic(db, "Environment",  "Environmental protection and climate",   "#22c55e")
    civil_rights = _get_or_create_topic(db, "Civil Rights", "Rights and civil liberties",             "#8b5cf6")
    defense      = _get_or_create_topic(db, "Defense",      "National security and defense spending", "#ef4444")
    education    = _get_or_create_topic(db, "Education",    "Education funding and curriculum",       "#f59e0b")

    # Assign org_id to all topics
    for topic in [healthcare, economy, environment, civil_rights, defense, education]:
        topic.org_id = demo_org.id
    db.flush()

    # ── Proposals ──────────────────────────────────────────────────────────

    # 1. Universal Healthcare Coverage Act — Voting, mixed
    healthcare_prop = _get_or_create_proposal(
        db,
        title="Universal Healthcare Coverage Act",
        body=(
            "## Overview\n\n"
            "This act proposes universal healthcare coverage for all citizens, funded through "
            "a progressive tax structure and efficiency reforms.\n\n"
            "## Key Provisions\n\n"
            "- Eliminate out-of-pocket costs for essential services\n"
            "- Consolidate insurance administration to reduce overhead\n"
            "- Expand preventive care and mental health services\n\n"
            "## Fiscal Impact\n\n"
            "Projected cost: $180bn over 5 years. The government's economic advisory council "
            "estimates long-term savings of $220bn through prevention and reduced emergency care."
        ),
        author_id=admin.id,
        status="voting",
        topic_relevances=[(healthcare, 1.0), (economy, 0.3)],
        days_ago_deliberation=10,
        days_ago_voting=2,
        days_ahead_close=5,
        org_id=demo_org.id,
    )

    # 2. Carbon Tax Implementation — Voting, mostly yes
    carbon_prop = _get_or_create_proposal(
        db,
        title="Carbon Tax Implementation",
        body=(
            "## Purpose\n\n"
            "A carbon pricing mechanism to reduce greenhouse gas emissions by 40% by 2035, "
            "with revenue recycled as a citizen dividend.\n\n"
            "## Mechanism\n\n"
            "- $50/tonne starting rate, increasing by $10/year\n"
            "- Revenue returned equally to all citizens (approx. $800/year per person)\n"
            "- Border adjustment to protect domestic industries\n\n"
            "## Expected Outcomes\n\n"
            "Modelling suggests a 25% reduction in emissions within 3 years of implementation."
        ),
        author_id=admin.id,
        status="voting",
        topic_relevances=[(environment, 1.0), (economy, 0.7)],
        days_ago_deliberation=8,
        days_ago_voting=1,
        days_ahead_close=7,
        org_id=demo_org.id,
    )

    # 3. Education Funding Reform — Deliberation
    education_prop = _get_or_create_proposal(
        db,
        title="Education Funding Reform",
        body=(
            "## Background\n\n"
            "Current school funding is tied to local property taxes, creating significant "
            "inequality between wealthy and low-income districts.\n\n"
            "## Proposal\n\n"
            "Shift to a state-level per-pupil funding model with equity adjustments for "
            "districts serving higher proportions of students in poverty.\n\n"
            "## Implementation\n\n"
            "3-year phase-in to allow districts to adjust budgets."
        ),
        author_id=admin.id,
        status="deliberation",
        topic_relevances=[(education, 1.0)],
        days_ago_deliberation=3,
        days_ago_voting=0,
        days_ahead_close=None,
        org_id=demo_org.id,
    )

    # 4. Infrastructure Investment Act — Passed
    infra_prop = _get_or_create_proposal(
        db,
        title="Infrastructure Investment Act",
        body=(
            "## Summary\n\n"
            "A $500bn, 10-year program to rebuild roads, bridges, broadband, and clean water "
            "infrastructure.\n\n"
            "## Funding\n\n"
            "Federal bonds, infrastructure user fees, and private-public partnerships.\n\n"
            "This proposal has passed."
        ),
        author_id=admin.id,
        status="passed",
        topic_relevances=[(economy, 1.0), (environment, 0.4)],
        days_ago_deliberation=30,
        days_ago_voting=20,
        days_ahead_close=None,
        org_id=demo_org.id,
    )

    # 5. Digital Privacy Rights Act — Voting, close vote
    privacy_prop = _get_or_create_proposal(
        db,
        title="Digital Privacy Rights Act",
        body=(
            "## Overview\n\n"
            "Establishes comprehensive digital privacy rights, modelled on GDPR but with "
            "stronger enforcement and private right of action.\n\n"
            "## Key Rights\n\n"
            "- Right to data portability\n"
            "- Right to deletion (right to be forgotten)\n"
            "- Algorithmic transparency for consequential decisions\n"
            "- Opt-in consent required for personal data processing\n\n"
            "## Enforcement\n\n"
            "Fines up to 4% of global annual revenue for violations."
        ),
        author_id=admin.id,
        status="voting",
        topic_relevances=[(civil_rights, 1.0)],
        days_ago_deliberation=5,
        days_ago_voting=1,
        days_ahead_close=4,
        org_id=demo_org.id,
    )

    # 6. Community Garden Location — Approval Voting, in voting status
    garden_options = [
        ("Riverside Park", "Convert the unused section of Riverside Park into a community garden"),
        ("School Grounds", "Partner with the local school to use their unused field"),
        ("Downtown Lot", "Use the vacant lot on Main Street for an urban garden"),
        ("Rooftop Gardens", "Install rooftop gardens on municipal buildings"),
    ]
    garden_prop = _get_or_create_proposal(
        db,
        title="Community Garden Location",
        body=(
            "## Purpose\n\n"
            "Select the best location for our new community garden. "
            "Approve all options you find acceptable.\n\n"
            "## Evaluation Criteria\n\n"
            "- Accessibility and public transit access\n"
            "- Soil quality and sunlight\n"
            "- Community impact and visibility\n"
        ),
        author_id=admin.id,
        status="voting",
        topic_relevances=[(environment, 0.8), (economy, 0.3)],
        days_ago_deliberation=6,
        days_ago_voting=1,
        days_ahead_close=5,
        org_id=demo_org.id,
        voting_method="approval",
        options=garden_options,
    )

    # 7. Office Renovation Style — Approval Voting, passed with tied result
    reno_options = [
        ("Modern Minimalist", "Clean lines, open spaces, neutral palette"),
        ("Biophilic Design", "Natural materials, plants, and nature-inspired elements"),
        ("Industrial Chic", "Exposed brick, metal accents, warehouse aesthetic"),
    ]
    reno_prop = _get_or_create_proposal(
        db,
        title="Office Renovation Style",
        body=(
            "## Background\n\n"
            "Select the design style for the office renovation. "
            "The two most-approved styles will be combined in the final design.\n\n"
        ),
        author_id=admin.id,
        status="passed",
        topic_relevances=[],  # No topic → delegations don't resolve → tie survives
        days_ago_deliberation=14,
        days_ago_voting=7,
        days_ahead_close=None,
        org_id=demo_org.id,
        voting_method="approval",
        options=reno_options,
    )

    # 8. Annual Team Offsite Destination — Ranked Choice (IRV), in voting
    offsite_options = [
        ("Mountain Lodge", "Hiking, fireside discussions, off-grid retreat"),
        ("Beach Resort", "Coastal walks, sun, group dinners with ocean view"),
        ("Urban Workshop", "City venue, easy travel, evening cultural programming"),
        ("Forest Cabin", "Quiet woods, board games, slow weekend"),
    ]
    offsite_prop = _get_or_create_proposal(
        db,
        title="Annual Team Offsite Destination",
        body=(
            "## Background\n\n"
            "Pick this year's offsite destination. Rank the options in order of preference. "
            "We'll use instant-runoff voting (IRV) to find the option with majority support.\n\n"
            "Partial rankings are fine — only rank the options you'd actually be happy to attend."
        ),
        author_id=admin.id,
        status="voting",
        topic_relevances=[],  # No topic context — direct ballots + dave's global delegation only
        days_ago_deliberation=10,
        days_ago_voting=2,
        days_ahead_close=5,
        org_id=demo_org.id,
        voting_method="ranked_choice",
        num_winners=1,
        options=offsite_options,
    )

    # 9. Steering Committee Members — STV, passed with two winners
    committee_options = [
        ("Aria Chen", "Engineering lead, 8 years in distributed systems"),
        ("Boris Patel", "Product manager, brings cross-functional perspective"),
        ("Cara Singh", "Operations, focused on hiring and onboarding"),
        ("Devon Park", "Designer, advocates for user-research-driven decisions"),
        ("Eli Rojas", "Finance, long view on budget and headcount planning"),
    ]
    committee_prop = _get_or_create_proposal(
        db,
        title="Steering Committee — Two New Members",
        body=(
            "## Background\n\n"
            "Elect two new members to the steering committee using single transferable vote (STV). "
            "STV produces proportional representation: minority preferences still get representation "
            "if they have enough first-choice votes to meet the quota.\n\n"
            "Rank as many candidates as you support. Lower-preference rankings only matter if your "
            "higher choices are eliminated or already elected."
        ),
        author_id=admin.id,
        status="passed",
        topic_relevances=[],
        days_ago_deliberation=21,
        days_ago_voting=14,
        days_ahead_close=None,
        org_id=demo_org.id,
        voting_method="ranked_choice",
        num_winners=2,
        options=committee_options,
    )

    # 10. New Office Coffee Vendor — IRV, passed with tied final round
    coffee_options = [
        ("Cafe Verde", "Local roaster, fair-trade beans, slightly higher cost"),
        ("Coffee Republic", "National chain, consistent quality, mid-tier pricing"),
        ("Bean & Brew", "Co-op model, rotating single-origins, premium pricing"),
    ]
    coffee_prop = _get_or_create_proposal(
        db,
        title="New Office Coffee Vendor",
        body=(
            "## Background\n\n"
            "Pick the new office coffee vendor. Rank in order of preference; we'll use "
            "instant-runoff voting (IRV).\n\n"
            "*Note: this proposal is here to demonstrate the tied-final-round flow — voting closed "
            "with a tie that admin must resolve.*"
        ),
        author_id=admin.id,
        status="passed",
        topic_relevances=[],
        days_ago_deliberation=14,
        days_ago_voting=7,
        days_ahead_close=None,
        org_id=demo_org.id,
        voting_method="ranked_choice",
        num_winners=1,
        options=coffee_options,
    )

    # ── Expert votes ───────────────────────────────────────────────────────
    _cast_vote(db, dr_chen,     healthcare_prop, "yes")
    _cast_vote(db, econ_bob,    healthcare_prop, "no")
    _cast_vote(db, env_emma,    carbon_prop,     "yes")
    _cast_vote(db, econ_bob,    carbon_prop,     "yes")
    _cast_vote(db, rights_raj,  privacy_prop,    "yes")
    _cast_vote(db, carol,       privacy_prop,    "no")    # carol votes directly
    _cast_vote(db, carol,       healthcare_prop, "yes")   # direct override

    # Infra (passed) — final votes
    _cast_vote(db, econ_bob,  infra_prop, "yes")
    _cast_vote(db, env_emma,  infra_prop, "yes")
    _cast_vote(db, dr_chen,   infra_prop, "yes")
    _cast_vote(db, alice,     infra_prop, "no")   # alice voted no on this one
    for u in extra_users[:8]:
        _cast_vote(db, u, infra_prop, "yes")
    for u in extra_users[8:11]:
        _cast_vote(db, u, infra_prop, "no")

    # ── Alice's delegations ────────────────────────────────────────────────
    # Healthcare → Dr. Chen, Economy → Bob, precedence: Healthcare > Economy
    _set_delegation(db, alice, dr_chen,  healthcare)
    _set_delegation(db, alice, econ_bob, economy)
    _set_delegation(db, alice, rights_raj, civil_rights)
    _set_precedence(db, alice, [healthcare, economy, civil_rights, environment, education, defense])

    # ── Dave chains to Alice (global delegation, demo-org-scoped) ──────────
    # Phase 18 B5: global delegations need explicit org_id since they can't
    # inherit from a topic.
    _set_delegation(db, dave, alice, None, chain_behavior="accept_sub",
                    org_id=demo_org.id)

    # ── Extra voters — healthcare proposal ────────────────────────────────
    # Group 1 (voters 1–6): Healthcare > Economy precedence → follow Dr. Chen → YES
    for u in extra_users[:6]:
        _set_delegation(db, u, dr_chen,  healthcare)
        _set_delegation(db, u, econ_bob, economy)
        _set_precedence(db, u, [healthcare, economy])

    # Group 2 (voters 7–9): Economy > Healthcare → follow EconBob → NO
    for u in extra_users[6:9]:
        _set_delegation(db, u, dr_chen,  healthcare)
        _set_delegation(db, u, econ_bob, economy)
        _set_precedence(db, u, [economy, healthcare])

    # Group 3 (voters 10–12): follow env_emma on environment; no healthcare del → no vote on healthcare
    for u in extra_users[9:12]:
        _set_delegation(db, u, env_emma, environment)
        _set_delegation(db, u, env_emma, economy)

    # Phase 8.6 Item 2 — voter02's Economy delegation (Decision 8 cross-scope
    # demo fixture). voter02 is a parent-org member who later gets added to
    # the Engineering sub-org (Phase 8.5 sub-org block below). She delegates
    # Economy → econ_bob, who is NOT a sub-org member. The trunk-based
    # proposal (sub-org-scoped) carries Economy as a secondary topic, so the
    # delegation engine resolves voter02's vote to econ_bob, who isn't an
    # eligible voter under sub-org scope — chain-behavior produces "not cast"
    # (Decision 8) and the proposal-detail page renders the cross-scope
    # "your vote" copy (Decision 10). This row was missing from the seed
    # through Phase 8.5; adding it unblocks Suite R9 prod verification.
    # _set_delegation is idempotent (skip-if-exists), so re-running the seed
    # against an existing prod DB adds the row if missing, no-op if present.
    _set_delegation(db, extra_users[1], econ_bob, economy)

    # Carbon prop — env_emma + econ_bob voted yes; extra_users[0..5] delegate env
    for u in extra_users[:5]:
        _set_delegation(db, u, env_emma, environment)

    # Privacy prop — close vote: extra direct votes
    for u in extra_users[:4]:
        _cast_vote(db, u, privacy_prop, "yes")
    for u in extra_users[4:8]:
        _cast_vote(db, u, privacy_prop, "no")

    # ── Phase 7C.1 voter expansion ────────────────────────────────────────
    # Extra voters 12-26 (the newly-named cohort) participate across the live
    # voting proposals so each one lands at 12-20 voters with mixed direct /
    # delegated patterns. Existing voters 0-11 keep their original behavior.

    # Healthcare (currently dr_chen yes, econ_bob no, carol yes-direct, plus
    # 6 voters via dr_chen, 3 via econ_bob → 11 ballots). Add 7 more for ~18.
    # Voters 12-15: precedence Healthcare > Economy → resolve via Dr. Chen → YES
    for u in extra_users[12:16]:
        _set_delegation(db, u, dr_chen, healthcare)
        _set_delegation(db, u, econ_bob, economy)
        _set_precedence(db, u, [healthcare, economy])
    # Voters 16-18: precedence Economy > Healthcare → resolve via econ_bob → NO
    for u in extra_users[16:19]:
        _set_delegation(db, u, dr_chen, healthcare)
        _set_delegation(db, u, econ_bob, economy)
        _set_precedence(db, u, [economy, healthcare])

    # Carbon Tax (currently env_emma + econ_bob direct, 5 via env_emma → 7).
    # Add 10 more for ~17.
    # Voters 12-17 already delegate environment to env_emma above? No — only via
    # _set_precedence calls. Add explicit env delegations for 12-21.
    for u in extra_users[12:22]:
        _set_delegation(db, u, env_emma, environment)
    # Voters 19-21 also have environment > economy precedence so the carbon
    # delegation actually fires (others already have precedence from healthcare
    # block). Voters 19-21 had no precedence yet, set environment-first.
    for u in extra_users[19:22]:
        _set_precedence(db, u, [environment, economy])
    # Direct YES votes on carbon from a few who care strongly (no delegation).
    for u in extra_users[22:25]:
        _cast_vote(db, u, carbon_prop, "yes")
    _cast_vote(db, extra_users[25], carbon_prop, "no")  # one direct dissent
    # voter26 abstains directly on carbon
    _cast_vote(db, extra_users[26], carbon_prop, "abstain")

    # Privacy Rights (currently rights_raj yes, carol no, plus 4 yes / 4 no
    # → 10 ballots). Add 8 more for ~18.
    for u in extra_users[8:12]:
        _cast_vote(db, u, privacy_prop, "yes")  # yes-leaning continuation
    for u in extra_users[12:14]:
        _cast_vote(db, u, privacy_prop, "no")
    for u in extra_users[14:18]:
        _cast_vote(db, u, privacy_prop, "yes")
    _cast_vote(db, extra_users[18], privacy_prop, "abstain")

    # Universal Healthcare prop is `healthcare_prop` (the title is "Universal
    # Healthcare Coverage Act"); already counted above.

    # ── Approval votes — Garden Location ──────────────────────────────────
    garden_opts = db.query(models.ProposalOption).filter(
        models.ProposalOption.proposal_id == garden_prop.id,
    ).order_by(models.ProposalOption.display_order).all()
    if len(garden_opts) >= 4:
        # Mixed voting: some approve multiple, some approve one.
        # Phase 7C.1: expand to ~13 voters with overlapping approval clustering
        # so the option-attractor graph shows visible aggregate shape.
        gid = [o.id for o in garden_opts[:4]]   # [Riverside, School, Downtown, Rooftop]
        _cast_approval_vote(db, alice, garden_prop, [gid[0], gid[1]])
        _cast_approval_vote(db, dr_chen, garden_prop, [gid[0]])
        _cast_approval_vote(db, econ_bob, garden_prop, [gid[2], gid[3]])
        _cast_approval_vote(db, carol, garden_prop, [gid[0], gid[2]])
        _cast_approval_vote(db, env_emma, garden_prop, [gid[0], gid[1], gid[3]])
        _cast_approval_vote(db, rights_raj, garden_prop, [gid[1]])
        # Original cohort 0-5 (kept stable for back-compat)
        for u in extra_users[:3]:
            _cast_approval_vote(db, u, garden_prop, [gid[0], gid[1]])
        for u in extra_users[3:5]:
            _cast_approval_vote(db, u, garden_prop, [gid[2]])
        _cast_approval_vote(db, extra_users[5], garden_prop, [])  # abstain
        # Phase 7C.1 expansion: 7 more for ~13 total
        _cast_approval_vote(db, extra_users[12], garden_prop, [gid[0], gid[1], gid[2]])
        _cast_approval_vote(db, extra_users[13], garden_prop, [gid[1], gid[3]])
        _cast_approval_vote(db, extra_users[14], garden_prop, [gid[0]])
        _cast_approval_vote(db, extra_users[15], garden_prop, [gid[2], gid[3]])
        _cast_approval_vote(db, extra_users[16], garden_prop, [gid[0], gid[1]])
        _cast_approval_vote(db, extra_users[17], garden_prop, [gid[1]])
        _cast_approval_vote(db, extra_users[18], garden_prop, [gid[3]])

    # ── Approval votes — Renovation Style (tied result) ───────────────────
    reno_opts = db.query(models.ProposalOption).filter(
        models.ProposalOption.proposal_id == reno_prop.id,
    ).order_by(models.ProposalOption.display_order).all()
    if len(reno_opts) >= 3:
        # Intentional tie between first two options.
        # Phase 7C.1: expand to ~12 voters; keep tie shape but add cluster volume.
        rid = [o.id for o in reno_opts[:3]]  # [Modern, Biophilic, Industrial]
        _cast_approval_vote(db, alice, reno_prop, [rid[0], rid[1]])
        _cast_approval_vote(db, dr_chen, reno_prop, [rid[0]])
        _cast_approval_vote(db, econ_bob, reno_prop, [rid[1]])
        _cast_approval_vote(db, carol, reno_prop, [rid[0], rid[2]])
        _cast_approval_vote(db, env_emma, reno_prop, [rid[1], rid[2]])
        # Phase 7C.1 expansion: 7 more for ~12 total. Maintain Modern/Biophilic
        # near-parity (3+3 from above; add 3 more to each plus a few floats).
        _cast_approval_vote(db, extra_users[19], reno_prop, [rid[0], rid[1]])  # both
        _cast_approval_vote(db, extra_users[20], reno_prop, [rid[1]])
        _cast_approval_vote(db, extra_users[21], reno_prop, [rid[0]])
        _cast_approval_vote(db, extra_users[22], reno_prop, [rid[1], rid[2]])
        _cast_approval_vote(db, extra_users[23], reno_prop, [rid[0], rid[2]])
        _cast_approval_vote(db, extra_users[24], reno_prop, [rid[2]])
        _cast_approval_vote(db, extra_users[25], reno_prop, [rid[0], rid[1], rid[2]])

    # ── Ranked-choice votes — Offsite (IRV, in voting, mixed full/partial; dave inherits via global del) ──
    offsite_opts = db.query(models.ProposalOption).filter(
        models.ProposalOption.proposal_id == offsite_prop.id,
    ).order_by(models.ProposalOption.display_order).all()
    if len(offsite_opts) >= 4:
        mtn, beach, urban, forest = (o.id for o in offsite_opts[:4])
        _cast_ranked_vote(db, alice,      offsite_prop, [mtn, beach, forest])      # 3 of 4
        _cast_ranked_vote(db, dr_chen,    offsite_prop, [beach, urban, mtn, forest])  # full
        _cast_ranked_vote(db, econ_bob,   offsite_prop, [urban, mtn])              # partial
        _cast_ranked_vote(db, carol,      offsite_prop, [forest, mtn])             # partial
        _cast_ranked_vote(db, env_emma,   offsite_prop, [forest, beach, mtn, urban])  # full
        _cast_ranked_vote(db, extra_users[0], offsite_prop, [mtn, beach])
        _cast_ranked_vote(db, extra_users[1], offsite_prop, [beach, forest])
        _cast_ranked_vote(db, extra_users[2], offsite_prop, [urban])               # bullet vote
        # dave does NOT cast directly — global delegation to alice means his ballot
        # resolves to alice's ranking [mtn, beach, forest] at tally time.

        # Phase 7C.1 expansion: 8 more voters with mixed full / partial / bullet
        # rankings so the Sankey has meaningful Initial column distribution.
        _cast_ranked_vote(db, extra_users[12], offsite_prop, [beach, mtn, forest, urban])  # full
        _cast_ranked_vote(db, extra_users[13], offsite_prop, [mtn, beach])         # partial
        _cast_ranked_vote(db, extra_users[14], offsite_prop, [forest, beach, mtn]) # 3 of 4
        _cast_ranked_vote(db, extra_users[15], offsite_prop, [urban, beach])       # partial
        _cast_ranked_vote(db, extra_users[16], offsite_prop, [beach, forest, mtn]) # 3 of 4
        _cast_ranked_vote(db, extra_users[17], offsite_prop, [mtn])                # bullet
        _cast_ranked_vote(db, extra_users[18], offsite_prop, [forest])             # bullet
        _cast_ranked_vote(db, extra_users[19], offsite_prop, [beach, mtn])         # partial
        # extra_users[20] abstains (no vote cast)

    # ── Ranked-choice votes — Steering Committee (STV, num_winners=2, passed) ──
    committee_opts = db.query(models.ProposalOption).filter(
        models.ProposalOption.proposal_id == committee_prop.id,
    ).order_by(models.ProposalOption.display_order).all()
    if len(committee_opts) >= 5:
        aria, boris, cara, devon, eli = (o.id for o in committee_opts[:5])
        # Aria has strong first-choice support → wins early
        _cast_ranked_vote(db, alice,      committee_prop, [aria, devon, boris])
        _cast_ranked_vote(db, dr_chen,    committee_prop, [aria, eli, boris])
        _cast_ranked_vote(db, env_emma,   committee_prop, [aria, devon, cara])
        _cast_ranked_vote(db, extra_users[0], committee_prop, [aria, boris])
        _cast_ranked_vote(db, extra_users[1], committee_prop, [aria, devon])
        # Boris and Devon split second-tier support
        _cast_ranked_vote(db, econ_bob,   committee_prop, [boris, eli, aria])
        _cast_ranked_vote(db, rights_raj, committee_prop, [devon, cara, aria])
        _cast_ranked_vote(db, carol,      committee_prop, [boris, aria])
        _cast_ranked_vote(db, extra_users[2], committee_prop, [boris, devon])
        _cast_ranked_vote(db, extra_users[3], committee_prop, [devon, cara])
        _cast_ranked_vote(db, extra_users[4], committee_prop, [boris, aria])
        _cast_ranked_vote(db, extra_users[5], committee_prop, [devon, eli])
        # Minority support — Cara/Eli — won't reach quota, votes transfer
        _cast_ranked_vote(db, extra_users[6], committee_prop, [cara, eli])
        _cast_ranked_vote(db, extra_users[7], committee_prop, [eli, cara])

        # Phase 7C.1 expansion: 6 more voters with varied STV ranking patterns
        # so the multi-round Sankey shows visible transfers and elimination flow.
        _cast_ranked_vote(db, extra_users[12], committee_prop, [aria, cara, devon])
        _cast_ranked_vote(db, extra_users[13], committee_prop, [boris, cara])
        _cast_ranked_vote(db, extra_users[14], committee_prop, [devon, aria, eli])
        _cast_ranked_vote(db, extra_users[15], committee_prop, [eli, boris, aria])
        _cast_ranked_vote(db, extra_users[16], committee_prop, [aria, eli])
        _cast_ranked_vote(db, extra_users[17], committee_prop, [cara, devon, boris])

    # ── Ranked-choice votes — Coffee Vendor (IRV, passed, deliberately tied final round) ──
    coffee_opts = db.query(models.ProposalOption).filter(
        models.ProposalOption.proposal_id == coffee_prop.id,
    ).order_by(models.ProposalOption.display_order).all()
    if len(coffee_opts) >= 3:
        verde, republic, brew = (o.id for o in coffee_opts[:3])
        # 3 voters prefer Verde > Brew > Republic; 3 prefer Republic > Brew > Verde.
        # (alice's ballot is inherited by dave via global delegation, so the verde
        # side has alice + dr_chen + dave; republic has econ_bob + carol + rights_raj.)
        # Round 1: Verde=3, Republic=3, Brew=0 → Brew eliminated (no transfers).
        # Round 2: Verde=3, Republic=3 → final-round tie. Admin must resolve.
        _cast_ranked_vote(db, alice,      coffee_prop, [verde, brew, republic])
        _cast_ranked_vote(db, dr_chen,    coffee_prop, [verde, brew, republic])
        _cast_ranked_vote(db, econ_bob,   coffee_prop, [republic, brew, verde])
        _cast_ranked_vote(db, carol,      coffee_prop, [republic, brew, verde])
        _cast_ranked_vote(db, rights_raj, coffee_prop, [republic, brew, verde])
        # Phase 7C.1 expansion: 11 more voters across varied rankings. Some
        # have brew as first choice so Round 1 isn't 0-Brew anymore (giving
        # the IRV Sankey real elimination dynamics rather than a 3-3-0 punt).
        _cast_ranked_vote(db, env_emma,   coffee_prop, [verde, republic, brew])
        _cast_ranked_vote(db, extra_users[12], coffee_prop, [brew, verde, republic])
        _cast_ranked_vote(db, extra_users[13], coffee_prop, [brew, republic, verde])
        _cast_ranked_vote(db, extra_users[14], coffee_prop, [verde, brew])
        _cast_ranked_vote(db, extra_users[15], coffee_prop, [republic, verde, brew])
        _cast_ranked_vote(db, extra_users[16], coffee_prop, [verde])              # bullet
        _cast_ranked_vote(db, extra_users[17], coffee_prop, [republic, brew])
        _cast_ranked_vote(db, extra_users[18], coffee_prop, [brew, verde])
        _cast_ranked_vote(db, extra_users[19], coffee_prop, [verde, brew, republic])
        _cast_ranked_vote(db, extra_users[20], coffee_prop, [republic])           # bullet
        _cast_ranked_vote(db, extra_users[21], coffee_prop, [brew, verde, republic])

    # ── Phase 3a: Permission system ───────────────────────────────────────

    # Register public delegates with bios
    _register_delegate(db, dr_chen, healthcare,
        "Board-certified physician with 20 years in health policy. "
        "I advocate for evidence-based universal coverage and cost transparency.",
        org_id=demo_org.id)
    _register_delegate(db, dr_chen, economy,
        "Healthcare economics researcher. My votes prioritize long-term fiscal sustainability "
        "and equitable resource allocation in health-adjacent spending.",
        org_id=demo_org.id)
    _register_delegate(db, econ_bob, economy,
        "Economist and former central bank advisor. I vote based on macroeconomic evidence, "
        "fiscal responsibility, and long-term growth prospects.",
        org_id=demo_org.id)
    _register_delegate(db, env_emma, environment,
        "Environmental scientist and policy advocate. I vote YES on carbon pricing, "
        "clean energy, and biodiversity protections.",
        org_id=demo_org.id)
    _register_delegate(db, rights_raj, civil_rights,
        "Civil liberties attorney. I prioritize individual rights, privacy, "
        "and equal protection under the law.",
        org_id=demo_org.id)

    # ── Phase 19: Public Delegate Pages — demo personas ──────────────────
    # Per spec §B5, the demo seed surfaces three personas demonstrating
    # the visibility ladder. The existing _register_delegate rows above
    # default to visibility='public_accepting' (D8 backwards-compat) — we
    # extend the cohort additively here so re-running the seed leaves
    # those rows alone and the new rows show the spectrum of states.
    #
    # Persona 1 — dr_chen: the canonical "transparent + accepting" public
    #   delegate. Already public_accepting on healthcare + economy via
    #   the rows above. We attach an OrgDelegateProfile with intro +
    #   page_visibility='private' (D9 default; effective derives to
    #   'public' because she has non-private topics) and add rationale
    #   on her past votes (Healthcare yes, Infrastructure yes — leaving
    #   some past votes WITHOUT rationale to demonstrate the
    #   recent_rationale_ratio metric on the browse page).
    # Persona 2 — env_emma: mixed states. Already public_accepting on
    #   environment via the row above. We add Economy as 'public' (transparent
    #   only, not accepting new delegations) — the canonical "I'm okay being
    #   transparent here but not soliciting delegators" pattern. Position
    #   statements on both. Also gets a delegate_handle.
    # Persona 3 — econ_bob: drafting state with private_delegators page
    #   visibility. Already public_accepting on economy from the row above
    #   — but to demonstrate the intermediate state for testing, we
    #   override that to 'private' here so econ_bob's effective page is
    #   private_delegators (NOT derived to public). Followers in the demo
    #   org (already-existing follow relationships) can preview his
    #   draft. NOTE: this overrides econ_bob's economy delegate
    #   profile — the existing tests against econ_bob's economy
    #   profile have been confirmed to pass, but this is intentional
    #   demo-state drift to expose the page_visibility='private_delegators'
    #   case for browser-verify.

    # Persona 1: dr_chen — canonical accepting + transparent delegate.
    _get_or_create_org_delegate_profile(
        db, dr_chen, demo_org,
        intro=(
            "Board-certified physician and healthcare-economics researcher. "
            "I focus on evidence-based universal coverage, cost transparency, "
            "and long-term fiscal sustainability of public-health spending. "
            "I delegate openly because I believe my voting record + reasoning "
            "is the right basis for trust — not credentials alone."
        ),
        page_visibility="private",  # effective = 'public' (has non-private topics)
    )
    # Add a delegate_handle (account-level per D10).
    if not getattr(dr_chen, "delegate_handle", None):
        dr_chen.delegate_handle = "drchen"
    # Position statements on dr_chen's existing healthcare + economy
    # DelegateProfile rows. The _register_delegate calls above already
    # created these with default visibility='public_accepting'; here we
    # backfill the position_statement column.
    for dp in db.query(models.DelegateProfile).filter(
        models.DelegateProfile.user_id == dr_chen.id,
        models.DelegateProfile.org_id == demo_org.id,
    ).all():
        if dp.topic_id == healthcare.id and not dp.position_statement:
            dp.position_statement = (
                "Universal coverage with strong cost-transparency mandates. "
                "I'll vote YES on bills that expand access AND require price "
                "disclosure for procedures over $500."
            )
        elif dp.topic_id == economy.id and not dp.position_statement:
            dp.position_statement = (
                "Long-term fiscal sustainability over short-term stimulus. "
                "I'll generally vote YES on infrastructure with clear ROI "
                "windows; cautious on deficit-funded discretionary spending."
            )
        # Ensure approved_at is set for these existing rows so the demo
        # represents post-approval state.
        if dp.visibility == "public_accepting" and not dp.public_accepting_approved_at:
            dp.public_accepting_approved_at = datetime.now(timezone.utc)
    db.flush()
    # Rationales on dr_chen's past votes — Healthcare YES gets a written
    # rationale; Infrastructure YES does not. The 50% rationale rate is
    # intentional so the browse page's rationale-ratio metric has visible
    # spread across delegates.
    _add_vote_rationale(
        db, dr_chen, healthcare_prop,
        content=(
            "I voted YES on this bill because the access-expansion provisions "
            "(sections 4-6) include the cost-transparency requirements I "
            "consider non-negotiable. The funding mechanism (employer mandate "
            "+ public option) is reasonable; I'd have preferred a stronger "
            "drug-pricing component but the bill as written still represents "
            "net progress. I'll re-evaluate if the implementation regulations "
            "weaken the transparency requirements."
        ),
    )

    # Persona 2: env_emma — mixed visibility. Add Economy as 'public'
    # (transparent only, not accepting). Existing environment row stays
    # public_accepting.
    _get_or_create_org_delegate_profile(
        db, env_emma, demo_org,
        intro=(
            "Environmental scientist and policy advocate. I lead with climate "
            "and biodiversity but vote across the broader policy space — my "
            "votes on Economy are visible here even though I'm not actively "
            "soliciting delegations on that topic; I think transparency about "
            "your full voting record matters even on issues you're not the "
            "loudest voice for."
        ),
        page_visibility="private",  # effective = 'public' (has non-private topics)
    )
    if not getattr(env_emma, "delegate_handle", None):
        env_emma.delegate_handle = "emmagreen"
    # env_emma's existing environment row gets a position_statement.
    env_emma_env_dp = db.query(models.DelegateProfile).filter(
        models.DelegateProfile.user_id == env_emma.id,
        models.DelegateProfile.topic_id == environment.id,
    ).first()
    if env_emma_env_dp and not env_emma_env_dp.position_statement:
        env_emma_env_dp.position_statement = (
            "YES on carbon pricing, clean energy mandates, and biodiversity "
            "protections. I'll vote NO on rollbacks of existing environmental "
            "regulations regardless of jobs-narrative framing."
        )
        if not env_emma_env_dp.public_accepting_approved_at:
            env_emma_env_dp.public_accepting_approved_at = datetime.now(timezone.utc)
    # New: env_emma is 'public' (transparent only) on Economy.
    _register_delegate_with_visibility(
        db, env_emma, economy,
        bio=(
            "I vote on economy bills as part of my broader policy work; not "
            "soliciting delegations here, but my reasoning is on the record."
        ),
        visibility="public",
        position_statement=(
            "I generally favor public investment in long-horizon infrastructure "
            "with environmental co-benefits. Skeptical of tax cuts framed as "
            "growth policy when paired with environmental rollbacks."
        ),
        org_id=demo_org.id,
    )
    # Rationale on env_emma's past Carbon Pricing vote.
    _add_vote_rationale(
        db, env_emma, carbon_prop,
        content=(
            "Voted YES. The revenue-recycling mechanism (rebates to lower-"
            "income households) addresses the regressive-tax concern that "
            "usually kills carbon-pricing bills. I'd have preferred a higher "
            "starting price ($45/ton) but the escalation schedule is the "
            "load-bearing piece — and this bill has it."
        ),
    )

    # Persona 3: econ_bob — drafting state with private_delegators page.
    # Override his economy DelegateProfile to 'private' so the page is
    # NOT derived to 'public'; the stored page_visibility of
    # 'private_delegators' becomes the effective state. Approved
    # followers (already-existing follow rows in demo org) preview the
    # draft; the public browse page does NOT list econ_bob.
    _get_or_create_org_delegate_profile(
        db, econ_bob, demo_org,
        intro=(
            "[DRAFT] I'm preparing my public delegate page on Economy. While "
            "this is in private_delegators preview, I'm sharing the draft "
            "intro + position statements with my existing approved followers "
            "to get feedback before going fully public. Please tell me what's "
            "missing — I'd rather iterate now than after I'm soliciting new "
            "delegators."
        ),
        page_visibility="private_delegators",
    )
    if not getattr(econ_bob, "delegate_handle", None):
        econ_bob.delegate_handle = "bobeconomist"
    # Override econ_bob's economy DelegateProfile to 'private' so the
    # page-visibility derivation lands on 'private_delegators'.
    econ_bob_econ_dp = db.query(models.DelegateProfile).filter(
        models.DelegateProfile.user_id == econ_bob.id,
        models.DelegateProfile.topic_id == economy.id,
    ).first()
    if econ_bob_econ_dp:
        econ_bob_econ_dp.visibility = "private"
        econ_bob_econ_dp.position_statement = (
            "[DRAFT — private_delegators preview] I weight macroeconomic "
            "evidence and long-term fiscal sustainability over short-term "
            "stimulus arguments. I'd appreciate feedback on whether this "
            "framing is specific enough to be useful, vs. generic enough "
            "that it doesn't actually commit me to anything."
        )
        # Clear approval state since the topic is now 'private' — the
        # demo seed shouldn't pretend a private topic was approved.
        econ_bob_econ_dp.public_accepting_approved_at = None
    db.flush()

    # Set dr_chen and env_emma to auto-approve follows (they're public figures)
    dr_chen.default_follow_policy = "auto_approve_view"
    econ_bob.default_follow_policy = "auto_approve_view"
    db.flush()

    # Create follow relationships — Phase 18 B5 (D2): all follow rows are
    # now org-scoped to the demo org for the seed cohort. Real visitor
    # follows pick up org_id from the request URL (Phase 18 D3).
    # alice follows dr_chen (delegation_allowed — already has healthcare/economy delegations)
    _create_follow_relationship(db, alice, dr_chen, "delegation_allowed", org_id=demo_org.id)
    # alice follows econ_bob (delegation_allowed)
    _create_follow_relationship(db, alice, econ_bob, "delegation_allowed", org_id=demo_org.id)
    # alice follows rights_raj (delegation_allowed)
    _create_follow_relationship(db, alice, rights_raj, "delegation_allowed", org_id=demo_org.id)
    # dave follows alice (delegation_allowed — dave has global delegation to alice)
    _create_follow_relationship(db, dave, alice, "delegation_allowed", org_id=demo_org.id)
    # carol follows dr_chen (view_only — she votes directly anyway)
    _create_follow_relationship(db, carol, dr_chen, "view_only", org_id=demo_org.id)
    # several voters follow the public delegates
    for u in extra_users[:4]:
        _create_follow_relationship(db, u, dr_chen, "delegation_allowed", org_id=demo_org.id)
        _create_follow_relationship(db, u, econ_bob, "delegation_allowed", org_id=demo_org.id)
    for u in extra_users[4:8]:
        _create_follow_relationship(db, u, env_emma, "delegation_allowed", org_id=demo_org.id)

    # Phase 7C.1: alice follows roughly half of the new cohort. The other
    # half remain anonymous to alice's view, so when she opens any vote
    # graph she sees ~50% named voters and ~50% anonymous voters with
    # ballot arrows (Phase 7C.1 privacy boundary). 13 of 27 chosen for
    # ratio 13:14 — close to half, intentionally not exactly half so that
    # not all proposals show identical follow / anon ratios.
    alice_follows_indices = [0, 2, 4, 7, 9, 11, 13, 15, 17, 19, 21, 23, 25]
    for idx in alice_follows_indices:
        _create_follow_relationship(db, alice, extra_users[idx], "view_only", org_id=demo_org.id)

    # Create a pending follow request for alice (from voter08 — follow only, no intent)
    _create_follow_request(
        db, extra_users[7], alice,
        message="Hi Alice, I've been following your advocacy on civil rights "
                "and would like to see your voting record.",
        org_id=demo_org.id,
    )
    # voter09 sent a request to carol (pending, follow only)
    _create_follow_request(
        db, extra_users[8], carol,
        message="Hey Carol, I heard you vote on everything directly — "
                "I'd like to follow and see how you vote.",
        org_id=demo_org.id,
    )

    # ── Phase 3b: Delegation intents + frank ──────────────────────────────
    # Phase 12.6 D1 — frank is now the demo persona-picker's Moderator entry
    # (alongside voter02 from 12.5 D1). _add_org_membership is "never
    # overwrite role/status" — for prod the existing membership row is
    # promoted via direct SQL UPDATE in the closeout. For fresh-DB seeds
    # this line lands frank as Moderator from the start.
    frank = _get_or_create_user(db, "frank", "Frank Unknown")
    _add_org_membership(db, frank, demo_org, "moderator")

    # Create a delegation intent: voter10 wants to delegate Economy to carol,
    # but carol isn't a public delegate and voter10 doesn't follow her.
    # This shows the intent → approval → activation flow.
    # Phase 18 B5: thread org_id (and inherit sub_org_id) from the topic.
    voter10_freq = _create_follow_request(
        db, extra_users[9], carol,
        message="Hi Carol, I'd like to delegate Economy votes to you.",
        org_id=demo_org.id,
    )
    # Create the intent
    from datetime import timedelta as _td
    existing_intent = db.query(models.DelegationIntent).filter(
        models.DelegationIntent.delegator_id == extra_users[9].id,
        models.DelegationIntent.delegate_id == carol.id,
        models.DelegationIntent.topic_id == economy.id,
    ).first()
    if not existing_intent:
        db.add(models.DelegationIntent(
            delegator_id=extra_users[9].id,
            delegate_id=carol.id,
            topic_id=economy.id,
            chain_behavior="accept_sub",
            follow_request_id=voter10_freq.id,
            status="pending",
            expires_at=datetime.now(timezone.utc) + _td(days=30),
            # Phase 18 B5: inherit org scope from the topic (Economy is
            # demo-org-scoped). sub_org_id stays NULL since Economy is
            # parent-org-wide.
            org_id=getattr(economy, "org_id", None) or demo_org.id,
            sub_org_id=getattr(economy, "sub_org_id", None),
        ))
        db.flush()

    # ── Phase 8.5: Sub-organization ───────────────────────────────────────
    # Decision 1 (two-level), Decision 2 (opt-in membership), Decision 3
    # (sub-org-scoped topic), Decision 8 (cross-scope delegation).
    #
    # Structure:
    #   Sub-org "Engineering Team" under demo org.
    #   - dave (sub-org admin)
    #   - carol, voter01 (Aiyana Adebayo), voter02 (Bo Beauchamp): members.
    #   - One sub-org-scoped topic: "Engineering Practices".
    #   - One sub-org-scoped voting proposal using that topic.
    #   - alice (parent-org admin) is intentionally NOT added as a sub-org
    #     member — parent-org-admin implicit power (Decision 6) gives her
    #     governance access without forcing her into the membership list, and
    #     her exclusion from the sub-org gives QA a clean "non-member with
    #     parent-org admin" persona to exercise Suite R scenarios with.
    #   - voter02 has a delegation set in the parent-org seed above
    #     (econ_bob on Economy — added in Phase 8.6 Item 2; the Phase 8.5
    #     Session 4 trunk-based proposal already wires Economy as a
    #     secondary relevance topic, so once both pieces are in place R9
    #     fires). econ_bob is NOT a sub-org member, which makes
    #     voter02 + econ_bob the canonical Decision 8 cross-scope
    #     delegation pair: voter02 will hit the chain-behavior path on
    #     sub-org proposals where their delegate isn't an eligible voter.
    eng_sub_org = _get_or_create_sub_org(
        db,
        parent=demo_org,
        name="Engineering Team",
        slug="demo-engineering",
        description=(
            "A sub-organization within the Demo Org for engineering-team-scoped "
            "decisions: tooling choices, on-call rotations, technical practices."
        ),
        join_policy="approval_required",
        settings={
            # Sub-org overrides nothing by default — Decision 9 lets us inherit
            # from the parent. Leaving settings empty here exercises the
            # parent-fallback path of get_org_config in real seed data.
        },
    )

    # Sub-org members. dave is the sub-org admin (Decision 6 — sub-org-only
    # admin powers; no parent-org-wide role escalation).
    _add_sub_org_membership(db, dave, eng_sub_org, role="admin")
    _add_sub_org_membership(db, carol, eng_sub_org, role="member")
    _add_sub_org_membership(db, extra_users[0], eng_sub_org, role="member")
    _add_sub_org_membership(db, extra_users[1], eng_sub_org, role="member")

    # Sub-org-scoped topic (Decision 3). NULL parent_org_id hidden, but
    # sub_org_id points to eng_sub_org.
    eng_practices = _get_or_create_topic(
        db,
        name="Engineering Practices",
        description="Engineering team coding practices, tooling, on-call.",
        color="#0891b2",
        sub_org_id=eng_sub_org.id,
    )
    eng_practices.org_id = demo_org.id  # parent-org for ownership; sub_org_id scopes it
    db.flush()

    # Sub-org-scoped proposal (Decision 3 / Decision 8). In voting status
    # using the sub-org-scoped topic. Per Decision 3, sub-org proposals may
    # also reference parent-org-wide topics — we add Economy at low
    # relevance so voter02's existing Economy → econ_bob delegation
    # actually resolves on this proposal. That makes the proposal the
    # canonical Decision-10-moment-2 fixture: voter02 has a delegation
    # that the engine resolves, the resolved delegate (econ_bob) isn't a
    # sub-org member, and the chain-behavior fallback fires — exactly the
    # case Suite R R9 needs to verify the cross-scope "your vote" copy.
    eng_proposal = _get_or_create_proposal(
        db,
        title="Engineering Team — Adopt Trunk-Based Development",
        body=(
            "## Background\n\n"
            "The engineering team is currently on long-lived feature branches "
            "and is hitting frequent merge-conflict pain. This proposal would "
            "switch the team to trunk-based development with feature flags.\n\n"
            "## Scope\n\n"
            "Engineering Team only — does not affect other parts of the demo org."
        ),
        author_id=dave.id,
        status="voting",
        topic_relevances=[(eng_practices, 1.0), (economy, 0.4)],
        days_ago_deliberation=8,
        days_ago_voting=2,
        days_ahead_close=5,
        org_id=demo_org.id,
        sub_org_id=eng_sub_org.id,
    )

    # Sub-org members vote on the sub-org proposal. Mix of yes/no/abstain.
    # voter02 (extra_users[1]) does NOT vote directly — this is the cross-
    # scope delegation case. voter02 delegates Economy → econ_bob; the
    # proposal carries Economy as a secondary topic, so the engine resolves
    # voter02's delegate to econ_bob. econ_bob isn't a member of
    # eng_sub_org (parent-org-only), so eligible_voter_ids excludes him,
    # he has no ballot, and the accept_sub chain-behavior default falls
    # through to "not cast" (Decision 8). The frontend detects this exact
    # case (delegation resolved, delegate not in sub_org_id member set)
    # and renders the Decision-10-moment-2 cross-scope "your vote" copy.
    _cast_vote(db, dave, eng_proposal, "yes")
    _cast_vote(db, carol, eng_proposal, "yes")
    _cast_vote(db, extra_users[0], eng_proposal, "no")
    # extra_users[1] (voter02) abstains by not voting; their delegate isn't
    # in scope and chain-behavior produces a "not cast" resolution.

    db.commit()
    log.info("Phase 8.5 sub-org seed scenarios added.")

    # ── Phase 9: Polis seed scenarios ─────────────────────────────────────
    # Decision 1 (first-class artifact), Decision 5 (visibility mirrors
    # topics/proposals), Decision 6 (creator-tier matches topic creation).
    #
    # Two seed Polises so QA can exercise both scopes without manual
    # creation:
    #   1. Org-wide "Annual Priorities for 2026" — created by alice
    #      (parent-org admin), visible to all demo-org members.
    #   2. Sub-org-scoped "Engineering — Tooling Priorities" — created by
    #      dave (sub-org admin), visible to Engineering Team members
    #      plus parent-org admins (alice) per Decision 7 default visibility.
    #
    # `polis_conversation_id` uses placeholder slugs in dev/demo since we
    # don't have POLIS_AUTH_TOKEN configured. The frontend's iframe embed
    # will fail-soft against these placeholders (Polis returns "conversation
    # not found"). Production seed runs would need real conversation IDs —
    # that's Session 2/4 work.
    _get_or_create_polis(
        db,
        title="Demo Org — Annual Priorities for 2026",
        prompt=(
            "What should the Demo Org focus on this year? Share statements "
            "about priorities, areas of investment, or directions worth "
            "exploring. Vote agree/disagree on others' statements to find "
            "consensus and divergence."
        ),
        org_id=demo_org.id,
        sub_org_id=None,
        created_by=alice.id,
        polis_conversation_id="demo-polis-org-wide",
        seed_statements_count=10,
    )
    _get_or_create_polis(
        db,
        title="Engineering Team — Tooling Priorities",
        prompt=(
            "What engineering tooling investments would have the most "
            "impact on team productivity over the next quarter? Submit "
            "statements about CI/CD, testing infra, code review tooling, "
            "or developer-experience improvements; vote on others' to "
            "surface team consensus."
        ),
        org_id=demo_org.id,
        sub_org_id=eng_sub_org.id,
        created_by=dave.id,
        polis_conversation_id="demo-polis-engineering",
        seed_statements_count=10,
    )

    db.commit()
    log.info("Phase 9 Polis seed scenarios added.")

    all_usernames = ["alice", "dr_chen", "econ_bob", "carol", "dave", "env_emma",
                     "rights_raj", "frank", "admin"] + [u for (u, _) in seed_voter_names]

    return {
        "message": "Demo loaded. Log in as any user with password 'demo1234'",
        "suggested_user": "alice",
        "users": all_usernames,
    }


# ---------------------------------------------------------------------------
# Legacy single-scenario helpers (kept for backward compatibility)
# ---------------------------------------------------------------------------

def _seed_healthcare(db: Session) -> None:
    """Thin wrapper — Phase 2 demo supersedes this but keeps the route working."""
    _seed_demo(db)


def _seed_environment(db: Session) -> None:
    _seed_demo(db)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_seed(db: Session, scenario: str = "healthcare") -> dict:
    return _seed_demo(db)
