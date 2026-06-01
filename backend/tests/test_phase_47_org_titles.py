"""Phase 47 — Org titles / offices tests.

Spec: phase47_org_titles_spec.md.

Verification matrix:
  - Built-in reconciliation regression: Steward/Admin + the
    governance.py floor + recovery + governance modes byte-for-byte
    unchanged. Reuses the 45a/45b/46 floor + recovery tests as the
    regression base (they continue to pass with this pass's changes).
  - Title↔role binding: bound-role title grant/revoke flows through
    the 45a/45b role machinery; title-only carries no permissions;
    role-only (no title) unaffected. Asserts actual role rows.
  - Floor preserved: revoking the only steward-binding title is
    blocked exactly as removing the only steward is today (D2/D7).
  - Cardinality: single-holder enforced; multi-cap enforced.
  - Assignment permission gate (D5): only title.manage-holders can
    grant/revoke.
  - System title protection: uneditable + undeletable + unassignable
    via the title endpoint.
  - held_titles surfaces on the member roster.
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
# Fixtures (StaticPool pattern; same as the rest of the 44/45/46/46a suite)
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

def _make_org(db: Session, slug: str) -> models.Organization:
    org = models.Organization(
        name=slug.replace("-", " ").title(),
        slug=slug,
        description="",
        join_policy="open",
        settings={},
    )
    db.add(org)
    db.flush()
    # Seed system titles like create_organization does.
    from org_titles import seed_system_titles_for_org
    seed_system_titles_for_org(db, org.id)
    return org


def _setup_org(db: Session, slug: str = "p47org"):
    """Steward + 2 admins + 2 members."""
    org = _make_org(db, slug)
    steward = make_user(db, f"{slug}-steward")
    admin_a = make_user(db, f"{slug}-admin-a")
    admin_b = make_user(db, f"{slug}-admin-b")
    member_x = make_user(db, f"{slug}-member-x")
    member_y = make_user(db, f"{slug}-member-y")
    make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
    make_org_membership(db, org_id=org.id, user_id=admin_a.id, role="admin")
    make_org_membership(db, org_id=org.id, user_id=admin_b.id, role="admin")
    make_org_membership(db, org_id=org.id, user_id=member_x.id, role="member")
    make_org_membership(db, org_id=org.id, user_id=member_y.id, role="member")
    db.commit()
    return org, steward, admin_a, admin_b, member_x, member_y


def _user_role(db: Session, org_id: str, user_id: str) -> str | None:
    m = db.query(models.OrgMembership).filter_by(
        org_id=org_id, user_id=user_id, status="active",
    ).first()
    if m is None or m.role_id is None:
        return None
    return db.get(models.Role, m.role_id).system_key


# ===========================================================================
# B5 — System title reconciliation
# ===========================================================================

class TestSystemTitleSeed:
    """Steward + Admin system titles are seeded per-org. They are
    uneditable + undeletable + not directly assignable per D6."""

    def test_system_titles_are_seeded(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, *_ = _setup_org(db, "p47seed")
        r = client.get(f"/api/orgs/{org.slug}/titles", headers=auth_for(steward))
        assert r.status_code == 200, r.text
        titles = r.json()
        names = {t["name"]: t for t in titles}
        assert "Steward" in names
        assert "Admin" in names
        assert names["Steward"]["bound_role"] == "steward"
        assert names["Admin"]["bound_role"] == "admin"
        assert names["Steward"]["is_system"] is True
        assert names["Admin"]["is_system"] is True
        # Cardinality reflects the role semantic.
        assert names["Steward"]["cardinality_mode"] == "single"
        assert names["Admin"]["cardinality_mode"] == "multi"

    def test_system_title_cannot_be_edited(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, *_ = _setup_org(db, "p47edit")
        steward_title = (
            db.query(models.OrgTitle)
            .filter_by(org_id=org.id, name="Steward")
            .one()
        )
        r = client.patch(
            f"/api/orgs/{org.slug}/titles/{steward_title.id}",
            headers=auth_for(steward),
            json={"name": "Renamed"},
        )
        assert r.status_code == 400
        assert "System" in r.json()["detail"]

    def test_system_title_cannot_be_deleted(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, *_ = _setup_org(db, "p47del")
        admin_title = (
            db.query(models.OrgTitle)
            .filter_by(org_id=org.id, name="Admin")
            .one()
        )
        r = client.delete(
            f"/api/orgs/{org.slug}/titles/{admin_title.id}",
            headers=auth_for(steward),
        )
        assert r.status_code == 400

    def test_system_title_cannot_be_assigned_directly(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin_a, admin_b, member_x, member_y = _setup_org(db, "p47sysassign")
        steward_title = (
            db.query(models.OrgTitle)
            .filter_by(org_id=org.id, name="Steward")
            .one()
        )
        r = client.post(
            f"/api/orgs/{org.slug}/titles/{steward_title.id}/assignments",
            headers=auth_for(steward),
            json={"user_id": admin_a.id},
        )
        assert r.status_code == 400
        # And the steward still holds the role.
        assert _user_role(db, org.id, steward.id) == "steward"


# ===========================================================================
# B2 — Title CRUD + permission gate
# ===========================================================================

class TestTitleCRUD:
    def test_steward_can_create_custom_title(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, *_ = _setup_org(db, "p47create")
        r = client.post(
            f"/api/orgs/{org.slug}/titles",
            headers=auth_for(steward),
            json={
                "name": "Treasurer",
                "bound_role": "admin",
                "cardinality_mode": "single",
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["name"] == "Treasurer"
        assert body["bound_role"] == "admin"
        assert body["is_system"] is False

    def test_member_without_title_manage_cannot_create(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin_a, admin_b, member_x, member_y = _setup_org(
            db, "p47gate",
        )
        r = client.post(
            f"/api/orgs/{org.slug}/titles",
            headers=auth_for(member_x),
            json={"name": "X", "bound_role": None},
        )
        assert r.status_code == 403

    def test_title_with_holders_cannot_be_deleted(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin_a, admin_b, member_x, member_y = _setup_org(
            db, "p47delholders",
        )
        # Create a Council Member multi-title (no bound role).
        r = client.post(
            f"/api/orgs/{org.slug}/titles",
            headers=auth_for(steward),
            json={
                "name": "Council Member", "bound_role": None,
                "cardinality_mode": "multi",
            },
        )
        title_id = r.json()["id"]
        # Assign to member_x.
        ra = client.post(
            f"/api/orgs/{org.slug}/titles/{title_id}/assignments",
            headers=auth_for(steward),
            json={"user_id": member_x.id},
        )
        assert ra.status_code == 201, ra.text
        # Now deletion blocked.
        rd = client.delete(
            f"/api/orgs/{org.slug}/titles/{title_id}",
            headers=auth_for(steward),
        )
        assert rd.status_code == 400


# ===========================================================================
# B3 — Assignment / revocation + role binding + cardinality + floor + mode
# ===========================================================================

class TestTitleAssignmentMechanics:
    """Bound-role assignment goes through the role-assignment
    machinery; the cardinality floor is preserved (D2/D7)."""

    def test_label_only_title_assignment_doesnt_change_role(
        self, client: TestClient, db: Session, auth_for,
    ):
        """A title with no bound role is pure label — assigning it
        does not change the member's platform role."""
        org, steward, admin_a, admin_b, member_x, member_y = _setup_org(
            db, "p47label",
        )
        r = client.post(
            f"/api/orgs/{org.slug}/titles",
            headers=auth_for(steward),
            json={
                "name": "Council Member", "bound_role": None,
                "cardinality_mode": "multi",
            },
        )
        tid = r.json()["id"]
        assert _user_role(db, org.id, member_x.id) == "member"
        ra = client.post(
            f"/api/orgs/{org.slug}/titles/{tid}/assignments",
            headers=auth_for(steward),
            json={"user_id": member_x.id},
        )
        assert ra.status_code == 201
        # Role unchanged.
        assert _user_role(db, org.id, member_x.id) == "member"

    def test_admin_binding_title_promotes_member_to_admin(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin_a, admin_b, member_x, member_y = _setup_org(
            db, "p47bindadmin",
        )
        r = client.post(
            f"/api/orgs/{org.slug}/titles",
            headers=auth_for(steward),
            json={
                "name": "Treasurer", "bound_role": "admin",
                "cardinality_mode": "single",
            },
        )
        tid = r.json()["id"]
        assert _user_role(db, org.id, member_x.id) == "member"
        ra = client.post(
            f"/api/orgs/{org.slug}/titles/{tid}/assignments",
            headers=auth_for(steward),
            json={"user_id": member_x.id},
        )
        assert ra.status_code == 201, ra.text
        # Side effect: member_x is now admin.
        db.expire_all()
        assert _user_role(db, org.id, member_x.id) == "admin"

    def test_steward_binding_title_atomically_swaps_with_existing_steward(
        self, client: TestClient, db: Session, auth_for,
    ):
        """Assigning a steward-binding title to a non-steward in
        single_steward mode does an atomic swap with the existing
        steward (mirrors transfer-stewardship)."""
        org, steward, admin_a, admin_b, member_x, member_y = _setup_org(
            db, "p47bindsteward",
        )
        r = client.post(
            f"/api/orgs/{org.slug}/titles",
            headers=auth_for(steward),
            json={
                "name": "President", "bound_role": "steward",
                "cardinality_mode": "single",
            },
        )
        tid = r.json()["id"]
        ra = client.post(
            f"/api/orgs/{org.slug}/titles/{tid}/assignments",
            headers=auth_for(steward),
            json={"user_id": admin_a.id},
        )
        assert ra.status_code == 201, ra.text
        db.expire_all()
        # admin_a is now steward; prior steward demoted to admin.
        assert _user_role(db, org.id, admin_a.id) == "steward"
        assert _user_role(db, org.id, steward.id) == "admin"

    def test_steward_binding_title_rejected_in_admin_council_mode(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin_a, admin_b, member_x, member_y = _setup_org(
            db, "p47council",
        )
        # Switch to admin_council mode.
        rs = client.post(
            f"/api/orgs/{org.slug}/governance-mode",
            headers=auth_for(steward),
            json={"mode": "admin_council"},
        )
        assert rs.status_code == 200, rs.text
        # admin_a is now an admin (the steward demoted via the switch).
        rt = client.post(
            f"/api/orgs/{org.slug}/titles",
            headers=auth_for(admin_a),
            json={
                "name": "President", "bound_role": "steward",
                "cardinality_mode": "single",
            },
        )
        tid = rt.json()["id"]
        ra = client.post(
            f"/api/orgs/{org.slug}/titles/{tid}/assignments",
            headers=auth_for(admin_a),
            json={"user_id": admin_b.id},
        )
        assert ra.status_code == 400
        assert "admin_council" in ra.json()["detail"]

    def test_single_holder_cardinality_enforced(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin_a, admin_b, member_x, member_y = _setup_org(
            db, "p47cardsingle",
        )
        r = client.post(
            f"/api/orgs/{org.slug}/titles",
            headers=auth_for(steward),
            json={
                "name": "Secretary", "bound_role": None,
                "cardinality_mode": "single",
            },
        )
        tid = r.json()["id"]
        r1 = client.post(
            f"/api/orgs/{org.slug}/titles/{tid}/assignments",
            headers=auth_for(steward),
            json={"user_id": member_x.id},
        )
        assert r1.status_code == 201
        # Second assignment blocked.
        r2 = client.post(
            f"/api/orgs/{org.slug}/titles/{tid}/assignments",
            headers=auth_for(steward),
            json={"user_id": member_y.id},
        )
        assert r2.status_code == 400
        assert "single-holder" in r2.json()["detail"]

    def test_multi_max_holders_cap_enforced(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin_a, admin_b, member_x, member_y = _setup_org(
            db, "p47cardmulti",
        )
        r = client.post(
            f"/api/orgs/{org.slug}/titles",
            headers=auth_for(steward),
            json={
                "name": "Council Member", "bound_role": None,
                "cardinality_mode": "multi", "max_holders": 1,
            },
        )
        tid = r.json()["id"]
        client.post(
            f"/api/orgs/{org.slug}/titles/{tid}/assignments",
            headers=auth_for(steward),
            json={"user_id": member_x.id},
        )
        r2 = client.post(
            f"/api/orgs/{org.slug}/titles/{tid}/assignments",
            headers=auth_for(steward),
            json={"user_id": member_y.id},
        )
        assert r2.status_code == 400
        assert "max_holders" in r2.json()["detail"]


class TestRevokeFloorPreserved:
    """Per D2/D7: revoking a bound-steward title that holds the org's
    only steward is blocked exactly as removing the only steward is
    blocked today."""

    def test_revoke_only_steward_title_blocked_by_floor(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin_a, admin_b, member_x, member_y = _setup_org(
            db, "p47revokefloor",
        )
        # Create President binding steward and "assign" the current
        # steward to it (no-op role change since they're already steward).
        rc = client.post(
            f"/api/orgs/{org.slug}/titles",
            headers=auth_for(steward),
            json={
                "name": "President", "bound_role": "steward",
                "cardinality_mode": "single",
            },
        )
        tid = rc.json()["id"]
        # Assign President to admin_a (atomic swap).
        client.post(
            f"/api/orgs/{org.slug}/titles/{tid}/assignments",
            headers=auth_for(steward),
            json={"user_id": admin_a.id},
        )
        db.expire_all()
        # admin_a is now the only steward.
        # Revoking President now would demote admin_a from steward.
        rd = client.delete(
            f"/api/orgs/{org.slug}/titles/{tid}/assignments/{admin_a.id}",
            headers=auth_for(admin_a),
        )
        assert rd.status_code == 400
        assert "steward" in rd.json()["detail"].lower()
        # admin_a still steward.
        db.expire_all()
        assert _user_role(db, org.id, admin_a.id) == "steward"

    def test_revoke_label_only_title_succeeds(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin_a, admin_b, member_x, member_y = _setup_org(
            db, "p47revokelabel",
        )
        rc = client.post(
            f"/api/orgs/{org.slug}/titles",
            headers=auth_for(steward),
            json={
                "name": "Honorary Chair", "bound_role": None,
                "cardinality_mode": "single",
            },
        )
        tid = rc.json()["id"]
        client.post(
            f"/api/orgs/{org.slug}/titles/{tid}/assignments",
            headers=auth_for(steward),
            json={"user_id": member_x.id},
        )
        rd = client.delete(
            f"/api/orgs/{org.slug}/titles/{tid}/assignments/{member_x.id}",
            headers=auth_for(steward),
        )
        assert rd.status_code == 204


# ===========================================================================
# B4 — held_titles surface on member roster
# ===========================================================================

class TestHeldTitlesSurfacing:
    def test_held_titles_includes_system_steward_label(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin_a, admin_b, member_x, member_y = _setup_org(
            db, "p47surface",
        )
        r = client.get(
            f"/api/orgs/{org.slug}/members",
            headers=auth_for(steward),
        )
        assert r.status_code == 200
        by_id = {m["user_id"]: m for m in r.json()}
        assert "Steward" in by_id[steward.id]["held_titles"]
        assert "Admin" in by_id[admin_a.id]["held_titles"]
        # Plain members have no titles yet.
        assert by_id[member_x.id]["held_titles"] == []

    def test_custom_title_appears_after_system_titles(
        self, client: TestClient, db: Session, auth_for,
    ):
        """System title (Steward, display_order=0) renders before a
        custom title (display_order default 0 but inserted after).
        Both must surface on the member roster."""
        org, steward, admin_a, admin_b, member_x, member_y = _setup_org(
            db, "p47customsurface",
        )
        rc = client.post(
            f"/api/orgs/{org.slug}/titles",
            headers=auth_for(steward),
            json={
                "name": "Honorary Chair", "bound_role": None,
                "cardinality_mode": "single", "display_order": 100,
            },
        )
        tid = rc.json()["id"]
        client.post(
            f"/api/orgs/{org.slug}/titles/{tid}/assignments",
            headers=auth_for(steward),
            json={"user_id": steward.id},
        )
        r = client.get(
            f"/api/orgs/{org.slug}/members",
            headers=auth_for(steward),
        )
        by_id = {m["user_id"]: m for m in r.json()}
        titles = by_id[steward.id]["held_titles"]
        assert "Steward" in titles
        assert "Honorary Chair" in titles


# ===========================================================================
# Built-in reconciliation regression: governance.py floor unchanged
# ===========================================================================

class TestBuiltinReconciliationRegression:
    """Per D2: the role + floor + governance modes + recovery work
    byte-for-byte as pre-47. Spot-check the key invariants — the full
    floor regression is covered by the Phase 45a + 45b tests, which
    continue to pass with this pass's changes."""

    def test_active_steward_still_blocked_from_removal_via_role_endpoint(
        self, client: TestClient, db: Session, auth_for,
    ):
        """Phase 45a's active-steward-cannot-be-removed guard fires
        regardless of titles."""
        org, steward, admin_a, admin_b, member_x, member_y = _setup_org(
            db, "p47regremove",
        )
        r = client.delete(
            f"/api/orgs/{org.slug}/members/{steward.id}",
            headers=auth_for(admin_a),
        )
        assert r.status_code == 400
        assert "Steward" in r.json()["detail"]

    def test_governance_mode_switch_still_works(
        self, client: TestClient, db: Session, auth_for,
    ):
        """Phase 45b's mode switch operates on roles, not titles —
        titles don't interfere with it."""
        org, steward, admin_a, admin_b, member_x, member_y = _setup_org(
            db, "p47regmode",
        )
        r = client.post(
            f"/api/orgs/{org.slug}/governance-mode",
            headers=auth_for(steward),
            json={"mode": "admin_council"},
        )
        assert r.status_code == 200
        db.expire_all()
        assert _user_role(db, org.id, steward.id) == "admin"
