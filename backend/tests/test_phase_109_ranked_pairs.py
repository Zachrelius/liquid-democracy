"""Margins Ranked Pairs v1, independent topological oracle, and integration."""
from copy import deepcopy
import random

import pytest

from delegation_engine import Ballot, DelegationData, ProposalContext, compute_tally_pure
from experimental_tally import ExperimentalTally, count_ranked_pairs, public_tally
from voting_methods import new_voting_rules, public_voting_rules


def count(ballots, ids=("a", "b", "c"), rules=None):
    return count_ranked_pairs(ids, ballots, rules or new_voting_rules("ranked_pairs", "p"), "p")


def record(tally, rules):
    return {"method": "ranked_pairs", "tally": tally.to_record(),
            "rules": public_voting_rules(rules), "tie_seed": rules["tie_seed"]}


def test_spec_cycle_locks_strong_victories_skips_cycle(monkeypatch):
    monkeypatch.setattr("experimental_tally.candidate_priority", lambda rules, pid, oid: oid)
    result = count([({"rank_groups": [["a"], ["b"], ["c"]]}, 3),
                    ({"rank_groups": [["b"], ["c"], ["a"]]}, 2),
                    ({"rank_groups": [["c"], ["a"], ["b"]]}, 2)])
    assert result.winners == ["a"]
    assert [(e["winner"], e["loser"], e["margin"]) for e in result.method_result["locked_edges"]] == [("a", "b", 3), ("b", "c", 3)]
    assert result.method_result["skipped_edges"] == [{"winner": "c", "loser": "a", "margin": 1,
                                                    "support": 4, "reason": "would_create_cycle"}]
    assert result.method_result["priority_used"]  # equal 3-margin/5-support edges consulted priority


def test_equal_strength_cycle_exact_edge_order(monkeypatch):
    monkeypatch.setattr("experimental_tally.candidate_priority", lambda rules, pid, oid: oid)
    result = count([({"rank_groups": [[a], [b], [c]]}, 1) for a, b, c in
                    [("a", "b", "c"), ("b", "c", "a"), ("c", "a", "b")]])
    assert result.winners == ["a"]
    assert [(e["winner"], e["loser"]) for e in result.method_result["ordered_victories"]] == [("a", "b"), ("b", "c"), ("c", "a")]
    assert result.tied


def test_equal_margins_compare_winning_support_before_priority(monkeypatch):
    monkeypatch.setattr("experimental_tally.candidate_priority", lambda rules, pid, oid: oid)
    result = count([({"rank_groups": [["a", "b"], ["c"]]}, 2),
                    ({"rank_groups": [["a"], ["b", "c"]]}, 1),
                    ({"rank_groups": [["c"], ["a", "b"]]}, 1)])
    assert [(e["winner"], e["loser"], e["margin"], e["support"]) for e in result.method_result["ordered_victories"]] == [
        ("a", "c", 2, 3), ("b", "c", 1, 2), ("a", "b", 1, 1)]
    assert result.winners == ["a"] and not result.tied


def test_topic_relevance_selects_whole_ranked_ballot_and_preserves_chain_limits():
    ctx = ProposalContext(
        ["t1", "t2"], {"u": {"t1": DelegationData("u", "left", "t1", "accept_sub"),
                              "t2": DelegationData("u", "right", "t2", "accept_sub")}}, {}, {},
        direct_ballots={"left": Ballot(method="ranked_pairs", rank_groups=[["a"]]),
                        "right": Ballot(method="ranked_pairs", rank_groups=[["b"]])},
        voting_method="ranked_pairs", user_strategies={"u": "relevance_weighted"},
        proposal_topic_relevances={"t1": 0.2, "t2": 0.8},
        user_weights={"u": 7, "left": 0, "right": 0},
        voting_rules=new_voting_rules("ranked_pairs", "p"), proposal_id="p")
    result = compute_tally_pure(["u", "left", "right"], ctx, option_ids=["a", "b"])
    assert result.method_result["pairwise"] == {"a": {"a": 0, "b": 0}, "b": {"a": 7, "b": 0}}
    chain = [f"chain{i}" for i in range(100)]
    for a, b in zip(chain, chain[1:] + ["right"]):
        ctx.all_delegations[a] = {None: DelegationData(a, b, None, "accept_sub")}
        ctx.user_weights[a] = 3
    result = compute_tally_pure(chain + ["right"], ctx, option_ids=["a", "b"])
    assert result.method_result["pairwise"]["b"]["a"] == 6 and result.not_cast == 98 * 3


def test_tied_ranks_omissions_abstain_neutral_and_late_option():
    ballot = {"rank_groups": [["a", "b"]]}
    original = deepcopy(ballot)
    result = count([(ballot, 7), ({"rank_groups": []}, 3), ({"abstain": True}, 2)])
    matrix = result.method_result["pairwise"]
    assert matrix["a"]["b"] == matrix["b"]["a"] == 0
    assert matrix["a"]["c"] == matrix["b"]["c"] == 7
    assert result.total_ballots_cast == 12 and result.total_abstain == 2
    assert result.method_result["preference_weight"] == 10
    late = count([(ballot, 7)], ["a", "b", "c", "late"])
    assert late.method_result["pairwise"]["c"]["late"] == late.method_result["pairwise"]["late"]["c"] == 0
    assert late.method_result["pairwise"]["a"]["late"] == 7
    assert ballot == original
    assert late.method_result["option_set_version"] != result.method_result["option_set_version"]


@pytest.mark.parametrize("ballots,ids,reason", [
    ([], ["a", "b"], "no_positive_weight_preferences"),
    ([({"abstain": True}, 5)], ["a", "b"], "no_positive_weight_preferences"),
    ([({"rank_groups": [["a"]]}, 0)], ["a", "b"], "no_positive_weight_preferences"),
    ([({"rank_groups": []}, 5)], ["a", "b"], "no_strict_preferences"),
    ([({"rank_groups": [["a", "b"]]}, 5)], ["a", "b"], "no_strict_preferences"),
    ([({"rank_groups": [["a"]]}, 5)], ["a"], "fewer_than_two_options"),
])
def test_no_result(ballots, ids, reason):
    rules = new_voting_rules("ranked_pairs", "p")
    result = count(ballots, ids, rules)
    assert result.winners == [] and result.method_result["no_result_reason"] == reason
    assert ExperimentalTally.from_record(record(result, rules)) == result


def test_balanced_strict_preferences_remain_meaningful_and_all_nodes_are_sources(monkeypatch):
    monkeypatch.setattr("experimental_tally.candidate_priority", lambda rules, pid, oid: oid)
    result = count([({"rank_groups": [["a"], ["b"]]}, 2), ({"rank_groups": [["b"], ["a"]]}, 2)], ["a", "b"])
    assert result.winners == ["a"] and result.method_result["no_result_reason"] is None
    assert result.method_result["ordered_victories"] == []
    assert result.method_result["source_candidates"] == ["a", "b"]


def test_delegation_owner_weights_override_and_empty_ballot():
    ctx = ProposalContext([], {"u": {None: DelegationData("u", "d", None, "accept_sub")}}, {}, {},
                          direct_ballots={"d": Ballot(method="ranked_pairs", rank_groups=[["a"]])},
                          voting_method="ranked_pairs", user_weights={"u": 10**18, "d": 2, "missing": 4},
                          voting_rules=new_voting_rules("ranked_pairs", "p"), proposal_id="p")
    def run():
        return compute_tally_pure(["u", "d", "missing"], ctx, option_ids=["a", "b", "late"])
    result = run()
    assert result.method_result["pairwise"]["a"]["b"] == 10**18 + 2
    assert public_tally(result)["method_result"]["pairwise"]["a"]["late"] == str(10**18 + 2)
    assert result.not_cast == 4
    ctx.direct_ballots["u"] = Ballot(method="ranked_pairs", abstain=True)
    assert run().total_abstain == 10**18
    ctx.direct_ballots["u"] = Ballot(method="ranked_pairs", rank_groups=[])
    assert run().method_result["pairwise"]["a"]["b"] == 2
    del ctx.direct_ballots["u"]
    assert run() == result


@pytest.mark.parametrize("payload", [{"rank_groups": [["a"], ["a"]]}, {"rank_groups": [[]]},
    {"rank_groups": [["foreign"]]}, {"rank_groups": [[True]]}, {"rank_groups": [], "scores": {}},
    {"abstain": True, "rank_groups": []}])
def test_invalid_ranked_payloads_rejected(payload):
    with pytest.raises(ValueError):
        count([(payload, 1)])


@pytest.mark.parametrize("field,value", [("winner", "b"), ("pairwise", {}), ("locked_edges", []),
    ("priority_used", False), ("option_set_version", "wrong"), ("no_result_reason", "no_strict_preferences")])
def test_frozen_graph_corruption_rejected(field, value):
    rules = new_voting_rules("ranked_pairs", "p")
    result = count([({"rank_groups": [["a"]]}, 3)], rules=rules)
    assert ExperimentalTally.from_record(record(result, rules)) == result
    stored = record(result, rules)
    stored["tally"]["method_result"][field] = value
    with pytest.raises(ValueError):
        ExperimentalTally.from_record(stored)


def reference_v1(ids, ballots):
    """Locally authored rp-margins-topological-oracle-v1; no production helpers.

    Column-pair sums plus Kahn elimination for cycle detection, independent of
    production's incremental bitset reachability. Lexical final priorities.
    """
    rankings = []
    for groups, weight in ballots:
        rank = {oid: i for i, group in enumerate(groups) for oid in group}
        rankings.append(({oid: rank.get(oid, len(groups)) for oid in ids}, weight))
    pairs = {a: {b: sum(weight for ranks, weight in rankings if ranks[a] < ranks[b])
                 for b in ids} for a in ids}
    edges = sorted([(a, b) for a in ids for b in ids if pairs[a][b] > pairs[b][a]],
                   key=lambda e: (pairs[e[1]][e[0]] - pairs[e[0]][e[1]], -pairs[e[0]][e[1]], *e))
    accepted = []
    rejected = []
    for edge in edges:
        trial = accepted + [edge]
        remaining = set(ids)
        while remaining:
            roots = {node for node in remaining if not any(b == node and a in remaining for a, b in trial)}
            if not roots:
                break
            remaining -= roots
        (rejected if remaining else accepted).append(edge)
    sources = sorted(set(ids) - {b for _, b in accepted})
    winner = sources[0] if any(any(row.values()) for row in pairs.values()) else None
    return pairs, accepted, rejected, winner


def test_independent_topological_reference_1000_profiles(monkeypatch):
    monkeypatch.setattr("experimental_tally.candidate_priority", lambda rules, pid, oid: oid)
    rules = new_voting_rules("ranked_pairs", "p")
    rng = random.Random(10903)
    for _ in range(1000):
        ids = list("abcdefg")[:rng.randrange(2, 8)]
        ballots = []
        for _ in range(rng.randrange(1, 18)):
            ranks = {oid: rng.randrange(4) for oid in ids if rng.randrange(4)}
            groups = [[oid for oid in ids if ranks.get(oid) == rank] for rank in sorted(set(ranks.values()))]
            ballots.append((groups, rng.randrange(1, 6)))
        matrix, accepted, rejected, winner = reference_v1(ids, ballots)
        payloads = [({"rank_groups": groups}, weight) for groups, weight in ballots]
        result = count(payloads, ids, rules).method_result
        assert result["pairwise"] == matrix and result["winner"] == winner
        assert [(e["winner"], e["loser"]) for e in result["locked_edges"]] == accepted
        assert [(e["winner"], e["loser"]) for e in result["skipped_edges"]] == rejected
        assert count(list(reversed(payloads)), list(reversed(ids)), rules).method_result == result
        expanded = [(payload, 1) for payload, weight in payloads for _ in range(weight)]
        assert count(expanded, ids, rules).method_result == result
        condorcet = [a for a in ids if all(a == b or matrix[a][b] > matrix[b][a] for b in ids)]
        if condorcet:
            assert result["winner"] == condorcet[0]
