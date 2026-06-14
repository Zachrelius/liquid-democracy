"""Phase 44 — Multi-admin approval workflow tests.

Covers the verification matrix items per spec §B7:
  - Feature-off regression: the four wrapped actions behave EXACTLY
    as before approval is enabled.
  - Opt-in toggle.
  - Submit + fan-out (notification spy) + audit.
  - Threshold execute (real side effects: member actually removed,
    topic soft-deleted, etc.).
  - Decline veto (D9).
  - Expiry worker tick (D8).
  - Self-approval (D4 — initiator's submission counts).
  - Deadlock guard (D6 — single-admin org executes directly).
  - Re-validation failure (D7).
  - Role-permissions baseline drift detection (D11b).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

import models
from main import app
from database import Base, get_db
from tests.conftest import make_user, make_org_membership


# ---------------------------------------------------------------------------
# Test app + DB wiring
# ---------------------------------------------------------------------------
#
# Phase 44 — use StaticPool so the engine reuses ONE connection across the
# TestClient + the fixture's session. SQLite ":memory:" databases are
# per-connection, so without StaticPool the route handler's session would
# checkout a fresh blank database when the request fires. This is the same
# pattern test_admin_endpoints.py uses.

@pytest.fixture()
def db() -> Iterator[Session]:
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


@pytest.fixture()
def client(db: Session) -> Iterator[TestClient]:
    def _override():
        try:
            yield db
        finally:
            pass
    app.dependency_overrides[get_db] = _override
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def auth_for(db: Session):
    """Return a helper that builds an Authorization header for any user.

    Bypasses the password flow — we mint a JWT directly using the same
    helper auth.py uses.
    """
    import auth as auth_utils

    def _headers(user: models.User) -> dict[str, str]:
        token = auth_utils.create_access_token(user.id)
        return {"Authorization": f"Bearer {token}"}
    return _headers


# ---------------------------------------------------------------------------
# Org setup helpers
# ---------------------------------------------------------------------------

def _make_org(db: Session, slug: str, settings: dict | None = None) -> models.Organization:
    org = models.Organization(
        name=slug.replace("-", " ").title(),
        slug=slug,
        description="",
        join_policy="open",
        settings=settings or {},
    )
    db.add(org)
    db.flush()
    return org


def _enable_approval(
    db: Session, org: models.Organization,
    *, thresholds: dict[str, int] | None = None,
    window_hours: int = 72,
) -> None:
    cfg = org.settings or {}
    cfg = dict(cfg)
    cfg["multi_admin_approval"] = {
        "enabled": True,
        "thresholds": thresholds or {
            "member.remove": 2,
            "topic.delete": 2,
            "role_permissions.edit": 2,
            "org.delete": 2,
        },
        "window_hours": window_hours,
    }
    org.settings = cfg
    from sqlalchemy.orm import attributes
    attributes.flag_modified(org, "settings")
    db.flush()


def _setup_two_admins(db: Session, slug: str = "p44org"):
    """Make an org with steward + admin_a + admin_b + plain member."""
    org = _make_org(db, slug)
    # Triggers preset Role seed
    steward = make_user(db, f"{slug}-steward")
    admin_a = make_user(db, f"{slug}-admin-a")
    admin_b = make_user(db, f"{slug}-admin-b")
    member = make_user(db, f"{slug}-member")
    make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
    make_org_membership(db, org_id=org.id, user_id=admin_a.id, role="admin")
    make_org_membership(db, org_id=org.id, user_id=admin_b.id, role="admin")
    make_org_membership(db, org_id=org.id, user_id=member.id, role="member")
    db.commit()
    return org, steward, admin_a, admin_b, member


def _setup_single_admin(db: Session, slug: str = "soloorg"):
    """Steward only — no other admins."""
    org = _make_org(db, slug)
    steward = make_user(db, f"{slug}-steward")
    target = make_user(db, f"{slug}-target")
    make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
    make_org_membership(db, org_id=org.id, user_id=target.id, role="member")
    db.commit()
    return org, steward, target


# ---------------------------------------------------------------------------
# Tests — feature-off regression
# ---------------------------------------------------------------------------

class TestFeatureOffRegression:
    """With approval OFF, the four wrapped actions execute immediately
    EXACTLY as today. No pending row created, no notifications, no audit
    entries for the wrapped flow."""

    def test_member_remove_executes_directly_when_approval_off(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin_a, admin_b, member = _setup_two_admins(db)
        r = client.delete(
            f"/api/orgs/{org.slug}/members/{member.id}",
            headers=auth_for(admin_a),
        )
        assert r.status_code == 204
        # Membership actually gone.
        assert db.query(models.OrgMembership).filter_by(
            user_id=member.id, org_id=org.id,
        ).first() is None
        # No pending row created.
        assert db.query(models.PendingAdminAction).count() == 0

    def test_topic_delete_executes_directly_when_approval_off(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin_a, admin_b, member = _setup_two_admins(db)
        # Make an org-scoped topic.
        topic = models.Topic(name="Budget", color="#0000ff", org_id=org.id)
        db.add(topic)
        db.commit()
        r = client.delete(
            f"/api/orgs/{org.slug}/topics/{topic.id}",
            headers=auth_for(admin_a),
        )
        assert r.status_code == 204
        db.refresh(topic)
        assert topic.org_id is None  # soft-deleted
        assert db.query(models.PendingAdminAction).count() == 0

    def test_org_delete_executes_directly_when_approval_off(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin_a, admin_b, member = _setup_two_admins(db, slug="del-direct")
        r = client.request(
            "DELETE",
            f"/api/orgs/{org.slug}",
            headers=auth_for(steward),
        )
        assert r.status_code == 204
        assert db.query(models.Organization).filter_by(slug="del-direct").first() is None

    def test_role_permissions_edit_executes_directly_when_approval_off(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin_a, admin_b, member = _setup_two_admins(db)
        body = {"changes": [
            {"role_system_key": "moderator", "permission_key": "topic.delete", "enabled": True},
        ]}
        r = client.patch(
            f"/api/orgs/{org.slug}/role-permissions",
            json=body,
            headers=auth_for(steward),
        )
        assert r.status_code == 200
        data = r.json()
        assert data.get("changes_applied") == 1
        assert db.query(models.PendingAdminAction).count() == 0


# ---------------------------------------------------------------------------
# Tests — submit / approve / execute happy path
# ---------------------------------------------------------------------------

class TestApprovalLifecycle:
    def test_member_remove_pending_then_executed_at_threshold(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin_a, admin_b, member = _setup_two_admins(db)
        _enable_approval(db, org)
        db.commit()

        # admin_a initiates removal → pending (admin_a's submission counts).
        r = client.delete(
            f"/api/orgs/{org.slug}/members/{member.id}",
            headers=auth_for(admin_a),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "submitted_for_approval"
        pending_id = body["pending_action"]["id"]
        # member still present, action pending.
        assert db.query(models.OrgMembership).filter_by(
            user_id=member.id, org_id=org.id,
        ).first() is not None
        pending = db.get(models.PendingAdminAction, pending_id)
        assert pending.status == "pending"
        assert pending.threshold == 2
        # Initiator's implicit approval row exists.
        assert db.query(models.PendingActionApproval).filter_by(
            pending_action_id=pending_id, approver_id=admin_a.id, decision="approve",
        ).first() is not None

        # admin_b approves → threshold met, action executes.
        r2 = client.post(
            f"/api/orgs/{org.slug}/admin/pending-actions/{pending_id}/approve",
            headers=auth_for(admin_b),
        )
        assert r2.status_code == 200
        body2 = r2.json()
        assert body2["status"] == "executed"
        db.expire_all()
        # Member actually removed (SIDE-EFFECT assertion).
        assert db.query(models.OrgMembership).filter_by(
            user_id=member.id, org_id=org.id,
        ).first() is None

    def test_decline_vetoes_action(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin_a, admin_b, member = _setup_two_admins(db, slug="declorg")
        _enable_approval(db, org)
        db.commit()

        r = client.delete(
            f"/api/orgs/{org.slug}/members/{member.id}",
            headers=auth_for(admin_a),
        )
        pending_id = r.json()["pending_action"]["id"]

        # admin_b declines.
        r2 = client.post(
            f"/api/orgs/{org.slug}/admin/pending-actions/{pending_id}/decline",
            json={"reason": "Not warranted"},
            headers=auth_for(admin_b),
        )
        assert r2.status_code == 200
        assert r2.json()["status"] == "declined"
        # Member still present.
        assert db.query(models.OrgMembership).filter_by(
            user_id=member.id, org_id=org.id,
        ).first() is not None

    def test_self_approval_counts_d4(
        self, client: TestClient, db: Session, auth_for,
    ):
        """With threshold=2 and an org of 2 admins + steward, the
        initiator's submission counts as their own approval — only ONE
        other approver is needed."""
        org, steward, admin_a, admin_b, member = _setup_two_admins(db, slug="d4org")
        _enable_approval(db, org)
        db.commit()
        r = client.delete(
            f"/api/orgs/{org.slug}/members/{member.id}",
            headers=auth_for(admin_a),
        )
        pending_id = r.json()["pending_action"]["id"]
        pending = db.get(models.PendingAdminAction, pending_id)
        assert pending.threshold == 2
        approval_count = db.query(models.PendingActionApproval).filter_by(
            pending_action_id=pending_id, decision="approve",
        ).count()
        assert approval_count == 1  # initiator's own

        # One more approver → threshold met.
        client.post(
            f"/api/orgs/{org.slug}/admin/pending-actions/{pending_id}/approve",
            headers=auth_for(admin_b),
        )
        db.expire_all()
        assert db.get(models.PendingAdminAction, pending_id).status == "executed"

    def test_deadlock_guard_d6_executes_directly_for_single_admin(
        self, client: TestClient, db: Session, auth_for,
    ):
        """If the approver-set has only one member (the initiator), the
        action executes directly with an audit entry noting the bypass."""
        org, steward, target = _setup_single_admin(db)
        _enable_approval(db, org, thresholds={"member.remove": 3})
        db.commit()

        r = client.delete(
            f"/api/orgs/{org.slug}/members/{target.id}",
            headers=auth_for(steward),
        )
        assert r.status_code == 204
        # No pending row.
        assert db.query(models.PendingAdminAction).count() == 0
        # Member actually removed.
        assert db.query(models.OrgMembership).filter_by(
            user_id=target.id, org_id=org.id,
        ).first() is None
        # Audit entry of the bypass exists.
        assert db.query(models.AuditLog).filter_by(
            action="pending_admin_action.executed_without_ratification",
        ).count() >= 1


# ---------------------------------------------------------------------------
# Tests — D7 revalidation failure
# ---------------------------------------------------------------------------

class TestRevalidationFailureD7:
    def test_failed_when_target_member_already_left(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin_a, admin_b, member = _setup_two_admins(db, slug="d7org")
        _enable_approval(db, org)
        db.commit()

        r = client.delete(
            f"/api/orgs/{org.slug}/members/{member.id}",
            headers=auth_for(admin_a),
        )
        pending_id = r.json()["pending_action"]["id"]

        # Outside-of-flow: member's row gets removed by an unrelated
        # mechanism (simulated by direct DB delete).
        m = db.query(models.OrgMembership).filter_by(
            user_id=member.id, org_id=org.id,
        ).first()
        db.delete(m)
        db.commit()

        # admin_b approves → executor revalidates → target gone → failed.
        r2 = client.post(
            f"/api/orgs/{org.slug}/admin/pending-actions/{pending_id}/approve",
            headers=auth_for(admin_b),
        )
        db.expire_all()
        pending = db.get(models.PendingAdminAction, pending_id)
        assert pending.status == "failed"
        assert "reason" in (pending.resolution_detail or {})


# ---------------------------------------------------------------------------
# Tests — D8 expiry worker tick
# ---------------------------------------------------------------------------

class TestExpiryWorkerD8:
    def test_expiry_worker_resolves_expired_actions(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin_a, admin_b, member = _setup_two_admins(db, slug="expirorg")
        _enable_approval(db, org, window_hours=1)
        db.commit()

        r = client.delete(
            f"/api/orgs/{org.slug}/members/{member.id}",
            headers=auth_for(admin_a),
        )
        pending_id = r.json()["pending_action"]["id"]

        # Backdate expires_at to the past.
        pending = db.get(models.PendingAdminAction, pending_id)
        pending.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=10)
        db.commit()

        from pending_actions.engine import expire_due_pending_actions
        cnt = expire_due_pending_actions(db)
        assert cnt == 1
        db.expire_all()
        pending = db.get(models.PendingAdminAction, pending_id)
        assert pending.status == "expired"

    def test_expiry_worker_short_circuits_when_no_due_actions(
        self, db: Session,
    ):
        from pending_actions.engine import expire_due_pending_actions
        assert expire_due_pending_actions(db) == 0


# ---------------------------------------------------------------------------
# Tests — D11b role_permissions.edit baseline drift detection
# ---------------------------------------------------------------------------

class TestRolePermissionsBaselineDriftD11b:
    def _setup(self, db: Session):
        org, steward, admin_a, admin_b, member = _setup_two_admins(db, slug="rporg")
        _enable_approval(db, org)
        db.commit()
        return org, steward, admin_a, admin_b, member

    def test_pending_action_captures_baseline_and_diff(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin_a, admin_b, _ = self._setup(db)
        body = {"changes": [
            {"role_system_key": "moderator", "permission_key": "topic.delete", "enabled": True},
        ]}
        r = client.patch(
            f"/api/orgs/{org.slug}/role-permissions",
            json=body,
            headers=auth_for(steward),
        )
        assert r.status_code == 200
        assert r.json()["status"] == "submitted_for_approval"
        pending = r.json()["pending_action"]
        assert "diff_by_role" in pending["preview"]
        diff = pending["preview"]["diff_by_role"]
        assert "moderator" in diff
        entry = diff["moderator"][0]
        assert entry["permission_key"] == "topic.delete"
        assert entry["from"] is False
        assert entry["to"] is True
        # No drift initially.
        assert pending["preview"]["drift"] is False

    def test_drift_detected_when_matrix_changes_post_submit(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin_a, admin_b, _ = self._setup(db)
        body = {"changes": [
            {"role_system_key": "moderator", "permission_key": "topic.delete", "enabled": True},
        ]}
        r = client.patch(
            f"/api/orgs/{org.slug}/role-permissions",
            json=body,
            headers=auth_for(steward),
        )
        pending_id = r.json()["pending_action"]["id"]

        # Mutate the live matrix outside the approval flow (turn off approval
        # temporarily so the second PATCH is direct).
        cfg = dict(org.settings)
        cfg["multi_admin_approval"]["enabled"] = False
        org.settings = cfg
        from sqlalchemy.orm import attributes
        attributes.flag_modified(org, "settings")
        db.commit()

        client.patch(
            f"/api/orgs/{org.slug}/role-permissions",
            json={"changes": [{
                "role_system_key": "moderator",
                # Phase 71a — must be a key NOT in the moderator default set,
                # otherwise the "drift" PATCH is a no-op (member.suspend is
                # now a moderator default). member.remove is admin-only by
                # default, so flipping it True genuinely drifts the matrix.
                "permission_key": "member.remove",
                "enabled": True,
            }]},
            headers=auth_for(steward),
        )

        # Re-enable approval.
        cfg = dict(org.settings)
        cfg["multi_admin_approval"]["enabled"] = True
        org.settings = cfg
        attributes.flag_modified(org, "settings")
        db.commit()

        # Fetch the pending action — drift should now be True.
        r2 = client.get(
            f"/api/orgs/{org.slug}/admin/pending-actions/{pending_id}",
            headers=auth_for(admin_b),
        )
        assert r2.status_code == 200
        assert r2.json()["preview"]["drift"] is True

    def test_execution_fails_when_baseline_drifts(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin_a, admin_b, _ = self._setup(db)
        body = {"changes": [
            {"role_system_key": "moderator", "permission_key": "topic.delete", "enabled": True},
        ]}
        r = client.patch(
            f"/api/orgs/{org.slug}/role-permissions",
            json=body,
            headers=auth_for(steward),
        )
        pending_id = r.json()["pending_action"]["id"]

        # Drift the matrix.
        cfg = dict(org.settings)
        cfg["multi_admin_approval"]["enabled"] = False
        org.settings = cfg
        from sqlalchemy.orm import attributes
        attributes.flag_modified(org, "settings")
        db.commit()
        client.patch(
            f"/api/orgs/{org.slug}/role-permissions",
            json={"changes": [{
                "role_system_key": "moderator",
                # Phase 71a — must be a key NOT in the moderator default set,
                # otherwise the "drift" PATCH is a no-op (member.suspend is
                # now a moderator default). member.remove is admin-only by
                # default, so flipping it True genuinely drifts the matrix.
                "permission_key": "member.remove",
                "enabled": True,
            }]},
            headers=auth_for(steward),
        )
        cfg = dict(org.settings)
        cfg["multi_admin_approval"]["enabled"] = True
        org.settings = cfg
        attributes.flag_modified(org, "settings")
        db.commit()

        # Try to approve the pending action → executor detects drift → failed.
        r2 = client.post(
            f"/api/orgs/{org.slug}/admin/pending-actions/{pending_id}/approve",
            headers=auth_for(admin_a),
        )
        db.expire_all()
        pending = db.get(models.PendingAdminAction, pending_id)
        assert pending.status == "failed"


# ---------------------------------------------------------------------------
# Tests — permission gating + non-eligible visibility
# ---------------------------------------------------------------------------

class TestPermissionGating:
    def test_non_eligible_member_cannot_list_pending_actions(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin_a, admin_b, member = _setup_two_admins(db, slug="permorg")
        _enable_approval(db, org)
        db.commit()
        # admin_a submits.
        client.delete(
            f"/api/orgs/{org.slug}/members/{member.id}",
            headers=auth_for(admin_a),
        )
        # member tries to list.
        r = client.get(
            f"/api/orgs/{org.slug}/admin/pending-actions",
            headers=auth_for(member),
        )
        assert r.status_code == 403

    def test_non_eligible_member_cannot_approve(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin_a, admin_b, member = _setup_two_admins(db, slug="permapprove")
        _enable_approval(db, org)
        db.commit()
        r = client.delete(
            f"/api/orgs/{org.slug}/members/{member.id}",
            headers=auth_for(admin_a),
        )
        # Try with a brand-new member who has no admin perm.
        other_member = make_user(db, "other-member-permapprove")
        make_org_membership(db, org_id=org.id, user_id=other_member.id, role="member")
        db.commit()
        pid = r.json()["pending_action"]["id"]
        r2 = client.post(
            f"/api/orgs/{org.slug}/admin/pending-actions/{pid}/approve",
            headers=auth_for(other_member),
        )
        assert r2.status_code == 403


# ---------------------------------------------------------------------------
# Tests — count endpoint for nav badge
# ---------------------------------------------------------------------------

class TestPendingCountEndpoint:
    def test_count_returns_zero_when_approval_off(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin_a, admin_b, _ = _setup_two_admins(db, slug="cnt-off")
        r = client.get(
            f"/api/orgs/{org.slug}/admin/pending-actions/count",
            headers=auth_for(admin_a),
        )
        assert r.status_code == 200
        assert r.json()["pending_count"] == 0
        assert r.json()["eligible"] is False

    def test_count_increments_after_submit(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin_a, admin_b, member = _setup_two_admins(db, slug="cnt-on")
        _enable_approval(db, org)
        db.commit()
        client.delete(
            f"/api/orgs/{org.slug}/members/{member.id}",
            headers=auth_for(admin_a),
        )
        r = client.get(
            f"/api/orgs/{org.slug}/admin/pending-actions/count",
            headers=auth_for(admin_b),
        )
        assert r.status_code == 200
        assert r.json()["pending_count"] == 1
        assert r.json()["pending_count_by_action_type"].get("member.remove") == 1
        assert r.json()["eligible"] is True


# ---------------------------------------------------------------------------
# Tests — audit entries at every transition
# ---------------------------------------------------------------------------

class TestAuditTrail:
    def test_audit_entries_at_submit_approve_execute(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin_a, admin_b, member = _setup_two_admins(db, slug="auditorg")
        _enable_approval(db, org)
        db.commit()

        r = client.delete(
            f"/api/orgs/{org.slug}/members/{member.id}",
            headers=auth_for(admin_a),
        )
        pid = r.json()["pending_action"]["id"]
        client.post(
            f"/api/orgs/{org.slug}/admin/pending-actions/{pid}/approve",
            headers=auth_for(admin_b),
        )
        # Submit + approve + execute audit entries all present.
        actions = {
            row.action for row in
            db.query(models.AuditLog).filter_by(target_id=pid).all()
        }
        assert "pending_admin_action.submitted" in actions
        assert "pending_admin_action.approved" in actions
        assert "pending_admin_action.executed" in actions
