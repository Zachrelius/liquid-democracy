"""Independent hand profiles for repeated full-weight STAR rounds."""
from copy import deepcopy
import pytest
from multiwinner_tally import count_bloc_star
from voting_methods import new_voting_rules,public_voting_rules
from experimental_tally import ExperimentalTally


def tally(ballots,k=2,ids=("a","b","c")):
    rules=new_voting_rules("star","p",k)
    return count_bloc_star(ids,ballots,rules,"p"),rules


def test_hand_4_3_2_sequential_runoffs():
    rows=[({"scores":{"a":5,"b":4,"c":0}},4),({"scores":{"a":0,"b":5,"c":4}},3),({"scores":{"a":0,"b":0,"c":5}},2)]
    result,rules=tally(rows);r=result.method_result
    assert r["scores"]=={"a":20,"b":31,"c":22} and result.winners==["b","c"]
    first,second=r["rounds"]
    assert first["finalists"]==["b","c"] and first["runoff"]=={"b":7,"c":2}
    assert second["pool"]==["a","c"] and second["runoff"]=={"c":5,"a":4}
    assert second["scores"]=={"a":20,"c":22}
    expanded=[(payload,1) for payload,weight in rows for _ in range(weight)]
    assert count_bloc_star(["c","b","a"],list(reversed(expanded)),rules,"p").method_result==r


def test_first_runoff_loser_is_not_automatically_next_winner():
    result,_=tally([({"scores":{"a":5,"b":4}},10),({"scores":{"b":5,"c":4}},11),({"scores":{"c":5}},1)])
    r=result.method_result
    assert r["scores"]=={"a":50,"b":95,"c":49}
    assert r["rounds"][0]["finalists"]==["b","a"]
    assert r["rounds"][0]["runoff"]=={"b":11,"a":10}
    assert r["rounds"][0]["equal_preference"]==1
    assert result.winners==["b","c"]
    assert r["rounds"][1]["runoff"]=={"a":10,"c":12}


@pytest.mark.parametrize("rows",[[],[({"abstain":True},4)],[({"scores":{}},4)],[({"scores":{"a":5}},0)]])
def test_unsupported_pool_never_fills_a_seat(rows):
    result,_=tally(rows)
    assert result.winners==[] and result.method_result["rounds"]==[]
    assert result.method_result["unfilled_count"]==2


def test_single_remaining_support_no_runoff_and_no_weight_depletion():
    result,rules=tally([({"scores":{"a":5,"b":3}},10**15)],k=3)
    assert result.winners==["a","b"]
    assert result.method_result["rounds"][1]["selection"]=="single_supported_option"
    assert result.method_result["rounds"][1]["competitive_runoff"] is False
    assert result.method_result["rounds"][1]["scores"]["b"]==3*10**15
    assert result.method_result["unfilled_count"]==1
    record={"record_version":2,"num_winners":3,"method":"star","rules":public_voting_rules(rules),"tie_seed":rules["tie_seed"],"option_labels":{"a":"A","b":"B","c":"C"},"tally":result.to_record(),"quorum_met":True,"official_winners":["a","b"]}
    assert ExperimentalTally.from_record(record).winners==["a","b"]
    record["tally"]["method_result"]["rounds"][1]["scores"]["b"]-=1
    with pytest.raises(ValueError):ExperimentalTally.from_record(record)


def test_all_rounds_use_one_committed_priority_and_original_histograms():
    result,_=tally([({"scores":{"a":5,"b":5,"c":5}},4)],k=3)
    assert len(result.winners)==3 and len(set(result.winners))==3 and result.tied
    assert all(row["priority_used"] for row in result.method_result["rounds"][:2])
    assert all(sum(h)==4 for row in result.method_result["rounds"] for h in row["score_histograms"].values())


def test_pinned_bloc_reference_and_independent_round_order_on_200_profiles():
    import os,sys,random,hashlib,json
    path=os.environ.get("STARVOTE_REFERENCE_PATH")
    if path:sys.path.insert(0,path)
    starvote=pytest.importorskip("starvote",reason="Pinned test-only STAR oracle required for release")
    assert starvote.__version__=="2.1.5"
    rng=random.Random(1133)
    for _ in range(200):
        ids=[str(i) for i in range(rng.randint(3,8))]
        rows=[({"scores":{oid:rng.randrange(6) for oid in ids}},rng.randint(1,4)) for _ in range(rng.randint(2,12))]
        supported=[oid for oid in ids if sum(payload["scores"][oid]*weight for payload,weight in rows)>0]
        if len(supported)<3:continue
        k=rng.randint(2,len(supported)-1)
        rules=new_voting_rules("star","p",k)
        def priority(oid):
            raw=json.dumps(["candidate_priority_v1",rules["tie_seed"],"p",oid],ensure_ascii=True,separators=(",",":"))
            return hashlib.sha256(raw.encode("ascii")).hexdigest(),oid
        permutation=sorted(supported,key=priority)
        expanded=[{oid:payload["scores"][oid] for oid in supported} for payload,weight in rows for _ in range(weight)]
        expected_set=starvote.bloc_star_voting(expanded,seats=k,tiebreaker=starvote.predefined_permutation_tiebreaker(permutation),verbosity=0)
        remaining=list(supported);expected=[]
        for seat in range(k):
            view=[{oid:ballot[oid] for oid in remaining} for ballot in expanded]
            winner=starvote.star_voting(view,tiebreaker=starvote.predefined_permutation_tiebreaker(sorted(remaining,key=priority)),verbosity=0)[0]
            expected.append(winner);remaining.remove(winner)
        actual=count_bloc_star(ids,rows,rules,"p")
        assert actual.winners==expected and set(actual.winners)==set(expected_set)


def test_v1_record_cannot_inject_a_winner_set():
    from experimental_tally import count_star, ExperimentalTally
    from voting_methods import new_voting_rules, public_voting_rules
    r = new_voting_rules("star", "p")
    tally = count_star(["a","b"], [({"scores":{"a":5,"b":3}},1)], r, "p")
    record = {"method":"star", "rules":public_voting_rules(r), "tally":tally.to_record()}
    record["tally"]["method_result"]["winners"] = ["b","a"]
    with pytest.raises(ValueError, match="multiwinner fields"):
        ExperimentalTally.from_record(record)
