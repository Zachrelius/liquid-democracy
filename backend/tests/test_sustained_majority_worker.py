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
from audit_utils import log_audit_event


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


def _member(db: Session, org: models.Organization, user: models.User) -> None:
    """Phase 10.1: scope-aware tally requires voters to be active org members.
    Pre-fix the worker tally iterated all users in the DB; post-fix only
    OrgMembership rows count. Helper added so the existing tests stay
    minimally changed.
    """
    db.add(models.OrgMembership(
        user_id=user.id, org_id=org.id, role="member", status="active",
    ))
    db.flush()


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


def _seed_establishing_snapshot(
    db: Session,
    proposal: models.Proposal,
    *,
    yes: int = 60,
    no: int = 40,
    abstain: int = 0,
    total_eligible: int = 100,
    seconds_ago: int = 3600,
) -> models.VoteSnapshot:
    """Insert a synthetic VoteSnapshot row representing prior establishment.

    Phase 9.8 C1: the floor only activates AFTER support has crossed the
    threshold at least once during the window. Worker tests that drive
    breach scenarios need a prior snapshot in the snapshot history showing
    support >= threshold so the breach is allowed to fire. We seed one
    directly rather than re-running `evaluate_proposal` against an
    established-then-mutated vote set, which would require swapping vote
    values mid-test and add fixture noise unrelated to what's being tested.
    """
    when = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=seconds_ago)
    snap = models.VoteSnapshot(
        proposal_id=proposal.id,
        simulated_time=when,
        yes_count=yes,
        no_count=no,
        abstain_count=abstain,
        not_cast_count=max(0, total_eligible - yes - no - abstain),
        total_eligible=total_eligible,
        multi_option_winners=None,
    )
    db.add(snap)
    db.flush()
    return snap


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
        """Phase 9.8 C1: requires a prior establishing snapshot. The original
        version of this test cast 1 yes / 9 no and expected immediate fail —
        which was the bug. After C1, breach only fires once support has been
        established (crossed threshold), so we seed an establishing snapshot
        first and assert the breach detection still works correctly.
        """
        author = _user(db, "alice")
        org = _voting_org(db, settings={
            "sustained_majority_enabled_default": True,
            "sustained_majority_floor": 0.45,
            "sustained_majority_failure_mode": "fail",
        })
        proposal = _voting_proposal(db, org=org, author=author)
        _member(db, org, author)  # Phase 10.1 eligibility
        # Seed prior establishment (60 yes / 40 no in history).
        _seed_establishing_snapshot(db, proposal, yes=60, no=40)
        # Now drop to 1 yes / 9 no → support 0.10, well below 0.45 floor.
        _cast_binary(db, author, proposal, "yes")
        for i in range(9):
            u = _user(db, f"no{i}")
            _member(db, org, u)  # Phase 10.1 eligibility
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
        """Phase 9.8 C1: seed establishment, then drop to no-vote → extend."""
        author = _user(db, "alice")
        org = _voting_org(db, settings={
            "sustained_majority_enabled_default": True,
            "sustained_majority_floor": 0.45,
            "sustained_majority_failure_mode": "extend",
        })
        proposal = _voting_proposal(db, org=org, author=author)
        _member(db, org, author)  # Phase 10.1 eligibility
        original_end = proposal.voting_end

        _seed_establishing_snapshot(db, proposal, yes=60, no=40)
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
        """Phase 9.8 C1: seed establishment so the extend → fail promotion
        path can be exercised."""
        author = _user(db, "alice")
        org = _voting_org(db, settings={
            "sustained_majority_enabled_default": True,
            "sustained_majority_floor": 0.45,
            "sustained_majority_failure_mode": "extend",
        })
        proposal = _voting_proposal(db, org=org, author=author)
        _member(db, org, author)  # Phase 10.1 eligibility
        _seed_establishing_snapshot(db, proposal, yes=60, no=40)
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
        """Phase 9.8 C1: seed establishment so escalate can fire on drop."""
        author = _user(db, "alice")
        org = _voting_org(db, settings={
            "sustained_majority_enabled_default": True,
            "sustained_majority_floor": 0.45,
            "sustained_majority_failure_mode": "escalate",
        })
        proposal = _voting_proposal(db, org=org, author=author)
        _member(db, org, author)  # Phase 10.1 eligibility
        _seed_establishing_snapshot(db, proposal, yes=60, no=40)
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

    def test_single_no_vote_without_establishment_does_not_fail(self, db):
        """Phase 9.8 C1 worker-level regression: a brand-new proposal with a
        single early no-vote and no prior support must NOT fail. This was
        the bug Z surfaced — under the old logic the proposal failed on the
        first vote, before anyone could vote yes.
        """
        author = _user(db, "alice")
        org = _voting_org(db, settings={
            "sustained_majority_enabled_default": True,
            "sustained_majority_floor": 0.45,
            "sustained_majority_failure_mode": "fail",
        })
        proposal = _voting_proposal(db, org=org, author=author)
        # No prior snapshot — establishment has never occurred.
        _cast_binary(db, author, proposal, "no")
        db.commit()

        result = worker.evaluate_proposal(db, proposal)
        db.commit()

        # Under the old logic this would return "failed". After C1: None.
        assert result is None
        assert proposal.status == "voting"
        # The snapshot was still captured (so the worker observes the state).
        snap_count = db.query(models.VoteSnapshot).filter(
            models.VoteSnapshot.proposal_id == proposal.id,
        ).count()
        assert snap_count == 1
        # No failure audit event.
        evt = db.query(models.AuditLog).filter(
            models.AuditLog.action == "proposal.failed_sustained_majority",
            models.AuditLog.target_id == proposal.id,
        ).first()
        assert evt is None


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
        """Re-running the worker tick should not extend the same proposal twice.

        Phase 9.8 C1: seeds an establishing snapshot so the breach is allowed
        to fire (the original test's single no-vote no longer triggers the
        floor without prior establishment).
        """
        author = _user(db, "alice")
        org = _voting_org(db, settings={
            "sustained_majority_enabled_default": True,
            "sustained_majority_floor": 0.45,
            "sustained_majority_failure_mode": "extend",
        })
        proposal = _voting_proposal(db, org=org, author=author)
        _member(db, org, author)  # Phase 10.1 eligibility
        _seed_establishing_snapshot(db, proposal, yes=60, no=40)
        _cast_binary(db, author, proposal, "no")
        db.commit()

        worker.run_one_tick(db)  # extends once
        # Recompute support — still below floor (votes haven't changed)
        assert count_extensions(db, proposal.id) == 1

        worker.run_one_tick(db)  # second run should fail (not extend again)
        assert proposal.status == "failed"
        assert count_extensions(db, proposal.id) == 1  # no second extend


# ---------------------------------------------------------------------------
# count_extensions actor-aware filter (Phase 8.1 Item 2)
# ---------------------------------------------------------------------------

class TestCountExtensionsActorFilter:
    """The worker's "extension already used" guard rail should only count
    system-fired extensions (actor_id IS NULL). Admin-driven extensions via
    resolve_escalation have actor_id set and must NOT count.
    """

    def test_admin_extension_not_counted(self, db):
        """Two window_extended events on the same proposal: one with
        actor_id=None (worker), one with actor_id=<admin user id>. Only the
        worker-fired one should count.
        """
        author = _user(db, "alice")
        admin = _user(db, "admin")
        org = _voting_org(db)
        proposal = _voting_proposal(db, org=org, author=author)
        db.commit()

        # Worker-style extension (system actor).
        log_audit_event(
            db,
            action="proposal.window_extended",
            target_type="proposal",
            target_id=proposal.id,
            actor_id=None,
            details={"proposal_id": proposal.id, "source": "worker"},
        )
        # Admin-style extension (actor_id set) — should be excluded.
        log_audit_event(
            db,
            action="proposal.window_extended",
            target_type="proposal",
            target_id=proposal.id,
            actor_id=admin.id,
            details={"proposal_id": proposal.id, "source": "resolve_escalation"},
        )
        db.commit()

        assert count_extensions(db, proposal.id) == 1

    def test_only_admin_extension_returns_zero(self, db):
        """A standalone admin extension must return 0 — the worker should still
        be willing to fire its one allowed extension afterwards.
        """
        author = _user(db, "alice")
        admin = _user(db, "admin")
        org = _voting_org(db)
        proposal = _voting_proposal(db, org=org, author=author)
        db.commit()

        log_audit_event(
            db,
            action="proposal.window_extended",
            target_type="proposal",
            target_id=proposal.id,
            actor_id=admin.id,
            details={"proposal_id": proposal.id, "source": "resolve_escalation"},
        )
        db.commit()

        assert count_extensions(db, proposal.id) == 0

    def test_apply_failure_mode_extend_admin_then_worker(self, db):
        """Integration-style: drive the extend path through
        `apply_failure_mode` twice — once with an admin actor_id (mimicking
        resolve_escalation's "extend" branch) and once with actor_id=None
        (worker). The admin call must not consume the worker's one allowed
        extension.

        Why this scope (not the full worker re-escalate flow): the full
        escalate→admin-extend→breach→re-escalate sequence requires invoking
        `evaluate_proposal` against an `escalate`-mode org, then mutating
        proposal.status back to "voting" after admin resolution, then driving
        a second breach with snapshot history that satisfies both the
        approaching-floor + sustained-breach windows. That's >100 lines of
        fixture wiring whose substance isn't the bug we're fixing — the bug
        is "do extension counts include admin events?". Calling
        `apply_failure_mode` twice and asserting `count_extensions == 1`
        proves the guard rail directly.
        """
        author = _user(db, "alice")
        admin = _user(db, "admin")
        org = _voting_org(db, settings={
            "sustained_majority_enabled_default": True,
            "sustained_majority_floor": 0.45,
            "sustained_majority_failure_mode": "extend",
        })
        proposal = _voting_proposal(db, org=org, author=author)
        db.commit()

        decision = FailureDecision(
            should_fire=True,
            mode="extend",
            reason="floor breach",
            breach_sample={"yes": 1, "no": 9},
        )

        # 1) Admin-driven extend (resolve_escalation analogue).
        apply_failure_mode(
            db, proposal, decision=decision, actor_id=admin.id,
        )
        db.commit()
        # Admin extension should not consume the worker's allowance.
        assert count_extensions(db, proposal.id) == 0

        # 2) Worker-driven extend (system actor).
        apply_failure_mode(
            db, proposal, decision=decision, actor_id=None,
        )
        db.commit()
        # Now the worker has used its one extension.
        assert count_extensions(db, proposal.id) == 1

        # Sanity: total window_extended events is 2 (both wrote audit rows).
        total = db.query(models.AuditLog).filter(
            models.AuditLog.action == "proposal.window_extended",
            models.AuditLog.target_id == proposal.id,
        ).count()
        assert total == 2
