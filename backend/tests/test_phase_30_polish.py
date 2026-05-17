"""Phase 30 — registration + demo polish tests.

Covers:
  - B2: backend submit-public-accepting contract preserved (frontend
    bridges the two-step transition; backend rules unchanged).
  - B3: personas JSONB includes avatar_url.
  - C1: three new proposals seed with correct status + topics, P-H-11
    and P-H-12 generate snapshots, P-H-10 (deliberation) does not.
  - C1: P-H-12 vote rationales seed with the 3-2 split per the
    contested trajectory.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from auth import hash_password
from database import Base, get_db
from demo_content.hoa_bible import HOA_BIBLE
from demo_content.seed_pipeline import _underlying_username, seed_org_from_bible
from main import app
from role_seed import seed_default_roles_for_org


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
def seeded_hoa(db_session):
    seed_org_from_bible(
        db_session,
        HOA_BIBLE,
        now=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db_session.commit()
    org = db_session.query(models.Organization).filter_by(
        slug="demo-cedar-hollow",
    ).first()
    return db_session, org


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


def _find_proposal(db: Session, org_id: str, title_fragment: str) -> models.Proposal | None:
    return (
        db.query(models.Proposal)
        .filter(
            models.Proposal.org_id == org_id,
            models.Proposal.title.like(f"%{title_fragment}%"),
        )
        .first()
    )


# ===========================================================================
# B3 — Demo persona avatars
# ===========================================================================


class TestSeedPipelinePersonasIncludeAvatarUrl:
    """personas JSONB has avatar_url for each quick-login HOA persona."""

    def test_all_six_personas_have_avatar_url(self, seeded_hoa):
        _, org = seeded_hoa
        personas = org.personas or []
        assert len(personas) == 6, f"expected 6 personas, got {len(personas)}"
        for p in personas:
            assert "avatar_url" in p, f"persona {p['username']!r} missing avatar_url key"
            assert p["avatar_url"] is not None, (
                f"persona {p['username']!r} avatar_url is None — Phase 29 C6 only "
                f"wires avatar_url for HOA bible members; if this fails the C6 "
                f"path regressed."
            )
            assert p["avatar_url"].startswith("/demo_assets/portraits/"), (
                f"persona {p['username']!r} avatar_url unexpected shape: "
                f"{p['avatar_url']!r}"
            )


# ===========================================================================
# C1 — New active proposals
# ===========================================================================


class TestNewProposalsSeedCorrectly:
    """P-H-10, P-H-11, P-H-12 exist with correct status and topics."""

    def test_p_h_10_deliberation(self, seeded_hoa):
        db, org = seeded_hoa
        p = _find_proposal(db, org.id, "EV Charging Station")
        assert p is not None
        assert p.status == "deliberation"
        assert p.voting_method == "binary"
        # Phase 30.1 B5 — Topic.name is now scoped per-org so demos no
        # longer prefix the name; assert directly on .name.
        topic_names = {pt.topic.name for pt in p.proposal_topics}
        assert "Long-Term Planning" in topic_names
        assert "Budget" in topic_names

    def test_p_h_11_voting_approval(self, seeded_hoa):
        db, org = seeded_hoa
        p = _find_proposal(db, org.id, "Entrance Signage")
        assert p is not None
        assert p.status == "voting"
        assert p.voting_method == "approval"
        assert len(p.options) == 4

    def test_p_h_12_voting_binary(self, seeded_hoa):
        db, org = seeded_hoa
        p = _find_proposal(db, org.id, "Pool Membership Fees")
        assert p is not None
        assert p.status == "voting"
        assert p.voting_method == "binary"


class TestNewProposalTrajectoriesGenerateSnapshots:
    """Voting proposals (P-H-11, P-H-12) generate VoteSnapshot rows;
    P-H-10 (deliberation) generates none."""

    def test_p_h_10_no_snapshots(self, seeded_hoa):
        db, org = seeded_hoa
        p = _find_proposal(db, org.id, "EV Charging Station")
        assert db.query(models.VoteSnapshot).filter_by(proposal_id=p.id).count() == 0

    def test_p_h_11_has_snapshots(self, seeded_hoa):
        db, org = seeded_hoa
        p = _find_proposal(db, org.id, "Entrance Signage")
        assert db.query(models.VoteSnapshot).filter_by(proposal_id=p.id).count() > 0

    def test_p_h_12_has_snapshots(self, seeded_hoa):
        db, org = seeded_hoa
        p = _find_proposal(db, org.id, "Pool Membership Fees")
        assert db.query(models.VoteSnapshot).filter_by(proposal_id=p.id).count() > 0


class TestProposalPH12NamedDelegateVotes:
    """P-H-12 has the 3-2 yes/no split from the 5 named delegates'
    vote rationales authored in C1. The seed pipeline writes Vote
    rows but doesn't persist the rationale text into
    DelegateVoteRationale (pre-existing — the rationale text only
    influences which Vote row gets created, not where it's stored)."""

    def test_3_yes_2_no_split(self, seeded_hoa):
        db, org = seeded_hoa
        p = _find_proposal(db, org.id, "Pool Membership Fees")
        named_usernames = {
            _underlying_username("hoa_janet"),
            "hoa_brenda",
            _underlying_username("hoa_marcus"),
            "hoa_don",
            "hoa_linda",
        }
        votes = (
            db.query(models.Vote, models.User)
            .join(models.User, models.Vote.user_id == models.User.id)
            .filter(
                models.Vote.proposal_id == p.id,
                models.User.username.in_(named_usernames),
            )
            .all()
        )
        votes_by_user = {u.username: v.vote_value for v, u in votes}
        assert votes_by_user.get(_underlying_username("hoa_janet")) == "yes"
        assert votes_by_user.get("hoa_brenda") == "yes"
        assert votes_by_user.get("hoa_linda") == "yes"
        assert votes_by_user.get(_underlying_username("hoa_marcus")) == "no"
        assert votes_by_user.get("hoa_don") == "no"


# ===========================================================================
# B2 — Backend contract preservation
# ===========================================================================
#
# Phase 30's frontend fix bridges private → public_accepting with two
# sequential backend calls (PATCH then POST). These tests pin the
# backend's existing behavior so a future change can't quietly break
# the frontend bridge.


@pytest.fixture(scope="function")
def org_with_user(db_session):
    """Minimal org + member with a topic + delegate profile in 'private'."""
    org = models.Organization(
        slug="test-org", name="Test Org",
        description="", join_policy="open", is_demo=False,
    )
    db_session.add(org)
    db_session.flush()
    seed_default_roles_for_org(db_session, org.id)

    member_role = db_session.query(models.Role).filter_by(
        org_id=org.id, system_key="member",
    ).first()

    user = models.User(
        username="alice", display_name="Alice",
        password_hash=hash_password("x"),
        email="alice@test.example", email_verified=True,
    )
    db_session.add(user)
    db_session.flush()

    db_session.add(models.OrgMembership(
        user_id=user.id, org_id=org.id, role_id=member_role.id, status="active",
    ))

    topic = models.Topic(
        name="test-org:Budget", description="Budget",
        color="#000000", org_id=org.id,
    )
    db_session.add(topic)
    db_session.flush()

    dp = models.DelegateProfile(
        user_id=user.id, org_id=org.id, topic_id=topic.id,
        bio="x" * 60,
        visibility="private",
    )
    db_session.add(dp)
    db_session.commit()

    return db_session, org, user, topic


def _auth_header(user_id: str) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user_id)}"}


class TestSubmitPublicAcceptingFromPrivateRejectedAtBackend:
    """Calling submit-public-accepting when the profile is at 'private'
    must return 400 with the existing error message. The frontend
    bridge issues a PATCH first; the backend contract doesn't change."""

    def test_returns_400(self, org_with_user, client):
        _, org, user, topic = org_with_user
        resp = client.post(
            f"/api/orgs/{org.slug}/delegate-profile/topics/{topic.id}/submit-public-accepting",
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 400
        assert "public" in resp.json().get("detail", "").lower()


class TestSubmitPublicAcceptingFromPublicStillWorks:
    """The canonical public → public_accepting path through
    submit-public-accepting (existing pre-Phase-30 flow) is unchanged."""

    def test_promotes_to_public_accepting(self, org_with_user, client):
        db, org, user, topic = org_with_user
        dp = db.query(models.DelegateProfile).filter_by(
            user_id=user.id, topic_id=topic.id,
        ).first()
        dp.visibility = "public"
        db.commit()

        resp = client.post(
            f"/api/orgs/{org.slug}/delegate-profile/topics/{topic.id}/submit-public-accepting",
            headers=_auth_header(user.id),
        )
        assert resp.status_code == 200, resp.json()

        db.refresh(dp)
        # Without approvers in the test org, submit auto-approves and
        # transitions the topic immediately to public_accepting.
        assert dp.visibility == "public_accepting"
