"""Phase 67 — election close semantics (W1, REVISED design), title-delete
friendly 400 (W4), delegations-network topic regression (W5).

Coverage map (spec: phase67_election_ux_and_bug_fixes_spec.md, W1 as
revised 2026-06-12 — quorum gates seat installation):

W1 — quorum is HONEST for elections:
  * Elections default to quorum 0 at creation (open_election route +
    the scheduled service path); plurality-of-those-who-vote stays the
    norm — a default election under ANY turnout closes "passed" and
    seats winners (incl. the uncontested auto-win with zero ballots).
  * An election with an EXPLICIT quorum that closes under it closes
    "failed" and seats NOTHING — incumbents stay, vacancies stay
    vacant; an election.not_finalized audit row records that seating
    was skipped (quorum_met: false, seats_unchanged: true); NO
    election.resolved row is written. Side-effect tested at all three
    close sites: /api/proposals advance, org-scoped advance (which
    pre-67 never ran finalize at all), worker natural close (same).
  * An explicit-quorum election that MEETS quorum passes + seats.
  * Scheduled-trigger elections still advance the title's term clock
    on a quorum-failed close (B4 cadence — otherwise the next tick
    would immediately re-open the same election).
  * Non-election proposals are completely untouched (quorum still
    gates them, both close sites).
  * The election results read carries the quorum/turnout fields the FE
    turnout line needs (RCV included).

W4 — DELETE /api/orgs/{slug}/titles/{id} returns a friendly 400 (not a
raw FK 500) when any proposal references the title via
election_title_id; the title row stays present.

W5 — regression for the personal delegation network 500
(Topic.description was dropped in Phase 58; the endpoint read it for
TOPIC-SPECIFIC delegations — the untested path). Asserts 200 + topic
name in the edge payload for both an outgoing and an incoming
topic-specific delegation.

Style mirrors test_phase_66a_election_wiring.py (route-driven close so
the real hook fires; production-shape Vote.ballot JSON; real model rows
per the Phase 17 lesson).
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
# Fixtures (66a pattern)
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
# Setup helpers (66a patterns)
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _make_org(
    db: Session, slug: str, *, extra_settings: dict | None = None,
) -> models.Organization:
    from org_titles import seed_system_titles_for_org
    from role_seed import seed_default_roles_for_org

    settings = {
        "default_deliberation_days": 3,
        "default_voting_days": 7,
        "default_pass_threshold": 0.50,
        # Deliberately non-zero: proves elections get quorum 0 by
        # default INSTEAD of inheriting the org proposal default.
        "default_quorum_threshold": 0.40,
        "allowed_voting_methods": ["binary", "approval", "ranked_choice"],
        "elections": {"enabled": True},
        # The worker tests exercise the NON-SRR natural-close branch;
        # SRR must be off by default so evaluate_proposal takes it.
        "stable_result_enabled_default": False,
    }
    if extra_settings:
        settings.update(extra_settings)
    org = models.Organization(
        name=slug.title(),
        slug=slug,
        description="",
        join_policy="open",
        settings=settings,
    )
    db.add(org)
    db.flush()
    seed_default_roles_for_org(db, org.id)
    seed_system_titles_for_org(db, org.id)
    db.commit()
    return org


def _make_council_title(
    db: Session, org: models.Organization, *,
    name: str = "Council Member",
    bound_role: str | None = None,
) -> models.OrgTitle:
    title = models.OrgTitle(
        org_id=org.id,
        name=name,
        bound_role=bound_role,
        cardinality_mode="multi",
        max_holders=None,
        fill_method="elected",
        is_system=False,
        display_order=50,
    )
    db.add(title)
    db.flush()
    db.commit()
    return title


def _setup_org(db: Session, slug: str, *, n_members: int = 10):
    org = _make_org(db, slug)
    steward = make_user(db, f"{slug}-steward")
    admin = make_user(db, f"{slug}-admin")
    members = [make_user(db, f"{slug}-m{i}") for i in range(n_members)]
    make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
    make_org_membership(db, org_id=org.id, user_id=admin.id, role="admin")
    for m in members:
        make_org_membership(db, org_id=org.id, user_id=m.id, role="member")
    db.commit()
    return org, steward, admin, members


def _open_election(
    client: TestClient, auth_for, org, opener, title, *,
    voting_method: str = "approval",
    config: dict | None = None,
    num_winners: int = 1,
    quorum_threshold: float | None = None,
):
    body = {
        "title_id": title.id,
        "voting_method": voting_method,
        "num_winners": num_winners,
        "slate_mode": "fill_vacancies",
    }
    if config is not None:
        body["approval_winner_config"] = config
    if quorum_threshold is not None:
        body["quorum_threshold"] = quorum_threshold
    r = client.post(
        f"/api/orgs/{org.slug}/elections",
        headers=auth_for(opener),
        json=body,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _declare(client: TestClient, auth_for, org, pid: str, user) -> None:
    r = client.post(
        f"/api/orgs/{org.slug}/elections/{pid}/candidacies",
        headers=auth_for(user),
    )
    assert r.status_code == 201, r.text


def _advance(client: TestClient, auth_for, pid: str, actor):
    return client.post(
        f"/api/proposals/{pid}/advance", headers=auth_for(actor), json={},
    )


def _advance_org(client: TestClient, auth_for, org, pid: str, actor):
    return client.post(
        f"/api/orgs/{org.slug}/proposals/{pid}/advance",
        headers=auth_for(actor), json={},
    )


def _option_id_for_candidate(db: Session, pid: str, user_id: str) -> str:
    row = db.query(models.ProposalOption).filter(
        models.ProposalOption.proposal_id == pid,
        models.ProposalOption.label == user_id,
    ).one()
    return row.id


def _cast_approval_ballot(
    db: Session, voter, pid: str, approved_option_ids: list[str],
) -> None:
    """Production storage shape: ballot data lives in Vote.ballot JSON."""
    db.add(models.Vote(
        proposal_id=pid,
        user_id=voter.id,
        vote_value=None,
        ballot={"approvals": approved_option_ids},
        is_direct=True,
        cast_by_id=voter.id,
    ))
    db.flush()


def _cast_rcv_ballot(
    db: Session, voter, pid: str, ranking: list[str],
) -> None:
    db.add(models.Vote(
        proposal_id=pid,
        user_id=voter.id,
        vote_value=None,
        ballot={"ranking": ranking},
        is_direct=True,
        cast_by_id=voter.id,
    ))
    db.flush()


def _assign_incumbent(db: Session, org, title, user) -> None:
    """Seed a pre-existing holder so the failed-close tests can assert
    the incumbent is untouched."""
    db.add(models.OrgTitleAssignment(
        title_id=title.id,
        user_id=user.id,
    ))
    db.commit()


def _holders(db: Session, title_id: str) -> set[str]:
    return {
        r.user_id
        for r in db.query(models.OrgTitleAssignment).filter(
            models.OrgTitleAssignment.title_id == title_id,
        ).all()
    }


def _audit_rows(db: Session, action: str, pid: str) -> list[models.AuditLog]:
    return (
        db.query(models.AuditLog)
        .filter(
            models.AuditLog.action == action,
            models.AuditLog.target_id == pid,
        )
        .all()
    )


def _resolved_audit_details(db: Session, pid: str) -> dict:
    rows = _audit_rows(db, "election.resolved", pid)
    assert rows, "election.resolved audit row missing"
    return rows[-1].details or {}


def _close_status_changed_details(db: Session, pid: str) -> dict:
    """The status_changed audit row for the voting->close transition.

    Selected by old_status (not recency) because AuditLog.id is a UUID
    and same-second timestamps don't order reliably."""
    rows = _audit_rows(db, "proposal.status_changed", pid)
    close_rows = [
        r for r in rows if (r.details or {}).get("old_status") == "voting"
    ]
    assert len(close_rows) == 1, "expected exactly one voting->close audit row"
    return close_rows[0].details or {}


def _open_voting_election(
    client, db, auth_for, org, admin, members, title, *,
    quorum_threshold: float | None = None,
    ballots_for_m0: int = 1,
):
    """Shared W1 setup: approval election (legacy, no config), two
    candidates (m0, m1), advanced to voting, ``ballots_for_m0`` ballots
    approving m0."""
    pid = _open_election(
        client, auth_for, org, admin, title,
        quorum_threshold=quorum_threshold,
    )
    _declare(client, auth_for, org, pid, members[0])
    _declare(client, auth_for, org, pid, members[1])
    r = _advance(client, auth_for, pid, admin)  # deliberation -> voting
    assert r.status_code == 200, r.text
    opt0 = _option_id_for_candidate(db, pid, members[0].id)
    for voter in members[2:2 + ballots_for_m0]:
        _cast_approval_ballot(db, voter, pid, [opt0])
    db.commit()
    return pid


# ===========================================================================
# W1 — elections default to quorum 0; low turnout still seats
# ===========================================================================

class TestElectionQuorumDefaultsToZero:

    def test_open_election_defaults_quorum_zero_not_org_default(
        self, client, db, auth_for,
    ):
        """The org's proposal default (0.40 in these fixtures) must NOT
        leak onto election proposals — elections get quorum 0."""
        org, steward, admin, members = _setup_org(db, "p67-qdefault")
        title = _make_council_title(db, org)
        pid = _open_election(client, auth_for, org, admin, title)
        assert db.get(models.Proposal, pid).quorum_threshold == 0.0

    def test_explicit_quorum_round_trips(self, client, db, auth_for):
        org, steward, admin, members = _setup_org(db, "p67-qexplicit")
        title = _make_council_title(db, org)
        pid = _open_election(
            client, auth_for, org, admin, title, quorum_threshold=0.4,
        )
        assert db.get(models.Proposal, pid).quorum_threshold == 0.4

    def test_out_of_range_quorum_rejected(self, client, db, auth_for):
        org, steward, admin, members = _setup_org(db, "p67-qbad")
        title = _make_council_title(db, org)
        r = client.post(
            f"/api/orgs/{org.slug}/elections",
            headers=auth_for(admin),
            json={"title_id": title.id, "quorum_threshold": 1.5},
        )
        assert r.status_code == 422, r.text

    def test_scheduled_election_opens_with_quorum_zero(self, db):
        """The scheduled service path mirrors the route default."""
        from elections import open_due_term_elections

        org = _make_org(
            db, "p67-qsched",
            extra_settings={
                "elections": {
                    "enabled": True,
                    "trigger_sources": ["admin_direct", "scheduled"],
                },
            },
        )
        steward = make_user(db, "p67-qsched-steward")
        make_org_membership(
            db, org_id=org.id, user_id=steward.id, role="steward",
        )
        title = _make_council_title(db, org, name="Scheduled Seat")
        title.term_length_days = 30
        title.next_election_due_at = _now() + timedelta(days=3)
        db.commit()

        r = open_due_term_elections(db, now=_now())
        assert r["opened"] == 1
        proposal = db.query(models.Proposal).filter_by(
            election_title_id=title.id,
        ).one()
        assert proposal.quorum_threshold == 0.0

    def test_default_election_low_turnout_passes_and_seats(
        self, client, db, auth_for,
    ):
        """Default (quorum 0) election, ONE ballot out of 12 eligible:
        closes passed, winner seated — plurality-of-those-who-vote
        preserved for the normal case."""
        org, steward, admin, members = _setup_org(db, "p67-lowturnout")
        title = _make_council_title(db, org)
        pid = _open_voting_election(
            client, db, auth_for, org, admin, members, title,
        )

        r = _advance(client, auth_for, pid, admin)  # voting -> close
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "passed"

        db.expire_all()
        assert db.get(models.Proposal, pid).status == "passed"
        assert _holders(db, title.id) == {members[0].id}
        assert _resolved_audit_details(db, pid)["outcome"] == "winners"
        assert _audit_rows(db, "election.not_finalized", pid) == []
        assert _close_status_changed_details(db, pid)["new_status"] == "passed"

    def test_uncontested_zero_ballot_election_still_seats(
        self, client, db, auth_for,
    ):
        """Uncontested auto-win with NO ballots at all keeps working
        under the new close rule (quorum 0 met trivially -> passed ->
        finalize auto-wins the lone candidate)."""
        org, steward, admin, members = _setup_org(db, "p67-uncontested")
        title = _make_council_title(db, org)
        pid = _open_election(client, auth_for, org, admin, title)
        _declare(client, auth_for, org, pid, members[0])
        assert _advance(client, auth_for, pid, admin).status_code == 200
        assert _advance(client, auth_for, pid, admin).status_code == 200

        db.expire_all()
        assert db.get(models.Proposal, pid).status == "passed"
        assert _holders(db, title.id) == {members[0].id}
        assert _resolved_audit_details(db, pid)["auto_win_uncontested"] is True

    def test_zero_candidate_election_holds_over_without_seats(
        self, client, db, auth_for,
    ):
        """Zero candidates: the close concludes (quorum 0 met ->
        passed -> finalize resolves the D6 no_candidates hold-over);
        nothing is seated."""
        org, steward, admin, members = _setup_org(db, "p67-zerocand")
        title = _make_council_title(db, org)
        pid = _open_election(client, auth_for, org, admin, title)
        assert _advance(client, auth_for, pid, admin).status_code == 200
        assert _advance(client, auth_for, pid, admin).status_code == 200

        db.expire_all()
        assert db.get(models.Proposal, pid).status == "passed"
        assert _holders(db, title.id) == set()
        assert _resolved_audit_details(db, pid)["outcome"] == "no_candidates"


# ===========================================================================
# W1 — explicit quorum unmet: failed close, NO seats changed
# (one side-effect test per close site)
# ===========================================================================

class TestUnderQuorumElectionFailsAndSeatsNothing:

    def _open_under_quorum(self, client, db, auth_for, org, admin, members, title):
        """Explicit quorum 0.4 over 12 eligible; ONE ballot (~8%) —
        quorum unmet at close. Incumbent m5 pre-seated."""
        _assign_incumbent(db, org, title, members[5])
        return _open_voting_election(
            client, db, auth_for, org, admin, members, title,
            quorum_threshold=0.4,
        )

    def _assert_failed_no_seat_changes(self, db, pid, title, members):
        db.expire_all()
        assert db.get(models.Proposal, pid).status == "failed"
        # THE side effect: incumbent intact, winner NOT installed.
        assert _holders(db, title.id) == {members[5].id}
        # Seating never ran: no election.resolved row at all.
        assert _audit_rows(db, "election.resolved", pid) == []
        # Explicit skip-record instead.
        rows = _audit_rows(db, "election.not_finalized", pid)
        assert len(rows) == 1
        details = rows[0].details or {}
        assert details["reason"] == "quorum_not_met"
        assert details["quorum_met"] is False
        assert details["seats_unchanged"] is True
        assert details["title_id"] == title.id
        assert _close_status_changed_details(db, pid)["new_status"] == "failed"

    def test_route_advance_under_quorum_fails_and_seats_nothing(
        self, client, db, auth_for,
    ):
        org, steward, admin, members = _setup_org(db, "p67-uq-route")
        title = _make_council_title(db, org)
        pid = self._open_under_quorum(
            client, db, auth_for, org, admin, members, title,
        )

        r = _advance(client, auth_for, pid, admin)  # voting -> close
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "failed"
        self._assert_failed_no_seat_changes(db, pid, title, members)

    def test_org_scoped_advance_under_quorum_fails_and_seats_nothing(
        self, client, db, auth_for,
    ):
        org, steward, admin, members = _setup_org(db, "p67-uq-orgroute")
        title = _make_council_title(db, org)
        pid = self._open_under_quorum(
            client, db, auth_for, org, admin, members, title,
        )

        r = _advance_org(client, auth_for, org, pid, admin)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "failed"
        self._assert_failed_no_seat_changes(db, pid, title, members)

    def test_worker_natural_close_under_quorum_fails_and_seats_nothing(
        self, client, db, auth_for,
    ):
        import sustained_majority_worker as worker

        org, steward, admin, members = _setup_org(db, "p67-uq-worker")
        title = _make_council_title(db, org)
        pid = self._open_under_quorum(
            client, db, auth_for, org, admin, members, title,
        )
        proposal = db.get(models.Proposal, pid)
        proposal.voting_end = _now() - timedelta(hours=1)
        db.commit()

        result = worker.evaluate_proposal(db, proposal)
        db.commit()

        assert result == "closed_on_time"
        self._assert_failed_no_seat_changes(db, pid, title, members)

    def test_bound_role_not_granted_on_under_quorum_close(
        self, client, db, auth_for,
    ):
        """Role side effect: a bound-role title must not grant the role
        when the close fails by quorum."""
        org, steward, admin, members = _setup_org(db, "p67-uq-role")
        title = _make_council_title(db, org, bound_role="admin")
        pid = _open_voting_election(
            client, db, auth_for, org, admin, members, title,
            quorum_threshold=0.4,
        )

        r = _advance(client, auth_for, pid, admin)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "failed"
        db.expire_all()
        assert _holders(db, title.id) == set()
        m = db.query(models.OrgMembership).filter_by(
            org_id=org.id, user_id=members[0].id, status="active",
        ).one()
        assert db.get(models.Role, m.role_id).system_key == "member"

    def test_scheduled_clock_still_advances_on_quorum_failed_close(
        self, db,
    ):
        """B4 cadence: a scheduled election that fails by quorum still
        advances next_election_due_at (pre-67 finalize advanced it for
        every scheduled outcome; without this the next tick re-opens
        the same election immediately)."""
        from elections import run_election_close_hook

        org = _make_org(db, "p67-uq-sched")
        author = make_user(db, "p67-uq-sched-author")
        make_org_membership(
            db, org_id=org.id, user_id=author.id, role="steward",
        )
        title = _make_council_title(db, org, name="Clocked Seat")
        original_due = _now() + timedelta(days=2)
        title.term_length_days = 30
        title.next_election_due_at = original_due
        proposal = models.Proposal(
            title="Election: Clocked Seat",
            body="",
            author_id=author.id,
            org_id=org.id,
            voting_method="ranked_choice",
            status="failed",
            quorum_threshold=0.4,
            is_election=True,
            election_title_id=title.id,
            election_trigger="scheduled",
        )
        db.add(proposal)
        db.commit()

        out = run_election_close_hook(db, proposal, "failed")
        db.commit()

        assert out == "failed"
        db.refresh(title)
        assert title.next_election_due_at == original_due + timedelta(days=30)
        rows = _audit_rows(db, "election.not_finalized", proposal.id)
        assert len(rows) == 1


# ===========================================================================
# W1 — explicit quorum MET: passes + seats through the ordinary path
# ===========================================================================

class TestExplicitQuorumMetElectionSeats:

    def test_quorum_met_close_passes_and_seats(self, client, db, auth_for):
        """Explicit quorum 0.25 over 12 eligible; FOUR ballots (~33%) —
        quorum met, winner seated, no skip-record."""
        org, steward, admin, members = _setup_org(db, "p67-quorumok")
        title = _make_council_title(db, org)
        pid = _open_voting_election(
            client, db, auth_for, org, admin, members, title,
            quorum_threshold=0.25,
            ballots_for_m0=4,
        )

        r = _advance(client, auth_for, pid, admin)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "passed"

        db.expire_all()
        assert db.get(models.Proposal, pid).status == "passed"
        assert _holders(db, title.id) == {members[0].id}
        assert _resolved_audit_details(db, pid)["outcome"] == "winners"
        assert _audit_rows(db, "election.not_finalized", pid) == []


# ===========================================================================
# W1 invariant — non-election proposals completely untouched
# ===========================================================================

class TestNonElectionProposalsUntouched:

    def _voting_binary_proposal(
        self, db, org, author, *, quorum_threshold: float = 0.9,
    ) -> models.Proposal:
        now = _now()
        p = models.Proposal(
            title="Ordinary proposal",
            body="",
            author_id=author.id,
            org_id=org.id,
            voting_method="binary",
            status="voting",
            voting_start=now - timedelta(hours=2),
            voting_end=now - timedelta(hours=1),
            pass_threshold=0.5,
            quorum_threshold=quorum_threshold,
        )
        db.add(p)
        db.commit()
        return p

    def test_route_advance_non_election_under_quorum_still_fails(
        self, client, db, auth_for,
    ):
        org, steward, admin, members = _setup_org(db, "p67-nonel-route")
        p = self._voting_binary_proposal(db, org, admin)
        db.add(models.Vote(
            proposal_id=p.id, user_id=members[0].id, vote_value="yes",
            is_direct=True, cast_by_id=members[0].id,
        ))
        db.commit()

        r = _advance(client, auth_for, p.id, admin)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "failed"
        db.expire_all()
        assert db.get(models.Proposal, p.id).status == "failed"
        # The election skip-record never fires for non-elections.
        assert _audit_rows(db, "election.not_finalized", p.id) == []

    def test_worker_close_non_election_under_quorum_still_fails(
        self, client, db, auth_for,
    ):
        import sustained_majority_worker as worker

        org, steward, admin, members = _setup_org(db, "p67-nonel-worker")
        p = self._voting_binary_proposal(db, org, admin)
        db.add(models.Vote(
            proposal_id=p.id, user_id=members[0].id, vote_value="yes",
            is_direct=True, cast_by_id=members[0].id,
        ))
        db.commit()

        result = worker.evaluate_proposal(db, p)
        db.commit()
        assert result == "closed_on_time"
        db.expire_all()
        assert db.get(models.Proposal, p.id).status == "failed"
        assert _audit_rows(db, "election.not_finalized", p.id) == []

    def test_non_election_quorum_met_majority_still_passes(
        self, client, db, auth_for,
    ):
        org, steward, admin, members = _setup_org(db, "p67-nonel-pass")
        p = self._voting_binary_proposal(
            db, org, admin, quorum_threshold=0.1,
        )
        for voter in members[:3]:
            db.add(models.Vote(
                proposal_id=p.id, user_id=voter.id, vote_value="yes",
                is_direct=True, cast_by_id=voter.id,
            ))
        db.commit()

        r = _advance(client, auth_for, p.id, admin)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "passed"


# ===========================================================================
# W1 — election results read exposes the turnout fields (RCV included)
# ===========================================================================

class TestElectionResultsTurnoutFields:

    def test_rcv_election_results_carry_quorum_and_turnout(
        self, client, db, auth_for,
    ):
        """The FE turnout line needs quorum_met + total_ballots_cast +
        total_eligible on the results read for RCV elections too (the
        approval branch already had coverage via 66/66a)."""
        org, steward, admin, members = _setup_org(db, "p67-rcvres")
        title = _make_council_title(db, org)
        pid = _open_election(
            client, auth_for, org, admin, title,
            voting_method="ranked_choice",
        )
        _declare(client, auth_for, org, pid, members[0])
        _declare(client, auth_for, org, pid, members[1])
        r = _advance(client, auth_for, pid, admin)
        assert r.status_code == 200, r.text
        opt0 = _option_id_for_candidate(db, pid, members[0].id)
        opt1 = _option_id_for_candidate(db, pid, members[1].id)
        _cast_rcv_ballot(db, members[2], pid, [opt0, opt1])
        db.commit()

        r = client.get(
            f"/api/proposals/{pid}/results", headers=auth_for(members[2]),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["voting_method"] == "ranked_choice"
        assert body["total_ballots_cast"] == 1
        assert body["total_eligible"] >= 3
        assert isinstance(body["quorum_met"], bool)

    def test_approval_election_results_carry_quorum_and_turnout(
        self, client, db, auth_for,
    ):
        org, steward, admin, members = _setup_org(db, "p67-appres")
        title = _make_council_title(db, org)
        pid = _open_election(client, auth_for, org, admin, title)
        _declare(client, auth_for, org, pid, members[0])
        _declare(client, auth_for, org, pid, members[1])
        r = _advance(client, auth_for, pid, admin)
        assert r.status_code == 200, r.text
        opt0 = _option_id_for_candidate(db, pid, members[0].id)
        _cast_approval_ballot(db, members[2], pid, [opt0])
        db.commit()

        r = client.get(
            f"/api/proposals/{pid}/results", headers=auth_for(members[2]),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["voting_method"] == "approval"
        assert body["total_ballots_cast"] == 1
        assert body["total_eligible"] >= 3
        assert isinstance(body["quorum_met"], bool)


# ===========================================================================
# W4 — title delete with election history -> friendly 400
# ===========================================================================

class TestTitleDeleteWithElectionHistory:

    def test_delete_with_election_history_400_and_row_intact(
        self, client, db, auth_for,
    ):
        """create title -> election referencing it -> close -> DELETE
        -> 400 with friendly copy; title row still present (the raw FK
        500 path is gone)."""
        org, steward, admin, members = _setup_org(db, "p67-titledel")
        title = _make_council_title(db, org, name="Treasurer Pool")
        pid = _open_election(client, auth_for, org, admin, title)
        # Close it out (zero candidates -> hold-over): the election is
        # history, not live, and the reference still blocks deletion.
        assert _advance(client, auth_for, pid, admin).status_code == 200
        assert _advance(client, auth_for, pid, admin).status_code == 200
        db.expire_all()
        assert _holders(db, title.id) == set()  # nothing to revoke

        r = client.delete(
            f"/api/orgs/{org.slug}/titles/{title.id}",
            headers=auth_for(steward),
        )
        assert r.status_code == 400, r.text
        detail = r.json()["detail"]
        assert "election history" in detail
        assert "can't be deleted" in detail

        db.expire_all()
        assert db.get(models.OrgTitle, title.id) is not None
        # The election proposal still references it.
        assert db.get(models.Proposal, pid).election_title_id == title.id

    def test_delete_with_open_election_also_400(
        self, client, db, auth_for,
    ):
        """An election still in its nomination window blocks deletion
        the same way (the FK reference exists from open)."""
        org, steward, admin, members = _setup_org(db, "p67-titledel-open")
        title = _make_council_title(db, org, name="Secretary Pool")
        _open_election(client, auth_for, org, admin, title)

        r = client.delete(
            f"/api/orgs/{org.slug}/titles/{title.id}",
            headers=auth_for(steward),
        )
        assert r.status_code == 400, r.text
        assert "election history" in r.json()["detail"]
        db.expire_all()
        assert db.get(models.OrgTitle, title.id) is not None

    def test_delete_without_election_history_still_works(
        self, client, db, auth_for,
    ):
        """The guard is not over-broad: a custom title nothing ever
        referenced deletes fine (204)."""
        org, steward, admin, members = _setup_org(db, "p67-titledel-ok")
        title = _make_council_title(db, org, name="Greeter")

        r = client.delete(
            f"/api/orgs/{org.slug}/titles/{title.id}",
            headers=auth_for(steward),
        )
        assert r.status_code == 204, r.text
        db.expire_all()
        assert db.get(models.OrgTitle, title.id) is None


# ===========================================================================
# W5 — personal delegation network with TOPIC-SPECIFIC delegations
# (regression: Topic.description read 500'd this path; no test covered it)
# ===========================================================================

class TestPersonalNetworkTopicSpecificDelegations:

    def test_topic_specific_outgoing_and_incoming_edges_200_with_name(
        self, client, db, auth_for,
    ):
        org, steward, admin, members = _setup_org(db, "p67-network", n_members=3)
        caller, delegate, delegator = members[0], members[1], members[2]
        topic = models.Topic(
            name="Budget", color="#ff8800", org_id=org.id,
        )
        db.add(topic)
        db.flush()
        # Outgoing: caller -> delegate on the topic.
        db.add(models.Delegation(
            delegator_id=caller.id,
            delegate_id=delegate.id,
            org_id=org.id,
            topic_id=topic.id,
        ))
        # Incoming: delegator -> caller on the topic.
        db.add(models.Delegation(
            delegator_id=delegator.id,
            delegate_id=caller.id,
            org_id=org.id,
            topic_id=topic.id,
        ))
        db.commit()

        r = client.get(
            f"/api/orgs/{org.slug}/delegations/network",
            headers=auth_for(caller),
        )
        assert r.status_code == 200, r.text
        body = r.json()

        outgoing = [e for e in body["edges"] if e["direction"] == "outgoing"]
        incoming = [e for e in body["edges"] if e["direction"] == "incoming"]
        assert len(outgoing) == 1
        assert len(incoming) == 1
        assert outgoing[0]["target"] == delegate.id
        assert [t["name"] for t in outgoing[0]["topics"]] == ["Budget"]
        assert incoming[0]["source"] == delegator.id
        assert [t["name"] for t in incoming[0]["topics"]] == ["Budget"]
        # Node topic chips carry the topic name too.
        node_topics = {n["id"]: n["topics"] for n in body["nodes"]}
        assert node_topics[delegate.id] == ["Budget"]
        assert node_topics[delegator.id] == ["Budget"]
