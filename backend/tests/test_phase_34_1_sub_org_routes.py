"""Phase 34.1 — sub-org route + middleware regression tests.

Covers:
- E3: GET /api/orgs/<sub_slug>/proposals returns the sub-org's proposals
  (was empty pre-fix because filter used Proposal.org_id == sub.id but
  proposals are seeded with org_id=parent + sub_org_id=sub).
- E3-sibling: GET /api/orgs/<sub_slug>/topics returns sub-org topics.
- E4: require_org_membership accepts SubOrgMembership when target org is
  a sub-org (was 403 for users created via UI's create_sub_org which
  never wrote OrgMembership on the sub-org Organization row).
- E5: _org_to_out inherits branding (logo_url, primary_color,
  accent_color) from parent when sub-org's value is null.
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


def _make_user(db, username):
    u = models.User(
        username=username, display_name=username.title(),
        email=f"{username}@example.com", email_verified=True,
        password_hash=auth_utils.hash_password("noop"),
    )
    db.add(u)
    db.flush()
    db.commit()
    return u


def _ensure_role(db, org_id, system_key):
    role = db.query(models.Role).filter_by(
        org_id=org_id, system_key=system_key,
    ).first()
    if role is None:
        role = models.Role(
            org_id=org_id, system_key=system_key,
            name=system_key.title(), display_order=0,
        )
        db.add(role)
        db.flush()
    return role


def _make_org(db, slug, *, parent_id=None, branding=None):
    settings = {}
    if branding is not None:
        settings["branding"] = branding
    org = models.Organization(
        name=slug.title(), slug=slug, settings=settings,
        parent_org_id=parent_id, join_policy="open",
    )
    db.add(org)
    db.flush()
    return org


def _login(client, username):
    resp = client.post(
        "/api/auth/login",
        data={"username": username, "password": "noop"},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _setup_parent_and_sub(db_session, *, sub_branding=None, parent_branding=None):
    parent = _make_org(db_session, "test-parent", branding=parent_branding)
    sub = _make_org(
        db_session, "test-sub",
        parent_id=parent.id, branding=sub_branding,
    )
    user = _make_user(db_session, "subuser")
    # Parent member role (sub-orgs inherit parent's roles per Phase 15 S)
    parent_member = _ensure_role(db_session, parent.id, "member")
    # User has OrgMembership on parent (so they can navigate into sub-org
    # via parent admin/member power), AND SubOrgMembership on sub-org.
    db_session.add(models.OrgMembership(
        user_id=user.id, org_id=parent.id,
        role_id=parent_member.id, status="active",
    ))
    db_session.add(models.SubOrgMembership(
        user_id=user.id, sub_org_id=sub.id,
        role_id=parent_member.id, status="active",
    ))
    db_session.flush()
    db_session.commit()
    return parent, sub, user


# ============================================================================
# E4 — require_org_membership accepts SubOrgMembership
# ============================================================================


class TestE4SubOrgMembershipAcceptedByMiddleware:
    def test_sub_org_member_can_access_sub_org_route(self, db_session, client):
        """User with SubOrgMembership but no OrgMembership on the sub-org
        Organization row can still hit /api/orgs/<sub_slug>/*. Pre-fix
        returned 403 'Not a member'."""
        parent, sub, user = _setup_parent_and_sub(db_session)
        # GET /api/orgs/<sub_slug>/proposals should not 403.
        headers = _login(client, "subuser")
        resp = client.get(f"/api/orgs/{sub.slug}/proposals", headers=headers)
        assert resp.status_code == 200, resp.text


# ============================================================================
# E3 — sub-org proposals + topics queries
# ============================================================================


class TestE3SubOrgProposalsQuery:
    def test_proposals_listed_via_sub_slug(self, db_session, client):
        """Proposal stored with org_id=parent + sub_org_id=sub is surfaced
        when /api/orgs/<sub_slug>/proposals is hit."""
        parent, sub, user = _setup_parent_and_sub(db_session)
        # Seed one sub-org proposal — note the org_id=parent shape.
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        p = models.Proposal(
            title="Sub-org P", body="", author_id=user.id,
            org_id=parent.id, sub_org_id=sub.id,
            status="deliberation",
            voting_method="binary", num_winners=1,
            deliberation_start=now,
            voting_end=now + timedelta(days=3),
            deliberation_days=14.0, voting_days=7.0,
        )
        db_session.add(p)
        db_session.flush()
        db_session.commit()

        headers = _login(client, "subuser")
        resp = client.get(f"/api/orgs/{sub.slug}/proposals", headers=headers)
        assert resp.status_code == 200
        proposals = resp.json()
        assert len(proposals) == 1
        assert proposals[0]["title"] == "Sub-org P"


class TestE3SubOrgTopicsQuery:
    def test_topics_listed_via_sub_slug(self, db_session, client):
        parent, sub, user = _setup_parent_and_sub(db_session)
        # Seed a sub-org topic — org_id=parent + sub_org_id=sub.
        topic = models.Topic(
            name="Sub Topic", color="#abcdef",
            org_id=parent.id, sub_org_id=sub.id,
        )
        db_session.add(topic)
        db_session.flush()
        db_session.commit()

        headers = _login(client, "subuser")
        resp = client.get(f"/api/orgs/{sub.slug}/topics", headers=headers)
        assert resp.status_code == 200
        topics = resp.json()
        assert len(topics) == 1
        assert topics[0]["name"] == "Sub Topic"


# ============================================================================
# E5 — branding inheritance
# ============================================================================


class TestE5BrandingInheritsFromParent:
    def test_sub_org_with_null_branding_inherits_parent(self, db_session, client):
        parent, sub, user = _setup_parent_and_sub(
            db_session,
            parent_branding={
                "primary_color": "#3B5A3B",
                "logo_url": "/demo_assets/parent-logo.jpg",
            },
            sub_branding=None,
        )
        headers = _login(client, "subuser")
        resp = client.get(f"/api/orgs/{sub.slug}", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        branding = body.get("branding", {})
        assert branding.get("primary_color") == "#3B5A3B"
        assert branding.get("logo_url") == "/demo_assets/parent-logo.jpg"

    def test_sub_org_explicit_value_wins(self, db_session, client):
        """Sub-org's own branding value beats parent's when both set."""
        parent, sub, user = _setup_parent_and_sub(
            db_session,
            parent_branding={"primary_color": "#3B5A3B"},
            sub_branding={"primary_color": "#FF0000"},
        )
        headers = _login(client, "subuser")
        resp = client.get(f"/api/orgs/{sub.slug}", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["branding"]["primary_color"] == "#FF0000"

    def test_parent_branding_untouched(self, db_session, client):
        """Parent's own branding response is unchanged (no inheritance for parent)."""
        parent, sub, user = _setup_parent_and_sub(
            db_session,
            parent_branding={"primary_color": "#3B5A3B"},
        )
        headers = _login(client, "subuser")
        resp = client.get(f"/api/orgs/{parent.slug}", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["branding"]["primary_color"] == "#3B5A3B"

    def test_nested_sub_org_route_also_inherits_branding(self, db_session, client):
        """Phase 34.1 hotfix #1 — the FE consumes
        /api/orgs/{parent}/sub-orgs/{sub} for sub-org admin pages, which
        goes through _sub_org_to_out (different serializer than
        _org_to_out). QA caught that the original E5 fix only patched
        _org_to_out; this regression covers the nested route."""
        parent, sub, user = _setup_parent_and_sub(
            db_session,
            parent_branding={
                "primary_color": "#3B5A3B",
                "logo_url": "/demo_assets/parent-logo.jpg",
            },
            sub_branding=None,
        )
        headers = _login(client, "subuser")
        resp = client.get(
            f"/api/orgs/{parent.slug}/sub-orgs/{sub.slug}", headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        branding = body.get("branding", {})
        assert branding.get("primary_color") == "#3B5A3B"
        assert branding.get("logo_url") == "/demo_assets/parent-logo.jpg"
