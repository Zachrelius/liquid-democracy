"""
Phase 22 — Support Trajectory Chart tests.

Coverage split:

  - **Phase 22 core (16 tests)** — universal snapshot capture, option_totals
    in multi_option_winners payload, trajectory API endpoint shape, org
    scoping, downsampling, SRR annotation overlay.
  - **Phase 20 preservation (7 tests)** — re-exercises the Phase 20 lifecycle
    paths against the Phase-22-modified worker (snapshot capture now
    universal). All scenarios must produce identical outcomes to pre-Phase-22
    behavior. Catches the worst-case regression: Phase 22's worker change
    accidentally breaks stability evaluation.

Phase 17 lesson observed: tests use real ``models.Proposal`` +
``models.VoteSnapshot`` rows rather than SimpleNamespace shims — the ballot-
shape bug in Phase 17's resolver wouldn't surface against shim'd Vote rows.
"""

from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
import sustained_majority_worker as worker
from audit_utils import log_audit_event
from database import Base, get_db
from main import app
from sustained_majority_service import (
    capture_snapshot,
    count_extensions,
    _sum_extension_seconds,
)
from tests.conftest import make_org_membership


_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def db():
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


@pytest.fixture(scope="function")
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _user(db: Session, username: str) -> models.User:
    u = models.User(
        username=username,
        display_name=username.title(),
        password_hash=_DUMMY_HASH,
        email=f"{username}@test.example",
        email_verified=True,
    )
    db.add(u)
    db.flush()
    return u


def _auth(user: models.User) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _org(
    db: Session,
    *,
    slug: str = "trajectory-org",
    srr_enabled: bool = False,
    stable_window_fraction: float = 0.25,
    max_extension_fraction: float = 0.25,
) -> models.Organization:
    org = models.Organization(
        name="Trajectory Org",
        slug=slug,
        description="",
        join_policy="open",
        settings={
            "stable_result_enabled_default": srr_enabled,
            "stable_window_fraction": stable_window_fraction,
            "max_extension_fraction": max_extension_fraction,
        },
    )
    db.add(org)
    db.flush()
    return org


def _member(db: Session, org: models.Organization, user: models.User, role: str = "member"):
    make_org_membership(
        db,
        user_id=user.id, org_id=org.id, role=role, status="active",
    )
    db.flush()


def _binary_proposal(
    db: Session,
    *,
    org: models.Organization,
    author: models.User,
    voting_start: datetime | None = None,
    voting_end: datetime | None = None,
    pass_threshold: float = 0.5,
    stable_result_required: bool | None = None,
    status: str = "voting",
) -> models.Proposal:
    now = _now()
    p = models.Proposal(
        title="P",
        body="",
        author_id=author.id,
        org_id=org.id,
        voting_method="binary",
        status=status,
        stable_result_required=stable_result_required,
        voting_start=voting_start or (now - timedelta(hours=2)),
        voting_end=voting_end or (now + timedelta(hours=4)),
        pass_threshold=pass_threshold,
        quorum_threshold=0.0,
    )
    db.add(p)
    db.flush()
    return p


def _approval_proposal(
    db: Session,
    *,
    org: models.Organization,
    author: models.User,
    option_labels: list[str] | None = None,
    voting_start: datetime | None = None,
    voting_end: datetime | None = None,
    stable_result_required: bool | None = None,
) -> models.Proposal:
    now = _now()
    p = models.Proposal(
        title="A",
        body="",
        author_id=author.id,
        org_id=org.id,
        voting_method="approval",
        status="voting",
        stable_result_required=stable_result_required,
        voting_start=voting_start or (now - timedelta(hours=2)),
        voting_end=voting_end or (now + timedelta(hours=4)),
        pass_threshold=0.5,
        quorum_threshold=0.0,
    )
    db.add(p)
    db.flush()
    labels = option_labels or ["Option A", "Option B", "Option C"]
    for i, label in enumerate(labels):
        db.add(models.ProposalOption(
            proposal_id=p.id,
            label=label,
            description="",
            display_order=i,
        ))
    db.flush()
    return p


def _rcv_proposal(
    db: Session,
    *,
    org: models.Organization,
    author: models.User,
    option_labels: list[str] | None = None,
    num_winners: int = 1,
    voting_start: datetime | None = None,
    voting_end: datetime | None = None,
    stable_result_required: bool | None = None,
) -> models.Proposal:
    now = _now()
    p = models.Proposal(
        title="R",
        body="",
        author_id=author.id,
        org_id=org.id,
        voting_method="ranked_choice",
        status="voting",
        stable_result_required=stable_result_required,
        num_winners=num_winners,
        voting_start=voting_start or (now - timedelta(hours=2)),
        voting_end=voting_end or (now + timedelta(hours=4)),
        pass_threshold=0.5,
        quorum_threshold=0.0,
    )
    db.add(p)
    db.flush()
    labels = option_labels or ["Option A", "Option B", "Option C"]
    for i, label in enumerate(labels):
        db.add(models.ProposalOption(
            proposal_id=p.id,
            label=label,
            description="",
            display_order=i,
        ))
    db.flush()
    return p


def _cast_binary(db, user, proposal, value):
    db.add(models.Vote(
        proposal_id=proposal.id,
        user_id=user.id,
        vote_value=value,
        is_direct=True,
        cast_by_id=user.id,
    ))
    db.flush()


def _cast_approval(db, user, proposal, option_ids):
    db.add(models.Vote(
        proposal_id=proposal.id,
        user_id=user.id,
        vote_value=None,
        ballot={"approvals": option_ids},
        is_direct=True,
        cast_by_id=user.id,
    ))
    db.flush()


def _cast_ranking(db, user, proposal, ranking):
    db.add(models.Vote(
        proposal_id=proposal.id,
        user_id=user.id,
        vote_value=None,
        ballot={"ranking": ranking},
        is_direct=True,
        cast_by_id=user.id,
    ))
    db.flush()


def _option_ids(db, proposal) -> list[str]:
    opts = db.query(models.ProposalOption).filter(
        models.ProposalOption.proposal_id == proposal.id,
    ).order_by(models.ProposalOption.display_order).all()
    return [o.id for o in opts]


def _seed_extension_audit(db, proposal, *, extension_seconds, new_voting_end=None, when=None):
    log_audit_event(
        db,
        action="proposal.window_extended",
        target_type="proposal",
        target_id=proposal.id,
        actor_id=None,
        details={
            "proposal_id": proposal.id,
            "extension_seconds": extension_seconds,
            "new_voting_end": (
                new_voting_end.isoformat() if new_voting_end else None
            ),
            "trigger": "stable_result_required",
        },
    )
    if when is not None:
        row = (
            db.query(models.AuditLog)
            .filter(models.AuditLog.target_id == proposal.id)
            .order_by(models.AuditLog.timestamp.desc())
            .first()
        )
        if row is not None:
            row.timestamp = when
    db.flush()


# ===========================================================================
# Phase 22 core tests
# ===========================================================================

class TestUniversalSnapshotCapture:
    """Phase 22 D1: snapshot capture runs for every voting proposal, not
    just SRR-active ones."""

    def test_non_srr_proposal_gets_snapshot(self, db):
        author = _user(db, "alice")
        org = _org(db, srr_enabled=False)  # SRR off at org default
        _member(db, org, author)
        proposal = _binary_proposal(
            db, org=org, author=author, stable_result_required=None,
        )
        _cast_binary(db, author, proposal, "yes")
        db.commit()

        # SRR is NOT active for this proposal (org default off, no override).
        result = worker.evaluate_proposal(db, proposal)
        db.commit()

        # Stability evaluation short-circuited (result is None because not
        # SRR-active), but a snapshot WAS written.
        assert result is None
        snap_count = db.query(models.VoteSnapshot).filter(
            models.VoteSnapshot.proposal_id == proposal.id,
        ).count()
        assert snap_count == 1, (
            "Non-SRR voting proposal must get snapshot capture per Phase 22 D1"
        )


class TestSRRProposalSnapshotsUnchanged:
    """Phase 22 doesn't break Phase 20: SRR proposals still get snapshots
    AND stability evaluation runs."""

    def test_srr_proposal_snapshot_and_stability_path(self, db):
        author = _user(db, "alice")
        bob = _user(db, "bob")
        org = _org(db, srr_enabled=True)
        _member(db, org, author)
        _member(db, org, bob)
        # Stable proposal in stable window — should snapshot + no extension.
        start = _now() - timedelta(seconds=80)
        end = _now() + timedelta(seconds=20)
        proposal = _binary_proposal(
            db, org=org, author=author,
            voting_start=start, voting_end=end,
        )
        _cast_binary(db, author, proposal, "yes")
        _cast_binary(db, bob, proposal, "yes")
        db.commit()

        result = worker.evaluate_proposal(db, proposal)
        db.commit()
        # Stable → no destabilization → result None.
        assert result is None
        # Snapshot was written.
        assert db.query(models.VoteSnapshot).filter(
            models.VoteSnapshot.proposal_id == proposal.id,
        ).count() == 1


class TestApprovalSnapshotOptionTotals:
    """Phase 22 D2: approval snapshots carry option_totals = per-option
    approval count."""

    def test_approval_option_totals_match_manual_tally(self, db):
        author = _user(db, "alice")
        bob = _user(db, "bob")
        carol = _user(db, "carol")
        org = _org(db)
        _member(db, org, author)
        _member(db, org, bob)
        _member(db, org, carol)
        proposal = _approval_proposal(
            db, org=org, author=author,
            option_labels=["Apples", "Bananas", "Cherries"],
        )
        opt_ids = _option_ids(db, proposal)
        # Alice approves A + B; Bob approves A + C; Carol approves A only.
        # Expected: A=3, B=1, C=1; winners=[A].
        _cast_approval(db, author, proposal, [opt_ids[0], opt_ids[1]])
        _cast_approval(db, bob, proposal, [opt_ids[0], opt_ids[2]])
        _cast_approval(db, carol, proposal, [opt_ids[0]])
        db.commit()

        capture_snapshot(db, proposal)
        db.commit()

        snap = db.query(models.VoteSnapshot).filter(
            models.VoteSnapshot.proposal_id == proposal.id,
        ).order_by(models.VoteSnapshot.simulated_time.desc()).first()
        assert snap is not None
        payload = snap.multi_option_winners
        assert payload is not None
        assert "option_totals" in payload
        totals = payload["option_totals"]
        assert int(totals[opt_ids[0]]) == 3
        assert int(totals[opt_ids[1]]) == 1
        assert int(totals[opt_ids[2]]) == 1
        # Winners derive from option_totals: A is sole winner.
        assert payload["winners"] == [opt_ids[0]]


class TestRCVSnapshotOptionTotals:
    """Phase 22 D2: RCV snapshots carry option_totals = first-choice counts
    from rounds[0], NOT the full elimination cascade winners."""

    def test_rcv_option_totals_are_first_choice_only(self, db):
        author = _user(db, "alice")
        bob = _user(db, "bob")
        carol = _user(db, "carol")
        dave = _user(db, "dave")
        org = _org(db)
        for u in (author, bob, carol, dave):
            _member(db, org, u)
        proposal = _rcv_proposal(
            db, org=org, author=author,
            option_labels=["Red", "Green", "Blue"],
            num_winners=1,
        )
        opt_ids = _option_ids(db, proposal)
        # First-choice counts: Red=2, Green=1, Blue=1.
        # After IRV elimination Green/Blue (whichever gets eliminated last
        # transfers to Red or its later preference), Red wins.
        _cast_ranking(db, author, proposal, [opt_ids[0], opt_ids[1]])  # Red>Green
        _cast_ranking(db, bob, proposal, [opt_ids[0], opt_ids[2]])      # Red>Blue
        _cast_ranking(db, carol, proposal, [opt_ids[1], opt_ids[0]])    # Green>Red
        _cast_ranking(db, dave, proposal, [opt_ids[2], opt_ids[0]])     # Blue>Red
        db.commit()

        capture_snapshot(db, proposal)
        db.commit()

        snap = db.query(models.VoteSnapshot).filter(
            models.VoteSnapshot.proposal_id == proposal.id,
        ).order_by(models.VoteSnapshot.simulated_time.desc()).first()
        payload = snap.multi_option_winners
        totals = payload["option_totals"]
        # First-choice counts (round 0): Red=2, Green=1, Blue=1.
        assert int(totals[opt_ids[0]]) == 2
        assert int(totals[opt_ids[1]]) == 1
        assert int(totals[opt_ids[2]]) == 1


class TestSTVSnapshotOptionTotals:
    """STV (multi-winner RCV) — same first-choice-counts contract as IRV."""

    def test_stv_option_totals_are_first_choice_only(self, db):
        author = _user(db, "alice")
        bob = _user(db, "bob")
        carol = _user(db, "carol")
        dave = _user(db, "dave")
        eve = _user(db, "eve")
        org = _org(db)
        for u in (author, bob, carol, dave, eve):
            _member(db, org, u)
        proposal = _rcv_proposal(
            db, org=org, author=author,
            option_labels=["X", "Y", "Z"],
            num_winners=2,
        )
        opt_ids = _option_ids(db, proposal)
        # First-choice: X=2, Y=2, Z=1.
        _cast_ranking(db, author, proposal, [opt_ids[0], opt_ids[1]])
        _cast_ranking(db, bob, proposal, [opt_ids[0], opt_ids[2]])
        _cast_ranking(db, carol, proposal, [opt_ids[1], opt_ids[2]])
        _cast_ranking(db, dave, proposal, [opt_ids[1], opt_ids[0]])
        _cast_ranking(db, eve, proposal, [opt_ids[2], opt_ids[0]])
        db.commit()

        capture_snapshot(db, proposal)
        db.commit()

        snap = db.query(models.VoteSnapshot).filter(
            models.VoteSnapshot.proposal_id == proposal.id,
        ).order_by(models.VoteSnapshot.simulated_time.desc()).first()
        payload = snap.multi_option_winners
        totals = payload["option_totals"]
        assert int(totals[opt_ids[0]]) == 2
        assert int(totals[opt_ids[1]]) == 2
        assert int(totals[opt_ids[2]]) == 1


class TestBinarySnapshotUnchanged:
    """Binary snapshots remain unchanged: yes/no/abstain counts;
    multi_option_winners is null."""

    def test_binary_snapshot_has_no_multi_option_winners(self, db):
        author = _user(db, "alice")
        org = _org(db)
        _member(db, org, author)
        proposal = _binary_proposal(db, org=org, author=author)
        _cast_binary(db, author, proposal, "yes")
        db.commit()

        capture_snapshot(db, proposal)
        db.commit()

        snap = db.query(models.VoteSnapshot).filter(
            models.VoteSnapshot.proposal_id == proposal.id,
        ).first()
        assert snap.yes_count == 1
        assert snap.no_count == 0
        assert snap.multi_option_winners is None


class TestWinnersOptionTotalsConsistency:
    """For approval: option(s) with max option_totals MUST equal winners.
    For RCV: winners (full cascade) may differ from option_totals (first
    choice only) — both come from the same tally pass."""

    def test_approval_winners_match_option_totals_max(self, db):
        author = _user(db, "alice")
        bob = _user(db, "bob")
        org = _org(db)
        _member(db, org, author)
        _member(db, org, bob)
        proposal = _approval_proposal(
            db, org=org, author=author,
            option_labels=["A", "B"],
        )
        opt_ids = _option_ids(db, proposal)
        # Both approve A; nobody approves B. Winners = [A].
        _cast_approval(db, author, proposal, [opt_ids[0]])
        _cast_approval(db, bob, proposal, [opt_ids[0]])
        db.commit()

        capture_snapshot(db, proposal)
        db.commit()

        snap = db.query(models.VoteSnapshot).filter(
            models.VoteSnapshot.proposal_id == proposal.id,
        ).first()
        payload = snap.multi_option_winners
        totals = payload["option_totals"]
        max_count = max(totals.values())
        max_options = sorted(
            [oid for oid, c in totals.items() if c == max_count]
        )
        assert sorted(payload["winners"]) == max_options

    def test_rcv_winners_and_option_totals_both_present_same_pass(self, db):
        """RCV winners may legitimately differ from option_totals (winners
        = elimination cascade output, option_totals = first-choice). Verify
        both are present and from the same tally call."""
        author = _user(db, "alice")
        bob = _user(db, "bob")
        carol = _user(db, "carol")
        org = _org(db)
        for u in (author, bob, carol):
            _member(db, org, u)
        proposal = _rcv_proposal(
            db, org=org, author=author,
            option_labels=["A", "B", "C"],
        )
        opt_ids = _option_ids(db, proposal)
        _cast_ranking(db, author, proposal, [opt_ids[0], opt_ids[1]])
        _cast_ranking(db, bob, proposal, [opt_ids[1], opt_ids[0]])
        _cast_ranking(db, carol, proposal, [opt_ids[2], opt_ids[0]])
        db.commit()

        capture_snapshot(db, proposal)
        db.commit()

        snap = db.query(models.VoteSnapshot).filter(
            models.VoteSnapshot.proposal_id == proposal.id,
        ).first()
        payload = snap.multi_option_winners
        assert "winners" in payload
        assert "option_totals" in payload
        assert isinstance(payload["winners"], list)
        assert isinstance(payload["option_totals"], dict)


class TestTrajectoryAPIBasic:
    """GET /api/proposals/{id}/trajectory — happy path."""

    def test_basic_response_shape(self, db, client):
        author = _user(db, "alice")
        org = _org(db)
        _member(db, org, author)
        proposal = _binary_proposal(db, org=org, author=author)
        _cast_binary(db, author, proposal, "yes")
        db.commit()
        capture_snapshot(db, proposal)
        db.commit()

        resp = client.get(
            f"/api/proposals/{proposal.id}/trajectory",
            headers=_auth(author),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["proposal_id"] == proposal.id
        assert body["voting_method"] == "binary"
        assert body["voting_start"] is not None
        assert body["voting_end"] is not None
        assert isinstance(body["snapshots"], list)
        assert len(body["snapshots"]) == 1
        # Non-SRR proposal → srr_annotations omitted entirely.
        assert body.get("srr_annotations") is None


class TestTrajectoryAPIDownsampling:
    """D7: > 500 snapshots are downsampled to ≤ 500 points."""

    def test_downsample_to_500_points(self, db, client):
        author = _user(db, "alice")
        org = _org(db)
        _member(db, org, author)
        # Make voting window span 10 hours so 600 buckets land cleanly.
        start = _now() - timedelta(hours=5)
        end = _now() + timedelta(hours=5)
        proposal = _binary_proposal(
            db, org=org, author=author,
            voting_start=start, voting_end=end,
        )
        # Synthesize 600 snapshots evenly spread across the window.
        total_seconds = (end - start).total_seconds()
        n = 600
        for i in range(n):
            t = start + timedelta(seconds=total_seconds * i / n)
            db.add(models.VoteSnapshot(
                proposal_id=proposal.id,
                simulated_time=t,
                yes_count=i,
                no_count=0,
                abstain_count=0,
                not_cast_count=0,
                total_eligible=600,
                multi_option_winners=None,
            ))
        db.commit()

        resp = client.get(
            f"/api/proposals/{proposal.id}/trajectory",
            headers=_auth(author),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        snaps = body["snapshots"]
        assert len(snaps) <= 500
        # Chronological order preserved.
        times = [s["captured_at"] for s in snaps]
        assert times == sorted(times)


class TestTrajectoryAPIBinaryFields:
    """Binary trajectory carries support_fraction + votes_cast per snapshot;
    no winners/option_totals."""

    def test_binary_fields_present(self, db, client):
        author = _user(db, "alice")
        bob = _user(db, "bob")
        org = _org(db)
        _member(db, org, author)
        _member(db, org, bob)
        proposal = _binary_proposal(db, org=org, author=author)
        _cast_binary(db, author, proposal, "yes")
        _cast_binary(db, bob, proposal, "no")
        db.commit()
        capture_snapshot(db, proposal)
        db.commit()

        resp = client.get(
            f"/api/proposals/{proposal.id}/trajectory",
            headers=_auth(author),
        )
        body = resp.json()
        snap = body["snapshots"][0]
        # 1 yes / 1 no / 0 abstain → support = 0.5.
        assert snap["support_fraction"] == pytest.approx(0.5)
        assert snap["votes_cast"] == 2
        # No multi-option fields.
        assert snap.get("winners") is None
        assert snap.get("option_totals") is None


class TestTrajectoryAPIMultiOptionFields:
    """Multi-option trajectory carries winners + option_totals per snapshot."""

    def test_approval_fields_present(self, db, client):
        author = _user(db, "alice")
        bob = _user(db, "bob")
        org = _org(db)
        _member(db, org, author)
        _member(db, org, bob)
        proposal = _approval_proposal(
            db, org=org, author=author,
            option_labels=["A", "B"],
        )
        opt_ids = _option_ids(db, proposal)
        _cast_approval(db, author, proposal, [opt_ids[0]])
        _cast_approval(db, bob, proposal, [opt_ids[0], opt_ids[1]])
        db.commit()
        capture_snapshot(db, proposal)
        db.commit()

        resp = client.get(
            f"/api/proposals/{proposal.id}/trajectory",
            headers=_auth(author),
        )
        body = resp.json()
        assert body["voting_method"] == "approval"
        snap = body["snapshots"][0]
        assert snap["winners"] == [opt_ids[0]]
        assert snap["option_totals"][opt_ids[0]] == 2
        assert snap["option_totals"][opt_ids[1]] == 1
        # No binary field.
        assert snap.get("support_fraction") is None


class TestTrajectoryAPIOldShapeFallback:
    """D12: a VoteSnapshot row with multi_option_winners missing
    ``option_totals`` (pre-Phase-22 shape) is returned with
    ``option_totals=None``; the API doesn't crash."""

    def test_old_shape_yields_null_option_totals(self, db, client):
        author = _user(db, "alice")
        org = _org(db)
        _member(db, org, author)
        proposal = _approval_proposal(
            db, org=org, author=author,
            option_labels=["A", "B"],
        )
        # Hand-craft an old-shape snapshot (no option_totals key).
        db.add(models.VoteSnapshot(
            proposal_id=proposal.id,
            simulated_time=_now(),
            yes_count=0,
            no_count=0,
            abstain_count=0,
            not_cast_count=0,
            total_eligible=2,
            multi_option_winners={
                "winners": ["opt-1"],
                "total_ballots_cast": 2,
                # option_totals deliberately omitted.
            },
        ))
        db.commit()

        resp = client.get(
            f"/api/proposals/{proposal.id}/trajectory",
            headers=_auth(author),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        snap = body["snapshots"][0]
        assert snap["winners"] == ["opt-1"]
        assert snap["option_totals"] is None
        assert snap["votes_cast"] == 2


class TestTrajectoryAPISRRAnnotations:
    """D3: srr_annotations present when stable_result_required active for
    proposal; omitted entirely otherwise."""

    def test_srr_annotations_populated(self, db, client):
        author = _user(db, "alice")
        org = _org(db, srr_enabled=True)  # active at org default
        _member(db, org, author)
        proposal = _binary_proposal(
            db, org=org, author=author,
            stable_result_required=None,  # inherit org default = on
        )
        # Seed one extension audit.
        new_end = proposal.voting_end + timedelta(seconds=25)
        _seed_extension_audit(
            db, proposal,
            extension_seconds=25,
            new_voting_end=new_end,
        )
        db.commit()

        resp = client.get(
            f"/api/proposals/{proposal.id}/trajectory",
            headers=_auth(author),
        )
        body = resp.json()
        ann = body["srr_annotations"]
        assert ann is not None
        assert ann["stable_window_fraction"] == pytest.approx(0.25)
        assert ann["stable_window_starts_at"] is not None
        assert len(ann["extensions"]) == 1
        assert ann["extensions"][0]["new_voting_end"] is not None
        assert ann["destabilization_events"] == []
        assert ann["close_trigger"] is None

    def test_non_srr_omits_annotations(self, db, client):
        author = _user(db, "alice")
        org = _org(db, srr_enabled=False)
        _member(db, org, author)
        proposal = _binary_proposal(
            db, org=org, author=author, stable_result_required=None,
        )
        db.commit()

        resp = client.get(
            f"/api/proposals/{proposal.id}/trajectory",
            headers=_auth(author),
        )
        body = resp.json()
        assert body.get("srr_annotations") is None


class TestTrajectoryAPIOrgScoping:
    """D4: non-members get 403; members get 200."""

    def test_non_member_gets_403(self, db, client):
        author = _user(db, "alice")
        outsider = _user(db, "outsider")
        org = _org(db)
        _member(db, org, author)
        # outsider is NOT a member.
        proposal = _binary_proposal(db, org=org, author=author)
        db.commit()

        resp = client.get(
            f"/api/proposals/{proposal.id}/trajectory",
            headers=_auth(outsider),
        )
        assert resp.status_code == 403

    def test_member_gets_200(self, db, client):
        author = _user(db, "alice")
        member = _user(db, "member")
        org = _org(db)
        _member(db, org, author)
        _member(db, org, member)
        proposal = _binary_proposal(db, org=org, author=author)
        db.commit()

        resp = client.get(
            f"/api/proposals/{proposal.id}/trajectory",
            headers=_auth(member),
        )
        assert resp.status_code == 200


class TestTrajectoryAPIClosedProposal:
    """Closed proposal trajectory remains fetchable; close_trigger populates
    from the proposal.status_changed audit row."""

    def test_closed_proposal_trajectory_with_close_trigger(self, db, client):
        author = _user(db, "alice")
        org = _org(db, srr_enabled=True)
        _member(db, org, author)
        proposal = _binary_proposal(
            db, org=org, author=author,
            stable_result_required=None,
            status="passed",  # closed
        )
        capture_snapshot(db, proposal)
        # Seed a close audit row with trigger.
        log_audit_event(
            db,
            action="proposal.status_changed",
            target_type="proposal",
            target_id=proposal.id,
            actor_id=None,
            details={
                "proposal_id": proposal.id,
                "old_status": "voting",
                "new_status": "passed",
                "trigger": "stable_result_achieved",
            },
        )
        db.commit()

        resp = client.get(
            f"/api/proposals/{proposal.id}/trajectory",
            headers=_auth(author),
        )
        assert resp.status_code == 200
        body = resp.json()
        ann = body["srr_annotations"]
        assert ann["close_trigger"] == "stable_result_achieved"
        assert len(body["snapshots"]) == 1


class TestSnapshotWorkerIdempotency:
    """Worker running twice in succession produces 2 distinct snapshot rows
    (the worker is designed to write one per tick; idempotency here means
    'no crash / no duplicate-bug')."""

    def test_two_evaluations_produce_two_snapshots(self, db):
        author = _user(db, "alice")
        org = _org(db, srr_enabled=True)
        _member(db, org, author)
        # Stable proposal — no extension fires, just snapshots accumulate.
        start = _now() - timedelta(seconds=80)
        end = _now() + timedelta(seconds=20)
        proposal = _binary_proposal(
            db, org=org, author=author,
            voting_start=start, voting_end=end,
        )
        _cast_binary(db, author, proposal, "yes")
        db.commit()

        worker.evaluate_proposal(db, proposal)
        db.commit()
        worker.evaluate_proposal(db, proposal)
        db.commit()

        snap_count = db.query(models.VoteSnapshot).filter(
            models.VoteSnapshot.proposal_id == proposal.id,
        ).count()
        assert snap_count == 2


# ===========================================================================
# Cluster B3a — Phase 20 behavior preservation tests
# ===========================================================================
#
# These re-exercise the load-bearing Phase 20 lifecycle paths against the
# Phase-22-modified worker. Phase 22's universal-capture change must not
# alter how evaluate_stability is invoked or what it produces for SRR
# proposals.

class TestPhase20BinaryStableWindowPreserved:
    """Binary SRR proposal in stable window with all snapshots stable: no
    extension fires."""

    def test_stable_window_no_extension(self, db):
        author = _user(db, "alice")
        bob = _user(db, "bob")
        org = _org(db, srr_enabled=True)
        _member(db, org, author)
        _member(db, org, bob)
        start = _now() - timedelta(seconds=80)
        end = _now() + timedelta(seconds=20)
        proposal = _binary_proposal(
            db, org=org, author=author,
            voting_start=start, voting_end=end,
        )
        _cast_binary(db, author, proposal, "yes")
        _cast_binary(db, bob, proposal, "yes")
        db.commit()

        result = worker.evaluate_proposal(db, proposal)
        db.commit()
        assert result is None
        assert count_extensions(db, proposal.id) == 0
        assert proposal.status == "voting"


class TestPhase20BinaryDestabilizationPreserved:
    """Binary SRR proposal drops below threshold in stable window: extension
    fires with same semantics as pre-Phase-22."""

    def test_destabilization_in_window_extends(self, db):
        author = _user(db, "alice")
        bob = _user(db, "bob")
        org = _org(
            db, srr_enabled=True, max_extension_fraction=0.50,
        )
        _member(db, org, author)
        _member(db, org, bob)
        start = _now() - timedelta(seconds=80)
        end = _now() + timedelta(seconds=20)
        proposal = _binary_proposal(
            db, org=org, author=author,
            voting_start=start, voting_end=end,
        )
        # Pre-seed a destabilizing snapshot inside the stable window.
        db.add(models.VoteSnapshot(
            proposal_id=proposal.id,
            simulated_time=_now() - timedelta(seconds=10),
            yes_count=2, no_count=8, abstain_count=0,
            not_cast_count=0, total_eligible=10,
            multi_option_winners=None,
        ))
        _cast_binary(db, author, proposal, "no")
        _cast_binary(db, bob, proposal, "no")
        db.commit()

        old_end = proposal.voting_end
        result = worker.evaluate_proposal(db, proposal)
        db.commit()
        assert result == "extended"
        assert proposal.voting_end > old_end
        assert count_extensions(db, proposal.id) == 1


class TestPhase20MultiOptionStableWindowPreserved:
    """Multi-option SRR proposal with stable winners across stable window:
    no extension."""

    def test_multi_option_stable_no_extension(self, db):
        author = _user(db, "alice")
        org = _org(db, srr_enabled=True)
        _member(db, org, author)
        start = _now() - timedelta(seconds=80)
        end = _now() + timedelta(seconds=20)
        proposal = _approval_proposal(
            db, org=org, author=author,
            voting_start=start, voting_end=end,
        )
        # Seed two stable snapshots in the window.
        for offset in (15, 5):
            db.add(models.VoteSnapshot(
                proposal_id=proposal.id,
                simulated_time=_now() - timedelta(seconds=offset),
                yes_count=0, no_count=0, abstain_count=0,
                not_cast_count=0, total_eligible=1,
                multi_option_winners={
                    "winners": ["A"],
                    "total_ballots_cast": 1,
                    "option_totals": {"A": 1},
                },
            ))
        db.commit()

        result = worker.evaluate_proposal(db, proposal)
        db.commit()
        assert result is None


class TestPhase20MultiOptionDestabilizationPreserved:
    """Multi-option SRR proposal with winner-set change in stable window:
    extension fires."""

    def test_multi_option_winner_swap_extends(self, db):
        author = _user(db, "alice")
        org = _org(
            db, srr_enabled=True, max_extension_fraction=0.50,
        )
        _member(db, org, author)
        start = _now() - timedelta(seconds=80)
        end = _now() + timedelta(seconds=20)
        proposal = _approval_proposal(
            db, org=org, author=author,
            voting_start=start, voting_end=end,
        )
        # Two snapshots with disjoint winners.
        db.add(models.VoteSnapshot(
            proposal_id=proposal.id,
            simulated_time=_now() - timedelta(seconds=15),
            yes_count=0, no_count=0, abstain_count=0,
            not_cast_count=0, total_eligible=1,
            multi_option_winners={
                "winners": ["A"], "total_ballots_cast": 1,
            },
        ))
        db.add(models.VoteSnapshot(
            proposal_id=proposal.id,
            simulated_time=_now() - timedelta(seconds=5),
            yes_count=0, no_count=0, abstain_count=0,
            not_cast_count=0, total_eligible=1,
            multi_option_winners={
                "winners": ["B"], "total_ballots_cast": 1,
            },
        ))
        db.commit()

        old_end = proposal.voting_end
        result = worker.evaluate_proposal(db, proposal)
        db.commit()
        assert result == "extended"
        assert proposal.voting_end > old_end


class TestPhase20ExtensionLifecyclePreserved:
    """Full lifecycle: destabilize → extend → re-stabilize during extension
    → close_early. Same outcome as pre-Phase-22."""

    def test_full_lifecycle_close_early_on_stable_extension(self, db):
        author = _user(db, "alice")
        bob = _user(db, "bob")
        org = _org(
            db, srr_enabled=True, max_extension_fraction=0.50,
        )
        _member(db, org, author)
        _member(db, org, bob)
        # Already extended once; sliding-window lookback stable → close_early.
        start = _now() - timedelta(seconds=130)
        end = start + timedelta(seconds=125)  # original 100s + 25s extension
        proposal = _binary_proposal(
            db, org=org, author=author,
            voting_start=start, voting_end=end,
        )
        _seed_extension_audit(db, proposal, extension_seconds=25)
        # Seed a stable snapshot in the sliding lookback (last 25s).
        db.add(models.VoteSnapshot(
            proposal_id=proposal.id,
            simulated_time=_now() - timedelta(seconds=15),
            yes_count=8, no_count=2, abstain_count=0,
            not_cast_count=0, total_eligible=10,
            multi_option_winners=None,
        ))
        _cast_binary(db, author, proposal, "yes")
        _cast_binary(db, bob, proposal, "yes")
        db.commit()

        result = worker.evaluate_proposal(db, proposal)
        db.commit()
        assert result == "closed_early"
        assert proposal.status in ("passed", "failed")


class TestPhase20BudgetExhaustionPreserved:
    """max_extension_fraction=0.0: destabilization triggers force-close
    audit (proposal continues to natural voting_end); no extension."""

    def test_zero_budget_logs_destabilization_no_extension(self, db):
        author = _user(db, "alice")
        bob = _user(db, "bob")
        org = _org(
            db, srr_enabled=True, max_extension_fraction=0.0,
        )
        _member(db, org, author)
        _member(db, org, bob)
        start = _now() - timedelta(seconds=80)
        end = _now() + timedelta(seconds=20)
        proposal = _binary_proposal(
            db, org=org, author=author,
            voting_start=start, voting_end=end,
        )
        # Pre-seed a destabilizing snapshot.
        db.add(models.VoteSnapshot(
            proposal_id=proposal.id,
            simulated_time=_now() - timedelta(seconds=10),
            yes_count=2, no_count=8, abstain_count=0,
            not_cast_count=0, total_eligible=10,
            multi_option_winners=None,
        ))
        _cast_binary(db, author, proposal, "no")
        _cast_binary(db, bob, proposal, "no")
        db.commit()

        old_end = proposal.voting_end
        result = worker.evaluate_proposal(db, proposal)
        db.commit()
        assert result == "destabilized_at_max"
        assert proposal.voting_end == old_end
        # Audit event written.
        destab_rows = db.query(models.AuditLog).filter(
            models.AuditLog.action == "proposal.destabilization_at_max_extensions",
            models.AuditLog.target_id == proposal.id,
        ).count()
        assert destab_rows == 1


class TestPhase20EvaluateStabilityCalledIdentically:
    """Verify evaluate_original_window_stability is called with the same
    kwargs Phase 20 would have used. The Phase 22 universal-capture change
    must not drift the call contract."""

    def test_kwargs_preserved(self, db):
        author = _user(db, "alice")
        bob = _user(db, "bob")
        org = _org(db, srr_enabled=True)
        _member(db, org, author)
        _member(db, org, bob)
        start = _now() - timedelta(seconds=80)
        end = _now() + timedelta(seconds=20)
        proposal = _binary_proposal(
            db, org=org, author=author,
            voting_start=start, voting_end=end,
            pass_threshold=0.6,
        )
        _cast_binary(db, author, proposal, "yes")
        _cast_binary(db, bob, proposal, "yes")
        db.commit()

        recorded: dict = {}
        real_fn = worker.evaluate_original_window_stability

        def _spy(**kwargs):
            recorded["kwargs"] = kwargs
            return real_fn(**kwargs)

        with mock.patch.object(
            worker, "evaluate_original_window_stability", side_effect=_spy
        ):
            worker.evaluate_proposal(db, proposal)
            db.commit()

        # The function was called.
        assert "kwargs" in recorded, (
            "evaluate_original_window_stability not invoked for SRR proposal"
        )
        kw = recorded["kwargs"]
        # Phase 20 contract: these kwargs are the load-bearing inputs.
        assert kw["voting_method"] == "binary"
        assert kw["pass_threshold"] == pytest.approx(0.6)
        assert kw["voting_start"] == proposal.voting_start
        assert kw["stable_window_fraction"] == pytest.approx(0.25)
        # snapshots + now + voting_end are present (exact values vary by
        # extension state, but they are passed).
        assert "snapshots" in kw
        assert "now" in kw
        assert "voting_end" in kw
