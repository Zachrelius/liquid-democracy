"""Independent hand counts and production-shape STAR delegation regressions."""
from copy import deepcopy
import itertools
import random

import pytest

from delegation_engine import Ballot, DelegationData, ProposalContext, compute_tally_pure, DelegationService
from experimental_tally import count_star, ExperimentalTally, public_tally
from voting_methods import candidate_priority, new_voting_rules


def tally(ballots, options=("a", "b", "c"), rules=None):
    return count_star(options, ballots, rules or new_voting_rules("star", "p"), "p")


def test_star_hand_count_differs_from_score():
    result = tally([({"scores": {"a": 5, "b": 4}}, 3), ({"scores": {"b": 4, "c": 5}}, 2)])
    assert result.method_result["scores"] == {"a": 15, "b": 20, "c": 10}
    assert result.method_result["finalists"] == ["b", "a"]
    assert result.method_result["runoff"] == {"b": 2, "a": 3}
    assert result.winners == ["a"]
    assert result.method_result["priority_used"] is False


def test_runoff_tie_uses_original_total():
    result = tally([({"scores": {"a": 5, "b": 4}}, 1), ({"scores": {"b": 4}}, 1)], ["a", "b"])
    assert result.winners == ["b"]
    assert result.method_result["tie_trace"] == [{"stage": "runoff_total_score", "pool": ["a", "b"], "values": {"a": 5, "b": 8}}]


def test_equal_ballots_abstain_and_zeros_are_separate():
    result = tally([({"scores": {"a": 5, "b": 5}}, 7), ({"scores": {"a": 5}}, 2),
                    ({"abstain": True}, 3), ({"scores": {}}, 4)], ["a", "b"])
    assert result.total_ballots_cast == 16 and result.total_abstain == 3
    assert result.method_result["scores"] == {"a": 45, "b": 35}
    assert result.method_result["runoff"] == {"a": 2, "b": 0}
    assert result.method_result["equal_preference"] == 11
    assert sum(result.method_result["score_histograms"]["a"]) == 13


@pytest.mark.parametrize("ballots,options,reason", [
    ([], ["a", "b"], "no_positive_weight_preferences"),
    ([({"abstain": True}, 8)], ["a", "b"], "no_positive_weight_preferences"),
    ([({"scores": {"a": 5}}, 0)], ["a", "b"], "no_positive_weight_preferences"),
    ([({"scores": {}}, 8)], ["a", "b"], "all_bottom_ratings"),
    ([({"scores": {"a": 5}}, 8)], ["a"], "fewer_than_two_options"),
])
def test_no_meaningful_result(ballots, options, reason):
    result = tally(ballots, options)
    assert result.winners == []
    assert result.method_result["no_result_reason"] == reason


def test_final_priority_repeat_order_invariance_and_exact_transport():
    rules = new_voting_rules("star", "p")
    votes = [({"scores": {"a": 5, "b": 5, "c": 5}}, 10**18)]
    first = tally(votes, rules=rules)
    expected = min(["a", "b", "c"], key=lambda oid: candidate_priority(rules, "p", oid))
    assert first.winners == [expected] and first.tied
    assert first.quorum_met(1)
    for ids in itertools.permutations(["a", "b", "c"]):
        assert tally(votes, ids, rules).winners == [expected]
    public = public_tally(first)
    assert public["method_result"]["scores"]["a"] == "5000000000000000000"
    assert public["method_result"]["priority_used"] is True
    restored = ExperimentalTally.from_record({"tally": first.to_record()})
    assert restored == first
    restored.method_result["scores"]["a"] = 0
    assert first.method_result["scores"]["a"] == 5 * 10**18


def test_weight_parity_with_small_share_expansion():
    rules = new_voting_rules("star", "p")
    weighted = [({"scores": {"a": 5, "b": 4}}, 7), ({"scores": {"c": 5, "b": 4}}, 5)]
    expanded = [(payload, 1) for payload, weight in weighted for _ in range(weight)]
    large, small = tally(weighted, rules=rules), tally(expanded, rules=rules)
    assert large.method_result == small.method_result
    assert large.participating_headcount == 2 and small.participating_headcount == 12


def test_delegation_uses_represented_member_weight_and_direct_abstain_override():
    ctx = ProposalContext([], {"u": {None: DelegationData("u", "d", None, "accept_sub")}}, {}, {},
                          direct_ballots={"d": Ballot(method="star", scores={"a": 5, "b": 2})},
                          voting_method="star", user_weights={"u": 7, "d": 2, "missing": 4},
                          voting_rules=new_voting_rules("star", "p"), proposal_id="p")
    def run():
        return compute_tally_pure(["u", "d", "missing"], ctx, option_ids=["a", "b"])
    result = run()
    assert result.method_result["scores"] == {"a": 45, "b": 18}
    assert result.total_eligible == 13 and result.not_cast == 4
    assert result.participating_headcount == 2 and result.eligible_headcount == 3
    ctx.direct_ballots["u"] = Ballot(method="star", abstain=True)
    assert run().method_result["scores"] == {"a": 10, "b": 4}
    assert run().total_abstain == 7
    del ctx.direct_ballots["u"]
    assert run().method_result["scores"] == result.method_result["scores"]
    ctx.direct_ballots["u"] = Ballot(method="star", scores={})
    assert run().total_abstain == 0
    assert run().method_result["scores"] == {"a": 10, "b": 4}


def test_real_stored_ballot_and_final_record_survive_membership_change(db):
    import models
    from tests.conftest import make_user, make_org_membership
    author = make_user(db, "star-voter")
    org = models.Organization(name="STAR test", slug="star-test", settings={})
    db.add(org); db.flush()
    membership = make_org_membership(db, org_id=org.id, user_id=author.id)
    proposal = models.Proposal(title="STAR", body="", author_id=author.id, org_id=org.id,
                               voting_method="star", status="voting")
    db.add(proposal); db.flush()
    proposal.voting_rules = new_voting_rules("star", proposal.id)
    options = [models.ProposalOption(proposal_id=proposal.id, label=name) for name in ("A", "B")]
    db.add_all(options); db.flush()
    vote = models.Vote(proposal_id=proposal.id, user_id=author.id, cast_by_id=author.id,
                       ballot={"scores": {options[0].id: 5}}, is_direct=True)
    db.add(vote); db.flush()
    from delegation_engine import DelegationGraphStore
    service = DelegationService(DelegationGraphStore())
    original = service.compute_tally(proposal, db)
    assert original.winners == [options[0].id]
    proposal.final_method_result = {"tally": original.to_record()}
    proposal.status = "passed"
    db.delete(membership)
    vote.ballot = {"scores": {options[1].id: 5}}
    db.flush()
    assert service.compute_tally(proposal, db) == original
    proposal.final_method_result = None
    with pytest.raises(ValueError, match="record is missing"):
        service.compute_tally(proposal, db)


@pytest.mark.parametrize("weight", [-1, True, 1.5, "1"])
def test_invalid_weights_fail_loud(weight):
    with pytest.raises(ValueError):
        tally([({"scores": {"a": 5}}, weight)])
