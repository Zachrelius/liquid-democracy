"""
Phase 8 / Phase 20 — API tests for Stable Result Required configuration,
per-proposal override, and the /results status payload.

Mirrors the org/proposal lifecycle test fixtures so we exercise the actual
FastAPI route handlers (not just the helpers).
"""

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


def _org(db: Session, settings: dict | None = None) -> models.Organization:
    org = models.Organization(
        name="Test Org",
        slug="test-org",
        description="",
        join_policy="open",
        settings=settings or {"default_voting_days": 7},
    )
    db.add(org)
    db.flush()
    return org


def _membership(db: Session, org, user, role="member"):
    m = make_org_membership(
        db,
        user_id=user.id, org_id=org.id, role=role, status="active",
    )
    return m


def _topic(db: Session, org) -> models.Topic:
    t = models.Topic(name="Climate", description="", color="#0f0", org_id=org.id)
    db.add(t)
    db.flush()
    return t


def _auth(user: models.User) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


# ---------------------------------------------------------------------------
# Org-settings PATCH — Stable Result Required keys + audit event
# ---------------------------------------------------------------------------

class TestOrgSettingsConfig:
    def test_patch_stable_result_keys_persists(self, db, client):
        admin = _user(db, "admin")
        org = _org(db)
        _membership(db, org, admin, role="admin")
        db.commit()

        new_settings = {
            "stable_result_enabled_default": True,
            "stable_window_fraction": 0.10,
            "max_extension_fraction": 0.50,
            "stable_result_per_proposal_override": False,
        }
        resp = client.patch(
            f"/api/orgs/{org.slug}",
            json={"settings": new_settings},
            headers=_auth(admin),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        for k, v in new_settings.items():
            assert body["settings"][k] == v

        # Audit event fires once with all four changes captured.
        events = db.query(models.AuditLog).filter(
            models.AuditLog.action == "org.stable_result_config_changed",
        ).all()
        assert len(events) == 1
        changes = events[0].details["changes"]
        assert set(changes.keys()) == set(new_settings.keys())
        assert changes["stable_window_fraction"]["new"] == 0.10
        assert changes["max_extension_fraction"]["new"] == 0.50

    def test_no_audit_event_when_only_unrelated_settings_changed(self, db, client):
        admin = _user(db, "admin")
        org = _org(db)
        _membership(db, org, admin, role="admin")
        db.commit()

        resp = client.patch(
            f"/api/orgs/{org.slug}",
            json={"settings": {"default_voting_days": 14}},
            headers=_auth(admin),
        )
        assert resp.status_code == 200
        events = db.query(models.AuditLog).filter(
            models.AuditLog.action == "org.stable_result_config_changed",
        ).count()
        assert events == 0

    def test_no_op_patch_does_not_log(self, db, client):
        """Re-submitting the same value is not a change → no audit event."""
        admin = _user(db, "admin")
        org = _org(db, settings={
            "default_voting_days": 7,
            "stable_window_fraction": 0.30,
        })
        _membership(db, org, admin, role="admin")
        db.commit()

        resp = client.patch(
            f"/api/orgs/{org.slug}",
            json={"settings": {"stable_window_fraction": 0.30}},
            headers=_auth(admin),
        )
        assert resp.status_code == 200
        count = db.query(models.AuditLog).filter(
            models.AuditLog.action == "org.stable_result_config_changed",
        ).count()
        assert count == 0

    def test_settings_merge_persists_via_new_dict_pattern(self, db, client):
        """Verify the org-update merge pattern: the new key lands alongside
        existing keys without clobbering them."""
        admin = _user(db, "admin")
        org = _org(db, settings={
            "default_voting_days": 7,
            "allow_public_delegates": True,
        })
        _membership(db, org, admin, role="admin")
        db.commit()

        client.patch(
            f"/api/orgs/{org.slug}",
            json={"settings": {"max_extension_fraction": 0.50}},
            headers=_auth(admin),
        )

        db.expire_all()
        fresh = db.query(models.Organization).filter(
            models.Organization.slug == "test-org",
        ).first()
        assert fresh.settings["default_voting_days"] == 7
        assert fresh.settings["allow_public_delegates"] is True
        assert fresh.settings["max_extension_fraction"] == 0.50

    def test_old_sustained_majority_keys_in_settings_silently_ignored(self, db, client):
        """D13: legacy keys present in the settings JSON are silently ignored
        by get_stable_result_config — no error, no value migration."""
        admin = _user(db, "admin")
        org = _org(db, settings={
            "sustained_majority_floor": 0.40,
            "sustained_majority_failure_mode": "extend",
            "sustained_majority_threshold": 0.6,
        })
        _membership(db, org, admin, role="admin")
        db.commit()

        # Org config helper should not raise on these keys.
        from sustained_majority import get_stable_result_config
        config = get_stable_result_config(org)
        # Defaults applied (legacy keys ignored).
        assert config.stable_window_fraction == 0.25
        assert config.max_extension_fraction == 0.25


# ---------------------------------------------------------------------------
# Per-proposal override — accepted / rejected / inherits
# ---------------------------------------------------------------------------

class TestPerProposalOverride:
    def test_accepts_override_when_org_allows(self, db, client):
        admin = _user(db, "admin")
        org = _org(db, settings={
            "stable_result_per_proposal_override": True,
            "stable_result_enabled_default": False,
        })
        _membership(db, org, admin, role="admin")
        topic = _topic(db, org)
        db.commit()

        resp = client.post(
            f"/api/orgs/{org.slug}/proposals",
            json={
                "title": "Binding fee schedule",
                "body": "test",
                "topics": [topic.id],
                "voting_method": "binary",
                "stable_result_required": True,
            },
            headers=_auth(admin),
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["stable_result_required"] is True

        # Audit: proposal.stable_result_required_enabled written.
        evt_count = db.query(models.AuditLog).filter(
            models.AuditLog.action == "proposal.stable_result_required_enabled",
        ).count()
        assert evt_count == 1

    def test_rejects_override_when_org_disallows(self, db, client):
        admin = _user(db, "admin")
        org = _org(db, settings={
            "stable_result_per_proposal_override": False,
            "stable_result_enabled_default": False,
        })
        _membership(db, org, admin, role="admin")
        topic = _topic(db, org)
        db.commit()

        resp = client.post(
            f"/api/orgs/{org.slug}/proposals",
            json={
                "title": "Disallowed override",
                "topics": [topic.id],
                "voting_method": "binary",
                "stable_result_required": True,
            },
            headers=_auth(admin),
        )
        assert resp.status_code == 403
        assert "per-proposal" in resp.json()["detail"].lower()

    def test_null_override_inherits_org_default_on_create(self, db, client):
        admin = _user(db, "admin")
        org = _org(db, settings={
            "stable_result_enabled_default": True,
            "stable_result_per_proposal_override": True,
        })
        _membership(db, org, admin, role="admin")
        topic = _topic(db, org)
        db.commit()

        resp = client.post(
            f"/api/orgs/{org.slug}/proposals",
            json={
                "title": "Inherits org default",
                "topics": [topic.id],
                "voting_method": "binary",
            },
            headers=_auth(admin),
        )
        assert resp.status_code == 201
        # null on the column means "inherit". The actual active state is
        # resolved at evaluation time.
        assert resp.json()["stable_result_required"] is None


# ---------------------------------------------------------------------------
# /results includes the StableResultStatus block
# ---------------------------------------------------------------------------

class TestResultsStableResultBlock:
    def test_inactive_when_neither_org_default_nor_override(self, db, client):
        admin = _user(db, "admin")
        org = _org(db)  # default settings: feature disabled
        _membership(db, org, admin, role="admin")
        proposal = models.Proposal(
            title="Plain", body="", author_id=admin.id, org_id=org.id,
            voting_method="binary", status="voting",
            pass_threshold=0.5, quorum_threshold=0.4,
        )
        db.add(proposal)
        db.flush()
        db.commit()

        resp = client.get(f"/api/proposals/{proposal.id}/results")
        assert resp.status_code == 200
        sm = resp.json()["sustained_majority"]
        assert sm["active"] is False
        # Even when inactive the org's config snapshot is exposed at defaults.
        assert sm["stable_window_fraction"] == 0.25
        assert sm["max_extension_fraction"] == 0.25

    def test_active_emits_new_shape(self, db, client):
        from datetime import datetime, timezone, timedelta
        admin = _user(db, "admin")
        org = _org(db, settings={
            "stable_result_enabled_default": True,
            "stable_window_fraction": 0.20,
            "max_extension_fraction": 0.50,
        })
        _membership(db, org, admin, role="admin")
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        proposal = models.Proposal(
            title="Active", body="", author_id=admin.id, org_id=org.id,
            voting_method="binary", status="voting",
            pass_threshold=0.5, quorum_threshold=0.4,
            voting_start=now - timedelta(hours=2),
            voting_end=now + timedelta(hours=4),
        )
        db.add(proposal)
        db.flush()
        db.commit()

        resp = client.get(f"/api/proposals/{proposal.id}/results")
        assert resp.status_code == 200
        sm = resp.json()["sustained_majority"]
        assert sm["active"] is True
        assert sm["stable_window_fraction"] == 0.20
        assert sm["max_extension_fraction"] == 0.50
        # Budget = original_duration_seconds * 0.50; for a fresh proposal
        # with no extensions, used = 0, remaining = total.
        assert sm["extension_budget_used_seconds"] == 0
        assert sm["extension_budget_total_seconds"] > 0
        assert sm["extension_budget_remaining_seconds"] == \
            sm["extension_budget_total_seconds"]
        assert sm["in_extension"] is False
        assert sm["extension_count"] == 0
        # No legacy fields surfaced.
        assert "floor_breached" not in sm
        assert "approaching_floor" not in sm
        assert "distance_to_floor" not in sm
        assert "failure_mode" not in sm
        # New fields surfaced.
        assert "stable_window_starts_at" in sm
        assert "in_stable_window" in sm
        assert "in_extension" in sm
