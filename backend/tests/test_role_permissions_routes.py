"""Phase 12 Stage 2 — tests for the per-org role-permissions matrix
endpoints (Cluster B, B1 + B2 + B5).

Covers the spec's enumerated cases (lines 211-225):
  * 200 happy path: PATCH applies real changes, audit row written with
    correct ``changes`` payload, response includes the new full matrix.
  * 200 no-op: PATCH whose changes already match state returns
    ``changes_applied: 0`` and emits NO audit event.
  * 400 unknown permission_key.
  * 400 unknown role_system_key.
  * 400 attempting to flip each of the three Steward locked cells.
  * 403 caller lacks role_permissions.edit.
  * 401 unauthenticated.
  * 404 org not found.
  * 404 caller is not a member of the org.
  * B1 GET: response shape includes the locked.steward 3-key list and
    every preset role + every registry permission.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from database import Base, get_db
from main import app
from permission_registry import ALL_PERMISSION_KEYS
from role_permissions import STEWARD_LOCKED_PERMISSIONS
from role_seed import seed_default_roles_for_org


_DUMMY_HASH = auth_utils.hash_password("demo1234")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def test_db():
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
def client(test_db):
    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _make_user(db, username: str) -> models.User:
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


def _make_org(db, name: str, slug: str) -> models.Organization:
    org = models.Organization(name=name, slug=slug, description="")
    db.add(org)
    db.flush()
    seed_default_roles_for_org(db, org.id)
    # Stage 2 explicitly seeds role_permissions.edit rows for moderator
    # and member with enabled=False to mirror the migration's behavior.
    # The seed helper only inserts True grants, so we add the False rows
    # here for the matrix-shape assertions to mirror prod state.
    for system_key in ("moderator", "member"):
        role = (
            db.query(models.Role)
            .filter(
                models.Role.org_id == org.id,
                models.Role.system_key == system_key,
            )
            .first()
        )
        existing = (
            db.query(models.RolePermission)
            .filter(
                models.RolePermission.role_id == role.id,
                models.RolePermission.permission_key == "role_permissions.edit",
            )
            .first()
        )
        if existing is None:
            db.add(models.RolePermission(
                role_id=role.id,
                permission_key="role_permissions.edit",
                enabled=False,
            ))
    db.flush()
    return org


def _add_membership(
    db, user, org, system_key: str, status: str = "active"
):
    role = (
        db.query(models.Role)
        .filter(
            models.Role.org_id == org.id,
            models.Role.system_key == system_key,
        )
        .first()
    )
    m = models.OrgMembership(
        user_id=user.id, org_id=org.id, role_id=role.id, status=status,
    )
    db.add(m)
    db.flush()
    return m


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


# ---------------------------------------------------------------------------
# B1 — GET shape
# ---------------------------------------------------------------------------

def test_get_returns_200_for_active_member(client, test_db):
    """Any active member can read the matrix — no permission gate on read."""
    user = _make_user(test_db, "alice")
    org = _make_org(test_db, "Org", "org")
    _add_membership(test_db, user, org, "member")
    test_db.commit()

    resp = client.get("/api/orgs/org/role-permissions", headers=_auth(user))
    assert resp.status_code == 200, resp.text


def test_get_response_shape(client, test_db):
    """B1 response includes org_id, org_slug, roles (4 ordered by display
    order), permissions (24 keys × 4 roles), and locked.steward (3 keys)."""
    user = _make_user(test_db, "alice")
    org = _make_org(test_db, "Org", "org")
    _add_membership(test_db, user, org, "steward")
    test_db.commit()

    resp = client.get("/api/orgs/org/role-permissions", headers=_auth(user))
    body = resp.json()

    assert body["org_id"] == org.id
    assert body["org_slug"] == "org"

    # 4 preset roles in display order.
    assert len(body["roles"]) == 4
    assert [r["system_key"] for r in body["roles"]] == [
        "steward", "admin", "moderator", "member"
    ]
    for r in body["roles"]:
        assert set(r.keys()) == {"id", "system_key", "name", "display_order"}

    # Permissions block: every key in registry × every preset role.
    assert set(body["permissions"].keys()) == ALL_PERMISSION_KEYS
    for pkey, per_role in body["permissions"].items():
        assert set(per_role.keys()) == {
            "steward", "admin", "moderator", "member"
        }
        for v in per_role.values():
            assert isinstance(v, bool)


def test_get_locked_block_lists_three_steward_keys(client, test_db):
    """B1 ``locked.steward`` enumerates the three protected keys in
    a sorted list — frontend uses this to render disabled checkboxes."""
    user = _make_user(test_db, "alice")
    org = _make_org(test_db, "Org", "org")
    _add_membership(test_db, user, org, "steward")
    test_db.commit()

    body = client.get(
        "/api/orgs/org/role-permissions", headers=_auth(user),
    ).json()

    assert "locked" in body
    assert set(body["locked"].keys()) == {"steward"}
    assert set(body["locked"]["steward"]) == STEWARD_LOCKED_PERMISSIONS
    assert body["locked"]["steward"] == sorted(STEWARD_LOCKED_PERMISSIONS)


def test_get_default_grants_reflected_in_matrix(client, test_db):
    """Spot-check default grants land in the right cells: steward and
    admin both have proposal.delete=True; moderator and member don't."""
    user = _make_user(test_db, "alice")
    org = _make_org(test_db, "Org", "org")
    _add_membership(test_db, user, org, "steward")
    test_db.commit()

    body = client.get(
        "/api/orgs/org/role-permissions", headers=_auth(user),
    ).json()

    assert body["permissions"]["proposal.delete"]["steward"] is True
    assert body["permissions"]["proposal.delete"]["admin"] is True
    assert body["permissions"]["proposal.delete"]["moderator"] is False
    assert body["permissions"]["proposal.delete"]["member"] is False

    # Moderator's 8-key default subset: proposal.create=True.
    assert body["permissions"]["proposal.create"]["moderator"] is True

    # role_permissions.edit defaults: steward/admin True, moderator/member False.
    assert body["permissions"]["role_permissions.edit"]["steward"] is True
    assert body["permissions"]["role_permissions.edit"]["admin"] is True
    assert body["permissions"]["role_permissions.edit"]["moderator"] is False
    assert body["permissions"]["role_permissions.edit"]["member"] is False


def test_get_unauthenticated_returns_401(client, test_db):
    """B1 requires auth like every other org-scoped endpoint."""
    org = _make_org(test_db, "Org", "org")
    test_db.commit()
    resp = client.get("/api/orgs/org/role-permissions")
    assert resp.status_code == 401


def test_get_unknown_org_returns_404(client, test_db):
    """B1 unknown slug — 404 from the org lookup."""
    user = _make_user(test_db, "alice")
    test_db.commit()
    resp = client.get(
        "/api/orgs/no-such-org/role-permissions", headers=_auth(user),
    )
    assert resp.status_code == 404


def test_get_non_member_returns_404(client, test_db):
    """Per spec line 220: caller is not a member of the org → 404 (not
    403). Doesn't disclose org existence."""
    user = _make_user(test_db, "alice")
    org = _make_org(test_db, "Org", "org")
    test_db.commit()
    resp = client.get(
        "/api/orgs/org/role-permissions", headers=_auth(user),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# B2 — PATCH happy path
# ---------------------------------------------------------------------------

def test_patch_happy_path_applies_change_and_audits(client, test_db):
    """200 happy path: PATCH a single non-locked cell, get
    changes_applied:1 + new matrix back, audit row exists with correct
    payload."""
    user = _make_user(test_db, "alice_steward")
    org = _make_org(test_db, "Org", "org")
    _add_membership(test_db, user, org, "steward")
    test_db.commit()

    # Flip moderator's proposal.delete from False -> True.
    resp = client.patch(
        "/api/orgs/org/role-permissions",
        headers=_auth(user),
        json={"changes": [{
            "role_system_key": "moderator",
            "permission_key": "proposal.delete",
            "enabled": True,
        }]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["changes_applied"] == 1
    # Returned matrix reflects the new state.
    assert body["permissions"]["proposal.delete"]["moderator"] is True

    # Audit row exists.
    audit_rows = (
        test_db.query(models.AuditLog)
        .filter(models.AuditLog.action == "role_permissions.updated")
        .all()
    )
    assert len(audit_rows) == 1
    audit = audit_rows[0]
    assert audit.actor_id == user.id
    assert audit.target_id == org.id
    assert audit.target_type == "organization"
    assert "changes" in audit.details
    assert len(audit.details["changes"]) == 1
    change = audit.details["changes"][0]
    assert change == {
        "role_system_key": "moderator",
        "permission_key": "proposal.delete",
        "old": False,
        "new": True,
    }


def test_patch_multiple_changes_applies_atomically(client, test_db):
    """Multiple changes in one PATCH: all apply, single audit event with
    full changes list."""
    user = _make_user(test_db, "alice_steward")
    org = _make_org(test_db, "Org", "org")
    _add_membership(test_db, user, org, "steward")
    test_db.commit()

    resp = client.patch(
        "/api/orgs/org/role-permissions",
        headers=_auth(user),
        json={"changes": [
            {"role_system_key": "moderator", "permission_key": "proposal.delete", "enabled": True},
            {"role_system_key": "admin", "permission_key": "member.remove", "enabled": False},
            {"role_system_key": "member", "permission_key": "proposal.create", "enabled": True},
        ]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["changes_applied"] == 3

    audit_rows = (
        test_db.query(models.AuditLog)
        .filter(models.AuditLog.action == "role_permissions.updated")
        .all()
    )
    assert len(audit_rows) == 1
    changes = audit_rows[0].details["changes"]
    assert len(changes) == 3
    by_key = {(c["role_system_key"], c["permission_key"]): c for c in changes}
    assert by_key[("moderator", "proposal.delete")] == {
        "role_system_key": "moderator", "permission_key": "proposal.delete",
        "old": False, "new": True,
    }
    assert by_key[("admin", "member.remove")] == {
        "role_system_key": "admin", "permission_key": "member.remove",
        "old": True, "new": False,
    }
    assert by_key[("member", "proposal.create")] == {
        "role_system_key": "member", "permission_key": "proposal.create",
        "old": False, "new": True,
    }


def test_patch_returns_matrix_with_b1_shape(client, test_db):
    """B2 success returns the same payload shape as B1 (with
    changes_applied prepended) so frontend doesn't need a follow-up GET."""
    user = _make_user(test_db, "alice_steward")
    org = _make_org(test_db, "Org", "org")
    _add_membership(test_db, user, org, "steward")
    test_db.commit()

    resp = client.patch(
        "/api/orgs/org/role-permissions",
        headers=_auth(user),
        json={"changes": [{
            "role_system_key": "moderator", "permission_key": "proposal.delete",
            "enabled": True,
        }]},
    )
    body = resp.json()
    assert "org_id" in body
    assert "org_slug" in body
    assert "roles" in body and len(body["roles"]) == 4
    assert "permissions" in body and len(body["permissions"]) == len(ALL_PERMISSION_KEYS)
    assert "locked" in body
    assert body["locked"]["steward"] == sorted(STEWARD_LOCKED_PERMISSIONS)


# ---------------------------------------------------------------------------
# B2 — no-op path (no audit)
# ---------------------------------------------------------------------------

def test_patch_no_op_returns_zero_and_skips_audit(client, test_db):
    """200 no-op: every change in the body already matches state →
    changes_applied: 0, NO audit event, full matrix returned."""
    user = _make_user(test_db, "alice_steward")
    org = _make_org(test_db, "Org", "org")
    _add_membership(test_db, user, org, "steward")
    test_db.commit()

    # admin.proposal.delete is True by default. Send "set to True" — no-op.
    # member.proposal.delete is False by default. Send "set to False" — no-op.
    resp = client.patch(
        "/api/orgs/org/role-permissions",
        headers=_auth(user),
        json={"changes": [
            {"role_system_key": "admin", "permission_key": "proposal.delete", "enabled": True},
            {"role_system_key": "member", "permission_key": "proposal.delete", "enabled": False},
        ]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["changes_applied"] == 0
    # Matrix is still in the response.
    assert "permissions" in body

    audit_rows = (
        test_db.query(models.AuditLog)
        .filter(models.AuditLog.action == "role_permissions.updated")
        .all()
    )
    assert audit_rows == [], (
        f"No-op PATCH must not write an audit event; got {len(audit_rows)} rows"
    )


def test_patch_empty_changes_is_no_op(client, test_db):
    """Empty changes list → changes_applied: 0, no audit."""
    user = _make_user(test_db, "alice_steward")
    org = _make_org(test_db, "Org", "org")
    _add_membership(test_db, user, org, "steward")
    test_db.commit()

    resp = client.patch(
        "/api/orgs/org/role-permissions",
        headers=_auth(user),
        json={"changes": []},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["changes_applied"] == 0
    audit_rows = (
        test_db.query(models.AuditLog)
        .filter(models.AuditLog.action == "role_permissions.updated")
        .all()
    )
    assert audit_rows == []


# ---------------------------------------------------------------------------
# B2 — 400 validation errors
# ---------------------------------------------------------------------------

def test_patch_unknown_permission_key_returns_400(client, test_db):
    """Unknown permission_key → 400, no audit, no mutation."""
    user = _make_user(test_db, "alice_steward")
    org = _make_org(test_db, "Org", "org")
    _add_membership(test_db, user, org, "steward")
    test_db.commit()

    resp = client.patch(
        "/api/orgs/org/role-permissions",
        headers=_auth(user),
        json={"changes": [{
            "role_system_key": "admin",
            "permission_key": "made.up.key",
            "enabled": True,
        }]},
    )
    assert resp.status_code == 400, resp.text
    assert "made.up.key" in resp.json()["detail"]

    audit_rows = (
        test_db.query(models.AuditLog)
        .filter(models.AuditLog.action == "role_permissions.updated")
        .all()
    )
    assert audit_rows == []


def test_patch_unknown_role_returns_400(client, test_db):
    """Unknown role_system_key → 400."""
    user = _make_user(test_db, "alice_steward")
    org = _make_org(test_db, "Org", "org")
    _add_membership(test_db, user, org, "steward")
    test_db.commit()

    resp = client.patch(
        "/api/orgs/org/role-permissions",
        headers=_auth(user),
        json={"changes": [{
            "role_system_key": "wizard",
            "permission_key": "proposal.create",
            "enabled": True,
        }]},
    )
    assert resp.status_code == 400, resp.text
    assert "wizard" in resp.json()["detail"]


@pytest.mark.parametrize("locked_key", sorted(STEWARD_LOCKED_PERMISSIONS))
def test_patch_attempting_to_unset_steward_locked_returns_400(
    client, test_db, locked_key
):
    """400 attempting to flip each of the three Steward locked cells.
    Parameterized over all three protected keys."""
    user = _make_user(test_db, "alice_steward")
    org = _make_org(test_db, "Org", "org")
    _add_membership(test_db, user, org, "steward")
    test_db.commit()

    resp = client.patch(
        "/api/orgs/org/role-permissions",
        headers=_auth(user),
        json={"changes": [{
            "role_system_key": "steward",
            "permission_key": locked_key,
            "enabled": False,
        }]},
    )
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert "locked" in detail.lower()
    assert locked_key in detail

    # Underlying row is unchanged — it should still read True via the matrix.
    matrix = client.get(
        "/api/orgs/org/role-permissions", headers=_auth(user),
    ).json()
    assert matrix["permissions"][locked_key]["steward"] is True


def test_patch_locked_cell_is_400_even_when_request_is_set_to_true(client, test_db):
    """Even a no-op-shaped PATCH against a locked cell (set to True, the
    current value) should 400 — the spec says reject the change request
    regardless of the requested value."""
    user = _make_user(test_db, "alice_steward")
    org = _make_org(test_db, "Org", "org")
    _add_membership(test_db, user, org, "steward")
    test_db.commit()

    resp = client.patch(
        "/api/orgs/org/role-permissions",
        headers=_auth(user),
        json={"changes": [{
            "role_system_key": "steward",
            "permission_key": "member.change_role",
            "enabled": True,
        }]},
    )
    assert resp.status_code == 400, resp.text


def test_patch_admin_can_flip_their_own_locked_keys(client, test_db):
    """Stewards' three locked keys are NOT locked for admin — the matrix
    permits flipping admin.member.change_role etc. (Spec Q1: "Other roles
    have no lockout protection.")"""
    user = _make_user(test_db, "alice_steward")
    org = _make_org(test_db, "Org", "org")
    _add_membership(test_db, user, org, "steward")
    test_db.commit()

    resp = client.patch(
        "/api/orgs/org/role-permissions",
        headers=_auth(user),
        json={"changes": [{
            "role_system_key": "admin",
            "permission_key": "member.change_role",
            "enabled": False,
        }]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["changes_applied"] == 1


# ---------------------------------------------------------------------------
# B2 — auth / membership errors
# ---------------------------------------------------------------------------

def test_patch_unauthenticated_returns_401(client, test_db):
    """No bearer token → 401."""
    org = _make_org(test_db, "Org", "org")
    test_db.commit()
    resp = client.patch(
        "/api/orgs/org/role-permissions",
        json={"changes": []},
    )
    assert resp.status_code == 401


def test_patch_unknown_org_returns_404(client, test_db):
    """Non-existent org slug → 404."""
    user = _make_user(test_db, "alice")
    test_db.commit()
    resp = client.patch(
        "/api/orgs/missing/role-permissions",
        headers=_auth(user),
        json={"changes": []},
    )
    assert resp.status_code == 404


def test_patch_non_member_returns_404(client, test_db):
    """Caller has no membership on the org → 404 (mirrors GET; doesn't
    disclose org existence)."""
    user = _make_user(test_db, "alice")
    org = _make_org(test_db, "Org", "org")
    test_db.commit()
    resp = client.patch(
        "/api/orgs/org/role-permissions",
        headers=_auth(user),
        json={"changes": []},
    )
    assert resp.status_code == 404


def test_patch_caller_lacks_role_permissions_edit_returns_403(client, test_db):
    """403 caller is a member but lacks role_permissions.edit. Default
    grants leave moderator and member without it."""
    user = _make_user(test_db, "bob_moderator")
    org = _make_org(test_db, "Org", "org")
    _add_membership(test_db, user, org, "moderator")
    test_db.commit()

    resp = client.patch(
        "/api/orgs/org/role-permissions",
        headers=_auth(user),
        json={"changes": [{
            "role_system_key": "admin",
            "permission_key": "proposal.delete",
            "enabled": False,
        }]},
    )
    assert resp.status_code == 403, resp.text


def test_patch_member_caller_lacks_role_permissions_edit_returns_403(client, test_db):
    """403 for members too — they default to no permissions including
    role_permissions.edit."""
    user = _make_user(test_db, "carol_member")
    org = _make_org(test_db, "Org", "org")
    _add_membership(test_db, user, org, "member")
    test_db.commit()

    resp = client.patch(
        "/api/orgs/org/role-permissions",
        headers=_auth(user),
        json={"changes": [{
            "role_system_key": "admin",
            "permission_key": "proposal.delete",
            "enabled": False,
        }]},
    )
    assert resp.status_code == 403


def test_patch_admin_caller_succeeds_via_default_grants(client, test_db):
    """Admin defaults to having role_permissions.edit (Stage 2 puts it in
    DEFAULT_GRANTS), so admin callers can edit the matrix successfully."""
    user = _make_user(test_db, "alice_admin")
    org = _make_org(test_db, "Org", "org")
    _add_membership(test_db, user, org, "admin")
    test_db.commit()

    resp = client.patch(
        "/api/orgs/org/role-permissions",
        headers=_auth(user),
        json={"changes": [{
            "role_system_key": "moderator",
            "permission_key": "proposal.delete",
            "enabled": True,
        }]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["changes_applied"] == 1


def test_patch_invalid_cell_rolls_back_other_changes_in_same_request(client, test_db):
    """Atomicity: one invalid cell rejects the WHOLE request — even valid
    changes earlier in the list don't apply."""
    user = _make_user(test_db, "alice_steward")
    org = _make_org(test_db, "Org", "org")
    _add_membership(test_db, user, org, "steward")
    test_db.commit()

    # First change is valid (would flip moderator.proposal.delete True);
    # second change is invalid (unknown key). Whole request 400s.
    resp = client.patch(
        "/api/orgs/org/role-permissions",
        headers=_auth(user),
        json={"changes": [
            {"role_system_key": "moderator", "permission_key": "proposal.delete", "enabled": True},
            {"role_system_key": "admin", "permission_key": "made.up.key", "enabled": True},
        ]},
    )
    assert resp.status_code == 400

    # The valid change must NOT have applied.
    matrix = client.get(
        "/api/orgs/org/role-permissions", headers=_auth(user),
    ).json()
    assert matrix["permissions"]["proposal.delete"]["moderator"] is False, (
        "atomicity violated: valid earlier change applied despite later invalid cell"
    )
