"""Phase 30.2 — public delegate page bio + position_statement render tests.

The Phase 30.2 B1 fix swapped the frontend ``DelegatePublic.jsx`` from
walking the browse list (which ships only ``{topic_id, name,
visibility}``) to calling the dedicated
``GET /api/orgs/{slug}/delegates/{handle_or_username}`` endpoint (which
already returned per-topic bio + position_statement since Phase 19).

These tests pin the endpoint's response shape so a future change can't
quietly drop the fields the frontend now relies on, plus exercise the
privacy guard that private topics are filtered out of the response.
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
from role_seed import seed_default_roles_for_org


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


def _seed_delegate(
    db: Session,
    slug: str,
    delegate_username: str,
    visibility: str = "public_accepting",
    bio: str = "x" * 60,
    position_statement: str | None = None,
    topic_name: str = "Budget",
):
    """Build org + delegate user + per-topic DelegateProfile with bio
    + (optionally) position_statement. The OrgDelegateProfile must be
    public-derivable so the public page is reachable — that requires
    at least one non-private topic, which our default visibility
    (public_accepting) provides."""
    org = models.Organization(
        slug=slug, name=slug.title(),
        description="", join_policy="open",
    )
    db.add(org); db.flush()
    seed_default_roles_for_org(db, org.id)
    member_role = db.query(models.Role).filter_by(
        org_id=org.id, system_key="member",
    ).first()

    delegate = models.User(
        username=delegate_username, display_name=delegate_username.title(),
        password_hash=hash_password("x"),
        email=f"{delegate_username}@test.example", email_verified=True,
    )
    db.add(delegate); db.flush()
    db.add(models.OrgMembership(
        user_id=delegate.id, org_id=org.id, role_id=member_role.id, status="active",
    ))

    topic = models.Topic(
        name=topic_name,
        color="#000000", org_id=org.id,
    )
    db.add(topic); db.flush()

    # Parent OrgDelegateProfile required for the public page to be
    # reachable. Phase 30.3 dropped page_visibility; visibility lives
    # entirely on per-topic DelegateProfile.visibility.
    odp = models.OrgDelegateProfile(
        user_id=delegate.id, org_id=org.id,
        intro="An intro.",
    )
    db.add(odp)

    dp = models.DelegateProfile(
        user_id=delegate.id, org_id=org.id, topic_id=topic.id,
        bio=bio, position_statement=position_statement,
        visibility=visibility,
    )
    db.add(dp); db.commit()
    return org, delegate, topic, dp


def _seed_viewer(db: Session, org: models.Organization, username: str) -> models.User:
    """A second user in the same org so we can test non-author view."""
    member_role = db.query(models.Role).filter_by(
        org_id=org.id, system_key="member",
    ).first()
    viewer = models.User(
        username=username, display_name=username.title(),
        password_hash=hash_password("x"),
        email=f"{username}@test.example", email_verified=True,
    )
    db.add(viewer); db.flush()
    db.add(models.OrgMembership(
        user_id=viewer.id, org_id=org.id, role_id=member_role.id, status="active",
    ))
    db.commit()
    return viewer


# ===========================================================================
# B3 tests
# ===========================================================================


class TestPublicDelegatePageIncludesBio:
    """Non-author GET returns the per-topic bio field."""

    def test_bio_in_response(self, db_session, client):
        org, delegate, _, _ = _seed_delegate(
            db_session, "o1", "alice",
            bio="I read every line of the budget.",
        )
        viewer = _seed_viewer(db_session, org, "bob")
        resp = client.get(
            f"/api/orgs/{org.slug}/delegates/alice",
            headers=_auth(viewer.id),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["topics"], "expected at least one topic in response"
        t = body["topics"][0]
        assert t["bio"] == "I read every line of the budget."


class TestPublicDelegatePageIncludesPositionStatement:
    """Non-author GET returns the per-topic position_statement field."""

    def test_position_in_response(self, db_session, client):
        org, _, _, _ = _seed_delegate(
            db_session, "o2", "alice",
            position_statement="Reserve discipline matters more than amenities.",
        )
        viewer = _seed_viewer(db_session, org, "bob")
        resp = client.get(
            f"/api/orgs/{org.slug}/delegates/alice",
            headers=_auth(viewer.id),
        )
        assert resp.status_code == 200
        body = resp.json()
        t = body["topics"][0]
        assert t["position_statement"] == "Reserve discipline matters more than amenities."


class TestPublicDelegatePageOmitsPrivateTopicData:
    """A topic at visibility=private is filtered out of the response;
    its bio doesn't leak under any key."""

    def test_private_topic_filtered(self, db_session, client):
        # Seed with a public_accepting topic so the page is reachable.
        org, delegate, _, _ = _seed_delegate(
            db_session, "o3", "alice",
            bio="Public bio shows.",
            position_statement="Public position shows.",
        )
        # Add a SECOND topic at visibility=private with sensitive text.
        private_topic = models.Topic(
            name="Bylaws",
            color="#000000", org_id=org.id,
        )
        db_session.add(private_topic); db_session.flush()
        private_dp = models.DelegateProfile(
            user_id=delegate.id, org_id=org.id, topic_id=private_topic.id,
            bio="SENSITIVE-PRIVATE-BIO",
            position_statement="SENSITIVE-PRIVATE-POSITION",
            visibility="private",
        )
        db_session.add(private_dp); db_session.commit()

        viewer = _seed_viewer(db_session, org, "bob")
        resp = client.get(
            f"/api/orgs/{org.slug}/delegates/alice",
            headers=_auth(viewer.id),
        )
        assert resp.status_code == 200
        body = resp.json()
        topic_names = {t["topic_name"] for t in body["topics"]}
        # Private topic is filtered out entirely.
        assert "Bylaws" not in topic_names
        assert "Budget" in topic_names
        # Sensitive bio doesn't leak anywhere in the response body.
        as_text = resp.text
        assert "SENSITIVE-PRIVATE-BIO" not in as_text
        assert "SENSITIVE-PRIVATE-POSITION" not in as_text


class TestPublicDelegatePageAuthorSeesEverything:
    """Author viewing their own public page sees all non-private topics
    with full bio + position content (matches what non-authors see —
    the public surface doesn't restrict for the author, but also
    doesn't include private topics for them either; for that the
    author uses the /delegate-profile edit view)."""

    def test_author_view_matches_non_author(self, db_session, client):
        org, delegate, _, _ = _seed_delegate(
            db_session, "o4", "alice",
            bio="Author bio.",
            position_statement="Author position.",
        )
        viewer = _seed_viewer(db_session, org, "bob")

        author_resp = client.get(
            f"/api/orgs/{org.slug}/delegates/alice",
            headers=_auth(delegate.id),
        )
        viewer_resp = client.get(
            f"/api/orgs/{org.slug}/delegates/alice",
            headers=_auth(viewer.id),
        )
        assert author_resp.status_code == 200
        assert viewer_resp.status_code == 200
        # Same topic shape for both viewers — author isn't restricted
        # below the non-author view.
        author_topics = author_resp.json()["topics"]
        viewer_topics = viewer_resp.json()["topics"]
        assert len(author_topics) == len(viewer_topics) == 1
        assert author_topics[0]["bio"] == "Author bio."
        assert author_topics[0]["bio"] == viewer_topics[0]["bio"]
        assert author_topics[0]["position_statement"] == "Author position."
