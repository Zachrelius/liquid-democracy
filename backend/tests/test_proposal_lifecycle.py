"""
Tests for proposal lifecycle (Fix 2+3).

Covers: create draft -> edit draft -> advance to deliberation ->
advance to voting -> close voting. Also tests draft editability
restrictions and org-scoped advance endpoint.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
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
        join_policy="open",
        settings={"default_voting_days": 7},
    )
    db.add(org)
    db.flush()
    return org


def _create_membership(db: Session, org, user, role="member"):
    m = models.OrgMembership(
        user_id=user.id, org_id=org.id, role=role, status="active",
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


def test_full_proposal_lifecycle(client, test_db):
    """Create draft -> advance to deliberation -> advance to voting -> close."""
    org = _create_org(test_db)
    admin = _create_user(test_db, "admin")
    _create_membership(test_db, org, admin, role="admin")
    topic = _create_topic(test_db, org)
    test_db.commit()

    headers = _auth_header(admin)

    # 1. Create proposal (starts as draft by default)
    resp = client.post(f"/api/orgs/test-org/proposals", headers=headers, json={
        "title": "Lifecycle Test",
        "body": "Testing the full lifecycle",
        "topics": [{"topic_id": topic.id, "relevance": 1.0}],
        "pass_threshold": 0.5,
        "quorum_threshold": 0.4,
    })
    assert resp.status_code == 201
    proposal = resp.json()
    pid = proposal["id"]
    assert proposal["status"] == "draft"

    # 2. Advance to deliberation
    resp = client.post(f"/api/orgs/test-org/proposals/{pid}/advance", headers=headers, json={})
    assert resp.status_code == 200
    assert resp.json()["status"] == "deliberation"

    # 3. Advance to voting
    resp = client.post(f"/api/orgs/test-org/proposals/{pid}/advance", headers=headers, json={
        "voting_end": "2030-01-01T00:00:00Z",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "voting"

    # 4. Close voting (will resolve as passed/failed based on tally)
    resp = client.post(f"/api/orgs/test-org/proposals/{pid}/advance", headers=headers, json={})
    assert resp.status_code == 200
    assert resp.json()["status"] in ("passed", "failed")


def test_draft_edit_then_advance(client, test_db):
    """Edit a draft proposal, then advance it."""
    org = _create_org(test_db)
    admin = _create_user(test_db, "admin")
    _create_membership(test_db, org, admin, role="admin")
    topic = _create_topic(test_db, org)
    test_db.commit()

    headers = _auth_header(admin)

    # Create draft
    resp = client.post(f"/api/orgs/test-org/proposals", headers=headers, json={
        "title": "Draft to Edit",
        "body": "Original body",
        "topics": [{"topic_id": topic.id, "relevance": 1.0}],
        "pass_threshold": 0.5,
        "quorum_threshold": 0.4,
    })
    pid = resp.json()["id"]

    # Edit draft via PATCH
    resp = client.patch(f"/api/proposals/{pid}", headers=headers, json={
        "title": "Updated Title",
        "body": "Updated body text",
    })
    assert resp.status_code == 200
    assert resp.json()["title"] == "Updated Title"
    assert resp.json()["body"] == "Updated body text"

    # Advance to deliberation
    resp = client.post(f"/api/orgs/test-org/proposals/{pid}/advance", headers=headers, json={})
    assert resp.status_code == 200
    assert resp.json()["status"] == "deliberation"


def test_cannot_edit_non_draft(client, test_db):
    """Editing a voting proposal should return 400."""
    org = _create_org(test_db)
    admin = _create_user(test_db, "admin")
    _create_membership(test_db, org, admin, role="admin")
    topic = _create_topic(test_db, org)
    test_db.commit()

    headers = _auth_header(admin)

    # Create and advance to deliberation, then voting
    resp = client.post(f"/api/orgs/test-org/proposals", headers=headers, json={
        "title": "No Edit",
        "body": "Body",
        "topics": [{"topic_id": topic.id, "relevance": 1.0}],
        "pass_threshold": 0.5,
        "quorum_threshold": 0.4,
    })
    pid = resp.json()["id"]
    client.post(f"/api/orgs/test-org/proposals/{pid}/advance", headers=headers, json={})
    client.post(f"/api/orgs/test-org/proposals/{pid}/advance", headers=headers, json={})

    # Try to edit — should fail (voting status)
    resp = client.patch(f"/api/proposals/{pid}", headers=headers, json={"title": "Hack"})
    assert resp.status_code == 400


def test_org_advance_cross_org_404(client, test_db):
    """Advancing a proposal from a different org should return 404."""
    org1 = _create_org(test_db)
    org2 = models.Organization(
        name="Other Org", slug="other-org", description="", join_policy="open", settings={},
    )
    test_db.add(org2)
    test_db.flush()
    admin = _create_user(test_db, "admin")
    _create_membership(test_db, org1, admin, role="admin")
    _create_membership(test_db, org2, admin, role="admin")
    topic = _create_topic(test_db, org1)
    test_db.commit()

    headers = _auth_header(admin)

    # Create proposal in org1
    resp = client.post(f"/api/orgs/test-org/proposals", headers=headers, json={
        "title": "Org1 Proposal",
        "body": "Body",
        "topics": [{"topic_id": topic.id, "relevance": 1.0}],
        "pass_threshold": 0.5,
        "quorum_threshold": 0.4,
    })
    pid = resp.json()["id"]

    # Try to advance via org2 — should be 404
    resp = client.post(f"/api/orgs/other-org/proposals/{pid}/advance", headers=headers, json={})
    assert resp.status_code == 404


def test_moderator_advance_own_proposal(client, test_db):
    """Moderator can advance their own proposal via org-scoped endpoint."""
    org = _create_org(test_db)
    mod = _create_user(test_db, "mod")
    _create_membership(test_db, org, mod, role="moderator")
    topic = _create_topic(test_db, org)
    test_db.commit()

    headers = _auth_header(mod)

    resp = client.post(f"/api/orgs/test-org/proposals", headers=headers, json={
        "title": "Mod Proposal",
        "body": "Body",
        "topics": [{"topic_id": topic.id, "relevance": 1.0}],
        "pass_threshold": 0.5,
        "quorum_threshold": 0.4,
    })
    pid = resp.json()["id"]

    resp = client.post(f"/api/orgs/test-org/proposals/{pid}/advance", headers=headers, json={})
    assert resp.status_code == 200
    assert resp.json()["status"] == "deliberation"


def test_moderator_cannot_advance_others_proposal(client, test_db):
    """Moderator cannot advance another user's proposal."""
    org = _create_org(test_db)
    admin = _create_user(test_db, "admin")
    _create_membership(test_db, org, admin, role="admin")
    mod = _create_user(test_db, "mod")
    _create_membership(test_db, org, mod, role="moderator")
    topic = _create_topic(test_db, org)
    test_db.commit()

    # Admin creates proposal
    resp = client.post(f"/api/orgs/test-org/proposals", headers=_auth_header(admin), json={
        "title": "Admin Proposal",
        "body": "Body",
        "topics": [{"topic_id": topic.id, "relevance": 1.0}],
        "pass_threshold": 0.5,
        "quorum_threshold": 0.4,
    })
    pid = resp.json()["id"]

    # Moderator tries to advance — should fail
    resp = client.post(
        f"/api/orgs/test-org/proposals/{pid}/advance",
        headers=_auth_header(mod),
        json={},
    )
    assert resp.status_code == 403
    assert "Moderators can only advance" in resp.json()["detail"]
