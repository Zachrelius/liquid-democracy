"""
Phase 8 / Phase 20 — pure-function tests for Stable Result Required evaluation.

These tests cover ``sustained_majority.py`` only. No DB, no fixtures, no I/O.
The service layer (DB-touching) and worker (time-dependent) live in their
own test modules.

Phase 20 redesign: the binary "floor" mechanic is gone. The unified mechanic
is "result stability across the closing portion of the voting window". Tests
cover the new pure helpers (binary_snapshot_is_stable, winner_set_overlaps,
evaluate_original_window_stability, evaluate_extension_stability) and the
config accessor (get_stable_result_config).
"""

from datetime import datetime, timedelta

import pytest

from sustained_majority import (
    BinarySnapshotPoint,
    DEFAULTS,
    DestabilizationDecision,
    MultiOptionSnapshotPoint,
    StableResultConfig,
    binary_snapshot_is_stable,
    evaluate_extension_stability,
    evaluate_original_window_stability,
    get_stable_result_config,
    in_stable_result_window,
    is_proposal_stable_result_active,
    winner_set_overlaps,
)


def _config(**kwargs) -> StableResultConfig:
    base = {
        "enabled_default": False,
        "per_proposal_override": True,
        "stable_window_fraction": 0.25,
        "max_extension_fraction": 0.25,
    }
    base.update(kwargs)
    return StableResultConfig(**base)


def _at(seconds_offset: int) -> datetime:
    base = datetime(2026, 4, 28, 12, 0, 0)
    return base + timedelta(seconds=seconds_offset)


# ---------------------------------------------------------------------------
# Config accessor
# ---------------------------------------------------------------------------

class TestGetStableResultConfig:
    def test_defaults_when_settings_empty(self):
        config = get_stable_result_config({})
        assert config.enabled_default is False
        assert config.per_proposal_override is True
        assert config.stable_window_fraction == 0.25
        assert config.max_extension_fraction == 0.25
        assert config.is_default

    def test_partial_override(self):
        config = get_stable_result_config({
            "stable_window_fraction": 0.10,
            "max_extension_fraction": 0.50,
        })
        assert config.stable_window_fraction == 0.10
        assert config.max_extension_fraction == 0.50
        # untouched keys still take defaults
        assert config.enabled_default is False
        assert not config.is_default

    def test_old_sustained_majority_keys_silently_ignored(self):
        """D13: legacy keys in settings JSON must not raise; just ignored."""
        config = get_stable_result_config({
            "sustained_majority_floor": 0.45,
            "sustained_majority_failure_mode": "extend",
            "sustained_majority_threshold": 0.6,
            "sustained_majority_enabled_default": True,  # ignored
        })
        # No error — and defaults applied (legacy enabled_default ignored).
        assert config.enabled_default is False
        assert config.is_default

    def test_legacy_keys_alongside_new_keys_uses_new(self):
        config = get_stable_result_config({
            "sustained_majority_enabled_default": True,  # ignored
            "stable_result_enabled_default": True,       # used
        })
        assert config.enabled_default is True

    def test_clamps_stable_window_fraction(self):
        # Below floor.
        c1 = get_stable_result_config({"stable_window_fraction": 0.01})
        assert c1.stable_window_fraction == 0.05
        # Above ceiling.
        c2 = get_stable_result_config({"stable_window_fraction": 0.99})
        assert c2.stable_window_fraction == 0.50

    def test_clamps_max_extension_fraction(self):
        c1 = get_stable_result_config({"max_extension_fraction": -0.5})
        assert c1.max_extension_fraction == 0.0
        c2 = get_stable_result_config({"max_extension_fraction": 1.5})
        assert c2.max_extension_fraction == 1.0

    def test_accepts_organization_object(self):
        class _Org:
            settings = {"stable_window_fraction": 0.10}
            parent_org_id = None
        config = get_stable_result_config(_Org())
        assert config.stable_window_fraction == 0.10


# ---------------------------------------------------------------------------
# Per-proposal override resolution
# ---------------------------------------------------------------------------

class TestPerProposalOverride:
    def test_null_inherits_org_default_off(self):
        assert is_proposal_stable_result_active(None, False) is False

    def test_null_inherits_org_default_on(self):
        assert is_proposal_stable_result_active(None, True) is True

    def test_explicit_true_overrides_org_default_off(self):
        assert is_proposal_stable_result_active(True, False) is True

    def test_explicit_false_overrides_org_default_on(self):
        assert is_proposal_stable_result_active(False, True) is False


# ---------------------------------------------------------------------------
# Binary snapshot stability
# ---------------------------------------------------------------------------

class TestBinarySnapshotIsStable:
    def _snap(self, yes: int, no: int, abstain: int = 0) -> BinarySnapshotPoint:
        return BinarySnapshotPoint(
            simulated_time=_at(0),
            yes=yes, no=no, abstain=abstain, total_eligible=10,
        )

    def test_zero_votes_returns_true(self):
        # Per D3: no destabilizing signal yet.
        assert binary_snapshot_is_stable(self._snap(0, 0), 0.5) is True

    def test_support_above_threshold_returns_true(self):
        # 6/10 = 0.6 >= 0.5
        assert binary_snapshot_is_stable(self._snap(6, 4), 0.5) is True

    def test_support_at_threshold_returns_true(self):
        # 5/10 = 0.5 >= 0.5
        assert binary_snapshot_is_stable(self._snap(5, 5), 0.5) is True

    def test_support_below_threshold_returns_false(self):
        # 4/10 = 0.4 < 0.5
        assert binary_snapshot_is_stable(self._snap(4, 6), 0.5) is False

    def test_high_pass_threshold(self):
        # 6/10 = 0.6 < 0.66 (super-majority)
        assert binary_snapshot_is_stable(self._snap(6, 4), 0.66) is False
        assert binary_snapshot_is_stable(self._snap(7, 3), 0.66) is True


# ---------------------------------------------------------------------------
# Winner set overlap (multi-option)
# ---------------------------------------------------------------------------

def _msnap(winners: tuple[str, ...]) -> MultiOptionSnapshotPoint:
    return MultiOptionSnapshotPoint(
        simulated_time=_at(0),
        winners=winners,
        total_ballots_cast=10,
        total_eligible=10,
    )


class TestWinnerSetOverlaps:
    """Cover the 8 worked examples from spec D4. The implementation uses
    subset-or-superset semantics (one set must contain or be contained by
    the other), which matches all 8 examples.
    """
    @pytest.mark.parametrize("prev,curr,expected", [
        # 1. Identity — no change.
        (("A",), ("A",), True),
        # 2. Resolution-out (A held, B added as tied option).
        (("A",), ("A", "B"), True),
        # 3. Resolution-in (tied {A,B} resolved to A).
        (("A", "B"), ("A",), True),
        # 4. Resolution-in (tied {A,B} resolved to B).
        (("A", "B"), ("B",), True),
        # 5. Winner swap — unstable.
        (("A",), ("B",), False),
        # 6. Displacement with addition — unstable (A gone, C new).
        (("A", "B"), ("B", "C"), False),
        # 7. Total displacement — unstable.
        (("A", "B"), ("C",), False),
        # 8. Two displaced from larger tie — unstable.
        (("A", "B", "C"), ("C", "D"), False),
    ])
    def test_d4_worked_examples(self, prev, curr, expected):
        assert winner_set_overlaps(_msnap(curr), _msnap(prev)) is expected

    def test_empty_winner_sets_match(self):
        # Both empty: trivially subset-of-each-other.
        assert winner_set_overlaps(_msnap(()), _msnap(())) is True

    def test_empty_to_winner_is_subset(self):
        # No winners -> some winners: empty is subset of any set.
        assert winner_set_overlaps(_msnap(("A",)), _msnap(())) is True


# ---------------------------------------------------------------------------
# Stable-result-window detection
# ---------------------------------------------------------------------------

class TestInStableResultWindow:
    def test_outside_window_before_start(self):
        # 100s window, fraction 0.25 -> stable window starts at +75s.
        start = _at(0)
        end = _at(100)
        # At +50s: well before stable window.
        assert in_stable_result_window(_at(50), start, end, 0.25) is False

    def test_inside_window(self):
        start = _at(0)
        end = _at(100)
        # At +80s: inside the final 25% window (which starts at +75s).
        assert in_stable_result_window(_at(80), start, end, 0.25) is True

    def test_at_boundary_open(self):
        start = _at(0)
        end = _at(100)
        # At exactly the boundary +75s.
        assert in_stable_result_window(_at(75), start, end, 0.25) is True

    def test_zero_duration_returns_false(self):
        start = _at(50)
        end = _at(50)
        assert in_stable_result_window(_at(50), start, end, 0.25) is False


# ---------------------------------------------------------------------------
# evaluate_original_window_stability — binary
# ---------------------------------------------------------------------------

def _bsnap(t_offset: int, yes: int, no: int, abstain: int = 0) -> BinarySnapshotPoint:
    return BinarySnapshotPoint(
        simulated_time=_at(t_offset),
        yes=yes, no=no, abstain=abstain,
        total_eligible=max(10, yes + no + abstain),
    )


class TestEvaluateOriginalWindowStabilityBinary:
    # Voting window: 0 -> 100s. Stable window starts at +75s.
    voting_start = _at(0)
    voting_end = _at(100)

    def test_empty_snapshots_not_destabilized(self):
        d = evaluate_original_window_stability(
            "binary", [], 0.5, self.voting_start, self.voting_end,
            now=_at(80), stable_window_fraction=0.25,
        )
        assert d.destabilized is False

    def test_before_stable_window_not_destabilized(self):
        # Snapshot in window but `now` is still before stable window.
        d = evaluate_original_window_stability(
            "binary", [_bsnap(60, 3, 7)], 0.5,
            self.voting_start, self.voting_end,
            now=_at(60), stable_window_fraction=0.25,
        )
        assert d.destabilized is False

    def test_no_in_window_snapshots_not_destabilized(self):
        d = evaluate_original_window_stability(
            "binary", [_bsnap(50, 3, 7)], 0.5,
            self.voting_start, self.voting_end,
            now=_at(80), stable_window_fraction=0.25,
        )
        assert d.destabilized is False

    def test_all_in_window_stable(self):
        snaps = [_bsnap(50, 6, 4), _bsnap(80, 7, 3), _bsnap(95, 6, 4)]
        d = evaluate_original_window_stability(
            "binary", snaps, 0.5, self.voting_start, self.voting_end,
            now=_at(95), stable_window_fraction=0.25,
        )
        assert d.destabilized is False

    def test_in_window_breach_destabilizes(self):
        # In-window snapshot below pass_threshold = destabilization.
        snaps = [_bsnap(50, 6, 4), _bsnap(80, 4, 6)]  # 0.4 < 0.5
        d = evaluate_original_window_stability(
            "binary", snaps, 0.5, self.voting_start, self.voting_end,
            now=_at(80), stable_window_fraction=0.25,
        )
        assert d.destabilized is True
        assert d.breach_sample["support_fraction"] == pytest.approx(0.4)
        assert d.breach_sample["pass_threshold"] == 0.5

    def test_out_of_window_breach_ignored(self):
        # Snapshot at +50s breaches but is BEFORE stable window start (+75s).
        snaps = [_bsnap(50, 4, 6), _bsnap(80, 6, 4)]
        d = evaluate_original_window_stability(
            "binary", snaps, 0.5, self.voting_start, self.voting_end,
            now=_at(80), stable_window_fraction=0.25,
        )
        assert d.destabilized is False


# ---------------------------------------------------------------------------
# evaluate_original_window_stability — multi-option
# ---------------------------------------------------------------------------

def _msnap_at(t_offset: int, winners: tuple[str, ...]) -> MultiOptionSnapshotPoint:
    return MultiOptionSnapshotPoint(
        simulated_time=_at(t_offset),
        winners=winners,
        total_ballots_cast=10,
        total_eligible=10,
    )


class TestEvaluateOriginalWindowStabilityMultiOption:
    voting_start = _at(0)
    voting_end = _at(100)

    def test_outside_window_not_destabilized(self):
        snaps = [_msnap_at(60, ("A",))]
        d = evaluate_original_window_stability(
            "approval", snaps, 0.5, self.voting_start, self.voting_end,
            now=_at(60), stable_window_fraction=0.25,
        )
        assert d.destabilized is False

    def test_in_window_overlap_stable(self):
        snaps = [_msnap_at(50, ("A",)), _msnap_at(80, ("A",))]
        d = evaluate_original_window_stability(
            "approval", snaps, 0.5, self.voting_start, self.voting_end,
            now=_at(80), stable_window_fraction=0.25,
        )
        assert d.destabilized is False

    def test_first_in_window_compared_to_last_out_of_window(self):
        # D10: first in-window snapshot uses the last-out-of-window snapshot
        # as its baseline. {A} outside, {B} inside -> destabilization.
        snaps = [_msnap_at(50, ("A",)), _msnap_at(80, ("B",))]
        d = evaluate_original_window_stability(
            "approval", snaps, 0.5, self.voting_start, self.voting_end,
            now=_at(80), stable_window_fraction=0.25,
        )
        assert d.destabilized is True
        assert d.breach_sample["previous_winners"] == ["A"]
        assert d.breach_sample["current_winners"] == ["B"]

    def test_in_window_winner_swap_destabilizes(self):
        snaps = [_msnap_at(80, ("A",)), _msnap_at(95, ("B",))]
        d = evaluate_original_window_stability(
            "approval", snaps, 0.5, self.voting_start, self.voting_end,
            now=_at(95), stable_window_fraction=0.25,
        )
        assert d.destabilized is True

    def test_first_in_window_no_prior_snapshot(self):
        # Only one in-window snapshot, no out-of-window: no comparison
        # available -> not destabilized.
        snaps = [_msnap_at(80, ("A",))]
        d = evaluate_original_window_stability(
            "approval", snaps, 0.5, self.voting_start, self.voting_end,
            now=_at(80), stable_window_fraction=0.25,
        )
        assert d.destabilized is False

    def test_resolution_pair_stable(self):
        # {A,B} -> {A}: subset, stable.
        snaps = [_msnap_at(80, ("A", "B")), _msnap_at(95, ("A",))]
        d = evaluate_original_window_stability(
            "approval", snaps, 0.5, self.voting_start, self.voting_end,
            now=_at(95), stable_window_fraction=0.25,
        )
        assert d.destabilized is False


# ---------------------------------------------------------------------------
# evaluate_extension_stability (sliding-window check)
# ---------------------------------------------------------------------------

class TestEvaluateExtensionStability:
    stable_window_duration = timedelta(seconds=20)

    def test_empty_snapshots_returns_false(self):
        assert evaluate_extension_stability(
            "binary", [], 0.5, _at(100), self.stable_window_duration,
        ) is False

    def test_only_one_snapshot_in_lookback_returns_false(self):
        # Insufficient lookback per D10.
        snaps = [_bsnap(95, 6, 4)]
        assert evaluate_extension_stability(
            "binary", snaps, 0.5, _at(100), self.stable_window_duration,
        ) is False

    def test_binary_all_stable_in_lookback_returns_true(self):
        # 3 snapshots within last 20s, all support >= 0.5.
        snaps = [_bsnap(85, 6, 4), _bsnap(90, 7, 3), _bsnap(100, 6, 4)]
        assert evaluate_extension_stability(
            "binary", snaps, 0.5, _at(100), self.stable_window_duration,
        ) is True

    def test_binary_one_unstable_in_lookback_returns_false(self):
        snaps = [_bsnap(85, 6, 4), _bsnap(90, 4, 6), _bsnap(100, 7, 3)]
        assert evaluate_extension_stability(
            "binary", snaps, 0.5, _at(100), self.stable_window_duration,
        ) is False

    def test_binary_old_unstable_outside_lookback_ignored(self):
        # Old snapshot (well before lookback) was unstable; the lookback
        # window only includes the recent stable ones.
        snaps = [_bsnap(50, 4, 6), _bsnap(85, 6, 4), _bsnap(95, 7, 3)]
        assert evaluate_extension_stability(
            "binary", snaps, 0.5, _at(100), self.stable_window_duration,
        ) is True

    def test_multi_option_all_overlap_returns_true(self):
        snaps = [_msnap_at(85, ("A",)), _msnap_at(95, ("A",))]
        assert evaluate_extension_stability(
            "approval", snaps, 0.5, _at(100), self.stable_window_duration,
        ) is True

    def test_multi_option_swap_returns_false(self):
        snaps = [_msnap_at(85, ("A",)), _msnap_at(95, ("B",))]
        assert evaluate_extension_stability(
            "approval", snaps, 0.5, _at(100), self.stable_window_duration,
        ) is False

    def test_multi_option_resolution_returns_true(self):
        snaps = [_msnap_at(85, ("A", "B")), _msnap_at(95, ("A",))]
        assert evaluate_extension_stability(
            "approval", snaps, 0.5, _at(100), self.stable_window_duration,
        ) is True

    def test_multi_option_three_snapshot_chain_with_break(self):
        # Pair 1: {A} -> {A} OK. Pair 2: {A} -> {B} bad. Returns False.
        snaps = [
            _msnap_at(82, ("A",)),
            _msnap_at(90, ("A",)),
            _msnap_at(98, ("B",)),
        ]
        assert evaluate_extension_stability(
            "approval", snaps, 0.5, _at(100), self.stable_window_duration,
        ) is False
