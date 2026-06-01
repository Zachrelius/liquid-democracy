"""Phase 48 Stage 1 — Binding elections tests.

Verification matrix (per spec §"Verification matrix" + per-stage notes):

  - Elections-disabled regression: an org with elections off behaves
    exactly as 45b/46/47 left it. Appointment remains default.
  - close→assign-title side effects (the load-bearing piece): assert
    actual title + role rows after close, via 47's org_titles.py path.
    Outgoing steward demoted per 45a transfer machinery.
  - At-least-one-governor floor preserved.
  - D6 paths: zero candidates → expire (incumbent stays); one
    candidate → auto-wins; contested → tally winner installed.
  - D8 path: incumbent who doesn't self-nominate forfeits to an
    unopposed challenger.
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
# Fixtures
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
    elections_enabled: bool = True,
) -> models.Organization:
    org = models.Organization(
        name=slug.title(),
        slug=slug,
        description="",
        join_policy="open",
        settings={
            "default_deliberation_days": 3,
            "default_voting_days": 7,
            "default_pass_threshold": 0.50,
            "default_quorum_threshold": 0.0,  # so tests don't need quorum
            "allowed_voting_methods": ["binary"],
            "elections": {"enabled": elections_enabled},
        },
    )
    db.add(org)
    db.flush()
    # Seed roles + system titles like create_organization does.
    from org_titles import seed_system_titles_for_org
    from role_seed import seed_default_roles_for_org
    seed_default_roles_for_org(db, org.id)
    seed_system_titles_for_org(db, org.id)
    db.commit()
    return org


def _set_steward_title_electable(
    db: Session, org: models.Organization,
) -> models.OrgTitle:
    """Mark the Steward system title as electable (fill_method='both').
    Required for an election open on the steward title."""
    steward_title = db.query(models.OrgTitle).filter_by(
        org_id=org.id, name="Steward",
    ).one()
    steward_title.fill_method = "both"
    db.flush()
    db.commit()
    return steward_title


def _setup_org(db: Session, slug: str = "p48s1"):
    """Steward + admin + 3 members. Steward title set to electable."""
    org = _make_org(db, slug)
    steward = make_user(db, f"{slug}-steward")
    admin = make_user(db, f"{slug}-admin")
    member_x = make_user(db, f"{slug}-member-x")
    member_y = make_user(db, f"{slug}-member-y")
    member_z = make_user(db, f"{slug}-member-z")
    make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
    make_org_membership(db, org_id=org.id, user_id=admin.id, role="admin")
    make_org_membership(db, org_id=org.id, user_id=member_x.id, role="member")
    make_org_membership(db, org_id=org.id, user_id=member_y.id, role="member")
    make_org_membership(db, org_id=org.id, user_id=member_z.id, role="member")
    db.commit()
    steward_title = _set_steward_title_electable(db, org)
    return org, steward, admin, member_x, member_y, member_z, steward_title


def _user_role(db: Session, org_id: str, user_id: str) -> str | None:
    m = db.query(models.OrgMembership).filter_by(
        org_id=org_id, user_id=user_id, status="active",
    ).first()
    if m is None or m.role_id is None:
        return None
    return db.get(models.Role, m.role_id).system_key


def _advance(client: TestClient, auth_for, proposal_id: str, actor: models.User):
    """Helper — call POST /api/proposals/{id}/advance with the actor
    so the close hook fires under the same path the FE/admin uses."""
    return client.post(
        f"/api/proposals/{proposal_id}/advance",
        headers=auth_for(actor),
        json={},
    )


# ===========================================================================
# Elections-disabled regression — opt-in is truly opt-in
# ===========================================================================

class TestElectionsDisabledRegression:
    """When org.settings.elections.enabled is False (the default),
    the elections endpoints are inert: open-election returns 400."""

    def test_open_election_blocked_when_disabled(
        self, client: TestClient, db: Session, auth_for,
    ):
        org = _make_org(db, "p48-disabled", elections_enabled=False)
        admin = make_user(db, "p48-disabled-admin")
        make_org_membership(db, org_id=org.id, user_id=admin.id, role="admin")
        _set_steward_title_electable(db, org)
        steward_title = db.query(models.OrgTitle).filter_by(
            org_id=org.id, name="Steward",
        ).one()
        r = client.post(
            f"/api/orgs/{org.slug}/elections",
            headers=auth_for(admin),
            json={"title_id": steward_title.id},
        )
        assert r.status_code == 400
        assert "not enabled" in r.json()["detail"].lower()


# ===========================================================================
# Open election + candidacy mechanics
# ===========================================================================

class TestOpenElectionAndCandidacy:
    def test_admin_can_open_steward_title_election(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, mx, my, mz, steward_title = _setup_org(db, "p48open")
        r = client.post(
            f"/api/orgs/{org.slug}/elections",
            headers=auth_for(admin),
            json={"title_id": steward_title.id},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["is_election"] is True
        assert body["status"] == "deliberation"

    def test_open_election_requires_electable_title(
        self, client: TestClient, db: Session, auth_for,
    ):
        """The system Admin title defaults to fill_method='assigned' —
        not electable until reconfigured."""
        org, steward, admin, *_ = _setup_org(db, "p48-nonelectable")
        admin_title = db.query(models.OrgTitle).filter_by(
            org_id=org.id, name="Admin",
        ).one()
        r = client.post(
            f"/api/orgs/{org.slug}/elections",
            headers=auth_for(admin),
            json={"title_id": admin_title.id},
        )
        assert r.status_code == 400
        assert "electable" in r.json()["detail"].lower()

    def test_member_can_self_nominate(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, mx, my, mz, steward_title = _setup_org(db, "p48selfnom")
        r = client.post(
            f"/api/orgs/{org.slug}/elections",
            headers=auth_for(admin),
            json={"title_id": steward_title.id},
        )
        pid = r.json()["id"]
        rd = client.post(
            f"/api/orgs/{org.slug}/elections/{pid}/candidacies",
            headers=auth_for(mx),
        )
        assert rd.status_code == 201, rd.text
        # Verify the candidacy row.
        rls = client.get(
            f"/api/orgs/{org.slug}/elections/{pid}/candidacies",
            headers=auth_for(mx),
        )
        assert rls.status_code == 200
        candidates = rls.json()
        assert any(c["user_id"] == mx.id for c in candidates)

    def test_self_nominate_idempotent_returns_400_when_already_declared(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, mx, my, mz, steward_title = _setup_org(db, "p48dup")
        r = client.post(
            f"/api/orgs/{org.slug}/elections",
            headers=auth_for(admin),
            json={"title_id": steward_title.id},
        )
        pid = r.json()["id"]
        client.post(
            f"/api/orgs/{org.slug}/elections/{pid}/candidacies",
            headers=auth_for(mx),
        )
        r2 = client.post(
            f"/api/orgs/{org.slug}/elections/{pid}/candidacies",
            headers=auth_for(mx),
        )
        assert r2.status_code == 400

    def test_withdraw_then_redeclare(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, mx, my, mz, steward_title = _setup_org(db, "p48redec")
        r = client.post(
            f"/api/orgs/{org.slug}/elections",
            headers=auth_for(admin),
            json={"title_id": steward_title.id},
        )
        pid = r.json()["id"]
        client.post(
            f"/api/orgs/{org.slug}/elections/{pid}/candidacies",
            headers=auth_for(mx),
        )
        client.request(
            "DELETE",
            f"/api/orgs/{org.slug}/elections/{pid}/candidacies",
            headers=auth_for(mx),
        )
        # Re-declare.
        r2 = client.post(
            f"/api/orgs/{org.slug}/elections/{pid}/candidacies",
            headers=auth_for(mx),
        )
        assert r2.status_code == 201


# ===========================================================================
# The load-bearing piece: close→assign-title hook
# ===========================================================================

class TestCloseAssignTitleHook:
    """When an election closes, the title is assigned to the winner
    via Phase 47's org_titles.py path. Bound-role swaps follow the
    45a/45b machinery (atomic steward transfer)."""

    def test_single_candidate_auto_wins_and_takes_steward_role(
        self, client: TestClient, db: Session, auth_for,
    ):
        """D6 single-candidate auto-win. Asserts side effects:
        winner now holds steward role; outgoing steward demoted to
        admin via the existing transfer machinery."""
        org, steward, admin, mx, my, mz, steward_title = _setup_org(db, "p48auto")
        # admin opens the election.
        r = client.post(
            f"/api/orgs/{org.slug}/elections",
            headers=auth_for(admin),
            json={"title_id": steward_title.id},
        )
        pid = r.json()["id"]
        # Only mx declares.
        client.post(
            f"/api/orgs/{org.slug}/elections/{pid}/candidacies",
            headers=auth_for(mx),
        )
        # Advance deliberation → voting (admin has proposal.advance_phase).
        ra = _advance(client, auth_for, pid, admin)
        assert ra.status_code == 200, ra.text
        # Advance voting → close (passed); the hook fires.
        rb = _advance(client, auth_for, pid, admin)
        assert rb.status_code == 200, rb.text
        db.expire_all()
        # Side effects: mx is now steward; prior steward demoted to admin.
        assert _user_role(db, org.id, mx.id) == "steward"
        assert _user_role(db, org.id, steward.id) == "admin"
        # The election audit fired.
        actions = {
            row.action for row in db.query(models.AuditLog).filter(
                models.AuditLog.target_id == pid,
            ).all()
        }
        assert "election.resolved" in actions

    def test_zero_candidates_no_assignment_incumbent_stays(
        self, client: TestClient, db: Session, auth_for,
    ):
        """D6 zero candidates → no_election outcome, status quo holds."""
        org, steward, admin, mx, my, mz, steward_title = _setup_org(db, "p48zero")
        r = client.post(
            f"/api/orgs/{org.slug}/elections",
            headers=auth_for(admin),
            json={"title_id": steward_title.id},
        )
        pid = r.json()["id"]
        # NOBODY declares.
        _advance(client, auth_for, pid, admin)  # → voting
        _advance(client, auth_for, pid, admin)  # → close
        db.expire_all()
        # Incumbent stays steward.
        assert _user_role(db, org.id, steward.id) == "steward"
        # The audit reports the no_candidates outcome.
        audits = db.query(models.AuditLog).filter(
            models.AuditLog.action == "election.resolved",
            models.AuditLog.target_id == pid,
        ).all()
        assert len(audits) == 1
        assert audits[0].details["outcome"] == "no_candidates"

    def test_contested_election_winner_installed_and_predecessor_demoted(
        self, client: TestClient, db: Session, auth_for,
    ):
        """Two candidates declare; the close hook resolves a winner +
        installs them. The defensive single-winner resolver picks the
        first declared candidate when no tally is available (Stage 2
        replaces this with full tally). The load-bearing assertion is
        the role-row side effect: winner = steward, predecessor =
        admin."""
        org, steward, admin, mx, my, mz, steward_title = _setup_org(db, "p48contest")
        r = client.post(
            f"/api/orgs/{org.slug}/elections",
            headers=auth_for(admin),
            json={"title_id": steward_title.id},
        )
        pid = r.json()["id"]
        # Two candidates. mx declared first.
        client.post(
            f"/api/orgs/{org.slug}/elections/{pid}/candidacies",
            headers=auth_for(mx),
        )
        client.post(
            f"/api/orgs/{org.slug}/elections/{pid}/candidacies",
            headers=auth_for(my),
        )
        _advance(client, auth_for, pid, admin)
        _advance(client, auth_for, pid, admin)
        db.expire_all()
        # One of the two declared candidates is now steward.
        new_steward_role = _user_role(db, org.id, mx.id)
        if new_steward_role != "steward":
            # The defensive resolver picks the first-declared, so the
            # winner should be mx. If a future change reorders, allow
            # either to be the winner.
            new_steward_role = _user_role(db, org.id, my.id)
            assert new_steward_role == "steward"
            new_steward_id = my.id
        else:
            new_steward_id = mx.id
        # Prior steward demoted.
        assert _user_role(db, org.id, steward.id) == "admin"
        # The org has exactly one steward post-close.
        stewards = db.query(models.OrgMembership).filter(
            models.OrgMembership.org_id == org.id,
            models.OrgMembership.status == "active",
        ).all()
        steward_count = 0
        for m in stewards:
            r = db.get(models.Role, m.role_id) if m.role_id else None
            if r is not None and r.system_key == "steward":
                steward_count += 1
        assert steward_count == 1


# ===========================================================================
# At-least-one-governor floor preserved
# ===========================================================================

class TestFloorPreservedAcrossElectionClose:
    def test_floor_intact_after_uncontested_election(
        self, client: TestClient, db: Session, auth_for,
    ):
        org, steward, admin, mx, my, mz, steward_title = _setup_org(db, "p48floor")
        r = client.post(
            f"/api/orgs/{org.slug}/elections",
            headers=auth_for(admin),
            json={"title_id": steward_title.id},
        )
        pid = r.json()["id"]
        client.post(
            f"/api/orgs/{org.slug}/elections/{pid}/candidacies",
            headers=auth_for(mx),
        )
        _advance(client, auth_for, pid, admin)
        _advance(client, auth_for, pid, admin)
        db.expire_all()
        from governance import count_active_governors
        assert count_active_governors(db, org) == 1


# ===========================================================================
# D8 — incumbent must self-nominate to defend
# ===========================================================================

class TestIncumbentForfeit:
    def test_incumbent_who_doesnt_self_nominate_forfeits_to_challenger(
        self, client: TestClient, db: Session, auth_for,
    ):
        """D8 explicitly: no automatic ballot presence. If the
        incumbent doesn't self-declare and a challenger does, the
        challenger wins unopposed."""
        org, steward, admin, mx, my, mz, steward_title = _setup_org(db, "p48forfeit")
        r = client.post(
            f"/api/orgs/{org.slug}/elections",
            headers=auth_for(admin),
            json={"title_id": steward_title.id},
        )
        pid = r.json()["id"]
        # Challenger declares. Incumbent (steward) does NOT.
        client.post(
            f"/api/orgs/{org.slug}/elections/{pid}/candidacies",
            headers=auth_for(mx),
        )
        _advance(client, auth_for, pid, admin)
        _advance(client, auth_for, pid, admin)
        db.expire_all()
        # Challenger took the seat; incumbent forfeited.
        assert _user_role(db, org.id, mx.id) == "steward"
        assert _user_role(db, org.id, steward.id) == "admin"
