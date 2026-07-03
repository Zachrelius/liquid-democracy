"""Phase 87 — verify-email idempotency (C0) + org takedown (C1, B-10)."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from database import Base, get_db
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


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _user(db, username, *, is_admin=False, email_verified=False):
    u = models.User(
        username=username, display_name=username.title(), password_hash=_DUMMY_HASH,
        email=f"{username}@test.example", email_verified=email_verified, is_admin=is_admin,
    )
    db.add(u); db.flush(); return u


def _org(db, slug="acme", *, is_demo=False, discoverability="listed", **kw):
    o = models.Organization(
        name=slug.title(), slug=slug, description="", join_policy="open",
        discoverability=discoverability, is_demo=is_demo,
        settings={"default_voting_days": 7}, **kw,
    )
    db.add(o); db.flush(); return o


def _member(db, org, user, role="member"):
    return make_org_membership(db, user_id=user.id, org_id=org.id, role=role, status="active")


def _auth(user):
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


# ===========================================================================
# Cluster 0 — verify-email idempotency
# ===========================================================================

class TestVerifyEmailIdempotent:
    def _token(self, db, user, token="tok-1", *, expires_hours=24):
        ev = models.EmailVerification(
            user_id=user.id, email=user.email, token=token,
            expires_at=_now() + timedelta(hours=expires_hours),
        )
        db.add(ev); db.commit(); return ev

    def test_double_post_same_token(self, client, test_db):
        u = _user(test_db, "newbie", email_verified=False)
        self._token(test_db, u, "tok-1")

        r1 = client.post("/api/auth/verify-email", json={"token": "tok-1"})
        assert r1.status_code == 200, r1.text
        assert r1.json().get("already_verified") is False
        test_db.expire_all()
        assert test_db.get(models.User, u.id).email_verified is True

        # Second POST of the SAME (now-consumed) token → benign success.
        r2 = client.post("/api/auth/verify-email", json={"token": "tok-1"})
        assert r2.status_code == 200, r2.text
        assert r2.json().get("already_verified") is True

        # Only one verification audit event (no duplicate side effects).
        n = test_db.query(models.AuditLog).filter_by(action="user.email_verified").count()
        assert n == 1

    def test_invalid_token_unverified_user_errors(self, client, test_db):
        r = client.post("/api/auth/verify-email", json={"token": "does-not-exist"})
        assert r.status_code == 400, r.text

    def test_expired_token_but_user_already_verified_is_benign(self, client, test_db):
        u = _user(test_db, "verified", email_verified=True)
        self._token(test_db, u, "tok-exp", expires_hours=-1)  # already expired
        r = client.post("/api/auth/verify-email", json={"token": "tok-exp"})
        assert r.status_code == 200, r.text
        assert r.json().get("already_verified") is True


# ===========================================================================
# Cluster 1 — org takedown
# ===========================================================================

class TestOrgTakedown:
    def _admin(self, db):
        return _user(db, "platadmin", is_admin=True, email_verified=True)

    def test_restrict_delisted_sets_fields_and_audit(self, client, test_db):
        admin = self._admin(test_db)
        org = _org(test_db)
        test_db.commit()
        r = client.patch(f"/api/admin/orgs/{org.id}/restriction", headers=_auth(admin),
                         json={"restriction": "delisted", "reason": "spam org"})
        assert r.status_code == 200, r.text
        test_db.expire_all()
        o = test_db.get(models.Organization, org.id)
        assert o.platform_restriction == "delisted"
        assert o.restricted_by_id == admin.id
        assert o.restricted_at is not None
        assert o.restriction_reason == "spam org"
        # Stored discoverability untouched.
        assert o.discoverability == "listed"
        assert test_db.query(models.AuditLog).filter_by(action="org.restriction_set").first() is not None

    def test_reason_required_on_restrict(self, client, test_db):
        admin = self._admin(test_db)
        org = _org(test_db); test_db.commit()
        r = client.patch(f"/api/admin/orgs/{org.id}/restriction", headers=_auth(admin),
                         json={"restriction": "suspended"})
        assert r.status_code == 422, r.text
        test_db.expire_all()
        assert test_db.get(models.Organization, org.id).platform_restriction is None

    def test_demo_org_cannot_be_restricted(self, client, test_db):
        admin = self._admin(test_db)
        org = _org(test_db, slug="demo-org", is_demo=True); test_db.commit()
        r = client.patch(f"/api/admin/orgs/{org.id}/restriction", headers=_auth(admin),
                         json={"restriction": "delisted", "reason": "x"})
        assert r.status_code == 422, r.text
        test_db.expire_all()
        assert test_db.get(models.Organization, org.id).platform_restriction is None

    def test_delisted_excluded_from_explore(self, client, test_db):
        admin = self._admin(test_db)
        org = _org(test_db, slug="listed-org"); test_db.commit()
        # Present before.
        before = client.get("/api/orgs/explore").json()["orgs"]
        assert any(o["slug"] == "listed-org" for o in before)
        # Delist.
        client.patch(f"/api/admin/orgs/{org.id}/restriction", headers=_auth(admin),
                     json={"restriction": "delisted", "reason": "x"})
        after = client.get("/api/orgs/explore").json()["orgs"]
        assert not any(o["slug"] == "listed-org" for o in after)

    def test_delisted_public_landing_404(self, client, test_db):
        admin = self._admin(test_db)
        org = _org(test_db, slug="pub-org"); test_db.commit()
        assert client.get("/api/orgs/pub-org/public").status_code == 200
        client.patch(f"/api/admin/orgs/{org.id}/restriction", headers=_auth(admin),
                     json={"restriction": "delisted", "reason": "x"})
        assert client.get("/api/orgs/pub-org/public").status_code == 404
        # Stored discoverability unchanged.
        test_db.expire_all()
        assert test_db.get(models.Organization, org.id).discoverability == "listed"

    def test_suspended_member_api_rejected_rows_intact(self, client, test_db):
        admin = self._admin(test_db)
        org = _org(test_db, slug="susp-org")
        member = _user(test_db, "member", email_verified=True)
        _member(test_db, org, member)
        test_db.commit()
        # Member can read before.
        assert client.get("/api/orgs/susp-org", headers=_auth(member)).status_code == 200
        client.patch(f"/api/admin/orgs/{org.id}/restriction", headers=_auth(admin),
                     json={"restriction": "suspended", "reason": "abuse"})
        # Member now 404s.
        assert client.get("/api/orgs/susp-org", headers=_auth(member)).status_code == 404
        # Rows intact.
        test_db.expire_all()
        assert test_db.query(models.OrgMembership).filter_by(
            org_id=org.id, user_id=member.id).first() is not None
        assert test_db.get(models.Organization, org.id) is not None

    def test_suspended_platform_admin_still_sees_in_list(self, client, test_db):
        admin = self._admin(test_db)
        org = _org(test_db, slug="susp2")
        test_db.commit()
        client.patch(f"/api/admin/orgs/{org.id}/restriction", headers=_auth(admin),
                     json={"restriction": "suspended", "reason": "x"})
        rows = client.get("/api/admin/orgs", headers=_auth(admin)).json()
        row = next(o for o in rows if o["slug"] == "susp2")
        assert row["platform_restriction"] == "suspended"

    def test_revert_restores_public_posture(self, client, test_db):
        admin = self._admin(test_db)
        org = _org(test_db, slug="revert-org"); test_db.commit()
        client.patch(f"/api/admin/orgs/{org.id}/restriction", headers=_auth(admin),
                     json={"restriction": "delisted", "reason": "x"})
        assert not any(o["slug"] == "revert-org" for o in client.get("/api/orgs/explore").json()["orgs"])
        # Revert.
        r = client.patch(f"/api/admin/orgs/{org.id}/restriction", headers=_auth(admin),
                         json={"restriction": "none"})
        assert r.status_code == 200, r.text
        test_db.expire_all()
        o = test_db.get(models.Organization, org.id)
        assert o.platform_restriction is None
        assert o.restricted_at is None
        assert any(x["slug"] == "revert-org" for x in client.get("/api/orgs/explore").json()["orgs"])
        assert test_db.query(models.AuditLog).filter_by(action="org.restriction_reverted").first() is not None

    def test_non_admin_cannot_list_or_restrict(self, client, test_db):
        plain = _user(test_db, "plain", email_verified=True)
        org = _org(test_db); test_db.commit()
        assert client.get("/api/admin/orgs", headers=_auth(plain)).status_code == 403
        r = client.patch(f"/api/admin/orgs/{org.id}/restriction", headers=_auth(plain),
                         json={"restriction": "delisted", "reason": "x"})
        assert r.status_code == 403

    def test_orgout_surfaces_platform_restriction(self, client, test_db):
        admin = self._admin(test_db)
        org = _org(test_db, slug="pr-org")
        m = _user(test_db, "prmember", email_verified=True); _member(test_db, org, m)
        test_db.commit()
        client.patch(f"/api/admin/orgs/{org.id}/restriction", headers=_auth(admin),
                     json={"restriction": "delisted", "reason": "x"})
        # A member of a DELISTED org still has full API access (delist is
        # public-surface only) and sees the restriction on OrgOut.
        r = client.get("/api/orgs/pr-org", headers=_auth(m))
        assert r.status_code == 200, r.text
        assert r.json()["platform_restriction"] == "delisted"
