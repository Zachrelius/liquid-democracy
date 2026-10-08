"""Score v1 independent fixtures and whole-ballot integration checks."""
import random

import pytest

from delegation_engine import Ballot, DelegationData, ProposalContext, compute_tally_pure
from experimental_tally import ExperimentalTally, count_score, public_tally
from voting_methods import new_voting_rules


def count(ballots, ids=("a", "b", "c"), rules=None):
    return count_score(ids, ballots, rules or new_voting_rules("score", "p"), "p")


def test_spec_fixture_elects_b_without_star_runoff():
    result = count([({"scores": {"a": 5, "b": 4}}, 3), ({"scores": {"b": 4, "c": 5}}, 2)])
    assert result.method_result["scores"] == {"a": 15, "b": 20, "c": 10}
    assert result.winners == ["b"]
    assert not any(key in result.method_result for key in ("finalists", "runoff", "five_star_counts"))
    assert ExperimentalTally.from_record({"tally": result.to_record()}) == result


def test_equal_maxima_use_priority_even_when_five_star_counts_differ(monkeypatch):
    monkeypatch.setattr("experimental_tally.candidate_priority", lambda rules, pid, oid: oid)
    result = count([({"scores": {"a": 4, "b": 5}}, 1), ({"scores": {"a": 1}}, 1)])
    assert result.winners == ["a"]
    assert result.method_result["tie_trace"] == [{"stage": "score_priority", "pool": ["a", "b"]}]
    assert result.tied


@pytest.mark.parametrize("ballots,ids,reason", [
    ([], ["a", "b"], "no_positive_weight_preferences"),
    ([({"abstain": True}, 8)], ["a", "b"], "no_positive_weight_preferences"),
    ([({"scores": {"a": 5}}, 0)], ["a", "b"], "no_positive_weight_preferences"),
    ([({"scores": {}}, 8)], ["a", "b"], "all_bottom_ratings"),
    ([({"scores": {"a": 5}}, 8)], ["a"], "fewer_than_two_options"),
])
def test_no_result(ballots, ids, reason):
    result = count(ballots, ids)
    assert result.winners == [] and result.method_result["no_result_reason"] == reason
    assert ExperimentalTally.from_record({"tally": result.to_record()}) == result


def test_omissions_neutral_and_abstain_keep_common_denominator_and_exact_weight():
    rules = new_voting_rules("score", "p")
    ballot = {"scores": {"a": 5}}
    result = count([(ballot, 10**18), ({"scores": {}}, 3), ({"abstain": True}, 7)], rules=rules)
    assert ballot == {"scores": {"a": 5}}
    assert result.method_result["preference_weight"] == 10**18 + 3
    assert result.method_result["score_histograms"]["b"] == [10**18 + 3, 0, 0, 0, 0, 0]
    assert result.total_ballots_cast == 10**18 + 10 and result.total_abstain == 7
    assert public_tally(result)["method_result"]["scores"]["a"] == str(5 * 10**18)
    late = count([(ballot, 10**18)], ["a", "b", "c", "late"], rules)
    assert late.method_result["scores"]["late"] == 0
    assert late.method_result["option_set_version"] != result.method_result["option_set_version"]
    result.total_eligible = 10**30 + 1
    result.total_ballots_cast = 5 * 10**29
    assert not result.quorum_met(0.5)


def test_whole_ballot_delegate_weights_overrides_and_retraction():
    ctx = ProposalContext([], {"u": {None: DelegationData("u", "d", None, "accept_sub")}}, {}, {},
                          direct_ballots={"d": Ballot(method="score", scores={"a": 5, "b": 2})},
                          voting_method="score", user_weights={"u": 7, "d": 2, "missing": 4},
                          voting_rules=new_voting_rules("score", "p"), proposal_id="p")
    def run():
        return compute_tally_pure(["u", "d", "missing"], ctx, option_ids=["a", "b", "late"])
    result = run()
    assert result.method_result["scores"] == {"a": 45, "b": 18, "late": 0}
    assert result.total_eligible == 13 and result.not_cast == 4
    ctx.direct_ballots["u"] = Ballot(method="score", abstain=True)
    assert run().total_abstain == 7
    ctx.direct_ballots["u"] = Ballot(method="score", scores={})
    assert run().method_result["scores"]["a"] == 10
    del ctx.direct_ballots["u"]
    assert run() == result


@pytest.mark.parametrize("field,value", [("winner", "c"), ("priority_used", True), ("runoff", {}),
                                         ("score_histograms", {}), ("option_set_version", "wrong")])
def test_corrupt_frozen_score_rejected(field, value):
    result = count([({"scores": {"a": 5, "b": 1}}, 7)])
    record = {"tally": result.to_record()}
    record["tally"]["method_result"][field] = value
    with pytest.raises(ValueError):
        ExperimentalTally.from_record(record)


@pytest.mark.parametrize("ballot", [{"scores": {"a": True}}, {"scores": {"a": 1.5}},
                                     {"scores": {"foreign": 5}}, {"scores": {}, "rank_groups": []},
                                     {"abstain": True, "scores": {}}])
def test_malformed_score_ballots_fail_before_counting(ballot):
    with pytest.raises(ValueError):
        count([(ballot, 1)])


@pytest.mark.parametrize("weight", [-1, True, 1.5, "1"])
def test_noninteger_or_negative_weights_fail(weight):
    with pytest.raises(ValueError):
        count([({"scores": {"a": 5}}, weight)])


@pytest.mark.parametrize("metadata", [{"method": "star"},
    {"rules": {"method": "score", "rule_id": "star_0_5_v1"}},
    {"rules": {"method": "star", "rule_id": "score_0_5_sum_v1"}}])
def test_frozen_outer_metadata_must_match_inner_tally(metadata):
    result = count([({"scores": {"a": 5}}, 1)])
    with pytest.raises(ValueError, match="contradict.*tally"):
        ExperimentalTally.from_record({"tally": result.to_record(), **metadata})


def test_independent_sum_oracle_v1_two_thousand_synthetic_profiles(monkeypatch):
    # Locally authored reference score-sum-oracle-v1, pinned by this test's
    # Git revision. Intentionally column-wise sums, no production helper;
    # controlled lexical priority permits comparing every tied outcome.
    monkeypatch.setattr("experimental_tally.candidate_priority", lambda rules, pid, oid: oid)
    rng = random.Random(10902)
    rules = new_voting_rules("score", "p")
    for _ in range(2000):
        ids = list("abcdef")[:rng.randrange(2, 7)]
        expressions = [(rng.choice([{}, {oid: rng.randrange(6) for oid in ids}]), rng.randrange(9))
                       for _ in range(rng.randrange(20))]
        reference = {oid: sum(ratings.get(oid, 0) * weight for ratings, weight in expressions) for oid in ids}
        expected = min(reference, key=lambda oid: (-reference[oid], oid)) if any(reference.values()) else None
        ballots = [({"scores": ratings}, weight) for ratings, weight in expressions]
        result = count(ballots, ids, rules)
        assert result.method_result["scores"] == reference
        assert result.method_result["winner"] == expected
        assert count(list(reversed(ballots)), list(reversed(ids)), rules).winners == result.winners
        expanded = [(payload, 1) for payload, weight in ballots for _ in range(weight)]
        assert count(expanded, ids, rules).method_result == result.method_result
