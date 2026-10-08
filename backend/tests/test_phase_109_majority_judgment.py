"""Exact lower median and compact removal versus an independent literal oracle."""
from copy import deepcopy
from itertools import combinations_with_replacement, product
import random

import pytest

from experimental_tally import (ExperimentalTally, _lower_median, _median_pair_runs,
                                _mj_outcome, count_majority_judgment, public_tally)
from voting_methods import new_voting_rules, public_voting_rules


def count(ballots, ids=("a", "b", "c"), rules=None):
    return count_majority_judgment(ids, ballots, rules or new_voting_rules("majority_judgment", "p"), "p")


def frozen(tally, rules):
    return {"method": "majority_judgment", "rules": public_voting_rules(rules),
            "tie_seed": rules["tie_seed"], "tally": tally.to_record()}


def literal_oracle_v1(histograms):
    """Locally authored mj-literal-removal-v1, deliberately one grade per share.

    Only small synthetic tests call it. No production counting helpers.
    Lexical priority is fixed to compare identical distributions exactly.
    """
    values = {oid: [g for g, n in enumerate(h) for _ in range(n)] for oid, h in histograms.items()}
    pool = sorted(values)
    while values[pool[0]]:
        medians = {oid: values[oid][(len(values[oid]) - 1) // 2] for oid in pool}
        best = max(medians.values())
        pool = [oid for oid in pool if medians[oid] == best]
        if len(pool) == 1:
            return pool[0], False
        for oid in pool:
            values[oid].pop((len(values[oid]) - 1) // 2)
    return min(pool), True


def test_spec_median_winner_differs_from_mean():
    result = count([({"grades": {"a": 5, "b": 4}}, 3), ({"grades": {"b": 4}}, 2)])
    assert result.winners == ["a"]
    assert result.method_result["majority_grades"] == {"a": 5, "b": 4, "c": 0}
    assert result.method_result["grade_histograms"]["a"] == [2, 0, 0, 0, 0, 3]
    assert "scores" not in result.method_result


def test_even_lower_median_and_tie_removal_preserve_original_histograms():
    assert _lower_median([2, 0, 0, 0, 0, 2]) == 0
    result = count([({"grades": {"a": 2}}, 1), ({"grades": {"a": 2, "b": 2}}, 1),
                    ({"grades": {"a": 5, "b": 2}}, 1)])
    assert result.winners == ["a"]
    assert result.method_result["majority_grades"]["a"] == result.method_result["majority_grades"]["b"] == 2
    assert result.method_result["grade_histograms"]["a"] == [0, 0, 2, 0, 0, 1]
    assert result.method_result["tie_trace"] == [{"stage": "median_removal", "pool": ["a", "b"],
        "removed_per_candidate": 1, "majority_grades": {"a": 2, "b": 0}, "remaining_candidates": ["a"]}]


def test_exhaustive_six_grade_histogram_pairs_through_five_shares():
    # All 82,993 ordered pairs over sizes 1..5, including even totals.
    cases = 0
    for size in range(1, 6):
        histograms = []
        for grades in combinations_with_replacement(range(6), size):
            histograms.append([grades.count(g) for g in range(6)])
        for a, b in product(histograms, repeat=2):
            candidates = {"a": a, "b": b}
            expected, tied = literal_oracle_v1(candidates)
            actual = _mj_outcome(candidates, {"a": "a", "b": "b"})
            assert (actual["winner"], actual["priority_used"]) == (expected, tied)
            cases += 1
    assert cases == 82993


def test_random_multiway_histograms_match_literal_reference():
    rng = random.Random(10904)
    for _ in range(2000):
        size = rng.randrange(1, 60)
        histograms = {}
        for oid in list("abcdef")[:rng.randrange(2, 7)]:
            h = [0] * 6
            for _ in range(size):
                h[rng.randrange(6)] += 1
            histograms[oid] = h
        before = deepcopy(histograms)
        expected, tied = literal_oracle_v1(histograms)
        actual = _mj_outcome(histograms, {oid: oid for oid in histograms})
        assert (actual["winner"], actual["priority_used"]) == (expected, tied)
        assert histograms == before


def test_trillion_share_alternating_median_jumps_are_bounded():
    n = 10**30
    # Same center-pair repeated almost n times, differing only at extremes.
    histograms = {"a": [0, 1, n, n, 1, 0], "b": [1, 0, n, n, 0, 1]}
    result = _mj_outcome(histograms, {"a": "a", "b": "b"})
    assert result["winner"] == "a" and not result["priority_used"]
    assert result["tie_trace"][0]["removed_per_candidate"] == 2 * n
    assert all(len(_median_pair_runs(h)) <= 11 for h in histograms.values())
    same = _mj_outcome({"a": histograms["a"], "b": histograms["a"]}, {"a": "z", "b": "a"})
    assert same["winner"] == "b" and same["priority_used"]


@pytest.mark.parametrize("ballots,ids,reason", [
    ([], ["a", "b"], "no_positive_weight_preferences"),
    ([({"abstain": True}, 4)], ["a", "b"], "no_positive_weight_preferences"),
    ([({"grades": {"a": 5}}, 0)], ["a", "b"], "no_positive_weight_preferences"),
    ([({"grades": {}}, 4)], ["a", "b"], "all_bottom_ratings"),
    ([({"grades": {"a": 5}}, 4)], ["a"], "fewer_than_two_options"),
])
def test_no_result_and_frozen_roundtrip(ballots, ids, reason):
    rules = new_voting_rules("majority_judgment", "p")
    result = count(ballots, ids, rules)
    assert result.winners == [] and result.method_result["no_result_reason"] == reason
    assert ExperimentalTally.from_record(frozen(result, rules)) == result


def test_neutral_counts_late_reject_and_abstain_exclusion():
    expression = {"grades": {"a": 5}}
    result = count([(expression, 7), ({"grades": {}}, 3), ({"abstain": True}, 5)])
    assert result.total_ballots_cast == 15 and result.total_abstain == 5
    assert result.method_result["preference_weight"] == 10
    assert result.method_result["grade_histograms"]["b"] == [10, 0, 0, 0, 0, 0]
    assert result.method_result["majority_grades"]["a"] == 5
    late = count([(expression, 7)], ["a", "b", "c", "late"])
    assert late.method_result["grade_histograms"]["late"] == [7, 0, 0, 0, 0, 0]
    assert expression == {"grades": {"a": 5}}


def test_whole_grade_ballot_relevance_override_and_exact_weight():
    from delegation_engine import Ballot, DelegationData, ProposalContext, compute_tally_pure
    ctx = ProposalContext(["t1", "t2"], {
        "u": {"t1": DelegationData("u", "left", "t1", "accept_sub"),
              "t2": DelegationData("u", "right", "t2", "accept_sub")}}, {}, {},
        direct_ballots={"left": Ballot(method="majority_judgment", grades={"a": 5}),
                        "right": Ballot(method="majority_judgment", grades={"b": 4})},
        voting_method="majority_judgment", user_strategies={"u": "relevance_weighted"},
        proposal_topic_relevances={"t1": 0.2, "t2": 0.8}, user_weights={"u": 10**18, "left": 0, "right": 0},
        voting_rules=new_voting_rules("majority_judgment", "p"), proposal_id="p")
    def run():
        return compute_tally_pure(["u", "left", "right"], ctx, option_ids=["a", "b"])
    result = run()
    assert result.winners == ["b"] and result.method_result["grade_histograms"]["b"][4] == 10**18
    public = public_tally(result)["method_result"]
    assert public["majority_grades"]["b"] == 4
    assert public["grade_histograms"]["b"][4] == str(10**18)
    ctx.direct_ballots["u"] = Ballot(method="majority_judgment", grades={})
    assert run().method_result["no_result_reason"] == "all_bottom_ratings"
    ctx.direct_ballots["u"] = Ballot(method="majority_judgment", abstain=True)
    assert run().total_abstain == 10**18
    del ctx.direct_ballots["u"]
    assert run() == result


def test_counter_weight_expansion_and_input_order_equivalence():
    rng = random.Random(1090402)
    rules = new_voting_rules("majority_judgment", "p")
    for _ in range(300):
        ballots = [({"grades": {oid: rng.randrange(6) for oid in "abc" if rng.randrange(3)}}, rng.randrange(6))
                   for _ in range(rng.randrange(1, 15))]
        result = count(ballots, rules=rules)
        expanded = [(expression, 1) for expression, weight in ballots for _ in range(weight)]
        assert count(expanded, rules=rules).method_result == result.method_result
        assert count(list(reversed(ballots)), list("cba"), rules).method_result == result.method_result


@pytest.mark.parametrize("payload", [{"grades": {"a": True}}, {"grades": {"a": "5"}},
    {"grades": {"a": 2.5}}, {"grades": {"foreign": 5}}, {"grades": {}, "scores": {}},
    {"grades": {}, "rank_groups": []}, {"abstain": True, "grades": {}}])
def test_malformed_grade_ballots_rejected(payload):
    with pytest.raises(ValueError):
        count([(payload, 1)])


@pytest.mark.parametrize("field,value", [("winner", "b"), ("majority_grades", {}), ("grade_histograms", {}),
    ("grade_labels", []), ("priority_used", True), ("no_result_reason", "all_bottom_ratings")])
def test_frozen_result_corruption_rejected(field, value):
    rules = new_voting_rules("majority_judgment", "p")
    result = count([({"grades": {"a": 5, "b": 4}}, 7)], rules=rules)
    assert ExperimentalTally.from_record(frozen(result, rules)) == result
    record = frozen(result, rules)
    record["tally"]["method_result"][field] = value
    with pytest.raises(ValueError):
        ExperimentalTally.from_record(record)
