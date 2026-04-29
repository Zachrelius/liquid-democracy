"""
Phase 8 — pure-function tests for sustained-majority evaluation.

These tests cover `sustained_majority.py` only. No DB, no fixtures, no I/O.
The service layer (DB-touching) and worker (time-dependent) live in their
own test modules.
"""

from datetime import datetime, timedelta, timezone

import pytest

from sustained_majority import (
    BinarySnapshotPoint,
    DEFAULTS,
    FLOOR_APPROACH_DELTA,
    MultiOptionSnapshotPoint,
    STABLE_RESULT_FRACTION,
    SustainedMajorityConfig,
    evaluate_binary,
    evaluate_multi_option,
    extension_window_for,
    get_sustained_majority_config,
    in_stable_result_window,
    is_above_floor,
    is_approaching_floor,
    is_proposal_sustained_majority_active,
    should_trigger_failure,
    winner_stable,
)


def _config(**kwargs) -> SustainedMajorityConfig:
    base = {
        "enabled_default": False,
        "per_proposal_override": True,
        "threshold": 0.5,
        "floor": 0.45,
        "failure_mode": "fail",
    }
    base.update(kwargs)
    return SustainedMajorityConfig(**base)


def _at(seconds_offset: int) -> datetime:
    base = datetime(2026, 4, 28, 12, 0, 0)
    return base + timedelta(seconds=seconds_offset)


# ---------------------------------------------------------------------------
# Config accessor
# ---------------------------------------------------------------------------

class TestGetSustainedMajorityConfig:
    def test_defaults_when_settings_empty(self):
        config = get_sustained_majority_config({})
        assert config.enabled_default is False
        assert config.per_proposal_override is True
        assert config.threshold == 0.5
        assert config.floor == 0.45
        assert config.failure_mode == "fail"
        assert config.is_default

    def test_partial_override(self):
        config = get_sustained_majority_config({
            "sustained_majority_failure_mode": "extend",
            "sustained_majority_floor": 0.40,
        })
        assert config.failure_mode == "extend"
        assert config.floor == 0.40
        # untouched keys still take defaults
        assert config.threshold == 0.5
        assert not config.is_default

    def test_corrupt_failure_mode_falls_back_to_fail(self):
        """Defensive: bad config doesn't blow up the worker."""
        config = get_sustained_majority_config({
            "sustained_majority_failure_mode": "bogus",
        })
        assert config.failure_mode == "fail"

    def test_accepts_organization_object(self):
        class _Org:
            settings = {"sustained_majority_threshold": 0.6}
        config = get_sustained_majority_config(_Org())
        assert config.threshold == 0.6


# ---------------------------------------------------------------------------
# Per-proposal override resolution
# ---------------------------------------------------------------------------

class TestPerProposalOverride:
    def test_null_inherits_org_default_off(self):
        assert is_proposal_sustained_majority_active(None, False) is False

    def test_null_inherits_org_default_on(self):
        assert is_proposal_sustained_majority_active(None, True) is True

    def test_true_overrides_org_off(self):
        assert is_proposal_sustained_majority_active(True, False) is True

    def test_false_overrides_org_on(self):
        assert is_proposal_sustained_majority_active(False, True) is False


# ---------------------------------------------------------------------------
# is_above_floor
# ---------------------------------------------------------------------------

class TestFloor:
    def test_above_floor(self):
        snap = BinarySnapshotPoint(
            simulated_time=_at(0), yes=60, no=40, abstain=0, total_eligible=100,
        )
        assert is_above_floor(snap, _config(floor=0.50)) is True

    def test_below_floor(self):
        snap = BinarySnapshotPoint(
            simulated_time=_at(0), yes=40, no=60, abstain=0, total_eligible=100,
        )
        assert is_above_floor(snap, _config(floor=0.50)) is False

    def test_at_floor_exactly(self):
        snap = BinarySnapshotPoint(
            simulated_time=_at(0), yes=50, no=50, abstain=0, total_eligible=100,
        )
        # >= floor counts as above (the floor is a "drop below" detector).
        assert is_above_floor(snap, _config(floor=0.50)) is True

    def test_zero_ballots_treated_as_above(self):
        snap = BinarySnapshotPoint(
            simulated_time=_at(0), yes=0, no=0, abstain=0, total_eligible=100,
        )
        assert is_above_floor(snap, _config(floor=0.50)) is True

    def test_support_fraction_matches_existing_yes_pct_semantics(self):
        # support_fraction uses yes / (yes+no+abstain) to stay consistent with
        # the existing ProposalTally.yes_pct (used by `pass_threshold` checks).
        # 30 yes / 30 no / 40 abstain → support = 30 / 100 = 0.30. A high
        # abstain count thus drags effective support down — same way it
        # affects the pass threshold today.
        snap = BinarySnapshotPoint(
            simulated_time=_at(0), yes=30, no=30, abstain=40, total_eligible=100,
        )
        assert pytest.approx(snap.support_fraction) == 0.30
        # 0.30 is below 0.45 floor → not above
        assert is_above_floor(snap, _config(floor=0.45)) is False


# ---------------------------------------------------------------------------
# winner_stable
# ---------------------------------------------------------------------------

class TestWinnerStable:
    def _snap(self, winners, t=0):
        return MultiOptionSnapshotPoint(
            simulated_time=_at(t),
            winners=tuple(winners),
            total_ballots_cast=10,
            total_eligible=20,
        )

    def test_same_winner(self):
        assert winner_stable(self._snap(["a"]), self._snap(["a"], t=1)) is True

    def test_different_winner(self):
        assert winner_stable(self._snap(["a"]), self._snap(["b"], t=1)) is False

    def test_set_equality_order_insensitive(self):
        assert winner_stable(
            self._snap(["a", "b"]), self._snap(["b", "a"], t=1),
        ) is True

    def test_subset_change_counts(self):
        # Ties shrinking from {a,b} to {a} is a winner change.
        assert winner_stable(
            self._snap(["a", "b"]), self._snap(["a"], t=1),
        ) is False


# ---------------------------------------------------------------------------
# in_stable_result_window
# ---------------------------------------------------------------------------

class TestStableResultWindow:
    def setup_method(self):
        self.start = _at(0)
        self.end = _at(1000)  # 1000-second window

    def test_outside_window_returns_false(self):
        # 50% elapsed — outside the final 25%
        assert in_stable_result_window(_at(500), self.start, self.end) is False

    def test_inside_final_25_percent(self):
        # 80% elapsed — inside the final 25%
        assert in_stable_result_window(_at(800), self.start, self.end) is True

    def test_boundary_at_75_percent(self):
        # Exactly at the boundary (1 - 0.25 = 0.75)
        assert in_stable_result_window(_at(750), self.start, self.end) is True

    def test_just_before_boundary(self):
        assert in_stable_result_window(_at(749), self.start, self.end) is False

    def test_zero_duration_returns_false(self):
        assert in_stable_result_window(self.start, self.start, self.start) is False


# ---------------------------------------------------------------------------
# evaluate_binary
# ---------------------------------------------------------------------------

class TestEvaluateBinary:
    def test_no_fire_when_above_floor(self):
        snap = BinarySnapshotPoint(
            simulated_time=_at(0), yes=60, no=40, abstain=0, total_eligible=100,
        )
        decision = evaluate_binary(snap, _config(floor=0.50))
        assert decision.should_fire is False
        assert decision.mode is None

    def test_fires_when_below_floor(self):
        snap = BinarySnapshotPoint(
            simulated_time=_at(0), yes=30, no=70, abstain=0, total_eligible=100,
        )
        decision = evaluate_binary(snap, _config(floor=0.45, failure_mode="fail"))
        assert decision.should_fire is True
        assert decision.mode == "fail"
        assert "below floor" in decision.reason
        assert decision.breach_sample["yes"] == 30
        assert decision.breach_sample["floor"] == 0.45


# ---------------------------------------------------------------------------
# evaluate_multi_option
# ---------------------------------------------------------------------------

class TestEvaluateMultiOption:
    def setup_method(self):
        self.start = _at(0)
        self.end = _at(1000)

    def _snap(self, winners, t):
        return MultiOptionSnapshotPoint(
            simulated_time=_at(t),
            winners=tuple(winners),
            total_ballots_cast=10,
            total_eligible=20,
        )

    def test_outside_window_no_fire(self):
        latest = self._snap(["b"], t=500)  # 50% elapsed
        previous = self._snap(["a"], t=400)
        decision = evaluate_multi_option(
            latest, previous, _config(), self.start, self.end, _at(500),
        )
        assert decision.should_fire is False

    def test_inside_window_no_previous_no_fire(self):
        latest = self._snap(["a"], t=800)
        decision = evaluate_multi_option(
            latest, None, _config(), self.start, self.end, _at(800),
        )
        assert decision.should_fire is False

    def test_inside_window_winner_change_fires(self):
        latest = self._snap(["b"], t=900)
        previous = self._snap(["a"], t=800)
        decision = evaluate_multi_option(
            latest, previous, _config(failure_mode="escalate"),
            self.start, self.end, _at(900),
        )
        assert decision.should_fire is True
        assert decision.mode == "escalate"
        assert "Winner changed" in decision.reason
        assert decision.breach_sample["previous_winners"] == ["a"]
        assert decision.breach_sample["current_winners"] == ["b"]

    def test_inside_window_winner_stable_no_fire(self):
        latest = self._snap(["a"], t=900)
        previous = self._snap(["a"], t=800)
        decision = evaluate_multi_option(
            latest, previous, _config(),
            self.start, self.end, _at(900),
        )
        assert decision.should_fire is False

    def test_boundary_change_at_exactly_25_percent_remaining(self):
        # Right at the boundary (75% elapsed): the spec requires the window
        # to be open at this instant. A change here should fire.
        latest = self._snap(["b"], t=750)
        previous = self._snap(["a"], t=700)
        decision = evaluate_multi_option(
            latest, previous, _config(),
            self.start, self.end, _at(750),
        )
        assert decision.should_fire is True


# ---------------------------------------------------------------------------
# should_trigger_failure  (top-level dispatch + extend bookkeeping)
# ---------------------------------------------------------------------------

class TestShouldTriggerFailure:
    def setup_method(self):
        self.start = _at(0)
        self.end = _at(1000)

    def test_binary_below_floor_fires_fail(self):
        snap = BinarySnapshotPoint(
            simulated_time=_at(500), yes=30, no=70, abstain=0, total_eligible=100,
        )
        decision = should_trigger_failure(
            voting_method="binary",
            snapshots=[snap],
            config=_config(floor=0.45, failure_mode="fail"),
            voting_start=self.start,
            voting_end=self.end,
            now=_at(500),
        )
        assert decision.should_fire is True
        assert decision.mode == "fail"

    def test_extend_fires_first_time(self):
        snap = BinarySnapshotPoint(
            simulated_time=_at(100), yes=30, no=70, abstain=0, total_eligible=100,
        )
        decision = should_trigger_failure(
            voting_method="binary",
            snapshots=[snap],
            config=_config(floor=0.45, failure_mode="extend"),
            voting_start=self.start,
            voting_end=self.end,
            now=_at(100),
            extension_count=0,
        )
        assert decision.should_fire is True
        assert decision.mode == "extend"

    def test_extend_promotes_to_fail_on_second_breach(self):
        snap = BinarySnapshotPoint(
            simulated_time=_at(100), yes=30, no=70, abstain=0, total_eligible=100,
        )
        decision = should_trigger_failure(
            voting_method="binary",
            snapshots=[snap],
            config=_config(floor=0.45, failure_mode="extend"),
            voting_start=self.start,
            voting_end=self.end,
            now=_at(100),
            extension_count=1,
        )
        assert decision.should_fire is True
        assert decision.mode == "fail"  # promoted
        assert "second breach" in decision.reason

    def test_escalate_mode_passes_through(self):
        snap = BinarySnapshotPoint(
            simulated_time=_at(100), yes=20, no=80, abstain=0, total_eligible=100,
        )
        decision = should_trigger_failure(
            voting_method="binary",
            snapshots=[snap],
            config=_config(floor=0.45, failure_mode="escalate"),
            voting_start=self.start,
            voting_end=self.end,
            now=_at(100),
        )
        assert decision.should_fire is True
        assert decision.mode == "escalate"

    def test_multi_option_dispatches_to_winner_check(self):
        s1 = MultiOptionSnapshotPoint(_at(800), ("a",), 10, 20)
        s2 = MultiOptionSnapshotPoint(_at(900), ("b",), 10, 20)
        decision = should_trigger_failure(
            voting_method="approval",
            snapshots=[s1, s2],
            config=_config(failure_mode="fail"),
            voting_start=self.start,
            voting_end=self.end,
            now=_at(900),
        )
        assert decision.should_fire is True
        assert decision.mode == "fail"

    def test_no_snapshots_no_fire(self):
        decision = should_trigger_failure(
            voting_method="binary",
            snapshots=[],
            config=_config(),
            voting_start=self.start,
            voting_end=self.end,
            now=_at(500),
        )
        assert decision.should_fire is False


# ---------------------------------------------------------------------------
# Floor-approach detection
# ---------------------------------------------------------------------------

class TestFloorApproach:
    def test_within_delta_above_floor(self):
        # 0.48 with floor=0.45, delta=0.05 → 0.48 <= 0.50 ✓
        snap = BinarySnapshotPoint(
            simulated_time=_at(0), yes=48, no=52, abstain=0, total_eligible=100,
        )
        assert is_approaching_floor(snap, _config(floor=0.45)) is True

    def test_clearly_above_floor(self):
        snap = BinarySnapshotPoint(
            simulated_time=_at(0), yes=70, no=30, abstain=0, total_eligible=100,
        )
        assert is_approaching_floor(snap, _config(floor=0.45)) is False

    def test_zero_ballots_not_approaching(self):
        snap = BinarySnapshotPoint(
            simulated_time=_at(0), yes=0, no=0, abstain=0, total_eligible=100,
        )
        assert is_approaching_floor(snap, _config(floor=0.45)) is False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def test_extension_window_returns_original_duration():
    start = _at(0)
    end = _at(86400)  # 1 day
    assert extension_window_for(start, end) == timedelta(days=1)
