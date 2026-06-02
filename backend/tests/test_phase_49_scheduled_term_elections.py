"""Phase 49 — Scheduled / fixed-term elections.

Verification matrix (per spec §"Verification matrix"):

  - No-term regression: electable titles WITHOUT a term behave exactly
    as Phase 48 (elected-until-challenged; no scheduled opens).
  - Existing-title parity: existing electable titles default to no-term
    after migration (no auto-scheduling for orgs that haven't opted in).
  - Due-term opens an election at lead-time before term-end via the
    tick, with trigger='scheduled'.
  - Idempotency (D5): a second tick while an election is open does NOT
    create a duplicate.
  - Hold-over (model A core): zero-candidate scheduled election → no
    winner installed, incumbent retains the title + bound role; the
    next-due date STILL advances exactly once so the calendar cadence
    continues.
  - Next-due advancement (D6): the title's next_election_due_at moves
    by exactly term_length_days per scheduled resolution; off-cycle
    (admin_direct / member_cosign) elections do NOT move the clock.
  - System-title term (steward / admin): schedules + resolves
    respecting governance.py floor (reuses Phase 48 + 45b machinery
    via finalize_election; no new code path).
  - `scheduled`-not-enabled gate (D2): a term set without 'scheduled'
    in trigger_sources opens nothing.
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
# Fixtures (mirror Phase 48 stage patterns)
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
    trigger_sources: list[str] | None = None,
) -> models.Organization:
    elections_cfg: dict = {"enabled": elections_enabled}
    if trigger_sources is not None:
        elections_cfg["trigger_sources"] = trigger_sources
    settings: dict = {
        "default_deliberation_days": 3,
        "default_voting_days": 7,
        "default_pass_threshold": 0.50,
        "default_quorum_threshold": 0.0,
        "allowed_voting_methods": ["binary", "approval", "ranked_choice"],
        "elections": elections_cfg,
    }
    org = models.Organization(
        name=slug.title(),
        slug=slug,
        description="",
        join_policy="open",
        settings=settings,
    )
    db.add(org)
    db.flush()
    from org_titles import seed_system_titles_for_org
    from role_seed import seed_default_roles_for_org
    seed_default_roles_for_org(db, org.id)
    seed_system_titles_for_org(db, org.id)
    db.commit()
    return org


def _set_steward_title_electable(
    db: Session, org: models.Organization,
) -> models.OrgTitle:
    steward_title = db.query(models.OrgTitle).filter_by(
        org_id=org.id, name="Steward",
    ).one()
    steward_title.fill_method = "both"
    db.flush()
    db.commit()
    return steward_title


def _make_custom_title(
    db: Session, org: models.Organization, name: str, *,
    bound_role: str | None = None,
    cardinality_mode: str = "single",
    fill_method: str = "elected",
    term_length_days: int | None = None,
    election_lead_time_days: int = 7,
    next_election_due_at: datetime | None = None,
) -> models.OrgTitle:
    title = models.OrgTitle(
        org_id=org.id,
        name=name,
        bound_role=bound_role,
        cardinality_mode=cardinality_mode,
        fill_method=fill_method,
        term_length_days=term_length_days,
        election_lead_time_days=election_lead_time_days,
        next_election_due_at=next_election_due_at,
    )
    db.add(title)
    db.commit()
    db.refresh(title)
    return title


def _user_role(db: Session, org_id: str, user_id: str) -> str | None:
    m = db.query(models.OrgMembership).filter_by(
        org_id=org_id, user_id=user_id, status="active",
    ).first()
    if m is None or m.role_id is None:
        return None
    return db.get(models.Role, m.role_id).system_key


def _advance(client: TestClient, auth_for, proposal_id: str, actor: models.User):
    return client.post(
        f"/api/proposals/{proposal_id}/advance",
        headers=auth_for(actor),
        json={},
    )


# ===========================================================================
# No-term regression (Phase 48 behavior preserved — load-bearing)
# ===========================================================================

class TestNoTermRegression:
    """Electable titles without a term behave exactly as Phase 48 —
    no scheduled opens, no clock advancement, byte-identical lifecycle."""

    def test_tick_does_not_open_election_for_no_term_title(self, db: Session):
        org = _make_org(
            db, "p49-noterm",
            trigger_sources=["admin_direct", "scheduled"],
        )
        steward = make_user(db, "p49-noterm-steward")
        make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
        # Title is electable but no term — Phase 48 territory.
        _set_steward_title_electable(db, org)

        from elections import open_due_term_elections
        # Use a `now` far in the future to ensure even a hypothetical
        # zero-term title would qualify — but no-term titles must
        # ALWAYS be skipped.
        future = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=3650)
        result = open_due_term_elections(db, now=future)
        assert result["opened"] == 0
        # And no election proposal was created for the title.
        steward_title = db.query(models.OrgTitle).filter_by(
            org_id=org.id, name="Steward",
        ).one()
        n = db.query(models.Proposal).filter_by(
            election_title_id=steward_title.id,
        ).count()
        assert n == 0


# ===========================================================================
# Due-term opens election (the happy path)
# ===========================================================================

class TestDueTermOpensElection:
    def test_tick_opens_election_at_lead_time_with_scheduled_trigger(
        self, db: Session,
    ):
        org = _make_org(
            db, "p49-due",
            trigger_sources=["admin_direct", "scheduled"],
        )
        steward = make_user(db, "p49-due-steward")
        make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
        steward_title = _set_steward_title_electable(db, org)
        # Set a 30-day term with a 7-day lead-time. next_due is +30
        # days from "now" in the tick's perspective.
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        steward_title.term_length_days = 30
        steward_title.election_lead_time_days = 7
        steward_title.next_election_due_at = now + timedelta(days=30)
        db.commit()

        from elections import open_due_term_elections
        # Tick at "23 days before due" — JUST inside the lead-time window.
        tick_now = now + timedelta(days=23, hours=1)
        result = open_due_term_elections(db, now=tick_now)
        assert result["opened"] == 1, result

        # The election proposal was created with trigger='scheduled'.
        proposal = db.query(models.Proposal).filter_by(
            election_title_id=steward_title.id, status="deliberation",
        ).one()
        assert proposal.is_election is True
        assert proposal.election_trigger == "scheduled"

    def test_tick_skips_titles_before_lead_time(self, db: Session):
        org = _make_org(
            db, "p49-early",
            trigger_sources=["admin_direct", "scheduled"],
        )
        steward = make_user(db, "p49-early-steward")
        make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
        steward_title = _set_steward_title_electable(db, org)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        steward_title.term_length_days = 30
        steward_title.election_lead_time_days = 7
        steward_title.next_election_due_at = now + timedelta(days=30)
        db.commit()

        from elections import open_due_term_elections
        # Tick at "25 days before due" — OUTSIDE lead-time.
        tick_now = now + timedelta(days=5)
        result = open_due_term_elections(db, now=tick_now)
        assert result["opened"] == 0


# ===========================================================================
# Idempotency (D5)
# ===========================================================================

class TestIdempotency:
    def test_second_tick_during_open_election_does_not_duplicate(
        self, db: Session,
    ):
        org = _make_org(
            db, "p49-idem",
            trigger_sources=["admin_direct", "scheduled"],
        )
        steward = make_user(db, "p49-idem-steward")
        make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
        steward_title = _set_steward_title_electable(db, org)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        steward_title.term_length_days = 30
        steward_title.next_election_due_at = now + timedelta(days=30)
        db.commit()

        from elections import open_due_term_elections
        tick_now = now + timedelta(days=24)
        r1 = open_due_term_elections(db, now=tick_now)
        assert r1["opened"] == 1
        # Second tick a few hours later — election is still open.
        r2 = open_due_term_elections(db, now=tick_now + timedelta(hours=2))
        assert r2["opened"] == 0
        assert r2["skipped_idempotent"] == 1
        # Still only one election proposal.
        n = db.query(models.Proposal).filter_by(
            election_title_id=steward_title.id,
        ).count()
        assert n == 1


# ===========================================================================
# Hold-over (model A core)
# ===========================================================================

class TestHoldOver:
    def test_zero_candidate_scheduled_election_preserves_incumbent(
        self, client: TestClient, db: Session, auth_for,
    ):
        org = _make_org(
            db, "p49-hold",
            trigger_sources=["admin_direct", "scheduled"],
        )
        # Single steward — the incumbent. The point of the test is
        # that the steward doesn't re-nominate AND no one else does;
        # the seat must NOT vacate.
        steward = make_user(db, "p49-hold-steward")
        admin = make_user(db, "p49-hold-admin")
        make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
        make_org_membership(db, org_id=org.id, user_id=admin.id, role="admin")
        steward_title = _set_steward_title_electable(db, org)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        steward_title.term_length_days = 30
        steward_title.next_election_due_at = now + timedelta(days=30)
        db.commit()

        # Open the scheduled election via the tick.
        from elections import open_due_term_elections, finalize_election
        tick_now = now + timedelta(days=24)
        r = open_due_term_elections(db, now=tick_now)
        assert r["opened"] == 1
        proposal = db.query(models.Proposal).filter_by(
            election_title_id=steward_title.id,
        ).one()

        # Nobody nominates. Resolve via the close hook directly (the
        # voting-end worker calls finalize_election when status flips
        # to passed/failed; this is the equivalent direct call).
        result = finalize_election(db, proposal)
        assert result["resolved"] == "no_election"

        # The load-bearing assertion: the incumbent steward is still
        # the steward — role row + governance floor unchanged.
        assert _user_role(db, org.id, steward.id) == "steward"
        from governance import count_active_governors
        assert count_active_governors(db, org) >= 1


# ===========================================================================
# Next-due advancement (D6) + off-cycle does NOT move clock (B4)
# ===========================================================================

class TestNextDueAdvancement:
    def test_scheduled_resolution_advances_next_due_exactly_once(
        self, db: Session,
    ):
        org = _make_org(
            db, "p49-nextdue",
            trigger_sources=["admin_direct", "scheduled"],
        )
        steward = make_user(db, "p49-nextdue-steward")
        make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
        steward_title = _set_steward_title_electable(db, org)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        original_due = now + timedelta(days=30)
        steward_title.term_length_days = 30
        steward_title.next_election_due_at = original_due
        db.commit()

        from elections import open_due_term_elections, finalize_election
        # Tick + resolve immediately (zero-candidate hold-over).
        tick_now = now + timedelta(days=24)
        open_due_term_elections(db, now=tick_now)
        proposal = db.query(models.Proposal).filter_by(
            election_title_id=steward_title.id,
        ).one()
        finalize_election(db, proposal)
        # finalize_election doesn't commit (production flow commits
        # at the end of advance_proposal). Mirror that here.
        db.commit()
        db.refresh(steward_title)
        # next_due advanced by exactly term_length_days.
        expected = original_due + timedelta(days=30)
        assert steward_title.next_election_due_at == expected

    def test_off_cycle_admin_election_does_not_move_schedule(
        self, client: TestClient, db: Session, auth_for,
    ):
        """An off-cycle admin_direct election resolving must NOT touch
        the title's next_election_due_at. The calendar is fixed; mid-
        term challenges are a separate cycle that doesn't reset it."""
        org = _make_org(
            db, "p49-offcycle",
            trigger_sources=["admin_direct", "scheduled"],
        )
        steward = make_user(db, "p49-offcycle-steward")
        admin = make_user(db, "p49-offcycle-admin")
        member = make_user(db, "p49-offcycle-member")
        make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
        make_org_membership(db, org_id=org.id, user_id=admin.id, role="admin")
        make_org_membership(db, org_id=org.id, user_id=member.id, role="member")
        steward_title = _set_steward_title_electable(db, org)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        original_due = now + timedelta(days=30)
        steward_title.term_length_days = 30
        steward_title.next_election_due_at = original_due
        db.commit()

        # Admin opens an off-cycle election (admin_direct trigger).
        r = client.post(
            f"/api/orgs/{org.slug}/elections",
            headers=auth_for(admin),
            json={"title_id": steward_title.id, "trigger": "admin_direct"},
        )
        assert r.status_code == 201, r.text
        pid = r.json()["id"]
        # member challenges; advance to close. The member auto-wins
        # (only candidate). Steward demotes; member becomes steward.
        client.post(
            f"/api/orgs/{org.slug}/elections/{pid}/candidacies",
            headers=auth_for(member),
        )
        _advance(client, auth_for, pid, admin)  # → voting
        _advance(client, auth_for, pid, admin)  # → close

        db.expire_all()
        steward_title = db.query(models.OrgTitle).filter_by(
            id=steward_title.id,
        ).one()
        # next_due UNCHANGED by the off-cycle election.
        assert steward_title.next_election_due_at == original_due


# ===========================================================================
# `scheduled`-not-enabled gate (D2)
# ===========================================================================

class TestSchedulerGate:
    def test_term_set_but_scheduled_not_in_trigger_sources_opens_nothing(
        self, db: Session,
    ):
        org = _make_org(
            db, "p49-nogate",
            trigger_sources=["admin_direct"],  # NO 'scheduled'
        )
        steward = make_user(db, "p49-nogate-steward")
        make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
        steward_title = _set_steward_title_electable(db, org)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        steward_title.term_length_days = 30
        steward_title.next_election_due_at = now + timedelta(days=30)
        db.commit()

        from elections import open_due_term_elections
        tick_now = now + timedelta(days=24)
        result = open_due_term_elections(db, now=tick_now)
        assert result["opened"] == 0
        assert result["skipped_not_eligible"] == 1


# ===========================================================================
# Existing-title parity (B0 discipline carried forward)
# ===========================================================================

class TestExistingTitleParity:
    def test_existing_electable_titles_default_to_no_term_post_migration(
        self, db: Session,
    ):
        """After the Phase 49 migration, an org seeded BEFORE the
        migration (or any org that hasn't opted any title into terms)
        sees term_length_days=None on every electable title — i.e. NO
        title auto-schedules unless explicitly opted in. This guards
        the silent-regression class (the Phase 47 hotfix lesson).
        """
        org = _make_org(
            db, "p49-parity",
            trigger_sources=["admin_direct", "scheduled"],
        )
        steward = make_user(db, "p49-parity-steward")
        make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
        _set_steward_title_electable(db, org)
        # Without any explicit term setting, no title is due.
        titles = db.query(models.OrgTitle).filter_by(org_id=org.id).all()
        for t in titles:
            assert t.term_length_days is None
            assert t.next_election_due_at is None

        from elections import open_due_term_elections
        # Even at a far-future tick, no title opens — the title-must-
        # have-a-term gate stops auto-scheduling.
        future = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=3650)
        result = open_due_term_elections(db, now=future)
        assert result["opened"] == 0


# ===========================================================================
# Title create / update API surface
# ===========================================================================

class TestTitleApiSetsTermClock:
    def test_create_title_with_term_sets_next_due(
        self, client: TestClient, db: Session, auth_for,
    ):
        """POSTing a custom title with term_length_days computes
        next_election_due_at server-side from now."""
        org = _make_org(db, "p49-api-create")
        steward = make_user(db, "p49-api-create-steward")
        make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
        r = client.post(
            f"/api/orgs/{org.slug}/titles",
            headers=auth_for(steward),
            json={
                "name": "President",
                "fill_method": "elected",
                "term_length_days": 365,
                "election_lead_time_days": 14,
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["term_length_days"] == 365
        assert body["election_lead_time_days"] == 14
        assert body["next_election_due_at"] is not None

    def test_patch_term_to_zero_clears_clock(
        self, client: TestClient, db: Session, auth_for,
    ):
        """PATCHing term_length_days=0 clears both term + next-due —
        an org can opt out of scheduled re-election without deleting
        the title."""
        org = _make_org(db, "p49-api-clear")
        steward = make_user(db, "p49-api-clear-steward")
        make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
        title = _make_custom_title(
            db, org, "Treasurer",
            term_length_days=180,
            next_election_due_at=(
                datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=180)
            ),
        )
        r = client.patch(
            f"/api/orgs/{org.slug}/titles/{title.id}",
            headers=auth_for(steward),
            json={"term_length_days": 0},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["term_length_days"] is None
        assert body["next_election_due_at"] is None


# ===========================================================================
# Phase 48 regression (one last sanity check)
# ===========================================================================

class TestPhase48ElectionsDisabledRegression:
    """Stage 1's load-bearing invariant: an org with elections off
    still 400s on open-election, including the new trigger param."""

    def test_open_election_blocked_when_elections_off(
        self, client: TestClient, db: Session, auth_for,
    ):
        org = _make_org(db, "p49-elec-off", elections_enabled=False)
        admin = make_user(db, "p49-elec-off-admin")
        make_org_membership(db, org_id=org.id, user_id=admin.id, role="admin")
        steward_title = _set_steward_title_electable(db, org)
        r = client.post(
            f"/api/orgs/{org.slug}/elections",
            headers=auth_for(admin),
            json={"title_id": steward_title.id},
        )
        assert r.status_code == 400
        assert "not enabled" in r.json()["detail"].lower()
