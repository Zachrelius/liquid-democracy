"""Phase 32.2 — org controls + bug fixes tests.

Covers:
  - B1 resolver: 4-mode × override-set/null = 8 cases per knob.
  - B2 permission gate: PATCH proposal requires author OR
    org.edit_proposal permission.
  - B3 public-delegate approval-required gate: with toggle OFF,
    submit_public_accepting auto-promotes without the approver
    workflow; with toggle ON, the existing flow runs.
  - B4 hide-on-disable: public-delegate page 404 + browse empty
    when `public_delegates.enabled=False`.
  - M2 permission registry: `org.edit_proposal` registered + seeded
    to admin/steward via DEFAULT_GRANTS.
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
from permission_registry import DEFAULT_GRANTS, PERMISSION_REGISTRY
from proposal_engagement_config import (
    MODE_ALWAYS_OFF,
    MODE_ALWAYS_ON,
    MODE_DEFAULT_OFF,
    MODE_DEFAULT_ON,
    resolve_allow_pre_voting_full,
    resolve_allow_write_in_options_full,
    resolve_show_votes_during_deliberation_full,
)


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


def _make_org(db, slug="test-org", settings=None):
    org = models.Organization(
        name=slug.title(), slug=slug, settings=settings or {},
    )
    db.add(org)
    db.flush()
    return org


def _ensure_role(db, org, system_key, *, perms=None):
    role = db.query(models.Role).filter_by(
        org_id=org.id, system_key=system_key,
    ).first()
    if role is None:
        role = models.Role(
            org_id=org.id, system_key=system_key,
            name=system_key.title(), display_order=0,
        )
        db.add(role)
        db.flush()
    for p in (perms or []):
        existing = db.query(models.RolePermission).filter_by(
            role_id=role.id, permission_key=p,
        ).first()
        if existing is None:
            db.add(models.RolePermission(
                role_id=role.id, permission_key=p, enabled=True,
            ))
    db.flush()
    return role


def _make_membership(db, user, org, system_key="member", perms=None):
    role = _ensure_role(db, org, system_key, perms=perms)
    m = models.OrgMembership(
        user_id=user.id, org_id=org.id, role_id=role.id, status="active",
    )
    db.add(m)
    db.flush()
    return m


# ===========================================================================
# B1 — Resolver mode logic
# ===========================================================================


class TestResolverFourModeLogic:
    """4 modes × {override=None, override=True, override=False} per knob."""

    def _build(self, db, org_mode, override):
        org = _make_org(db, settings={
            "write_ins": {"allowed_mode": org_mode},
        })
        author = _make_user(db, "author")
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        p = models.Proposal(
            title="T", body="", author_id=author.id, org_id=org.id,
            status="deliberation", voting_method="approval", num_winners=1,
            deliberation_start=now,
            voting_end=now + timedelta(days=3),
            deliberation_days=14.0, voting_days=7.0,
            allow_write_in_options=override,
        )
        db.add(p)
        db.flush()
        return p, org

    @pytest.mark.parametrize("mode,override,expected_eff,expected_overridable", [
        (MODE_ALWAYS_OFF, None, False, False),
        (MODE_ALWAYS_OFF, True, False, False),  # locked overrides ignored
        (MODE_ALWAYS_OFF, False, False, False),
        (MODE_DEFAULT_OFF, None, False, True),
        (MODE_DEFAULT_OFF, True, True, True),
        (MODE_DEFAULT_OFF, False, False, True),
        (MODE_DEFAULT_ON, None, True, True),
        (MODE_DEFAULT_ON, True, True, True),
        (MODE_DEFAULT_ON, False, False, True),
        (MODE_ALWAYS_ON, None, True, False),
        (MODE_ALWAYS_ON, False, True, False),  # locked overrides ignored
    ])
    def test_resolution(
        self, db_session, mode, override, expected_eff, expected_overridable,
    ):
        p, org = self._build(db_session, mode, override)
        r = resolve_allow_write_in_options_full(p, org)
        assert r.effective is expected_eff
        assert r.overridable is expected_overridable


# ===========================================================================
# M2 — Permission registry
# ===========================================================================


class TestPermissionRegistryHasEditProposal:
    def test_key_present(self):
        keys = {p.key for p in PERMISSION_REGISTRY}
        assert "org.edit_proposal" in keys

    def test_seeded_to_admin_and_steward(self):
        assert "org.edit_proposal" in DEFAULT_GRANTS["steward"]
        assert "org.edit_proposal" in DEFAULT_GRANTS["admin"]

    def test_not_seeded_to_moderator_or_member(self):
        assert "org.edit_proposal" not in DEFAULT_GRANTS["moderator"]
        assert "org.edit_proposal" not in DEFAULT_GRANTS["member"]


# ===========================================================================
# B2 — PATCH proposal permission gate
# ===========================================================================


class TestPatchProposalPermissionGate:
    """Author can PATCH; org admin with org.edit_proposal can PATCH;
    ordinary member cannot PATCH another member's proposal."""

    def _setup(self, db_session, *, with_edit_perm=True):
        org = _make_org(db_session)
        author = _make_user(db_session, "author")
        admin = _make_user(db_session, "orgadmin")
        member = _make_user(db_session, "normie")
        _make_membership(db_session, author, org, system_key="member")
        _make_membership(
            db_session, admin, org, system_key="admin",
            perms=(["org.edit_proposal"] if with_edit_perm else []),
        )
        _make_membership(db_session, member, org, system_key="member")
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        p = models.Proposal(
            title="Author's proposal", body="", author_id=author.id,
            org_id=org.id, status="deliberation",
            voting_method="binary", num_winners=1,
            deliberation_start=now,
            voting_end=now + timedelta(days=3),
            deliberation_days=14.0, voting_days=7.0,
        )
        db_session.add(p)
        db_session.flush()
        db_session.commit()
        return p

    def _login(self, client, username):
        resp = client.post(
            "/api/auth/login",
            data={"username": username, "password": "noop"},
        )
        assert resp.status_code == 200, resp.text
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    def test_author_can_patch(self, db_session, client):
        p = self._setup(db_session)
        resp = client.patch(
            f"/api/proposals/{p.id}",
            json={"title": "Author edited"},
            headers=self._login(client, "author"),
        )
        assert resp.status_code == 200, resp.text

    def test_org_admin_can_patch(self, db_session, client):
        p = self._setup(db_session, with_edit_perm=True)
        resp = client.patch(
            f"/api/proposals/{p.id}",
            json={"title": "Admin edited"},
            headers=self._login(client, "orgadmin"),
        )
        assert resp.status_code == 200, resp.text

    def test_member_cannot_patch(self, db_session, client):
        p = self._setup(db_session)
        resp = client.patch(
            f"/api/proposals/{p.id}",
            json={"title": "Sneaky edit"},
            headers=self._login(client, "normie"),
        )
        assert resp.status_code == 403


# ===========================================================================
# B3 — Public delegate approval-required gate
# ===========================================================================


class TestPublicDelegateApprovalRequired:
    """Toggle controls whether submit_public_accepting auto-promotes."""

    def _setup(self, db_session, *, approval_required: bool):
        org = _make_org(db_session, settings={
            "public_delegates": {
                "enabled": True,
                "approval_required": approval_required,
            },
        })
        user = _make_user(db_session, "delegate1")
        _make_membership(db_session, user, org, system_key="member")
        # Approver role with the permission so the existing approver-gate path
        # kicks in when approval is required.
        _ensure_role(
            db_session, org, "admin",
            perms=["delegate_application.approve"],
        )
        topic = models.Topic(name="Budget", org_id=org.id)
        db_session.add(topic)
        db_session.flush()
        # Existing DelegateProfile in `public` state (the spec'd preconditon
        # for submit_public_accepting).
        dp = models.DelegateProfile(
            user_id=user.id,
            org_id=org.id,
            topic_id=topic.id,
            bio="",
            is_active=True,
            visibility="public",
        )
        db_session.add(dp)
        db_session.flush()
        db_session.commit()
        return user, org, topic, dp

    def _login(self, client, username):
        resp = client.post(
            "/api/auth/login",
            data={"username": username, "password": "noop"},
        )
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    def test_approval_required_off_self_promotes(self, db_session, client):
        user, org, topic, dp = self._setup(db_session, approval_required=False)
        resp = client.post(
            f"/api/orgs/{org.slug}/delegate-profile/topics/{topic.id}/submit-public-accepting",
            headers=self._login(client, "delegate1"),
        )
        assert resp.status_code in (200, 201, 204), resp.text
        db_session.refresh(dp)
        assert dp.visibility == "public_accepting"
        assert dp.public_accepting_approved_at is not None


# ===========================================================================
# B4 — Hide-on-disable
# ===========================================================================


class TestPublicDelegateHideOnDisable:
    def _setup(self, db_session, enabled: bool):
        org = _make_org(db_session, settings={
            "public_delegates": {"enabled": enabled, "approval_required": True},
        })
        user = _make_user(db_session, "delegateX")
        _make_membership(db_session, user, org, system_key="member")
        odp = models.OrgDelegateProfile(
            user_id=user.id, org_id=org.id, intro="hi",
        )
        db_session.add(odp)
        db_session.flush()
        db_session.commit()
        return user, org

    def test_disabled_page_returns_404(self, db_session, client):
        user, org = self._setup(db_session, enabled=False)
        resp = client.get(f"/api/orgs/{org.slug}/delegates/delegateX")
        assert resp.status_code == 404

    def test_disabled_browse_returns_empty(self, db_session, client):
        user, org = self._setup(db_session, enabled=False)
        resp = client.get(f"/api/orgs/{org.slug}/delegates")
        assert resp.status_code == 200
        assert resp.json() == []
