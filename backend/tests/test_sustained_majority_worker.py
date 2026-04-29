"""
Phase 8 — sustained-majority background worker integration tests.

Exercises `evaluate_proposal` + `run_one_tick` end-to-end against an in-memory
DB. We mock `should_run_on_this_instance` only where the multi-instance guard
itself is the unit under test; the rest of the suite calls `evaluate_proposal`
directly and checks side effects (status mutation, audit-log entries,
extension counts).
"""

from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

import models
import sustained_majority_worker as worker
from database import Base
from sustained_majority import (
    BinarySnapshotPoint,
    FailureDecision,
    SustainedMajorityConfig,
    should_trigger_failure,
)
from sustained_majority_service import (
    apply_failure_mode,
    capture_snapshot,
    count_extensions,
)


_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


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


def _voting_org(db: Session, settings: dict | None = None) -> models.Organization:
    org = models.Organization(
        name="Org",
        slug="o",
        description="",
        join_policy="open",
        settings=settings or {
            "sustained_majority_enabled_default": True,
            "sustained_majority_floor": 0.45,
            "sustained_majority_failure_mode": "fail",
        },
    )
    db.add(org)
    db.flush()
    return org


def _voting_proposal(
    db: Session,
    *,
    org: models.Organization,
    author: models.User,
    voting_method: str = "binary",
    voting_start: datetime | None = None,
    voting_end: datetime | None = None,
) -> models.Proposal:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    p = models.Proposal(
        title="P",
        body="",
        author_id=author.id,
        org_id=org.id,
        voting_method=voting_method,
        status="voting",
        sustained_majority_enabled=None,  # inherit org default
        voting_start=voting_start or (now - timedelta(hours=2)),
        voting_end=voting_end or (now + timedelta(hours=4)),
    )
    db.add(p)
    db.flush()
    return p


def _cast_binary(db: Session, user: models.User, proposal: models.Proposal, value: str):
    db.add(models.Vote(
        proposal_id=proposal.id,
        user_id=user.id,
        vote_value=value,
        is_direct=True,
        cast_by_id=user.id,
    ))
    db.flush()


# ---------------------------------------------------------------------------
# Multi-instance guard
# ---------------------------------------------------------------------------

class TestInstanceGuard:
    def test_runs_when_no_instance_id_set(self):
        with mock.patch.object(worker.settings, "sustained_majority_worker_instance_id", ""):
            with mock.patch.object(worker.settings, "sustained_majority_worker_disable", False):
                assert worker.should_run_on_this_instance() is True

    def test_skips_when_instance_id_mismatch(self, monkeypatch):
        monkeypatch.setenv("INSTANCE_ID", "worker-2")
        with mock.patch.object(
            worker.settings, "sustained_majority_worker_instance_id", "worker-1"
        ):
            with mock.patch.object(
                worker.settings, "sustained_majority_worker_disable", False
            ):
                assert worker.should_run_on_this_instance() is False

    def test_runs_when_instance_id_matches(self, monkeypatch):
        monkeypatch.setenv("INSTANCE_ID", "primary")
        with mock.patch.object(
            worker.settings, "sustained_majority_worker_instance_id", "primary"
        ):
            with mock.patch.object(
                worker.settings, "sustained_majority_worker_disable", False
            ):
                assert worker.should_run_on_this_instance() is True

    def test_disable_flag_short_circuits(self):
        with mock.patch.object(worker.settings, "sustained_majority_worker_disable", True):
            assert worker.should_run_on_this_instance() is False


# ---------------------------------------------------------------------------
# evaluate_proposal — binary failure modes
# ---------------------------------------------------------------------------

class TestEvaluateProposalBinary:
    def test_above_floor_no_action(self, db):
        author = _user(db, "alice")
        org = _voting_org(db)
        proposal = _voting_proposal(db, org=org, author=author)
        _cast_binary(db, author, proposal, "yes")
        bob = _user(db, "bob")
        _cast_binary(db, bob, proposal, "yes")
        db.commit()

        result = worker.evaluate_proposal(db, proposal)
        db.commit()

        assert result is None
        assert proposal.status == "voting"
        # Snapshot was still taken even though no failure fired.
        snap_count = db.query(models.VoteSnapshot).filter(
            models.VoteSnapshot.proposal_id == proposal.id,
        ).count()
        assert snap_count == 1

    def test_below_floor_fail_mode_moves_to_failed(self, db):
        author = _user(db, "alice")
        org = _voting_org(db, settings={
            "sustained_majority_enabled_default": True,
            "sustained_majority_floor": 0.45,
            "sustained_majority_failure_mode": "fail",
        })
        proposal = _voting_proposal(db, org=org, author=author)
        # 1 yes / 9 no → support 0.10, well below 0.45 floor
        _cast_binary(db, author, proposal, "yes")
        for i in range(9):
            u = _user(db, f"no{i}")
            _cast_binary(db, u, proposal, "no")
        db.commit()

        result = worker.evaluate_proposal(db, proposal)
        db.commit()

        assert result == "failed"
        assert proposal.status == "failed"
        # Audit event recorded.
        evt = db.query(models.AuditLog).filter(
            models.AuditLog.action == "proposal.failed_sustained_majority",
            models.AuditLog.target_id == proposal.id,
        ).first()
        assert evt is not None
        assert evt.details["breach_sample"]["yes"] == 1

    def test_extend_mode_extends_window_first_time(self, db):
        author = _user(db, "alice")
        org = _voting_org(db, settings={
            "sustained_majority_enabled_default": True,
            "sustained_majority_floor": 0.45,
            "sustained_majority_failure_mode": "extend",
        })
        proposal = _voting_proposal(db, org=org, author=author)
        original_end = proposal.voting_end

        _cast_binary(db, author, proposal, "no")
        db.commit()

        result = worker.evaluate_proposal(db, proposal)
        db.commit()

        # Status stays voting; voting_end is pushed forward.
        assert result == "voting"
        assert proposal.status == "voting"
        assert proposal.voting_end > original_end
        ext_count = count_extensions(db, proposal.id)
        assert ext_count == 1

    def test_extend_promotes_to_fail_on_second_breach(self, db):
        author = _user(db, "alice")
        org = _voting_org(db, settings={
            "sustained_majority_enabled_default": True,
            "sustained_majority_floor": 0.45,
            "sustained_majority_failure_mode": "extend",
        })
        proposal = _voting_proposal(db, org=org, author=author)
        _cast_binary(db, author, proposal, "no")
        db.commit()

        # First breach — extends.
        worker.evaluate_proposal(db, proposal)
        db.commit()
        assert proposal.status == "voting"
        assert count_extensions(db, proposal.id) == 1

        # Second breach — promotes to fail.
        worker.evaluate_proposal(db, proposal)
        db.commit()
        assert proposal.status == "failed"

    def test_escalate_mode_moves_to_unresolved(self, db):
        author = _user(db, "alice")
        org = _voting_org(db, settings={
            "sustained_majority_enabled_default": True,
            "sustained_majority_floor": 0.45,
            "sustained_majority_failure_mode": "escalate",
        })
        proposal = _voting_proposal(db, org=org, author=author)
        _cast_binary(db, author, proposal, "no")
        db.commit()

        result = worker.evaluate_proposal(db, proposal)
        db.commit()

        assert result == "unresolved"
        assert proposal.status == "unresolved"
        evt = db.query(models.AuditLog).filter(
            models.AuditLog.action == "proposal.escalated",
            models.AuditLog.target_id == proposal.id,
        ).first()
        assert evt is not None


# ---------------------------------------------------------------------------
# Per-proposal override respected
# ---------------------------------------------------------------------------

class TestPerProposalOverrideRespected:
    def test_explicit_false_skips_evaluation(self, db):
        """proposal.sustained_majority_enabled=False overrides org default-on."""
        author = _user(db, "alice")
        org = _voting_org(db, settings={
            "sustained_majority_enabled_default": True,
            "sustained_majority_floor": 0.45,
            "sustained_majority_failure_mode": "fail",
        })
        proposal = _voting_proposal(db, org=org, author=author)
        proposal.sustained_majority_enabled = False
        # Even with bad support, this proposal should not fail.
        _cast_binary(db, author, proposal, "no")
        db.commit()

        result = worker.evaluate_proposal(db, proposal)
        db.commit()

        assert result is None
        assert proposal.status == "voting"
        # No snapshot taken either — evaluate_proposal short-circuits.
        snap_count = db.query(models.VoteSnapshot).filter(
            models.VoteSnapshot.proposal_id == proposal.id,
        ).count()
        assert snap_count == 0


# ---------------------------------------------------------------------------
# run_one_tick — full sweep
# ---------------------------------------------------------------------------

class TestRunOneTick:
    def test_skips_non_voting_proposals(self, db):
        author = _user(db, "alice")
        org = _voting_org(db)
        # One voting, one draft
        active = _voting_proposal(db, org=org, author=author)
        draft = models.Proposal(
            title="Draft", body="", author_id=author.id, org_id=org.id,
            voting_method="binary", status="draft",
        )
        db.add(draft)
        _cast_binary(db, author, active, "yes")
        db.commit()

        processed = worker.run_one_tick(db)
        # Only the voting one is touched (snapshot recorded).
        assert processed == 1
        snap_count = db.query(models.VoteSnapshot).count()
        assert snap_count == 1

    def test_one_proposal_failure_does_not_block_others(self, db):
        """Defensive: a per-proposal exception should not abort the loop."""
        author = _user(db, "alice")
        org = _voting_org(db)
        good = _voting_proposal(db, org=org, author=author)
        _cast_binary(db, author, good, "yes")
        # A second proposal with no org will trigger the early-return path
        # in evaluate_proposal (org_id=None) — exercised here for parity, not
        # a real exception, but confirms the loop continues.
        bad = models.Proposal(
            title="Orphan", body="", author_id=author.id, org_id=None,
            voting_method="binary", status="voting",
        )
        db.add(bad)
        db.commit()

        processed = worker.run_one_tick(db)
        assert processed == 2  # both processed (orphan early-returns)

    def test_restart_safe_no_double_extension(self, db):
        """Re-running the worker tick should not extend the same proposal twice."""
        author = _user(db, "alice")
        org = _voting_org(db, settings={
            "sustained_majority_enabled_default": True,
            "sustained_majority_floor": 0.45,
            "sustained_majority_failure_mode": "extend",
        })
        proposal = _voting_proposal(db, org=org, author=author)
        _cast_binary(db, author, proposal, "no")
        db.commit()

        worker.run_one_tick(db)  # extends once
        # Recompute support — still below floor (votes haven't changed)
        assert count_extensions(db, proposal.id) == 1

        worker.run_one_tick(db)  # second run should fail (not extend again)
        assert proposal.status == "failed"
        assert count_extensions(db, proposal.id) == 1  # no second extend
