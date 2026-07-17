"""Phase 66 — multi-winner approval voting (core; election wiring is 66a).

Coverage map (spec: phase_66_multiwinner_approval.md):

1. TestPureSelection        — D3 selection algorithm + D2 denominator +
                              NULL-config byte-for-byte parity.
2. TestBoundaryTies         — D4 pure-layer boundary-tie exposure.
3. TestRouteBoundaryTie     — D4 route layer: advance routes the tied
                              subset through resolve_tie; side-effect
                              assertions on Proposal.tie_resolution +
                              the audit row (both invocation sites).
4. TestConfigValidation     — Pydantic 422s, route 400s (non-approval
                              methods, elections, non-draft PATCH).
5. TestD5WinnerSets         — winner_set_overlaps order-insensitivity
                              with multi-winner sets + worker snapshot
                              round-trip of a multi-winner list.
6. TestRoundTrip            — config through BOTH create endpoints and
                              back out of _build_proposal_out + the
                              results surface (winner_seats).

Style mirrors test_phase_17_tie_resolution.py: in-memory SQLite,
explicit fixtures, side-effect assertions per CLAUDE.md.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from database import Base, get_db
from delegation_engine import (
    ApprovalTally,
    Ballot,
    ProposalContext,
    compute_tally_pure,
    select_approval_winners_with_config,
)
from main import app
from role_seed import seed_default_roles_for_org
from sustained_majority import MultiOptionSnapshotPoint, winner_set_overlaps
from tests.conftest import make_org_membership


_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


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
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def client(test_db: Session):
    def _get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(db: Session, username: str) -> models.User:
    u = models.User(
        username=username,
        display_name=username,
        password_hash=_DUMMY_HASH,
        email=f"{username}@test.example",
        email_verified=True,
    )
    db.add(u)
    db.flush()
    return u


def _make_org(
    db: Session, slug: str, *, settings: dict | None = None,
) -> models.Organization:
    o = models.Organization(
        name=slug.title(), slug=slug, description="",
        settings=settings if settings is not None else {},
    )
    db.add(o)
    db.flush()
    seed_default_roles_for_org(db, o.id)
    return o


def _auth(user: models.User) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _make_approval_proposal(
    db: Session,
    author: models.User,
    org: models.Organization,
    *,
    option_labels: list[str],
    status: str = "voting",
    config: dict | None = None,
    is_election: bool = False,
) -> models.Proposal:
    p = models.Proposal(
        title="MW Approval P",
        body="",
        author_id=author.id,
        voting_method="approval",
        status=status,
        org_id=org.id,
        voting_start=datetime.now(timezone.utc) - timedelta(days=1),
        voting_end=datetime.now(timezone.utc) - timedelta(minutes=1),
        approval_winner_config=config,
        is_election=is_election,
    )
    db.add(p)
    db.flush()
    for i, label in enumerate(option_labels):
        db.add(models.ProposalOption(
            proposal_id=p.id, label=label, description="",
            display_order=i,
        ))
    db.flush()
    return p


def _option_ids_by_label(
    db: Session, proposal: models.Proposal,
) -> dict[str, str]:
    rows = db.query(models.ProposalOption).filter(
        models.ProposalOption.proposal_id == proposal.id,
    ).all()
    return {r.label: r.id for r in rows}


def _cast_approval_vote(
    db: Session,
    user: models.User,
    proposal: models.Proposal,
    approvals: list[str],
) -> models.Vote:
    """Production storage shape: ballot data lives in Vote.ballot JSON."""
    v = models.Vote(
        proposal_id=proposal.id,
        user_id=user.id,
        vote_value=None,
        ballot={"approvals": approvals},
        is_direct=True,
        cast_by_id=user.id,
    )
    db.add(v)
    db.flush()
    return v


def _ctx(
    direct_ballots: dict[str, Ballot],
    *,
    config: dict | None = None,
) -> ProposalContext:
    return ProposalContext(
        proposal_topics=[],
        all_delegations={},
        all_precedences={},
        direct_votes={},
        direct_ballots=direct_ballots,
        voting_method="approval",
        approval_winner_config=config,
    )


def _seed_votes_for_counts(
    db: Session,
    org: models.Organization,
    proposal: models.Proposal,
    counts_by_label: dict[str, int],
    *,
    prefix: str,
) -> int:
    """Create one voter per ballot; each ballot approves exactly one
    option. Returns the number of voters created."""
    oids = _option_ids_by_label(db, proposal)
    n = 0
    for label, count in counts_by_label.items():
        for i in range(count):
            u = _make_user(db, f"{prefix}-{label}-{i}")
            make_org_membership(
                db, org_id=org.id, user_id=u.id, role="member",
            )
            _cast_approval_vote(db, u, proposal, [oids[label]])
            n += 1
    return n


# ---------------------------------------------------------------------------
# 1. Pure-layer selection (D3 + D2 denominator + NULL parity)
# ---------------------------------------------------------------------------

class TestPureSelection:

    def test_null_config_identical_to_legacy(self):
        """NULL config ⇒ exactly today's behavior: winners = the
        max-approval set, no Phase 66 fields populated. (The untouched
        pre-existing approval suite is the broader proof.)"""
        ballots = {
            "u1": Ballot(approvals=["A", "B"]),
            "u2": Ballot(approvals=["A"]),
            "u3": Ballot(approvals=["B"]),
            "u4": Ballot(approvals=[]),       # abstain
        }
        tally = compute_tally_pure(
            ["u1", "u2", "u3", "u4", "u5"], _ctx(ballots, config=None),
        )
        assert isinstance(tally, ApprovalTally)
        # Pre-change expectations, hand-computed: A=2, B=2 → tied max set.
        assert tally.option_approvals == {"A": 2, "B": 2}
        assert sorted(tally.winners) == ["A", "B"]
        assert tally.tied is True
        assert tally.total_ballots_cast == 4   # abstain ballot counts
        assert tally.total_abstain == 1
        assert tally.not_cast == 1
        # Phase 66 fields stay at their empty defaults on the legacy path.
        assert tally.winner_seats == {}
        assert tally.boundary_tied == []
        assert tally.seats_remaining == 0

    def test_top_x_exact_winner_set(self):
        """Top X preset: min=max=X, threshold null."""
        counts = {"A": 5, "B": 4, "C": 3, "D": 1}
        winners, seats, tied, boundary, remaining = (
            select_approval_winners_with_config(
                counts, 10,
                {"min_winners": 2, "max_winners": 2,
                 "approval_threshold": None},
            )
        )
        assert winners == ["A", "B"]
        assert seats == {"A": "floor", "B": "floor"}
        assert tied is False
        assert boundary == [] and remaining == 0

    def test_threshold_preset_exact_set(self):
        """Threshold preset: min=0, max null, threshold=B. Denominator
        is ballots cast."""
        counts = {"A": 6, "B": 5, "C": 4}
        winners, seats, tied, boundary, remaining = (
            select_approval_winners_with_config(
                counts, 10,
                {"min_winners": 0, "max_winners": None,
                 "approval_threshold": 0.5},
            )
        )
        assert winners == ["A", "B"]    # 0.6, 0.5 clear; 0.4 does not
        assert seats == {"A": "threshold", "B": "threshold"}
        assert tied is False

    def test_threshold_zero_winner_case(self):
        """Nobody clears the threshold and min=0 ⇒ empty winner set."""
        counts = {"A": 3, "B": 2}
        winners, seats, tied, boundary, remaining = (
            select_approval_winners_with_config(
                counts, 10,
                {"min_winners": 0, "max_winners": None,
                 "approval_threshold": 0.5},
            )
        )
        assert winners == []
        assert seats == {}
        assert tied is False

    def test_threshold_denominator_includes_abstain_ballots(self):
        """D2 — empty-approval (abstain) ballots count in the
        denominator, mirroring the existing quorum math. 5 approvals
        over 10 non-abstain ballots would be 50%; one extra abstain
        ballot makes it 5/11 < 50% and the option must NOT seat."""
        ballots = {f"u{i}": Ballot(approvals=["A"]) for i in range(5)}
        for i in range(5, 10):
            ballots[f"u{i}"] = Ballot(approvals=["B"])
        ballots["u10"] = Ballot(approvals=[])  # abstain — in denominator
        tally = compute_tally_pure(
            list(ballots.keys()),
            _ctx(ballots, config={
                "min_winners": 0, "max_winners": None,
                "approval_threshold": 0.5,
            }),
        )
        assert tally.total_ballots_cast == 11
        assert tally.winners == []  # 5/11 ≈ 0.4545 < 0.5 for both A and B

    def test_floor_plus_extras(self):
        """Floor + conditional extras: the floor seats even below the
        threshold; extras only above it; the max cap is honored."""
        # Denominator 10; distinct counts so no boundary ambiguity
        # (boundary ties are covered separately).
        counts = {"A": 7, "B": 5, "C": 4, "D": 3}
        winners, seats, tied, boundary, remaining = (
            select_approval_winners_with_config(
                counts, 10,
                {"min_winners": 2, "max_winners": 3,
                 "approval_threshold": 0.65},
            )
        )
        # A clears 0.65 (floor seat #1); B at 0.5 does NOT clear but
        # seats via the unconditional floor (seat #2); C at 0.4 is below
        # threshold and the floor is full → does not seat.
        assert winners == ["A", "B"]
        assert seats == {"A": "floor", "B": "floor"}
        assert tied is False

    def test_floor_plus_extras_max_cap(self):
        """Extras above the threshold seat only until max_winners."""
        counts = {"A": 9, "B": 8, "C": 7, "D": 6}
        winners, seats, tied, boundary, remaining = (
            select_approval_winners_with_config(
                counts, 10,
                {"min_winners": 1, "max_winners": 3,
                 "approval_threshold": 0.5},
            )
        )
        # All four clear 0.5 but max=3 caps the seats; D (count 6,
        # unique) simply doesn't fit — no tie.
        assert winners == ["A", "B", "C"]
        assert seats == {"A": "floor", "B": "threshold", "C": "threshold"}
        assert tied is False

    def test_threshold_null_only_floor_seats(self):
        """Threshold null ⇒ only the unconditional floor seats, even
        with max_winners headroom."""
        counts = {"A": 9, "B": 8, "C": 7}
        winners, seats, tied, boundary, remaining = (
            select_approval_winners_with_config(
                counts, 10,
                {"min_winners": 1, "max_winners": 3,
                 "approval_threshold": None},
            )
        )
        assert winners == ["A"]
        assert seats == {"A": "floor"}

    def test_fewer_approved_options_than_floor(self):
        """min_winners larger than the number of options anyone approved:
        every approved option seats; no phantom seats."""
        counts = {"A": 2, "B": 1}
        winners, seats, tied, boundary, remaining = (
            select_approval_winners_with_config(
                counts, 5,
                {"min_winners": 3, "max_winners": 3,
                 "approval_threshold": None},
            )
        )
        assert winners == ["A", "B"]
        assert tied is False


# ---------------------------------------------------------------------------
# 2. Pure-layer boundary ties (D4)
# ---------------------------------------------------------------------------

class TestBoundaryTies:

    def test_boundary_tie_at_floor(self):
        """Top 2 with #2/#3 tied: the unambiguous winner seats; the tied
        pair is exposed with 1 seat remaining."""
        counts = {"A": 5, "B": 3, "C": 3, "D": 1}
        winners, seats, tied, boundary, remaining = (
            select_approval_winners_with_config(
                counts, 10,
                {"min_winners": 2, "max_winners": 2,
                 "approval_threshold": None},
            )
        )
        assert winners == ["A"]
        assert seats == {"A": "floor"}
        assert tied is True
        assert sorted(boundary) == ["B", "C"]
        assert remaining == 1

    def test_boundary_tie_at_max_cap(self):
        """Threshold-cleared equal-count group only partially fits under
        max_winners."""
        counts = {"A": 9, "B": 8, "C": 8, "D": 8}
        winners, seats, tied, boundary, remaining = (
            select_approval_winners_with_config(
                counts, 10,
                {"min_winners": 1, "max_winners": 3,
                 "approval_threshold": 0.5},
            )
        )
        assert winners == ["A"]
        assert tied is True
        assert sorted(boundary) == ["B", "C", "D"]
        assert remaining == 2

    def test_full_tie_at_top_single_seat(self):
        """Top 1 with the top two tied: nobody seats unambiguously."""
        counts = {"A": 3, "B": 3}
        winners, seats, tied, boundary, remaining = (
            select_approval_winners_with_config(
                counts, 6,
                {"min_winners": 1, "max_winners": 1,
                 "approval_threshold": None},
            )
        )
        assert winners == []
        assert tied is True
        assert sorted(boundary) == ["A", "B"]
        assert remaining == 1


# ---------------------------------------------------------------------------
# 3. Route-layer boundary-tie resolution (D4) — side-effect assertions
# ---------------------------------------------------------------------------

class TestRouteBoundaryTie:

    def _setup(self, db, slug, *, settings=None):
        org = _make_org(db, slug, settings=settings)
        steward = _make_user(db, f"{slug}-steward")
        make_org_membership(
            db, org_id=org.id, user_id=steward.id, role="steward",
        )
        return org, steward

    def test_advance_resolves_boundary_tie_and_persists_audit(
        self, client, test_db,
    ):
        """Top 2 with a 2-way tie for the second seat: the remaining
        seat routes through resolve_tie (random_seed); the proposal
        passes with the merged winner set and the Proposal.tie_resolution
        audit record + audit-log row are persisted."""
        org, steward = self._setup(
            test_db, "mw-rand",
            settings={"tie_resolution": {"approval": "random_seed"}},
        )
        p = _make_approval_proposal(
            test_db, steward, org, option_labels=["A", "B", "C", "D"],
            config={"min_winners": 2, "max_winners": 2,
                    "approval_threshold": None},
        )
        oids = _option_ids_by_label(test_db, p)
        # A=3, B=2, C=2, D=1 → A seats; B/C tied for the last seat.
        _seed_votes_for_counts(
            test_db, org, p, {"A": 3, "B": 2, "C": 2, "D": 1},
            prefix="mw-rand",
        )
        p.quorum_threshold = 0.5
        test_db.commit()

        resp = client.post(
            f"/api/proposals/{p.id}/advance", headers=_auth(steward),
            json={},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "passed"

        # Side-effect 1: persisted Proposal.tie_resolution record.
        test_db.expire_all()
        row = test_db.get(models.Proposal, p.id)
        tr = row.tie_resolution
        assert tr is not None
        assert tr["method"] == "random_seed"
        assert sorted(tr["input_winners"]) == sorted(
            [oids["B"], oids["C"]],
        )
        assert len(tr["chosen_winners"]) == 1
        assert tr["chosen_winners"][0] in (oids["B"], oids["C"])
        assert tr["seed"] is not None
        assert tr["metadata"]["boundary_tie"] is True
        assert tr["metadata"]["seats_remaining"] == 1
        assert "applied_at" in tr

        # Side-effect 2: audit-log row.
        audit = test_db.query(models.AuditLog).filter(
            models.AuditLog.action == "proposal.tie_resolved",
            models.AuditLog.target_id == p.id,
        ).first()
        assert audit is not None
        assert audit.details["boundary_tie"] is True
        assert audit.details["method"] == "random_seed"

        # Results surface: winner_seats attributes A=floor and the
        # resolver's pick as tie_resolution.
        results = client.get(
            f"/api/proposals/{p.id}/results", headers=_auth(steward),
        )
        assert results.status_code == 200, results.text
        body = results.json()
        assert body["winner_seats"][oids["A"]] == "floor"
        chosen = tr["chosen_winners"][0]
        assert body["winner_seats"][chosen] == "tie_resolution"
        assert body["tied"] is True
        assert body["approval_winner_config"]["min_winners"] == 2

    def test_advance_boundary_tie_expand_winners_seats_all(
        self, client, test_db,
    ):
        """expand_winners seats ALL boundary-tied options — documented
        D11 semantics; the result may exceed max_winners."""
        org, steward = self._setup(
            test_db, "mw-expand",
            settings={"tie_resolution": {"approval": "expand_winners"}},
        )
        p = _make_approval_proposal(
            test_db, steward, org, option_labels=["A", "B", "C"],
            config={"min_winners": 2, "max_winners": 2,
                    "approval_threshold": None},
        )
        oids = _option_ids_by_label(test_db, p)
        _seed_votes_for_counts(
            test_db, org, p, {"A": 3, "B": 2, "C": 2}, prefix="mw-exp",
        )
        p.quorum_threshold = 0.5
        test_db.commit()

        resp = client.post(
            f"/api/proposals/{p.id}/advance", headers=_auth(steward),
            json={},
        )
        assert resp.status_code == 200, resp.text
        test_db.expire_all()
        row = test_db.get(models.Proposal, p.id)
        assert row.tie_resolution["method"] == "expand_winners"
        # Both tied options chosen → 3 total winners on a max=2 config.
        assert sorted(row.tie_resolution["chosen_winners"]) == sorted(
            [oids["B"], oids["C"]],
        )

    def test_org_scoped_advance_resolves_boundary_tie(
        self, client, test_db,
    ):
        """The advance_org_proposal duplicate (routes/organizations.py)
        also handles the multi-winner boundary-tie path."""
        org, steward = self._setup(
            test_db, "mw-org",
            settings={"tie_resolution": {"approval": "random_seed"}},
        )
        p = _make_approval_proposal(
            test_db, steward, org, option_labels=["A", "B", "C"],
            config={"min_winners": 2, "max_winners": 2,
                    "approval_threshold": None},
        )
        oids = _option_ids_by_label(test_db, p)
        _seed_votes_for_counts(
            test_db, org, p, {"A": 3, "B": 2, "C": 2}, prefix="mw-org",
        )
        p.quorum_threshold = 0.5
        test_db.commit()

        resp = client.post(
            f"/api/orgs/{org.slug}/proposals/{p.id}/advance",
            headers=_auth(steward), json={},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "passed"
        test_db.expire_all()
        row = test_db.get(models.Proposal, p.id)
        assert row.tie_resolution is not None
        assert row.tie_resolution["metadata"]["boundary_tie"] is True
        assert len(row.tie_resolution["chosen_winners"]) == 1
        assert row.tie_resolution["chosen_winners"][0] in (
            oids["B"], oids["C"],
        )

    def test_full_top_tie_single_seat_still_passes(self, client, test_db):
        """Top 1 with the whole top tied leaves the pure winner set
        empty — the close path must treat it as resolvable, not failed."""
        org, steward = self._setup(
            test_db, "mw-fulltie",
            settings={"tie_resolution": {"approval": "random_seed"}},
        )
        p = _make_approval_proposal(
            test_db, steward, org, option_labels=["A", "B"],
            config={"min_winners": 1, "max_winners": 1,
                    "approval_threshold": None},
        )
        oids = _option_ids_by_label(test_db, p)
        _seed_votes_for_counts(
            test_db, org, p, {"A": 2, "B": 2}, prefix="mw-ft",
        )
        p.quorum_threshold = 0.5
        test_db.commit()

        resp = client.post(
            f"/api/proposals/{p.id}/advance", headers=_auth(steward),
            json={},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "passed"
        test_db.expire_all()
        row = test_db.get(models.Proposal, p.id)
        assert len(row.tie_resolution["chosen_winners"]) == 1
        assert row.tie_resolution["chosen_winners"][0] in oids.values()


# ---------------------------------------------------------------------------
# 4. Config validation (schema 422s + route 400s)
# ---------------------------------------------------------------------------

class TestConfigValidation:

    def _global_create_body(self, method="approval", config=None):
        body = {
            "title": "T", "body": "", "voting_method": method,
            "options": (
                [{"label": "A"}, {"label": "B"}]
                if method in ("approval", "ranked_choice") else []
            ),
        }
        if config is not None:
            body["approval_winner_config"] = config
        return body

    def test_binary_with_config_400(self, client, test_db):
        u = _make_user(test_db, "val-bin")
        u.is_admin = True
        test_db.commit()
        resp = client.post(
            "/api/proposals", headers=_auth(u),
            json=self._global_create_body(
                "binary",
                {"min_winners": 2, "max_winners": 2,
                 "approval_threshold": None},
            ),
        )
        assert resp.status_code == 400, resp.text
        assert "approval" in resp.json()["detail"]

    def test_ranked_choice_with_config_400(self, client, test_db):
        u = _make_user(test_db, "val-rcv")
        u.is_admin = True
        test_db.commit()
        resp = client.post(
            "/api/proposals", headers=_auth(u),
            json=self._global_create_body(
                "ranked_choice",
                {"min_winners": 2, "max_winners": 2,
                 "approval_threshold": None},
            ),
        )
        assert resp.status_code == 400, resp.text

    def test_vacuous_config_422(self, client, test_db):
        u = _make_user(test_db, "val-vac")
        test_db.commit()
        resp = client.post(
            "/api/proposals", headers=_auth(u),
            json=self._global_create_body(
                "approval",
                {"min_winners": 0, "max_winners": 5,
                 "approval_threshold": None},
            ),
        )
        assert resp.status_code == 422, resp.text

    @pytest.mark.parametrize("bad_config", [
        {"min_winners": -1},
        {"min_winners": 1, "max_winners": 0},
        {"min_winners": 2, "max_winners": 1},          # max < min
        {"min_winners": 0, "approval_threshold": 0},   # not in (0,1]
        {"min_winners": 0, "approval_threshold": 1.5},
        {"min_winners": 0, "approval_threshold": "half"},
        {"min_winners": 1, "bogus_key": True},
        {"min_winners": "two"},
        "not-an-object",
    ])
    def test_invalid_shapes_422(self, client, test_db, bad_config):
        u = _make_user(test_db, "val-shape")
        test_db.commit()
        resp = client.post(
            "/api/proposals", headers=_auth(u),
            json=self._global_create_body("approval", bad_config),
        )
        assert resp.status_code == 422, resp.text

    def test_election_patch_with_config_non_approval_400(
        self, client, test_db,
    ):
        """Phase 66a lifted the blanket election block for APPROVAL
        elections; non-approval elections still reject the config
        (num_winners owns RCV/STV winner counts). Updated from the
        Phase 66 core version of this test, which asserted the
        pre-66a blanket 400."""
        org = _make_org(test_db, "val-elect")
        u = _make_user(test_db, "val-elect-author")
        make_org_membership(
            test_db, org_id=org.id, user_id=u.id, role="steward",
        )
        p = _make_approval_proposal(
            test_db, u, org, option_labels=["A", "B"],
            status="draft", is_election=True,
        )
        p.voting_method = "ranked_choice"
        test_db.commit()
        resp = client.patch(
            f"/api/proposals/{p.id}", headers=_auth(u),
            json={"approval_winner_config": {
                "min_winners": 2, "max_winners": 2,
                "approval_threshold": None,
            }},
        )
        assert resp.status_code == 400, resp.text
        assert "approval-method elections" in resp.json()["detail"]

    def test_election_patch_with_config_approval_draft_ok(
        self, client, test_db,
    ):
        """Phase 66a — a draft approval-method election accepts the
        config through the same draft-edit gate as ordinary approval
        proposals."""
        org = _make_org(test_db, "val-elect-ok")
        u = _make_user(test_db, "val-elect-ok-author")
        make_org_membership(
            test_db, org_id=org.id, user_id=u.id, role="steward",
        )
        p = _make_approval_proposal(
            test_db, u, org, option_labels=["A", "B"],
            status="draft", is_election=True,
        )
        test_db.commit()
        resp = client.patch(
            f"/api/proposals/{p.id}", headers=_auth(u),
            json={"approval_winner_config": {
                "min_winners": 2, "max_winners": 2,
                "approval_threshold": None,
            }},
        )
        assert resp.status_code == 200, resp.text
        test_db.expire_all()
        assert (
            test_db.get(models.Proposal, p.id)
            .approval_winner_config["min_winners"] == 2
        )

    def test_patch_non_draft_400(self, client, test_db):
        org = _make_org(test_db, "val-nondraft")
        u = _make_user(test_db, "val-nondraft-author")
        make_org_membership(
            test_db, org_id=org.id, user_id=u.id, role="steward",
        )
        p = _make_approval_proposal(
            test_db, u, org, option_labels=["A", "B"],
            status="deliberation",
        )
        p.deliberation_start = datetime.now(timezone.utc).replace(
            tzinfo=None,
        )
        test_db.commit()
        resp = client.patch(
            f"/api/proposals/{p.id}", headers=_auth(u),
            json={"approval_winner_config": {
                "min_winners": 2, "max_winners": 2,
                "approval_threshold": None,
            }},
        )
        assert resp.status_code == 400, resp.text
        assert "draft" in resp.json()["detail"]

    def test_patch_draft_sets_and_clears_config(self, client, test_db):
        org = _make_org(test_db, "val-setclear")
        u = _make_user(test_db, "val-setclear-author")
        make_org_membership(
            test_db, org_id=org.id, user_id=u.id, role="steward",
        )
        p = _make_approval_proposal(
            test_db, u, org, option_labels=["A", "B"], status="draft",
        )
        test_db.commit()
        cfg = {"min_winners": 2, "max_winners": 2,
               "approval_threshold": None}
        resp = client.patch(
            f"/api/proposals/{p.id}", headers=_auth(u),
            json={"approval_winner_config": cfg},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["approval_winner_config"]["min_winners"] == 2
        test_db.expire_all()
        assert (
            test_db.get(models.Proposal, p.id)
            .approval_winner_config["min_winners"] == 2
        )
        # Explicit null clears.
        resp = client.patch(
            f"/api/proposals/{p.id}", headers=_auth(u),
            json={"approval_winner_config": None},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["approval_winner_config"] is None
        test_db.expire_all()
        assert (
            test_db.get(models.Proposal, p.id).approval_winner_config
            is None
        )

    def test_method_change_away_from_approval_clears_config(
        self, client, test_db,
    ):
        org = _make_org(test_db, "val-methodswap")
        u = _make_user(test_db, "val-methodswap-author")
        make_org_membership(
            test_db, org_id=org.id, user_id=u.id, role="steward",
        )
        p = _make_approval_proposal(
            test_db, u, org, option_labels=["A", "B"], status="draft",
            config={"min_winners": 2, "max_winners": 2,
                    "approval_threshold": None},
        )
        test_db.commit()
        resp = client.patch(
            f"/api/proposals/{p.id}", headers=_auth(u),
            json={"voting_method": "binary"},
        )
        assert resp.status_code == 200, resp.text
        test_db.expire_all()
        row = test_db.get(models.Proposal, p.id)
        assert row.voting_method == "binary"
        assert row.approval_winner_config is None


# ---------------------------------------------------------------------------
# 5. D5 — Stable Result winner-SET comparison + worker snapshot round-trip
# ---------------------------------------------------------------------------

def _mo_point(winners) -> MultiOptionSnapshotPoint:
    return MultiOptionSnapshotPoint(
        simulated_time=datetime(2026, 6, 1),
        winners=tuple(winners),
        total_ballots_cast=10,
        total_eligible=20,
    )


class TestD5WinnerSets:

    def test_winner_set_overlaps_is_order_insensitive(self):
        """Multi-winner sets compare as SETS — element order in the
        snapshot list must not matter."""
        assert winner_set_overlaps(
            _mo_point(["A", "B"]), _mo_point(["B", "A"]),
        ) is True
        assert winner_set_overlaps(
            _mo_point(["C", "A", "B"]), _mo_point(["B", "A"]),
        ) is True   # superset — ambiguity emerged
        assert winner_set_overlaps(
            _mo_point(["A"]), _mo_point(["B", "A"]),
        ) is True   # subset — resolution
        assert winner_set_overlaps(
            _mo_point(["B", "C"]), _mo_point(["A", "B"]),
        ) is False  # displacement — unstable

    def test_worker_snapshot_roundtrips_multiwinner_list(self, test_db):
        """capture_snapshot writes the multi-winner list into
        VoteSnapshot.multi_option_winners; the worker's
        _snapshot_points_for lifts it back unchanged (sorted)."""
        from sustained_majority_service import capture_snapshot
        from sustained_majority_worker import _snapshot_points_for

        org = _make_org(test_db, "d5-org")
        author = _make_user(test_db, "d5-author")
        make_org_membership(
            test_db, org_id=org.id, user_id=author.id, role="steward",
        )
        p = _make_approval_proposal(
            test_db, author, org, option_labels=["A", "B", "C"],
            config={"min_winners": 2, "max_winners": 2,
                    "approval_threshold": None},
        )
        oids = _option_ids_by_label(test_db, p)
        _seed_votes_for_counts(
            test_db, org, p, {"A": 3, "B": 2, "C": 1}, prefix="d5",
        )
        test_db.commit()

        snap = capture_snapshot(test_db, p)
        test_db.commit()
        payload = snap.multi_option_winners
        assert sorted(payload["winners"]) == sorted(
            [oids["A"], oids["B"]],
        )
        assert payload["total_ballots_cast"] == 6

        points = _snapshot_points_for(test_db, p)
        assert len(points) == 1
        assert frozenset(points[0].winners) == frozenset(
            [oids["A"], oids["B"]],
        )
        assert points[0].total_ballots_cast == 6


# ---------------------------------------------------------------------------
# 6. Round-trip through BOTH create endpoints + _build_proposal_out
# ---------------------------------------------------------------------------

class TestRoundTrip:

    CONFIG = {"min_winners": 1, "max_winners": 3,
              "approval_threshold": 0.6}

    def test_global_create_roundtrip(self, client, test_db):
        u = _make_user(test_db, "rt-global")
        u.is_admin = True
        test_db.commit()
        resp = client.post(
            "/api/proposals", headers=_auth(u),
            json={
                "title": "RT", "body": "", "voting_method": "approval",
                "options": [{"label": "A"}, {"label": "B"}],
                "approval_winner_config": self.CONFIG,
            },
        )
        assert resp.status_code in (200, 201), resp.text
        body = resp.json()
        assert body["approval_winner_config"] == self.CONFIG
        # Column actually persisted (not just echoed).
        test_db.expire_all()
        row = test_db.get(models.Proposal, body["id"])
        assert row.approval_winner_config == self.CONFIG
        # And back out through the detail GET (_build_proposal_out).
        detail = client.get(
            f"/api/proposals/{body['id']}", headers=_auth(u),
        )
        assert detail.status_code == 200
        assert detail.json()["approval_winner_config"] == self.CONFIG

    def test_org_create_roundtrip(self, client, test_db):
        org = _make_org(test_db, "rt-org")
        u = _make_user(test_db, "rt-org-steward")
        make_org_membership(
            test_db, org_id=org.id, user_id=u.id, role="steward",
        )
        test_db.commit()
        resp = client.post(
            f"/api/orgs/{org.slug}/proposals", headers=_auth(u),
            json={
                "title": "RT Org", "body": "",
                "voting_method": "approval",
                "options": [{"label": "A"}, {"label": "B"}],
                "approval_winner_config": self.CONFIG,
            },
        )
        assert resp.status_code in (200, 201), resp.text
        body = resp.json()
        assert body["approval_winner_config"] == self.CONFIG
        test_db.expire_all()
        row = test_db.get(models.Proposal, body["id"])
        assert row.approval_winner_config == self.CONFIG

    def test_results_surface_winner_seats_without_tie(
        self, client, test_db,
    ):
        """Results endpoint exposes per-winner floor/threshold
        attribution for a cleanly-decided multi-winner proposal."""
        org = _make_org(test_db, "rt-results")
        u = _make_user(test_db, "rt-results-steward")
        make_org_membership(
            test_db, org_id=org.id, user_id=u.id, role="steward",
        )
        p = _make_approval_proposal(
            test_db, u, org, option_labels=["A", "B", "C"],
            config={"min_winners": 1, "max_winners": 3,
                    "approval_threshold": 0.6},
        )
        oids = _option_ids_by_label(test_db, p)
        # 10 ballots: A=8 (0.8 → threshold), B=7 (0.7 → threshold),
        # C=2 (0.2 → no seat). A takes the floor seat.
        voters = []
        for i in range(10):
            v = _make_user(test_db, f"rt-res-v{i}")
            make_org_membership(
                test_db, org_id=org.id, user_id=v.id, role="member",
            )
            voters.append(v)
        for i, v in enumerate(voters):
            approvals = []
            if i < 8:
                approvals.append(oids["A"])
            if i < 7:
                approvals.append(oids["B"])
            if i < 2:
                approvals.append(oids["C"])
            _cast_approval_vote(test_db, v, p, approvals)
        test_db.commit()

        resp = client.get(
            f"/api/proposals/{p.id}/results", headers=_auth(u),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert sorted(body["winners"]) == sorted([oids["A"], oids["B"]])
        assert body["winner_seats"] == {
            oids["A"]: "floor", oids["B"]: "threshold",
        }
        assert body["tied"] is False
        assert body["boundary_tied"] == []
        assert body["seats_remaining"] == 0
        assert body["approval_winner_config"]["approval_threshold"] == 0.6
