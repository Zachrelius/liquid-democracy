"""Phase 71b — systemic config-authoritative sweep.

Each previously-tier-gated key now reads the org's role_permissions config,
with the role tier kept as a FLOOR. Per key: side-effect assertion both
directions (holds cell → action mutates the right rows; cell revoked → 403,
no mutation) + floor invariant (a role below the tier floor granted the cell
still 403s). Plus: member.remove/topic.delete ENGINE-path regression,
member.invite at the lowered moderator floor, and the polis.manage
creator-ownership clause preserved.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from database import Base, get_db
import models
import auth as auth_utils
from main import app
from tests.conftest import make_org_membership


_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


@pytest.fixture(scope="function")
def test_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
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
def client(test_db):
    def override_get_db():
        try:
            yield test_db
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _user(db, username, *, is_admin=False):
    u = models.User(
        username=username, display_name=username.title(), password_hash=_DUMMY_HASH,
        email=f"{username}@test.example", email_verified=True, is_admin=is_admin,
    )
    db.add(u); db.flush(); return u


def _org(db, slug="test-org", *, settings=None, **kw):
    o = models.Organization(
        name=slug.title(), slug=slug, description="",
        join_policy="approval_required",
        settings=settings if settings is not None else {"default_voting_days": 7},
        **kw,
    )
    db.add(o); db.flush(); return o


def _member(db, org, user, role="member", status="active"):
    return make_org_membership(db, user_id=user.id, org_id=org.id, role=role, status=status)


def _auth(user):
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _set_perm(db, org_id, system_key, key, enabled):
    role = db.query(models.Role).filter_by(org_id=org_id, system_key=system_key).first()
    row = db.query(models.RolePermission).filter_by(role_id=role.id, permission_key=key).first()
    if row is None:
        db.add(models.RolePermission(role_id=role.id, permission_key=key, enabled=enabled))
    else:
        row.enabled = enabled
    db.commit()
    db.info.pop("_permission_cache", None)


def _topic(db, org):
    t = models.Topic(name="Environment", color="#00ff00", org_id=org.id)
    db.add(t); db.flush(); return t


# ===========================================================================
# topic.edit — moderator+ floor, moderator granted by default
# ===========================================================================

class TestTopicEdit:
    def _setup(self, db):
        org = _org(db); mod = _user(db, "mod"); _member(db, org, mod, role="moderator")
        topic = _topic(db, org); db.commit()
        return org, mod, topic

    def test_moderator_with_cell_can_edit(self, client, test_db):
        org, mod, topic = self._setup(test_db)
        r = client.patch(f"/api/orgs/test-org/topics/{topic.id}", headers=_auth(mod),
                         json={"name": "Climate", "color": "#0000ff"})
        assert r.status_code == 200, r.text
        test_db.expire_all()
        assert test_db.get(models.Topic, topic.id).name == "Climate"

    def test_moderator_cell_revoked_403_no_change(self, client, test_db):
        org, mod, topic = self._setup(test_db)
        _set_perm(test_db, org.id, "moderator", "topic.edit", False)
        r = client.patch(f"/api/orgs/test-org/topics/{topic.id}", headers=_auth(mod),
                         json={"name": "Climate", "color": "#0000ff"})
        assert r.status_code == 403, r.text
        test_db.expire_all()
        assert test_db.get(models.Topic, topic.id).name == "Environment"

    def test_floor_member_with_cell_403(self, client, test_db):
        org = _org(test_db); m = _user(test_db, "plain"); _member(test_db, org, m, role="member")
        topic = _topic(test_db, org); test_db.commit()
        _set_perm(test_db, org.id, "member", "topic.edit", True)
        r = client.patch(f"/api/orgs/test-org/topics/{topic.id}", headers=_auth(m),
                         json={"name": "X", "color": "#0000ff"})
        assert r.status_code == 403, r.text


# ===========================================================================
# topic.delete — admin floor (VERIFIED: route is require_org_admin, not mod+)
# ===========================================================================

class TestTopicDelete:
    def test_admin_with_cell_can_delete(self, client, test_db):
        org = _org(test_db); admin = _user(test_db, "admin"); _member(test_db, org, admin, role="admin")
        topic = _topic(test_db, org); test_db.commit()
        r = client.delete(f"/api/orgs/test-org/topics/{topic.id}", headers=_auth(admin))
        assert r.status_code == 204, r.text
        test_db.expire_all()
        assert test_db.get(models.Topic, topic.id).org_id is None  # soft-deleted

    def test_admin_cell_revoked_403_no_change(self, client, test_db):
        org = _org(test_db); admin = _user(test_db, "admin"); _member(test_db, org, admin, role="admin")
        topic = _topic(test_db, org); test_db.commit()
        _set_perm(test_db, org.id, "admin", "topic.delete", False)
        r = client.delete(f"/api/orgs/test-org/topics/{topic.id}", headers=_auth(admin))
        assert r.status_code == 403, r.text
        test_db.expire_all()
        assert test_db.get(models.Topic, topic.id).org_id == org.id

    def test_floor_moderator_with_cell_403(self, client, test_db):
        """topic.delete floors at admin — a moderator granted the cell still
        403s (tier floor holds; this is why 71a seeded topic.delete admin-only,
        NOT moderator as the 71b spec table claimed)."""
        org = _org(test_db); mod = _user(test_db, "mod"); _member(test_db, org, mod, role="moderator")
        topic = _topic(test_db, org); test_db.commit()
        _set_perm(test_db, org.id, "moderator", "topic.delete", True)
        r = client.delete(f"/api/orgs/test-org/topics/{topic.id}", headers=_auth(mod))
        assert r.status_code == 403, r.text
        test_db.expire_all()
        assert test_db.get(models.Topic, topic.id).org_id == org.id


# ===========================================================================
# member.approve_join — moderator+ floor
# ===========================================================================

class TestMemberApproveJoin:
    def _setup(self, db, role="moderator"):
        org = _org(db); actor = _user(db, "actor"); _member(db, org, actor, role=role)
        applicant = _user(db, "applicant"); _member(db, org, applicant, role="member", status="pending_approval")
        db.commit()
        return org, actor, applicant

    def test_moderator_can_approve(self, client, test_db):
        org, mod, applicant = self._setup(test_db)
        r = client.post(f"/api/orgs/test-org/join/approve/{applicant.id}", headers=_auth(mod))
        assert r.status_code == 200, r.text
        m = test_db.query(models.OrgMembership).filter_by(org_id=org.id, user_id=applicant.id).first()
        assert m.status == "active"

    def test_moderator_revoked_403_no_change(self, client, test_db):
        org, mod, applicant = self._setup(test_db)
        _set_perm(test_db, org.id, "moderator", "member.approve_join", False)
        r = client.post(f"/api/orgs/test-org/join/approve/{applicant.id}", headers=_auth(mod))
        assert r.status_code == 403, r.text
        m = test_db.query(models.OrgMembership).filter_by(org_id=org.id, user_id=applicant.id).first()
        assert m.status == "pending_approval"

    def test_floor_member_with_cell_403(self, client, test_db):
        org = _org(test_db); m = _user(test_db, "plain"); _member(test_db, org, m, role="member")
        applicant = _user(test_db, "applicant"); _member(test_db, org, applicant, role="member", status="pending_approval")
        test_db.commit()
        _set_perm(test_db, org.id, "member", "member.approve_join", True)
        r = client.post(f"/api/orgs/test-org/join/approve/{applicant.id}", headers=_auth(m))
        assert r.status_code == 403, r.text


# ===========================================================================
# member.remove — admin floor; direct path + ENGINE path
# ===========================================================================

class TestMemberRemove:
    def test_admin_with_cell_removes(self, client, test_db):
        org = _org(test_db); admin = _user(test_db, "admin"); _member(test_db, org, admin, role="admin")
        target = _user(test_db, "target"); _member(test_db, org, target, role="member"); test_db.commit()
        r = client.delete(f"/api/orgs/test-org/members/{target.id}", headers=_auth(admin))
        assert r.status_code == 204, r.text
        assert test_db.query(models.OrgMembership).filter_by(org_id=org.id, user_id=target.id).first() is None

    def test_admin_cell_revoked_403_no_change(self, client, test_db):
        org = _org(test_db); admin = _user(test_db, "admin"); _member(test_db, org, admin, role="admin")
        target = _user(test_db, "target"); _member(test_db, org, target, role="member"); test_db.commit()
        _set_perm(test_db, org.id, "admin", "member.remove", False)
        r = client.delete(f"/api/orgs/test-org/members/{target.id}", headers=_auth(admin))
        assert r.status_code == 403, r.text
        assert test_db.query(models.OrgMembership).filter_by(org_id=org.id, user_id=target.id).first() is not None

    def test_floor_moderator_with_cell_403(self, client, test_db):
        org = _org(test_db); mod = _user(test_db, "mod"); _member(test_db, org, mod, role="moderator")
        target = _user(test_db, "target"); _member(test_db, org, target, role="member"); test_db.commit()
        _set_perm(test_db, org.id, "moderator", "member.remove", True)
        r = client.delete(f"/api/orgs/test-org/members/{target.id}", headers=_auth(mod))
        assert r.status_code == 403, r.text

    def test_engine_path_still_works_with_cell(self, client, test_db):
        """Multi-admin approval ON: the engine path gates member.remove via
        required_permission_key and must still function (not double-broken)."""
        org = _org(test_db, settings={
            "default_voting_days": 7,
            "multi_admin_approval": {"enabled": True, "thresholds": {"member.remove": 2}},
        })
        steward = _user(test_db, "steward"); _member(test_db, org, steward, role="steward")
        admin2 = _user(test_db, "admin2"); _member(test_db, org, admin2, role="admin")
        target = _user(test_db, "target"); _member(test_db, org, target, role="member"); test_db.commit()
        r = client.delete(f"/api/orgs/test-org/members/{target.id}", headers=_auth(steward))
        # Either submitted for approval (pending) or executed directly if the
        # deadlock guard fired — both are non-403 (initiator held the key).
        assert r.status_code in (200, 204), r.text


# ===========================================================================
# member.invite — floor LOWERED to moderator+ (Z decision); whole surface
# ===========================================================================

class TestMemberInvite:
    def test_moderator_with_default_cell_can_send(self, client, test_db):
        """The Z-intended new capability: a moderator (who holds member.invite
        by default) can now actually send invitations."""
        org = _org(test_db); mod = _user(test_db, "mod"); _member(test_db, org, mod, role="moderator")
        test_db.commit()
        r = client.post("/api/orgs/test-org/invitations", headers=_auth(mod),
                        json={"emails": ["new@x.example"], "role": "member"})
        assert r.status_code == 201, r.text
        assert test_db.query(models.Invitation).filter_by(org_id=org.id).count() == 1

    def test_moderator_revoked_403(self, client, test_db):
        org = _org(test_db); mod = _user(test_db, "mod"); _member(test_db, org, mod, role="moderator")
        test_db.commit()
        _set_perm(test_db, org.id, "moderator", "member.invite", False)
        r = client.post("/api/orgs/test-org/invitations", headers=_auth(mod),
                        json={"emails": ["new@x.example"], "role": "member"})
        assert r.status_code == 403, r.text
        assert test_db.query(models.Invitation).filter_by(org_id=org.id).count() == 0

    def test_floor_member_with_cell_403(self, client, test_db):
        org = _org(test_db); m = _user(test_db, "plain"); _member(test_db, org, m, role="member")
        test_db.commit()
        _set_perm(test_db, org.id, "member", "member.invite", True)
        r = client.post("/api/orgs/test-org/invitations", headers=_auth(m),
                        json={"emails": ["new@x.example"], "role": "member"})
        assert r.status_code == 403, r.text

    def test_moderator_can_list_invitations(self, client, test_db):
        """member.invite governs the whole surface — a moderator who can send
        can also list (so the FE invite section isn't half-403)."""
        org = _org(test_db); mod = _user(test_db, "mod"); _member(test_db, org, mod, role="moderator")
        test_db.commit()
        r = client.get("/api/orgs/test-org/invitations", headers=_auth(mod))
        assert r.status_code == 200, r.text


# ===========================================================================
# sub_org.* — admin floor on parent (parent-admin implicit power)
# ===========================================================================

class TestSubOrgKeys:
    def _setup(self, db):
        parent = _org(db, "parent")
        admin = _user(db, "padmin"); _member(db, parent, admin, role="admin")
        sub = _org(db, "sub", parent_org_id=parent.id)
        db.commit()
        return parent, admin, sub

    def test_create_admin_with_cell(self, client, test_db):
        parent, admin, sub = self._setup(test_db)
        r = client.post("/api/orgs/parent/sub-orgs", headers=_auth(admin),
                        json={"name": "New Sub", "slug": "newsub", "description": ""})
        assert r.status_code in (200, 201), r.text

    def test_create_admin_revoked_403(self, client, test_db):
        parent, admin, sub = self._setup(test_db)
        _set_perm(test_db, parent.id, "admin", "sub_org.create", False)
        r = client.post("/api/orgs/parent/sub-orgs", headers=_auth(admin),
                        json={"name": "New Sub", "slug": "newsub2", "description": ""})
        assert r.status_code == 403, r.text

    def test_edit_settings_admin_with_cell(self, client, test_db):
        parent, admin, sub = self._setup(test_db)
        r = client.patch("/api/orgs/parent/sub-orgs/sub", headers=_auth(admin),
                         json={"name": "Renamed Sub"})
        assert r.status_code == 200, r.text
        test_db.expire_all()
        assert test_db.get(models.Organization, sub.id).name == "Renamed Sub"

    def test_edit_settings_admin_revoked_403(self, client, test_db):
        parent, admin, sub = self._setup(test_db)
        _set_perm(test_db, parent.id, "admin", "sub_org.edit_settings", False)
        r = client.patch("/api/orgs/parent/sub-orgs/sub", headers=_auth(admin),
                         json={"name": "Renamed Sub"})
        assert r.status_code == 403, r.text
        test_db.expire_all()
        assert test_db.get(models.Organization, sub.id).name == "Sub"

    def test_delete_admin_with_cell(self, client, test_db):
        parent, admin, sub = self._setup(test_db)
        r = client.delete("/api/orgs/parent/sub-orgs/sub", headers=_auth(admin))
        assert r.status_code in (200, 204), r.text

    def test_delete_admin_revoked_403(self, client, test_db):
        parent, admin, sub = self._setup(test_db)
        _set_perm(test_db, parent.id, "admin", "sub_org.delete", False)
        r = client.delete("/api/orgs/parent/sub-orgs/sub", headers=_auth(admin))
        assert r.status_code == 403, r.text
        assert test_db.get(models.Organization, sub.id) is not None


# ===========================================================================
# polis.create (moderator+) and polis.manage (creator-OR + mod+ floor)
# ===========================================================================

class TestPolisKeys:
    def _polis(self, db, org, creator, **kw):
        p = models.Polis(org_id=org.id, title="P", prompt="Q?", created_by=creator.id, **kw)
        db.add(p); db.flush(); return p

    def test_create_moderator_with_cell(self, client, test_db):
        org = _org(test_db); mod = _user(test_db, "mod"); _member(test_db, org, mod, role="moderator")
        test_db.commit()
        # Manual-fallback (no POLIS_AUTH_TOKEN in tests) requires a pasted
        # conversation id; the polis.create gate is checked BEFORE that
        # validation, so this exercises the granted path end-to-end.
        r = client.post("/api/orgs/test-org/polises", headers=_auth(mod),
                        json={"title": "T", "prompt": "Q?", "polis_conversation_id": "demo-convo-1"})
        assert r.status_code in (200, 201), r.text

    def test_create_moderator_revoked_403(self, client, test_db):
        org = _org(test_db); mod = _user(test_db, "mod"); _member(test_db, org, mod, role="moderator")
        test_db.commit()
        _set_perm(test_db, org.id, "moderator", "polis.create", False)
        r = client.post("/api/orgs/test-org/polises", headers=_auth(mod),
                        json={"title": "T", "prompt": "Q?"})
        assert r.status_code == 403, r.text

    def test_manage_creator_clause_preserved(self, client, test_db):
        """A plain MEMBER who created the Polis can still manage it — the
        creator-ownership axis survives the config-authoritative conversion
        (Z requirement). They have neither moderator tier nor polis.manage."""
        org = _org(test_db); creator = _user(test_db, "creator"); _member(test_db, org, creator, role="member")
        polis = self._polis(test_db, org, creator); test_db.commit()
        r = client.patch(f"/api/orgs/test-org/polises/{polis.id}", headers=_auth(creator),
                         json={"title": "Creator Renamed"})
        assert r.status_code == 200, r.text
        test_db.expire_all()
        assert test_db.get(models.Polis, polis.id).title == "Creator Renamed"

    def test_manage_moderator_noncreator_with_cell(self, client, test_db):
        org = _org(test_db)
        author = _user(test_db, "author"); _member(test_db, org, author, role="member")
        mod = _user(test_db, "mod"); _member(test_db, org, mod, role="moderator")
        polis = self._polis(test_db, org, author); test_db.commit()
        r = client.patch(f"/api/orgs/test-org/polises/{polis.id}", headers=_auth(mod),
                         json={"title": "Mod Renamed"})
        assert r.status_code == 200, r.text

    def test_manage_moderator_noncreator_revoked_403(self, client, test_db):
        org = _org(test_db)
        author = _user(test_db, "author"); _member(test_db, org, author, role="member")
        mod = _user(test_db, "mod"); _member(test_db, org, mod, role="moderator")
        polis = self._polis(test_db, org, author); test_db.commit()
        _set_perm(test_db, org.id, "moderator", "polis.manage", False)
        r = client.patch(f"/api/orgs/test-org/polises/{polis.id}", headers=_auth(mod),
                         json={"title": "Should Fail"})
        assert r.status_code == 403, r.text
        test_db.expire_all()
        assert test_db.get(models.Polis, polis.id).title == "P"

    def test_manage_floor_member_noncreator_with_cell_403(self, client, test_db):
        """A plain member who is NOT the creator, granted polis.manage, still
        403s — the moderator+ tier floor holds."""
        org = _org(test_db)
        author = _user(test_db, "author"); _member(test_db, org, author, role="member")
        other = _user(test_db, "other"); _member(test_db, org, other, role="member")
        polis = self._polis(test_db, org, author); test_db.commit()
        _set_perm(test_db, org.id, "member", "polis.manage", True)
        r = client.patch(f"/api/orgs/test-org/polises/{polis.id}", headers=_auth(other),
                         json={"title": "Should Fail"})
        assert r.status_code == 403, r.text
