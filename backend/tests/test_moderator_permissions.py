"""
Tests for moderator permissions (Fix 5).

Covers the full permission matrix: what moderators CAN and CANNOT do
compared to admins, including endpoint-level authorization.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from database import Base, get_db
import models
import auth as auth_utils
from main import app


_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


@pytest.fixture(scope="function")
def test_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def client(test_db):
    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _create_user(db: Session, username: str) -> models.User:
    u = models.User(
        username=username,
        display_name=username.title(),
        password_hash=_DUMMY_HASH,
        email=f"{username}@test.example",
        email_verified=True,
    )
    db.add(u)
    db.flush()
    return u


def _create_org(db: Session) -> models.Organization:
    org = models.Organization(
        name="Test Org",
        slug="test-org",
        description="",
        join_policy="approval_required",
        settings={"default_voting_days": 7},
    )
    db.add(org)
    db.flush()
    return org


def _create_membership(db: Session, org, user, role="member", status="active"):
    m = models.OrgMembership(
        user_id=user.id,
        org_id=org.id,
        role=role,
        status=status,
    )
    db.add(m)
    db.flush()
    return m


def _create_topic(db: Session, org) -> models.Topic:
    t = models.Topic(name="Environment", description="", color="#00ff00", org_id=org.id)
    db.add(t)
    db.flush()
    return t


def _auth_header(user: models.User) -> dict:
    token = auth_utils.create_access_token(user.id)
    return {"Authorization": f"Bearer {token}"}


# ---- Moderator CAN do ----

def test_moderator_can_approve_join_request(client, test_db):
    org = _create_org(test_db)
    moderator = _create_user(test_db, "mod")
    _create_membership(test_db, org, moderator, role="moderator")
    applicant = _create_user(test_db, "applicant")
    _create_membership(test_db, org, applicant, role="member", status="pending_approval")
    test_db.commit()

    resp = client.post(
        f"/api/orgs/test-org/join/approve/{applicant.id}",
        headers=_auth_header(moderator),
    )
    assert resp.status_code == 200


def test_moderator_can_suspend_member(client, test_db):
    org = _create_org(test_db)
    moderator = _create_user(test_db, "mod")
    _create_membership(test_db, org, moderator, role="moderator")
    target = _create_user(test_db, "target")
    _create_membership(test_db, org, target, role="member")
    test_db.commit()

    resp = client.post(
        f"/api/orgs/test-org/members/{target.id}/suspend",
        headers=_auth_header(moderator),
    )
    assert resp.status_code == 200


def test_moderator_can_edit_topic(client, test_db):
    org = _create_org(test_db)
    moderator = _create_user(test_db, "mod")
    _create_membership(test_db, org, moderator, role="moderator")
    topic = _create_topic(test_db, org)
    test_db.commit()

    resp = client.patch(
        f"/api/orgs/test-org/topics/{topic.id}",
        headers=_auth_header(moderator),
        json={"name": "Climate", "description": "Updated", "color": "#0000ff"},
    )
    assert resp.status_code == 200


def test_moderator_can_create_proposal(client, test_db):
    org = _create_org(test_db)
    moderator = _create_user(test_db, "mod")
    _create_membership(test_db, org, moderator, role="moderator")
    topic = _create_topic(test_db, org)
    test_db.commit()

    resp = client.post(
        f"/api/orgs/test-org/proposals",
        headers=_auth_header(moderator),
        json={
            "title": "Mod Proposal",
            "body": "A proposal by moderator",
            "topics": [{"topic_id": topic.id, "relevance": 1.0}],
            "pass_threshold": 0.5,
            "quorum_threshold": 0.4,
        },
    )
    assert resp.status_code == 201


# ---- Moderator CANNOT do ----

def test_moderator_cannot_remove_member(client, test_db):
    org = _create_org(test_db)
    moderator = _create_user(test_db, "mod")
    _create_membership(test_db, org, moderator, role="moderator")
    target = _create_user(test_db, "target")
    _create_membership(test_db, org, target, role="member")
    test_db.commit()

    resp = client.delete(
        f"/api/orgs/test-org/members/{target.id}",
        headers=_auth_header(moderator),
    )
    assert resp.status_code == 403


def test_moderator_cannot_delete_topic(client, test_db):
    org = _create_org(test_db)
    moderator = _create_user(test_db, "mod")
    _create_membership(test_db, org, moderator, role="moderator")
    topic = _create_topic(test_db, org)
    test_db.commit()

    resp = client.delete(
        f"/api/orgs/test-org/topics/{topic.id}",
        headers=_auth_header(moderator),
    )
    assert resp.status_code == 403


def test_moderator_cannot_change_member_role(client, test_db):
    org = _create_org(test_db)
    moderator = _create_user(test_db, "mod")
    _create_membership(test_db, org, moderator, role="moderator")
    target = _create_user(test_db, "target")
    _create_membership(test_db, org, target, role="member")
    test_db.commit()

    resp = client.patch(
        f"/api/orgs/test-org/members/{target.id}",
        headers=_auth_header(moderator),
        json={"role": "admin"},
    )
    assert resp.status_code == 403


def test_moderator_cannot_update_org_settings(client, test_db):
    org = _create_org(test_db)
    moderator = _create_user(test_db, "mod")
    _create_membership(test_db, org, moderator, role="moderator")
    test_db.commit()

    resp = client.patch(
        f"/api/orgs/test-org",
        headers=_auth_header(moderator),
        json={"settings": {"default_voting_days": 14}},
    )
    assert resp.status_code == 403


# ---- Regular member CANNOT do moderator actions ----

def test_regular_member_cannot_suspend(client, test_db):
    org = _create_org(test_db)
    member = _create_user(test_db, "member")
    _create_membership(test_db, org, member, role="member")
    target = _create_user(test_db, "target")
    _create_membership(test_db, org, target, role="member")
    test_db.commit()

    resp = client.post(
        f"/api/orgs/test-org/members/{target.id}/suspend",
        headers=_auth_header(member),
    )
    assert resp.status_code == 403


def test_regular_member_cannot_create_proposal(client, test_db):
    org = _create_org(test_db)
    member = _create_user(test_db, "member")
    _create_membership(test_db, org, member, role="member")
    topic = _create_topic(test_db, org)
    test_db.commit()

    resp = client.post(
        f"/api/orgs/test-org/proposals",
        headers=_auth_header(member),
        json={
            "title": "Proposal",
            "body": "Body",
            "topics": [{"topic_id": topic.id, "relevance": 1.0}],
            "pass_threshold": 0.5,
            "quorum_threshold": 0.4,
        },
    )
    assert resp.status_code == 403
