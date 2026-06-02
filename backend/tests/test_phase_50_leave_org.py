"""Phase 50 — self-service leave-org tests.

Verification matrix (per spec §"Verification matrix"):
  * Floor reuse (D1): `count_active_governors(exclude_user_id=...)`
    gates identically to remove_member.
  * Transfer-first then leave (D2): two distinct operations; the
    second is unblocked only after the first.
  * Title cleanup (D3): custom title assignments revoked on leave;
    bound-role for a non-sole-governor revoked + role removed.
  * Delegation cleanup (B3): leaver's outgoing org-scoped delegations
    cleaned; incoming-delegation behavior asserted (the engine's
    eligibility filter tolerates a departed delegate naturally).
  * Informed consent only (D5): no Phase 44 wrap — assert the
    endpoint executes directly.
  * `org.left` audit emitted with actor = the leaver.
  * Reusable per-org logic: `leave_org` is callable as a function
    (not welded into the route).
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
    db: Session, slug: str, *, governance_mode: str = "single_steward",
) -> models.Organization:
    org = models.Organization(
        name=slug.title(), slug=slug,
        description="", join_policy="open",
        governance_mode=governance_mode,
        settings={
            "default_deliberation_days": 1,
            "default_voting_days": 7,
            "default_pass_threshold": 0.50,
            "default_quorum_threshold": 0.40,
            "allowed_voting_methods": ["binary"],
        },
    )
    db.add(org); db.flush()
    from role_seed import seed_default_roles_for_org
    from org_titles import seed_system_titles_for_org
    seed_default_roles_for_org(db, org.id)
    seed_system_titles_for_org(db, org.id)
    db.commit()
    return org


def _is_member(db: Session, org_id: str, user_id: str) -> bool:
    return db.query(models.OrgMembership).filter_by(
        org_id=org_id, user_id=user_id, status="active",
    ).first() is not None


def _user_role_key(db: Session, org_id: str, user_id: str) -> str | None:
    m = db.query(models.OrgMembership).filter_by(
        org_id=org_id, user_id=user_id, status="active",
    ).first()
    if m is None or m.role_id is None:
        return None
    return db.get(models.Role, m.role_id).system_key


class TestOrdinaryMemberLeavesImmediately:
    def test_member_leaves_cleanly(
        self, client: TestClient, db: Session, auth_for,
    ):
        org = _make_org(db, "p50-member")
        steward = make_user(db, "p50-member-s")
        m = make_user(db, "p50-member-m")
        make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
        make_org_membership(db, org_id=org.id, user_id=m.id, role="member")
        r = client.post(
            f"/api/orgs/{org.slug}/leave",
            headers=auth_for(m),
        )
        assert r.status_code == 200, r.text
        assert _is_member(db, org.id, m.id) is False
        # Steward unaffected.
        assert _user_role_key(db, org.id, steward.id) == "steward"


class TestSoleStewardBlockedThenTransferThenLeave:
    def test_sole_steward_leave_blocked_with_transfer_required(
        self, client: TestClient, db: Session, auth_for,
    ):
        org = _make_org(db, "p50-soles")
        steward = make_user(db, "p50-soles-s")
        admin = make_user(db, "p50-soles-a")
        make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
        make_org_membership(db, org_id=org.id, user_id=admin.id, role="admin")
        r = client.post(
            f"/api/orgs/{org.slug}/leave",
            headers=auth_for(steward),
        )
        assert r.status_code == 409
        body = r.json()
        # Structured payload for the FE's inline transfer flow.
        assert body["detail"]["error"] == "transfer_required"
        assert body["detail"]["mode"] == "single_steward"
        # Steward still a member (D1 — leave not applied on the
        # transfer_required path).
        assert _user_role_key(db, org.id, steward.id) == "steward"

    def test_transfer_then_leave_succeeds(
        self, client: TestClient, db: Session, auth_for,
    ):
        org = _make_org(db, "p50-tnl")
        steward = make_user(db, "p50-tnl-s")
        admin = make_user(db, "p50-tnl-a")
        make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
        make_org_membership(db, org_id=org.id, user_id=admin.id, role="admin")
        # Step 1: transfer stewardship via the existing 45a endpoint.
        r1 = client.post(
            f"/api/orgs/{org.slug}/transfer-stewardship",
            headers=auth_for(steward),
            json={"target_user_id": admin.id},
        )
        assert r1.status_code == 200, r1.text
        db.expire_all()
        # Steward is now admin; admin is now steward.
        assert _user_role_key(db, org.id, steward.id) == "admin"
        assert _user_role_key(db, org.id, admin.id) == "steward"
        # Step 2: leave now succeeds (steward is no longer the sole
        # governor; in fact they're not even a governor anymore).
        r2 = client.post(
            f"/api/orgs/{org.slug}/leave",
            headers=auth_for(steward),
        )
        assert r2.status_code == 200, r2.text
        assert _is_member(db, org.id, steward.id) is False


class TestLastAdminInCouncilModeBlocked:
    def test_last_admin_blocked_with_transfer_required(
        self, client: TestClient, db: Session, auth_for,
    ):
        org = _make_org(db, "p50-lastadm", governance_mode="admin_council")
        # admin_council mode means top-tier is admin. With a single
        # active admin, leaving must require a handoff first.
        a1 = make_user(db, "p50-lastadm-a1")
        member = make_user(db, "p50-lastadm-m")
        make_org_membership(db, org_id=org.id, user_id=a1.id, role="admin")
        make_org_membership(db, org_id=org.id, user_id=member.id, role="member")
        r = client.post(
            f"/api/orgs/{org.slug}/leave",
            headers=auth_for(a1),
        )
        assert r.status_code == 409
        body = r.json()
        assert body["detail"]["error"] == "transfer_required"
        assert body["detail"]["mode"] == "admin_council"


class TestTitleCleanupOnLeave:
    def test_custom_title_revoked_on_leave(
        self, client: TestClient, db: Session, auth_for,
    ):
        org = _make_org(db, "p50-titles")
        steward = make_user(db, "p50-titles-s")
        m = make_user(db, "p50-titles-m")
        make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
        make_org_membership(db, org_id=org.id, user_id=m.id, role="member")
        # Add a custom (non-system) title held by the leaver.
        title = models.OrgTitle(
            org_id=org.id, name="Council Member",
            cardinality_mode="single", fill_method="assigned",
            is_system=False,
        )
        db.add(title); db.flush()
        db.add(models.OrgTitleAssignment(title_id=title.id, user_id=m.id))
        db.commit()
        # Leave.
        r = client.post(
            f"/api/orgs/{org.slug}/leave",
            headers=auth_for(m),
        )
        assert r.status_code == 200, r.text
        # Title assignment row gone.
        a = db.query(models.OrgTitleAssignment).filter_by(
            title_id=title.id, user_id=m.id,
        ).first()
        assert a is None
        # The audit entry for the revoke is present.
        rev = db.query(models.AuditLog).filter(
            models.AuditLog.action == "title.revoked",
            models.AuditLog.target_id == title.id,
        ).all()
        assert any(
            (e.details or {}).get("trigger") == "member_left"
            for e in rev
        )


class TestDelegationCleanupOnLeave:
    def test_outgoing_delegations_deleted(
        self, client: TestClient, db: Session, auth_for,
    ):
        org = _make_org(db, "p50-deleg")
        steward = make_user(db, "p50-deleg-s")
        m = make_user(db, "p50-deleg-m")
        target = make_user(db, "p50-deleg-t")
        make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
        make_org_membership(db, org_id=org.id, user_id=m.id, role="member")
        make_org_membership(db, org_id=org.id, user_id=target.id, role="member")
        # Outgoing delegation from m → target.
        db.add(models.Delegation(
            org_id=org.id, delegator_id=m.id, delegate_id=target.id,
        ))
        db.commit()
        r = client.post(
            f"/api/orgs/{org.slug}/leave",
            headers=auth_for(m),
        )
        assert r.status_code == 200, r.text
        out = db.query(models.Delegation).filter_by(
            org_id=org.id, delegator_id=m.id,
        ).all()
        assert out == []

    def test_incoming_delegations_NOT_deleted_but_engine_tolerates(
        self, db: Session,
    ):
        """B3 finding: ``eligible_voter_ids_for_proposal`` filters
        delegates by active OrgMembership, so an incoming delegation
        to a departed user resolves to no-vote at tally time without
        explicit row cleanup. We confirm here that the leave path
        does NOT delete the incoming delegation row (per the
        documented behavior) — leaving the row + the engine's
        eligibility filter handle the case naturally."""
        from org_leave import leave_org
        org = _make_org(db, "p50-incoming")
        steward = make_user(db, "p50-incoming-s")
        m = make_user(db, "p50-incoming-m")
        delegator = make_user(db, "p50-incoming-d")
        make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
        make_org_membership(db, org_id=org.id, user_id=m.id, role="member")
        make_org_membership(db, org_id=org.id, user_id=delegator.id, role="member")
        # Incoming delegation: delegator → m.
        db.add(models.Delegation(
            org_id=org.id, delegator_id=delegator.id, delegate_id=m.id,
        ))
        db.commit()
        # Leave (m).
        leave_org(db, org, m)
        db.commit()
        # Incoming delegation row still there — the engine handles
        # the departed-delegate case via the eligibility filter.
        incoming = db.query(models.Delegation).filter_by(
            org_id=org.id, delegator_id=delegator.id, delegate_id=m.id,
        ).all()
        assert len(incoming) == 1


class TestAuditOrgLeftEmitted:
    def test_org_left_audit_emitted_with_leaver_actor(
        self, client: TestClient, db: Session, auth_for,
    ):
        org = _make_org(db, "p50-audit")
        steward = make_user(db, "p50-audit-s")
        m = make_user(db, "p50-audit-m")
        make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
        make_org_membership(db, org_id=org.id, user_id=m.id, role="member")
        r = client.post(
            f"/api/orgs/{org.slug}/leave",
            headers=auth_for(m),
        )
        assert r.status_code == 200, r.text
        entries = db.query(models.AuditLog).filter(
            models.AuditLog.action == "org.left",
            models.AuditLog.target_id == org.id,
        ).all()
        assert any(e.actor_id == m.id for e in entries)


class TestReusableLeaveLogic:
    """The core leave logic is a callable function (not welded into
    the route) so the future account-deletion path can loop it."""

    def test_leave_org_callable_directly(self, db: Session):
        from org_leave import leave_org
        org = _make_org(db, "p50-callable")
        steward = make_user(db, "p50-callable-s")
        m = make_user(db, "p50-callable-m")
        make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
        make_org_membership(db, org_id=org.id, user_id=m.id, role="member")
        result = leave_org(db, org, m)
        db.commit()
        assert result["status"] == "ok"
        assert _is_member(db, org.id, m.id) is False


class TestLeaveIsNotApprovalGated:
    """D5 — leaving is unilateral, NOT routed through Phase 44 even
    when the org has multi_admin_approval enabled."""

    def test_leave_with_approval_enabled_still_executes_directly(
        self, client: TestClient, db: Session, auth_for,
    ):
        org = _make_org(db, "p50-nogate")
        # Enable Phase 44 approval at the org level.
        org.settings = {
            **(org.settings or {}),
            "multi_admin_approval": {
                "enabled": True, "thresholds": {}, "window_hours": 72,
            },
        }
        db.commit()
        steward = make_user(db, "p50-nogate-s")
        m = make_user(db, "p50-nogate-m")
        make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
        make_org_membership(db, org_id=org.id, user_id=m.id, role="member")
        r = client.post(
            f"/api/orgs/{org.slug}/leave",
            headers=auth_for(m),
        )
        # Direct execution — no submitted_for_approval / no 202.
        assert r.status_code == 200, r.text
        assert _is_member(db, org.id, m.id) is False
        # No pending action was created for this leave.
        pending = db.query(models.PendingAdminAction).filter(
            models.PendingAdminAction.org_id == org.id,
        ).all()
        assert pending == []
