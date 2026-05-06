"""Phase 15 Cluster S — sub-org permission inheritance tests.

Covers spec §S6:

  - Effective-role resolution: 7 cases.
  - Permission gate via has_permission / has_permission_on_sub_org: 5 cases.
  - Transferability config endpoint: 3 cases.
  - Audit-log platform_admin_override enrichment: 1 case.

The migration tests are in test_phase15_migration_cycle.py.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from audit_utils import log_audit_event
from database import Base, get_db
from main import app
from role_permissions import (
    effective_role_on_sub_org,
    has_permission,
    has_permission_on_sub_org,
    role_transfers_to_sub_orgs,
)
from tests.conftest import (
    make_org_membership,
    make_sub_org_membership,
    make_user,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

def _make_org(
    db: Session, name: str, slug: str,
    parent_org_id: str | None = None,
    settings: dict | None = None,
) -> models.Organization:
    """Create an Organization and ensure its preset Role rows are seeded.

    We always seed roles (even for sub-orgs) so the test helpers can
    construct memberships against this org. Production code seeds at
    org-create time via ``role_seed.seed_default_roles_for_org``; the
    test helper mirrors that.
    """
    from role_seed import seed_default_roles_for_org
    org = models.Organization(
        name=name, slug=slug, description="",
        parent_org_id=parent_org_id,
        settings=settings or {},
    )
    db.add(org)
    db.flush()
    # Seed presets for the parent org. Sub-orgs inherit the parent's
    # matrix wholesale; we don't seed Role rows on them.
    if parent_org_id is None:
        seed_default_roles_for_org(db, org.id)
        db.flush()
    return org


def _admin_user(db: Session, username: str) -> models.User:
    """Make a platform-admin user (User.is_admin=True)."""
    u = make_user(db, username)
    u.is_admin = True
    db.flush()
    return u


# ---------------------------------------------------------------------------
# role_transfers_to_sub_orgs (S1 helper)
# ---------------------------------------------------------------------------

class TestRoleTransfersToSubOrgs:
    def test_steward_always_transfers_regardless_of_settings(self, db):
        """Spec §S1: Steward is locked ON; even an explicit False is
        ignored at the helper level."""
        org = _make_org(db, "Org", "org",
                        settings={"sub_org_role_transferability":
                                  {"steward": False}})
        # Locked on at the helper level.
        assert role_transfers_to_sub_orgs(org, "steward") is True

    def test_admin_defaults_on(self, db):
        """Default for admin is ON when settings absent."""
        org = _make_org(db, "Org", "org", settings={})
        assert role_transfers_to_sub_orgs(org, "admin") is True

    def test_moderator_defaults_on(self, db):
        org = _make_org(db, "Org", "org", settings={})
        assert role_transfers_to_sub_orgs(org, "moderator") is True

    def test_member_defaults_off(self, db):
        """Default for member is OFF when settings absent (the
        load-bearing privacy default)."""
        org = _make_org(db, "Org", "org", settings={})
        assert role_transfers_to_sub_orgs(org, "member") is False

    def test_admin_can_be_disabled_via_settings(self, db):
        org = _make_org(db, "Org", "org",
                        settings={"sub_org_role_transferability":
                                  {"admin": False}})
        assert role_transfers_to_sub_orgs(org, "admin") is False

    def test_member_can_be_enabled_via_settings(self, db):
        org = _make_org(db, "Org", "org",
                        settings={"sub_org_role_transferability":
                                  {"member": True}})
        assert role_transfers_to_sub_orgs(org, "member") is True


# ---------------------------------------------------------------------------
# Effective-role resolution (S6 — 7 cases)
# ---------------------------------------------------------------------------

class TestEffectiveRoleOnSubOrg:
    """Spec §S6 effective-role resolution test cases (7 cases)."""

    def test_sub_org_admin_with_parent_member_resolves_to_admin(self, db):
        """Case 1: User has sub-org-specific Admin AND parent Member.
        Sub-org assignment wins because it's higher tier than parent
        Member's transferability candidate (which is OFF by default
        anyway)."""
        parent = _make_org(db, "Parent", "parent")
        sub = _make_org(db, "Sub", "sub", parent_org_id=parent.id)
        user = make_user(db, "alice")
        make_org_membership(db, org_id=parent.id, user_id=user.id, role="member")
        make_sub_org_membership(db, sub_org_id=sub.id, user_id=user.id, role="admin")
        db.flush()

        role, via_pa = effective_role_on_sub_org(db, user.id, sub)
        assert role is not None
        assert role.system_key == "admin"
        assert via_pa is False

    def test_no_sub_org_membership_parent_steward_resolves_to_steward(self, db):
        """Case 2: User has parent Steward but no sub-org membership.
        Steward transferability is locked ON; user resolves to Steward."""
        parent = _make_org(db, "Parent", "parent")
        sub = _make_org(db, "Sub", "sub", parent_org_id=parent.id)
        user = make_user(db, "alice")
        make_org_membership(db, org_id=parent.id, user_id=user.id, role="steward")
        db.flush()

        role, via_pa = effective_role_on_sub_org(db, user.id, sub)
        assert role is not None
        assert role.system_key == "steward"
        assert via_pa is False

    def test_no_sub_org_parent_member_default_off_resolves_to_none(self, db):
        """Case 3: Parent Member, default-off Member transferability,
        no sub-org membership. Resolved role is None — no permissions."""
        parent = _make_org(db, "Parent", "parent")
        sub = _make_org(db, "Sub", "sub", parent_org_id=parent.id)
        user = make_user(db, "alice")
        make_org_membership(db, org_id=parent.id, user_id=user.id, role="member")
        db.flush()

        role, via_pa = effective_role_on_sub_org(db, user.id, sub)
        assert role is None
        assert via_pa is False

    def test_no_sub_org_parent_member_with_transferability_resolves_to_member(self, db):
        """Case 4: Same as Case 3 but org has Member transferability ON.
        Resolved role is Member."""
        parent = _make_org(
            db, "Parent", "parent",
            settings={"sub_org_role_transferability": {"member": True}},
        )
        sub = _make_org(db, "Sub", "sub", parent_org_id=parent.id)
        user = make_user(db, "alice")
        make_org_membership(db, org_id=parent.id, user_id=user.id, role="member")
        db.flush()

        role, via_pa = effective_role_on_sub_org(db, user.id, sub)
        assert role is not None
        assert role.system_key == "member"
        assert via_pa is False

    def test_sub_org_member_with_parent_steward_resolves_to_steward(self, db):
        """Case 5: User has sub-org Member AND parent Steward. Highest
        tier wins; Steward (tier 3) > Member (tier 0)."""
        parent = _make_org(db, "Parent", "parent")
        sub = _make_org(db, "Sub", "sub", parent_org_id=parent.id)
        user = make_user(db, "alice")
        make_org_membership(db, org_id=parent.id, user_id=user.id, role="steward")
        make_sub_org_membership(db, sub_org_id=sub.id, user_id=user.id, role="member")
        db.flush()

        role, via_pa = effective_role_on_sub_org(db, user.id, sub)
        assert role is not None
        assert role.system_key == "steward"
        assert via_pa is False

    def test_platform_admin_with_no_membership_resolves_to_admin(self, db):
        """Case 6: Platform admin with no membership anywhere falls
        through to the Admin role on the parent. via_platform_admin=True."""
        parent = _make_org(db, "Parent", "parent")
        sub = _make_org(db, "Sub", "sub", parent_org_id=parent.id)
        admin = _admin_user(db, "platform_admin")
        db.flush()

        role, via_pa = effective_role_on_sub_org(db, admin.id, sub)
        assert role is not None
        assert role.system_key == "admin"
        assert via_pa is True

    def test_platform_admin_with_sub_org_steward_resolves_to_steward_not_via_pa(self, db):
        """Case 7: Platform admin who ALSO has sub-org Steward via
        direct membership — resolved role is Steward (highest tier),
        and via_platform_admin is False (the direct sub-org membership
        outranks the platform-admin candidate, so the "override" flag
        shouldn't be set)."""
        parent = _make_org(db, "Parent", "parent")
        sub = _make_org(db, "Sub", "sub", parent_org_id=parent.id)
        admin = _admin_user(db, "platform_admin")
        make_sub_org_membership(db, sub_org_id=sub.id, user_id=admin.id, role="steward")
        db.flush()

        role, via_pa = effective_role_on_sub_org(db, admin.id, sub)
        assert role is not None
        assert role.system_key == "steward"
        # via_platform_admin should be False because the sub-org Steward
        # candidate outranks the platform-admin Admin candidate.
        assert via_pa is False


# ---------------------------------------------------------------------------
# Permission gate (S6 — 5 cases)
# ---------------------------------------------------------------------------

class TestPermissionGateOnSubOrg:
    """Spec §S6 permission-gate cases (5)."""

    def test_parent_steward_can_create_proposal_in_sub_org(self, db):
        """Case 1: Parent Steward, no sub-org membership, attempts
        proposal.create in sub-org. Steward transferability is locked
        ON, parent matrix grants proposal.create to Steward → True.
        """
        parent = _make_org(db, "Parent", "parent")
        sub = _make_org(db, "Sub", "sub", parent_org_id=parent.id)
        user = make_user(db, "steward")
        make_org_membership(db, org_id=parent.id, user_id=user.id, role="steward")
        db.flush()

        allowed, via_pa = has_permission_on_sub_org(
            db, user.id, sub, "proposal.create",
        )
        assert allowed is True
        assert via_pa is False

    def test_parent_member_default_off_cannot_create_proposal_in_sub_org(self, db):
        """Case 2: Parent Member with default-off transferability →
        no permission.
        """
        parent = _make_org(db, "Parent", "parent")
        sub = _make_org(db, "Sub", "sub", parent_org_id=parent.id)
        user = make_user(db, "member")
        make_org_membership(db, org_id=parent.id, user_id=user.id, role="member")
        db.flush()

        allowed, via_pa = has_permission_on_sub_org(
            db, user.id, sub, "proposal.create",
        )
        assert allowed is False
        assert via_pa is False

    def test_parent_member_with_transferability_on_can_create_proposal(self, db):
        """Case 3: Same setup as Case 2 but Member transferability ON.
        Note: parent's Member matrix doesn't grant proposal.create by
        default (DEFAULT_GRANTS for member is empty), so we need to
        explicitly grant it for this test to demonstrate the
        transferability is taking effect. We use a permission Member
        actually has by default — but Member has no defaults. Instead,
        we test that effective_role_on_sub_org RESOLVES to member
        (via the transferability flag), and check a permission via
        the matrix at member tier (which is no permissions out of the
        box). The test reframes: with transferability ON, the user
        is no-longer None — they CAN have permissions if explicitly
        granted to the Member role.
        """
        parent = _make_org(
            db, "Parent", "parent",
            settings={"sub_org_role_transferability": {"member": True}},
        )
        sub = _make_org(db, "Sub", "sub", parent_org_id=parent.id)
        user = make_user(db, "member")
        make_org_membership(db, org_id=parent.id, user_id=user.id, role="member")
        # Grant proposal.create to Member on the parent (custom matrix).
        member_role = (
            db.query(models.Role)
            .filter(models.Role.org_id == parent.id,
                    models.Role.system_key == "member")
            .first()
        )
        db.add(models.RolePermission(
            role_id=member_role.id,
            permission_key="proposal.create",
            enabled=True,
        ))
        db.flush()

        allowed, via_pa = has_permission_on_sub_org(
            db, user.id, sub, "proposal.create",
        )
        assert allowed is True
        assert via_pa is False

    def test_platform_admin_cannot_delete_sub_org_org_delete_steward_only(self, db):
        """Case 4: Platform admin attempts org.delete on a sub-org.
        Resolved role is Admin (via the platform-admin fallback);
        org.delete is hardcoded Steward-only → fails."""
        parent = _make_org(db, "Parent", "parent")
        sub = _make_org(db, "Sub", "sub", parent_org_id=parent.id)
        admin = _admin_user(db, "platform_admin")
        db.flush()

        allowed, via_pa = has_permission_on_sub_org(
            db, admin.id, sub, "org.delete",
        )
        assert allowed is False
        # via_platform_admin reflects the resolved-role path even when
        # the permission is denied; spec §S6 case "Platform admin
        # attempts org.delete on a sub-org: fails" doesn't require the
        # flag to be False on denial. The resolution still came via
        # the platform-admin path; the gate just rejects the specific
        # permission key.
        assert via_pa is True

    def test_audit_log_includes_platform_admin_override_when_applicable(self, db):
        """Case 5: When an action is taken on a sub-org via the
        platform-admin override, the audit-log entry's details payload
        includes ``platform_admin_override: true``."""
        parent = _make_org(db, "Parent", "parent")
        sub = _make_org(db, "Sub", "sub", parent_org_id=parent.id)
        admin = _admin_user(db, "platform_admin")
        db.flush()

        # Resolve effective role + capture the override flag.
        role, via_pa = effective_role_on_sub_org(db, admin.id, sub)
        assert role is not None and role.system_key == "admin"
        assert via_pa is True

        # Emit an audit event with the flag.
        log_audit_event(
            db,
            action="sub_org.member_invited",
            target_type="sub_org_membership",
            target_id=sub.id,
            actor_id=admin.id,
            details={"sub_org_id": sub.id, "target_user_id": "x"},
            platform_admin_override=via_pa,
        )
        db.flush()

        entry = (
            db.query(models.AuditLog)
            .filter(models.AuditLog.actor_id == admin.id)
            .order_by(models.AuditLog.timestamp.desc())
            .first()
        )
        assert entry is not None
        assert entry.details.get("platform_admin_override") is True

    def test_audit_log_omits_platform_admin_override_for_regular_actions(self, db):
        """Negative: when via_platform_admin is False, the flag is NOT
        added to details (audit log stays signal-rich; absence means
        membership-based action)."""
        parent = _make_org(db, "Parent", "parent")
        sub = _make_org(db, "Sub", "sub", parent_org_id=parent.id)
        user = make_user(db, "regular_steward")
        make_org_membership(db, org_id=parent.id, user_id=user.id, role="steward")
        db.flush()

        role, via_pa = effective_role_on_sub_org(db, user.id, sub)
        assert role.system_key == "steward"
        assert via_pa is False

        log_audit_event(
            db,
            action="sub_org.member_invited",
            target_type="sub_org_membership",
            target_id=sub.id,
            actor_id=user.id,
            details={"sub_org_id": sub.id},
            platform_admin_override=via_pa,
        )
        db.flush()

        entry = (
            db.query(models.AuditLog)
            .filter(models.AuditLog.actor_id == user.id)
            .order_by(models.AuditLog.timestamp.desc())
            .first()
        )
        assert entry is not None
        assert "platform_admin_override" not in entry.details


# ---------------------------------------------------------------------------
# Transferability config endpoint (S3 — 3 cases)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def shared_db():
    """A db session backed by a StaticPool engine so a TestClient
    request and the test body see the same in-memory DB. Use this
    fixture (instead of the conftest ``db``) for tests that issue HTTP
    requests through the TestClient.
    """
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


@pytest.fixture
def client(shared_db):
    """TestClient bound to the shared_db via dependency override."""
    def _get_db_override():
        try:
            yield shared_db
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db_override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def _auth(user: models.User) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


class TestTransferabilityConfigEndpoint:
    """Spec §S6 transferability-config cases (3)."""

    def test_patch_rejects_steward_false(self, shared_db, client):
        """Steward transferability cannot be disabled (locked ON).
        PATCH attempting to set steward=false returns 400."""
        org = _make_org(shared_db, "Org", "org-cfg-1")
        user = make_user(shared_db, "steward_user")
        make_org_membership(shared_db, org_id=org.id, user_id=user.id, role="steward")
        shared_db.commit()

        resp = client.patch(
            f"/api/orgs/{org.slug}",
            json={"settings": {
                "sub_org_role_transferability": {"steward": False},
            }},
            headers=_auth(user),
        )
        assert resp.status_code == 400, resp.text
        assert "Steward role transferability cannot be disabled" in resp.text

    def test_patch_accepts_member_true(self, shared_db, client):
        """PATCH setting member=true is accepted; the resolution helper
        reflects the new state."""
        org = _make_org(shared_db, "Org", "org-cfg-2")
        user = make_user(shared_db, "steward_user2")
        make_org_membership(shared_db, org_id=org.id, user_id=user.id, role="steward")
        sub = _make_org(shared_db, "Sub", "sub-cfg-2", parent_org_id=org.id)
        member = make_user(shared_db, "member_user2")
        make_org_membership(shared_db, org_id=org.id, user_id=member.id, role="member")
        shared_db.commit()

        # Pre: default Member transferability is OFF → resolved role None.
        role_pre, _ = effective_role_on_sub_org(shared_db, member.id, sub)
        assert role_pre is None

        resp = client.patch(
            f"/api/orgs/{org.slug}",
            json={"settings": {
                "sub_org_role_transferability": {"member": True},
            }},
            headers=_auth(user),
        )
        assert resp.status_code == 200, resp.text

        # Post: the Member transferability flag is now ON → resolved role
        # is Member.
        shared_db.expire_all()
        sub_refreshed = shared_db.get(models.Organization, sub.id)
        role_post, _ = effective_role_on_sub_org(
            shared_db, member.id, sub_refreshed,
        )
        assert role_post is not None
        assert role_post.system_key == "member"

    def test_defaults_apply_when_setting_absent(self, db):
        """When the settings key is absent entirely, the spec defaults
        apply (steward/admin/moderator ON, member OFF). Pure helper-
        level test; doesn't need the HTTP client."""
        org = _make_org(db, "Org", "org-cfg-3", settings={})
        assert role_transfers_to_sub_orgs(org, "steward") is True
        assert role_transfers_to_sub_orgs(org, "admin") is True
        assert role_transfers_to_sub_orgs(org, "moderator") is True
        assert role_transfers_to_sub_orgs(org, "member") is False


# ---------------------------------------------------------------------------
# has_permission integration (S4) — confirm sub-org scope routes through
# the new resolution
# ---------------------------------------------------------------------------

class TestHasPermissionSubOrgIntegration:
    def test_has_permission_on_sub_org_uses_effective_role(self, db):
        """Calling has_permission with a sub-org scope_id now goes
        through effective_role_on_sub_org rather than the old
        "implicit power" path. Verified by the parent-Member-with-
        default-off case: old behavior returned False (no implicit
        power for non-admin) — same answer here, but via the new
        resolution. The differentiating case (parent Moderator) is
        verified separately."""
        parent = _make_org(db, "Parent", "parent-int1")
        sub = _make_org(db, "Sub", "sub-int1", parent_org_id=parent.id)
        user = make_user(db, "alice_int1")
        make_org_membership(db, org_id=parent.id, user_id=user.id, role="member")
        db.flush()

        # Parent Member with default-off transferability → no
        # permissions on the sub-org.
        assert has_permission(db, user.id, sub.id, "proposal.create") is False

    def test_parent_moderator_now_inherits_via_transferability(self, db):
        """The behavior change from Phase 12 Stage 1: parent Moderator
        now DOES inherit permissions on sub-orgs (Moderator transferability
        defaults ON). This is the canonical "implicit power replacement"
        case."""
        parent = _make_org(db, "Parent", "parent-int2")
        sub = _make_org(db, "Sub", "sub-int2", parent_org_id=parent.id)
        user = make_user(db, "moderator_int2")
        make_org_membership(db, org_id=parent.id, user_id=user.id, role="moderator")
        db.flush()

        # Parent Moderator inherits Moderator on sub-org → has
        # proposal.create (which is in DEFAULT_GRANTS for moderator).
        assert has_permission(db, user.id, sub.id, "proposal.create") is True
