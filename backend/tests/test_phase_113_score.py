"""Hand-counted Score and real ballot/office lifecycle regression fixtures."""
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
import pytest
from fastapi import HTTPException
import models
from experimental_tally import ExperimentalTally, count_score
from multiwinner_tally import count_score_top_n
from voting_methods import new_voting_rules, public_voting_rules
from tests.test_ranked_choice_voting import test_db, client, _auth_header
from tests.test_phase_110_elections import election_org, opened, nominate_and_open, close


def rules(k=2):
    value=new_voting_rules("score","p",k)
    value.update(tie_seed="12"*32,tie_commitment=hashlib.sha256(bytes.fromhex("12"*32)).hexdigest())
    return value


def test_hand_totals_weighted_replication_permutation_and_zero_tail():
    ballots=[({"scores":{"a":5,"b":4,"c":3}},2),({"scores":{"a":2,"b":2,"c":2}},1)]
    r=rules()
    tally=count_score_top_n(["a","b","c","d"],ballots,r,"p")
    assert tally.method_result["scores"]=={"a":12,"b":10,"c":8,"d":0}
    assert tally.winners==["a","b"]
    assert tally.method_result["ranked_order"]==["a","b","c"]
    assert not tally.tied
    expanded=[(ballot,1) for ballot,weight in ballots for _ in range(weight)]
    assert count_score_top_n(["d","c","b","a"],list(reversed(expanded)),r,"p").method_result==tally.method_result
    old=count_score(["a","b","c","d"],ballots,new_voting_rules("score","p"),"p")
    assert old.winners==["a"] and "winners" not in old.method_result


@pytest.mark.parametrize("ballots",[[],[({"abstain":True},3)],[({"scores":{}},3)],[({"scores":{"a":5}},0)]])
def test_no_support_has_no_selections(ballots):
    tally=count_score_top_n(["a","b","c"],ballots,rules(),"p")
    assert tally.winners==[]
    assert tally.method_result["unfilled_count"]==2
    assert tally.method_result["unfilled_reason"]=="support_exhausted"


def test_partial_and_boundary_priority_is_committed_independent_oracle():
    r=rules()
    result=count_score_top_n(["a","b","c"],[({"scores":{"a":5,"b":3,"c":3}},1)],r,"p").method_result
    def priority(oid):
        raw=json.dumps(["candidate_priority_v1",r["tie_seed"],"p",oid],ensure_ascii=True,separators=(",",":"))
        return hashlib.sha256(raw.encode("ascii")).hexdigest(),oid
    assert result["winners"]==["a",min(["b","c"],key=priority)]
    assert result["selection_boundary_tie"] and result["priority_used"]
    partial=count_score_top_n(["a","b","c"],[({"scores":{"a":5}},10**18)],r,"p")
    assert partial.winners==["a"] and partial.method_result["unfilled_count"]==1
    assert partial.method_result["scores"]["a"]==5*10**18


@pytest.mark.parametrize("key,value",[("winners",["c","a"]),("rule_id","score_0_5_sum_v1"),("filled_count",1),("priority_used",0),("scores",{"a":5,"b":5,"c":0})])
def test_frozen_aggregate_tampering_fails_loudly(key,value):
    r=rules();tally=count_score_top_n(["a","b","c"],[({"scores":{"a":5,"b":3}},1)],r,"p")
    record={"record_version":2,"num_winners":2,"method":"score","rules":public_voting_rules(r),"tie_seed":r["tie_seed"],"option_labels":{"a":"A","b":"B","c":"C"},"tally":tally.to_record(),"quorum_met":True,"official_winners":["a","b"]}
    assert ExperimentalTally.from_record(record).winners==["a","b"]
    record["tally"]["method_result"][key]=value
    with pytest.raises(ValueError):ExperimentalTally.from_record(record)


@pytest.fixture
def multi_org(test_db,election_org):
    org,owner,candidates,title=election_org
    org.settings={**org.settings,"allowed_multiwinner_methods":["score","star","majority_judgment","ranked_pairs"],"allowed_voting_methods":[*org.settings["allowed_voting_methods"],"allocated_score"]}
    title.cardinality_mode="multi";title.max_holders=2
    test_db.commit()
    return election_org


def proposal_method(client,owner,pid):
    return client.get(f"/api/proposals/{pid}",headers=_auth_header(owner)).json()["voting_method"]


def method_payload(method,scores):
    if method=="ranked_pairs":return {"rank_groups":[[oid] for oid in sorted(scores,key=lambda oid:-scores[oid])]}
    return {"grades" if method=="majority_judgment" else "scores":scores}


def cast_set(client,fixture,pid,options,partial=False):
    org,owner,candidates,title=fixture
    by_user={o["label"]:o["id"] for o in options}
    scores={by_user[candidates[0].id]:5}
    if not partial:scores[by_user[candidates[1].id]]=3
    response=client.post(f"/api/proposals/{pid}/vote",headers=_auth_header(owner),json=method_payload(proposal_method(client,owner,pid),scores))
    assert response.status_code==200,response.text
    return [by_user[u.id] for u in candidates[:1 if partial else 2]]


@pytest.mark.parametrize("site",["generic","org","worker"])
@pytest.mark.parametrize("method",["score","star","majority_judgment","ranked_pairs","allocated_score"])
def test_complete_set_installed_frozen_and_retry_idempotent(client,test_db,multi_org,site,method):
    org,owner,candidates,title=multi_org
    pid=opened(client,multi_org,method,num_winners=2)
    options=nominate_and_open(client,multi_org,pid)
    expected=cast_set(client,multi_org,pid,options)
    ballot=test_db.query(models.Vote).filter_by(proposal_id=pid).one().ballot
    assert (ballot["rank_groups"][0]==[expected[0]] if method=="ranked_pairs" else ballot["grades" if method=="majority_judgment" else "scores"][expected[0]]==5)
    assert close(client,test_db,multi_org,pid,site)=="passed"
    p=test_db.get(models.Proposal,pid);record=deepcopy(p.final_method_result)
    assert record["record_version"]==2 and record["official_winners"]==expected
    assert record["election"]["winner_user_ids"]==[u.id for u in candidates[:2]]
    assert {a.user_id for a in test_db.query(models.OrgTitleAssignment).filter_by(title_id=title.id)}=={u.id for u in candidates[:2]}
    for user in candidates[:2]:
        member=test_db.query(models.OrgMembership).filter_by(org_id=org.id,user_id=user.id).one()
        assert test_db.get(models.Role,member.role_id).system_key=="moderator"
    final=client.get(f"/api/proposals/{pid}/results",headers=_auth_header(owner)).json()
    from elections import run_election_close_hook
    run_election_close_hook(test_db,p,p.status)
    org.settings={**org.settings,"allowed_multiwinner_methods":[]};candidates[0].display_name="Changed";test_db.commit()
    assert client.get(f"/api/proposals/{pid}/results",headers=_auth_header(owner)).json()==final
    assert p.final_method_result==record
    assert test_db.query(models.AuditLog).filter_by(action="election.resolved",target_id=pid).count()==1


@pytest.mark.parametrize("number",[0,1,2])
@pytest.mark.parametrize("method",["score","star","majority_judgment","ranked_pairs","allocated_score"])
def test_uncontested_set_policy_is_distinct(client,test_db,multi_org,number,method):
    org,owner,candidates,title=multi_org
    pid=opened(client,multi_org,method,num_winners=2)
    nominate_and_open(client,multi_org,pid,number)
    assert close(client,test_db,multi_org,pid,"worker")=="passed"
    outcome=test_db.get(models.Proposal,pid).final_method_result["election"]
    assert outcome["policy"]==("uncontested" if number else None)
    assert len(outcome["winner_user_ids"])==number
    assert test_db.query(models.OrgTitleAssignment).filter_by(title_id=title.id).count()==number


@pytest.mark.parametrize("case",["verification","inactive","capacity","partial_refresh","partial_fill","quorum"])
@pytest.mark.parametrize("method",["score","star","majority_judgment","ranked_pairs","allocated_score"])
def test_whole_set_preflight_preserves_incumbents(client,test_db,multi_org,case,method):
    org,owner,candidates,title=multi_org
    partial_rp=method=="ranked_pairs" and case in ("partial_fill","partial_refresh")
    if partial_rp:
        from tests.test_ranked_choice_voting import _create_user,_create_membership
        fourth=_create_user(test_db,"p113-rp-fourth");_create_membership(test_db,org,fourth,"member");candidates.append(fourth)
        title.max_holders=3
    incumbent=candidates[2]
    test_db.add(models.OrgTitleAssignment(title_id=title.id,user_id=incumbent.id))
    if case=="verification":org.settings={**org.settings,"verification_role_floors":{"moderator":"identity"}}
    test_db.commit()
    pid=opened(client,multi_org,method,num_winners=3 if partial_rp else 2,slate_mode="fill_vacancies" if case in ("capacity","partial_fill") else "refresh_slate",quorum_threshold=1 if case=="quorum" else 0)
    options=nominate_and_open(client,multi_org,pid,number=4 if partial_rp else 3)
    cast_set(client,multi_org,pid,options,partial=not partial_rp and case in ("partial_fill","partial_refresh"))
    if case=="inactive":candidates[1].is_active=False
    test_db.commit()
    assert close(client,test_db,multi_org,pid,"worker")==("failed" if case=="quorum" else "passed")
    outcome=test_db.get(models.Proposal,pid).final_method_result["election"]
    holders={r.user_id for r in test_db.query(models.OrgTitleAssignment).filter_by(title_id=title.id)}
    if case=="partial_fill":
        assert outcome["installation"]=="installed" and holders=={incumbent.id,*[u.id for u in candidates[:2 if partial_rp else 1]]}
    else:
        assert outcome["installation"]==("pending_verification" if case=="verification" else "not_installed" if case=="quorum" else "rejected")
        assert holders=={incumbent.id}
        for user in candidates[:2]:
            member=test_db.query(models.OrgMembership).filter_by(org_id=org.id,user_id=user.id).one()
            assert test_db.get(models.Role,member.role_id).system_key=="member"
    if case=="partial_refresh":assert outcome["reason"]=="partial_selection_cannot_refresh_slate"


@pytest.mark.parametrize("stage",["second_assignment","expected_second","audit"])
@pytest.mark.parametrize("method",["score","star","majority_judgment","ranked_pairs","allocated_score"])
def test_atomic_second_assignment_and_audit_failures(client,test_db,multi_org,stage,monkeypatch,method):
    import elections,audit_utils
    org,owner,candidates,title=multi_org
    test_db.add(models.OrgTitleAssignment(title_id=title.id,user_id=candidates[2].id));test_db.commit()
    pid=opened(client,multi_org,method,num_winners=2,slate_mode="refresh_slate")
    options=nominate_and_open(client,multi_org,pid);cast_set(client,multi_org,pid,options)
    module=audit_utils if stage=="audit" else elections
    key="log_audit_event" if stage=="audit" else "_apply_election_winner"
    original=getattr(module,key);calls=[]
    def injected(*args,**kwargs):
        result=original(*args,**kwargs)
        calls.append(True)
        if (stage=="audit" and kwargs.get("action")=="election.resolved") or (stage!="audit" and len(calls)==2):
            if stage=="expected_second":raise HTTPException(400,"assignment_policy_changed")
            raise RuntimeError("synthetic second-step failure")
        return result
    monkeypatch.setattr(module,key,injected)
    if stage=="expected_second":
        assert close(client,test_db,multi_org,pid,"worker")=="passed"
        assert test_db.get(models.Proposal,pid).final_method_result["election"]["installation"]=="rejected"
    else:
        with pytest.raises(RuntimeError,match="synthetic second-step"):close(client,test_db,multi_org,pid,"worker")
    test_db.expire_all();p=test_db.get(models.Proposal,pid)
    assert {r.user_id for r in test_db.query(models.OrgTitleAssignment).filter_by(title_id=title.id)}=={candidates[2].id}
    for user in candidates[:2]:
        member=test_db.query(models.OrgMembership).filter_by(org_id=org.id,user_id=user.id).one()
        assert test_db.get(models.Role,member.role_id).system_key=="member"
    if stage!="expected_second":
        assert p.status=="voting" and p.final_method_result is None
        monkeypatch.setattr(module,key,original)
        assert close(client,test_db,multi_org,pid,"worker")=="passed"
        assert test_db.query(models.AuditLog).filter_by(action="election.resolved",target_id=pid).count()==1


def test_stability_compares_set_and_unfilled_reason():
    from sustained_majority import ExperimentalSnapshotPoint as Point, experimental_window_stable
    now=datetime(2026,1,1);cutoff=now-timedelta(hours=1)
    def point(when,winners,**kwargs):
        return Point(simulated_time=when,winners=tuple(winners),total_ballots_cast=5,total_eligible=5,option_set_version="same",quorum_met=True,meaningful=True,priority_used=False,requested_count=2,**kwargs)
    a=point(cutoff,["a","b"]);b=point(now,["b","a"])
    assert experimental_window_stable([a,b],cutoff,now)
    assert not experimental_window_stable([a,point(now,["a"],unfilled_reason="support_exhausted")],cutoff,now)
    assert not experimental_window_stable([a,point(now,["a","c"])],cutoff,now)


@pytest.mark.parametrize("k",[True,2.0,"2",0,121])
def test_strict_count_rejected_in_election_schema(client,test_db,multi_org,k):
    org,owner,candidates,title=multi_org
    response=client.post(f"/api/orgs/{org.slug}/elections",headers=_auth_header(owner),json={"title_id":title.id,"voting_method":"score","num_winners":k})
    assert response.status_code==422,response.text
    assert test_db.query(models.Proposal).count()==0


def ordinary(client,fixture,k=2,method="score"):
    org,owner,*_=fixture
    response=client.post(f"/api/orgs/{org.slug}/proposals",headers=_auth_header(owner),json={"title":"Synthetic choices","voting_method":method,"num_winners":k,"options":[{"label":name} for name in ("A","B","C")]})
    assert response.status_code==201,response.text
    return response.json()


def test_ordinary_draft_count_reset_and_grandfathered_seed(client,test_db,multi_org):
    org,owner,*_=multi_org
    org.settings={**org.settings,"pre_voting":{"allowed_mode":"always_on"}};test_db.commit()
    p=ordinary(client,multi_org);pid=p["id"]
    old_seed=test_db.get(models.Proposal,pid).voting_rules["tie_seed"]
    # Real preliminary ballot from deliberation, retained when a draft is reopened.
    proposal=test_db.get(models.Proposal,pid);proposal.status="deliberation";test_db.commit()
    response=client.post(f"/api/proposals/{pid}/vote",headers=_auth_header(owner),json={"scores":{p["options"][0]["id"]:5}})
    assert response.status_code==200,response.text
    proposal.status="draft";test_db.commit()
    assert client.patch(f"/api/proposals/{pid}",headers=_auth_header(owner),json={"num_winners":3}).status_code==409
    assert test_db.query(models.Vote).filter_by(proposal_id=pid).count()==1
    saved=client.patch(f"/api/proposals/{pid}",headers=_auth_header(owner),json={"num_winners":3,"confirm_ballot_reset":True})
    assert saved.status_code==200,saved.text
    assert test_db.query(models.Vote).filter_by(proposal_id=pid).count()==0
    proposal=test_db.get(models.Proposal,pid);seed=proposal.voting_rules["tie_seed"]
    assert seed!=old_seed and proposal.voting_rules["num_winners"]==3
    org.settings={**org.settings,"allowed_multiwinner_methods":[]};test_db.commit()
    saved=client.patch(f"/api/proposals/{pid}",headers=_auth_header(owner),json={"num_winners":3,"title":"Kept rules"})
    assert saved.status_code==200,saved.text
    assert proposal.voting_rules["tie_seed"]==seed
    assert client.patch(f"/api/proposals/{pid}",headers=_auth_header(owner),json={"num_winners":2,"confirm_ballot_reset":True}).status_code==400
    assert client.post(f"/api/orgs/{org.slug}/proposals",headers=_auth_header(owner),json={"title":"Clone","voting_method":"score","num_winners":3,"options":[{"label":name} for name in ("A","B","C")]}).status_code==400


@pytest.mark.parametrize("site",["generic","org","worker"])
@pytest.mark.parametrize("method",["score","star","majority_judgment","ranked_pairs","allocated_score"])
def test_ordinary_weighted_delegation_neutral_override_quorum_and_frozen(client,test_db,multi_org,site,method):
    org,owner,candidates,title=multi_org
    org.settings={**org.settings,"weighted_voting":{"enabled":True,"unit_label":"shares"}}
    for user,weight in zip([owner,*candidates],[7,2,3,0]):
        test_db.query(models.OrgMembership).filter_by(org_id=org.id,user_id=user.id).one().voting_weight=weight
    test_db.add(models.Delegation(org_id=org.id,delegator_id=owner.id,delegate_id=candidates[0].id,chain_behavior="accept_sub"));test_db.commit()
    p=ordinary(client,multi_org,method=method);pid=p["id"];options=p["options"]
    # Draft -> deliberation -> voting follows the two actual manual transitions.
    for _ in range(2):
        r=client.post(f"/api/proposals/{pid}/advance",headers=_auth_header(owner),json={})
        assert r.status_code==200,r.text
    path=f"/api/proposals/{pid}"
    field="rank_groups" if method=="ranked_pairs" else "grades" if method=="majority_judgment" else "scores"
    assert client.post(path+"/vote",headers=_auth_header(candidates[0]),json=method_payload(method,{options[0]["id"]:5,options[1]["id"]:3})).status_code==200
    live=client.get(path+"/results",headers=_auth_header(owner)).json()
    assert live["total_ballots_cast"]=="9"
    assert (live["method_result"]["pairwise"][options[0]["id"]][options[1]["id"]]=="9" if field=="rank_groups" else live["method_result"]["grade_histograms"][options[0]["id"]][5]=="9" if field=="grades" else live["method_result"]["scores"][options[0]["id"]]=="45")
    assert client.post(path+"/vote",headers=_auth_header(owner),json=method_payload(method,{})).status_code==200
    live=client.get(path+"/results",headers=_auth_header(owner)).json()
    assert live["total_ballots_cast"]=="9"
    assert (live["method_result"]["pairwise"][options[0]["id"]][options[1]["id"]]=="2" if field=="rank_groups" else live["method_result"]["grade_histograms"][options[0]["id"]]==["7","0","0","0","0","2"] if field=="grades" else live["method_result"]["scores"][options[0]["id"]]=="10")
    assert client.post(path+"/vote",headers=_auth_header(owner),json={"abstain":True}).status_code==200
    assert client.get(path+"/results",headers=_auth_header(owner)).json()["total_abstain"]=="7"
    assert client.delete(path+"/vote",headers=_auth_header(owner)).status_code==204
    assert close(client,test_db,multi_org,pid,site)=="passed"
    final=client.get(path+"/results",headers=_auth_header(owner)).json()
    assert final["winners"]==[o["id"] for o in options[:2]]
    test_db.query(models.OrgMembership).filter_by(org_id=org.id,user_id=owner.id).one().voting_weight=1
    org.settings={"allowed_voting_methods":["binary"]};test_db.commit()
    assert client.get(path+"/results",headers=_auth_header(owner)).json()==final


def test_contested_ordinary_cannot_start_with_count_above_options(client,test_db,multi_org):
    org,owner,*_=multi_org
    p=ordinary(client,multi_org,k=4)
    for expected in (200,400):
        r=client.post(f"/api/proposals/{p['id']}/advance",headers=_auth_header(owner),json={})
        assert r.status_code==expected,r.text
    assert test_db.get(models.Proposal,p["id"]).status=="deliberation"


@pytest.mark.parametrize("method",["score","star","majority_judgment","ranked_pairs","allocated_score"])
def test_draft_departure_from_budget_clears_incompatible_budget_config(client,test_db,multi_org,method):
    org,owner,*_=multi_org
    # Reopened synthetic draft with actual stored budget configuration.
    org.settings={**org.settings,"allowed_voting_methods":[*org.settings["allowed_voting_methods"],"budget_allocation"]};test_db.commit()
    response=client.post(f"/api/orgs/{org.slug}/proposals",headers=_auth_header(owner),json={"title":"Budget draft","voting_method":"budget_allocation","budget_config":{"mode":"allocation","envelope":1000},"options":[{"label":"A"},{"label":"B"}]})
    assert response.status_code==201,response.text
    pid=response.json()["id"]
    changed=client.patch(f"/api/proposals/{pid}",headers=_auth_header(owner),json={"voting_method":method,"num_winners":2,"confirm_ballot_reset":True})
    assert changed.status_code==200,changed.text
    assert changed.json()["budget_config"] is None
    assert test_db.get(models.Proposal,pid).voting_rules["num_winners"]==2


@pytest.mark.parametrize("method",["score","star","majority_judgment","ranked_pairs","allocated_score"])
def test_real_null_child_inherits_creation_count_and_parent_restrictions(client,test_db,multi_org,method):
    org,owner,*_=multi_org
    child=models.Organization(name="Fictional child",slug="phase113-null-child",parent_org=org,settings={"allowed_voting_methods":None,"allowed_multiwinner_methods":None,"allowed_budget_aggregations":None})
    test_db.add(child);test_db.commit()
    payload={"title":"Inherited multiple winners","sub_org_id":child.id,"voting_method":method,"num_winners":2,"options":[{"label":"A"},{"label":"B"},{"label":"C"}]}
    response=client.post(f"/api/orgs/{org.slug}/proposals",headers=_auth_header(owner),json=payload)
    assert response.status_code==201,response.text
    pid=response.json()["id"]
    assert response.json()["num_winners"]==2 and response.json()["voting_rules"]["num_winners"]==2
    assert test_db.get(models.Proposal,pid).num_winners==2
    org.settings={**org.settings,"allowed_voting_methods":["binary"]};test_db.commit()
    blocked=client.post(f"/api/orgs/{org.slug}/proposals",headers=_auth_header(owner),json=payload)
    assert blocked.status_code==400,blocked.text
    unchanged=client.patch(f"/api/proposals/{pid}",headers=_auth_header(owner),json={"title":"Grandfathered inherited count","num_winners":2})
    assert unchanged.status_code==200,unchanged.text
    assert unchanged.json()["voting_rules"]==response.json()["voting_rules"]


@pytest.mark.parametrize("method",["score","star","majority_judgment","ranked_pairs","allocated_score"])
def test_import_fresh_rules_global_rejection_and_early_privacy(client,test_db,multi_org,method):
    org,owner,*_=multi_org
    payload={"title":"Fresh independent import","voting_method":method,"num_winners":2,"options":[{"label":"A"},{"label":"B"},{"label":"C"}]}
    preview=client.post(f"/api/orgs/{org.slug}/proposals/import-preview",headers=_auth_header(owner),files={"file":("choices.json",json.dumps(payload),"application/json")})
    assert preview.status_code==200,preview.text
    assert preview.json()["proposal"]["num_winners"]==2
    first=client.post(f"/api/orgs/{org.slug}/proposals",headers=_auth_header(owner),json=payload)
    second=client.post(f"/api/orgs/{org.slug}/proposals",headers=_auth_header(owner),json=payload)
    assert first.status_code==second.status_code==201
    one=test_db.get(models.Proposal,first.json()["id"]);two=test_db.get(models.Proposal,second.json()["id"])
    assert one.voting_rules["tie_seed"]!=two.voting_rules["tie_seed"]
    # Actual generic global create rejects this method even for platform admins.
    owner.is_admin=True;test_db.commit()
    global_create=client.post("/api/proposals",headers=_auth_header(owner),json=payload)
    assert global_create.status_code==400,global_create.text
    owner.is_admin=False;one.status="deliberation";one.allow_pre_voting=True;one.show_votes_during_deliberation=False;test_db.commit()
    path=f"/api/proposals/{one.id}";oid=first.json()["options"][0]["id"]
    vote=client.post(path+"/vote",headers=_auth_header(owner),json=method_payload(method,{oid:5}))
    assert vote.status_code==200,vote.text
    assert client.get(path+"/results",headers=_auth_header(owner)).status_code==404
    assert client.get(path+"/vote-graph",headers=_auth_header(owner)).status_code==404
    assert client.get(path+"/my-vote",headers=_auth_header(owner)).json()["is_direct"] is True
    assert "tie_seed" not in client.get(path,headers=_auth_header(owner)).json()["voting_rules"]
    org.settings={**org.settings,"allowed_voting_methods":["binary"]};test_db.commit()
    rejected=client.post(f"/api/orgs/{org.slug}/proposals/import-preview",headers=_auth_header(owner),files={"file":("choices.json",json.dumps(payload),"application/json")})
    assert rejected.status_code==422,rejected.text
