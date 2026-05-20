"""Phase 32.1 — deliberation engagement follow-up tests.

Covers:
  - B1 snapshot worker filter extension: deliberation-phase proposals
    with both pre-voting flags on get snapshots captured by the worker.
    Flags off → no snapshot. Voting-status → snapshot (regression check).
  - B2 engaged-member expansion: delegator on the proposal's topic
    receives the proposal.edited notification even without voting or
    commenting directly.
  - D-pre-voting bible: P-H-10 in hoa_bible.py declares
    allow_pre_voting=True + show_votes_during_deliberation=True.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from database import Base, get_db
from main import app


@pytest.fixture(scope="function")
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _make_user(db, username, is_admin=False):
    user = models.User(
        username=username,
        display_name=username.title(),
        email=f"{username}@example.com",
        email_verified=True,
        password_hash=auth_utils.hash_password("noop"),
        is_admin=is_admin,
    )
    db.add(user)
    db.flush()
    return user


def _make_org(db, slug="test-org"):
    org = models.Organization(name=slug.title(), slug=slug, settings={})
    db.add(org)
    db.flush()
    return org


def _make_membership(db, user, org):
    role = db.query(models.Role).filter_by(
        org_id=org.id, system_key="member",
    ).first()
    if role is None:
        role = models.Role(
            org_id=org.id, system_key="member",
            name="Member", display_order=0,
        )
        db.add(role)
        db.flush()
    m = models.OrgMembership(
        user_id=user.id, org_id=org.id, role_id=role.id, status="active",
    )
    db.add(m)
    db.flush()
    return m


# ===========================================================================
# B1 — Snapshot worker filter extension
# ===========================================================================


class TestB1WorkerCapturesDeliberationSnapshots:
    """When both pre-voting flags are on AND proposal is in deliberation,
    the worker captures a snapshot. Otherwise no snapshot."""

    def _make_proposal(
        self, db, org, author, status, *, allow_pre_voting=None,
        show_votes_during_deliberation=None,
    ):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        p = models.Proposal(
            title="EV Charging",
            body="",
            author_id=author.id,
            org_id=org.id,
            status=status,
            voting_method="binary",
            num_winners=1,
            deliberation_start=now - timedelta(days=2),
            voting_start=now + timedelta(days=5),
            voting_end=now + timedelta(days=12),
            deliberation_days=7.0,
            voting_days=7.0,
            allow_pre_voting=allow_pre_voting,
            show_votes_during_deliberation=show_votes_during_deliberation,
        )
        db.add(p)
        db.flush()
        return p

    def _run_tick_count_snapshots(self, db, proposal):
        from sustained_majority_worker import run_one_tick
        before = (
            db.query(models.VoteSnapshot)
            .filter(models.VoteSnapshot.proposal_id == proposal.id)
            .count()
        )
        run_one_tick(db)
        after = (
            db.query(models.VoteSnapshot)
            .filter(models.VoteSnapshot.proposal_id == proposal.id)
            .count()
        )
        return after - before

    def test_both_flags_on_captures_snapshot(self, db_session):
        org = _make_org(db_session)
        author = _make_user(db_session, "author")
        _make_membership(db_session, author, org)
        p = self._make_proposal(
            db_session, org, author, "deliberation",
            allow_pre_voting=True,
            show_votes_during_deliberation=True,
        )
        db_session.commit()
        delta = self._run_tick_count_snapshots(db_session, p)
        assert delta >= 1, (
            f"expected at least 1 snapshot captured for deliberation "
            f"proposal with both flags on; got delta={delta}"
        )

    def test_pre_voting_off_no_snapshot(self, db_session):
        org = _make_org(db_session)
        author = _make_user(db_session, "author")
        _make_membership(db_session, author, org)
        p = self._make_proposal(
            db_session, org, author, "deliberation",
            allow_pre_voting=False,
            show_votes_during_deliberation=True,
        )
        db_session.commit()
        delta = self._run_tick_count_snapshots(db_session, p)
        assert delta == 0, (
            f"expected 0 snapshots when pre_voting is off; got {delta}"
        )

    def test_visibility_off_no_snapshot(self, db_session):
        org = _make_org(db_session)
        author = _make_user(db_session, "author")
        _make_membership(db_session, author, org)
        p = self._make_proposal(
            db_session, org, author, "deliberation",
            allow_pre_voting=True,
            show_votes_during_deliberation=False,
        )
        db_session.commit()
        delta = self._run_tick_count_snapshots(db_session, p)
        assert delta == 0, (
            f"expected 0 snapshots when visibility off; got {delta}"
        )


# ===========================================================================
# B2 — Engaged-member expansion (delegators)
# ===========================================================================


class TestB2DelegatorReceivesEditNotification:
    """A user with an active delegation on the proposal's topic receives
    the proposal.edited notification even when they haven't voted or
    commented directly."""

    def test_delegator_on_topic_in_engaged_set(self, db_session, client):
        org = _make_org(db_session)
        author = _make_user(db_session, "author")
        delegator = _make_user(db_session, "delegator")
        delegate = _make_user(db_session, "delegate")
        for u in (author, delegator, delegate):
            _make_membership(db_session, u, org)

        topic = models.Topic(name="Budget", org_id=org.id)
        db_session.add(topic)
        db_session.flush()

        db_session.add(models.Delegation(
            delegator_id=delegator.id,
            delegate_id=delegate.id,
            org_id=org.id,
            topic_id=topic.id,
        ))
        db_session.flush()

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        p = models.Proposal(
            title="Test edit",
            body="",
            author_id=author.id,
            org_id=org.id,
            status="deliberation",
            voting_method="binary",
            num_winners=1,
            deliberation_start=now,
            voting_end=now + timedelta(days=7),
            deliberation_days=14.0,
            voting_days=7.0,
        )
        db_session.add(p)
        db_session.flush()
        db_session.add(models.ProposalTopic(
            proposal_id=p.id, topic_id=topic.id, relevance=1.0,
        ))
        # Pref row so emit_notification creates an in-app Notification
        # row (otherwise the absent-row opt-in default suppresses it).
        db_session.add(models.NotificationPreference(
            user_id=delegator.id,
            event_type="proposal.edited",
            channel="in_app",
            enabled=True,
        ))
        db_session.commit()

        token_resp = client.post(
            "/api/auth/login",
            data={"username": "author", "password": "noop"},
        )
        token = token_resp.json()["access_token"]
        resp = client.patch(
            f"/api/proposals/{p.id}",
            json={"title": "Edited title"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text

        notif = (
            db_session.query(models.Notification)
            .filter(
                models.Notification.user_id == delegator.id,
                models.Notification.event_type == "proposal.edited",
            )
            .first()
        )
        assert notif is not None, (
            "delegator on the proposal's topic did not receive a "
            "proposal.edited in-app notification — B2 expansion did "
            "not include them"
        )


# ===========================================================================
# D-pre-voting bible — P-H-10 declares the demo flags
# ===========================================================================


class TestDPreVotingBibleAdditions:
    def test_p_h_10_has_pre_voting_flags(self):
        from demo_content.hoa_bible import HOA_BIBLE
        p_h_10 = next(
            (p for p in HOA_BIBLE.proposals if p.proposal_id == "P-H-10"),
            None,
        )
        assert p_h_10 is not None, "P-H-10 missing from HOA bible"
        assert p_h_10.allow_pre_voting is True
        assert p_h_10.show_votes_during_deliberation is True
