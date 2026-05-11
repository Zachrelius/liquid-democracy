"""
Phase 8 / Phase 20 — Stable Result Required worker integration tests.

Exercises ``evaluate_proposal`` end-to-end against an in-memory DB. Per
Phase 17 lesson: tests use real ``models.Proposal`` + ``models.VoteSnapshot``
rows rather than SimpleNamespace shims.

Tests cover the lifecycle paths in spec §B5:
  - Original-window stable / unstable (binary + multi-option).
  - Extension branch sliding-window stable -> early close.
  - Extension branch unstable -> wait for next tick.
  - Extension reaches voting_end with budget remaining -> another extension.
  - Extension reaches voting_end with budget exhausted -> destabilization-
    at-max-extensions audit; proposal continues to natural close.
  - max_extension_fraction = 0 -> no extension granted, audit logged.
  - Budget computation: 0.50 fits 2 extensions; 0.30 rounds down to 1.
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
from sustained_majority_service import (
    capture_snapshot,
    count_extensions,
    _sum_extension_seconds,
)
from audit_utils import log_audit_event
from tests.conftest import make_org_membership


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


def _member(db: Session, org: models.Organization, user: models.User) -> None:
    make_org_membership(
        db,
        user_id=user.id, org_id=org.id, role="member", status="active",
    )
    db.flush()


def _voting_org(
    db: Session,
    *,
    settings: dict | None = None,
) -> models.Organization:
    org = models.Organization(
        name="Org",
        slug=f"o-{id(settings)}",
        description="",
        join_policy="open",
        settings=settings or {
            "stable_result_enabled_default": True,
            "stable_window_fraction": 0.25,
            "max_extension_fraction": 0.25,
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
    pass_threshold: float = 0.5,
) -> models.Proposal:
    now = _now()
    p = models.Proposal(
        title="P",
        body="",
        author_id=author.id,
        org_id=org.id,
        voting_method=voting_method,
        status="voting",
        stable_result_required=None,  # inherit org default
        voting_start=voting_start or (now - timedelta(hours=2)),
        voting_end=voting_end or (now + timedelta(hours=4)),
        pass_threshold=pass_threshold,
        quorum_threshold=0.0,
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


def _seed_binary_snapshot(
    db: Session,
    proposal: models.Proposal,
    *,
    yes: int,
    no: int,
    abstain: int = 0,
    total_eligible: int = 10,
    when: datetime | None = None,
) -> models.VoteSnapshot:
    snap = models.VoteSnapshot(
        proposal_id=proposal.id,
        simulated_time=when or _now(),
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


def _seed_multi_snapshot(
    db: Session,
    proposal: models.Proposal,
    *,
    winners: list[str],
    when: datetime | None = None,
) -> models.VoteSnapshot:
    snap = models.VoteSnapshot(
        proposal_id=proposal.id,
        simulated_time=when or _now(),
        yes_count=0,
        no_count=0,
        abstain_count=0,
        not_cast_count=0,
        total_eligible=10,
        multi_option_winners={"winners": winners, "total_ballots_cast": 10},
    )
    db.add(snap)
    db.flush()
    return snap


def _seed_extension_audit(
    db: Session,
    proposal: models.Proposal,
    *,
    extension_seconds: int,
    when: datetime | None = None,
) -> None:
    """Record a worker-fired extension audit event so subsequent worker
    ticks see the right extension_count + budget_used."""
    log_audit_event(
        db,
        action="proposal.window_extended",
        target_type="proposal",
        target_id=proposal.id,
        actor_id=None,  # worker-fired
        details={
            "proposal_id": proposal.id,
            "extension_seconds": extension_seconds,
            "trigger": "stable_result_required",
        },
    )
    if when is not None:
        # Backdate the audit row's timestamp if the test needs it.
        row = (
            db.query(models.AuditLog)
            .filter(models.AuditLog.target_id == proposal.id)
            .order_by(models.AuditLog.timestamp.desc())
            .first()
        )
        if row is not None:
            row.timestamp = when
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

    def test_disable_flag_short_circuits(self):
        with mock.patch.object(worker.settings, "sustained_majority_worker_disable", True):
            assert worker.should_run_on_this_instance() is False


# ---------------------------------------------------------------------------
# Original-window scenarios
# ---------------------------------------------------------------------------

class TestEvaluateProposalOriginalWindow:
    """Proposals with no extensions yet — exercising the
    evaluate_original_window_stability branch.
    """

    def test_binary_stable_in_original_window_no_action(self, db):
        """Binary proposal with support >= pass_threshold throughout
        stable window: no extension fires."""
        author = _user(db, "alice")
        bob = _user(db, "bob")
        org = _voting_org(db)
        # 100s window, now near the end so we're inside the stable window.
        start = _now() - timedelta(seconds=80)
        end = _now() + timedelta(seconds=20)
        proposal = _voting_proposal(
            db, org=org, author=author,
            voting_start=start, voting_end=end,
        )
        _member(db, org, author)
        _member(db, org, bob)
        _cast_binary(db, author, proposal, "yes")
        _cast_binary(db, bob, proposal, "yes")
        db.commit()

        result = worker.evaluate_proposal(db, proposal)
        db.commit()
        assert result is None
        # Snapshot was still taken.
        snap_count = db.query(models.VoteSnapshot).filter(
            models.VoteSnapshot.proposal_id == proposal.id,
        ).count()
        assert snap_count == 1
        assert proposal.status == "voting"

    def test_binary_unstable_in_window_extends(self, db):
        """Binary proposal with a snapshot below pass_threshold inside the
        stable window: extension fires, voting_end pushed back, audit logged.
        """
        author = _user(db, "alice")
        bob = _user(db, "bob")
        org = _voting_org(db, settings={
            "stable_result_enabled_default": True,
            "stable_window_fraction": 0.25,
            "max_extension_fraction": 0.50,  # accommodates 2 extensions
        })
        start = _now() - timedelta(seconds=80)
        end = _now() + timedelta(seconds=20)
        proposal = _voting_proposal(
            db, org=org, author=author,
            voting_start=start, voting_end=end,
        )
        _member(db, org, author)
        _member(db, org, bob)
        # Cast votes that tally to 1 yes / 1 no = 0.5 support exactly. To
        # force a breach we need support < 0.5. Seed a destabilizing snapshot
        # explicitly inside the stable window — the worker will also capture
        # a fresh snapshot on tick, but the seeded breach is what triggers
        # destabilization.
        _seed_binary_snapshot(
            db, proposal, yes=2, no=8, total_eligible=10,
            when=_now() - timedelta(seconds=10),  # inside stable window
        )
        # Cast a couple of votes so the live tally on tick is also bad.
        _cast_binary(db, author, proposal, "no")
        _cast_binary(db, bob, proposal, "no")
        db.commit()

        old_end = proposal.voting_end
        result = worker.evaluate_proposal(db, proposal)
        db.commit()

        assert result == "extended"
        # voting_end pushed back by stable_window_duration = 100s * 0.25 = 25s.
        # (Some jitter is fine; assert it moved forward.)
        assert proposal.voting_end > old_end
        # An extension audit event was written.
        ext_count = count_extensions(db, proposal.id)
        assert ext_count == 1
        # voting_end updated in place — proposal still in voting status.
        assert proposal.status == "voting"

    def test_multi_option_stable_winners_no_extension(self, db):
        author = _user(db, "alice")
        org = _voting_org(db)
        start = _now() - timedelta(seconds=80)
        end = _now() + timedelta(seconds=20)
        proposal = _voting_proposal(
            db, org=org, author=author, voting_method="approval",
            voting_start=start, voting_end=end,
        )
        _member(db, org, author)
        # Pre-seed two snapshots in the stable window with same winner.
        _seed_multi_snapshot(
            db, proposal, winners=["A"],
            when=_now() - timedelta(seconds=15),
        )
        _seed_multi_snapshot(
            db, proposal, winners=["A"],
            when=_now() - timedelta(seconds=5),
        )
        db.commit()

        result = worker.evaluate_proposal(db, proposal)
        db.commit()
        assert result is None

    def test_multi_option_winner_swap_extends(self, db):
        author = _user(db, "alice")
        org = _voting_org(db, settings={
            "stable_result_enabled_default": True,
            "stable_window_fraction": 0.25,
            "max_extension_fraction": 0.50,
        })
        start = _now() - timedelta(seconds=80)
        end = _now() + timedelta(seconds=20)
        proposal = _voting_proposal(
            db, org=org, author=author, voting_method="approval",
            voting_start=start, voting_end=end,
        )
        _member(db, org, author)
        # Two snapshots in stable window with disjoint winners.
        _seed_multi_snapshot(
            db, proposal, winners=["A"],
            when=_now() - timedelta(seconds=15),
        )
        _seed_multi_snapshot(
            db, proposal, winners=["B"],
            when=_now() - timedelta(seconds=5),
        )
        db.commit()

        old_end = proposal.voting_end
        result = worker.evaluate_proposal(db, proposal)
        db.commit()
        assert result == "extended"
        assert proposal.voting_end > old_end


# ---------------------------------------------------------------------------
# Extension-branch scenarios (sliding-window check)
# ---------------------------------------------------------------------------

class TestEvaluateProposalExtensionBranch:
    """Proposals with at least one prior worker-fired extension — exercising
    the evaluate_extension_stability sliding-window branch.
    """

    def _setup_extended_proposal(
        self,
        db: Session,
        *,
        original_duration_seconds: int = 100,
        extension_seconds: int = 25,
        max_ext_fraction: float = 0.50,
    ) -> tuple[models.User, models.Organization, models.Proposal]:
        author = _user(db, "alice")
        bob = _user(db, "bob")
        org = _voting_org(db, settings={
            "stable_result_enabled_default": True,
            "stable_window_fraction": 0.25,
            "max_extension_fraction": max_ext_fraction,
        })
        # The proposal has been extended once: original was [start, start+100s].
        # Now voting_end = start + 100s + extension_seconds.
        start = _now() - timedelta(seconds=original_duration_seconds + 10)
        end = start + timedelta(seconds=original_duration_seconds + extension_seconds)
        proposal = _voting_proposal(
            db, org=org, author=author,
            voting_start=start, voting_end=end,
        )
        _member(db, org, author)
        _member(db, org, bob)
        # Seed the prior extension audit event so count_extensions == 1
        # and _sum_extension_seconds returns the right value.
        _seed_extension_audit(
            db, proposal, extension_seconds=extension_seconds,
        )
        db.commit()
        return author, org, proposal

    def test_extension_stable_lookback_closes_early(self, db):
        """Sliding-window check during extension: all snapshots in lookback
        are stable -> proposal closes at this snapshot."""
        author, org, proposal = self._setup_extended_proposal(db)
        bob = db.query(models.User).filter(models.User.username == "bob").first()
        # Two snapshots within the lookback (stable_window_duration =
        # 100s * 0.25 = 25s), both stable.
        _seed_binary_snapshot(
            db, proposal, yes=8, no=2, total_eligible=10,
            when=_now() - timedelta(seconds=15),
        )
        # Cast votes so the worker's fresh snapshot is also stable.
        _cast_binary(db, author, proposal, "yes")
        _cast_binary(db, bob, proposal, "yes")
        db.commit()

        result = worker.evaluate_proposal(db, proposal)
        db.commit()
        assert result == "closed_early"
        assert proposal.status in ("passed", "failed")
        # A status_changed audit was logged.
        rows = (
            db.query(models.AuditLog)
            .filter(
                models.AuditLog.action == "proposal.status_changed",
                models.AuditLog.target_id == proposal.id,
            )
            .all()
        )
        assert any(
            (r.details or {}).get("trigger") == "stable_result_achieved"
            for r in rows
        )

    def test_extension_unstable_lookback_continues(self, db):
        """Sliding-window check fails: voting continues until next tick or
        natural voting_end."""
        author, org, proposal = self._setup_extended_proposal(db)
        # Old snapshot in lookback was unstable.
        _seed_binary_snapshot(
            db, proposal, yes=2, no=8, total_eligible=10,
            when=_now() - timedelta(seconds=15),
        )
        # Cast yes votes so fresh worker snapshot is stable, but the OLD
        # one in lookback breaks the chain.
        bob = db.query(models.User).filter(models.User.username == "bob").first()
        _cast_binary(db, author, proposal, "yes")
        _cast_binary(db, bob, proposal, "yes")
        db.commit()

        result = worker.evaluate_proposal(db, proposal)
        db.commit()
        # Either None (waiting for next tick — voting_end not yet reached)
        # or "extended" (if voting_end passed and budget allows). With
        # voting_end ~15s in the future, expect None.
        assert result is None
        assert proposal.status == "voting"

    def test_extension_voting_end_reached_budget_remaining_extends_again(self, db):
        """Extension reaches its voting_end without stability; budget allows
        another extension."""
        author = _user(db, "alice")
        bob = _user(db, "bob")
        # max_extension_fraction = 0.50 -> budget = 50s.
        # First extension used 25s -> remaining = 25s -> fits another.
        org = _voting_org(db, settings={
            "stable_result_enabled_default": True,
            "stable_window_fraction": 0.25,
            "max_extension_fraction": 0.50,
        })
        # Original was 100s; one prior extension added 25s; voting_end now
        # in the past so worker considers it past natural voting_end.
        start = _now() - timedelta(seconds=130)
        end = _now() - timedelta(seconds=5)  # 5s ago
        proposal = _voting_proposal(
            db, org=org, author=author,
            voting_start=start, voting_end=end,
        )
        _member(db, org, author)
        _member(db, org, bob)
        _seed_extension_audit(db, proposal, extension_seconds=25)
        # Seed unstable snapshots so sliding-window is False.
        _seed_binary_snapshot(
            db, proposal, yes=2, no=8, total_eligible=10,
            when=_now() - timedelta(seconds=20),
        )
        # No fresh votes — fresh snapshot will be 0/0/0 = stable per D3
        # zero-vote-cast = stable. To force unstable lookback we cast no.
        _cast_binary(db, author, proposal, "no")
        _cast_binary(db, bob, proposal, "no")
        db.commit()

        old_end = proposal.voting_end
        result = worker.evaluate_proposal(db, proposal)
        db.commit()
        assert result == "extended"
        assert proposal.voting_end > old_end
        # Now there are 2 extension audits.
        assert count_extensions(db, proposal.id) == 2

    def test_extension_voting_end_reached_budget_exhausted_logs_max(self, db):
        """Extension reaches voting_end without stability + budget exhausted."""
        author = _user(db, "alice")
        bob = _user(db, "bob")
        # max_extension_fraction = 0.25 -> budget = 25s. One extension of
        # 25s already used -> budget remaining = 0, no further extension.
        org = _voting_org(db, settings={
            "stable_result_enabled_default": True,
            "stable_window_fraction": 0.25,
            "max_extension_fraction": 0.25,
        })
        start = _now() - timedelta(seconds=130)
        end = _now() - timedelta(seconds=5)
        proposal = _voting_proposal(
            db, org=org, author=author,
            voting_start=start, voting_end=end,
        )
        _member(db, org, author)
        _member(db, org, bob)
        _seed_extension_audit(db, proposal, extension_seconds=25)
        # Seed unstable snapshots so sliding-window is False.
        _seed_binary_snapshot(
            db, proposal, yes=2, no=8, total_eligible=10,
            when=_now() - timedelta(seconds=20),
        )
        _cast_binary(db, author, proposal, "no")
        _cast_binary(db, bob, proposal, "no")
        db.commit()

        old_end = proposal.voting_end
        result = worker.evaluate_proposal(db, proposal)
        db.commit()
        assert result == "destabilized_at_max"
        assert proposal.voting_end == old_end  # not extended
        # Audit event exists.
        rows = (
            db.query(models.AuditLog)
            .filter(
                models.AuditLog.action == "proposal.destabilization_at_max_extensions",
                models.AuditLog.target_id == proposal.id,
            )
            .all()
        )
        assert len(rows) == 1


# ---------------------------------------------------------------------------
# Budget computation edge cases (D9)
# ---------------------------------------------------------------------------

class TestExtensionBudgetSemantics:
    """Verify that the extension budget rounds down to whole stable_window_
    duration chunks."""

    def test_max_extension_fraction_zero_grants_no_extension(self, db):
        """max_extension_fraction = 0: destabilization detected, no extension
        granted, audit logged, proposal continues to original voting_end."""
        author = _user(db, "alice")
        bob = _user(db, "bob")
        org = _voting_org(db, settings={
            "stable_result_enabled_default": True,
            "stable_window_fraction": 0.25,
            "max_extension_fraction": 0.0,
        })
        start = _now() - timedelta(seconds=80)
        end = _now() + timedelta(seconds=20)
        proposal = _voting_proposal(
            db, org=org, author=author,
            voting_start=start, voting_end=end,
        )
        _member(db, org, author)
        _member(db, org, bob)
        # Seed in-window destabilizing snapshot.
        _seed_binary_snapshot(
            db, proposal, yes=2, no=8, total_eligible=10,
            when=_now() - timedelta(seconds=10),
        )
        _cast_binary(db, author, proposal, "no")
        _cast_binary(db, bob, proposal, "no")
        db.commit()

        old_end = proposal.voting_end
        result = worker.evaluate_proposal(db, proposal)
        db.commit()
        assert result == "destabilized_at_max"
        assert proposal.voting_end == old_end
        assert count_extensions(db, proposal.id) == 0
        # Audit recorded.
        rows = (
            db.query(models.AuditLog)
            .filter(
                models.AuditLog.action == "proposal.destabilization_at_max_extensions",
                models.AuditLog.target_id == proposal.id,
            )
            .all()
        )
        assert len(rows) == 1

    def test_budget_50pct_fits_two_extensions_exactly(self, db):
        """Per D9 worked example: 7-day proposal, stable_window_fraction =
        0.25, max_extension_fraction = 0.50 -> budget = 84h, fits 2
        extensions of 42h each.

        Modeled here at 100s scale: budget = 50s, fits 2 extensions of 25s.
        """
        author = _user(db, "alice")
        bob = _user(db, "bob")
        org = _voting_org(db, settings={
            "stable_result_enabled_default": True,
            "stable_window_fraction": 0.25,
            "max_extension_fraction": 0.50,
        })
        # Two extensions already used (50s).
        start = _now() - timedelta(seconds=155)
        end = _now() - timedelta(seconds=5)  # past voting_end
        proposal = _voting_proposal(
            db, org=org, author=author,
            voting_start=start, voting_end=end,
        )
        _member(db, org, author)
        _member(db, org, bob)
        _seed_extension_audit(db, proposal, extension_seconds=25)
        _seed_extension_audit(db, proposal, extension_seconds=25)
        # Force unstable lookback at voting_end.
        _seed_binary_snapshot(
            db, proposal, yes=2, no=8, total_eligible=10,
            when=_now() - timedelta(seconds=15),
        )
        _cast_binary(db, author, proposal, "no")
        _cast_binary(db, bob, proposal, "no")
        db.commit()

        result = worker.evaluate_proposal(db, proposal)
        db.commit()
        # Budget: 100s * 0.50 = 50s. Used: 50s. Remaining: 0. Cannot fit
        # another 25s extension. Should log destabilization-at-max.
        assert result == "destabilized_at_max"
        assert count_extensions(db, proposal.id) == 2

    def test_budget_30pct_rounds_down_to_one_extension(self, db):
        """Per D9: 7-day proposal, stable_window_fraction = 0.25,
        max_extension_fraction = 0.30 -> budget ~ 50h. One 42h extension
        fits; remaining 8h < 42h, no second extension.

        At 100s scale: budget = 30s, stable_window_duration = 25s. One
        extension fits; remaining 5s < 25s, no second.
        """
        author = _user(db, "alice")
        bob = _user(db, "bob")
        org = _voting_org(db, settings={
            "stable_result_enabled_default": True,
            "stable_window_fraction": 0.25,
            "max_extension_fraction": 0.30,
        })
        # One extension already used (25s).
        start = _now() - timedelta(seconds=130)
        end = _now() - timedelta(seconds=5)
        proposal = _voting_proposal(
            db, org=org, author=author,
            voting_start=start, voting_end=end,
        )
        _member(db, org, author)
        _member(db, org, bob)
        _seed_extension_audit(db, proposal, extension_seconds=25)
        # Unstable lookback at voting_end.
        _seed_binary_snapshot(
            db, proposal, yes=2, no=8, total_eligible=10,
            when=_now() - timedelta(seconds=15),
        )
        _cast_binary(db, author, proposal, "no")
        _cast_binary(db, bob, proposal, "no")
        db.commit()

        result = worker.evaluate_proposal(db, proposal)
        db.commit()
        # Budget: 100 * 0.30 = 30s. Used: 25s. Remaining: 5s < 25s. No
        # second extension.
        assert result == "destabilized_at_max"
        assert count_extensions(db, proposal.id) == 1


# ---------------------------------------------------------------------------
# Per-proposal override
# ---------------------------------------------------------------------------

class TestPerProposalOverride:
    def test_override_false_disables(self, db):
        """proposal.stable_result_required=False overrides org default-on."""
        author = _user(db, "alice")
        org = _voting_org(db, settings={
            "stable_result_enabled_default": True,
            "stable_window_fraction": 0.25,
            "max_extension_fraction": 0.25,
        })
        proposal = _voting_proposal(db, org=org, author=author)
        proposal.stable_result_required = False
        _member(db, org, author)
        db.commit()

        result = worker.evaluate_proposal(db, proposal)
        db.commit()
        assert result is None
        # No snapshot taken because feature was inactive.
        snap_count = db.query(models.VoteSnapshot).filter(
            models.VoteSnapshot.proposal_id == proposal.id,
        ).count()
        assert snap_count == 0
