"""Phase 49a Cluster A — multi-admin-approval disarm lockdown.

The security headline: an admin can no longer unilaterally weaken the
multi-admin approval guarantee while approval is enabled.

  * Weakening (disable / threshold decrease / wrapped-action removal)
    while enabled → routes through the approval workflow itself
    (pending action), NOT applied directly. Config unchanged until
    ratified.
  * First-enable (enabled false→true) → applies directly. You can
    always ADD a constraint on yourself unilaterally.
  * Strengthening (threshold increase, wrapped-action addition) →
    applies directly. Same logic.
  * Window-only changes → neutral, apply directly (out of the gated
    list per spec).

Tests use the PATCH /api/orgs/{slug} route — that's the actual surface
the live admin UI hits, so the lockdown must be enforced there.
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


def _make_org_with_approval(
    db: Session, slug: str, *,
    enabled: bool, thresholds: dict[str, int] | None = None,
    window_hours: int = 72,
):
    """Council org with `multi_admin_approval` config set."""
    cfg = {
        "enabled": enabled,
        "thresholds": thresholds or {},
        "window_hours": window_hours,
    }
    org = models.Organization(
        name=slug.title(), slug=slug,
        description="", join_policy="open",
        governance_mode="admin_council",
        settings={"multi_admin_approval": cfg},
    )
    db.add(org); db.flush()
    from role_seed import seed_default_roles_for_org
    seed_default_roles_for_org(db, org.id)
    db.commit()
    return org


def _org_approval(db: Session, org_id: str) -> dict:
    db.expire_all()
    org = db.get(models.Organization, org_id)
    return (org.settings or {}).get("multi_admin_approval", {})


class TestStrengtheningIsDirect:
    """First-enable + raising thresholds + adding wrapped actions all
    apply directly — you can always add a constraint on yourself."""

    def test_first_enable_applies_directly(
        self, client: TestClient, db: Session, auth_for,
    ):
        org = _make_org_with_approval(db, "p49a-fe", enabled=False)
        a1 = make_user(db, "p49a-fe-a1")
        make_org_membership(db, org_id=org.id, user_id=a1.id, role="admin")
        r = client.patch(
            f"/api/orgs/{org.slug}",
            headers=auth_for(a1),
            json={"settings": {"multi_admin_approval": {
                "enabled": True, "thresholds": {}, "window_hours": 72,
            }}},
        )
        assert r.status_code == 200, r.text
        cfg = _org_approval(db, org.id)
        assert cfg.get("enabled") is True

    def test_raising_threshold_applies_directly(
        self, client: TestClient, db: Session, auth_for,
    ):
        org = _make_org_with_approval(
            db, "p49a-raise",
            enabled=True, thresholds={"org.delete": 2},
        )
        a1 = make_user(db, "p49a-raise-a1")
        make_org_membership(db, org_id=org.id, user_id=a1.id, role="admin")
        r = client.patch(
            f"/api/orgs/{org.slug}",
            headers=auth_for(a1),
            json={"settings": {"multi_admin_approval": {
                "enabled": True, "thresholds": {"org.delete": 3},
                "window_hours": 72,
            }}},
        )
        assert r.status_code == 200, r.text
        cfg = _org_approval(db, org.id)
        assert cfg["thresholds"]["org.delete"] == 3


class TestWeakeningRoutesToPendingAction:
    """The headline security fix: weakening while enabled does NOT
    apply directly. Config stays at the old value until ratified.
    """

    def test_disable_attempt_while_enabled_does_not_apply(
        self, client: TestClient, db: Session, auth_for,
    ):
        org = _make_org_with_approval(
            db, "p49a-disarm",
            enabled=True, thresholds={"org.delete": 2},
        )
        # Multi admins so the action goes to pending (threshold=2 — the
        # initiator counts as 1, needs 1 more approver).
        a1 = make_user(db, "p49a-disarm-a1")
        a2 = make_user(db, "p49a-disarm-a2")
        make_org_membership(db, org_id=org.id, user_id=a1.id, role="admin")
        make_org_membership(db, org_id=org.id, user_id=a2.id, role="admin")
        r = client.patch(
            f"/api/orgs/{org.slug}",
            headers=auth_for(a1),
            json={"settings": {"multi_admin_approval": {
                "enabled": False, "thresholds": {}, "window_hours": 72,
            }}},
        )
        assert r.status_code == 200, r.text
        # The load-bearing assertion: enabled is STILL True.
        cfg = _org_approval(db, org.id)
        assert cfg.get("enabled") is True, (
            "Disarm attempt routed to pending action but the lockdown "
            "incorrectly applied the change anyway."
        )
        # A pending action was created.
        pending = db.query(models.PendingAdminAction).filter(
            models.PendingAdminAction.org_id == org.id,
            models.PendingAdminAction.action_type == "org.approval_config_change",
        ).all()
        assert len(pending) == 1
        assert pending[0].status in ("pending", "ratified")

    def test_threshold_decrease_does_not_apply_directly(
        self, client: TestClient, db: Session, auth_for,
    ):
        org = _make_org_with_approval(
            db, "p49a-thrlower",
            enabled=True, thresholds={"org.delete": 3},
        )
        a1 = make_user(db, "p49a-thrlower-a1")
        a2 = make_user(db, "p49a-thrlower-a2")
        make_org_membership(db, org_id=org.id, user_id=a1.id, role="admin")
        make_org_membership(db, org_id=org.id, user_id=a2.id, role="admin")
        r = client.patch(
            f"/api/orgs/{org.slug}",
            headers=auth_for(a1),
            json={"settings": {"multi_admin_approval": {
                "enabled": True,
                "thresholds": {"org.delete": 1},  # lowered
                "window_hours": 72,
            }}},
        )
        assert r.status_code == 200, r.text
        cfg = _org_approval(db, org.id)
        # Threshold STILL 3 — change is pending.
        assert cfg["thresholds"]["org.delete"] == 3


class TestRatificationAppliesTheChange:
    """When the pending action is ratified by the threshold, the
    multi_admin_approval config actually changes."""

    def test_ratification_applies_disable(
        self, client: TestClient, db: Session, auth_for,
    ):
        org = _make_org_with_approval(
            db, "p49a-ratify",
            enabled=True,
            thresholds={"org.approval_config_change": 2},
        )
        a1 = make_user(db, "p49a-ratify-a1")
        a2 = make_user(db, "p49a-ratify-a2")
        make_org_membership(db, org_id=org.id, user_id=a1.id, role="admin")
        make_org_membership(db, org_id=org.id, user_id=a2.id, role="admin")

        # a1 submits the disarm.
        r = client.patch(
            f"/api/orgs/{org.slug}",
            headers=auth_for(a1),
            json={"settings": {"multi_admin_approval": {
                "enabled": False, "thresholds": {}, "window_hours": 72,
            }}},
        )
        assert r.status_code == 200, r.text
        pending = db.query(models.PendingAdminAction).filter(
            models.PendingAdminAction.org_id == org.id,
            models.PendingAdminAction.action_type == "org.approval_config_change",
        ).one()
        # Config still enabled.
        assert _org_approval(db, org.id).get("enabled") is True

        # a2 ratifies (threshold=2, initiator counts → 2 hit → executes).
        r2 = client.post(
            f"/api/orgs/{org.slug}/admin/pending-actions/{pending.id}/approve",
            headers=auth_for(a2),
        )
        assert r2.status_code in (200, 204), r2.text
        # Now the config is disabled.
        cfg = _org_approval(db, org.id)
        assert cfg.get("enabled") is False


class TestApprovalOffMeansDirect:
    """If approval is currently off, even a 'weakening' change applies
    directly — the lockdown only protects orgs that opted in."""

    def test_change_while_disabled_applies_directly(
        self, client: TestClient, db: Session, auth_for,
    ):
        org = _make_org_with_approval(db, "p49a-off", enabled=False)
        a1 = make_user(db, "p49a-off-a1")
        make_org_membership(db, org_id=org.id, user_id=a1.id, role="admin")
        r = client.patch(
            f"/api/orgs/{org.slug}",
            headers=auth_for(a1),
            json={"settings": {"multi_admin_approval": {
                "enabled": False,
                "thresholds": {"org.delete": 1},  # lower than default
                "window_hours": 72,
            }}},
        )
        assert r.status_code == 200, r.text
        cfg = _org_approval(db, org.id)
        # Applied directly — no pending action.
        assert cfg["thresholds"]["org.delete"] == 1
        pending = db.query(models.PendingAdminAction).filter(
            models.PendingAdminAction.org_id == org.id,
            models.PendingAdminAction.action_type == "org.approval_config_change",
        ).all()
        assert pending == []


class TestWeakeningPredicate:
    """Unit-level on the is_weakening_change helper. Documents the
    spec's gate-list explicitly."""

    def test_enabled_false_to_true_is_not_weakening(self):
        from pending_actions.settings import is_weakening_change
        assert is_weakening_change(
            {"enabled": False, "thresholds": {}},
            {"enabled": True, "thresholds": {}},
        ) is False

    def test_enabled_true_to_false_is_weakening(self):
        from pending_actions.settings import is_weakening_change
        assert is_weakening_change(
            {"enabled": True, "thresholds": {}},
            {"enabled": False, "thresholds": {}},
        ) is True

    def test_threshold_decrease_is_weakening(self):
        from pending_actions.settings import is_weakening_change
        assert is_weakening_change(
            {"enabled": True, "thresholds": {"org.delete": 3}},
            {"enabled": True, "thresholds": {"org.delete": 2}},
        ) is True

    def test_threshold_increase_is_not_weakening(self):
        from pending_actions.settings import is_weakening_change
        assert is_weakening_change(
            {"enabled": True, "thresholds": {"org.delete": 2}},
            {"enabled": True, "thresholds": {"org.delete": 3}},
        ) is False

    def test_window_only_change_is_not_weakening(self):
        from pending_actions.settings import is_weakening_change
        assert is_weakening_change(
            {"enabled": True, "thresholds": {}, "window_hours": 72},
            {"enabled": True, "thresholds": {}, "window_hours": 24},
        ) is False
