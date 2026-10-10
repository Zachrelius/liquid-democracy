"""Independent matrix/DFS locking/Kahn oracle for one collective ordering."""
from copy import deepcopy
import hashlib,json,random
import pytest
from multiwinner_tally import count_ranked_pairs_top_n
from experimental_tally import count_ranked_pairs,ExperimentalTally
from voting_methods import new_voting_rules,public_voting_rules


def rules(k=2):
    r=new_voting_rules("ranked_pairs","p",k)
    r.update(tie_seed="34"*32,tie_commitment=hashlib.sha256(bytes.fromhex("34"*32)).hexdigest())
    return r


def priority(r,oid):
    raw=json.dumps(["candidate_priority_v1",r["tie_seed"],"p",oid],separators=(",",":"))
    return hashlib.sha256(raw.encode()).hexdigest(),oid


def oracle(ids,rows,r):
    eligible=sorted({oid for ballot,w in rows if w>0 and not ballot.get("abstain") for group in ballot["rank_groups"] for oid in group if oid in ids})
    matrix={a:{b:0 for b in eligible} for a in eligible}
    for ballot,w in rows:
        if not w or ballot.get("abstain"):continue
        rank={oid:index for index,group in enumerate(ballot["rank_groups"]) for oid in group}
        for a in eligible:
            for b in eligible:
                if rank.get(a,len(eligible))<rank.get(b,len(eligible)):matrix[a][b]+=w
    if not any(v for row in matrix.values() for v in row.values()):return [],matrix,[]
    edges=[(a,b,matrix[a][b]-matrix[b][a],matrix[a][b]) for a in eligible for b in eligible if matrix[a][b]>matrix[b][a]]
    edges.sort(key=lambda e:(-e[2],-e[3],priority(r,e[0]),priority(r,e[1])))
    locked=[]
    def path(a,b):
        if a==b:return True
        return any(path(y,b) for x,y,*_ in locked if x==a)
    for edge in edges:
        if not path(edge[1],edge[0]):locked.append(edge)
    todo=set(eligible);order=[]
    while todo:
        sources=[a for a in todo if not any(y==a and x in todo for x,y,*_ in locked)]
        chosen=min(sources,key=lambda a:priority(r,a));todo.remove(chosen);order.append(chosen)
    return order,matrix,locked


def assert_oracle(ids,rows,r):
    expected,matrix,edges=oracle(ids,rows,r)
    result=count_ranked_pairs_top_n(ids,rows,r,"p").method_result
    assert result["ranked_order"]==expected and result["pairwise"]==matrix
    assert [(e["winner"],e["loser"],e["margin"],e["support"]) for e in result["locked_edges"]]==edges
    assert all(expected.index(a)<expected.index(b) for a,b,*_ in edges)
    return result


def test_hand_strict_order_omission_and_unsupported_tail():
    rows=[({"rank_groups":[["a"],["b"],["c"]]},4),({"rank_groups":[["b"],["c"],["a"]]},2)]
    result=assert_oracle("abcd",rows,rules())
    assert result["ranked_order"]==["a","b","c"] and result["winners"]==["a","b"]
    assert result["ranked_weights"]["d"]==0 and "d" not in result["pairwise"]
    assert result["pairwise"]["a"]["b"]==4 and result["pairwise"]["b"]["a"]==2
    assert result["priority_used"]
    assert any(e["stage"]=="edge_priority" for e in result["tie_trace"])


def test_equal_strength_cycle_committed_edges_and_balanced_preferences():
    rows=[({"rank_groups":[["a"],["b"],["c"]]},1),({"rank_groups":[["b"],["c"],["a"]]},1),({"rank_groups":[["c"],["a"],["b"]]},1)]
    result=assert_oracle("abc",rows,rules())
    assert len(result["skipped_edges"])==1 and result["priority_used"]
    balanced=assert_oracle("abc",[({"rank_groups":[["a"],["b"],["c"]]},2),({"rank_groups":[["c"],["b"],["a"]]},2)],rules())
    assert balanced["ranked_order"]==sorted("abc",key=lambda oid:priority(rules(),oid))
    assert balanced["selection_boundary_tie"] and not balanced["no_result_reason"]


@pytest.mark.parametrize("rows",[[],[({"abstain":True},2)],[({"rank_groups":[]},2)],[({"rank_groups":[["a","b","c"]]},2)],[({"rank_groups":[["a"]]},2)],[({"rank_groups":[["a"],["b"]]},0)]])
def test_no_strict_preference_among_eligible_never_fabricates_result(rows):
    result=assert_oracle("abcd",rows,rules())
    assert result["winners"]==[] and result["no_result_reason"]=="no_strict_preferences"


def test_random_oracle_permutations_replication_and_old_first_choice():
    rng=random.Random(1135);r=rules()
    for _ in range(400):
        rows=[]
        for __ in range(rng.randrange(1,12)):
            ids=list("abcd");rng.shuffle(ids);ids=ids[:rng.randrange(5)]
            groups=[]
            for oid in ids:
                if groups and rng.randrange(3)==0:groups[-1].append(oid)
                else:groups.append([oid])
            rows.append(({"rank_groups":groups},rng.randrange(4)))
        result=assert_oracle("abcd",rows,r)
        assert count_ranked_pairs_top_n("dcba",list(reversed(rows)),r,"p").method_result==result
        expanded=[(ballot,1) for ballot,w in rows for _ in range(w)]
        assert count_ranked_pairs_top_n("abcd",expanded,r,"p").method_result==result
        if set(result["eligible_options"])==set("abcd"):
            old=rules(1);assert count_ranked_pairs("abcd",rows,old,"p").winners==result["winners"][:1]


def test_partial_pool_and_large_integer_weights_are_not_expanded():
    result=assert_oracle("abcd",[({"rank_groups":[["a"],["b"]]},10**40)],rules(3))
    assert result["winners"]==["a","b"] and result["unfilled_count"]==1
    assert result["pairwise"]["a"]["b"]==10**40


def test_frozen_fixed_graph_corruption_and_label_change():
    r=rules();tally=count_ranked_pairs_top_n("abc",[({"rank_groups":[["a"],["b"],["c"]]},3)],r,"p")
    record={"record_version":2,"num_winners":2,"method":"ranked_pairs","rules":public_voting_rules(r),"tie_seed":r["tie_seed"],"option_labels":dict(zip("abc","ABC")),"tally":tally.to_record(),"quorum_met":True,"official_winners":tally.winners}
    assert ExperimentalTally.from_record(record).winners==["a","b"]
    record["option_labels"]={"a":"Renamed","b":"Renamed also","c":"Other"}
    assert ExperimentalTally.from_record(record).winners==["a","b"]
    for key,value in [("ranked_order",["a","c","b"]),("locked_edges",[]),("ranked_weights",{"a":3,"b":3,"c":0}),("source_ties",[{"pool":["b","c"]}])]:
        broken=deepcopy(record);broken["tally"]["method_result"][key]=value
        with pytest.raises(ValueError):ExperimentalTally.from_record(broken)


def test_graph_is_locked_once_and_retains_all_edges_after_selections(monkeypatch):
    import multiwinner_tally
    original=multiwinner_tally._ranked_pairs_graph;calls=[]
    def observed(*args):
        calls.append(deepcopy(args[0]));return original(*args)
    monkeypatch.setattr(multiwinner_tally,"_ranked_pairs_graph",observed)
    rows=[({"rank_groups":[["a"],["b"],["c"],["d"]]},5)]
    r=count_ranked_pairs_top_n("abcd",rows,rules(3),"p").method_result
    assert len(calls)==1 and len(r["locked_edges"])==6
    assert r["winners"]==["a","b","c"]
    assert any(e["winner"]=="a" and e["loser"]=="d" for e in r["locked_edges"])
