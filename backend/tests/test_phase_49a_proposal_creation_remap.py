"""Phase 49a Cluster B — proposal_creation_mode → allow_cosign_petition remap.

Verifies the new gating model:
  * Members with `proposal.create` create directly.
  * Members without `proposal.create` AND
    `settings.allow_cosign_petition=True` → cosign-gathering path.
  * Otherwise: 403.

And confirms the migration mapping preserves each old mode's
effective behavior (the B5 parity assertion).
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


def _make_org(
    db: Session, slug: str, *,
    allow_cosign_petition: bool = False,
    cosign_threshold: int = 3,
) -> models.Organization:
    org = models.Organization(
        name=slug.title(), slug=slug,
        description="", join_policy="open",
        settings={
            "default_deliberation_days": 1,
            "default_voting_days": 7,
            "default_pass_threshold": 0.50,
            "default_quorum_threshold": 0.40,
            "allowed_voting_methods": ["binary"],
            "allow_cosign_petition": allow_cosign_petition,
            "cosign": {"threshold": cosign_threshold, "expiry_hours": 168},
        },
    )
    db.add(org); db.flush()
    from role_seed import seed_default_roles_for_org
    seed_default_roles_for_org(db, org.id)
    db.commit()
    return org


def _grant_member_proposal_create(db: Session, org: models.Organization) -> None:
    member_role = db.query(models.Role).filter(
        models.Role.org_id == org.id,
        models.Role.system_key == "member",
    ).first()
    db.add(models.RolePermission(
        role_id=member_role.id,
        permission_key="proposal.create",
        enabled=True,
    ))
    db.commit()


def _body() -> dict:
    return {
        "title": "P49a test", "body": "x",
        "voting_method": "binary", "num_winners": 1,
    }


class TestMemberWithPermissionCreatesDirectly:
    def test_member_with_proposal_create_goes_direct_regardless_of_toggle(
        self, client: TestClient, db: Session, auth_for,
    ):
        """The decision tree's first branch: holding ``proposal.create``
        means direct creation, regardless of the cosign-petition toggle."""
        org = _make_org(db, "p49a-direct", allow_cosign_petition=True)
        m = make_user(db, "p49a-direct-m")
        make_org_membership(db, org_id=org.id, user_id=m.id, role="member")
        _grant_member_proposal_create(db, org)
        r = client.post(
            f"/api/orgs/{org.slug}/proposals",
            headers=auth_for(m), json=_body(),
        )
        assert r.status_code == 201, r.text
        assert r.json()["is_cosign_gated"] is False


class TestMemberWithoutPermissionUsesCosign:
    def test_member_without_permission_with_toggle_on_routes_to_cosign(
        self, client: TestClient, db: Session, auth_for,
    ):
        org = _make_org(db, "p49a-cosign", allow_cosign_petition=True)
        m = make_user(db, "p49a-cosign-m")
        make_org_membership(db, org_id=org.id, user_id=m.id, role="member")
        # NO _grant_member_proposal_create.
        r = client.post(
            f"/api/orgs/{org.slug}/proposals",
            headers=auth_for(m), json=_body(),
        )
        assert r.status_code == 201, r.text
        assert r.json()["is_cosign_gated"] is True


class TestMemberWithoutPermissionWithoutToggleIs403:
    def test_no_permission_no_toggle_returns_403(
        self, client: TestClient, db: Session, auth_for,
    ):
        org = _make_org(db, "p49a-403", allow_cosign_petition=False)
        m = make_user(db, "p49a-403-m")
        make_org_membership(db, org_id=org.id, user_id=m.id, role="member")
        r = client.post(
            f"/api/orgs/{org.slug}/proposals",
            headers=auth_for(m), json=_body(),
        )
        assert r.status_code == 403
        # No mode-name in the message — phase-number-free per C2 / Z.
        detail = r.json()["detail"].lower()
        assert "admin_only" not in detail
        assert "cosign_required" not in detail
        assert "permission" in detail


class TestOrgOutSurface:
    def test_orgout_surfaces_allow_cosign_petition(
        self, client: TestClient, db: Session, auth_for,
    ):
        org = _make_org(db, "p49a-surface", allow_cosign_petition=True)
        s = make_user(db, "p49a-surface-s")
        make_org_membership(db, org_id=org.id, user_id=s.id, role="steward")
        r = client.get(f"/api/orgs/{org.slug}", headers=auth_for(s))
        assert r.status_code == 200
        body = r.json()
        assert body["allow_cosign_petition"] is True
        # Legacy field is gone from the response.
        assert "proposal_creation_mode" not in body


class TestParityHelper:
    """B5 parity assertion mirrors the Phase 48 B0 helper pattern: each
    old mode's effective behavior is preserved post-migration. Since
    the migration's data-backfill happens at alembic-upgrade time and
    the test suite uses fresh in-memory SQLite (no migration history),
    these assertions are integration-shaped: build orgs matching each
    pre-49a end-state and confirm the gate makes the same decision the
    old code path would have."""

    def test_open_mode_parity(
        self, client: TestClient, db: Session, auth_for,
    ):
        """Pre-49a ``open`` orgs: member without grant gets 403 (no
        change). Member with grant creates direct (no change)."""
        # Members defaultly lack proposal.create — that IS the pre-49a
        # open mode's member behavior with the default grant matrix.
        org = _make_org(db, "p49a-parity-open", allow_cosign_petition=False)
        m = make_user(db, "p49a-parity-open-m")
        make_org_membership(db, org_id=org.id, user_id=m.id, role="member")
        r = client.post(
            f"/api/orgs/{org.slug}/proposals",
            headers=auth_for(m), json=_body(),
        )
        # Matches pre-49a open: member without proposal.create -> 403.
        assert r.status_code == 403

    def test_cosign_required_mode_parity(
        self, client: TestClient, db: Session, auth_for,
    ):
        """Pre-49a ``cosign_required`` orgs: member-tier creates entered
        gathering state (regardless of their explicit proposal.create
        grant, because the mode override took precedence). The migration
        REVOKES member proposal.create + sets toggle=true so the new
        model produces the same effective outcome."""
        org = _make_org(db, "p49a-parity-cosign", allow_cosign_petition=True)
        m = make_user(db, "p49a-parity-cosign-m")
        make_org_membership(db, org_id=org.id, user_id=m.id, role="member")
        # The migration revokes member proposal.create for old
        # cosign_required orgs — emulate the post-migration state.
        r = client.post(
            f"/api/orgs/{org.slug}/proposals",
            headers=auth_for(m), json=_body(),
        )
        assert r.status_code == 201, r.text
        assert r.json()["is_cosign_gated"] is True

    def test_admin_only_mode_parity(
        self, client: TestClient, db: Session, auth_for,
    ):
        """Pre-49a ``admin_only`` orgs: member-tier blocked with the
        explicit admin_only message. Post-migration: same 403, but
        with a permission-shaped message (no mode-name leakage)."""
        org = _make_org(db, "p49a-parity-admonly", allow_cosign_petition=False)
        m = make_user(db, "p49a-parity-admonly-m")
        make_org_membership(db, org_id=org.id, user_id=m.id, role="member")
        # Member without proposal.create + toggle off -> 403.
        r = client.post(
            f"/api/orgs/{org.slug}/proposals",
            headers=auth_for(m), json=_body(),
        )
        assert r.status_code == 403
