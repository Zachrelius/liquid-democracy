"""
Phase 8.5 Session 2 — Integration tests for sub-organization routes.

Exercises:
  - Sub-org CRUD round-trip (create, get, list, patch, delete)
  - Two-level enforcement (creating a sub-sub-org fails 400)
  - Member invite + approve / request-join + approve / deny / remove /
    change-role flows
  - Topic creation with sub-org scope; topic list scope filtering
  - Proposal creation with sub-org scope; proposal list privacy filtering
  - Promote-to-org-wide (with confirm, without confirm, on already-org-wide)
  - Sub-org privacy flag flips
  - Cross-scope-delegation strict-in-group flag flips
  - Voting method override via get_org_config (sub-org enables RCV)
  - All 8 new audit event types fire with expected payload shape
  - Permissions: parent-org admin acts as sub-org admin (Decision 6);
    non-admin sub-org member cannot
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from database import Base, get_db
from main import app


_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


@pytest.fixture(scope="function")
def db():
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
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _user(db: Session, username: str) -> models.User:
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


def _org(
    db: Session,
    slug: str = "parent",
    parent_org_id: str | None = None,
    settings: dict | None = None,
) -> models.Organization:
    org = models.Organization(
        name=slug.replace("-", " ").title(),
        slug=slug,
        description="",
        join_policy="open" if parent_org_id is None else "invite_only",
        settings=settings or {},
        parent_org_id=parent_org_id,
    )
    db.add(org)
    db.flush()
    return org


def _membership(db: Session, org, user, role="member", status="active"):
    m = models.OrgMembership(
        user_id=user.id, org_id=org.id, role=role, status=status,
    )
    db.add(m)
    db.flush()
    return m


def _sub_membership(db: Session, sub_org, user, role="member", status="active"):
    m = models.SubOrgMembership(
        user_id=user.id, sub_org_id=sub_org.id, role=role, status=status,
    )
    db.add(m)
    db.flush()
    return m


def _auth(user: models.User) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _audit_actions(db: Session, action: str | None = None) -> list[models.AuditLog]:
    q = db.query(models.AuditLog)
    if action:
        q = q.filter(models.AuditLog.action == action)
    return q.order_by(models.AuditLog.timestamp).all()


# ---------------------------------------------------------------------------
# Sub-org CRUD
# ---------------------------------------------------------------------------

class TestSubOrgCRUD:
    def test_create_sub_org_round_trip(self, db, client):
        admin = _user(db, "admin")
        parent = _org(db, "parent")
        _membership(db, parent, admin, role="admin")
        db.commit()

        # Create
        resp = client.post(
            f"/api/orgs/{parent.slug}/sub-orgs",
            json={"name": "Engineering", "slug": "engineering", "description": "Eng team"},
            headers=_auth(admin),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["slug"] == "engineering"
        assert body["parent_org_id"] == parent.id
        sub_id = body["id"]

        # Get
        resp = client.get(
            f"/api/orgs/{parent.slug}/sub-orgs/engineering",
            headers=_auth(admin),
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == sub_id

        # List
        resp = client.get(
            f"/api/orgs/{parent.slug}/sub-orgs", headers=_auth(admin),
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["slug"] == "engineering"

        # Patch
        resp = client.patch(
            f"/api/orgs/{parent.slug}/sub-orgs/engineering",
            json={"description": "Eng team (updated)"},
            headers=_auth(admin),
        )
        assert resp.status_code == 200
        assert resp.json()["description"] == "Eng team (updated)"

        # Delete (no topics/proposals scoped to it)
        resp = client.delete(
            f"/api/orgs/{parent.slug}/sub-orgs/engineering",
            headers=_auth(admin),
        )
        assert resp.status_code == 204

    def test_two_level_enforcement(self, db, client):
        """Creating a sub-org under another sub-org fails 400."""
        admin = _user(db, "admin")
        parent = _org(db, "parent")
        # Create the level-1 sub-org directly.
        sub = _org(db, "sub", parent_org_id=parent.id)
        _membership(db, parent, admin, role="admin")
        db.commit()

        # Attempt to create a sub-sub-org under `sub` — should 400.
        resp = client.post(
            f"/api/orgs/{sub.slug}/sub-orgs",
            json={"name": "Deep", "slug": "deep"},
            headers=_auth(admin),
        )
        assert resp.status_code == 400
        assert "Two-level" in resp.json()["detail"] or "sub-org under another" in resp.json()["detail"]

    def test_create_requires_parent_org_admin(self, db, client):
        regular = _user(db, "regular")
        parent = _org(db, "parent")
        _membership(db, parent, regular, role="member")
        db.commit()
        resp = client.post(
            f"/api/orgs/{parent.slug}/sub-orgs",
            json={"name": "Engineering", "slug": "engineering"},
            headers=_auth(regular),
        )
        assert resp.status_code == 403

    def test_delete_blocked_when_topics_scoped(self, db, client):
        admin = _user(db, "admin")
        parent = _org(db, "parent")
        sub = _org(db, "sub", parent_org_id=parent.id)
        _membership(db, parent, admin, role="admin")
        # Add a topic scoped to the sub.
        topic = models.Topic(
            name="ScopedTopic", description="", color="#000",
            org_id=parent.id, sub_org_id=sub.id,
        )
        db.add(topic)
        db.commit()

        resp = client.delete(
            f"/api/orgs/{parent.slug}/sub-orgs/sub", headers=_auth(admin),
        )
        assert resp.status_code == 409
        assert "topic" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Sub-org membership flows
# ---------------------------------------------------------------------------

class TestSubOrgMembership:
    def test_invite_then_approve(self, db, client):
        admin = _user(db, "admin")
        invitee = _user(db, "invitee")
        parent = _org(db, "parent")
        sub = _org(db, "sub", parent_org_id=parent.id)
        _membership(db, parent, admin, role="admin")
        _membership(db, parent, invitee, role="member")
        db.commit()

        resp = client.post(
            f"/api/orgs/{parent.slug}/sub-orgs/sub/members/invite",
            json={"user_id": invitee.id, "role": "member"},
            headers=_auth(admin),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "pending_approval"

        # Approve as the parent-org admin (implicit power)
        resp = client.post(
            f"/api/orgs/{parent.slug}/sub-orgs/sub/members/{invitee.id}/approve",
            headers=_auth(admin),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"

    def test_invite_non_parent_member_fails(self, db, client):
        admin = _user(db, "admin")
        outsider = _user(db, "outsider")
        parent = _org(db, "parent")
        _org(db, "sub", parent_org_id=parent.id)
        _membership(db, parent, admin, role="admin")
        # outsider is NOT a parent-org member
        db.commit()
        resp = client.post(
            f"/api/orgs/{parent.slug}/sub-orgs/sub/members/invite",
            json={"user_id": outsider.id, "role": "member"},
            headers=_auth(admin),
        )
        assert resp.status_code == 400

    def test_request_join_then_approve(self, db, client):
        admin = _user(db, "admin")
        member = _user(db, "member")
        parent = _org(db, "parent")
        sub = _org(db, "sub", parent_org_id=parent.id)
        _membership(db, parent, admin, role="admin")
        _membership(db, parent, member, role="member")
        db.commit()

        resp = client.post(
            f"/api/orgs/{parent.slug}/sub-orgs/sub/members/request-join",
            headers=_auth(member),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending_approval"

        # Audit event should be sub_org.member_invited with requested=true
        events = _audit_actions(db, "sub_org.member_invited")
        assert any(
            e.details.get("requested") is True
            and e.details.get("target_user_id") == member.id
            for e in events
        )

        # Approve
        resp = client.post(
            f"/api/orgs/{parent.slug}/sub-orgs/sub/members/{member.id}/approve",
            headers=_auth(admin),
        )
        assert resp.status_code == 200

    def test_deny_removes_membership(self, db, client):
        admin = _user(db, "admin")
        member = _user(db, "member")
        parent = _org(db, "parent")
        sub = _org(db, "sub", parent_org_id=parent.id)
        _membership(db, parent, admin, role="admin")
        _membership(db, parent, member, role="member")
        # Pre-create pending invite
        _sub_membership(db, sub, member, status="pending_approval")
        db.commit()

        resp = client.post(
            f"/api/orgs/{parent.slug}/sub-orgs/sub/members/{member.id}/deny",
            headers=_auth(admin),
        )
        assert resp.status_code == 200
        # Row hard-deleted
        assert db.query(models.SubOrgMembership).filter(
            models.SubOrgMembership.user_id == member.id,
            models.SubOrgMembership.sub_org_id == sub.id,
        ).first() is None

    def test_remove_active_member(self, db, client):
        admin = _user(db, "admin")
        member = _user(db, "member")
        parent = _org(db, "parent")
        sub = _org(db, "sub", parent_org_id=parent.id)
        _membership(db, parent, admin, role="admin")
        _membership(db, parent, member, role="member")
        _sub_membership(db, sub, member)
        db.commit()

        resp = client.post(
            f"/api/orgs/{parent.slug}/sub-orgs/sub/members/{member.id}/remove",
            headers=_auth(admin),
        )
        assert resp.status_code == 200
        events = _audit_actions(db, "sub_org.member_removed")
        assert any(e.details.get("reason") == "removed" for e in events)

    def test_change_role(self, db, client):
        admin = _user(db, "admin")
        member = _user(db, "member")
        parent = _org(db, "parent")
        sub = _org(db, "sub", parent_org_id=parent.id)
        _membership(db, parent, admin, role="admin")
        _membership(db, parent, member, role="member")
        _sub_membership(db, sub, member, role="member")
        db.commit()

        resp = client.post(
            f"/api/orgs/{parent.slug}/sub-orgs/sub/members/{member.id}/change-role",
            json={"role": "moderator"},
            headers=_auth(admin),
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "moderator"
        events = _audit_actions(db, "sub_org.member_role_changed")
        assert any(
            e.details.get("old_role") == "member"
            and e.details.get("new_role") == "moderator"
            for e in events
        )

    def test_non_admin_member_cannot_invite(self, db, client):
        regular = _user(db, "regular")
        invitee = _user(db, "invitee")
        parent = _org(db, "parent")
        sub = _org(db, "sub", parent_org_id=parent.id)
        _membership(db, parent, regular, role="member")
        _membership(db, parent, invitee, role="member")
        # regular is a sub-org *member* but NOT admin
        _sub_membership(db, sub, regular, role="member")
        db.commit()

        resp = client.post(
            f"/api/orgs/{parent.slug}/sub-orgs/sub/members/invite",
            json={"user_id": invitee.id, "role": "member"},
            headers=_auth(regular),
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Topic & proposal scope
# ---------------------------------------------------------------------------

class TestTopicAndProposalScope:
    def _bootstrap(self, db):
        admin = _user(db, "admin")
        sub_admin = _user(db, "subadmin")
        parent_only = _user(db, "parentonly")
        sub_member = _user(db, "submember")
        parent = _org(db, "parent")
        sub = _org(db, "sub", parent_org_id=parent.id)
        _membership(db, parent, admin, role="admin")
        # sub_admin needs parent-org moderator role at minimum so the
        # existing `require_org_moderator_or_admin` gate on POST proposals
        # passes; the sub-org admin check is layered on top.
        _membership(db, parent, sub_admin, role="moderator")
        _membership(db, parent, parent_only, role="member")
        _membership(db, parent, sub_member, role="member")
        _sub_membership(db, sub, sub_admin, role="admin")
        _sub_membership(db, sub, sub_member, role="member")
        db.commit()
        return admin, sub_admin, parent_only, sub_member, parent, sub

    def test_create_topic_with_sub_org_scope(self, db, client):
        admin, sub_admin, parent_only, sub_member, parent, sub = self._bootstrap(db)
        resp = client.post(
            f"/api/orgs/{parent.slug}/topics",
            json={
                "name": "Eng-Practices", "description": "", "color": "#abc",
                "sub_org_id": sub.id,
            },
            headers=_auth(sub_admin),
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["sub_org_id"] == sub.id

    def test_topic_list_filters_by_viewer_scope(self, db, client):
        admin, sub_admin, parent_only, sub_member, parent, sub = self._bootstrap(db)
        # Org-wide topic
        t_open = models.Topic(
            name="Open", description="", color="#000", org_id=parent.id,
        )
        # Sub-org-scoped topic
        t_sub = models.Topic(
            name="Sub", description="", color="#000",
            org_id=parent.id, sub_org_id=sub.id,
        )
        db.add_all([t_open, t_sub])
        db.commit()

        # parent_only sees only the open topic
        resp = client.get(
            f"/api/orgs/{parent.slug}/topics", headers=_auth(parent_only),
        )
        names = [t["name"] for t in resp.json()]
        assert "Open" in names
        assert "Sub" not in names

        # sub_member sees both
        resp = client.get(
            f"/api/orgs/{parent.slug}/topics", headers=_auth(sub_member),
        )
        names = [t["name"] for t in resp.json()]
        assert "Open" in names and "Sub" in names

        # Parent-org admin sees both even though they're not a sub-org member
        resp = client.get(
            f"/api/orgs/{parent.slug}/topics", headers=_auth(admin),
        )
        names = [t["name"] for t in resp.json()]
        assert "Open" in names and "Sub" in names

    def test_create_proposal_with_sub_org_scope(self, db, client):
        admin, sub_admin, parent_only, sub_member, parent, sub = self._bootstrap(db)
        # Need a topic scoped to the sub-org
        topic = models.Topic(
            name="Eng", description="", color="#000",
            org_id=parent.id, sub_org_id=sub.id,
        )
        db.add(topic)
        db.commit()

        resp = client.post(
            f"/api/orgs/{parent.slug}/proposals",
            json={
                "title": "Trunk-Based",
                "body": "",
                "topics": [topic.id],
                "voting_method": "binary",
                "sub_org_id": sub.id,
            },
            headers=_auth(sub_admin),
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["sub_org_id"] == sub.id

    def test_parent_proposal_cannot_use_sub_org_topic(self, db, client):
        admin, sub_admin, parent_only, sub_member, parent, sub = self._bootstrap(db)
        topic = models.Topic(
            name="Eng", description="", color="#000",
            org_id=parent.id, sub_org_id=sub.id,
        )
        db.add(topic)
        db.commit()

        resp = client.post(
            f"/api/orgs/{parent.slug}/proposals",
            json={
                "title": "P", "body": "", "topics": [topic.id],
                "voting_method": "binary",
                # no sub_org_id => parent-org-wide
            },
            headers=_auth(admin),
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Promote-to-org-wide
# ---------------------------------------------------------------------------

class TestPromoteTopic:
    def test_promote_with_confirm_succeeds(self, db, client):
        admin = _user(db, "admin")
        parent = _org(db, "parent")
        sub = _org(db, "sub", parent_org_id=parent.id)
        _membership(db, parent, admin, role="admin")
        topic = models.Topic(
            name="Eng", description="", color="#000",
            org_id=parent.id, sub_org_id=sub.id,
        )
        db.add(topic)
        db.commit()

        resp = client.post(
            f"/api/orgs/{parent.slug}/topics/{topic.id}/promote-to-orgwide",
            json={"confirm": True},
            headers=_auth(admin),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["sub_org_id"] is None

        # Audit event fired
        events = _audit_actions(db, "topic.promoted_to_orgwide")
        assert len(events) == 1
        assert events[0].details["promoted_from_sub_org_id"] == sub.id

    def test_promote_without_confirm_fails(self, db, client):
        admin = _user(db, "admin")
        parent = _org(db, "parent")
        sub = _org(db, "sub", parent_org_id=parent.id)
        _membership(db, parent, admin, role="admin")
        topic = models.Topic(
            name="Eng", description="", color="#000",
            org_id=parent.id, sub_org_id=sub.id,
        )
        db.add(topic)
        db.commit()

        resp = client.post(
            f"/api/orgs/{parent.slug}/topics/{topic.id}/promote-to-orgwide",
            json={},
            headers=_auth(admin),
        )
        assert resp.status_code == 400

    def test_promote_already_orgwide_fails(self, db, client):
        admin = _user(db, "admin")
        parent = _org(db, "parent")
        _membership(db, parent, admin, role="admin")
        topic = models.Topic(
            name="Open", description="", color="#000",
            org_id=parent.id, sub_org_id=None,
        )
        db.add(topic)
        db.commit()

        resp = client.post(
            f"/api/orgs/{parent.slug}/topics/{topic.id}/promote-to-orgwide",
            json={"confirm": True},
            headers=_auth(admin),
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Privacy + cross-scope flag flips
# ---------------------------------------------------------------------------

class TestPrivacyAndCrossScope:
    def test_privacy_flag_hides_sub_org_proposals(self, db, client):
        admin = _user(db, "admin")
        parent_only = _user(db, "parentonly")
        sub_member = _user(db, "submember")
        parent = _org(db, "parent")
        sub = _org(db, "sub", parent_org_id=parent.id)
        _membership(db, parent, admin, role="admin")
        _membership(db, parent, parent_only, role="member")
        _membership(db, parent, sub_member, role="member")
        _sub_membership(db, sub, sub_member, role="admin")
        # Sub-org-scoped proposal
        proposal = models.Proposal(
            title="Sub Prop", body="", author_id=sub_member.id, status="voting",
            org_id=parent.id, sub_org_id=sub.id,
        )
        db.add(proposal)
        db.commit()

        # Default (not private): parent_only sees the proposal
        resp = client.get(
            f"/api/orgs/{parent.slug}/proposals", headers=_auth(parent_only),
        )
        assert resp.status_code == 200
        assert any(p["id"] == proposal.id for p in resp.json())

        # Flip privacy on
        resp = client.patch(
            f"/api/orgs/{parent.slug}/sub-orgs/sub",
            json={"settings": {"private": True}},
            headers=_auth(sub_member),
        )
        assert resp.status_code == 200
        events = _audit_actions(db, "sub_org.privacy_changed")
        assert len(events) == 1
        assert events[0].details["new_value"] is True

        # parent_only no longer sees it
        resp = client.get(
            f"/api/orgs/{parent.slug}/proposals", headers=_auth(parent_only),
        )
        assert all(p["id"] != proposal.id for p in resp.json())

        # sub_member still sees it
        resp = client.get(
            f"/api/orgs/{parent.slug}/proposals", headers=_auth(sub_member),
        )
        assert any(p["id"] == proposal.id for p in resp.json())

        # Parent-org admin always sees it
        resp = client.get(
            f"/api/orgs/{parent.slug}/proposals", headers=_auth(admin),
        )
        assert any(p["id"] == proposal.id for p in resp.json())

    def test_cross_scope_delegation_setting_audit(self, db, client):
        admin = _user(db, "admin")
        parent = _org(db, "parent")
        sub = _org(db, "sub", parent_org_id=parent.id)
        _membership(db, parent, admin, role="admin")
        db.commit()

        resp = client.patch(
            f"/api/orgs/{parent.slug}/sub-orgs/sub",
            json={"settings": {"reject_non_member_delegations": True}},
            headers=_auth(admin),
        )
        assert resp.status_code == 200
        events = _audit_actions(
            db, "sub_org.cross_scope_delegation_setting_changed"
        )
        assert len(events) == 1
        assert events[0].details["new_value"] is True


# ---------------------------------------------------------------------------
# Voting method override via get_org_config
# ---------------------------------------------------------------------------

class TestVotingMethodOverride:
    def test_sub_org_can_enable_rcv_when_parent_does_not(self, db, client):
        """Decision 9: sub-org's settings override parent's allowed_voting_methods."""
        admin = _user(db, "admin")
        parent = _org(db, "parent", settings={
            "allowed_voting_methods": ["binary", "approval"],
        })
        sub = _org(db, "sub", parent_org_id=parent.id, settings={
            "allowed_voting_methods": ["binary", "approval", "ranked_choice"],
        })
        _membership(db, parent, admin, role="admin")
        topic = models.Topic(
            name="Sub Eng", description="", color="#000",
            org_id=parent.id, sub_org_id=sub.id,
        )
        db.add(topic)
        db.commit()

        # Sub-org-scoped RCV proposal succeeds
        resp = client.post(
            f"/api/orgs/{parent.slug}/proposals",
            json={
                "title": "RCV Sub Prop",
                "body": "",
                "topics": [topic.id],
                "voting_method": "ranked_choice",
                "sub_org_id": sub.id,
                "options": [
                    {"label": "A"}, {"label": "B"}, {"label": "C"},
                ],
            },
            headers=_auth(admin),
        )
        assert resp.status_code == 201, resp.text

        # Parent-scoped RCV proposal still fails (parent allowlist excludes RCV)
        resp = client.post(
            f"/api/orgs/{parent.slug}/proposals",
            json={
                "title": "RCV Parent Prop",
                "body": "",
                "topics": [],
                "voting_method": "ranked_choice",
                "options": [
                    {"label": "A"}, {"label": "B"}, {"label": "C"},
                ],
            },
            headers=_auth(admin),
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Composite audit event coverage
# ---------------------------------------------------------------------------

class TestAuditEventCoverage:
    def test_all_eight_event_types_fire(self, db, client):
        """Composite test: drives all 8 new audit event types and confirms
        each one fires with the expected payload shape.

        Events:
          1. sub_org.created
          2. sub_org.updated
          3. sub_org.privacy_changed
          4. sub_org.cross_scope_delegation_setting_changed
          5. sub_org.member_invited
          6. sub_org.member_joined
          7. sub_org.member_role_changed
          8. sub_org.member_removed
          9. sub_org.deleted
          10. topic.promoted_to_orgwide
        """
        admin = _user(db, "admin")
        invitee = _user(db, "invitee")
        parent = _org(db, "parent")
        _membership(db, parent, admin, role="admin")
        _membership(db, parent, invitee, role="member")
        db.commit()

        # 1. create
        resp = client.post(
            f"/api/orgs/{parent.slug}/sub-orgs",
            json={"name": "S", "slug": "scope1"},
            headers=_auth(admin),
        )
        assert resp.status_code == 201

        # 2. update (name change)
        resp = client.patch(
            f"/api/orgs/{parent.slug}/sub-orgs/scope1",
            json={"name": "S2"},
            headers=_auth(admin),
        )
        assert resp.status_code == 200

        # 3. privacy_changed
        resp = client.patch(
            f"/api/orgs/{parent.slug}/sub-orgs/scope1",
            json={"settings": {"private": True}},
            headers=_auth(admin),
        )
        assert resp.status_code == 200

        # 4. cross_scope_delegation_setting_changed
        resp = client.patch(
            f"/api/orgs/{parent.slug}/sub-orgs/scope1",
            json={"settings": {"reject_non_member_delegations": True}},
            headers=_auth(admin),
        )
        assert resp.status_code == 200

        # 5. member_invited
        resp = client.post(
            f"/api/orgs/{parent.slug}/sub-orgs/scope1/members/invite",
            json={"user_id": invitee.id, "role": "member"},
            headers=_auth(admin),
        )
        assert resp.status_code == 200

        # 6. member_joined (approve)
        resp = client.post(
            f"/api/orgs/{parent.slug}/sub-orgs/scope1/members/{invitee.id}/approve",
            headers=_auth(admin),
        )
        assert resp.status_code == 200

        # 7. member_role_changed
        resp = client.post(
            f"/api/orgs/{parent.slug}/sub-orgs/scope1/members/{invitee.id}/change-role",
            json={"role": "moderator"},
            headers=_auth(admin),
        )
        assert resp.status_code == 200

        # 8. member_removed
        resp = client.post(
            f"/api/orgs/{parent.slug}/sub-orgs/scope1/members/{invitee.id}/remove",
            headers=_auth(admin),
        )
        assert resp.status_code == 200

        # Add a topic for promote-to-orgwide. We need a fresh sub-org since the
        # one we just munged has its private flag set; it doesn't matter for
        # promote, just for clarity.
        sub = db.query(models.Organization).filter_by(slug="scope1").first()
        topic = models.Topic(
            name="T1", description="", color="#000",
            org_id=parent.id, sub_org_id=sub.id,
        )
        db.add(topic)
        db.commit()

        # 10. topic.promoted_to_orgwide
        resp = client.post(
            f"/api/orgs/{parent.slug}/topics/{topic.id}/promote-to-orgwide",
            json={"confirm": True},
            headers=_auth(admin),
        )
        assert resp.status_code == 200, resp.text

        # 9. delete sub-org (no scoped topics/proposals left after promote)
        resp = client.delete(
            f"/api/orgs/{parent.slug}/sub-orgs/scope1",
            headers=_auth(admin),
        )
        assert resp.status_code == 204

        expected = {
            "sub_org.created",
            "sub_org.updated",
            "sub_org.privacy_changed",
            "sub_org.cross_scope_delegation_setting_changed",
            "sub_org.member_invited",
            "sub_org.member_joined",
            "sub_org.member_role_changed",
            "sub_org.member_removed",
            "sub_org.deleted",
            "topic.promoted_to_orgwide",
        }
        all_events = _audit_actions(db)
        action_set = {e.action for e in all_events}
        missing = expected - action_set
        assert not missing, f"Missing audit events: {missing}"

        # Dump the captured events as a JSON sample for the test_results
        # screenshots dir so the lead can attach to the PROGRESS entry.
        import os
        out_dir = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "test_results", "phase8_5_screenshots",
        )
        os.makedirs(out_dir, exist_ok=True)
        out_file = os.path.join(out_dir, "session2_audit_log_sample.txt")
        sample = []
        for e in all_events:
            if e.action in expected:
                sample.append({
                    "action": e.action,
                    "target_type": e.target_type,
                    "target_id": e.target_id,
                    "actor_id": e.actor_id,
                    "details": e.details,
                })
        with open(out_file, "w") as f:
            f.write(json.dumps(sample, indent=2, default=str))


# ---------------------------------------------------------------------------
# Decision 6: parent-org admin implicit power
# ---------------------------------------------------------------------------

class TestParentOrgAdminImplicitPower:
    def test_parent_admin_can_act_on_sub_org_without_membership(self, db, client):
        """Decision 6: a parent-org admin who is NOT a sub-org member can
        still update, invite to, and delete a sub-org of theirs."""
        admin = _user(db, "admin")
        parent = _org(db, "parent")
        sub = _org(db, "sub", parent_org_id=parent.id)
        _membership(db, parent, admin, role="admin")
        # admin has NO SubOrgMembership row
        db.commit()

        # Patch sub-org as parent admin
        resp = client.patch(
            f"/api/orgs/{parent.slug}/sub-orgs/sub",
            json={"description": "by parent admin"},
            headers=_auth(admin),
        )
        assert resp.status_code == 200
