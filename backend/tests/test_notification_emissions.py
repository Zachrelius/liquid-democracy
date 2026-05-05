"""Phase 13 B-emit — emission-site tests.

One positive + one negative test per emission site per spec §B5. Negative
tests assert that opt-OUT (NotificationPreference row with enabled=False
OR no row at all = default opt-in-False) suppresses the in-app row. The
opt-in default means the negative test is just "don't grant preference"
for most sites; for clarity the tests opt the user IN, then OUT, and
confirm the difference.

Sites covered (12):
  1. comment.replied                           routes/comments.py
  2. comment.posted_on_your_proposal           routes/comments.py
  3. member.join_request                       routes/organizations.py
  4. invitation.accepted                       routes/organizations.py
  5. proposal.entered_voting                   routes/proposals.py
  6. proposal.closed                           routes/proposals.py
  7. sustained_majority.floor_approached       sustained_majority_worker.py
  8. delegate.applied                          routes/organizations.py
  9. delegate.application_decided              routes/organizations.py
  10. follow.requested                         routes/follows.py
  11. follow.approved                          routes/follows.py
  12. polis.created                            routes/polises.py

Plus the no-self-notify dedup tests for comment.replied (parent author IS
new commenter) and proposal.closed (author voted on own proposal).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest
from fastapi import BackgroundTasks
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from database import Base, get_db
from main import app
from role_seed import seed_default_roles_for_org
from tests.conftest import make_org_membership


_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


@pytest.fixture(scope="function")
def test_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def client(test_db: Session):
    def _get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _make_user(
    db: Session,
    username: str,
    *,
    email_verified: bool = True,
    default_follow_policy: str = "require_approval",
) -> models.User:
    u = models.User(
        username=username,
        display_name=username.title(),
        password_hash=_DUMMY_HASH,
        email=f"{username}@test.example",
        email_verified=email_verified,
        default_follow_policy=default_follow_policy,
    )
    db.add(u)
    db.flush()
    return u


def _make_org(db: Session, slug: str) -> models.Organization:
    o = models.Organization(name=slug.title(), slug=slug, description="", settings={})
    db.add(o)
    db.flush()
    seed_default_roles_for_org(db, o.id)
    return o


def _auth(user: models.User) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _opt_in(db: Session, user: models.User, event_type: str, *, in_app: bool = True, email: bool = False) -> None:
    if in_app:
        db.add(models.NotificationPreference(
            user_id=user.id, event_type=event_type,
            channel="in_app", enabled=True,
        ))
    if email:
        db.add(models.NotificationPreference(
            user_id=user.id, event_type=event_type,
            channel="email", enabled=True,
        ))
    db.flush()


def _notifications_for(db: Session, user: models.User, event_type: str) -> list[models.Notification]:
    return (
        db.query(models.Notification)
        .filter(
            models.Notification.user_id == user.id,
            models.Notification.event_type == event_type,
        )
        .all()
    )


# ---------------------------------------------------------------------------
# Site 1+2 — comment.replied / comment.posted_on_your_proposal
# ---------------------------------------------------------------------------

def _make_proposal(
    db: Session, author: models.User, org: models.Organization,
    *, status: str = "deliberation",
) -> models.Proposal:
    p = models.Proposal(
        title="Test Proposal",
        body="Body",
        author_id=author.id,
        org_id=org.id,
        status=status,
        voting_method="binary",
    )
    db.add(p)
    db.flush()
    return p


def test_comment_replied_emits_to_parent_author_when_opted_in(client, test_db):
    org = _make_org(test_db, "rep_org")
    author = _make_user(test_db, "rep_author")
    parent_user = _make_user(test_db, "rep_parent")
    replier = _make_user(test_db, "rep_reply")
    make_org_membership(test_db, org_id=org.id, user_id=author.id, role="member")
    make_org_membership(test_db, org_id=org.id, user_id=parent_user.id, role="member")
    make_org_membership(test_db, org_id=org.id, user_id=replier.id, role="member")
    proposal = _make_proposal(test_db, author, org)
    parent = models.Comment(
        proposal_id=proposal.id, author_id=parent_user.id, body="Top-level",
    )
    test_db.add(parent)
    test_db.flush()
    _opt_in(test_db, parent_user, "comment.replied")
    test_db.commit()

    resp = client.post(
        f"/api/proposals/{proposal.id}/comments",
        json={"body": "Reply!", "parent_comment_id": parent.id},
        headers=_auth(replier),
    )
    assert resp.status_code == 201, resp.text

    rows = _notifications_for(test_db, parent_user, "comment.replied")
    assert len(rows) == 1
    assert rows[0].org_id == org.id
    assert rows[0].actor_id == replier.id
    assert rows[0].payload["proposal_title"] == "Test Proposal"
    assert "body_excerpt" in rows[0].payload


def test_comment_replied_negative_no_optin_no_row(client, test_db):
    org = _make_org(test_db, "rep_org_neg")
    author = _make_user(test_db, "rep_author_n")
    parent_user = _make_user(test_db, "rep_parent_n")
    replier = _make_user(test_db, "rep_reply_n")
    make_org_membership(test_db, org_id=org.id, user_id=author.id, role="member")
    make_org_membership(test_db, org_id=org.id, user_id=parent_user.id, role="member")
    make_org_membership(test_db, org_id=org.id, user_id=replier.id, role="member")
    proposal = _make_proposal(test_db, author, org)
    parent = models.Comment(
        proposal_id=proposal.id, author_id=parent_user.id, body="Top-level",
    )
    test_db.add(parent)
    test_db.flush()
    # Explicit opt-OUT row (default would also work; this is the explicit form)
    test_db.add(models.NotificationPreference(
        user_id=parent_user.id, event_type="comment.replied",
        channel="in_app", enabled=False,
    ))
    test_db.commit()

    resp = client.post(
        f"/api/proposals/{proposal.id}/comments",
        json={"body": "Reply", "parent_comment_id": parent.id},
        headers=_auth(replier),
    )
    assert resp.status_code == 201

    rows = _notifications_for(test_db, parent_user, "comment.replied")
    assert rows == []


def test_comment_replied_no_self_notify(client, test_db):
    """Replying to your own comment doesn't generate a notification."""
    org = _make_org(test_db, "self_rep_org")
    user = _make_user(test_db, "self_replier")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="member")
    proposal = _make_proposal(test_db, user, org)
    parent = models.Comment(
        proposal_id=proposal.id, author_id=user.id, body="My own top-level",
    )
    test_db.add(parent)
    test_db.flush()
    _opt_in(test_db, user, "comment.replied")
    test_db.commit()

    resp = client.post(
        f"/api/proposals/{proposal.id}/comments",
        json={"body": "Reply to self", "parent_comment_id": parent.id},
        headers=_auth(user),
    )
    assert resp.status_code == 201

    rows = _notifications_for(test_db, user, "comment.replied")
    assert rows == []


def test_comment_posted_on_your_proposal_emits_to_author(client, test_db):
    org = _make_org(test_db, "topcomment")
    author = _make_user(test_db, "tc_author")
    commenter = _make_user(test_db, "tc_commenter")
    make_org_membership(test_db, org_id=org.id, user_id=author.id, role="member")
    make_org_membership(test_db, org_id=org.id, user_id=commenter.id, role="member")
    proposal = _make_proposal(test_db, author, org)
    _opt_in(test_db, author, "comment.posted_on_your_proposal")
    test_db.commit()

    resp = client.post(
        f"/api/proposals/{proposal.id}/comments",
        json={"body": "Top-level comment"},
        headers=_auth(commenter),
    )
    assert resp.status_code == 201

    rows = _notifications_for(test_db, author, "comment.posted_on_your_proposal")
    assert len(rows) == 1
    assert rows[0].org_id == org.id


def test_comment_posted_on_your_proposal_no_self_notify(client, test_db):
    """Author commenting on their own proposal doesn't notify themselves."""
    org = _make_org(test_db, "self_top_org")
    author = _make_user(test_db, "self_top_author")
    make_org_membership(test_db, org_id=org.id, user_id=author.id, role="member")
    proposal = _make_proposal(test_db, author, org)
    _opt_in(test_db, author, "comment.posted_on_your_proposal")
    test_db.commit()

    resp = client.post(
        f"/api/proposals/{proposal.id}/comments",
        json={"body": "My own comment"},
        headers=_auth(author),
    )
    assert resp.status_code == 201

    rows = _notifications_for(test_db, author, "comment.posted_on_your_proposal")
    assert rows == []


def test_comment_posted_on_your_proposal_negative(client, test_db):
    org = _make_org(test_db, "topneg")
    author = _make_user(test_db, "tn_author")
    commenter = _make_user(test_db, "tn_commenter")
    make_org_membership(test_db, org_id=org.id, user_id=author.id, role="member")
    make_org_membership(test_db, org_id=org.id, user_id=commenter.id, role="member")
    proposal = _make_proposal(test_db, author, org)
    test_db.commit()

    resp = client.post(
        f"/api/proposals/{proposal.id}/comments",
        json={"body": "Top-level"},
        headers=_auth(commenter),
    )
    assert resp.status_code == 201
    rows = _notifications_for(test_db, author, "comment.posted_on_your_proposal")
    assert rows == []


# ---------------------------------------------------------------------------
# Site 3 — member.join_request
# ---------------------------------------------------------------------------

def test_member_join_request_emits_to_admins(client, test_db):
    org = _make_org(test_db, "joinreq")
    org.join_policy = "approval_required"
    test_db.flush()
    admin = _make_user(test_db, "jr_admin")
    member = _make_user(test_db, "jr_member")
    requester = _make_user(test_db, "jr_requester")
    make_org_membership(test_db, org_id=org.id, user_id=admin.id, role="admin")
    make_org_membership(test_db, org_id=org.id, user_id=member.id, role="member")
    _opt_in(test_db, admin, "member.join_request")
    _opt_in(test_db, member, "member.join_request")
    test_db.commit()

    resp = client.post(f"/api/orgs/{org.slug}/join", headers=_auth(requester))
    assert resp.status_code == 200

    admin_rows = _notifications_for(test_db, admin, "member.join_request")
    assert len(admin_rows) == 1
    member_rows = _notifications_for(test_db, member, "member.join_request")
    # Plain members don't have member.approve_join — should NOT be notified
    assert member_rows == []


def test_member_join_request_negative_admin_optout(client, test_db):
    org = _make_org(test_db, "joinneg")
    org.join_policy = "approval_required"
    test_db.flush()
    admin = _make_user(test_db, "jrn_admin")
    requester = _make_user(test_db, "jrn_requester")
    make_org_membership(test_db, org_id=org.id, user_id=admin.id, role="admin")
    test_db.commit()

    resp = client.post(f"/api/orgs/{org.slug}/join", headers=_auth(requester))
    assert resp.status_code == 200

    rows = _notifications_for(test_db, admin, "member.join_request")
    assert rows == []


# ---------------------------------------------------------------------------
# Site 4 — invitation.accepted
# ---------------------------------------------------------------------------

def test_invitation_accepted_emits_to_inviter(client, test_db):
    org = _make_org(test_db, "invorg")
    inviter = _make_user(test_db, "inv_inviter")
    accepter = _make_user(test_db, "inv_accepter")
    make_org_membership(test_db, org_id=org.id, user_id=inviter.id, role="admin")
    inv = models.Invitation(
        org_id=org.id, email=accepter.email, invited_by=inviter.id,
        role="member", token="invtok123",
        expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=7),
    )
    test_db.add(inv)
    _opt_in(test_db, inviter, "invitation.accepted")
    test_db.commit()

    resp = client.post(f"/api/orgs/join/{inv.token}", headers=_auth(accepter))
    assert resp.status_code == 200

    rows = _notifications_for(test_db, inviter, "invitation.accepted")
    assert len(rows) == 1
    assert rows[0].org_id == org.id


def test_invitation_accepted_negative_no_optin(client, test_db):
    org = _make_org(test_db, "invneg")
    inviter = _make_user(test_db, "invn_inviter")
    accepter = _make_user(test_db, "invn_accepter")
    make_org_membership(test_db, org_id=org.id, user_id=inviter.id, role="admin")
    inv = models.Invitation(
        org_id=org.id, email=accepter.email, invited_by=inviter.id,
        role="member", token="invtok456",
        expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=7),
    )
    test_db.add(inv)
    test_db.commit()

    resp = client.post(f"/api/orgs/join/{inv.token}", headers=_auth(accepter))
    assert resp.status_code == 200
    rows = _notifications_for(test_db, inviter, "invitation.accepted")
    assert rows == []


# ---------------------------------------------------------------------------
# Site 5+6 — proposal.entered_voting / proposal.closed
# ---------------------------------------------------------------------------

def test_proposal_entered_voting_emits_to_eligible_voters(client, test_db):
    org = _make_org(test_db, "advorg")
    author = _make_user(test_db, "adv_author")
    voter1 = _make_user(test_db, "adv_voter1")
    voter2 = _make_user(test_db, "adv_voter2")
    make_org_membership(test_db, org_id=org.id, user_id=author.id, role="admin")
    make_org_membership(test_db, org_id=org.id, user_id=voter1.id, role="member")
    make_org_membership(test_db, org_id=org.id, user_id=voter2.id, role="member")
    proposal = _make_proposal(test_db, author, org, status="deliberation")
    _opt_in(test_db, voter1, "proposal.entered_voting")
    _opt_in(test_db, voter2, "proposal.entered_voting")
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/proposals/{proposal.id}/advance",
        json={},
        headers=_auth(author),
    )
    assert resp.status_code == 200, resp.text

    for v in (voter1, voter2):
        rows = _notifications_for(test_db, v, "proposal.entered_voting")
        assert len(rows) == 1
        assert rows[0].org_id == org.id


def test_proposal_entered_voting_negative(client, test_db):
    org = _make_org(test_db, "advneg")
    author = _make_user(test_db, "advn_author")
    voter1 = _make_user(test_db, "advn_voter1")
    make_org_membership(test_db, org_id=org.id, user_id=author.id, role="admin")
    make_org_membership(test_db, org_id=org.id, user_id=voter1.id, role="member")
    proposal = _make_proposal(test_db, author, org, status="deliberation")
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/proposals/{proposal.id}/advance",
        json={},
        headers=_auth(author),
    )
    assert resp.status_code == 200
    rows = _notifications_for(test_db, voter1, "proposal.entered_voting")
    assert rows == []


def test_proposal_closed_emits_to_author_and_voters_deduped(client, test_db):
    org = _make_org(test_db, "closeorg")
    author = _make_user(test_db, "cl_author")
    voter = _make_user(test_db, "cl_voter")
    make_org_membership(test_db, org_id=org.id, user_id=author.id, role="admin")
    make_org_membership(test_db, org_id=org.id, user_id=voter.id, role="member")
    # Author votes too (so dedup kicks in for them).
    proposal = _make_proposal(test_db, author, org, status="voting")
    proposal.voting_start = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=8)
    proposal.voting_end = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    test_db.flush()
    test_db.add(models.Vote(
        proposal_id=proposal.id, user_id=author.id, vote_value="yes",
        is_direct=True, cast_by_id=author.id,
    ))
    test_db.add(models.Vote(
        proposal_id=proposal.id, user_id=voter.id, vote_value="yes",
        is_direct=True, cast_by_id=voter.id,
    ))
    _opt_in(test_db, author, "proposal.closed")
    _opt_in(test_db, voter, "proposal.closed")
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/proposals/{proposal.id}/advance",
        json={},
        headers=_auth(author),
    )
    assert resp.status_code == 200

    # Author should have exactly ONE row (deduplication) even though they
    # are both author + voter.
    author_rows = _notifications_for(test_db, author, "proposal.closed")
    assert len(author_rows) == 1
    voter_rows = _notifications_for(test_db, voter, "proposal.closed")
    assert len(voter_rows) == 1


def test_proposal_closed_negative(client, test_db):
    org = _make_org(test_db, "closeneg")
    author = _make_user(test_db, "cln_author")
    voter = _make_user(test_db, "cln_voter")
    make_org_membership(test_db, org_id=org.id, user_id=author.id, role="admin")
    make_org_membership(test_db, org_id=org.id, user_id=voter.id, role="member")
    proposal = _make_proposal(test_db, author, org, status="voting")
    proposal.voting_start = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=8)
    proposal.voting_end = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    test_db.flush()
    test_db.add(models.Vote(
        proposal_id=proposal.id, user_id=voter.id, vote_value="yes",
        is_direct=True, cast_by_id=voter.id,
    ))
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/proposals/{proposal.id}/advance",
        json={},
        headers=_auth(author),
    )
    assert resp.status_code == 200
    assert _notifications_for(test_db, voter, "proposal.closed") == []


# ---------------------------------------------------------------------------
# Site 7 — sustained_majority.floor_approached (worker)
# ---------------------------------------------------------------------------

def test_sustained_majority_floor_approached_emits_idempotently(test_db):
    """Direct unit test of the worker's floor_approached path."""
    from sustained_majority_worker import _maybe_emit_floor_approached
    from sustained_majority import (
        BinarySnapshotPoint,
        SustainedMajorityConfig,
    )

    org = _make_org(test_db, "smorg")
    author = _make_user(test_db, "sm_author")
    voter = _make_user(test_db, "sm_voter")
    make_org_membership(test_db, org_id=org.id, user_id=author.id, role="admin")
    make_org_membership(test_db, org_id=org.id, user_id=voter.id, role="member")
    proposal = _make_proposal(test_db, author, org, status="voting")
    test_db.add(models.Vote(
        proposal_id=proposal.id, user_id=voter.id, vote_value="no",
        is_direct=True, cast_by_id=voter.id,
    ))
    _opt_in(test_db, author, "sustained_majority.floor_approached")
    _opt_in(test_db, voter, "sustained_majority.floor_approached")
    test_db.commit()

    # Snapshot showing support = 0.46 (just above floor 0.45 + 5% delta).
    snap = BinarySnapshotPoint(
        simulated_time=datetime.now(timezone.utc).replace(tzinfo=None),
        yes=46, no=54, abstain=0, total_eligible=100,
    )
    config = SustainedMajorityConfig(
        enabled_default=True, per_proposal_override=True,
        threshold=0.50, floor=0.45, failure_mode="fail",
    )
    _maybe_emit_floor_approached(test_db, proposal, [snap], config)
    test_db.flush()

    assert len(_notifications_for(test_db, author, "sustained_majority.floor_approached")) == 1
    assert len(_notifications_for(test_db, voter, "sustained_majority.floor_approached")) == 1

    # Second call within the dedup window should NOT emit again.
    _maybe_emit_floor_approached(test_db, proposal, [snap], config)
    test_db.flush()
    assert len(_notifications_for(test_db, author, "sustained_majority.floor_approached")) == 1


def test_sustained_majority_floor_approached_negative(test_db):
    from sustained_majority_worker import _maybe_emit_floor_approached
    from sustained_majority import (
        BinarySnapshotPoint,
        SustainedMajorityConfig,
    )

    org = _make_org(test_db, "smneg")
    author = _make_user(test_db, "smn_author")
    make_org_membership(test_db, org_id=org.id, user_id=author.id, role="admin")
    proposal = _make_proposal(test_db, author, org, status="voting")
    # No opt-in -> no row.
    test_db.commit()

    snap = BinarySnapshotPoint(
        simulated_time=datetime.now(timezone.utc).replace(tzinfo=None),
        yes=46, no=54, abstain=0, total_eligible=100,
    )
    config = SustainedMajorityConfig(
        enabled_default=True, per_proposal_override=True,
        threshold=0.50, floor=0.45, failure_mode="fail",
    )
    _maybe_emit_floor_approached(test_db, proposal, [snap], config)
    test_db.flush()

    rows = _notifications_for(test_db, author, "sustained_majority.floor_approached")
    assert rows == []


# ---------------------------------------------------------------------------
# Site 8+9 — delegate.applied / delegate.application_decided
# ---------------------------------------------------------------------------

def test_delegate_applied_emits_to_admins(client, test_db):
    org = _make_org(test_db, "dapp")
    admin = _make_user(test_db, "da_admin")
    applicant = _make_user(test_db, "da_applicant")
    make_org_membership(test_db, org_id=org.id, user_id=admin.id, role="admin")
    make_org_membership(test_db, org_id=org.id, user_id=applicant.id, role="member")
    topic = models.Topic(org_id=org.id, name="Budget", description="")
    test_db.add(topic)
    test_db.flush()
    _opt_in(test_db, admin, "delegate.applied")
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/delegate-applications",
        json={"topic_id": topic.id, "bio": "I want to delegate"},
        headers=_auth(applicant),
    )
    assert resp.status_code == 201, resp.text

    rows = _notifications_for(test_db, admin, "delegate.applied")
    assert len(rows) == 1
    assert rows[0].org_id == org.id


def test_delegate_applied_negative(client, test_db):
    org = _make_org(test_db, "dappneg")
    admin = _make_user(test_db, "dan_admin")
    applicant = _make_user(test_db, "dan_applicant")
    make_org_membership(test_db, org_id=org.id, user_id=admin.id, role="admin")
    make_org_membership(test_db, org_id=org.id, user_id=applicant.id, role="member")
    topic = models.Topic(org_id=org.id, name="Budget", description="")
    test_db.add(topic)
    test_db.flush()
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/delegate-applications",
        json={"topic_id": topic.id, "bio": "I want to delegate"},
        headers=_auth(applicant),
    )
    assert resp.status_code == 201

    rows = _notifications_for(test_db, admin, "delegate.applied")
    assert rows == []


def test_delegate_application_decided_emits_on_approve(client, test_db):
    org = _make_org(test_db, "dec")
    admin = _make_user(test_db, "dec_admin")
    applicant = _make_user(test_db, "dec_applicant")
    make_org_membership(test_db, org_id=org.id, user_id=admin.id, role="admin")
    make_org_membership(test_db, org_id=org.id, user_id=applicant.id, role="member")
    topic = models.Topic(org_id=org.id, name="Budget", description="")
    test_db.add(topic)
    test_db.flush()
    app_row = models.DelegateApplication(
        user_id=applicant.id, org_id=org.id, topic_id=topic.id, bio="bio",
    )
    test_db.add(app_row)
    _opt_in(test_db, applicant, "delegate.application_decided")
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/delegate-applications/{app_row.id}/approve",
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text

    rows = _notifications_for(test_db, applicant, "delegate.application_decided")
    assert len(rows) == 1
    assert rows[0].payload["decision"] == "approved"


def test_delegate_application_decided_emits_on_deny(client, test_db):
    org = _make_org(test_db, "decden")
    admin = _make_user(test_db, "decd_admin")
    applicant = _make_user(test_db, "decd_applicant")
    make_org_membership(test_db, org_id=org.id, user_id=admin.id, role="admin")
    make_org_membership(test_db, org_id=org.id, user_id=applicant.id, role="member")
    topic = models.Topic(org_id=org.id, name="Budget", description="")
    test_db.add(topic)
    test_db.flush()
    app_row = models.DelegateApplication(
        user_id=applicant.id, org_id=org.id, topic_id=topic.id, bio="bio",
    )
    test_db.add(app_row)
    _opt_in(test_db, applicant, "delegate.application_decided")
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/delegate-applications/{app_row.id}/deny",
        json={"feedback": "Not a fit right now"},
        headers=_auth(admin),
    )
    assert resp.status_code == 200

    rows = _notifications_for(test_db, applicant, "delegate.application_decided")
    assert len(rows) == 1
    assert rows[0].payload["decision"] == "denied"


def test_delegate_application_decided_negative(client, test_db):
    org = _make_org(test_db, "decneg")
    admin = _make_user(test_db, "decn_admin")
    applicant = _make_user(test_db, "decn_applicant")
    make_org_membership(test_db, org_id=org.id, user_id=admin.id, role="admin")
    make_org_membership(test_db, org_id=org.id, user_id=applicant.id, role="member")
    topic = models.Topic(org_id=org.id, name="Budget", description="")
    test_db.add(topic)
    test_db.flush()
    app_row = models.DelegateApplication(
        user_id=applicant.id, org_id=org.id, topic_id=topic.id, bio="bio",
    )
    test_db.add(app_row)
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/delegate-applications/{app_row.id}/approve",
        headers=_auth(admin),
    )
    assert resp.status_code == 200
    rows = _notifications_for(test_db, applicant, "delegate.application_decided")
    assert rows == []


# ---------------------------------------------------------------------------
# Site 10+11 — follow.requested / follow.approved
# ---------------------------------------------------------------------------

def test_follow_requested_emits_to_target(client, test_db):
    requester = _make_user(test_db, "fr_req")
    target = _make_user(test_db, "fr_target")
    _opt_in(test_db, target, "follow.requested")
    test_db.commit()

    resp = client.post(
        "/api/follows/request",
        json={"target_id": target.id, "message": "hi"},
        headers=_auth(requester),
    )
    assert resp.status_code == 201, resp.text

    rows = _notifications_for(test_db, target, "follow.requested")
    assert len(rows) == 1
    assert rows[0].org_id is None  # account-level event


def test_follow_requested_negative(client, test_db):
    requester = _make_user(test_db, "frn_req")
    target = _make_user(test_db, "frn_target")
    test_db.commit()

    resp = client.post(
        "/api/follows/request",
        json={"target_id": target.id, "message": "hi"},
        headers=_auth(requester),
    )
    assert resp.status_code == 201
    rows = _notifications_for(test_db, target, "follow.requested")
    assert rows == []


def test_follow_approved_emits_to_requester_on_respond(client, test_db):
    requester = _make_user(test_db, "fap_req")
    target = _make_user(test_db, "fap_target")
    test_db.commit()

    # Create a pending request first (without opt-in so requested doesn't notify)
    resp = client.post(
        "/api/follows/request",
        json={"target_id": target.id, "message": "hi"},
        headers=_auth(requester),
    )
    assert resp.status_code == 201
    freq_id = resp.json()["id"]
    # Now opt requester IN to follow.approved
    _opt_in(test_db, requester, "follow.approved")
    test_db.commit()

    resp2 = client.put(
        f"/api/follows/requests/{freq_id}/respond",
        json={"status": "approved", "permission_level": "view_only"},
        headers=_auth(target),
    )
    assert resp2.status_code == 200, resp2.text

    rows = _notifications_for(test_db, requester, "follow.approved")
    assert len(rows) == 1


def test_follow_approved_emits_on_auto_approve(client, test_db):
    requester = _make_user(test_db, "fauto_req")
    # auto-approve target
    target = _make_user(
        test_db, "fauto_target", default_follow_policy="auto_approve_view",
    )
    _opt_in(test_db, requester, "follow.approved")
    test_db.commit()

    resp = client.post(
        "/api/follows/request",
        json={"target_id": target.id},
        headers=_auth(requester),
    )
    assert resp.status_code == 201

    rows = _notifications_for(test_db, requester, "follow.approved")
    assert len(rows) == 1


def test_follow_approved_negative(client, test_db):
    requester = _make_user(test_db, "fapn_req")
    target = _make_user(test_db, "fapn_target")
    test_db.commit()

    resp = client.post(
        "/api/follows/request",
        json={"target_id": target.id},
        headers=_auth(requester),
    )
    freq_id = resp.json()["id"]
    resp2 = client.put(
        f"/api/follows/requests/{freq_id}/respond",
        json={"status": "approved", "permission_level": "view_only"},
        headers=_auth(target),
    )
    assert resp2.status_code == 200
    rows = _notifications_for(test_db, requester, "follow.approved")
    assert rows == []


# ---------------------------------------------------------------------------
# Site 12 — polis.created
# ---------------------------------------------------------------------------

def test_polis_created_emits_to_org_members(client, test_db):
    org = _make_org(test_db, "polorg")
    creator = _make_user(test_db, "pol_creator")
    member = _make_user(test_db, "pol_member")
    other = _make_user(test_db, "pol_other")
    make_org_membership(test_db, org_id=org.id, user_id=creator.id, role="admin")
    make_org_membership(test_db, org_id=org.id, user_id=member.id, role="member")
    make_org_membership(test_db, org_id=org.id, user_id=other.id, role="member")
    _opt_in(test_db, member, "polis.created")
    _opt_in(test_db, other, "polis.created")
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/polises",
        json={
            "title": "New Polis",
            "prompt": "Discuss",
            "polis_conversation_id": "conv-123",
            "seed_statements": [],
        },
        headers=_auth(creator),
    )
    assert resp.status_code == 201, resp.text

    for u in (member, other):
        rows = _notifications_for(test_db, u, "polis.created")
        assert len(rows) == 1
        assert rows[0].org_id == org.id

    # Creator should NOT be notified.
    creator_rows = _notifications_for(test_db, creator, "polis.created")
    assert creator_rows == []


def test_polis_created_negative(client, test_db):
    org = _make_org(test_db, "polneg")
    creator = _make_user(test_db, "pol_n_creator")
    member = _make_user(test_db, "pol_n_member")
    make_org_membership(test_db, org_id=org.id, user_id=creator.id, role="admin")
    make_org_membership(test_db, org_id=org.id, user_id=member.id, role="member")
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/polises",
        json={
            "title": "Solo Polis",
            "prompt": "Hi",
            "polis_conversation_id": "conv-456",
            "seed_statements": [],
        },
        headers=_auth(creator),
    )
    assert resp.status_code == 201
    rows = _notifications_for(test_db, member, "polis.created")
    assert rows == []
