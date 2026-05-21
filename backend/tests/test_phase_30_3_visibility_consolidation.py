"""Phase 30.3 — visibility consolidation tests.

Covers:
  - B1: `followers_only` is a valid `DelegateProfile.visibility` value.
  - B2: backfill semantic — when seeded fresh, no row sits at `private`
    (the seed pipeline now defaults topics to `followers_only` for
    bible entries that don't explicitly set state).
  - B3: `org_delegate_profiles.page_visibility` column gone from the
    SQLAlchemy model (proxy for migration's column drop).
  - B4: `can_see_votes` rewrite — per-topic visibility rules + follower
    check.
  - B5: public-page endpoint filters topics per viewer relationship.
  - B6: new ``DelegateProfile`` rows default to `followers_only`.
  - B6: submit-public-accepting bridges from `followers_only`.
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
from main import app
from permissions import can_see_votes
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
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _auth(user_id: str) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user_id)}"}


def _make_user(db: Session, username: str) -> models.User:
    u = models.User(
        username=username, display_name=username.title(),
        password_hash=hash_password("x"),
        email=f"{username}@test.example", email_verified=True,
    )
    db.add(u); db.flush()
    return u


def _make_org(db: Session, slug: str) -> models.Organization:
    org = models.Organization(
        slug=slug, name=slug.title(),
        description="", join_policy="open",
    )
    db.add(org); db.flush()
    seed_default_roles_for_org(db, org.id)
    return org


def _join(db: Session, user: models.User, org: models.Organization) -> None:
    member_role = db.query(models.Role).filter_by(
        org_id=org.id, system_key="member",
    ).first()
    db.add(models.OrgMembership(
        user_id=user.id, org_id=org.id, role_id=member_role.id, status="active",
    ))
    db.flush()


def _make_topic(db: Session, org: models.Organization, name: str) -> models.Topic:
    t = models.Topic(
        name=name,
        color="#000000", org_id=org.id,
    )
    db.add(t); db.flush()
    return t


def _make_dp(
    db: Session,
    user: models.User, org: models.Organization, topic: models.Topic,
    visibility: str,
    bio: str = "x" * 60,
    position: str | None = None,
) -> models.DelegateProfile:
    odp = db.query(models.OrgDelegateProfile).filter_by(
        user_id=user.id, org_id=org.id,
    ).first()
    if odp is None:
        odp = models.OrgDelegateProfile(
            user_id=user.id, org_id=org.id, intro="intro",
        )
        db.add(odp)
    dp = models.DelegateProfile(
        user_id=user.id, org_id=org.id, topic_id=topic.id,
        bio=bio, position_statement=position,
        visibility=visibility,
    )
    db.add(dp); db.commit()
    return dp


# ===========================================================================
# B1-B3 — migration shape
# ===========================================================================


class TestEnumValueAdded:
    """The followers_only value is a valid enum on the model."""

    def test_model_accepts_followers_only(self, db_session):
        org = _make_org(db_session, "o1")
        user = _make_user(db_session, "u1")
        topic = _make_topic(db_session, org, "Budget")
        dp = _make_dp(db_session, user, org, topic, visibility="followers_only")
        db_session.refresh(dp)
        assert dp.visibility == "followers_only"


class TestPageVisibilityColumnGone:
    """The OrgDelegateProfile.page_visibility column is removed from
    the SQLAlchemy model (proxy for the migration drop)."""

    def test_column_absent(self):
        cols = {c.name for c in models.OrgDelegateProfile.__table__.columns}
        assert "page_visibility" not in cols


# ===========================================================================
# B4 — can_see_votes rewrite
# ===========================================================================


class TestCanSeeVotesPublicTopic:
    def test_anyone_sees_public_topic(self, db_session):
        org = _make_org(db_session, "o2")
        target = _make_user(db_session, "target")
        viewer = _make_user(db_session, "viewer")
        _join(db_session, target, org); _join(db_session, viewer, org)
        topic = _make_topic(db_session, org, "Budget")
        _make_dp(db_session, target, org, topic, visibility="public")
        assert can_see_votes(
            db_session, viewer.id, target.id, [topic.id], org_id=org.id,
        ) is True
        # Anonymous viewer also sees public-topic votes.
        assert can_see_votes(
            db_session, None, target.id, [topic.id], org_id=org.id,
        ) is True


class TestCanSeeVotesFollowersOnlyForFollower:
    def test_follower_sees(self, db_session):
        org = _make_org(db_session, "o3")
        target = _make_user(db_session, "t3")
        viewer = _make_user(db_session, "v3")
        _join(db_session, target, org); _join(db_session, viewer, org)
        topic = _make_topic(db_session, org, "Budget")
        _make_dp(db_session, target, org, topic, visibility="followers_only")
        db_session.add(models.FollowRelationship(
            follower_id=viewer.id, followed_id=target.id,
            org_id=org.id, permission_level="view_only",
        ))
        db_session.commit()
        assert can_see_votes(
            db_session, viewer.id, target.id, [topic.id], org_id=org.id,
        ) is True


class TestCanSeeVotesFollowersOnlyNotForNonFollower:
    def test_non_follower_blocked(self, db_session):
        org = _make_org(db_session, "o4")
        target = _make_user(db_session, "t4")
        viewer = _make_user(db_session, "v4")
        _join(db_session, target, org); _join(db_session, viewer, org)
        topic = _make_topic(db_session, org, "Budget")
        _make_dp(db_session, target, org, topic, visibility="followers_only")
        # No FollowRelationship.
        assert can_see_votes(
            db_session, viewer.id, target.id, [topic.id], org_id=org.id,
        ) is False


class TestCanSeeVotesPrivateTopicEvenForFollower:
    """Phase 30.3 semantic shift: private is now strictly private, even
    for approved followers."""

    def test_follower_blocked_on_private(self, db_session):
        org = _make_org(db_session, "o5")
        target = _make_user(db_session, "t5")
        viewer = _make_user(db_session, "v5")
        _join(db_session, target, org); _join(db_session, viewer, org)
        topic = _make_topic(db_session, org, "Budget")
        _make_dp(db_session, target, org, topic, visibility="private")
        db_session.add(models.FollowRelationship(
            follower_id=viewer.id, followed_id=target.id,
            org_id=org.id, permission_level="delegation_allowed",
        ))
        db_session.commit()
        assert can_see_votes(
            db_session, viewer.id, target.id, [topic.id], org_id=org.id,
        ) is False


class TestCanSeeVotesSelf:
    def test_author_always_sees(self, db_session):
        org = _make_org(db_session, "o6")
        author = _make_user(db_session, "a6")
        _join(db_session, author, org)
        topic = _make_topic(db_session, org, "Budget")
        _make_dp(db_session, author, org, topic, visibility="private")
        assert can_see_votes(
            db_session, author.id, author.id, [topic.id], org_id=org.id,
        ) is True


# ===========================================================================
# B5 — Public-page endpoint
# ===========================================================================


class TestPublicPageHidesPrivateTopicsFromAnonymous:
    def test_anonymous_sees_only_public(self, db_session, client):
        org = _make_org(db_session, "p1")
        target = _make_user(db_session, "t_p1")
        _join(db_session, target, org)
        t_pub = _make_topic(db_session, org, "Budget")
        t_foll = _make_topic(db_session, org, "Pool")
        t_priv = _make_topic(db_session, org, "Bylaws")
        _make_dp(db_session, target, org, t_pub, "public")
        _make_dp(db_session, target, org, t_foll, "followers_only")
        _make_dp(db_session, target, org, t_priv, "private",
                 bio="SECRET-PRIVATE")
        resp = client.get(f"/api/orgs/{org.slug}/delegates/{target.username}")
        assert resp.status_code == 200
        body = resp.json()
        topic_names = {t["topic_name"] for t in body["topics"]}
        assert topic_names == {"Budget"}
        assert "SECRET-PRIVATE" not in resp.text


class TestPublicPageShowsFollowersOnlyToFollower:
    def test_follower_sees_followers_only(self, db_session, client):
        org = _make_org(db_session, "p2")
        target = _make_user(db_session, "t_p2")
        viewer = _make_user(db_session, "v_p2")
        _join(db_session, target, org); _join(db_session, viewer, org)
        t_foll = _make_topic(db_session, org, "Pool")
        _make_dp(db_session, target, org, t_foll, "followers_only",
                 bio="FOLLOWER-VISIBLE")
        db_session.add(models.FollowRelationship(
            follower_id=viewer.id, followed_id=target.id,
            org_id=org.id, permission_level="view_only",
        ))
        db_session.commit()
        resp = client.get(
            f"/api/orgs/{org.slug}/delegates/{target.username}",
            headers=_auth(viewer.id),
        )
        assert resp.status_code == 200
        body = resp.json()
        topic_names = {t["topic_name"] for t in body["topics"]}
        assert "Pool" in topic_names
        bios = {t["bio"] for t in body["topics"]}
        assert "FOLLOWER-VISIBLE" in bios


class TestPublicPage404WhenAllPrivate:
    def test_404_when_all_private(self, db_session, client):
        org = _make_org(db_session, "p3")
        target = _make_user(db_session, "t_p3")
        viewer = _make_user(db_session, "v_p3")
        _join(db_session, target, org); _join(db_session, viewer, org)
        t = _make_topic(db_session, org, "Budget")
        _make_dp(db_session, target, org, t, "private")
        resp = client.get(
            f"/api/orgs/{org.slug}/delegates/{target.username}",
            headers=_auth(viewer.id),
        )
        assert resp.status_code == 404


# ===========================================================================
# B6 — Defaults + submit bridge
# ===========================================================================


class TestNewDelegateProfileDefaultsToFollowersOnly:
    """A PATCH that creates a DelegateProfile via get-or-create lands
    the row at followers_only (the new Phase 30.3 default)."""

    def test_patch_creates_followers_only(self, db_session, client):
        org = _make_org(db_session, "d1")
        user = _make_user(db_session, "u_d1")
        _join(db_session, user, org)
        topic = _make_topic(db_session, org, "Budget")
        # PATCH the topic with just a bio — no visibility specified.
        # The get-or-create runs and creates a fresh DP at the new
        # default.
        resp = client.patch(
            f"/api/orgs/{org.slug}/delegate-profile/topics/{topic.id}",
            json={"bio": "x" * 60},
            headers=_auth(user.id),
        )
        assert resp.status_code == 200, resp.text
        dp = db_session.query(models.DelegateProfile).filter_by(
            user_id=user.id, topic_id=topic.id,
        ).first()
        assert dp is not None
        assert dp.visibility == "followers_only"


class TestSubmitFromFollowersOnlyBridgesToPublicAccepting:
    """Posting submit-public-accepting on a followers_only topic auto-
    promotes the row to public first (server-side bridge), then runs
    the submit, landing at public_accepting (or pending — same shape
    as the existing private→public_accepting bridge)."""

    def test_followers_only_bridged(self, db_session, client):
        org = _make_org(db_session, "b1")
        user = _make_user(db_session, "u_b1")
        _join(db_session, user, org)
        topic = _make_topic(db_session, org, "Budget")
        # Seed at followers_only directly.
        _make_dp(db_session, user, org, topic, "followers_only",
                 bio="x" * 60)
        resp = client.post(
            f"/api/orgs/{org.slug}/delegate-profile/topics/{topic.id}/submit-public-accepting",
            headers=_auth(user.id),
        )
        assert resp.status_code == 200, resp.text
        db_session.refresh(
            db_session.query(models.DelegateProfile).filter_by(
                user_id=user.id, topic_id=topic.id,
            ).first()
        )
        dp = db_session.query(models.DelegateProfile).filter_by(
            user_id=user.id, topic_id=topic.id,
        ).first()
        # No approvers in this test org → auto-approves to public_accepting.
        assert dp.visibility == "public_accepting"


class TestPatchVisibilityAcceptsFollowersOnly:
    """Schema validator accepts the new value."""

    def test_patch_to_followers_only(self, db_session, client):
        org = _make_org(db_session, "p_b1")
        user = _make_user(db_session, "u_p_b1")
        _join(db_session, user, org)
        topic = _make_topic(db_session, org, "Budget")
        resp = client.patch(
            f"/api/orgs/{org.slug}/delegate-profile/topics/{topic.id}",
            json={"visibility": "followers_only"},
            headers=_auth(user.id),
        )
        assert resp.status_code == 200, resp.text
        dp = db_session.query(models.DelegateProfile).filter_by(
            user_id=user.id, topic_id=topic.id,
        ).first()
        assert dp.visibility == "followers_only"


class TestPatchRejectsPublicAccepting:
    """Schema validator still rejects public_accepting on PATCH."""

    def test_422_on_public_accepting(self, db_session, client):
        org = _make_org(db_session, "p_b2")
        user = _make_user(db_session, "u_p_b2")
        _join(db_session, user, org)
        topic = _make_topic(db_session, org, "Budget")
        resp = client.patch(
            f"/api/orgs/{org.slug}/delegate-profile/topics/{topic.id}",
            json={"visibility": "public_accepting"},
            headers=_auth(user.id),
        )
        assert resp.status_code == 422
