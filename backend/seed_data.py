"""
Demo scenario seed data.

Scenario A — "Healthcare Reform Act"
  Tests topic precedence ordering and delegation resolution.

Scenario B — "Environmental Budget Allocation"
  Tests chain_behavior: accept_sub, revert_direct, abstain.
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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_or_create_user(db: Session, username: str, display_name: str, is_admin: bool = False) -> models.User:
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user:
        user = models.User(
            username=username,
            display_name=display_name,
            password_hash=hash_password("demo1234"),
            is_admin=is_admin,
        )
        db.add(user)
        db.flush()
    return user


def _get_or_create_topic(db: Session, name: str, description: str, color: str) -> models.Topic:
    topic = db.query(models.Topic).filter(models.Topic.name == name).first()
    if not topic:
        topic = models.Topic(name=name, description=description, color=color)
        db.add(topic)
        db.flush()
    return topic


def _set_delegation(
    db: Session,
    delegator: models.User,
    delegate: models.User,
    topic: Optional[models.Topic],
    chain_behavior: str = "accept_sub",
) -> None:
    topic_id = topic.id if topic else None
    existing = (
        db.query(models.Delegation)
        .filter(
            models.Delegation.delegator_id == delegator.id,
            models.Delegation.topic_id == topic_id,
        )
        .first()
    )
    if existing:
        existing.delegate_id = delegate.id
        existing.chain_behavior = chain_behavior
    else:
        db.add(
            models.Delegation(
                delegator_id=delegator.id,
                delegate_id=delegate.id,
                topic_id=topic_id,
                chain_behavior=chain_behavior,
            )
        )
    db.flush()
    graph_store.add_delegation(delegator.id, delegate.id, topic_id)


def _set_precedence(db: Session, user: models.User, ordered_topics: list[models.Topic]) -> None:
    db.query(models.TopicPrecedence).filter(models.TopicPrecedence.user_id == user.id).delete()
    db.flush()
    for priority, topic in enumerate(ordered_topics):
        db.add(
            models.TopicPrecedence(
                user_id=user.id,
                topic_id=topic.id,
                priority=priority,
            )
        )
    db.flush()


def _cast_direct_vote(
    db: Session,
    user: models.User,
    proposal: models.Proposal,
    value: str,
) -> None:
    existing = (
        db.query(models.Vote)
        .filter(models.Vote.proposal_id == proposal.id, models.Vote.user_id == user.id)
        .first()
    )
    if existing:
        existing.vote_value = value
    else:
        db.add(
            models.Vote(
                proposal_id=proposal.id,
                user_id=user.id,
                vote_value=value,
                is_direct=True,
                cast_by_id=user.id,
            )
        )
    db.flush()


# ---------------------------------------------------------------------------
# Scenario A: Healthcare Reform Act
# ---------------------------------------------------------------------------


def _seed_healthcare(db: Session) -> None:
    log.info("Seeding healthcare scenario…")

    admin = _get_or_create_user(db, "admin", "Admin User", is_admin=True)
    dr_chen = _get_or_create_user(db, "dr_chen", "Dr. Chen")
    econ_expert = _get_or_create_user(db, "econ_expert", "EconExpert")

    # 20 regular users
    users = [_get_or_create_user(db, f"user{i:02d}", f"Citizen {i:02d}") for i in range(1, 21)]

    healthcare = _get_or_create_topic(db, "healthcare", "Health policy and reform", "#10b981")
    economy = _get_or_create_topic(db, "economy", "Economic policy and budgets", "#3b82f6")

    # Create the proposal
    existing_proposal = (
        db.query(models.Proposal).filter(models.Proposal.title == "Healthcare Reform Act").first()
    )
    if existing_proposal:
        proposal = existing_proposal
    else:
        now = datetime.now(timezone.utc)
        proposal = models.Proposal(
            title="Healthcare Reform Act",
            body=(
                "## Summary\n\n"
                "This act proposes a comprehensive reform of the public healthcare system, "
                "including universal coverage, cost controls, and digital health initiatives.\n\n"
                "## Fiscal Impact\n\n"
                "Estimated cost: $120bn over 5 years. Funded through a combination of savings "
                "and new revenue measures."
            ),
            author_id=admin.id,
            status="voting",
            deliberation_start=now - timedelta(days=7),
            voting_start=now - timedelta(hours=1),
            voting_end=now + timedelta(days=6),
        )
        db.add(proposal)
        db.flush()
        db.add(models.ProposalTopic(proposal_id=proposal.id, topic_id=healthcare.id))
        db.add(models.ProposalTopic(proposal_id=proposal.id, topic_id=economy.id))
        db.flush()

    # Dr. Chen votes YES
    _cast_direct_vote(db, dr_chen, proposal, "yes")
    # EconExpert votes NO
    _cast_direct_vote(db, econ_expert, proposal, "no")

    # Users 1-10: healthcare > economy precedence → follow Dr. Chen → YES
    for u in users[:10]:
        _set_delegation(db, u, dr_chen, healthcare)
        _set_delegation(db, u, econ_expert, economy)
        _set_precedence(db, u, [healthcare, economy])

    # Users 11-15: economy > healthcare precedence → follow EconExpert → NO
    for u in users[10:15]:
        _set_delegation(db, u, dr_chen, healthcare)
        _set_delegation(db, u, econ_expert, economy)
        _set_precedence(db, u, [economy, healthcare])

    # Users 16-18: direct votes (overriding delegations)
    _cast_direct_vote(db, users[15], proposal, "yes")
    _cast_direct_vote(db, users[16], proposal, "no")
    _cast_direct_vote(db, users[17], proposal, "abstain")
    # Give them delegations too so we can show override
    _set_delegation(db, users[15], econ_expert, economy)
    _set_delegation(db, users[16], dr_chen, healthcare)
    _set_delegation(db, users[17], econ_expert, None)  # global

    # Users 19-20: no delegation, no vote
    # (users[18] and users[19] — already have no delegations set)

    db.commit()
    log.info("Healthcare scenario seeded.")


# ---------------------------------------------------------------------------
# Scenario B: Environmental Budget Allocation
# ---------------------------------------------------------------------------


def _seed_environment(db: Session) -> None:
    log.info("Seeding environment scenario…")

    admin = _get_or_create_user(db, "admin", "Admin User", is_admin=True)
    delegate_a = _get_or_create_user(db, "delegate_a", "Delegate A")
    delegate_b = _get_or_create_user(db, "delegate_b", "Delegate B")

    env_users = [
        _get_or_create_user(db, f"env_user{i:02d}", f"Env Citizen {i:02d}") for i in range(1, 13)
    ]

    environment = _get_or_create_topic(db, "environment", "Environmental protection and budgets", "#22c55e")

    existing_proposal = (
        db.query(models.Proposal)
        .filter(models.Proposal.title == "Environmental Budget Allocation")
        .first()
    )
    if existing_proposal:
        proposal = existing_proposal
    else:
        now = datetime.now(timezone.utc)
        proposal = models.Proposal(
            title="Environmental Budget Allocation",
            body=(
                "## Proposal\n\n"
                "Allocate 15% of the national budget to environmental protection, "
                "renewable energy, and climate adaptation over the next decade."
            ),
            author_id=admin.id,
            status="voting",
            deliberation_start=now - timedelta(days=3),
            voting_start=now - timedelta(hours=2),
            voting_end=now + timedelta(days=5),
        )
        db.add(proposal)
        db.flush()
        db.add(models.ProposalTopic(proposal_id=proposal.id, topic_id=environment.id))
        db.flush()

    # Delegate B votes YES (directly)
    _cast_direct_vote(db, delegate_b, proposal, "yes")
    # Delegate A did NOT vote — but delegates to Delegate B
    _set_delegation(db, delegate_a, delegate_b, environment, chain_behavior="accept_sub")

    # Group 1 (users 1-4): accept_sub — chain propagates to Delegate B → YES
    for u in env_users[:4]:
        _set_delegation(db, u, delegate_a, environment, chain_behavior="accept_sub")

    # Group 2 (users 5-8): revert_direct — flagged, no vote resolved
    for u in env_users[4:8]:
        _set_delegation(db, u, delegate_a, environment, chain_behavior="revert_direct")

    # Group 3 (users 9-12): abstain — vote not cast
    for u in env_users[8:12]:
        _set_delegation(db, u, delegate_a, environment, chain_behavior="abstain")

    db.commit()
    log.info("Environment scenario seeded.")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_seed(db: Session, scenario: str = "healthcare") -> None:
    if scenario == "healthcare":
        _seed_healthcare(db)
    elif scenario == "environment":
        _seed_environment(db)
    else:
        raise ValueError(f"Unknown scenario: {scenario}")
