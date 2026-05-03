"""
Phase 8 — API tests for sustained-majority configuration, per-proposal
override, escalation resolution, and audit logging.

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
# Org-settings PATCH — sustained-majority keys + audit event
# ---------------------------------------------------------------------------

class TestOrgSettingsConfig:
    def test_patch_sustained_majority_keys_persists(self, db, client):
        admin = _user(db, "admin")
        org = _org(db)
        _membership(db, org, admin, role="admin")
        db.commit()

        new_settings = {
            "sustained_majority_enabled_default": True,
            "sustained_majority_threshold": 0.6,
            "sustained_majority_floor": 0.40,
            "sustained_majority_failure_mode": "escalate",
            "sustained_majority_per_proposal_override": False,
        }
        resp = client.patch(
            f"/api/orgs/{org.slug}",
            json={"settings": new_settings},
            headers=_auth(admin),
        )
        assert resp.status_code == 200
        body = resp.json()
        for k, v in new_settings.items():
            assert body["settings"][k] == v

        # Audit event fires once with all five changes captured.
        events = db.query(models.AuditLog).filter(
            models.AuditLog.action == "org.sustained_majority_config_changed",
        ).all()
        assert len(events) == 1
        changes = events[0].details["changes"]
        assert set(changes.keys()) == set(new_settings.keys())
        assert changes["sustained_majority_failure_mode"]["new"] == "escalate"

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
            models.AuditLog.action == "org.sustained_majority_config_changed",
        ).count()
        assert events == 0

    def test_no_op_patch_does_not_log(self, db, client):
        """Re-submitting the same value is not a change → no audit event."""
        admin = _user(db, "admin")
        org = _org(db, settings={
            "default_voting_days": 7,
            "sustained_majority_threshold": 0.55,
        })
        _membership(db, org, admin, role="admin")
        db.commit()

        resp = client.patch(
            f"/api/orgs/{org.slug}",
            json={"settings": {"sustained_majority_threshold": 0.55}},
            headers=_auth(admin),
        )
        assert resp.status_code == 200
        count = db.query(models.AuditLog).filter(
            models.AuditLog.action == "org.sustained_majority_config_changed",
        ).count()
        assert count == 0

    def test_settings_merge_persists_via_new_dict_pattern(self, db, client):
        """Phase 4 Cleanup Fix 1 pattern test — sustained-majority keys merge
        cleanly with existing settings rather than replacing them."""
        admin = _user(db, "admin")
        org = _org(db, settings={
            "default_voting_days": 7,
            "allow_public_delegates": True,
        })
        _membership(db, org, admin, role="admin")
        db.commit()

        client.patch(
            f"/api/orgs/{org.slug}",
            json={"settings": {"sustained_majority_floor": 0.40}},
            headers=_auth(admin),
        )

        db.expire_all()
        fresh = db.query(models.Organization).filter(
            models.Organization.slug == "test-org",
        ).first()
        # Original keys preserved + new key added — proves we used new-dict.
        assert fresh.settings["default_voting_days"] == 7
        assert fresh.settings["allow_public_delegates"] is True
        assert fresh.settings["sustained_majority_floor"] == 0.40


# ---------------------------------------------------------------------------
# Per-proposal override — accepted / rejected / inherits
# ---------------------------------------------------------------------------

class TestPerProposalOverride:
    def test_accepts_override_when_org_allows(self, db, client):
        admin = _user(db, "admin")
        org = _org(db, settings={
            "sustained_majority_per_proposal_override": True,
            "sustained_majority_enabled_default": False,
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
                "sustained_majority_enabled": True,
            },
            headers=_auth(admin),
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["sustained_majority_enabled"] is True

        # Audit: proposal.sustained_majority_enabled written.
        evt_count = db.query(models.AuditLog).filter(
            models.AuditLog.action == "proposal.sustained_majority_enabled",
        ).count()
        assert evt_count == 1

    def test_rejects_override_when_org_disallows(self, db, client):
        admin = _user(db, "admin")
        org = _org(db, settings={
            "sustained_majority_per_proposal_override": False,
            "sustained_majority_enabled_default": False,
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
                "sustained_majority_enabled": True,
            },
            headers=_auth(admin),
        )
        assert resp.status_code == 403
        assert "per-proposal" in resp.json()["detail"]

    def test_null_override_inherits_org_default_on_create(self, db, client):
        admin = _user(db, "admin")
        org = _org(db, settings={
            "sustained_majority_enabled_default": True,
            "sustained_majority_per_proposal_override": True,
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
        assert resp.json()["sustained_majority_enabled"] is None


# ---------------------------------------------------------------------------
# Escalation resolution endpoint
# ---------------------------------------------------------------------------

class TestEscalationResolution:
    def _make_unresolved_proposal(self, db: Session) -> tuple:
        admin = _user(db, "admin")
        author = _user(db, "author")
        org = _org(db, settings={"sustained_majority_failure_mode": "escalate"})
        _membership(db, org, admin, role="admin")
        _membership(db, org, author, role="member")
        topic = _topic(db, org)
        db.flush()

        proposal = models.Proposal(
            title="Stuck proposal",
            body="",
            author_id=author.id,
            org_id=org.id,
            voting_method="binary",
            status="unresolved",
            sustained_majority_enabled=True,
        )
        db.add(proposal)
        db.flush()
        db.commit()
        return admin, author, org, proposal

    def test_resolve_extend_returns_to_voting(self, db, client):
        admin, _, org, proposal = self._make_unresolved_proposal(db)
        resp = client.post(
            f"/api/orgs/{org.slug}/proposals/{proposal.id}/resolve_escalation",
            json={"action": "extend", "reason": "Need more time"},
            headers=_auth(admin),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "voting"

        # Two audit events: window_extended + escalation_resolved
        actions = {
            r.action
            for r in db.query(models.AuditLog).filter(
                models.AuditLog.target_id == proposal.id,
            ).all()
        }
        assert "proposal.window_extended" in actions
        assert "proposal.escalation_resolved" in actions

    def test_resolve_fail(self, db, client):
        admin, _, org, proposal = self._make_unresolved_proposal(db)
        resp = client.post(
            f"/api/orgs/{org.slug}/proposals/{proposal.id}/resolve_escalation",
            json={"action": "fail"},
            headers=_auth(admin),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "failed"

    def test_resolve_pass_override_audit_includes_reason(self, db, client):
        admin, _, org, proposal = self._make_unresolved_proposal(db)
        resp = client.post(
            f"/api/orgs/{org.slug}/proposals/{proposal.id}/resolve_escalation",
            json={"action": "pass", "reason": "Emergency override per board memo"},
            headers=_auth(admin),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "passed"

        evt = db.query(models.AuditLog).filter(
            models.AuditLog.action == "proposal.escalation_resolved",
            models.AuditLog.target_id == proposal.id,
        ).first()
        assert evt is not None
        assert evt.details["action"] == "pass"
        assert "Emergency override" in evt.details["reason"]

    def test_resolve_back_to_deliberation(self, db, client):
        admin, _, org, proposal = self._make_unresolved_proposal(db)
        resp = client.post(
            f"/api/orgs/{org.slug}/proposals/{proposal.id}/resolve_escalation",
            json={"action": "back_to_deliberation"},
            headers=_auth(admin),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "deliberation"

    def test_rejects_when_not_unresolved(self, db, client):
        admin = _user(db, "admin")
        org = _org(db)
        _membership(db, org, admin, role="admin")
        topic = _topic(db, org)
        proposal = models.Proposal(
            title="Active",
            body="",
            author_id=admin.id,
            org_id=org.id,
            voting_method="binary",
            status="voting",
        )
        db.add(proposal)
        db.flush()
        db.commit()

        resp = client.post(
            f"/api/orgs/{org.slug}/proposals/{proposal.id}/resolve_escalation",
            json={"action": "fail"},
            headers=_auth(admin),
        )
        assert resp.status_code == 400
        assert "unresolved" in resp.json()["detail"]

    def test_member_cannot_resolve(self, db, client):
        admin = _user(db, "admin")
        member = _user(db, "member")
        org = _org(db)
        _membership(db, org, admin, role="admin")
        _membership(db, org, member, role="member")
        proposal = models.Proposal(
            title="Stuck",
            body="",
            author_id=admin.id,
            org_id=org.id,
            voting_method="binary",
            status="unresolved",
        )
        db.add(proposal)
        db.flush()
        db.commit()

        resp = client.post(
            f"/api/orgs/{org.slug}/proposals/{proposal.id}/resolve_escalation",
            json={"action": "fail"},
            headers=_auth(member),
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# /results includes sustained_majority status
# ---------------------------------------------------------------------------

class TestResultsSustainedMajorityBlock:
    def test_inactive_when_neither_org_default_nor_override(self, db, client):
        admin = _user(db, "admin")
        org = _org(db)  # default settings: SM disabled
        _membership(db, org, admin, role="admin")
        proposal = models.Proposal(
            title="Plain", body="", author_id=admin.id, org_id=org.id,
            voting_method="binary", status="voting",
        )
        db.add(proposal)
        db.flush()
        db.commit()

        resp = client.get(f"/api/proposals/{proposal.id}/results")
        assert resp.status_code == 200
        sm = resp.json()["sustained_majority"]
        assert sm["active"] is False

    def test_active_with_floor_and_threshold_in_payload(self, db, client):
        admin = _user(db, "admin")
        org = _org(db, settings={
            "sustained_majority_enabled_default": True,
            "sustained_majority_threshold": 0.6,
            "sustained_majority_floor": 0.40,
        })
        _membership(db, org, admin, role="admin")
        proposal = models.Proposal(
            title="Active", body="", author_id=admin.id, org_id=org.id,
            voting_method="binary", status="voting",
        )
        db.add(proposal)
        db.flush()
        db.commit()

        resp = client.get(f"/api/proposals/{proposal.id}/results")
        assert resp.status_code == 200
        sm = resp.json()["sustained_majority"]
        assert sm["active"] is True
        assert sm["threshold"] == 0.6
        assert sm["floor"] == 0.40
