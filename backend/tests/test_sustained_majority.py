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
    support_ever_established,
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
    """Direct tests of `is_above_floor` — these always pass
    `support_was_established=True` since they target the post-establishment
    branch. Pre-establishment behavior is covered separately in
    `TestFloorActivation`.
    """
    def test_above_floor(self):
        snap = BinarySnapshotPoint(
            simulated_time=_at(0), yes=60, no=40, abstain=0, total_eligible=100,
        )
        assert is_above_floor(snap, _config(floor=0.50), True) is True

    def test_below_floor(self):
        snap = BinarySnapshotPoint(
            simulated_time=_at(0), yes=40, no=60, abstain=0, total_eligible=100,
        )
        assert is_above_floor(snap, _config(floor=0.50), True) is False

    def test_at_floor_exactly(self):
        snap = BinarySnapshotPoint(
            simulated_time=_at(0), yes=50, no=50, abstain=0, total_eligible=100,
        )
        # >= floor counts as above (the floor is a "drop below" detector).
        assert is_above_floor(snap, _config(floor=0.50), True) is True

    def test_zero_ballots_treated_as_above(self):
        snap = BinarySnapshotPoint(
            simulated_time=_at(0), yes=0, no=0, abstain=0, total_eligible=100,
        )
        assert is_above_floor(snap, _config(floor=0.50), True) is True

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
        # 0.30 is below 0.45 floor → not above (assuming support was previously
        # established — see TestFloorActivation for the pre-establishment case).
        assert is_above_floor(snap, _config(floor=0.45), True) is False


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
        # Single snapshot that itself establishes support (0.6 >= 0.5
        # threshold) and is above floor — no fire.
        decision = evaluate_binary([snap], _config(floor=0.50))
        assert decision.should_fire is False
        assert decision.mode is None

    def test_fires_when_below_floor_after_establishment(self):
        """Establish support first, then drop below floor → breach fires.

        Updated for Phase 9.8 C1: the prior version of this test passed a
        single below-floor snapshot and expected an immediate breach. That
        was the bug — without prior establishment the floor must not fire.
        Updated to seed an establishing snapshot before the breach snapshot.
        """
        established = BinarySnapshotPoint(
            simulated_time=_at(0), yes=60, no=40, abstain=0, total_eligible=100,
        )
        breach = BinarySnapshotPoint(
            simulated_time=_at(60), yes=30, no=70, abstain=0, total_eligible=100,
        )
        decision = evaluate_binary(
            [established, breach], _config(floor=0.45, failure_mode="fail"),
        )
        assert decision.should_fire is True
        assert decision.mode == "fail"
        assert "below floor" in decision.reason
        assert decision.breach_sample["yes"] == 30
        assert decision.breach_sample["floor"] == 0.45

    def test_no_fire_when_below_floor_but_never_established(self):
        """Single early no-vote with no prior support → no breach.

        This is the canonical bug Z surfaced: under the old logic
        `evaluate_binary` would fire on this single below-floor snapshot.
        After C1 it must not — support has never been established.
        """
        snap = BinarySnapshotPoint(
            simulated_time=_at(0), yes=0, no=1, abstain=0, total_eligible=100,
        )
        decision = evaluate_binary([snap], _config(floor=0.45))
        assert decision.should_fire is False
        assert decision.mode is None

    def test_no_fire_with_empty_snapshots(self):
        """Defensive: an empty snapshot list returns no-fire."""
        decision = evaluate_binary([], _config(floor=0.45))
        assert decision.should_fire is False


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
    """Top-level dispatch tests.

    Updated for Phase 9.8 C1: each binary-failure-mode test now seeds an
    establishing snapshot (support >= threshold) before the breach snapshot
    so the new floor-activation gate allows the breach to fire. The prior
    versions passed a single below-floor snapshot and were exercising the
    bug (immediate fire on first no-vote).
    """
    def setup_method(self):
        self.start = _at(0)
        self.end = _at(1000)

    def _established_then_breach(self, breach_yes: int, breach_no: int):
        """Helper: 60/40 establishing snapshot, then a breach snapshot."""
        return [
            BinarySnapshotPoint(
                simulated_time=_at(50), yes=60, no=40, abstain=0,
                total_eligible=100,
            ),
            BinarySnapshotPoint(
                simulated_time=_at(100), yes=breach_yes, no=breach_no,
                abstain=0, total_eligible=100,
            ),
        ]

    def test_binary_below_floor_fires_fail(self):
        decision = should_trigger_failure(
            voting_method="binary",
            snapshots=self._established_then_breach(30, 70),
            config=_config(floor=0.45, failure_mode="fail"),
            voting_start=self.start,
            voting_end=self.end,
            now=_at(500),
        )
        assert decision.should_fire is True
        assert decision.mode == "fail"

    def test_extend_fires_first_time(self):
        decision = should_trigger_failure(
            voting_method="binary",
            snapshots=self._established_then_breach(30, 70),
            config=_config(floor=0.45, failure_mode="extend"),
            voting_start=self.start,
            voting_end=self.end,
            now=_at(100),
            extension_count=0,
        )
        assert decision.should_fire is True
        assert decision.mode == "extend"

    def test_extend_promotes_to_fail_on_second_breach(self):
        decision = should_trigger_failure(
            voting_method="binary",
            snapshots=self._established_then_breach(30, 70),
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
        decision = should_trigger_failure(
            voting_method="binary",
            snapshots=self._established_then_breach(20, 80),
            config=_config(floor=0.45, failure_mode="escalate"),
            voting_start=self.start,
            voting_end=self.end,
            now=_at(100),
        )
        assert decision.should_fire is True
        assert decision.mode == "escalate"

    def test_binary_below_floor_no_fire_without_establishment(self):
        """Phase 9.8 C1 regression: a single early no-vote (no prior
        establishment) must NOT fire even at the top-level dispatch."""
        snap = BinarySnapshotPoint(
            simulated_time=_at(50), yes=0, no=1, abstain=0, total_eligible=100,
        )
        decision = should_trigger_failure(
            voting_method="binary",
            snapshots=[snap],
            config=_config(floor=0.45, failure_mode="fail"),
            voting_start=self.start,
            voting_end=self.end,
            now=_at(50),
        )
        assert decision.should_fire is False

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
# support_ever_established + floor-activation gate (Phase 9.8 C1)
# ---------------------------------------------------------------------------

class TestSupportEverEstablished:
    """The pure helper that gates `is_above_floor`."""

    def test_empty_snapshots(self):
        assert support_ever_established([], _config()) is False

    def test_zero_votes_only(self):
        snaps = [
            BinarySnapshotPoint(
                simulated_time=_at(0), yes=0, no=0, abstain=0, total_eligible=100,
            ),
        ]
        assert support_ever_established(snaps, _config()) is False

    def test_single_snapshot_above_threshold(self):
        snaps = [
            BinarySnapshotPoint(
                simulated_time=_at(0), yes=60, no=40, abstain=0, total_eligible=100,
            ),
        ]
        assert support_ever_established(snaps, _config(threshold=0.5)) is True

    def test_at_exact_threshold_counts_as_established(self):
        # >= comparison — exactly the threshold establishes support.
        snaps = [
            BinarySnapshotPoint(
                simulated_time=_at(0), yes=50, no=50, abstain=0, total_eligible=100,
            ),
        ]
        assert support_ever_established(snaps, _config(threshold=0.5)) is True

    def test_just_below_threshold_not_established(self):
        # 0.499 < 0.5 → not established.
        snaps = [
            BinarySnapshotPoint(
                simulated_time=_at(0), yes=499, no=501, abstain=0, total_eligible=2000,
            ),
        ]
        assert support_ever_established(snaps, _config(threshold=0.5)) is False

    def test_one_high_snapshot_then_drop_still_established(self):
        snaps = [
            BinarySnapshotPoint(
                simulated_time=_at(0), yes=70, no=30, abstain=0, total_eligible=100,
            ),
            BinarySnapshotPoint(
                simulated_time=_at(60), yes=20, no=80, abstain=0, total_eligible=100,
            ),
        ]
        assert support_ever_established(snaps, _config(threshold=0.5)) is True


class TestFloorActivation:
    """`is_above_floor` no longer fires before support has been established.

    These tests target the bug Z surfaced (Phase 9.8 C1): under the prior
    behavior a single early no-vote would breach the floor immediately,
    failing the proposal before anyone had a chance to vote yes. The fix
    routes through `support_was_established` so the floor only activates
    after support has crossed the threshold at least once.
    """

    def _no_vote(self, t: int = 0) -> BinarySnapshotPoint:
        return BinarySnapshotPoint(
            simulated_time=_at(t), yes=0, no=1, abstain=0, total_eligible=100,
        )

    def _yes_vote_majority(self, yes: int, no: int, t: int = 0) -> BinarySnapshotPoint:
        return BinarySnapshotPoint(
            simulated_time=_at(t), yes=yes, no=no, abstain=0, total_eligible=100,
        )

    def test_floor_inactive_before_support_established(self):
        """Single early no-vote, support never reaches threshold → no breach."""
        snap = self._no_vote()
        # Even though support_fraction (0.0) is below floor (0.45), the floor
        # cannot fire because support has never been established.
        assert is_above_floor(snap, _config(floor=0.45), False) is True

    def test_floor_active_after_support_crosses_threshold(self):
        """Support hits 0.5 once, then drops below floor → breach detected."""
        # Drop snapshot: 30/70 → support 0.3, below floor 0.45.
        drop = self._yes_vote_majority(yes=30, no=70, t=60)
        # The caller (`evaluate_binary`) will compute established=True from
        # the prior 50/50 snapshot in the list — here we model that by
        # passing established=True directly.
        assert is_above_floor(drop, _config(floor=0.45), True) is False

    def test_support_established_at_exact_threshold(self):
        """Support exactly 0.5 → established (>= comparison)."""
        snaps = [
            self._yes_vote_majority(yes=50, no=50, t=0),
            BinarySnapshotPoint(
                simulated_time=_at(60), yes=20, no=80, abstain=0, total_eligible=100,
            ),
        ]
        config = _config(threshold=0.5, floor=0.45, failure_mode="fail")
        assert support_ever_established(snaps, config) is True
        decision = evaluate_binary(snaps, config)
        # Established + drop to 0.2 below floor 0.45 → fires.
        assert decision.should_fire is True
        assert decision.mode == "fail"

    def test_support_not_established_just_below_threshold(self):
        """Support 0.499 max → not established → no breach when it drops."""
        snaps = [
            BinarySnapshotPoint(
                simulated_time=_at(0), yes=499, no=501, abstain=0,
                total_eligible=2000,
            ),
            BinarySnapshotPoint(
                simulated_time=_at(60), yes=100, no=900, abstain=0,
                total_eligible=2000,
            ),
        ]
        config = _config(threshold=0.5, floor=0.45)
        assert support_ever_established(snaps, config) is False
        decision = evaluate_binary(snaps, config)
        assert decision.should_fire is False

    def test_breach_after_establishment_then_drop(self):
        """Establish 0.7, drop to 0.3 → breach fires."""
        snaps = [
            BinarySnapshotPoint(
                simulated_time=_at(0), yes=70, no=30, abstain=0, total_eligible=100,
            ),
            BinarySnapshotPoint(
                simulated_time=_at(60), yes=30, no=70, abstain=0, total_eligible=100,
            ),
        ]
        config = _config(threshold=0.5, floor=0.45, failure_mode="fail")
        decision = evaluate_binary(snaps, config)
        assert decision.should_fire is True
        assert decision.mode == "fail"
        assert decision.breach_sample["yes"] == 30
        assert decision.breach_sample["no"] == 70

    def test_zero_votes_still_no_breach(self):
        """Regression on the existing zero-votes case: zero ballots = no breach
        regardless of establishment state."""
        snap = BinarySnapshotPoint(
            simulated_time=_at(0), yes=0, no=0, abstain=0, total_eligible=100,
        )
        # Pre-establishment: no breach.
        assert is_above_floor(snap, _config(floor=0.45), False) is True
        # Post-establishment: still no breach (zero ballots short-circuits).
        assert is_above_floor(snap, _config(floor=0.45), True) is True
        # And the empty-history evaluate_binary also returns no-fire.
        decision = evaluate_binary([snap], _config(floor=0.45))
        assert decision.should_fire is False

    @pytest.mark.parametrize("failure_mode", ["fail", "extend", "escalate"])
    def test_existing_failure_modes_unchanged_after_establishment(
        self, failure_mode,
    ):
        """Each failure mode still fires correctly once support has been
        established and then dropped — the activation gate doesn't suppress
        legitimate breaches."""
        snaps = [
            BinarySnapshotPoint(
                simulated_time=_at(0), yes=70, no=30, abstain=0, total_eligible=100,
            ),
            BinarySnapshotPoint(
                simulated_time=_at(60), yes=20, no=80, abstain=0, total_eligible=100,
            ),
        ]
        decision = should_trigger_failure(
            voting_method="binary",
            snapshots=snaps,
            config=_config(floor=0.45, failure_mode=failure_mode),
            voting_start=_at(0),
            voting_end=_at(1000),
            now=_at(60),
            extension_count=0,
        )
        assert decision.should_fire is True
        assert decision.mode == failure_mode

    def test_long_no_vote_stretch_then_establishment_then_drop(self):
        """Edge case from spec: long stretch of no-votes early, then a flood
        of yes-votes establishes support, then a flood of no-votes drops it
        → breach fires only after the second flood."""
        snaps = [
            # Early no-votes — would have fired under the old logic.
            BinarySnapshotPoint(
                simulated_time=_at(0), yes=0, no=3, abstain=0, total_eligible=100,
            ),
            BinarySnapshotPoint(
                simulated_time=_at(30), yes=0, no=5, abstain=0, total_eligible=100,
            ),
            # Yes-vote flood establishes support.
            BinarySnapshotPoint(
                simulated_time=_at(60), yes=60, no=10, abstain=0, total_eligible=100,
            ),
            # No-vote flood drops support below floor.
            BinarySnapshotPoint(
                simulated_time=_at(90), yes=15, no=85, abstain=0, total_eligible=100,
            ),
        ]
        config = _config(floor=0.45, failure_mode="fail")
        # Establishment: yes (the 60/10 snapshot crosses 0.5).
        assert support_ever_established(snaps, config) is True
        # The latest snapshot is below floor → fires.
        decision = evaluate_binary(snaps, config)
        assert decision.should_fire is True

        # If we truncate to the pre-establishment portion only, no fire.
        decision_pre = evaluate_binary(snaps[:2], config)
        assert decision_pre.should_fire is False


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
