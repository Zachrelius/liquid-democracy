"""Independent literal median-removal ordering, never production comparator reuse."""
from copy import deepcopy
from itertools import permutations
import hashlib,json,random
import pytest
from multiwinner_tally import count_majority_judgment_top_n,_mj_order
from experimental_tally import ExperimentalTally
from voting_methods import new_voting_rules,public_voting_rules


def rules(k=2):
    r=new_voting_rules("majority_judgment","p",k)
    r.update(tie_seed="23"*32,tie_commitment=hashlib.sha256(bytes.fromhex("23"*32)).hexdigest())
    return r


def priority(r,oid):
    raw=json.dumps(["candidate_priority_v1",r["tie_seed"],"p",oid],separators=(",",":"))
    return hashlib.sha256(raw.encode()).hexdigest(),oid


def literal_sequence(grades):
    remaining=sorted(grades);sequence=[]
    while remaining:
        sequence.append(remaining.pop((len(remaining)-1)//2))
    return tuple(sequence)


def literal_order(histograms,r):
    return sorted((oid for oid,h in histograms.items() if any(h[1:])),
        key=lambda oid:(tuple(-g for g in literal_sequence([grade for grade,n in enumerate(histograms[oid]) for _ in range(n)])),priority(r,oid)))


def test_deep_boundary_tie_preserves_original_histograms():
    # Initial grade 4 and two further identical medians; fourth removal differs.
    columns={"a":[2,3,4,4,5],"b":[1,3,4,4,5],"c":[0,3,4,4,5]}
    rows=[({"grades":{oid:g[i] for oid,g in columns.items()}},1) for i in range(5)]
    r=rules();result=count_majority_judgment_top_n(["a","b","c","d"],rows,r,"p").method_result
    expected={oid:[grades.count(g) for g in range(6)] for oid,grades in columns.items()};expected["d"]=[5,0,0,0,0,0]
    assert result["grade_histograms"]==expected
    assert result["majority_grades"]=={"a":4,"b":4,"c":4,"d":0}
    assert result["ranked_order"]==["a","b","c"] and result["winners"]==["a","b"]
    assert result["selection_boundary_tie"] and not result["priority_used"]
    assert any(e["removed_per_candidate"]==3 for e in result["tie_trace"])
    assert count_majority_judgment_top_n(["d","c","a","b"],list(reversed(rows)),r,"p").method_result==result


def test_literal_full_order_and_transitivity_random_small_profiles():
    rng=random.Random(1134);r=rules()
    for _ in range(500):
        rows=[({"grades":{oid:rng.randrange(6) for oid in "abcd"}},rng.randrange(4)) for _ in range(rng.randrange(1,9))]
        result=count_majority_judgment_top_n("abcd",rows,r,"p").method_result
        original=deepcopy(result["grade_histograms"])
        assert result["ranked_order"]==literal_order(original,r)
        for a,b,c in permutations(result["ranked_order"],3):
            ab,_=_mj_order({a:original[a],b:original[b]},r,"p")
            bc,_=_mj_order({b:original[b],c:original[c]},r,"p")
            ac,_=_mj_order({a:original[a],c:original[c]},r,"p")
            if ab[0]==a and bc[0]==b:assert ac[0]==a
        assert result["grade_histograms"]==original
        expanded=[(p,1) for p,w in rows for _ in range(w)]
        assert count_majority_judgment_top_n("dcba",list(reversed(expanded)),r,"p").method_result==result


def test_reject_median_still_supported_and_singleton_fills_only_one():
    r=rules(3)
    result=count_majority_judgment_top_n("abcd",[({"grades":{"a":5}},1),({"grades":{}},10**20)],r,"p").method_result
    assert result["majority_grades"]["a"]==0 and result["winners"]==["a"]
    assert result["unfilled_count"]==2 and not result["priority_used"]


def test_huge_common_runs_skip_without_expanding_shares():
    r=rules();n=10**40
    rows=[({"grades":{"a":4,"b":4,"c":4}},n),({"grades":{"a":3,"b":2,"c":1}},n),({"grades":{"a":5,"b":5,"c":5}},n)]
    result=count_majority_judgment_top_n("abc",rows,r,"p").method_result
    assert result["ranked_order"]==["a","b","c"]
    assert result["grade_histograms"]["a"]==[0,0,0,n,n,n]
    assert max(e["removed_per_candidate"] for e in result["tie_trace"])>=n


@pytest.mark.parametrize("rows",[[],[({"abstain":True},3)],[({"grades":{}},3)],[({"grades":{"a":5}},0)]])
def test_no_support(rows):
    result=count_majority_judgment_top_n("abc",rows,rules(),"p").method_result
    assert result["winners"]==[] and result["unfilled_count"]==2


def test_identical_distributions_use_fixed_priority_and_corruption_fails():
    r=rules();tally=count_majority_judgment_top_n("abc",[({"grades":{"a":4,"b":4,"c":4}},2)],r,"p")
    result=tally.method_result
    assert result["ranked_order"]==sorted("abc",key=lambda oid:priority(r,oid))
    assert result["priority_used"] and result["selection_boundary_tie"]
    record={"record_version":2,"num_winners":2,"method":"majority_judgment","rules":public_voting_rules(r),"tie_seed":r["tie_seed"],"option_labels":dict(zip("abc","ABC")),"tally":tally.to_record(),"quorum_met":True,"official_winners":tally.winners}
    assert ExperimentalTally.from_record(record).winners==tally.winners
    for key,value in [("ranked_order",list(reversed(result["ranked_order"]))),("majority_grades",{"a":2,"b":4,"c":4}),("comparisons",[]),("filled_count",True),("grade_histograms",{"a":[0,0,0,0,1,0]})]:
        broken=deepcopy(record);broken["tally"]["method_result"][key]=value
        with pytest.raises(ValueError):ExperimentalTally.from_record(broken)
