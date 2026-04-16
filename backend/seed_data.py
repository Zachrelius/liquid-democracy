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

def _get_or_create_user(
    db: Session, username: str, display_name: str, is_admin: bool = False
) -> models.User:
    email = f"{username}@demo.example"
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user:
        user = models.User(
            username=username,
            display_name=display_name,
            password_hash=hash_password(DEMO_PASSWORD),
            is_admin=is_admin,
            email=email,
            email_verified=True,
        )
        db.add(user)
        db.flush()
    else:
        user.password_hash = hash_password(DEMO_PASSWORD)
        user.display_name = display_name
        user.is_admin = is_admin
        user.email = email
        user.email_verified = True
        db.flush()
    return user


def _get_or_create_topic(
    db: Session, name: str, description: str, color: str
) -> models.Topic:
    topic = db.query(models.Topic).filter(models.Topic.name == name).first()
    if not topic:
        topic = models.Topic(name=name, description=description, color=color)
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
        status=status,
        deliberation_start=now - timedelta(days=days_ago_deliberation),
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
    db.flush()
    return proposal


def _set_delegation(
    db: Session,
    delegator: models.User,
    delegate: models.User,
    topic: Optional[models.Topic],
    chain_behavior: str = "accept_sub",
) -> None:
    topic_id = topic.id if topic else None
    existing = db.query(models.Delegation).filter(
        models.Delegation.delegator_id == delegator.id,
        models.Delegation.topic_id == topic_id,
    ).first()
    if existing:
        existing.delegate_id = delegate.id
        existing.chain_behavior = chain_behavior
    else:
        db.add(models.Delegation(
            delegator_id=delegator.id,
            delegate_id=delegate.id,
            topic_id=topic_id,
            chain_behavior=chain_behavior,
        ))
    db.flush()
    graph_store.add_delegation(delegator.id, delegate.id, topic_id)


def _set_precedence(
    db: Session, user: models.User, ordered_topics: list[models.Topic]
) -> None:
    db.query(models.TopicPrecedence).filter(
        models.TopicPrecedence.user_id == user.id
    ).delete()
    db.flush()
    for priority, topic in enumerate(ordered_topics):
        db.add(models.TopicPrecedence(
            user_id=user.id, topic_id=topic.id, priority=priority
        ))
    db.flush()


def _register_delegate(
    db: Session, user: models.User, topic: models.Topic, bio: str,
    org_id: Optional[str] = None,
) -> models.DelegateProfile:
    existing = db.query(models.DelegateProfile).filter(
        models.DelegateProfile.user_id == user.id,
        models.DelegateProfile.topic_id == topic.id,
    ).first()
    if existing:
        existing.is_active = True
        existing.bio = bio
        if org_id:
            existing.org_id = org_id
        db.flush()
        return existing
    profile = models.DelegateProfile(
        user_id=user.id, topic_id=topic.id, bio=bio, is_active=True,
        org_id=org_id,
    )
    db.add(profile)
    db.flush()
    return profile


def _create_follow_relationship(
    db: Session,
    follower: models.User,
    followed: models.User,
    permission_level: str = "view_only",
) -> models.FollowRelationship:
    existing = db.query(models.FollowRelationship).filter(
        models.FollowRelationship.follower_id == follower.id,
        models.FollowRelationship.followed_id == followed.id,
    ).first()
    if existing:
        existing.permission_level = permission_level
        db.flush()
        return existing
    rel = models.FollowRelationship(
        follower_id=follower.id,
        followed_id=followed.id,
        permission_level=permission_level,
    )
    db.add(rel)
    db.flush()
    return rel


def _create_follow_request(
    db: Session,
    requester: models.User,
    target: models.User,
    message: Optional[str] = None,
) -> models.FollowRequest:
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
    )
    db.add(req)
    db.flush()
    return req


def _cast_vote(
    db: Session, user: models.User, proposal: models.Proposal, value: str
) -> None:
    existing = db.query(models.Vote).filter(
        models.Vote.proposal_id == proposal.id,
        models.Vote.user_id == user.id,
    ).first()
    if existing:
        existing.vote_value = value
    else:
        db.add(models.Vote(
            proposal_id=proposal.id,
            user_id=user.id,
            vote_value=value,
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
                "public_delegate_policy": "admin_approval",
                "require_email_verification": True,
                "sustained_majority_floor": 0.45,
            },
        )
        db.add(org)
        db.flush()
    return org


def _add_org_membership(
    db: Session, user: models.User, org: models.Organization, role: str = "member"
) -> models.OrgMembership:
    existing = db.query(models.OrgMembership).filter(
        models.OrgMembership.user_id == user.id,
        models.OrgMembership.org_id == org.id,
    ).first()
    if existing:
        existing.role = role
        existing.status = "active"
        db.flush()
        return existing
    m = models.OrgMembership(
        user_id=user.id,
        org_id=org.id,
        role=role,
        status="active",
    )
    db.add(m)
    db.flush()
    return m


def _seed_demo(db: Session) -> dict:
    log.info("Seeding Phase 2 full demo scenario…")

    # ── Default organization ───────────────────────────────────────────────
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

    extra_users = [
        _get_or_create_user(db, f"voter{i:02d}", f"Voter {i:02d}") for i in range(1, 14)
    ]
    all_non_expert_users = [alice, carol, dave] + extra_users

    # ── Org memberships ────────────────────────────────────────────────────
    _add_org_membership(db, admin, demo_org, "owner")
    _add_org_membership(db, alice, demo_org, "admin")
    for u in [dr_chen, econ_bob, carol, dave, env_emma, rights_raj]:
        _add_org_membership(db, u, demo_org, "member")
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

    # ── Dave chains to Alice (global delegation) ───────────────────────────
    _set_delegation(db, dave, alice, None, chain_behavior="accept_sub")

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

    # Carbon prop — env_emma + econ_bob voted yes; extra_users[0..5] delegate env
    for u in extra_users[:5]:
        _set_delegation(db, u, env_emma, environment)

    # Privacy prop — close vote: extra direct votes
    for u in extra_users[:4]:
        _cast_vote(db, u, privacy_prop, "yes")
    for u in extra_users[4:8]:
        _cast_vote(db, u, privacy_prop, "no")

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

    # Set dr_chen and env_emma to auto-approve follows (they're public figures)
    dr_chen.default_follow_policy = "auto_approve_view"
    econ_bob.default_follow_policy = "auto_approve_view"
    db.flush()

    # Create follow relationships
    # alice follows dr_chen (delegation_allowed — already has healthcare/economy delegations)
    _create_follow_relationship(db, alice, dr_chen, "delegation_allowed")
    # alice follows econ_bob (delegation_allowed)
    _create_follow_relationship(db, alice, econ_bob, "delegation_allowed")
    # alice follows rights_raj (delegation_allowed)
    _create_follow_relationship(db, alice, rights_raj, "delegation_allowed")
    # dave follows alice (delegation_allowed — dave has global delegation to alice)
    _create_follow_relationship(db, dave, alice, "delegation_allowed")
    # carol follows dr_chen (view_only — she votes directly anyway)
    _create_follow_relationship(db, carol, dr_chen, "view_only")
    # several voters follow the public delegates
    for u in extra_users[:4]:
        _create_follow_relationship(db, u, dr_chen, "delegation_allowed")
        _create_follow_relationship(db, u, econ_bob, "delegation_allowed")
    for u in extra_users[4:8]:
        _create_follow_relationship(db, u, env_emma, "delegation_allowed")

    # Create a pending follow request for alice (from voter08 — follow only, no intent)
    _create_follow_request(
        db, extra_users[7], alice,
        message="Hi Alice, I've been following your advocacy on civil rights "
                "and would like to see your voting record."
    )
    # voter09 sent a request to carol (pending, follow only)
    _create_follow_request(
        db, extra_users[8], carol,
        message="Hey Carol, I heard you vote on everything directly — "
                "I'd like to follow and see how you vote."
    )

    # ── Phase 3b: Delegation intents + frank ──────────────────────────────
    frank = _get_or_create_user(db, "frank", "Frank Unknown")
    _add_org_membership(db, frank, demo_org, "member")

    # Create a delegation intent: voter10 wants to delegate Economy to carol,
    # but carol isn't a public delegate and voter10 doesn't follow her.
    # This shows the intent → approval → activation flow.
    voter10_freq = _create_follow_request(
        db, extra_users[9], carol,
        message="Hi Carol, I'd like to delegate Economy votes to you."
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
        ))
        db.flush()

    db.commit()
    log.info("Phase 3b seed scenarios added.")

    all_usernames = ["alice", "dr_chen", "econ_bob", "carol", "dave", "env_emma",
                     "rights_raj", "frank", "admin"] + [f"voter{i:02d}" for i in range(1, 14)]

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
