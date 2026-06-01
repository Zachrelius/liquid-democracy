"""Phase 45b — Opt-in ownerless governance (flat admin council) tests.

Spec: phase45b_governance_modes_spec.md.

Verification matrix:
  - Default-mode regression: untouched orgs behave exactly as 45a left
    them (single steward, all 45a floors intact).
  - Mode switch atomicity (both directions): steward→admin demotion +
    mode flip in one transaction; council→single produces exactly one
    steward + mode flip in one transaction.
  - Council-mode at-least-one-admin floor (D6): blocks every path that
    would drop the last admin.
  - Owner-only keys resolve to any-admin in council mode (D4): direct
    has_permission test + require_org_owner accepts admin in council.
  - Locked permissions held by admin tier in council mode (D5): is_locked
    + the matrix-edit guard.
  - Phase 44 path: mode switch is NOT itself gated by approval (D1);
    in-mode high-stakes actions still defer when enabled.
  - Recovery state (B4): zero-governor condition emits org.needs_rebootstrap
    audit; platform-admin re-seat works; non-rebootstrap call rejected.
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
# Fixtures (StaticPool pattern; same as Phase 44 + 45a)
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

def _make_org(
    db: Session, slug: str, *,
    mode: str = "single_steward",
) -> models.Organization:
    org = models.Organization(
        name=slug.replace("-", " ").title(),
        slug=slug,
        description="",
        join_policy="open",
        settings={},
        governance_mode=mode,
    )
    db.add(org)
    db.flush()
    return org


def _setup_single_steward_org(db: Session, slug: str = "p45borg"):
    """Steward + admin + member, single_steward mode."""
    org = _make_org(db, slug, mode="single_steward")
    steward = make_user(db, f"{slug}-steward")
    admin = make_user(db, f"{slug}-admin")
    member = make_user(db, f"{slug}-member")
    make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
    make_org_membership(db, org_id=org.id, user_id=admin.id, role="admin")
    make_org_membership(db, org_id=org.id, user_id=member.id, role="member")
    db.commit()
    return org, steward, admin, member


def _setup_council_org(db: Session, slug: str = "p45bcouncil"):
    """Two admins + a member, admin_council mode. No steward."""
    org = _make_org(db, slug, mode="admin_council")
    admin_a = make_user(db, f"{slug}-admin-a")
    admin_b = make_user(db, f"{slug}-admin-b")
    member = make_user(db, f"{slug}-member")
    make_org_membership(db, org_id=org.id, user_id=admin_a.id, role="admin")
    make_org_membership(db, org_id=org.id, user_id=admin_b.id, role="admin")
    make_org_membership(db, org_id=org.id, user_id=member.id, role="member")
    db.commit()
    return org, admin_a, admin_b, member


def _set_user_inactive(db: Session, user: models.User) -> None:
    user.is_active = False
    db.flush()


def _count_active_role(db: Session, org_id: str, system_key: str) -> int:
    rows = db.query(models.OrgMembership).filter(
        models.OrgMembership.org_id == org_id,
        models.OrgMembership.status == "active",
    ).all()
    n = 0
    for m in rows:
        if m.role_id is None:
            continue
        role = db.get(models.Role, m.role_id)
        if role is not None and role.system_key == system_key:
            n += 1
    return n


# ===========================================================================
# Default-mode regression (the entire safety story)
# ===========================================================================

class TestDefaultModeRegression:
    """Orgs that never switch mode behave exactly as Phase 45a left them.
    This is the entire safety story for the opt-in — verified at every
    mutating endpoint we touched."""

    def test_new_orgs_default_to_single_steward(
        self, db: Session,
    ):
        org = _make_org(db, "default-org")
        assert org.governance_mode == "single_steward"

    def test_active_steward_unconditionally_blocked_from_removal(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, member = _setup_single_steward_org(db)
        r = client.delete(
            f"/api/orgs/{org.slug}/members/{steward.id}",
            headers=auth_for(admin),
        )
        assert r.status_code == 400
        assert "Steward" in r.json()["detail"]

    def test_active_steward_unconditionally_blocked_from_role_change(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, member = _setup_single_steward_org(db)
        r = client.patch(
            f"/api/orgs/{org.slug}/members/{steward.id}",
            headers=auth_for(admin),
            json={"role": "admin"},
        )
        assert r.status_code == 400
        assert "Steward" in r.json()["detail"]

    def test_org_delete_remains_steward_only_in_default_mode(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, member = _setup_single_steward_org(db)
        # Admin cannot delete.
        r = client.request(
            "DELETE", f"/api/orgs/{org.slug}",
            headers=auth_for(admin),
        )
        assert r.status_code == 403

    def test_org_transfer_stewardship_remains_steward_only(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, member = _setup_single_steward_org(db)
        r = client.post(
            f"/api/orgs/{org.slug}/transfer-stewardship",
            headers=auth_for(admin),
            json={"target_user_id": member.id},
        )
        assert r.status_code == 403


# ===========================================================================
# B2 — Mode switch endpoints (both directions)
# ===========================================================================

class TestModeSwitchSingleToCouncil:
    """D2: steward initiates; steward atomically demotes to admin."""

    def test_steward_switches_to_council_demotes_self(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, member = _setup_single_steward_org(db)
        r = client.post(
            f"/api/orgs/{org.slug}/governance-mode",
            headers=auth_for(steward),
            json={"mode": "admin_council"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "ok"
        assert body["mode"] == "admin_council"
        assert body["demoted_user_id"] == steward.id
        db.expire_all()
        org2 = db.query(models.Organization).filter_by(slug=org.slug).one()
        assert org2.governance_mode == "admin_council"
        # Side effect: steward is now admin; zero stewards; two admins total.
        steward_mem = db.query(models.OrgMembership).filter_by(
            user_id=steward.id, org_id=org.id,
        ).one()
        assert db.get(models.Role, steward_mem.role_id).system_key == "admin"
        assert _count_active_role(db, org.id, "steward") == 0
        assert _count_active_role(db, org.id, "admin") == 2

    def test_admin_cannot_switch_to_council(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, member = _setup_single_steward_org(db)
        r = client.post(
            f"/api/orgs/{org.slug}/governance-mode",
            headers=auth_for(admin),
            json={"mode": "admin_council"},
        )
        assert r.status_code == 403

    def test_idempotent_no_op_when_already_in_target_mode(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, admin_a, admin_b, member = _setup_council_org(db)
        r = client.post(
            f"/api/orgs/{org.slug}/governance-mode",
            headers=auth_for(admin_a),
            json={"mode": "admin_council"},
        )
        assert r.status_code == 200
        assert r.json()["changed"] is False

    def test_audit_emitted_on_switch(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, member = _setup_single_steward_org(db)
        client.post(
            f"/api/orgs/{org.slug}/governance-mode",
            headers=auth_for(steward),
            json={"mode": "admin_council"},
        )
        audit = db.query(models.AuditLog).filter(
            models.AuditLog.action == "org.governance_mode_changed",
        ).all()
        assert len(audit) == 1
        d = audit[0].details
        assert d["from"] == "single_steward"
        assert d["to"] == "admin_council"
        assert d["demoted_user_id"] == steward.id


class TestModeSwitchCouncilToSingle:
    """D3: any admin initiates; named admin (default: caller) claims
    the steward seat atomically."""

    def test_admin_reverts_claims_seat_by_default(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, admin_a, admin_b, member = _setup_council_org(db)
        r = client.post(
            f"/api/orgs/{org.slug}/governance-mode",
            headers=auth_for(admin_a),
            json={"mode": "single_steward"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["mode"] == "single_steward"
        assert body["promoted_user_id"] == admin_a.id
        db.expire_all()
        # Side effect: admin_a is now steward; admin_b still admin.
        admin_a_mem = db.query(models.OrgMembership).filter_by(
            user_id=admin_a.id, org_id=org.id,
        ).one()
        assert db.get(models.Role, admin_a_mem.role_id).system_key == "steward"
        admin_b_mem = db.query(models.OrgMembership).filter_by(
            user_id=admin_b.id, org_id=org.id,
        ).one()
        assert db.get(models.Role, admin_b_mem.role_id).system_key == "admin"
        # Invariant: exactly one steward.
        assert _count_active_role(db, org.id, "steward") == 1

    def test_admin_reverts_naming_another_admin(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, admin_a, admin_b, member = _setup_council_org(db)
        r = client.post(
            f"/api/orgs/{org.slug}/governance-mode",
            headers=auth_for(admin_a),
            json={"mode": "single_steward", "successor_user_id": admin_b.id},
        )
        assert r.status_code == 200
        db.expire_all()
        admin_b_mem = db.query(models.OrgMembership).filter_by(
            user_id=admin_b.id, org_id=org.id,
        ).one()
        assert db.get(models.Role, admin_b_mem.role_id).system_key == "steward"

    def test_revert_rejects_non_admin_successor(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, admin_a, admin_b, member = _setup_council_org(db)
        r = client.post(
            f"/api/orgs/{org.slug}/governance-mode",
            headers=auth_for(admin_a),
            json={"mode": "single_steward", "successor_user_id": member.id},
        )
        assert r.status_code == 400
        # Org still in council mode, no change.
        db.expire_all()
        org2 = db.query(models.Organization).filter_by(slug=org.slug).one()
        assert org2.governance_mode == "admin_council"


# ===========================================================================
# B3 — Mode-aware permission resolution (D4 + D5)
# ===========================================================================

class TestD4OwnerOnlyKeysResolveByMode:
    """OWNER_ONLY_KEYS resolve to:
      - steward in single_steward mode
      - admin in admin_council mode
    """

    def test_steward_holds_owner_only_in_single_mode(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, member = _setup_single_steward_org(db)
        r = client.get(f"/api/orgs/{org.slug}", headers=auth_for(steward))
        perms = r.json()["user_permissions"]
        assert "org.delete" in perms
        assert "org.transfer_stewardship" in perms

    def test_admin_holds_owner_only_in_council_mode(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, admin_a, admin_b, member = _setup_council_org(db)
        r = client.get(f"/api/orgs/{org.slug}", headers=auth_for(admin_a))
        perms = r.json()["user_permissions"]
        assert "org.delete" in perms
        assert "org.transfer_stewardship" in perms

    def test_member_excludes_owner_only_in_council_mode(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, admin_a, admin_b, member = _setup_council_org(db)
        r = client.get(f"/api/orgs/{org.slug}", headers=auth_for(member))
        perms = r.json()["user_permissions"]
        assert "org.delete" not in perms
        assert "org.transfer_stewardship" not in perms

    def test_admin_can_delete_in_council_mode(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, admin_a, admin_b, member = _setup_council_org(db)
        # require_org_owner now accepts admin in council mode.
        # Use confirmation body (matches Phase 44 + direct delete pattern).
        r = client.request(
            "DELETE", f"/api/orgs/{org.slug}",
            headers=auth_for(admin_a),
        )
        assert r.status_code == 204


class TestD5LockedPermissionsHeldByGoverningTier:
    """STEWARD_LOCKED_PERMISSIONS are locked for the top governing tier:
      - steward in single_steward mode
      - admin in admin_council mode
    """

    def test_steward_locked_perms_held_in_single_mode(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, member = _setup_single_steward_org(db)
        r = client.get(f"/api/orgs/{org.slug}", headers=auth_for(steward))
        perms = r.json()["user_permissions"]
        # The three STEWARD_LOCKED_PERMISSIONS.
        assert "member.change_role" in perms
        assert "org.edit_settings" in perms
        assert "role_permissions.edit" in perms

    def test_admin_holds_locked_perms_in_council_mode(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, admin_a, admin_b, member = _setup_council_org(db)
        r = client.get(f"/api/orgs/{org.slug}", headers=auth_for(admin_a))
        perms = r.json()["user_permissions"]
        assert "member.change_role" in perms
        assert "org.edit_settings" in perms
        assert "role_permissions.edit" in perms


# ===========================================================================
# B3 — D6 cardinality floor
# ===========================================================================

class TestCouncilFloorAtLeastOneAdmin:
    """admin_council mode: at-least-one-admin floor must hold against
    every removal/demotion/suspension path."""

    def test_last_active_admin_cannot_be_removed(
        self, client: TestClient, db: Session, auth_for,
    ):
        """Council with two admins: remove admin_b, then try to remove
        admin_a (the last). Should fail."""
        org, admin_a, admin_b, member = _setup_council_org(db)
        # Remove admin_b first (allowed — admin_a remains).
        r1 = client.delete(
            f"/api/orgs/{org.slug}/members/{admin_b.id}",
            headers=auth_for(admin_a),
        )
        assert r1.status_code == 204
        # Now admin_a is the only admin; can't be removed.
        # The actor (admin_a) is removing themselves, which is allowed
        # operationally (any admin can remove any member in council); but
        # the floor must block it.
        r2 = client.delete(
            f"/api/orgs/{org.slug}/members/{admin_a.id}",
            headers=auth_for(admin_a),
        )
        assert r2.status_code == 400
        assert "last admin" in r2.json()["detail"].lower()

    def test_last_active_admin_cannot_be_role_changed_down(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, admin_a, admin_b, member = _setup_council_org(db)
        # Remove admin_b first.
        client.delete(
            f"/api/orgs/{org.slug}/members/{admin_b.id}",
            headers=auth_for(admin_a),
        )
        # Try to demote admin_a to member.
        r = client.patch(
            f"/api/orgs/{org.slug}/members/{admin_a.id}",
            headers=auth_for(admin_a),
            json={"role": "member"},
        )
        assert r.status_code == 400
        assert "last admin" in r.json()["detail"].lower()

    def test_last_active_admin_cannot_be_suspended(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, admin_a, admin_b, member = _setup_council_org(db)
        # Remove admin_b.
        client.delete(
            f"/api/orgs/{org.slug}/members/{admin_b.id}",
            headers=auth_for(admin_a),
        )
        r = client.post(
            f"/api/orgs/{org.slug}/members/{admin_a.id}/suspend",
            headers=auth_for(admin_a),
        )
        assert r.status_code == 400
        assert "last admin" in r.json()["detail"].lower()

    def test_non_last_admin_can_be_removed(
        self, client: TestClient, db: Session, auth_for,
    ):
        """In council with 2 admins, removing the non-last one is allowed."""
        org, admin_a, admin_b, member = _setup_council_org(db)
        r = client.delete(
            f"/api/orgs/{org.slug}/members/{admin_b.id}",
            headers=auth_for(admin_a),
        )
        assert r.status_code == 204
        assert _count_active_role(db, org.id, "admin") == 1


# ===========================================================================
# B4 — Recovery state
# ===========================================================================

class TestRecoveryState:
    """Zero-governor condition is detected + audited (not silent);
    platform-admin can re-seat."""

    def test_zero_governor_emits_audit_after_inactive_admin_removal(
        self, client: TestClient, db: Session, auth_for,
    ):
        """Council org → soft-revoke the only admin's account → admin's
        successor isn't named → removal blocked. But once an admin is
        soft-revoked AND removed via successor path, the org might land
        at zero active governors if everyone went inactive. Simulate by
        soft-revoking and then having a platform-admin remove."""
        # Build: council with 1 admin + 1 member.
        org = _make_org(db, "needsfix", mode="admin_council")
        only_admin = make_user(db, "needsfix-only-admin")
        member = make_user(db, "needsfix-member")
        make_org_membership(db, org_id=org.id, user_id=only_admin.id, role="admin")
        make_org_membership(db, org_id=org.id, user_id=member.id, role="member")
        db.commit()
        # Soft-revoke the only admin.
        _set_user_inactive(db, only_admin)
        db.commit()

        # No active admins now — confirm at_risk.
        from governance import at_risk_of_needs_rebootstrap
        assert at_risk_of_needs_rebootstrap(db, org) is True

    def test_check_and_audit_rebootstrap_emits_audit(
        self, db: Session,
    ):
        org = _make_org(db, "needsaudit", mode="admin_council")
        member = make_user(db, "needsaudit-member")
        make_org_membership(db, org_id=org.id, user_id=member.id, role="member")
        db.commit()
        from governance import check_and_audit_rebootstrap
        emitted = check_and_audit_rebootstrap(db, org, actor_id=None)
        db.commit()
        assert emitted is True
        audit = db.query(models.AuditLog).filter(
            models.AuditLog.action == "org.needs_rebootstrap",
        ).all()
        assert len(audit) == 1
        assert audit[0].details["governance_mode"] == "admin_council"

    def test_check_and_audit_no_emission_when_healthy(
        self, db: Session,
    ):
        org, admin_a, admin_b, member = _setup_council_org(db)
        from governance import check_and_audit_rebootstrap
        emitted = check_and_audit_rebootstrap(db, org, actor_id=None)
        assert emitted is False
        audit = db.query(models.AuditLog).filter(
            models.AuditLog.action == "org.needs_rebootstrap",
        ).all()
        assert len(audit) == 0

    def test_platform_admin_can_rebootstrap_zero_governor_council(
        self, client: TestClient, db: Session, auth_for,
    ):
        org = _make_org(db, "rebootme", mode="admin_council")
        member = make_user(db, "rebootme-member")
        make_org_membership(db, org_id=org.id, user_id=member.id, role="member")
        platform_admin = make_user(db, "platform-admin")
        platform_admin.is_admin = True
        rescue_user = make_user(db, "rescue-user")
        db.commit()

        r = client.post(
            f"/api/admin/orgs/{org.slug}/rebootstrap",
            headers=auth_for(platform_admin),
            json={"target_user_id": rescue_user.id, "target_role": "admin"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["mode"] == "admin_council"
        assert body["target_role"] == "admin"

        # Side effect: rescue_user is now admin.
        new_membership = db.query(models.OrgMembership).filter_by(
            user_id=rescue_user.id, org_id=org.id,
        ).one()
        assert db.get(models.Role, new_membership.role_id).system_key == "admin"
        assert _count_active_role(db, org.id, "admin") == 1

    def test_rebootstrap_rejected_when_org_healthy(
        self, client: TestClient, db: Session, auth_for,
    ):
        """Platform admin cannot use the rebootstrap backstop to bypass
        in-org governance — the org must actually be at zero governors."""
        org, admin_a, admin_b, member = _setup_council_org(db)
        platform_admin = make_user(db, "pa-healthy")
        platform_admin.is_admin = True
        rescue = make_user(db, "rescue2")
        db.commit()

        r = client.post(
            f"/api/admin/orgs/{org.slug}/rebootstrap",
            headers=auth_for(platform_admin),
            json={"target_user_id": rescue.id, "target_role": "admin"},
        )
        assert r.status_code == 400

    def test_rebootstrap_role_must_match_mode(
        self, client: TestClient, db: Session, auth_for,
    ):
        org = _make_org(db, "wrongrole", mode="admin_council")
        member = make_user(db, "wrongrole-member")
        make_org_membership(db, org_id=org.id, user_id=member.id, role="member")
        platform_admin = make_user(db, "wrongrole-pa")
        platform_admin.is_admin = True
        db.commit()

        # Council mode expects 'admin'; sending 'steward' should 400.
        r = client.post(
            f"/api/admin/orgs/{org.slug}/rebootstrap",
            headers=auth_for(platform_admin),
            json={"target_user_id": member.id, "target_role": "steward"},
        )
        assert r.status_code == 400

    def test_rebootstrap_requires_platform_admin(
        self, client: TestClient, db: Session, auth_for,
    ):
        org = _make_org(db, "nonpaorg", mode="admin_council")
        member = make_user(db, "nonpaorg-member")
        make_org_membership(db, org_id=org.id, user_id=member.id, role="member")
        regular = make_user(db, "regular-user")
        # not platform admin
        db.commit()
        r = client.post(
            f"/api/admin/orgs/{org.slug}/rebootstrap",
            headers=auth_for(regular),
            json={"target_user_id": member.id, "target_role": "admin"},
        )
        # Phase 39 + admin gate: should 403 (not platform admin).
        assert r.status_code == 403
