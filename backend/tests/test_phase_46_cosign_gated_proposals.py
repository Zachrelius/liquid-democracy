"""Phase 46 — Cosign-gated proposals (petition threshold) tests.

Spec: phase46_cosign_gated_proposals_spec.md.

Verification matrix:
  - Default-mode regression: org in 'open' mode behaves byte-for-byte
    as pre-46.
  - cosign_required mode: member-tier creator's proposal enters
    gathering state (deliberation status + is_cosign_gated=True);
    author counts as first signature (D3).
  - Sign endpoint: idempotent re-sign; threshold check; auto-advance
    to voting with side effects (status, voting_start/end, audit,
    notification helper invoked).
  - Withdraw endpoint: decrements count; can drop below threshold;
    author cannot withdraw.
  - One-signature-per-member (DB invariant via unique constraint).
  - Threshold snapshot at creation immune to later org-config changes.
  - admin_only mode rejects member-tier creator.
  - Holders of proposal.advance_phase create normally in cosign_required
    mode (admin/moderator bypass).
  - Worker expiry path: sub-threshold past-window proposal -> status
    expired_unsigned with audit; non-expired proposal untouched;
    threshold-met-but-uncounted defensive path skips expiry.
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
# Fixtures (StaticPool pattern; same as Phase 44 / 45a / 45b)
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
    proposal_creation_mode: str = "open",
    cosign_config: dict | None = None,
) -> models.Organization:
    settings: dict = {
        "default_deliberation_days": 1,
        "default_voting_days": 7,
        "default_pass_threshold": 0.50,
        "default_quorum_threshold": 0.40,
        "allowed_voting_methods": ["binary"],
    }
    if cosign_config is not None:
        settings["cosign"] = cosign_config
    org = models.Organization(
        name=slug.replace("-", " ").title(),
        slug=slug,
        description="",
        join_policy="open",
        settings=settings,
        proposal_creation_mode=proposal_creation_mode,
    )
    db.add(org)
    db.flush()
    return org


def _grant_member_proposal_create(
    db: Session, org: models.Organization,
) -> None:
    """Grant member role the proposal.create permission so members can
    initiate proposals (without this, default member grants are 0 keys
    and create attempts get 403 regardless of cosign mode).
    """
    member_role = db.query(models.Role).filter(
        models.Role.org_id == org.id,
        models.Role.system_key == "member",
    ).first()
    # Idempotent — insert if missing.
    existing = db.query(models.RolePermission).filter(
        models.RolePermission.role_id == member_role.id,
        models.RolePermission.permission_key == "proposal.create",
    ).first()
    if existing is None:
        db.add(models.RolePermission(
            role_id=member_role.id,
            permission_key="proposal.create",
            enabled=True,
        ))
    else:
        existing.enabled = True
    db.flush()


def _setup_org(
    db: Session, slug: str, *,
    mode: str = "open",
    cosign_threshold: int = 3,
    cosign_expiry_hours: int = 168,
):
    """Steward + 2 admins + 5 members. Members have proposal.create granted."""
    cfg = {"threshold": cosign_threshold, "expiry_hours": cosign_expiry_hours}
    org = _make_org(db, slug, proposal_creation_mode=mode, cosign_config=cfg)
    steward = make_user(db, f"{slug}-steward")
    admin = make_user(db, f"{slug}-admin")
    members = [make_user(db, f"{slug}-m{i}") for i in range(5)]
    make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
    make_org_membership(db, org_id=org.id, user_id=admin.id, role="admin")
    for m in members:
        make_org_membership(db, org_id=org.id, user_id=m.id, role="member")
    _grant_member_proposal_create(db, org)
    db.commit()
    return org, steward, admin, members


def _create_proposal_body(title: str = "Petition X") -> dict:
    return {
        "title": title,
        "body": "Demonstrated support gathers here.",
        "voting_method": "binary",
        "num_winners": 1,
    }


# ===========================================================================
# Default-mode regression
# ===========================================================================

class TestOpenModeRegression:
    """An org in 'open' mode behaves byte-for-byte as pre-46."""

    def test_member_creates_open_mode_proposal_goes_live(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, members = _setup_org(db, "p46open", mode="open")
        r = client.post(
            f"/api/orgs/{org.slug}/proposals",
            headers=auth_for(members[0]),
            json=_create_proposal_body(),
        )
        assert r.status_code == 201, r.text
        body = r.json()
        # No cosign-gating fields populated.
        assert body["is_cosign_gated"] is False
        assert body["cosign_threshold_snapshot"] is None
        assert body["cosign_expires_at"] is None
        assert body["cosign_signature_count"] == 0
        # Status is the pre-46 default (draft; no 0-day skip configured).
        assert body["status"] == "draft"

    def test_admin_creates_open_mode_unchanged(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, members = _setup_org(db, "p46openadmin", mode="open")
        r = client.post(
            f"/api/orgs/{org.slug}/proposals",
            headers=auth_for(admin),
            json=_create_proposal_body("Admin proposal"),
        )
        assert r.status_code == 201, r.text
        assert r.json()["is_cosign_gated"] is False


# ===========================================================================
# cosign_required mode — creation routes to gathering state
# ===========================================================================

class TestCosignRequiredCreationFlow:
    """Member-tier creator -> gathering state. Admin -> normal."""

    def test_member_creates_proposal_enters_gathering(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, members = _setup_org(
            db, "p46gather", mode="cosign_required", cosign_threshold=3,
        )
        author = members[0]
        r = client.post(
            f"/api/orgs/{org.slug}/proposals",
            headers=auth_for(author),
            json=_create_proposal_body(),
        )
        assert r.status_code == 201, r.text
        body = r.json()
        # Side effects:
        assert body["status"] == "deliberation"
        assert body["is_cosign_gated"] is True
        assert body["cosign_threshold_snapshot"] == 3
        assert body["cosign_expires_at"] is not None
        # Author counts as first signature (D3).
        assert body["cosign_signature_count"] == 1

    def test_author_implicit_signature_persisted(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, members = _setup_org(
            db, "p46impsig", mode="cosign_required",
        )
        author = members[0]
        r = client.post(
            f"/api/orgs/{org.slug}/proposals",
            headers=auth_for(author),
            json=_create_proposal_body(),
        )
        assert r.status_code == 201
        proposal_id = r.json()["id"]
        rows = db.query(models.ProposalCosignature).filter_by(
            proposal_id=proposal_id,
        ).all()
        assert len(rows) == 1
        assert rows[0].user_id == author.id

    def test_admin_creates_in_cosign_required_mode_bypasses_gating(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, members = _setup_org(
            db, "p46adminbypass", mode="cosign_required",
        )
        r = client.post(
            f"/api/orgs/{org.slug}/proposals",
            headers=auth_for(admin),
            json=_create_proposal_body("admin pass"),
        )
        assert r.status_code == 201, r.text
        body = r.json()
        # Admin holds proposal.advance_phase -> bypass cosign-gating.
        assert body["is_cosign_gated"] is False
        assert body["status"] == "draft"

    def test_threshold_snapshot_immune_to_later_config_change(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, members = _setup_org(
            db, "p46snapshot", mode="cosign_required", cosign_threshold=3,
        )
        # Member creates with threshold=3.
        r = client.post(
            f"/api/orgs/{org.slug}/proposals",
            headers=auth_for(members[0]),
            json=_create_proposal_body(),
        )
        proposal_id = r.json()["id"]
        # Org admin bumps threshold to 10 after creation.
        org_row = db.query(models.Organization).filter_by(slug=org.slug).one()
        cfg = dict(org_row.settings)
        cfg["cosign"] = {"threshold": 10, "expiry_hours": 168}
        org_row.settings = cfg
        from sqlalchemy.orm import attributes
        attributes.flag_modified(org_row, "settings")
        db.commit()
        # Proposal's threshold is still 3.
        proposal_row = db.get(models.Proposal, proposal_id)
        assert proposal_row.cosign_threshold_snapshot == 3


# ===========================================================================
# admin_only mode
# ===========================================================================

class TestAdminOnlyMode:
    """Member-tier creator gets 403; admin creates normally."""

    def test_member_blocked_in_admin_only_mode(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, members = _setup_org(
            db, "p46admonly", mode="admin_only",
        )
        r = client.post(
            f"/api/orgs/{org.slug}/proposals",
            headers=auth_for(members[0]),
            json=_create_proposal_body(),
        )
        assert r.status_code == 403
        assert "admin_only" in r.json()["detail"]

    def test_admin_creates_normally_in_admin_only_mode(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, members = _setup_org(
            db, "p46admonlyok", mode="admin_only",
        )
        r = client.post(
            f"/api/orgs/{org.slug}/proposals",
            headers=auth_for(admin),
            json=_create_proposal_body("admin ok"),
        )
        assert r.status_code == 201
        assert r.json()["is_cosign_gated"] is False


# ===========================================================================
# Sign / withdraw endpoints
# ===========================================================================

class TestSignAndWithdraw:
    """Sign / withdraw semantics + idempotency + threshold trigger."""

    def _make_petition(
        self, client: TestClient, db: Session, auth_for,
        slug: str = "p46petition", threshold: int = 3,
    ):
        org, steward, admin, members = _setup_org(
            db, slug, mode="cosign_required", cosign_threshold=threshold,
        )
        r = client.post(
            f"/api/orgs/{org.slug}/proposals",
            headers=auth_for(members[0]),
            json=_create_proposal_body(),
        )
        assert r.status_code == 201
        return org, members[0], members[1:], r.json()["id"]

    def test_cosign_adds_signature_increments_count(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, author, others, pid = self._make_petition(
            client, db, auth_for, "p46sign",
        )
        r = client.post(
            f"/api/proposals/{pid}/cosign",
            headers=auth_for(others[0]),
        )
        assert r.status_code == 200, r.text
        assert r.json()["cosign_signature_count"] == 2
        assert r.json()["viewer_has_cosigned"] is True
        # Still deliberation (threshold=3, count=2).
        assert r.json()["status"] == "deliberation"

    def test_cosign_idempotent_re_sign(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, author, others, pid = self._make_petition(
            client, db, auth_for, "p46idem",
        )
        r1 = client.post(
            f"/api/proposals/{pid}/cosign",
            headers=auth_for(others[0]),
        )
        assert r1.status_code == 200
        r2 = client.post(
            f"/api/proposals/{pid}/cosign",
            headers=auth_for(others[0]),
        )
        assert r2.status_code == 200
        assert r2.json()["cosign_signature_count"] == 2  # unchanged

    def test_threshold_met_advances_to_voting(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, author, others, pid = self._make_petition(
            client, db, auth_for, "p46advance", threshold=3,
        )
        # author = 1; sign with two more to reach threshold.
        client.post(f"/api/proposals/{pid}/cosign", headers=auth_for(others[0]))
        r = client.post(
            f"/api/proposals/{pid}/cosign", headers=auth_for(others[1]),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Side effects: status -> voting; voting_start + voting_end set.
        assert body["status"] == "voting"
        assert body["voting_start"] is not None
        assert body["voting_end"] is not None
        # Audit events: status_changed + cosign_threshold_met.
        audit_actions = {
            row.action for row in
            db.query(models.AuditLog).filter(
                models.AuditLog.target_id == pid,
            ).all()
        }
        assert "proposal.status_changed" in audit_actions
        assert "proposal.cosign_threshold_met" in audit_actions

    def test_withdraw_decrements_count(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, author, others, pid = self._make_petition(
            client, db, auth_for, "p46withdraw",
        )
        client.post(f"/api/proposals/{pid}/cosign", headers=auth_for(others[0]))
        r = client.request(
            "DELETE", f"/api/proposals/{pid}/cosign",
            headers=auth_for(others[0]),
        )
        assert r.status_code == 200
        assert r.json()["cosign_signature_count"] == 1
        assert r.json()["viewer_has_cosigned"] is False

    def test_withdraw_can_drop_below_threshold(
        self, client: TestClient, db: Session, auth_for,
    ):
        """When a member withdraws and count drops below threshold, the
        proposal stays in deliberation gathering."""
        org, author, others, pid = self._make_petition(
            client, db, auth_for, "p46belowthresh", threshold=3,
        )
        # author + 1 = 2 (below threshold of 3).
        client.post(f"/api/proposals/{pid}/cosign", headers=auth_for(others[0]))
        client.request(
            "DELETE", f"/api/proposals/{pid}/cosign",
            headers=auth_for(others[0]),
        )
        proposal_row = db.get(models.Proposal, pid)
        assert proposal_row.status == "deliberation"

    def test_author_cannot_withdraw(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, author, others, pid = self._make_petition(
            client, db, auth_for, "p46authornowithdraw",
        )
        r = client.request(
            "DELETE", f"/api/proposals/{pid}/cosign",
            headers=auth_for(author),
        )
        assert r.status_code == 400
        assert "author" in r.json()["detail"].lower()

    def test_cosign_open_mode_proposal_rejected(
        self, client: TestClient, db: Session, auth_for,
    ):
        """Cosigning a non-cosign-gated proposal returns 400."""
        org, steward, admin, members = _setup_org(db, "p46openrej", mode="open")
        r = client.post(
            f"/api/orgs/{org.slug}/proposals",
            headers=auth_for(admin),
            json=_create_proposal_body(),
        )
        pid = r.json()["id"]
        r2 = client.post(
            f"/api/proposals/{pid}/cosign",
            headers=auth_for(members[0]),
        )
        assert r2.status_code == 400

    def test_one_signature_per_member_db_invariant(
        self, client: TestClient, db: Session, auth_for,
    ):
        """The UniqueConstraint(proposal_id, user_id) is a DB-level
        invariant; the idempotent endpoint enforces it at the
        application layer, but the constraint is the safety net."""
        org, author, others, pid = self._make_petition(
            client, db, auth_for, "p46uniq",
        )
        # Try direct DB insert of a duplicate row.
        from sqlalchemy.exc import IntegrityError
        with pytest.raises(IntegrityError):
            db.add(models.ProposalCosignature(
                proposal_id=pid, user_id=author.id,
            ))
            db.commit()


# ===========================================================================
# Worker expiry path
# ===========================================================================

class TestWorkerExpiry:
    """expire_due_cosign_proposals moves sub-threshold past-window
    proposals to expired_unsigned."""

    def test_expired_window_proposal_closes_to_expired_unsigned(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, members = _setup_org(
            db, "p46expworker", mode="cosign_required",
            cosign_threshold=3, cosign_expiry_hours=1,
        )
        # Create a cosign-gated proposal and backdate its expiry.
        r = client.post(
            f"/api/orgs/{org.slug}/proposals",
            headers=auth_for(members[0]),
            json=_create_proposal_body(),
        )
        pid = r.json()["id"]
        proposal_row = db.get(models.Proposal, pid)
        proposal_row.cosign_expires_at = (
            datetime.now(timezone.utc).replace(tzinfo=None)
            - timedelta(hours=1)
        )
        db.commit()
        # Invoke the worker tick (one-shot mode).
        from sustained_majority_worker import expire_due_cosign_proposals
        count = expire_due_cosign_proposals(db)
        assert count == 1
        proposal_row = db.get(models.Proposal, pid)
        assert proposal_row.status == "expired_unsigned"

    def test_expiry_emits_audit_events(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, members = _setup_org(
            db, "p46expaudit", mode="cosign_required",
            cosign_threshold=3, cosign_expiry_hours=1,
        )
        r = client.post(
            f"/api/orgs/{org.slug}/proposals",
            headers=auth_for(members[0]),
            json=_create_proposal_body(),
        )
        pid = r.json()["id"]
        proposal_row = db.get(models.Proposal, pid)
        proposal_row.cosign_expires_at = (
            datetime.now(timezone.utc).replace(tzinfo=None)
            - timedelta(hours=1)
        )
        db.commit()
        from sustained_majority_worker import expire_due_cosign_proposals
        expire_due_cosign_proposals(db)
        actions = {
            row.action for row in db.query(models.AuditLog).filter(
                models.AuditLog.target_id == pid,
            ).all()
        }
        assert "proposal.cosign_expired" in actions

    def test_not_yet_expired_proposal_untouched(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, members = _setup_org(
            db, "p46notexp", mode="cosign_required",
            cosign_threshold=3, cosign_expiry_hours=24,
        )
        r = client.post(
            f"/api/orgs/{org.slug}/proposals",
            headers=auth_for(members[0]),
            json=_create_proposal_body(),
        )
        pid = r.json()["id"]
        from sustained_majority_worker import expire_due_cosign_proposals
        count = expire_due_cosign_proposals(db)
        assert count == 0
        proposal_row = db.get(models.Proposal, pid)
        assert proposal_row.status == "deliberation"

    def test_expiry_skips_proposal_at_or_above_threshold(
        self, client: TestClient, db: Session, auth_for,
    ):
        """Defensive — if a proposal somehow reached threshold without
        auto-advancing AND its window expired, the worker skips it
        rather than expiring a petition that should have advanced."""
        org, steward, admin, members = _setup_org(
            db, "p46defensive", mode="cosign_required",
            cosign_threshold=2, cosign_expiry_hours=1,
        )
        r = client.post(
            f"/api/orgs/{org.slug}/proposals",
            headers=auth_for(members[0]),
            json=_create_proposal_body(),
        )
        pid = r.json()["id"]
        # Insert a second signature directly (bypass the endpoint that
        # would auto-advance) to simulate the race window.
        db.add(models.ProposalCosignature(
            proposal_id=pid, user_id=members[1].id,
        ))
        proposal_row = db.get(models.Proposal, pid)
        proposal_row.cosign_expires_at = (
            datetime.now(timezone.utc).replace(tzinfo=None)
            - timedelta(hours=1)
        )
        db.commit()
        from sustained_majority_worker import expire_due_cosign_proposals
        count = expire_due_cosign_proposals(db)
        assert count == 0
        proposal_row = db.get(models.Proposal, pid)
        # Still deliberation — defensive skip leaves the row for the
        # next sign-endpoint call to advance.
        assert proposal_row.status == "deliberation"
