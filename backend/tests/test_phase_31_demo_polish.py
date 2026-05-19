"""Phase 31 — demo polish tests.

Covers:
  - B1: ``generate_snapshots`` respects ``seed_until`` and ``allocate_filler_votes``
    respects ``cast_at_cap`` — the two changes that fix the live-worker /
    seed-data boundary spike.
  - B5: the lumpy cumulative-vote curve produced by
    ``_lumpy_fraction_voted_at`` is monotone non-decreasing and
    deterministic per ``proposal_id``.
  - F1: proposal list endpoint orders voting → deliberation → closed,
    with secondary sort within each group.
  - N1: registering a new user stamps the "low" preset.
  - N1: seed pipeline stamps a bible member's notification preset.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base, get_db
from demo_content.filler_generator import FillerMember, allocate_filler_votes
from demo_content.hoa_bible import HOA_BIBLE
from demo_content.schema import Trajectory, Waypoint, TrajectoryEvent
from demo_content.seed_pipeline import seed_org_from_bible
from demo_snapshot_generator import (
    _lumpy_fraction_voted_at,
    generate_snapshots,
)
from main import app
from notification_events import PRESET_STAMP_RULES, build_preset_preference_rows


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


@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


# ===========================================================================
# B1 — Spike fix: seed_until + cast_at_cap
# ===========================================================================


class TestGenerateSnapshotsSeedUntil:
    """``seed_until`` truncates seeded snapshots at the elapsed boundary."""

    def _make_traj(self):
        return Trajectory(
            proposal_id="P-TEST-01",
            voting_method="binary",
            duration_hours=72,
            waypoints=[
                Waypoint(hour=0, support_pct=0.0),
                Waypoint(hour=24, support_pct=50.0),
                Waypoint(hour=72, support_pct=60.0),
            ],
            events=[TrajectoryEvent(0, "voting_open")],
            final_result="60-40 passed",
        )

    def test_no_cap_emits_full_window(self, db_session):
        proposal = SimpleNamespace(id="prop-1", options=[], num_winners=1)
        start = datetime(2026, 5, 19, 0, 0, 0)
        end = start + timedelta(hours=72)
        snaps = generate_snapshots(
            proposal=proposal,
            trajectory=self._make_traj(),
            voting_start=start,
            voting_end=end,
            cadence_seconds=3600,
            total_eligible=60,
        )
        assert len(snaps) > 0
        # Last snap reaches voting_end.
        assert max(s.simulated_time for s in snaps) >= end - timedelta(hours=1)

    def test_seed_until_clamps_to_elapsed(self, db_session):
        proposal = SimpleNamespace(id="prop-2", options=[], num_winners=1)
        start = datetime(2026, 5, 19, 0, 0, 0)
        end = start + timedelta(hours=72)
        # Reset moment at hour 30 — only past portion should be seeded.
        reset = start + timedelta(hours=30)
        snaps = generate_snapshots(
            proposal=proposal,
            trajectory=self._make_traj(),
            voting_start=start,
            voting_end=end,
            cadence_seconds=3600,
            total_eligible=60,
            seed_until=reset,
        )
        assert len(snaps) > 0
        # No snapshot extends past reset_moment.
        assert max(s.simulated_time for s in snaps) <= reset
        # At least one snapshot near the reset boundary.
        assert max(s.simulated_time for s in snaps) >= reset - timedelta(hours=1)


class TestAllocateFillerVotesCastAtCap:
    """``cast_at_cap`` scales filler-vote count by elapsed fraction and
    clamps cast_at to the elapsed portion."""

    def _make_traj(self):
        return Trajectory(
            proposal_id="P-TEST-02",
            voting_method="binary",
            duration_hours=72,
            waypoints=[
                Waypoint(hour=0, support_pct=0.0),
                Waypoint(hour=72, support_pct=60.0),
            ],
            events=[TrajectoryEvent(0, "voting_open")],
            final_result="60-40 passed",
        )

    def _make_fillers(self, n: int):
        return [
            FillerMember(
                user_id=f"filler_test_{i:03d}",
                display_name=f"Filler {i}",
                username=f"filler_test_{i:03d}",
            )
            for i in range(n)
        ]

    def test_no_cap_casts_all_fillers(self):
        proposal = SimpleNamespace(id="prop-3", options=[])
        start = datetime(2026, 5, 19, 0, 0, 0)
        end = start + timedelta(hours=72)
        fillers = self._make_fillers(30)
        votes = allocate_filler_votes(
            proposal,
            self._make_traj(),
            fillers,
            voting_start=start,
            voting_end=end,
            cast_by_resolver=lambda uid: f"user-{uid}",
        )
        assert len(votes) == 30
        # cast_at uniformly across full window.
        assert any(v.cast_at > start + timedelta(hours=50) for v in votes), (
            "expected at least one vote in the final third of the window "
            "when no cap is set"
        )

    def test_cap_at_third_window_scales_count(self):
        proposal = SimpleNamespace(id="prop-4", options=[])
        start = datetime(2026, 5, 19, 0, 0, 0)
        end = start + timedelta(hours=72)
        cap = start + timedelta(hours=24)  # 1/3 elapsed
        fillers = self._make_fillers(30)
        votes = allocate_filler_votes(
            proposal,
            self._make_traj(),
            fillers,
            voting_start=start,
            voting_end=end,
            cast_by_resolver=lambda uid: f"user-{uid}",
            cast_at_cap=cap,
        )
        # ~1/3 of fillers cast → ~10 votes (rounding-tolerant).
        assert 8 <= len(votes) <= 12, f"expected ~10 votes, got {len(votes)}"
        # Every cast_at within [start, cap].
        for v in votes:
            assert start <= v.cast_at <= cap, (
                f"vote cast_at {v.cast_at} outside cap window "
                f"[{start}, {cap}]"
            )


# ===========================================================================
# B5 — Lumpy cumulative-vote curve
# ===========================================================================


class TestLumpyFractionVotedAt:
    """``_lumpy_fraction_voted_at`` is monotone, bounded, and deterministic."""

    def test_monotone_non_decreasing(self):
        prev = 0.0
        for hour in range(0, 73):
            val = _lumpy_fraction_voted_at(hour, 72.0, "prop-A")
            assert val >= prev - 1e-9, (
                f"non-monotone at hour {hour}: {val} < {prev}"
            )
            prev = val

    def test_bounded_zero_to_one(self):
        for hour in range(0, 73):
            val = _lumpy_fraction_voted_at(hour, 72.0, "prop-B")
            assert 0.0 <= val <= 1.0

    def test_boundary_conditions(self):
        assert _lumpy_fraction_voted_at(0.0, 72.0, "prop-C") == 0.0
        # Full elapsed = ~1.0 (within rounding from the sub-segment weights).
        assert _lumpy_fraction_voted_at(72.0, 72.0, "prop-C") == pytest.approx(
            1.0, abs=1e-9,
        )

    def test_deterministic_per_proposal_id(self):
        a1 = _lumpy_fraction_voted_at(36.0, 72.0, "prop-X")
        a2 = _lumpy_fraction_voted_at(36.0, 72.0, "prop-X")
        assert a1 == a2
        # Different proposal_id → different curve (not strictly guaranteed,
        # but extremely likely for a hash-derived RNG; treat as a smoke test).
        b = _lumpy_fraction_voted_at(36.0, 72.0, "prop-Y")
        assert a1 != b or _lumpy_fraction_voted_at(20.0, 72.0, "prop-X") != \
            _lumpy_fraction_voted_at(20.0, 72.0, "prop-Y")

    def test_not_a_perfect_linear_ramp(self):
        """The curve should deviate visibly from a uniform straight line."""
        # Sample 10 points; compare local slopes to the linear baseline.
        duration = 72.0
        samples = [
            _lumpy_fraction_voted_at(duration * i / 10, duration, "prop-Z")
            for i in range(11)
        ]
        slopes = [samples[i + 1] - samples[i] for i in range(10)]
        # A perfect linear ramp would have slopes = 0.1 each. Lumpy curve
        # should show meaningful variance.
        max_slope = max(slopes)
        min_slope = min(slopes)
        assert max_slope - min_slope > 0.02, (
            "lumpy curve unexpectedly close to linear: slopes "
            f"min={min_slope:.4f} max={max_slope:.4f}"
        )


# ===========================================================================
# F1 — Proposal list three-tier ordering
# ===========================================================================


class TestProposalListOrdering:
    """Voting → deliberation → closed primary sort, with secondary sort
    within each group."""

    def _seed_user_org(self, db: Session):
        from auth import hash_password
        user = models.User(
            username="testuser",
            display_name="Test User",
            email="testuser@example.com",
            email_verified=True,
            password_hash=hash_password("noop"),
        )
        db.add(user)
        db.flush()
        org = models.Organization(name="Test Org", slug="test-org")
        db.add(org)
        db.flush()
        return user, org

    def _make_proposal(self, db, *, org, author, status, title,
                       voting_end=None, updated_at=None, created_at=None):
        p = models.Proposal(
            title=title,
            body="",
            author_id=author.id,
            org_id=org.id,
            status=status,
            voting_end=voting_end,
        )
        if created_at is not None:
            p.created_at = created_at
        if updated_at is not None:
            p.updated_at = updated_at
        db.add(p)
        db.flush()
        return p

    def test_status_groups_ordered_voting_delib_closed(
        self, db_session: Session,
    ):
        user, org = self._seed_user_org(db_session)
        base = datetime(2026, 5, 19, 12, 0, 0)
        # One of each major status group.
        p_closed = self._make_proposal(
            db_session, org=org, author=user, status="passed",
            title="Closed proposal",
            updated_at=base - timedelta(days=1),
            created_at=base - timedelta(days=10),
        )
        p_delib = self._make_proposal(
            db_session, org=org, author=user, status="deliberation",
            title="Delib proposal",
            created_at=base - timedelta(days=2),
        )
        p_vote = self._make_proposal(
            db_session, org=org, author=user, status="voting",
            title="Voting proposal",
            voting_end=base + timedelta(days=2),
            created_at=base - timedelta(days=3),
        )
        db_session.commit()

        from routes.proposals import _proposal_list_ordering
        ordered = (
            db_session.query(models.Proposal)
            .filter(models.Proposal.org_id == org.id)
            .order_by(*_proposal_list_ordering())
            .all()
        )
        assert [p.id for p in ordered] == [
            p_vote.id, p_delib.id, p_closed.id,
        ]

    def test_voting_group_sorted_by_closing_soonest(
        self, db_session: Session,
    ):
        user, org = self._seed_user_org(db_session)
        base = datetime(2026, 5, 19, 12, 0, 0)
        p_late = self._make_proposal(
            db_session, org=org, author=user, status="voting",
            title="Voting late", voting_end=base + timedelta(days=5),
        )
        p_soon = self._make_proposal(
            db_session, org=org, author=user, status="voting",
            title="Voting soon", voting_end=base + timedelta(hours=6),
        )
        db_session.commit()

        from routes.proposals import _proposal_list_ordering
        ordered = (
            db_session.query(models.Proposal)
            .filter(models.Proposal.org_id == org.id)
            .order_by(*_proposal_list_ordering())
            .all()
        )
        assert [p.id for p in ordered] == [p_soon.id, p_late.id]


# ===========================================================================
# N1 — Notification defaults
# ===========================================================================


class TestBuildPresetPreferenceRows:
    """The helper emits only ``enabled=True`` rows."""

    def test_low_preset_emits_only_enabled_rows(self):
        rows = build_preset_preference_rows("user-1", "low")
        assert len(rows) > 0
        assert all(r.enabled is True for r in rows)
        assert all(r.user_id == "user-1" for r in rows)
        assert all(r.event_type for r in rows)
        assert all(r.channel for r in rows)

    def test_unknown_preset_raises(self):
        with pytest.raises(ValueError):
            build_preset_preference_rows("user-2", "ultra")

    def test_presets_differ(self):
        low_keys = {
            (r.event_type, r.channel)
            for r in build_preset_preference_rows("u", "low")
        }
        high_keys = {
            (r.event_type, r.channel)
            for r in build_preset_preference_rows("u", "high")
        }
        # High preset enables strictly more channel toggles than low.
        # (Not a subset: low enables ``email_weekly`` on critical events
        # while high routes critical to ``email_immediate``, so the
        # specific channel choices differ even within an event.)
        assert len(high_keys) > len(low_keys)
        assert low_keys != high_keys


class TestRegisterStampsLowPreset:
    """``POST /api/auth/register`` stamps the "low" preset on the new user."""

    def test_new_user_has_low_preset_rows(
        self, db_session: Session, client: TestClient,
    ):
        resp = client.post(
            "/api/auth/register",
            json={
                "username": "newuser",
                "display_name": "New User",
                "email": "newuser@example.com",
                "password": "noopnoop123",
            },
        )
        assert resp.status_code == 201, resp.text
        user = db_session.query(models.User).filter_by(
            username="newuser",
        ).first()
        assert user is not None

        rows = (
            db_session.query(models.NotificationPreference)
            .filter(models.NotificationPreference.user_id == user.id)
            .all()
        )
        assert len(rows) > 0
        # Every stamped row corresponds to a (event, channel) the "low"
        # preset enables.
        stamped = {(r.event_type, r.channel): r.enabled for r in rows}
        from notification_events import EVENT_REGISTRY
        expected_keys: set[tuple[str, str]] = set()
        for ev in EVENT_REGISTRY:
            if ev.signal_level == "always_on":
                continue
            channels = PRESET_STAMP_RULES["low"].get(ev.signal_level, {})
            for ch, enabled in channels.items():
                if enabled:
                    expected_keys.add((ev.key, ch))
        assert set(stamped.keys()) == expected_keys, (
            f"stamped keys {sorted(stamped.keys())} != expected "
            f"{sorted(expected_keys)}"
        )


class TestSeedPipelineStampsBibleMemberPreset:
    """Phase 31 N1.b — a Cedar Hollow member's prefs reflect their
    bible-declared notification_preset after seed."""

    def test_janet_gets_high_preset(self, db_session: Session):
        seed_org_from_bible(
            db_session,
            HOA_BIBLE,
            now=datetime(2026, 5, 19, 12, 0, 0),
        )
        db_session.commit()
        janet = db_session.query(models.User).filter_by(
            username="janet_reilly",
        ).first()
        assert janet is not None
        rows = (
            db_session.query(models.NotificationPreference)
            .filter(models.NotificationPreference.user_id == janet.id)
            .all()
        )
        assert len(rows) > 0
        from notification_events import EVENT_REGISTRY
        expected_keys: set[tuple[str, str]] = set()
        for ev in EVENT_REGISTRY:
            if ev.signal_level == "always_on":
                continue
            channels = PRESET_STAMP_RULES["high"].get(ev.signal_level, {})
            for ch, enabled in channels.items():
                if enabled:
                    expected_keys.add((ev.key, ch))
        stamped = {(r.event_type, r.channel) for r in rows}
        assert stamped == expected_keys, (
            "Janet's prefs don't match the 'high' preset; bible declares "
            "her notification_preset='high' but seed stamped something else"
        )
