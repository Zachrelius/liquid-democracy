"""Phase 12 Stage 1 — Cluster R4 tests.

Positive/negative coverage of the production-code role-check rewrites
(see ``docs/phase12_role_check_audit.md``):

* MAPS_TO_KEY rewrites in ``routes/organizations.py``
  (``create_org_topic``, ``create_org_proposal``).
* OWNER_ONLY_D4 enforcement at the HTTP layer
  (``DELETE /api/orgs/{slug}`` requires Steward).
* Rename verification: ``role.name`` is "Steward" (not "Owner") and
  ``role.system_key`` is "steward". API responses surface the new
  ``system_key`` in payload.
* Decision-6 implicit power surfaced through the route layer
  (cross-parent isolation already covered in
  ``test_role_permissions.py``; this file asserts the route honors it).

The ``test_role_permissions.py`` file (Cluster H) covers the
``has_permission`` helper directly. This file covers the rewritten call
sites that consume the helper.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from database import Base, get_db
from main import app
from role_seed import seed_default_roles_for_org
from tests.conftest import make_org_membership


_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


def _make_user(db: Session, username: str) -> models.User:
    u = models.User(
        username=username,
        display_name=username,
        password_hash=_DUMMY_HASH,
        email=f"{username}@test.example",
        email_verified=True,
    )
    db.add(u)
    db.flush()
    return u


def _make_org(
    db: Session, slug: str = "alpha", *, parent_id: str | None = None,
) -> models.Organization:
    o = models.Organization(
        name=slug.title(), slug=slug, description="",
        parent_org_id=parent_id, settings={},
    )
    db.add(o)
    db.flush()
    return o


def _auth(user: models.User) -> dict:
    token = auth_utils.create_access_token(user.id)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Rename verification (R4 — "Steward" + system_key="steward" everywhere)
# ---------------------------------------------------------------------------


def test_seeded_role_rows_carry_steward_name_not_owner(test_db):
    """The 'owner' role is renamed to 'Steward' on seed; system_key is
    'steward'. No row carries the literal 'owner' system_key."""
    org = _make_org(test_db, "renamed")
    roles = seed_default_roles_for_org(test_db, org.id)

    steward = roles["steward"]
    assert steward.name == "Steward"
    assert steward.system_key == "steward"

    all_keys = {r.system_key for r in test_db.query(models.Role).all()}
    assert "owner" not in all_keys
    assert {"steward", "admin", "moderator", "member"} == all_keys


def test_org_creation_response_user_role_is_steward(client, test_db):
    """``POST /api/orgs`` — the creator's user_role payload field is
    'steward' (not the legacy 'owner')."""
    creator = _make_user(test_db, "alice")
    test_db.commit()

    resp = client.post(
        "/api/orgs",
        json={
            "name": "Renamed",
            "slug": "renamed",
            "description": "",
            "join_policy": "approval_required",
        },
        headers={**_auth(creator), "User-Agent": "pytest-ua/1.0"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["user_role"] == "steward"


def test_list_members_payload_role_is_system_key(client, test_db):
    """``GET /api/orgs/{slug}/members`` returns role.system_key for every
    member (not the dropped string column or the Role display name)."""
    creator = _make_user(test_db, "creator")
    other = _make_user(test_db, "other")
    org = _make_org(test_db, "members-test")
    seed_default_roles_for_org(test_db, org.id)
    make_org_membership(test_db, org_id=org.id, user_id=creator.id, role="steward")
    make_org_membership(test_db, org_id=org.id, user_id=other.id, role="moderator")
    test_db.commit()

    resp = client.get(f"/api/orgs/{org.slug}/members", headers=_auth(creator))
    assert resp.status_code == 200, resp.text
    by_user = {m["user_id"]: m for m in resp.json()}
    assert by_user[creator.id]["role"] == "steward"
    assert by_user[other.id]["role"] == "moderator"


# ---------------------------------------------------------------------------
# OWNER_ONLY_D4 — DELETE /api/orgs/{slug}
# ---------------------------------------------------------------------------


def test_delete_org_requires_steward_admin_gets_403(client, test_db):
    """Phase 12 D4 — DELETE /api/orgs/{slug} requires Steward; an Admin
    in the same org gets 403 even though Admin has all 23 grant defaults."""
    steward_user = _make_user(test_db, "steward_user")
    admin_user = _make_user(test_db, "admin_user")
    org = _make_org(test_db, "delete-test")
    make_org_membership(test_db, org_id=org.id, user_id=steward_user.id, role="steward")
    make_org_membership(test_db, org_id=org.id, user_id=admin_user.id, role="admin")
    test_db.commit()

    resp_admin = client.delete(
        f"/api/orgs/{org.slug}", headers=_auth(admin_user),
    )
    assert resp_admin.status_code == 403


def test_delete_org_steward_succeeds(client, test_db):
    """Steward CAN delete the org (sanity counterpart to the 403 test)."""
    steward_user = _make_user(test_db, "steward_user")
    org = _make_org(test_db, "delete-ok")
    make_org_membership(test_db, org_id=org.id, user_id=steward_user.id, role="steward")
    test_db.commit()

    resp = client.delete(
        f"/api/orgs/{org.slug}", headers=_auth(steward_user),
    )
    # Endpoint may return 200 or 204; either confirms the gate let it through.
    assert resp.status_code in (200, 204)


# ---------------------------------------------------------------------------
# MAPS_TO_KEY — create_org_topic via 'topic.create'
# ---------------------------------------------------------------------------


def test_create_org_topic_admin_succeeds(client, test_db):
    """Admin (default grant of 'topic.create') creates an org-wide topic."""
    user = _make_user(test_db, "topic_admin")
    org = _make_org(test_db, "topic-admin")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="admin")
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/topics",
        json={
            "name": "Environment", "description": "", "color": "#00ff00",
        },
        headers=_auth(user),
    )
    assert resp.status_code == 201, resp.text


def test_create_org_topic_member_gets_403(client, test_db):
    """Member (no 'topic.create' default grant) is denied."""
    user = _make_user(test_db, "topic_member")
    org = _make_org(test_db, "topic-member")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="member")
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/topics",
        json={
            "name": "Environment", "description": "", "color": "#00ff00",
        },
        headers=_auth(user),
    )
    assert resp.status_code == 403
    # Error copy is role-agnostic per spec.
    assert "permission" in resp.json()["detail"].lower()
    assert "admin" not in resp.json()["detail"].lower()


def test_create_org_topic_moderator_succeeds_via_default_grant(client, test_db):
    """Moderator's 8-key default set INCLUDES 'topic.create'; succeeds."""
    user = _make_user(test_db, "topic_mod")
    org = _make_org(test_db, "topic-mod")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="moderator")
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/topics",
        json={
            "name": "Environment", "description": "", "color": "#00ff00",
        },
        headers=_auth(user),
    )
    assert resp.status_code == 201, resp.text


# ---------------------------------------------------------------------------
# MAPS_TO_KEY — create_org_proposal via 'proposal.create'
# ---------------------------------------------------------------------------


def _seed_topic(db: Session, org: models.Organization) -> models.Topic:
    t = models.Topic(name="T", description="", color="#000000", org_id=org.id)
    db.add(t)
    db.flush()
    return t


def test_create_org_proposal_member_gets_403(client, test_db):
    """Member (no 'proposal.create' default grant) is denied."""
    user = _make_user(test_db, "prop_member")
    org = _make_org(test_db, "prop-member")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="member")
    topic = _seed_topic(test_db, org)
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/proposals",
        json={
            "title": "P", "body": "B", "topics": [{"topic_id": topic.id}],
            "voting_method": "binary",
        },
        headers=_auth(user),
    )
    assert resp.status_code == 403
    # Role-agnostic copy.
    assert "permission" in resp.json()["detail"].lower()


def test_create_org_proposal_admin_succeeds(client, test_db):
    """Admin (default grant of 'proposal.create') creates a proposal."""
    user = _make_user(test_db, "prop_admin")
    org = _make_org(test_db, "prop-admin")
    make_org_membership(test_db, org_id=org.id, user_id=user.id, role="admin")
    topic = _seed_topic(test_db, org)
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/proposals",
        json={
            "title": "P", "body": "B", "topics": [{"topic_id": topic.id}],
            "voting_method": "binary",
        },
        headers=_auth(user),
    )
    assert resp.status_code == 201, resp.text


# ---------------------------------------------------------------------------
# Decision-6 — parent-org Steward implicit power surfaced through route
# ---------------------------------------------------------------------------


def test_parent_steward_can_create_sub_org_topic_via_implicit_power(
    client, test_db,
):
    """Decision 6 — a parent-org Steward without sub-org membership can
    create a sub-org-scoped topic via implicit-admin power.
    """
    steward = _make_user(test_db, "steward_implicit")
    parent = _make_org(test_db, "parent-implicit")
    sub_org = _make_org(test_db, "child-implicit", parent_id=parent.id)
    make_org_membership(
        test_db, org_id=parent.id, user_id=steward.id, role="steward",
    )
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{parent.slug}/topics",
        json={
            "name": "Sub-Topic", "description": "", "color": "#00ff00",
            "sub_org_id": sub_org.id,
        },
        headers=_auth(steward),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body.get("sub_org_id") == sub_org.id


def test_unrelated_parent_steward_cannot_act_on_other_parents_sub_org(
    client, test_db,
):
    """Decision 6 cross-parent isolation surfaced through the route layer:
    a Steward of Parent A cannot create topics in Parent B's sub-org."""
    steward_a = _make_user(test_db, "steward_a")
    parent_a = _make_org(test_db, "parent-a")
    parent_b = _make_org(test_db, "parent-b")
    sub_b = _make_org(test_db, "child-b", parent_id=parent_b.id)
    make_org_membership(
        test_db, org_id=parent_a.id, user_id=steward_a.id, role="steward",
    )
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{parent_b.slug}/topics",
        json={
            "name": "Other-Sub", "description": "", "color": "#00ff00",
            "sub_org_id": sub_b.id,
        },
        headers=_auth(steward_a),
    )
    # Either 403 (membership fail, no access to /api/orgs/parent-b/...) or
    # the deeper sub-org-admin gate. Both are correct cross-parent isolation.
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# OWNER_ONLY_D4 — change_member_role / remove / suspend protections
# ---------------------------------------------------------------------------


def test_cannot_change_steward_role(client, test_db):
    """Phase 12 — the Steward role is protected from in-place demotion via
    the change-role endpoint (renamed-from-'owner' guard)."""
    steward = _make_user(test_db, "steward_protected")
    other = _make_user(test_db, "other_steward")
    org = _make_org(test_db, "guard-steward")
    make_org_membership(test_db, org_id=org.id, user_id=steward.id, role="steward")
    make_org_membership(test_db, org_id=org.id, user_id=other.id, role="steward")
    test_db.commit()

    resp = client.patch(
        f"/api/orgs/{org.slug}/members/{other.id}",
        json={"role": "member"},
        headers=_auth(steward),
    )
    assert resp.status_code == 400
    assert "Steward" in resp.json()["detail"]


def test_cannot_remove_steward_member(client, test_db):
    """Phase 12 — the Steward cannot be removed via the member-remove
    endpoint (renamed-from-'owner' guard)."""
    steward = _make_user(test_db, "steward_keep")
    other = _make_user(test_db, "other_keep")
    org = _make_org(test_db, "guard-remove")
    make_org_membership(test_db, org_id=org.id, user_id=steward.id, role="steward")
    make_org_membership(test_db, org_id=org.id, user_id=other.id, role="steward")
    test_db.commit()

    resp = client.delete(
        f"/api/orgs/{org.slug}/members/{other.id}",
        headers=_auth(steward),
    )
    assert resp.status_code == 400
    assert "Steward" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# DOESNT_MAP_FLAG: moderators-can-only-advance-own-proposals
# ---------------------------------------------------------------------------


def test_moderator_cannot_advance_others_proposal(client, test_db):
    """Stage-1 preserved tier rule: moderators only advance their OWN
    proposals (admin/Steward have no such restriction). Documented as
    DOESNT_MAP_FLAG in the audit doc."""
    mod = _make_user(test_db, "mod_advance")
    author = _make_user(test_db, "author")
    org = _make_org(test_db, "mod-advance")
    make_org_membership(test_db, org_id=org.id, user_id=mod.id, role="moderator")
    make_org_membership(test_db, org_id=org.id, user_id=author.id, role="admin")
    topic = _seed_topic(test_db, org)
    proposal = models.Proposal(
        title="Other's", body="", author_id=author.id, org_id=org.id,
        status="draft", voting_method="binary",
    )
    test_db.add(proposal)
    test_db.flush()
    test_db.add(models.ProposalTopic(proposal_id=proposal.id, topic_id=topic.id))
    test_db.commit()

    resp = client.post(
        f"/api/orgs/{org.slug}/proposals/{proposal.id}/advance",
        json={},
        headers=_auth(mod),
    )
    assert resp.status_code == 403
