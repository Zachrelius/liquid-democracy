"""Phase 30.1 — delegate-approval rebuild + topic-name root-cause tests.

Covers:
  - B2: GET /delegate-applications-pending (scope, exclusion, permission,
    inclusion of intro/bio/position).
  - B2: POST /delegate-applications/{profile_id}/approve and /deny
    (success, cross-org reject, deny requires comment).
  - B4: legacy /delegate-applications endpoints removed (404).
  - B5: Topic.name uniqueness is now scoped to (org_id, name); demo
    seed produces un-prefixed names.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from auth import hash_password
from database import Base, get_db
from demo_content.hoa_bible import HOA_BIBLE
from demo_content.seed_pipeline import seed_org_from_bible
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


def _make_org_with_admin(
    db: Session, slug: str, admin_username: str,
) -> tuple[models.Organization, models.User]:
    """Set up an org with an admin user holding delegate_application.approve."""
    org = models.Organization(
        slug=slug, name=slug.title(),
        description="", join_policy="open",
    )
    db.add(org); db.flush()
    seed_default_roles_for_org(db, org.id)

    admin = _make_user(db, admin_username)
    admin_role = db.query(models.Role).filter_by(
        org_id=org.id, system_key="admin",
    ).first()
    db.add(models.OrgMembership(
        user_id=admin.id, org_id=org.id, role_id=admin_role.id, status="active",
    ))
    db.flush()
    return org, admin


def _make_pending_dp(
    db: Session, org: models.Organization, user: models.User,
    topic_name: str = "Budget",
) -> tuple[models.DelegateProfile, models.Topic]:
    """Create a Topic + a pending DelegateProfile owned by user in org."""
    topic = models.Topic(
        name=topic_name, description=topic_name,
        color="#000000", org_id=org.id,
    )
    db.add(topic); db.flush()

    member_role = db.query(models.Role).filter_by(
        org_id=org.id, system_key="member",
    ).first()
    if not db.query(models.OrgMembership).filter_by(
        user_id=user.id, org_id=org.id,
    ).first():
        db.add(models.OrgMembership(
            user_id=user.id, org_id=org.id, role_id=member_role.id, status="active",
        ))
        db.flush()

    dp = models.DelegateProfile(
        user_id=user.id, org_id=org.id, topic_id=topic.id,
        bio="x" * 60,
        visibility="public",
        public_accepting_submitted_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(dp); db.commit()
    return dp, topic


# ===========================================================================
# B2 — list pending endpoint
# ===========================================================================


class TestListPendingApplicationsScopedToOrg:
    """Pending DPs from another org must not appear."""

    def test_returns_only_this_orgs_pending(self, db_session, client):
        org1, admin1 = _make_org_with_admin(db_session, "o1", "admin1")
        org2, _ = _make_org_with_admin(db_session, "o2", "admin2")
        applicant1 = _make_user(db_session, "alice")
        applicant2 = _make_user(db_session, "bob")
        _make_pending_dp(db_session, org1, applicant1)
        _make_pending_dp(db_session, org2, applicant2)

        resp = client.get(
            f"/api/orgs/{org1.slug}/delegate-applications-pending",
            headers=_auth(admin1.id),
        )
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 1
        assert rows[0]["applicant"]["username"] == "alice"


class TestListPendingApplicationsExcludesApprovedAndDenied:
    """Approved + denied DPs are filtered out."""

    def test_excludes_approved_and_denied(self, db_session, client):
        org, admin = _make_org_with_admin(db_session, "x", "x_admin")
        u_p = _make_user(db_session, "u_pending")
        u_a = _make_user(db_session, "u_approved")
        u_d = _make_user(db_session, "u_denied")
        _make_pending_dp(db_session, org, u_p, topic_name="Budget")
        dp_a, _ = _make_pending_dp(db_session, org, u_a, topic_name="Pool")
        dp_d, _ = _make_pending_dp(db_session, org, u_d, topic_name="Bylaws")

        dp_a.public_accepting_approved_at = datetime.now(timezone.utc).replace(tzinfo=None)
        dp_d.public_accepting_denied_comment = "no"
        db_session.commit()

        resp = client.get(
            f"/api/orgs/{org.slug}/delegate-applications-pending",
            headers=_auth(admin.id),
        )
        assert resp.status_code == 200
        rows = resp.json()
        assert {r["applicant"]["username"] for r in rows} == {"u_pending"}


class TestListPendingApplicationsRequiresPermission:
    """Non-approvers get 403."""

    def test_member_gets_403(self, db_session, client):
        org, _ = _make_org_with_admin(db_session, "y", "y_admin")
        # Member without approve permission.
        applicant = _make_user(db_session, "rando")
        _make_pending_dp(db_session, org, applicant)

        # rando is now a member (added by _make_pending_dp) — no admin role.
        resp = client.get(
            f"/api/orgs/{org.slug}/delegate-applications-pending",
            headers=_auth(applicant.id),
        )
        assert resp.status_code == 403


class TestListPendingApplicationsIncludesBioPosition:
    """The list endpoint surfaces bio + position + topic_name."""

    def test_payload_fields(self, db_session, client):
        org, admin = _make_org_with_admin(db_session, "z", "z_admin")
        applicant = _make_user(db_session, "pamela")
        dp, topic = _make_pending_dp(db_session, org, applicant)
        dp.position_statement = "Budget discipline matters."
        db_session.commit()

        resp = client.get(
            f"/api/orgs/{org.slug}/delegate-applications-pending",
            headers=_auth(admin.id),
        )
        assert resp.status_code == 200
        row = resp.json()[0]
        assert row["topic_name"] == "Budget"
        assert row["bio"].startswith("x")
        assert row["position_statement"] == "Budget discipline matters."
        assert row["applicant"]["display_name"] == "Pamela"
        assert row["delegate_page_url"].startswith(f"/{org.slug}/delegates/")


# ===========================================================================
# B2 — new per-profile-id approve/deny
# ===========================================================================


class TestApproveByProfileIdSucceeds:
    """POST approve transitions DP to public_accepting + clears
    submitted_at marker."""

    def test_approve_flips_to_public_accepting(self, db_session, client):
        org, admin = _make_org_with_admin(db_session, "a1", "a1_admin")
        applicant = _make_user(db_session, "candidate")
        dp, _ = _make_pending_dp(db_session, org, applicant)

        resp = client.post(
            f"/api/orgs/{org.slug}/delegate-applications/{dp.id}/approve",
            headers=_auth(admin.id),
        )
        assert resp.status_code == 200, resp.text
        db_session.refresh(dp)
        assert dp.visibility == "public_accepting"
        assert dp.public_accepting_approved_at is not None


class TestApproveByProfileIdRejectsCrossOrg:
    """Approving a profile from a different org returns 404."""

    def test_cross_org_404(self, db_session, client):
        org1, admin1 = _make_org_with_admin(db_session, "co1", "co1_admin")
        org2, _ = _make_org_with_admin(db_session, "co2", "co2_admin")
        applicant = _make_user(db_session, "stranger")
        dp_in_org2, _ = _make_pending_dp(db_session, org2, applicant)

        resp = client.post(
            f"/api/orgs/{org1.slug}/delegate-applications/{dp_in_org2.id}/approve",
            headers=_auth(admin1.id),
        )
        assert resp.status_code == 404


class TestDenyByProfileIdRequiresComment:
    """Deny without a comment returns 422 (schema-level)."""

    def test_empty_comment_422(self, db_session, client):
        org, admin = _make_org_with_admin(db_session, "d1", "d1_admin")
        applicant = _make_user(db_session, "rej")
        dp, _ = _make_pending_dp(db_session, org, applicant)

        resp = client.post(
            f"/api/orgs/{org.slug}/delegate-applications/{dp.id}/deny",
            json={"comment": ""},
            headers=_auth(admin.id),
        )
        assert resp.status_code == 422


# ===========================================================================
# B4 — legacy endpoints removed
# ===========================================================================


class TestLegacyDelegateApplicationsEndpointGone:
    """Legacy GET /delegate-applications is no longer registered."""

    def test_returns_404_or_405(self, db_session, client):
        org, admin = _make_org_with_admin(db_session, "leg", "leg_admin")
        resp = client.get(
            f"/api/orgs/{org.slug}/delegate-applications",
            headers=_auth(admin.id),
        )
        # FastAPI returns 405 when path matches but method differs (the
        # new -pending variant is GET, the new -applications/{id}/approve
        # is POST, but plain /delegate-applications has no GET registration
        # post-Phase-30.1 B4). Either 404 or 405 is acceptable proof of
        # removal.
        assert resp.status_code in (404, 405)


# ===========================================================================
# B5 — Topic.name root-cause
# ===========================================================================


class TestTopicNameOrgScopedUniqueness:
    """Two topics with same name in different orgs are allowed; two in
    same org are rejected."""

    def test_same_name_different_orgs_ok(self, db_session):
        o1 = models.Organization(slug="rc1", name="RC1",
                                 description="", join_policy="open")
        o2 = models.Organization(slug="rc2", name="RC2",
                                 description="", join_policy="open")
        db_session.add_all([o1, o2]); db_session.flush()
        db_session.add_all([
            models.Topic(name="Budget", description="", color="#000000", org_id=o1.id),
            models.Topic(name="Budget", description="", color="#000000", org_id=o2.id),
        ])
        db_session.commit()
        assert db_session.query(models.Topic).filter_by(name="Budget").count() == 2

    def test_same_name_same_org_rejected(self, db_session):
        org = models.Organization(slug="rc3", name="RC3",
                                  description="", join_policy="open")
        db_session.add(org); db_session.flush()
        db_session.add(models.Topic(name="Budget", description="",
                                    color="#000000", org_id=org.id))
        db_session.commit()
        db_session.add(models.Topic(name="Budget", description="",
                                    color="#000000", org_id=org.id))
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()


class TestSeededTopicsHaveUnprefixedNames:
    """After seeding Cedar Hollow, topic names are clean (no
    'demo-cedar-hollow:' prefix)."""

    def test_topic_names_unprefixed(self, db_session):
        seed_org_from_bible(
            db_session,
            HOA_BIBLE,
            now=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db_session.commit()

        org = db_session.query(models.Organization).filter_by(
            slug="demo-cedar-hollow",
        ).first()
        topic_names = {
            t.name for t in db_session.query(models.Topic).filter_by(org_id=org.id)
        }
        assert "Budget" in topic_names
        assert "Pool & Recreation" in topic_names
        # Verify NONE of the names carry the legacy prefix.
        for name in topic_names:
            assert not name.startswith("demo-cedar-hollow:"), (
                f"Topic name {name!r} still has the legacy slug prefix — "
                f"Phase 30.1 B5 should have stripped it."
            )
