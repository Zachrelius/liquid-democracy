"""Phase 36 — trajectory alignment regression tests.

Covers:
  - B1: ``generate_snapshots`` accepts a ``terminal_tally`` kwarg, rebases
    intermediate snapshots to interpolate toward it, and overwrites the
    LAST emitted snapshot exactly with the terminal values so the chart's
    final point matches the /results panel regardless of waypoint disagreement.
  - B2: full seed-pipeline integration — after a real bible seed, the last
    VoteSnapshot row for a closed binary proposal agrees with
    ``compute_tally(proposal, db)`` on yes/no/abstain counts.

The headline regression is B2#5 (test_b2_seed_pipeline_trajectory_matches_results_for_closed_binary).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base
from delegation_engine import engine as delegation_engine_singleton
from demo_content.hoa_bible import HOA_BIBLE
from demo_content.schema import Trajectory, Waypoint, TrajectoryEvent
from demo_content.seed_pipeline import seed_org_from_bible
from demo_snapshot_generator import generate_snapshots


@pytest.fixture(scope="function")
def db_session():
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


def _binary_traj():
    return Trajectory(
        proposal_id="P-TEST-36-BIN",
        voting_method="binary",
        duration_hours=72,
        waypoints=[
            Waypoint(hour=0, support_pct=0.0),
            Waypoint(hour=24, support_pct=40.0),
            Waypoint(hour=72, support_pct=80.0),  # Waypoint says 80% support
        ],
        events=[TrajectoryEvent(0, "voting_open")],
        final_result="80-20 passed",
    )


def _approval_traj():
    return Trajectory(
        proposal_id="P-TEST-36-APP",
        voting_method="approval",
        duration_hours=72,
        waypoints=[
            Waypoint(hour=0, support_pct=0.0),
            Waypoint(hour=72, support_pct=70.0),
        ],
        events=[TrajectoryEvent(0, "voting_open")],
        final_result="passed",
    )


# ===========================================================================
# B1 — terminal_tally rebase behavior
# ===========================================================================


class TestB1TerminalTallyBinary:
    """terminal_tally overrides the legacy waypoint-driven shape."""

    def test_b1_terminal_tally_binary_last_snapshot_matches(self, db_session):
        """Last emitted snapshot exactly equals terminal_tally values
        regardless of what the final waypoint's support_pct would produce.
        """
        proposal = SimpleNamespace(id="prop-bin-1", options=[], num_winners=1)
        start = datetime(2026, 5, 19, 0, 0, 0)
        end = start + timedelta(hours=72)
        # Waypoint terminus says 80% support; deliberately set terminal_tally
        # to a different split (say 53-37 with 3 abstain).
        terminal_tally = {
            "method": "binary",
            "yes": 53,
            "no": 37,
            "abstain": 3,
            "total_cast": 93,
            "not_cast": 7,
            "total_eligible": 100,
        }
        snaps = generate_snapshots(
            proposal=proposal,
            trajectory=_binary_traj(),
            voting_start=start,
            voting_end=end,
            cadence_seconds=3600,
            total_eligible=100,
            terminal_tally=terminal_tally,
        )
        assert len(snaps) > 0
        last = snaps[-1]
        # Last snapshot must match terminal_tally exactly — that's the
        # whole point of the rebase guard.
        assert last.yes_count == 53
        assert last.no_count == 37
        assert last.abstain_count == 3
        assert last.not_cast_count == 7
        assert last.total_eligible == 100
        assert last.multi_option_winners is None

    def test_b1_terminal_tally_none_preserves_legacy_behavior(self, db_session):
        """When terminal_tally is None, the legacy
        waypoint × lumpy × total_eligible computation applies; yes_count
        on the LAST snapshot is derived from the final waypoint
        (80% support × ballots_so_far), not from a terminal tally.
        """
        proposal = SimpleNamespace(id="prop-bin-2", options=[], num_winners=1)
        start = datetime(2026, 5, 19, 0, 0, 0)
        end = start + timedelta(hours=72)
        snaps = generate_snapshots(
            proposal=proposal,
            trajectory=_binary_traj(),
            voting_start=start,
            voting_end=end,
            cadence_seconds=3600,
            total_eligible=60,
            terminal_tally=None,  # legacy
        )
        assert len(snaps) > 0
        last = snaps[-1]
        # Legacy: yes ≈ 80% of ballots_so_far; abstain = 0
        assert last.abstain_count == 0
        # ballots_so_far ≈ 0.99-1.00 × 60 = ~60; yes ≈ 80% of 60 = ~48
        ballots = last.yes_count + last.no_count + last.abstain_count
        assert ballots <= 60
        # Sanity: yes/(yes+no) close to 80% (legacy semantics)
        if ballots > 0:
            ratio = last.yes_count / max(1, ballots)
            assert 0.6 <= ratio <= 1.0, (
                f"Legacy ratio {ratio:.2f} outside expected ~0.8 window"
            )


class TestB1TerminalTallyMultiOption:
    """Multi-option terminal_tally drives option_totals + winners directly."""

    def test_b1_terminal_tally_multi_option_last_snapshot_matches(
        self, db_session
    ):
        proposal = SimpleNamespace(
            id="prop-app-1",
            options=[
                SimpleNamespace(id="opt-A", label="A", display_order=0),
                SimpleNamespace(id="opt-B", label="B", display_order=1),
                SimpleNamespace(id="opt-C", label="C", display_order=2),
            ],
            num_winners=2,
        )
        start = datetime(2026, 5, 19, 0, 0, 0)
        end = start + timedelta(hours=72)
        terminal_tally = {
            "method": "approval",
            "option_totals": {"opt-A": 18, "opt-B": 42, "opt-C": 25},
            # Winners deliberately NOT in display_order (B is leader)
            "winners": ["opt-B", "opt-C"],
            "total_cast": 60,
            "total_abstain": 2,
            "not_cast": 38,
            "total_eligible": 100,
        }
        snaps = generate_snapshots(
            proposal=proposal,
            trajectory=_approval_traj(),
            voting_start=start,
            voting_end=end,
            cadence_seconds=3600,
            total_eligible=100,
            terminal_tally=terminal_tally,
        )
        assert len(snaps) > 0
        last = snaps[-1]
        mw = last.multi_option_winners
        assert mw is not None
        assert mw["winners"] == ["opt-B", "opt-C"]
        assert mw["total_ballots_cast"] == 60
        assert mw["option_totals"] == {"opt-A": 18, "opt-B": 42, "opt-C": 25}
        assert last.abstain_count == 2
        assert last.total_eligible == 100


class TestB1TerminalTallyMonotone:
    """Intermediate snapshots interpolate monotonically toward terminal."""

    def test_b1_terminal_tally_intermediate_snapshots_interpolate_monotonically(
        self, db_session
    ):
        proposal = SimpleNamespace(id="prop-mono-1", options=[], num_winners=1)
        start = datetime(2026, 5, 19, 0, 0, 0)
        end = start + timedelta(hours=72)
        terminal_tally = {
            "method": "binary",
            "yes": 30,
            "no": 25,
            "abstain": 5,
            "total_cast": 60,
            "not_cast": 40,
            "total_eligible": 100,
        }
        snaps = generate_snapshots(
            proposal=proposal,
            trajectory=_binary_traj(),
            voting_start=start,
            voting_end=end,
            cadence_seconds=1800,  # 30-min cadence; many snapshots
            total_eligible=100,
            terminal_tally=terminal_tally,
        )
        assert len(snaps) >= 3
        # Skip the last snapshot (which is the exact rebase) for the
        # monotonicity check on intermediates — though the rebase value
        # equals the terminal_tally so it should still satisfy the
        # monotonicity check.
        cumulative = [
            s.yes_count + s.no_count + s.abstain_count for s in snaps
        ]
        for i in range(1, len(cumulative)):
            assert cumulative[i] >= cumulative[i - 1], (
                f"Snapshot {i} ({cumulative[i]}) < "
                f"snapshot {i-1} ({cumulative[i-1]}); not monotone."
            )
        # Last must equal terminal total_cast exactly.
        assert cumulative[-1] == 60


# ===========================================================================
# B2 — seed pipeline integration
# ===========================================================================


class TestB2SeedPipelineTrajectoryMatchesResults:
    """End-to-end: real bible seed → compute_tally agrees with last snapshot."""

    def test_b2_seed_pipeline_trajectory_matches_results_for_closed_binary(
        self, db_session
    ):
        """Seed Cedar Hollow HOA bible into SQLite; pick the canonical
        closed-binary proposal (P-H-01, 'Pool Fee Structure 2026', passed
        58-42); assert the last VoteSnapshot row's yes/no/abstain agrees
        with compute_tally for that proposal.

        This is the headline regression-net test for the entire pass.
        """
        seed_org_from_bible(
            db_session,
            HOA_BIBLE,
            now=datetime(2026, 5, 19, 12, 0, 0),
        )
        db_session.flush()

        # Locate P-H-01 by title (Proposal model has no bible_proposal_id field).
        proposal = (
            db_session.query(models.Proposal)
            .filter(models.Proposal.title == "Pool Fee Structure 2026")
            .first()
        )
        assert proposal is not None, "Expected P-H-01 proposal to be seeded"
        assert proposal.voting_method == "binary"
        assert proposal.status in ("passed", "failed"), (
            f"P-H-01 should be closed; got status={proposal.status}"
        )

        # The last seeded snapshot.
        last_snap = (
            db_session.query(models.VoteSnapshot)
            .filter(models.VoteSnapshot.proposal_id == proposal.id)
            .order_by(models.VoteSnapshot.simulated_time.desc())
            .first()
        )
        assert last_snap is not None, (
            "P-H-12 should have at least one snapshot post-Phase-36"
        )

        # compute_tally over the actual seeded Vote rows.
        tally = delegation_engine_singleton.compute_tally(proposal, db_session)
        assert tally is not None

        # The cardinal assertion: trajectory's last point == /results
        # panel's count.
        assert last_snap.yes_count == tally.yes, (
            f"yes mismatch: snapshot={last_snap.yes_count} tally={tally.yes}"
        )
        assert last_snap.no_count == tally.no, (
            f"no mismatch: snapshot={last_snap.no_count} tally={tally.no}"
        )
        assert last_snap.abstain_count == tally.abstain, (
            f"abstain mismatch: snapshot={last_snap.abstain_count} "
            f"tally={tally.abstain}"
        )
