"""Phase 66a — election wiring for multi-winner approval voting.

Coverage map (spec: phase_66_multiwinner_approval.md, D6 + 66a bullets):

1. TestOpenElectionConfigValidation — _OpenElectionBody accepts the
   config for approval elections only: RCV election + config → 400
   (item e); num_winners must stay 1 when a config is set; single-
   holder titles require max_winners == 1; valid config round-trips
   through the open response + the DB row.
2. TestMultiWinnerApprovalElection — election close with N winners:
   resulting OrgTitle holder rows EXACTLY match the expected winner
   set (item a), bound-role grants applied (item b), floor preserved;
   Top-X and threshold modes; uncontested floor shortcut.
3. TestSlateModes — fill_vacancies vs refresh_slate with an approval
   config (item d), mirroring the Stage 2 STV semantics.
4. TestFloorDefense — engineered-violation scenario (item c):
   admin_council org with ONE active governor; a refresh_slate
   approval election whose winner set excludes the governor is
   REJECTED by the existing ``_check_revoke_floor`` defense
   (consulting ``governance.count_active_governors``); side-effect
   evidence that the governor keeps the role and the floor holds.
5. TestLegacyElectionUnchanged — approval election WITHOUT a config
   takes the pre-66a single-winner path byte-for-byte (item f).
6. TestBoundaryTieElection — a boundary tie in an approval election
   routes through the Phase 17 tie machinery and the RESOLVED set
   seats (item g); expand_winners overflow is capped at the title's
   capacity with the overflow recorded in the finalize audit detail.

Style mirrors test_phase_48_stage2_elections.py (route-driven close so
``finalize_election`` fires via the real hook) with Phase 66's
production-shape ballot casting (Vote.ballot JSON).
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
# Setup helpers (Stage 2 patterns)
# ---------------------------------------------------------------------------

def _make_org(
    db: Session, slug: str, *, extra_settings: dict | None = None,
) -> models.Organization:
    from org_titles import seed_system_titles_for_org
    from role_seed import seed_default_roles_for_org

    settings = {
        "default_deliberation_days": 3,
        "default_voting_days": 7,
        "default_pass_threshold": 0.50,
        "default_quorum_threshold": 0.0,
        "allowed_voting_methods": ["binary", "approval", "ranked_choice"],
        "elections": {"enabled": True},
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
    max_holders: int | None = None,
    cardinality_mode: str = "multi",
    bound_role: str | None = "admin",
) -> models.OrgTitle:
    title = models.OrgTitle(
        org_id=org.id,
        name="Council Member",
        bound_role=bound_role,
        cardinality_mode=cardinality_mode,
        max_holders=max_holders,
        fill_method="elected",
        is_system=False,
        display_order=50,
    )
    db.add(title)
    db.flush()
    db.commit()
    return title


def _setup_org(db: Session, slug: str, *, n_members: int = 8):
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


def _open_approval_election(
    client: TestClient, auth_for, org, opener, title, *,
    config: dict | None, slate_mode: str = "fill_vacancies",
    num_winners: int = 1,
):
    body = {
        "title_id": title.id,
        "voting_method": "approval",
        "num_winners": num_winners,
        "slate_mode": slate_mode,
    }
    if config is not None:
        body["approval_winner_config"] = config
    return client.post(
        f"/api/orgs/{org.slug}/elections",
        headers=auth_for(opener),
        json=body,
    )


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


def _option_id_for_candidate(
    db: Session, pid: str, user_id: str,
) -> str:
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


def _vote_counts_for_candidates(
    db: Session, pid: str, voters: list, counts_by_candidate: dict[str, int],
) -> None:
    """Each voter approves a slice of candidates so each candidate ends
    with the requested approval count. Voter i approves every candidate
    whose requested count is > i."""
    max_count = max(counts_by_candidate.values()) if counts_by_candidate else 0
    assert len(voters) >= max_count, "not enough voters for requested counts"
    oids = {
        uid: _option_id_for_candidate(db, pid, uid)
        for uid in counts_by_candidate
    }
    for i in range(max_count):
        approvals = [
            oids[uid] for uid, c in counts_by_candidate.items() if c > i
        ]
        _cast_approval_ballot(db, voters[i], pid, approvals)
    db.commit()


def _holders(db: Session, title_id: str) -> set[str]:
    return {
        r.user_id
        for r in db.query(models.OrgTitleAssignment).filter(
            models.OrgTitleAssignment.title_id == title_id,
        ).all()
    }


def _user_role(db: Session, org_id: str, user_id: str) -> str | None:
    m = db.query(models.OrgMembership).filter_by(
        org_id=org_id, user_id=user_id, status="active",
    ).first()
    if m is None or m.role_id is None:
        return None
    return db.get(models.Role, m.role_id).system_key


def _resolved_audit_details(db: Session, pid: str) -> dict:
    row = (
        db.query(models.AuditLog)
        .filter(
            models.AuditLog.action == "election.resolved",
            models.AuditLog.target_id == pid,
        )
        .order_by(models.AuditLog.timestamp.desc())
        .first()
    )
    assert row is not None, "election.resolved audit row missing"
    return row.details or {}


TOP2 = {"min_winners": 2, "max_winners": 2, "approval_threshold": None}


# ===========================================================================
# 1. Open-election config validation
# ===========================================================================

class TestOpenElectionConfigValidation:

    def test_rcv_election_with_config_400(self, client, db, auth_for):
        """Item (e): num_winners owns RCV — a ranked_choice election
        with an approval_winner_config is rejected."""
        org, steward, admin, members = _setup_org(db, "p66a-rcv400")
        title = _make_council_title(db, org)
        r = client.post(
            f"/api/orgs/{org.slug}/elections",
            headers=auth_for(admin),
            json={
                "title_id": title.id,
                "voting_method": "ranked_choice",
                "num_winners": 2,
                "approval_winner_config": TOP2,
            },
        )
        assert r.status_code == 400, r.text
        assert "approval-method elections" in r.json()["detail"]

    def test_config_with_num_winners_gt1_400(self, client, db, auth_for):
        org, steward, admin, members = _setup_org(db, "p66a-nw400")
        title = _make_council_title(db, org)
        r = _open_approval_election(
            client, auth_for, org, admin, title,
            config=TOP2, num_winners=2,
        )
        assert r.status_code == 400, r.text
        assert "num_winners must be 1" in r.json()["detail"]

    def test_single_holder_title_config_must_cap_at_one(
        self, client, db, auth_for,
    ):
        org, steward, admin, members = _setup_org(db, "p66a-single400")
        title = _make_council_title(
            db, org, cardinality_mode="single",
        )
        r = _open_approval_election(
            client, auth_for, org, admin, title, config=TOP2,
        )
        assert r.status_code == 400, r.text
        assert "max_winners must be 1" in r.json()["detail"]
        # max_winners == 1 is accepted on a single-holder title.
        r = _open_approval_election(
            client, auth_for, org, admin, title,
            config={"min_winners": 1, "max_winners": 1,
                    "approval_threshold": None},
        )
        assert r.status_code == 201, r.text

    def test_invalid_config_shape_422(self, client, db, auth_for):
        """The shared Phase 66 schema validator runs on the election
        body too."""
        org, steward, admin, members = _setup_org(db, "p66a-shape422")
        title = _make_council_title(db, org)
        r = _open_approval_election(
            client, auth_for, org, admin, title,
            config={"min_winners": 0, "max_winners": 5,
                    "approval_threshold": None},  # vacuous
        )
        assert r.status_code == 422, r.text

    def test_valid_config_round_trips(self, client, db, auth_for):
        """Open response + DB row both carry the config (Phase 32.1
        round-trip lesson)."""
        org, steward, admin, members = _setup_org(db, "p66a-roundtrip")
        title = _make_council_title(db, org)
        r = _open_approval_election(
            client, auth_for, org, admin, title, config=TOP2,
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["is_election"] is True
        assert body["voting_method"] == "approval"
        assert body["approval_winner_config"] == TOP2
        db.expire_all()
        row = db.get(models.Proposal, body["id"])
        assert row.approval_winner_config == TOP2

    def test_election_without_config_unaffected(self, client, db, auth_for):
        """Opening an approval election WITHOUT a config keeps the
        legacy NULL column (item f, open-side)."""
        org, steward, admin, members = _setup_org(db, "p66a-noconfig")
        title = _make_council_title(db, org)
        r = _open_approval_election(
            client, auth_for, org, admin, title, config=None,
        )
        assert r.status_code == 201, r.text
        assert r.json()["approval_winner_config"] is None


# ===========================================================================
# 2. Multi-winner approval election close (items a + b + floor)
# ===========================================================================

class TestMultiWinnerApprovalElection:

    def test_top2_seats_exact_winner_set_and_roles(
        self, client, db, auth_for,
    ):
        """Items (a) + (b): Top-2 config seats EXACTLY the two
        most-approved candidates; bound role granted to both; the
        third candidate gets neither; floor preserved."""
        org, steward, admin, members = _setup_org(db, "p66a-top2")
        title = _make_council_title(db, org)
        r = _open_approval_election(
            client, auth_for, org, admin, title, config=TOP2,
        )
        pid = r.json()["id"]
        for c in members[:3]:
            _declare(client, auth_for, org, pid, c)
        assert _advance(client, auth_for, pid, admin).status_code == 200
        # Approvals: m0=3, m1=2, m2=1 → Top 2 = {m0, m1}.
        _vote_counts_for_candidates(
            db, pid, voters=members[3:],
            counts_by_candidate={
                members[0].id: 3, members[1].id: 2, members[2].id: 1,
            },
        )
        assert _advance(client, auth_for, pid, admin).status_code == 200
        db.expire_all()
        # (a) exact holder set.
        assert _holders(db, title.id) == {members[0].id, members[1].id}
        # (b) bound-role grants.
        assert _user_role(db, org.id, members[0].id) == "admin"
        assert _user_role(db, org.id, members[1].id) == "admin"
        assert _user_role(db, org.id, members[2].id) == "member"
        # Floor preserved (single_steward mode: steward intact).
        from governance import count_active_governors
        assert count_active_governors(db, org) >= 1
        assert _user_role(db, org.id, steward.id) == "steward"
        # Audit carries the 66a transparency keys.
        details = _resolved_audit_details(db, pid)
        assert details["approval_winner_config"] == TOP2
        assert details["capacity_overflow_winner_ids"] == []
        assert sorted(details["winner_ids"]) == sorted(
            [members[0].id, members[1].id],
        )

    def test_threshold_mode_seats_all_clearing_candidates(
        self, client, db, auth_for,
    ):
        """Threshold mode: every candidate above B% of ballots cast
        wins. m0 (3/4) + m1 (2/4) clear 50%; m2 (1/4) doesn't."""
        org, steward, admin, members = _setup_org(db, "p66a-thresh")
        title = _make_council_title(db, org)
        cfg = {"min_winners": 0, "max_winners": None,
               "approval_threshold": 0.5}
        r = _open_approval_election(
            client, auth_for, org, admin, title, config=cfg,
        )
        pid = r.json()["id"]
        for c in members[:3]:
            _declare(client, auth_for, org, pid, c)
        assert _advance(client, auth_for, pid, admin).status_code == 200
        # 4 ballots cast: m0=3 (75%), m1=2 (50%), m2=1 (25%).
        _vote_counts_for_candidates(
            db, pid, voters=members[3:7],
            counts_by_candidate={
                members[0].id: 3, members[1].id: 2, members[2].id: 1,
            },
        )
        # A fourth ballot approving only m0 already exists via counts
        # (voter 0..2 cover max count 3) — add an abstain ballot so
        # ballots cast = 4 and m1 sits exactly at the 50% boundary
        # (>= threshold seats, mirroring pass_threshold semantics).
        _cast_approval_ballot(db, members[6], pid, [])
        db.commit()
        assert _advance(client, auth_for, pid, admin).status_code == 200
        db.expire_all()
        assert _holders(db, title.id) == {members[0].id, members[1].id}

    def test_uncontested_floor_shortcut(self, client, db, auth_for):
        """D6 generalization: candidates <= min_winners → all win
        without a tally (mirrors Stage 2's candidates <= num_winners)."""
        org, steward, admin, members = _setup_org(db, "p66a-uncontested")
        title = _make_council_title(db, org)
        cfg = {"min_winners": 3, "max_winners": 3,
               "approval_threshold": None}
        r = _open_approval_election(
            client, auth_for, org, admin, title, config=cfg,
        )
        pid = r.json()["id"]
        for c in members[:2]:
            _declare(client, auth_for, org, pid, c)
        assert _advance(client, auth_for, pid, admin).status_code == 200
        # No votes cast at all — uncontested.
        assert _advance(client, auth_for, pid, admin).status_code == 200
        db.expire_all()
        assert _holders(db, title.id) == {members[0].id, members[1].id}
        assert _resolved_audit_details(db, pid)["auto_win_uncontested"] is True


# ===========================================================================
# 3. Slate modes (item d)
# ===========================================================================

class TestSlateModes:

    def _seed_holder(self, db, org, title, user) -> None:
        db.add(models.OrgTitleAssignment(
            title_id=title.id, user_id=user.id,
        ))
        mb = db.query(models.OrgMembership).filter_by(
            org_id=org.id, user_id=user.id,
        ).one()
        admin_role = db.query(models.Role).filter_by(
            org_id=org.id, system_key="admin",
        ).one()
        mb.role_id = admin_role.id
        db.commit()

    def test_fill_vacancies_keeps_existing_holders(
        self, client, db, auth_for,
    ):
        org, steward, admin, members = _setup_org(db, "p66a-fill")
        title = _make_council_title(db, org)
        self._seed_holder(db, org, title, members[0])
        r = _open_approval_election(
            client, auth_for, org, admin, title,
            config=TOP2, slate_mode="fill_vacancies",
        )
        pid = r.json()["id"]
        for c in members[1:4]:
            _declare(client, auth_for, org, pid, c)
        assert _advance(client, auth_for, pid, admin).status_code == 200
        _vote_counts_for_candidates(
            db, pid, voters=members[4:],
            counts_by_candidate={
                members[1].id: 3, members[2].id: 2, members[3].id: 1,
            },
        )
        assert _advance(client, auth_for, pid, admin).status_code == 200
        db.expire_all()
        # Incumbent kept + the two winners added.
        assert _holders(db, title.id) == {
            members[0].id, members[1].id, members[2].id,
        }

    def test_refresh_slate_replaces_non_winning_holders(
        self, client, db, auth_for,
    ):
        """refresh_slate: existing holders are replaced by the winner
        set; an incumbent who wins again keeps the seat (no churn)."""
        org, steward, admin, members = _setup_org(db, "p66a-refresh")
        title = _make_council_title(db, org)
        self._seed_holder(db, org, title, members[0])  # will lose seat
        self._seed_holder(db, org, title, members[1])  # incumbent winner
        r = _open_approval_election(
            client, auth_for, org, admin, title,
            config=TOP2, slate_mode="refresh_slate",
        )
        pid = r.json()["id"]
        for c in (members[1], members[2], members[3]):
            _declare(client, auth_for, org, pid, c)
        assert _advance(client, auth_for, pid, admin).status_code == 200
        _vote_counts_for_candidates(
            db, pid, voters=members[4:],
            counts_by_candidate={
                members[1].id: 3, members[2].id: 2, members[3].id: 1,
            },
        )
        assert _advance(client, auth_for, pid, admin).status_code == 200
        db.expire_all()
        # members[0] wiped; members[1] kept; members[2] added.
        assert _holders(db, title.id) == {members[1].id, members[2].id}
        from governance import count_active_governors
        assert count_active_governors(db, org) >= 1

    def test_fill_vacancies_capacity_overflow_recorded(
        self, client, db, auth_for,
    ):
        """max_holders=2 with one seat occupied: a Top-2 winner set
        only seats one new holder; the overflow is audited, not
        silently dropped."""
        org, steward, admin, members = _setup_org(db, "p66a-cap")
        title = _make_council_title(db, org, max_holders=2)
        self._seed_holder(db, org, title, members[0])  # occupies a seat
        r = _open_approval_election(
            client, auth_for, org, admin, title,
            config=TOP2, slate_mode="fill_vacancies",
        )
        pid = r.json()["id"]
        for c in (members[1], members[2], members[3]):
            _declare(client, auth_for, org, pid, c)
        assert _advance(client, auth_for, pid, admin).status_code == 200
        _vote_counts_for_candidates(
            db, pid, voters=members[4:],
            counts_by_candidate={
                members[1].id: 3, members[2].id: 2, members[3].id: 1,
            },
        )
        assert _advance(client, auth_for, pid, admin).status_code == 200
        db.expire_all()
        # Only the top winner fits the remaining seat.
        assert _holders(db, title.id) == {members[0].id, members[1].id}
        details = _resolved_audit_details(db, pid)
        assert details["capacity_overflow_winner_ids"] == [members[2].id]


# ===========================================================================
# 4. Floor defense (item c — engineered violation)
# ===========================================================================

class TestFloorDefense:

    def test_refresh_slate_cannot_demote_last_governor(
        self, client, db, auth_for,
    ):
        """Engineered to violate the floor WITHOUT the defense: an
        admin_council org with exactly ONE active governor runs a
        refresh_slate approval election on the system Admin title
        whose winner set excludes the governor. Without
        ``_check_revoke_floor`` (which consults
        ``governance.count_active_governors``) the refresh would
        demote the only admin to member BEFORE the winners are
        installed → zero governors. The defense rejects the refresh;
        side-effect evidence below."""
        from governance import count_active_governors

        org = _make_org(db, "p66a-floor")
        org.governance_mode = "admin_council"
        gov = make_user(db, "p66a-floor-gov")
        members = [make_user(db, f"p66a-floor-m{i}") for i in range(6)]
        make_org_membership(db, org_id=org.id, user_id=gov.id, role="admin")
        for m in members:
            make_org_membership(
                db, org_id=org.id, user_id=m.id, role="member",
            )
        db.commit()
        assert count_active_governors(db, org) == 1  # precondition

        admin_title = db.query(models.OrgTitle).filter_by(
            org_id=org.id, name="Admin", is_system=True,
        ).one()
        admin_title.fill_method = "elected"
        db.commit()

        r = _open_approval_election(
            client, auth_for, org, gov, admin_title,
            config=TOP2, slate_mode="refresh_slate",
        )
        assert r.status_code == 201, r.text
        pid = r.json()["id"]
        # Two members run; the sitting governor does NOT.
        _declare(client, auth_for, org, pid, members[0])
        _declare(client, auth_for, org, pid, members[1])
        assert _advance(client, auth_for, pid, gov).status_code == 200
        _vote_counts_for_candidates(
            db, pid, voters=members[2:5],
            counts_by_candidate={members[0].id: 3, members[1].id: 2},
        )
        assert _advance(client, auth_for, pid, gov).status_code == 200
        db.expire_all()

        # The defense held: the governor keeps the admin role; the
        # would-be winners were NOT installed; the floor invariant
        # holds with side-effect evidence.
        org_refreshed = db.get(models.Organization, org.id)
        assert _user_role(db, org.id, gov.id) == "admin"
        assert _user_role(db, org.id, members[0].id) == "member"
        assert _user_role(db, org.id, members[1].id) == "member"
        assert count_active_governors(db, org_refreshed) == 1
        details = _resolved_audit_details(db, pid)
        assert details["outcome"] == "slate_refresh_rejected"

    def test_refresh_slate_floor_allows_replacement_with_governor_present(
        self, client, db, auth_for,
    ):
        """Counterpart: with TWO governors, refreshing the custom
        admin-bound council title around one of them is allowed and
        the floor still holds afterwards."""
        from governance import count_active_governors

        org, steward, admin, members = _setup_org(db, "p66a-floor-ok")
        title = _make_council_title(db, org)
        # members[0] is a current holder with the bound admin role.
        db.add(models.OrgTitleAssignment(
            title_id=title.id, user_id=members[0].id,
        ))
        mb = db.query(models.OrgMembership).filter_by(
            org_id=org.id, user_id=members[0].id,
        ).one()
        admin_role = db.query(models.Role).filter_by(
            org_id=org.id, system_key="admin",
        ).one()
        mb.role_id = admin_role.id
        db.commit()

        r = _open_approval_election(
            client, auth_for, org, admin, title,
            config=TOP2, slate_mode="refresh_slate",
        )
        pid = r.json()["id"]
        _declare(client, auth_for, org, pid, members[1])
        _declare(client, auth_for, org, pid, members[2])
        assert _advance(client, auth_for, pid, admin).status_code == 200
        _vote_counts_for_candidates(
            db, pid, voters=members[3:6],
            counts_by_candidate={members[1].id: 3, members[2].id: 2},
        )
        assert _advance(client, auth_for, pid, admin).status_code == 200
        db.expire_all()
        assert _holders(db, title.id) == {members[1].id, members[2].id}
        assert count_active_governors(db, org) >= 1


# ===========================================================================
# 5. Legacy (NULL-config) election path unchanged (item f)
# ===========================================================================

class TestLegacyElectionUnchanged:

    def test_approval_election_without_config_single_winner(
        self, client, db, auth_for,
    ):
        """No config → the pre-66a path: legacy max-approval tally,
        num_winners=1, exactly one winner seated; no 66a audit keys."""
        org, steward, admin, members = _setup_org(db, "p66a-legacy")
        title = _make_council_title(db, org)
        r = _open_approval_election(
            client, auth_for, org, admin, title, config=None,
        )
        pid = r.json()["id"]
        for c in members[:3]:
            _declare(client, auth_for, org, pid, c)
        assert _advance(client, auth_for, pid, admin).status_code == 200
        _vote_counts_for_candidates(
            db, pid, voters=members[3:6],
            counts_by_candidate={
                members[0].id: 3, members[1].id: 2, members[2].id: 1,
            },
        )
        assert _advance(client, auth_for, pid, admin).status_code == 200
        db.expire_all()
        # Single winner only — multi-winner needs the config.
        assert _holders(db, title.id) == {members[0].id}
        assert _user_role(db, org.id, members[0].id) == "admin"
        assert _user_role(db, org.id, members[1].id) == "member"
        details = _resolved_audit_details(db, pid)
        assert "approval_winner_config" not in details
        assert "capacity_overflow_winner_ids" not in details

    def test_legacy_uncontested_auto_win_unchanged(
        self, client, db, auth_for,
    ):
        """candidates <= num_winners auto-win still fires on the
        NULL-config path (Stage 2 semantics untouched)."""
        org, steward, admin, members = _setup_org(db, "p66a-legacyauto")
        title = _make_council_title(db, org)
        r = _open_approval_election(
            client, auth_for, org, admin, title, config=None,
        )
        pid = r.json()["id"]
        _declare(client, auth_for, org, pid, members[0])
        assert _advance(client, auth_for, pid, admin).status_code == 200
        assert _advance(client, auth_for, pid, admin).status_code == 200
        db.expire_all()
        assert _holders(db, title.id) == {members[0].id}


# ===========================================================================
# 6. Boundary ties (item g)
# ===========================================================================

class TestBoundaryTieElection:

    def test_boundary_tie_routes_through_resolver_and_seats(
        self, client, db, auth_for,
    ):
        """Top-1 with two candidates tied: the boundary subset goes
        through the org's Phase 17 resolver; the RESOLVED winner is
        the one seated; Proposal.tie_resolution is persisted."""
        org, steward, admin, members = _setup_org(db, "p66a-tie")
        # Deterministic single-pick resolver behavior isn't needed —
        # assert the resolved choice is honored whichever way it lands.
        org.settings = {
            **org.settings,
            "tie_resolution": {"approval": "random_seed"},
        }
        db.commit()
        title = _make_council_title(db, org, cardinality_mode="single",
                                    bound_role=None)
        cfg = {"min_winners": 1, "max_winners": 1,
               "approval_threshold": None}
        r = _open_approval_election(
            client, auth_for, org, admin, title, config=cfg,
        )
        pid = r.json()["id"]
        _declare(client, auth_for, org, pid, members[0])
        _declare(client, auth_for, org, pid, members[1])
        assert _advance(client, auth_for, pid, admin).status_code == 200
        # One approval each → tied at the only seat.
        _cast_approval_ballot(
            db, members[2], pid,
            [_option_id_for_candidate(db, pid, members[0].id)],
        )
        _cast_approval_ballot(
            db, members[3], pid,
            [_option_id_for_candidate(db, pid, members[1].id)],
        )
        db.commit()
        assert _advance(client, auth_for, pid, admin).status_code == 200
        db.expire_all()

        proposal = db.get(models.Proposal, pid)
        tr = proposal.tie_resolution
        assert tr is not None
        assert tr["method"] == "random_seed"
        assert set(tr["input_winners"]) == {
            _option_id_for_candidate(db, pid, members[0].id),
            _option_id_for_candidate(db, pid, members[1].id),
        }
        assert len(tr["chosen_winners"]) == 1
        chosen_opt = db.get(models.ProposalOption, tr["chosen_winners"][0])
        # The seated holder is EXACTLY the resolved option's candidate.
        assert _holders(db, title.id) == {chosen_opt.label}
        # Exactly one tie_resolved audit row — finalize merged the
        # route-layer resolution instead of re-resolving.
        tie_rows = db.query(models.AuditLog).filter(
            models.AuditLog.action == "proposal.tie_resolved",
            models.AuditLog.target_id == pid,
        ).count()
        assert tie_rows == 1

    def test_expand_winners_overflow_capped_at_capacity(
        self, client, db, auth_for,
    ):
        """expand_winners seats ALL boundary-tied options (documented
        D4/D11 semantics) — on a single-holder title the set exceeds
        capacity; 66a seats up to capacity in tally-winner order and
        records the overflow in the finalize audit detail."""
        org, steward, admin, members = _setup_org(db, "p66a-expand")
        org.settings = {
            **org.settings,
            "tie_resolution": {"approval": "expand_winners"},
        }
        db.commit()
        title = _make_council_title(db, org, cardinality_mode="single",
                                    bound_role=None)
        cfg = {"min_winners": 1, "max_winners": 1,
               "approval_threshold": None}
        r = _open_approval_election(
            client, auth_for, org, admin, title, config=cfg,
        )
        pid = r.json()["id"]
        _declare(client, auth_for, org, pid, members[0])
        _declare(client, auth_for, org, pid, members[1])
        assert _advance(client, auth_for, pid, admin).status_code == 200
        _cast_approval_ballot(
            db, members[2], pid,
            [_option_id_for_candidate(db, pid, members[0].id)],
        )
        _cast_approval_ballot(
            db, members[3], pid,
            [_option_id_for_candidate(db, pid, members[1].id)],
        )
        db.commit()
        assert _advance(client, auth_for, pid, admin).status_code == 200
        db.expire_all()

        holders = _holders(db, title.id)
        assert len(holders) == 1  # capacity 1 enforced
        details = _resolved_audit_details(db, pid)
        overflow = details["capacity_overflow_winner_ids"]
        assert len(overflow) == 1
        # Seated + overflow partition the tied pair.
        assert holders | set(overflow) == {members[0].id, members[1].id}
