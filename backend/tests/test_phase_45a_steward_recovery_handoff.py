"""Phase 45a — Steward recovery + voluntary handoff tests.

Spec: phase45a_steward_recovery_handoff_spec.md.
Covers B5's verification matrix items:

  - Active steward un-removable (regression — the relaxation is
    inactive-only, D4).
  - Inactive steward removable by single admin on a non-opted-in org
    (B1, the live latent-bug fix from the recon's GAP-2).
  - Inactive-steward removal blocked when no successor named (B2/D3).
  - Successor promoted atomically in the same transaction (B2).
  - Transfer endpoint happy path: outgoing → admin, target → steward
    (B3/D1).
  - Transfer rejects non-member / non-active / self targets.
  - Transfer rejects when caller is not the Steward.
  - At-least-one-steward invariant holds after every mutating path
    (D3).
  - Phase 44 path defers correctly when multi-admin approval is on
    and the successor field round-trips through ratification (B4/D2).
  - Audit events: ``steward.removed_while_inactive`` +
    ``org.stewardship_transferred``.
"""
from __future__ import annotations

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
# Test app + DB wiring (same StaticPool pattern as Phase 44 + admin tests)
# ---------------------------------------------------------------------------

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
    import auth as auth_utils

    def _headers(user: models.User) -> dict[str, str]:
        token = auth_utils.create_access_token(user.id)
        return {"Authorization": f"Bearer {token}"}
    return _headers


# ---------------------------------------------------------------------------
# Setup helpers
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
    cfg = dict(org.settings or {})
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


def _steward_role_id(db: Session, org_id: str) -> str:
    return (
        db.query(models.Role)
        .filter(models.Role.org_id == org_id, models.Role.system_key == "steward")
        .first()
        .id
    )


def _admin_role_id(db: Session, org_id: str) -> str:
    return (
        db.query(models.Role)
        .filter(models.Role.org_id == org_id, models.Role.system_key == "admin")
        .first()
        .id
    )


def _set_user_inactive(db: Session, user: models.User) -> None:
    user.is_active = False
    db.flush()


def _count_active_stewards(db: Session, org_id: str) -> int:
    rows = (
        db.query(models.OrgMembership)
        .filter(
            models.OrgMembership.org_id == org_id,
            models.OrgMembership.status == "active",
        )
        .all()
    )
    n = 0
    for m in rows:
        if m.role_id is None:
            continue
        role = db.get(models.Role, m.role_id)
        if role is not None and role.system_key == "steward":
            n += 1
    return n


def _setup_basic_org(db: Session, slug: str = "p45org"):
    """Org with steward + admin + member. Approval OFF by default."""
    org = _make_org(db, slug)
    steward = make_user(db, f"{slug}-steward")
    admin = make_user(db, f"{slug}-admin")
    member = make_user(db, f"{slug}-member")
    make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
    make_org_membership(db, org_id=org.id, user_id=admin.id, role="admin")
    make_org_membership(db, org_id=org.id, user_id=member.id, role="member")
    db.commit()
    return org, steward, admin, member


def _setup_two_admins(db: Session, slug: str = "p45twoadmin"):
    """Org with steward + two admins + a member (Phase 44 ratification
    needs ≥2 eligible approvers for member.remove)."""
    org = _make_org(db, slug)
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


# ===========================================================================
# B1 + D4 — active vs inactive steward removal
# ===========================================================================

class TestActiveStewardRegression:
    """The Phase 45a relaxation is inactive-only. An active steward must
    be exactly as protected after this pass as before."""

    def test_active_steward_cannot_be_removed_via_direct_path(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, member = _setup_basic_org(db)
        assert steward.is_active is True
        r = client.delete(
            f"/api/orgs/{org.slug}/members/{steward.id}",
            headers=auth_for(admin),
        )
        assert r.status_code == 400
        assert "Steward" in r.json()["detail"]
        # Steward membership still present.
        assert db.query(models.OrgMembership).filter_by(
            user_id=steward.id, org_id=org.id,
        ).first() is not None

    def test_active_steward_cannot_be_role_changed(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, member = _setup_basic_org(db)
        r = client.patch(
            f"/api/orgs/{org.slug}/members/{steward.id}",
            headers=auth_for(admin),
            json={"role": "admin"},
        )
        assert r.status_code == 400
        assert "Steward" in r.json()["detail"]

    def test_active_steward_cannot_be_suspended(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, member = _setup_basic_org(db)
        r = client.post(
            f"/api/orgs/{org.slug}/members/{steward.id}/suspend",
            headers=auth_for(admin),
        )
        assert r.status_code == 400
        assert "Steward" in r.json()["detail"]


# ===========================================================================
# B1 + B2 — inactive-steward recovery removal (direct path, no approval)
# ===========================================================================

class TestInactiveStewardRecovery:
    """Per D2 (single-admin default when org has not opted into Phase 44
    multi-admin approval) and D3 (at-least-one-steward invariant
    enforced via successor requirement)."""

    def test_inactive_steward_removal_blocked_without_successor(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, member = _setup_basic_org(db)
        _set_user_inactive(db, steward)
        db.commit()
        r = client.delete(
            f"/api/orgs/{org.slug}/members/{steward.id}",
            headers=auth_for(admin),
        )
        assert r.status_code == 400
        assert "successor" in r.json()["detail"].lower()
        # Steward STILL there — the invariant held.
        assert db.query(models.OrgMembership).filter_by(
            user_id=steward.id, org_id=org.id,
        ).first() is not None
        assert _count_active_stewards(db, org.id) == 1

    def test_inactive_steward_removable_with_successor_atomic_promotion(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, member = _setup_basic_org(db)
        _set_user_inactive(db, steward)
        db.commit()
        # Acting admin claims stewardship as the successor.
        r = client.request(
            "DELETE",
            f"/api/orgs/{org.slug}/members/{steward.id}",
            headers=auth_for(admin),
            json={"successor_user_id": admin.id},
        )
        assert r.status_code == 204, r.text
        db.expire_all()
        # Side effect 1: prior steward's membership gone.
        assert db.query(models.OrgMembership).filter_by(
            user_id=steward.id, org_id=org.id,
        ).first() is None
        # Side effect 2: successor (admin) is now Steward.
        successor_membership = db.query(models.OrgMembership).filter_by(
            user_id=admin.id, org_id=org.id,
        ).first()
        assert successor_membership is not None
        new_role = db.get(models.Role, successor_membership.role_id)
        assert new_role.system_key == "steward"
        # Invariant held: exactly one steward throughout.
        assert _count_active_stewards(db, org.id) == 1

    def test_inactive_steward_removal_with_successor_promotes_member(
        self, client: TestClient, db: Session, auth_for,
    ):
        """Acting admin can name a plain Member as the successor instead
        of claiming stewardship themselves."""
        org, steward, admin, member = _setup_basic_org(db)
        _set_user_inactive(db, steward)
        db.commit()
        r = client.request(
            "DELETE",
            f"/api/orgs/{org.slug}/members/{steward.id}",
            headers=auth_for(admin),
            json={"successor_user_id": member.id},
        )
        assert r.status_code == 204
        db.expire_all()
        # Member is now Steward.
        m_membership = db.query(models.OrgMembership).filter_by(
            user_id=member.id, org_id=org.id,
        ).first()
        new_role = db.get(models.Role, m_membership.role_id)
        assert new_role.system_key == "steward"
        assert _count_active_stewards(db, org.id) == 1

    def test_inactive_steward_removal_emits_recovery_audit(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, member = _setup_basic_org(db)
        _set_user_inactive(db, steward)
        db.commit()
        r = client.request(
            "DELETE",
            f"/api/orgs/{org.slug}/members/{steward.id}",
            headers=auth_for(admin),
            json={"successor_user_id": admin.id},
        )
        assert r.status_code == 204
        audit = (
            db.query(models.AuditLog)
            .filter(models.AuditLog.action == "steward.removed_while_inactive")
            .all()
        )
        assert len(audit) == 1
        details = audit[0].details
        assert details["removed_user_id"] == steward.id
        assert details["successor_user_id"] == admin.id
        assert details["had_other_stewards"] is False

    def test_inactive_steward_removal_with_nonactive_successor_rejected(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, member = _setup_basic_org(db)
        _set_user_inactive(db, steward)
        # Member's account is also inactive — invalid successor.
        _set_user_inactive(db, member)
        db.commit()
        r = client.request(
            "DELETE",
            f"/api/orgs/{org.slug}/members/{steward.id}",
            headers=auth_for(admin),
            json={"successor_user_id": member.id},
        )
        assert r.status_code == 400
        assert "active" in r.json()["detail"].lower()
        # Steward still in place.
        assert _count_active_stewards(db, org.id) == 1

    def test_inactive_steward_removal_with_self_as_successor_rejected(
        self, client: TestClient, db: Session, auth_for,
    ):
        """successor cannot be the user being removed."""
        org, steward, admin, member = _setup_basic_org(db)
        _set_user_inactive(db, steward)
        db.commit()
        r = client.request(
            "DELETE",
            f"/api/orgs/{org.slug}/members/{steward.id}",
            headers=auth_for(admin),
            json={"successor_user_id": steward.id},
        )
        assert r.status_code == 400
        assert _count_active_stewards(db, org.id) == 1


# ===========================================================================
# B3 — voluntary transfer
# ===========================================================================

class TestTransferStewardship:
    """Steward-initiated atomic swap (D1)."""

    def test_steward_can_transfer_to_active_member(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, member = _setup_basic_org(db)
        r = client.post(
            f"/api/orgs/{org.slug}/transfer-stewardship",
            headers=auth_for(steward),
            json={"target_user_id": member.id},
        )
        assert r.status_code == 200, r.text
        db.expire_all()
        # Outgoing → admin
        outgoing = db.query(models.OrgMembership).filter_by(
            user_id=steward.id, org_id=org.id,
        ).first()
        outgoing_role = db.get(models.Role, outgoing.role_id)
        assert outgoing_role.system_key == "admin"
        # Incoming → steward
        incoming = db.query(models.OrgMembership).filter_by(
            user_id=member.id, org_id=org.id,
        ).first()
        incoming_role = db.get(models.Role, incoming.role_id)
        assert incoming_role.system_key == "steward"
        # Invariant: still exactly one steward.
        assert _count_active_stewards(db, org.id) == 1

    def test_transfer_emits_audit(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, member = _setup_basic_org(db)
        r = client.post(
            f"/api/orgs/{org.slug}/transfer-stewardship",
            headers=auth_for(steward),
            json={"target_user_id": admin.id},
        )
        assert r.status_code == 200
        audit = (
            db.query(models.AuditLog)
            .filter(models.AuditLog.action == "org.stewardship_transferred")
            .all()
        )
        assert len(audit) == 1
        d = audit[0].details
        assert d["outgoing_steward_id"] == steward.id
        assert d["incoming_steward_id"] == admin.id

    def test_admin_cannot_initiate_transfer(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, member = _setup_basic_org(db)
        r = client.post(
            f"/api/orgs/{org.slug}/transfer-stewardship",
            headers=auth_for(admin),
            json={"target_user_id": member.id},
        )
        assert r.status_code == 403

    def test_transfer_rejects_non_member_target(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, member = _setup_basic_org(db)
        outsider = make_user(db, "outsider")
        db.commit()
        r = client.post(
            f"/api/orgs/{org.slug}/transfer-stewardship",
            headers=auth_for(steward),
            json={"target_user_id": outsider.id},
        )
        assert r.status_code == 400
        assert "active member" in r.json()["detail"].lower()
        assert _count_active_stewards(db, org.id) == 1

    def test_transfer_rejects_inactive_target(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, member = _setup_basic_org(db)
        _set_user_inactive(db, member)
        db.commit()
        r = client.post(
            f"/api/orgs/{org.slug}/transfer-stewardship",
            headers=auth_for(steward),
            json={"target_user_id": member.id},
        )
        assert r.status_code == 400
        assert _count_active_stewards(db, org.id) == 1

    def test_transfer_rejects_self(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, member = _setup_basic_org(db)
        r = client.post(
            f"/api/orgs/{org.slug}/transfer-stewardship",
            headers=auth_for(steward),
            json={"target_user_id": steward.id},
        )
        assert r.status_code == 400


# ===========================================================================
# B4 — Phase 44 integration (recovery path through ratification queue)
# ===========================================================================

class TestPhase44RecoveryPath:
    """When the org opted into multi-admin approval and member.remove is
    wrapped, inactive-steward removal routes through the PendingAdminAction
    queue, carrying ``successor_user_id`` through to ratified execution."""

    def test_inactive_steward_removal_defers_when_approval_enabled(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin_a, admin_b, member = _setup_two_admins(db)
        _enable_approval(db, org, thresholds={"member.remove": 2})
        _set_user_inactive(db, steward)
        db.commit()

        r = client.request(
            "DELETE",
            f"/api/orgs/{org.slug}/members/{steward.id}",
            headers=auth_for(admin_a),
            json={"successor_user_id": admin_a.id},
        )
        # Submitted for approval, not executed yet (threshold=2,
        # initiator's implicit approval = 1 of 2).
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "submitted_for_approval"
        pending_id = body["pending_action"]["id"]
        # Side effect: steward STILL there.
        assert db.query(models.OrgMembership).filter_by(
            user_id=steward.id, org_id=org.id,
        ).first() is not None

        # The successor field round-tripped into the persisted payload.
        pending = db.get(models.PendingAdminAction, pending_id)
        assert pending.payload.get("successor_user_id") == admin_a.id

        # Second admin approves → threshold met → executes.
        r2 = client.post(
            f"/api/orgs/{org.slug}/admin/pending-actions/{pending_id}/approve",
            headers=auth_for(admin_b),
        )
        assert r2.status_code == 200, r2.text
        db.expire_all()
        # Side effect: now prior steward gone + admin_a is steward.
        assert db.query(models.OrgMembership).filter_by(
            user_id=steward.id, org_id=org.id,
        ).first() is None
        admin_a_membership = db.query(models.OrgMembership).filter_by(
            user_id=admin_a.id, org_id=org.id,
        ).first()
        admin_a_role = db.get(models.Role, admin_a_membership.role_id)
        assert admin_a_role.system_key == "steward"
        assert _count_active_stewards(db, org.id) == 1

    def test_phase44_path_blocks_active_steward_removal_at_submit(
        self, client: TestClient, db: Session, auth_for,
    ):
        """The Phase 44 validator must also enforce that active stewards
        are not removable. The relaxation is inactive-only on every path."""
        org, steward, admin_a, admin_b, member = _setup_two_admins(db)
        _enable_approval(db, org, thresholds={"member.remove": 2})
        # Steward is still active.
        db.commit()
        r = client.request(
            "DELETE",
            f"/api/orgs/{org.slug}/members/{steward.id}",
            headers=auth_for(admin_a),
            json={"successor_user_id": admin_a.id},
        )
        assert r.status_code == 400
        assert "Steward" in r.json()["detail"]
        # No pending row created.
        assert db.query(models.PendingAdminAction).count() == 0


# ===========================================================================
# Cross-cutting invariant assertion
# ===========================================================================

class TestAtLeastOneStewardInvariant:
    """After every mutating path that could change steward count, the
    default-path invariant must still hold: exactly one steward exists."""

    def test_invariant_after_successful_transfer(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, member = _setup_basic_org(db)
        client.post(
            f"/api/orgs/{org.slug}/transfer-stewardship",
            headers=auth_for(steward),
            json={"target_user_id": admin.id},
        )
        db.expire_all()
        assert _count_active_stewards(db, org.id) == 1

    def test_invariant_after_recovery_removal(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, member = _setup_basic_org(db)
        _set_user_inactive(db, steward)
        db.commit()
        client.request(
            "DELETE",
            f"/api/orgs/{org.slug}/members/{steward.id}",
            headers=auth_for(admin),
            json={"successor_user_id": admin.id},
        )
        db.expire_all()
        assert _count_active_stewards(db, org.id) == 1
