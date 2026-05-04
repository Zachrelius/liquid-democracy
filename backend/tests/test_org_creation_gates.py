"""
Phase 9.5 — Org-creation gate tests.

Covers POST /api/orgs gate behavior + the three new admin endpoints
(GET / PATCH /api/admin/platform-settings, PATCH
/api/admin/users/{id}/org-creation-limit).

Gate order (the frontend keys off both status and detail text):
  1. Platform mode kill switch (`platform_settings.org_creation_mode`) -> 403
  2. Email-verified -> 403
  3. Per-user cap (default 3, overridable via `users.org_creation_limit`) -> 403
  4. Platform-wide hourly rate limit (>=20 `org.created` audit events) -> 429

Reuses the in-memory SQLite + dependency-override pattern from Phase 8.5
Session 2's test_sub_org_routes.py.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from database import Base, get_db
from main import app
from tests.conftest import make_org_membership


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
# Helpers
# ---------------------------------------------------------------------------

def _user(
    db: Session,
    username: str,
    email_verified: bool = True,
    is_admin: bool = False,
    org_creation_limit: int | None = None,
) -> models.User:
    u = models.User(
        username=username,
        display_name=username.title(),
        password_hash=_DUMMY_HASH,
        email=f"{username}@test.example",
        email_verified=email_verified,
        is_admin=is_admin,
        org_creation_limit=org_creation_limit,
    )
    db.add(u)
    db.flush()
    return u


def _auth(user: models.User) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _own_org(db: Session, owner: models.User, slug: str) -> models.Organization:
    """Stamp an existing owned-org membership for cap-test fixtures.

    Bypasses POST /api/orgs so we can pre-seed the user's owned-org count
    without tripping any of the gates we're testing.
    """
    org = models.Organization(
        name=slug.title(),
        slug=slug,
        description="",
        join_policy="open",
        settings={},
    )
    db.add(org)
    db.flush()
    make_org_membership(
        db,
        user_id=owner.id, org_id=org.id, role="owner", status="active",
    )
    db.flush()
    return org


def _create_payload(slug: str = "new-org", name: str = "New Org") -> dict:
    return {
        "name": name,
        "slug": slug,
        "description": "",
        "join_policy": "open",
    }


def _set_platform_mode(db: Session, mode: str) -> None:
    row = db.get(models.PlatformSetting, "org_creation_mode")
    if row is None:
        row = models.PlatformSetting(key="org_creation_mode", value=mode)
        db.add(row)
    else:
        row.value = mode
    db.flush()


# ---------------------------------------------------------------------------
# Gate tests
# ---------------------------------------------------------------------------

class TestOrgCreationGates:
    def test_email_not_verified_rejects(self, db, client):
        u = _user(db, "alice", email_verified=False)
        db.commit()
        resp = client.post(
            "/api/orgs", json=_create_payload(), headers=_auth(u),
        )
        assert resp.status_code == 403
        assert "verify your email" in resp.json()["detail"].lower()

    def test_cap_at_default_limit_rejects(self, db, client):
        """User with 3 owned orgs cannot create a 4th (default cap = 3)."""
        u = _user(db, "alice", email_verified=True)
        _own_org(db, u, "one")
        _own_org(db, u, "two")
        _own_org(db, u, "three")
        db.commit()
        resp = client.post(
            "/api/orgs", json=_create_payload("four"), headers=_auth(u),
        )
        assert resp.status_code == 403
        assert "(3)" in resp.json()["detail"]
        assert "support@liquiddemocracy.us" in resp.json()["detail"]

    def test_cap_not_yet_reached_succeeds(self, db, client):
        """User with 2 owned orgs can still create their 3rd."""
        u = _user(db, "alice", email_verified=True)
        _own_org(db, u, "one")
        _own_org(db, u, "two")
        db.commit()
        resp = client.post(
            "/api/orgs", json=_create_payload("third"), headers=_auth(u),
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["slug"] == "third"

    def test_rate_limit_rejects(self, db, client):
        """When >=20 `org.created` audit events were logged in the past hour,
        return 429 even if the per-user cap permits."""
        u = _user(
            db, "alice", email_verified=True, org_creation_limit=100,
        )
        # Stamp 20 fresh org.created audit events so the rate-limit query
        # sees them as "recent."
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for i in range(20):
            db.add(models.AuditLog(
                action="org.created",
                target_type="organization",
                target_id=f"fake-{i}",
                actor_id=u.id,
                details={},
                timestamp=now - timedelta(minutes=5),
            ))
        db.commit()
        resp = client.post(
            "/api/orgs", json=_create_payload("blocked"), headers=_auth(u),
        )
        assert resp.status_code == 429
        assert "many organization-creation requests" in resp.json()["detail"]

    def test_kill_switch_rejects(self, db, client):
        """Platform-mode = approval_required -> 403, even for a verified user
        well under the per-user cap."""
        u = _user(db, "alice", email_verified=True)
        _set_platform_mode(db, "approval_required")
        db.commit()
        resp = client.post(
            "/api/orgs", json=_create_payload(), headers=_auth(u),
        )
        assert resp.status_code == 403
        assert "temporarily paused" in resp.json()["detail"]
        assert "support@liquiddemocracy.us" in resp.json()["detail"]

    def test_happy_path_regression(self, db, client):
        """Verified user, no orgs yet, mode=open -> 201 + audit row."""
        u = _user(db, "alice", email_verified=True)
        # Seed the platform_settings row mode=open (matches what the
        # migration would do on a real deploy).
        _set_platform_mode(db, "open")
        # Create an EmailVerification with verified_at so the audit
        # enrichment captures a real `creator_email_verified_age_seconds`.
        ev = models.EmailVerification(
            user_id=u.id,
            email=u.email,
            token="t" * 16,
            expires_at=datetime.now(timezone.utc).replace(tzinfo=None)
            + timedelta(days=1),
            verified_at=datetime.now(timezone.utc).replace(tzinfo=None)
            - timedelta(seconds=42),
        )
        db.add(ev)
        db.commit()

        resp = client.post(
            "/api/orgs",
            json=_create_payload("happy"),
            headers={**_auth(u), "User-Agent": "pytest-ua/1.0"},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["slug"] == "happy"
        # Phase 12 — preset role rename: 'owner' → 'steward'.
        assert body["user_role"] == "steward"

        # Audit enrichment present
        audit = db.query(models.AuditLog).filter(
            models.AuditLog.action == "org.created",
            models.AuditLog.target_id == body["id"],
        ).one()
        details = audit.details or {}
        assert details.get("name") == "New Org"
        assert details.get("slug") == "happy"
        # creator_email_verified_age_seconds should be a small positive int
        age = details.get("creator_email_verified_age_seconds")
        assert isinstance(age, int) and 0 <= age <= 600
        # Pre-insert hourly count (no prior org.created rows seeded) = 0
        assert details.get("platform_org_creation_hour_count") == 0
        assert details.get("creator_user_agent") == "pytest-ua/1.0"

    def test_per_user_cap_override_zero_immediately_bites(self, db, client):
        """org_creation_limit=0 caps the user before they own anything."""
        u = _user(
            db, "alice", email_verified=True, org_creation_limit=0,
        )
        db.commit()
        resp = client.post(
            "/api/orgs", json=_create_payload(), headers=_auth(u),
        )
        assert resp.status_code == 403
        assert "(0)" in resp.json()["detail"]

    def test_per_user_cap_override_none_uses_default(self, db, client):
        """org_creation_limit=None means 'use platform default of 3'.

        Verified by stamping 3 owned orgs and confirming the 4th rejects.
        """
        u = _user(
            db, "alice", email_verified=True, org_creation_limit=None,
        )
        _own_org(db, u, "alpha")
        _own_org(db, u, "beta")
        _own_org(db, u, "gamma")
        db.commit()
        resp = client.post(
            "/api/orgs", json=_create_payload("delta"), headers=_auth(u),
        )
        assert resp.status_code == 403
        assert "(3)" in resp.json()["detail"]

    def test_gate_order_email_before_cap(self, db, client):
        """A user whose count exceeds their limit AND lacks verified email
        sees the kill-switch / email message first per spec gate order."""
        # Mode=open default (no row), email_verified=False, limit=0 (cap reached).
        # Email gate runs first per spec, so the response should be the
        # email-not-verified message.
        u = _user(
            db, "alice", email_verified=False, org_creation_limit=0,
        )
        db.commit()
        resp = client.post(
            "/api/orgs", json=_create_payload(), headers=_auth(u),
        )
        assert resp.status_code == 403
        assert "verify your email" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Admin endpoint tests
# ---------------------------------------------------------------------------

class TestPlatformSettingsAdmin:
    def test_get_platform_settings_returns_seeded_keys(self, db, client):
        admin = _user(db, "admin", is_admin=True)
        # Seed the row the migration would create
        db.add(models.PlatformSetting(
            key="org_creation_mode", value="open",
        ))
        db.commit()
        resp = client.get(
            "/api/admin/platform-settings", headers=_auth(admin),
        )
        assert resp.status_code == 200
        assert resp.json() == {"org_creation_mode": "open"}

    def test_get_platform_settings_requires_admin(self, db, client):
        user = _user(db, "alice", is_admin=False)
        db.commit()
        resp = client.get(
            "/api/admin/platform-settings", headers=_auth(user),
        )
        assert resp.status_code == 403

    def test_patch_platform_settings_audited(self, db, client):
        admin = _user(db, "admin", is_admin=True)
        db.add(models.PlatformSetting(
            key="org_creation_mode", value="open",
        ))
        db.commit()
        resp = client.patch(
            "/api/admin/platform-settings",
            json={"key": "org_creation_mode", "value": "approval_required"},
            headers=_auth(admin),
        )
        assert resp.status_code == 200
        assert resp.json()["value"] == "approval_required"

        # Row updated
        row = db.get(models.PlatformSetting, "org_creation_mode")
        db.refresh(row)
        assert row.value == "approval_required"

        # Audit emitted
        audit = db.query(models.AuditLog).filter(
            models.AuditLog.action == "platform_settings.changed",
        ).one()
        assert audit.actor_id == admin.id
        assert audit.target_id == "org_creation_mode"
        assert audit.details == {
            "key": "org_creation_mode",
            "old_value": "open",
            "new_value": "approval_required",
        }

    def test_patch_platform_settings_creates_new_key(self, db, client):
        """PATCH creates the row when it doesn't exist (upsert)."""
        admin = _user(db, "admin", is_admin=True)
        db.commit()
        resp = client.patch(
            "/api/admin/platform-settings",
            json={"key": "experimental_flag", "value": True},
            headers=_auth(admin),
        )
        assert resp.status_code == 200
        row = db.get(models.PlatformSetting, "experimental_flag")
        assert row is not None and row.value is True

    def test_patch_user_org_creation_limit_audited(self, db, client):
        admin = _user(db, "admin", is_admin=True)
        target = _user(db, "alice", org_creation_limit=None)
        db.commit()
        resp = client.patch(
            f"/api/admin/users/{target.id}/org-creation-limit",
            json={"limit": 25},
            headers=_auth(admin),
        )
        assert resp.status_code == 200

        db.refresh(target)
        assert target.org_creation_limit == 25

        audit = db.query(models.AuditLog).filter(
            models.AuditLog.action == "user.org_creation_limit_changed",
        ).one()
        assert audit.actor_id == admin.id
        assert audit.target_id == target.id
        assert audit.details == {
            "target_user_id": target.id,
            "old_value": None,
            "new_value": 25,
        }

    def test_patch_user_org_creation_limit_clear_via_null(self, db, client):
        admin = _user(db, "admin", is_admin=True)
        target = _user(db, "alice", org_creation_limit=10)
        db.commit()
        resp = client.patch(
            f"/api/admin/users/{target.id}/org-creation-limit",
            json={"limit": None},
            headers=_auth(admin),
        )
        assert resp.status_code == 200
        db.refresh(target)
        assert target.org_creation_limit is None
