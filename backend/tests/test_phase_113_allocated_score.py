"""Literal unit-voter oracle independent of the grouped production allocator."""
from copy import deepcopy
from fractions import Fraction
import hashlib,json,random
import pytest
from allocated_score import count_allocated_score,read_quantity
from experimental_tally import ExperimentalTally
from voting_methods import new_voting_rules,public_voting_rules


def rules(k=2):
    r=new_voting_rules("allocated_score","p",k)
    r.update(tie_seed="45"*32,tie_commitment=hashlib.sha256(bytes.fromhex("45"*32)).hexdigest())
    return r


def priority(r,oid):
    raw=json.dumps(["candidate_priority_v1",r["tie_seed"],"p",oid],separators=(",",":"))
    return hashlib.sha256(raw.encode()).hexdigest(),oid


def unit_oracle(ids,rows,r):
    voters=[(dict(ballot["scores"]),Fraction(1)) for ballot,w in rows if not ballot.get("abstain") for _ in range(w) if any(ballot["scores"].values())]
    quota=Fraction(len(voters),r["num_winners"]);remaining=sorted(ids);winners=[];totals_log=[];mass_log=[]
    while remaining and len(winners)<r["num_winners"]:
        totals={c:sum((f*s.get(c,0) for s,f in voters),Fraction(0)) for c in remaining}
        best=max(totals.values())
        if not best:break
        selected=min([c for c in remaining if totals[c]==best],key=lambda c:priority(r,c))
        contribution={i:f*s.get(selected,0) for i,(s,f) in enumerate(voters) if f}
        need=quota
        for value in sorted(set(contribution.values()),reverse=True):
            members=[i for i,c in contribution.items() if c==value]
            mass=sum((voters[i][1] for i in members),Fraction(0));spend=min(need,mass)
            retained=1-spend/mass
            for i in members:voters[i]=(voters[i][0],voters[i][1]*retained)
            need-=spend
            if not need:break
        totals_log.append(totals);mass_log.append(sum((f for s,f in voters),Fraction(0)))
        winners.append(selected);remaining.remove(selected)
    return winners,quota,totals_log,mass_log


def test_30_20_boundary_and_zero_contribution_band_conservation():
    result=count_allocated_score("abc",[({"scores":{"a":5}},30),({"scores":{"b":5}},20)],rules(),"p").method_result
    assert result["winners"]==["a","b"] and read_quantity(result["quota"])==25
    first=result["rounds"][0]
    assert read_quantity(first["allocation_bands"][0]["allocated_fraction"])==Fraction(5,6)
    assert read_quantity(first["remaining_weight_after"])==25
    # Every first-group voter's retained fraction is 1/6, not five selected people.
    second=result["rounds"][1];assert read_quantity(second["totals"]["b"])==100
    assert [(read_quantity(b["contribution"]),read_quantity(b["allocated_mass"])) for b in second["allocation_bands"]]==[(5,20),(0,5)]
    assert read_quantity(result["allocated_weight"])==50 and read_quantity(result["remaining_weight"])==0


def test_fractional_contribution_reorders_lower_original_scores():
    rows=[({"scores":{"a":5,"b":4}},6),({"scores":{"a":4,"b":3,"c":5}},4)]
    result=count_allocated_score("abc",rows,rules(3),"p").method_result
    assert result["winners"]==["a","b","c"]
    assert read_quantity(result["rounds"][0]["allocation_bands"][0]["allocated_fraction"])==Fraction(5,9)
    second=result["rounds"][1]
    # Original B4 now contributes 16/9; untouched B3 contributes 3 and goes first.
    assert read_quantity(second["allocation_bands"][0]["contribution"])==3
    assert read_quantity(second["allocation_bands"][0]["remaining_mass"])==4
    assert read_quantity(second["allocation_bands"][0]["allocated_fraction"])==Fraction(5,6)
    assert read_quantity(second["totals"]["b"])==Fraction(68,3)


def test_weighted_groups_order_by_unit_contribution_not_group_total():
    rows=[({"scores":{"a":5}},50),({"scores":{"a":4,"b":5}},100)]
    r=rules();result=count_allocated_score("abc",rows,r,"p").method_result
    bands=result["rounds"][0]["allocation_bands"]
    assert [(read_quantity(b["contribution"]),read_quantity(b["allocated_mass"])) for b in bands]==[(5,50),(4,25)]
    assert read_quantity(bands[1]["allocated_fraction"])==Fraction(1,4)
    split=[(rows[0][0],20),(rows[0][0],30),(rows[1][0],100)]
    assert count_allocated_score("abc",split,r,"p").method_result==result
    expanded=[(p,1) for p,w in rows for _ in range(w)]
    assert count_allocated_score("cba",list(reversed(expanded)),r,"p").method_result==result


def test_60_40_proportional_weight_illustration_not_demographic_claim():
    ids=[f"a{i}" for i in range(5)]+[f"b{i}" for i in range(5)]
    rows=[({"scores":{c:5 for c in ids if c.startswith("a")}},60),({"scores":{c:5 for c in ids if c.startswith("b")}},40)]
    result=count_allocated_score(ids,rows,rules(5),"p").method_result
    assert sum(c.startswith("a") for c in result["winners"])==3
    assert sum(c.startswith("b") for c in result["winners"])==2
    assert read_quantity(result["remaining_weight"])==0
    from multiwinner_tally import count_score_top_n,count_bloc_star,count_majority_judgment_top_n,count_ranked_pairs_top_n
    for method,counter in [("score",count_score_top_n),("star",count_bloc_star),("majority_judgment",count_majority_judgment_top_n),("ranked_pairs",count_ranked_pairs_top_n)]:
        ballots=rows if method in ("score","star") else [({"grades":b["scores"]},w) for b,w in rows] if method=="majority_judgment" else [({"rank_groups":[[c for c in ids if c.startswith("a")],[c for c in ids if c.startswith("b")]]},60),({"rank_groups":[[c for c in ids if c.startswith("b")],[c for c in ids if c.startswith("a")]]},40)]
        assert all(c.startswith("a") for c in counter(ids,ballots,new_voting_rules(method,"p",5),"p").winners)


def test_random_literal_unit_voter_oracle_and_weight_scaling():
    rng=random.Random(1136);r=rules(3)
    for _ in range(250):
        rows=[({"scores":{c:rng.randrange(6) for c in "abcd"}},rng.randrange(4)) for __ in range(rng.randrange(1,10))]
        expected,q,totals,masses=unit_oracle("abcd",rows,r)
        result=count_allocated_score("abcd",rows,r,"p").method_result
        assert result["winners"]==expected and read_quantity(result["quota"])==q
        assert [{c:read_quantity(n) for c,n in row["totals"].items()} for row in result["rounds"]]==totals
        assert [read_quantity(row["remaining_weight_after"]) for row in result["rounds"]]==masses
        scaled=count_allocated_score("dcba",[(p,w*10**15) for p,w in reversed(rows)],r,"p").method_result
        assert scaled["winners"]==expected
        for small,big in zip(result["rounds"],scaled["rounds"]):
            assert [b["contribution"] for b in small["allocation_bands"]]==[b["contribution"] for b in big["allocation_bands"]]
            assert [b["allocated_fraction"] for b in small["allocation_bands"]]==[b["allocated_fraction"] for b in big["allocation_bands"]]


@pytest.mark.parametrize("rows",[[],[({"abstain":True},3)],[({"scores":{}},3)],[({"scores":{"a":5}},0)]])
def test_neutral_abstention_zero_weights_do_not_create_quota(rows):
    result=count_allocated_score("abc",rows,rules(),"p").method_result
    assert result["winners"]==[] and result["informative_weight"]==0 and read_quantity(result["quota"])==0


def test_partial_supported_and_frozen_private_aggregate_contract():
    r=rules(3);tally=count_allocated_score("abcd",[({"scores":{"a":5}},10**20),({"scores":{}},7),({"abstain":True},4)],r,"p")
    result=tally.method_result;assert result["winners"]==["a"] and result["unfilled_count"]==2
    assert result["informative_weight"]==10**20 and result["preference_weight"]==10**20+7
    record={"record_version":2,"num_winners":3,"method":"allocated_score","rules":public_voting_rules(r),"tie_seed":r["tie_seed"],"option_labels":dict(zip("abcd","ABCD")),"tally":tally.to_record(),"quorum_met":True,"official_winners":tally.winners}
    assert ExperimentalTally.from_record(record).winners==["a"]
    text=json.dumps(result)
    assert not any(key in text for key in ('user_id','ballots','profiles','delegator','cast_by'))
    assert r["allocation_order"]=="remaining_fraction_times_score" and r["arithmetic"]=="exact_rational_strings_v1"
    for key,value in [("quota",{"numerator":"01","denominator":"3"}),("remaining_weight",{"numerator":"0","denominator":"1"}),("winners",["a","b"]),("stop_totals",{"b":{"numerator":"1","denominator":"1"}})]:
        broken=deepcopy(record);broken["tally"]["method_result"][key]=value
        with pytest.raises(ValueError):ExperimentalTally.from_record(broken)
    bad=deepcopy(record);bad["tally"]["method_result"]["rounds"][0]["allocation_bands"][0]["user_id"]="private"
    with pytest.raises(ValueError):ExperimentalTally.from_record(bad)

    for target in ("result","round"):
        bad=deepcopy(record)
        row=bad["tally"]["method_result"]
        if target=="round":row=row["rounds"][0]
        row["voter_id"]="private"
        with pytest.raises(ValueError):ExperimentalTally.from_record(bad)
