"""Phase 110: real candidate/ballot/role side effects at every close site."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import pytest
from fastapi import HTTPException
import models
from tests.test_ranked_choice_voting import test_db, client, _create_user, _create_org, _create_membership, _auth_header

METHODS = ('star','score','ranked_pairs','majority_judgment')

@pytest.fixture
def election_org(test_db):
    org = _create_org(test_db, ['binary','approval','ranked_choice',*METHODS], slug='phase110')
    org.settings = {**org.settings, 'elections': {'enabled': True, 'trigger_sources': ['admin_direct','member_cosign']}}
    owner = _create_user(test_db,'p110-owner'); _create_membership(test_db,org,owner,'steward')
    candidates=[]
    for i in range(3):
        user=_create_user(test_db,f'p110-candidate{i}'); _create_membership(test_db,org,user,'member');candidates.append(user)
    title=models.OrgTitle(org_id=org.id,name='Secretary',fill_method='elected',cardinality_mode='single',bound_role='moderator',is_system=False)
    test_db.add(title);test_db.commit()
    return org,owner,candidates,title


def opened(client, fixture, method, **overrides):
    org,owner,candidates,title=fixture
    response=client.post(f'/api/orgs/{org.slug}/elections',headers=_auth_header(owner),json={'title_id':title.id,'voting_method':method,**overrides})
    assert response.status_code==201,response.text
    assert response.json()['voting_rules']['rule_id']
    assert 'tie_seed' not in response.json()['voting_rules']
    return response.json()['id']


def nominate_and_open(client, fixture, pid, number=3):
    org,owner,candidates,title=fixture
    for candidate in candidates[:number]:
        response=client.post(f'/api/orgs/{org.slug}/elections/{pid}/candidacies',headers=_auth_header(candidate))
        assert response.status_code==201,response.text
    response=client.post(f'/api/proposals/{pid}/advance',headers=_auth_header(owner),json={})
    assert response.status_code==200,response.text
    return response.json()['options']


def ballot(method, options, index=1):
    oid=options[index]['id']
    return {'rank_groups':[[oid]]} if method=='ranked_pairs' else {('grades' if method=='majority_judgment' else 'scores'):{oid:5}}


def close(client,db,fixture,pid,site):
    org,owner,*_=fixture
    if site=='worker':
        from sustained_majority_worker import _close_proposal_now
        proposal=db.get(models.Proposal,pid)
        status=_close_proposal_now(db,proposal,trigger='phase110_scoped_test',update_voting_end=False)
        db.commit();return status
    path=f'/api/orgs/{org.slug}/proposals/{pid}/advance' if site=='org' else f'/api/proposals/{pid}/advance'
    response=client.post(path,headers=_auth_header(owner),json={})
    assert response.status_code==200,response.text
    return response.json()['status']

@pytest.mark.parametrize('method',METHODS)
@pytest.mark.parametrize('site',('generic','org','worker'))
def test_exact_second_candidate_seated_frozen_once(client,test_db,election_org,method,site):
    org,owner,candidates,title=election_org
    pid=opened(client,election_org,method);options=nominate_and_open(client,election_org,pid)
    for voter in candidates:
        response=client.post(f'/api/proposals/{pid}/vote',headers=_auth_header(voter),json=ballot(method,options))
        assert response.status_code==200,response.text
    assert close(client,test_db,election_org,pid,site)=='passed'
    assignments=test_db.query(models.OrgTitleAssignment).filter_by(title_id=title.id).all()
    assert [row.user_id for row in assignments]==[candidates[1].id]
    membership=test_db.query(models.OrgMembership).filter_by(org_id=org.id,user_id=candidates[1].id).one()
    assert test_db.get(models.Role,membership.role_id).system_key=='moderator'
    proposal=test_db.get(models.Proposal,pid);record=deepcopy(proposal.final_method_result)
    assert record['election']['counting_winner_option_id']==options[1]['id']
    assert record['election']['winner_user_id']==candidates[1].id
    assert record['election']['installation']=='installed'
    assert record['option_labels'][options[1]['id']]==candidates[1].id
    final=client.get(f'/api/proposals/{pid}/results',headers=_auth_header(owner)).json()
    assert final['option_labels'][options[1]['id']]==candidates[1].display_name
    assert final['method_result']['election']['installation']=='installed'
    assert test_db.query(models.AuditLog).filter_by(target_id=pid,action='election.resolved').count()==1
    from elections import run_election_close_hook
    run_election_close_hook(test_db,proposal,proposal.status)
    candidates[1].display_name='Later renamed';membership.status='inactive'
    proposal.options[1].description='Edited option name';test_db.commit()
    assert client.get(f'/api/proposals/{pid}/results',headers=_auth_header(owner)).json()==final
    assert proposal.final_method_result==record
    assert test_db.query(models.AuditLog).filter_by(target_id=pid,action='election.resolved').count()==1

@pytest.mark.parametrize('method',METHODS)
@pytest.mark.parametrize('expression',('empty','abstain','bottom','equal'))
def test_no_first_declared_fallback(client,test_db,election_org,method,expression):
    org,owner,candidates,title=election_org
    pid=opened(client,election_org,method);options=nominate_and_open(client,election_org,pid)
    if expression!='empty':
        if expression=='abstain': data={'abstain':True}
        elif method=='ranked_pairs': data={'rank_groups':[] if expression=='bottom' else [[o['id'] for o in options]]}
        else: data={('grades' if method=='majority_judgment' else 'scores'):{o['id']:0 for o in options}}
        assert client.post(f'/api/proposals/{pid}/vote',headers=_auth_header(owner),json=data).status_code==200
    assert close(client,test_db,election_org,pid,'generic')=='failed'
    assert test_db.query(models.OrgTitleAssignment).filter_by(title_id=title.id).count()==0
    record=test_db.get(models.Proposal,pid).final_method_result
    assert record['election']['installation']=='not_installed'
    assert record['election']['reason']
    assert record['tally']['method_result']['winner'] is None

@pytest.mark.parametrize('method',METHODS)
@pytest.mark.parametrize('number',(0,1))
def test_uncontested_policy_is_not_a_fabricated_method_winner(client,test_db,election_org,method,number):
    org,owner,candidates,title=election_org
    pid=opened(client,election_org,method);nominate_and_open(client,election_org,pid,number)
    assert close(client,test_db,election_org,pid,'generic')=='passed'
    p=test_db.get(models.Proposal,pid)
    assert p.final_method_result['tally']['method_result']['winner'] is None
    assert p.final_method_result['election']['installation']==('installed' if number else 'not_installed')
    assert test_db.query(models.OrgTitleAssignment).filter_by(title_id=title.id).count()==number

@pytest.mark.parametrize('method',METHODS)
def test_quorum_failure_keeps_incumbent_and_roles(client,test_db,election_org,method):
    org,owner,candidates,title=election_org
    test_db.add(models.OrgTitleAssignment(title_id=title.id,user_id=owner.id));test_db.commit()
    pid=opened(client,election_org,method,quorum_threshold=1,slate_mode='refresh_slate')
    options=nominate_and_open(client,election_org,pid)
    assert client.post(f'/api/proposals/{pid}/vote',headers=_auth_header(candidates[1]),json=ballot(method,options)).status_code==200
    assert close(client,test_db,election_org,pid,'org')=='failed'
    assert [r.user_id for r in test_db.query(models.OrgTitleAssignment).filter_by(title_id=title.id)]==[owner.id]
    assert test_db.get(models.Proposal,pid).final_method_result['election']['reason']=='quorum_not_met'

@pytest.mark.parametrize('method',METHODS)
@pytest.mark.parametrize('patch',({'num_winners':2},{'approval_winner_config':{'min_winners':1,'max_winners':1,'approval_threshold':None}}, {'trigger':'scheduled'}))
def test_creation_rejects_incompatible_configuration(client,test_db,election_org,method,patch):
    org,owner,candidates,title=election_org
    response=client.post(f'/api/orgs/{org.slug}/elections',headers=_auth_header(owner),json={'title_id':title.id,'voting_method':method,**patch})
    assert response.status_code==400,response.text
    assert test_db.query(models.Proposal).count()==0

@pytest.mark.parametrize('method',METHODS)
@pytest.mark.parametrize('disabled',('method','elections','trigger','title','actor'))
def test_capability_and_role_gates(client,test_db,election_org,method,disabled):
    org,owner,candidates,title=election_org
    if disabled=='method':org.settings={**org.settings,'allowed_voting_methods':['binary']}
    if disabled=='elections':org.settings={**org.settings,'elections':{'enabled':False}}
    if disabled=='trigger':org.settings={**org.settings,'elections':{'enabled':True,'trigger_sources':[]}}
    if disabled=='title':title.fill_method='assigned'
    test_db.commit()
    response=client.post(f'/api/orgs/{org.slug}/elections',headers=_auth_header(candidates[0] if disabled=='actor' else owner),json={'title_id':title.id,'voting_method':method})
    assert response.status_code==(403 if disabled=='actor' else 400),response.text
    assert test_db.query(models.Proposal).count()==0

@pytest.mark.parametrize('method',METHODS)
def test_existing_election_survives_method_disabled_and_forbids_writeins(client,test_db,election_org,method):
    org,owner,candidates,title=election_org
    pid=opened(client,election_org,method);options=nominate_and_open(client,election_org,pid)
    org.settings={**org.settings,'allowed_voting_methods':['binary'],'allow_write_in_options':'always_on'};test_db.commit()
    assert client.post(f'/api/proposals/{pid}/options',headers=_auth_header(owner),json={'label':candidates[0].id}).status_code in (400,403)
    assert client.post(f'/api/orgs/{org.slug}/elections/{pid}/candidacies',headers=_auth_header(owner)).status_code==400
    assert client.post(f'/api/proposals/{pid}/vote',headers=_auth_header(candidates[1]),json=ballot(method,options)).status_code==200
    assert close(client,test_db,election_org,pid,'generic')=='passed'

@pytest.mark.parametrize('method',METHODS)
@pytest.mark.parametrize('stage',('assignment','audit'))
def test_unexpected_failure_rolls_back_slate_then_retry(client,test_db,election_org,method,stage,monkeypatch):
    import elections,experimental_elections,audit_utils
    org,owner,candidates,title=election_org
    test_db.add(models.OrgTitleAssignment(title_id=title.id,user_id=owner.id));test_db.commit()
    pid=opened(client,election_org,method,slate_mode='refresh_slate');options=nominate_and_open(client,election_org,pid)
    assert client.post(f'/api/proposals/{pid}/vote',headers=_auth_header(candidates[1]),json=ballot(method,options)).status_code==200
    module=elections if stage=='assignment' else audit_utils
    attribute='_apply_election_winner' if stage=='assignment' else 'log_audit_event'
    real=getattr(module,attribute)
    def injected(*args,**kwargs):
        value=real(*args,**kwargs)
        if stage=='assignment' or kwargs.get('action')=='election.resolved':raise RuntimeError('Injected election failure')
        return value
    monkeypatch.setattr(module,attribute,injected)
    with pytest.raises(RuntimeError,match='Injected election failure'):
        close(client,test_db,election_org,pid,'generic')
    test_db.expire_all();proposal=test_db.get(models.Proposal,pid)
    assert proposal.status=='voting' and proposal.final_method_result is None
    assert [r.user_id for r in test_db.query(models.OrgTitleAssignment).filter_by(title_id=title.id)]==[owner.id]
    member=test_db.query(models.OrgMembership).filter_by(org_id=org.id,user_id=candidates[1].id).one()
    assert test_db.get(models.Role,member.role_id).system_key=='member'
    monkeypatch.setattr(module,attribute,real)
    assert close(client,test_db,election_org,pid,'generic')=='passed'
    assert test_db.query(models.AuditLog).filter_by(target_id=pid,action='election.resolved').count()==1

@pytest.mark.parametrize('method',METHODS)
@pytest.mark.parametrize('patch', ({'budget_config': {}}, {'voting_rules': {'tie_seed':'forged'}}, {'final_method_result': {'winner':'forged'}}))
def test_client_cannot_supply_server_state(client,test_db,election_org,method,patch):
    org,owner,_,title=election_org
    response=client.post(f'/api/orgs/{org.slug}/elections',headers=_auth_header(owner),json={'title_id':title.id,'voting_method':method,**patch})
    assert response.status_code==422,response.text
    assert test_db.query(models.Proposal).count()==0

@pytest.mark.parametrize('method',METHODS)
def test_service_initializer_and_finalize_cannot_bypass_capability(test_db,election_org,method):
    from experimental_voting import initialize_rules
    from elections import finalize_election
    org,owner,_,title=election_org
    p=models.Proposal(title="Synthetic election",id=models._uuid(),org_id=org.id,author_id=owner.id,voting_method=method,num_winners=1,is_election=True,election_title_id=title.id,election_trigger='admin_direct',election_slate_mode='fill_vacancies')
    with pytest.raises(ValueError,match='database session'):initialize_rules(p)
    p.num_winners=2
    with pytest.raises(ValueError):initialize_rules(p,test_db)
    p.num_winners=1;p.budget_config={}
    with pytest.raises(HTTPException):initialize_rules(p,test_db)
    p.budget_config=None;initialize_rules(p,test_db);test_db.add(p);test_db.commit()
    with pytest.raises(ValueError,match='frozen'):finalize_election(test_db,p)
    assert test_db.query(models.OrgTitleAssignment).count()==0

@pytest.mark.parametrize('method',METHODS)
@pytest.mark.parametrize('mode', ('full','vacancy','refresh','inactive','membership','verification','floor'))
def test_installation_policy_keeps_seats_on_rejection(client,test_db,election_org,method,mode):
    org,owner,candidates,title=election_org
    incumbent=candidates[2]
    test_db.add(models.OrgTitleAssignment(title_id=title.id,user_id=incumbent.id))
    if mode=='vacancy':title.cardinality_mode='multi';title.max_holders=2
    if mode=='verification':org.settings={**org.settings,'verification_role_floors':{'moderator':'identity'}}
    test_db.commit()
    pid=opened(client,election_org,method,slate_mode='refresh_slate' if mode in ('refresh','inactive','membership','verification','floor') else 'fill_vacancies')
    options=nominate_and_open(client,election_org,pid)
    assert client.post(f'/api/proposals/{pid}/vote',headers=_auth_header(owner),json=ballot(method,options)).status_code==200
    if mode=='inactive':candidates[1].is_active=False
    if mode=='membership':test_db.query(models.OrgMembership).filter_by(org_id=org.id,user_id=candidates[1].id).one().status='inactive'
    if mode=='floor':
        # Demoting the only steward to moderator is forbidden even if a
        # valid ballot selected them. No runner-up is substituted.
        steward=test_db.query(models.Role).filter_by(org_id=org.id,system_key='steward').one()
        member=test_db.query(models.Role).filter_by(org_id=org.id,system_key='member').one()
        test_db.query(models.OrgMembership).filter_by(org_id=org.id,user_id=owner.id).one().role_id=member.id
        test_db.query(models.OrgMembership).filter_by(org_id=org.id,user_id=candidates[1].id).one().role_id=steward.id
    test_db.commit()
    assert close(client,test_db,election_org,pid,'worker')=='passed'
    p=test_db.get(models.Proposal,pid);outcome=p.final_method_result['election']
    assignments={r.user_id for r in test_db.query(models.OrgTitleAssignment).filter_by(title_id=title.id)}
    assert outcome['winner_user_id']==candidates[1].id
    if mode in ('vacancy','refresh'):
        assert outcome['installation']=='installed'
        assert assignments==({incumbent.id,candidates[1].id} if mode=='vacancy' else {candidates[1].id})
    else:
        assert outcome['installation']==('pending_verification' if mode=='verification' else 'rejected')
        assert assignments=={incumbent.id}
        assert outcome['title_granted'] is False

@pytest.mark.parametrize('method',METHODS)
def test_withdraw_cross_org_nomination_privacy_and_candidate_text_lock(client,test_db,election_org,method):
    from elections import declare_candidacy
    org,owner,candidates,title=election_org
    other=_create_org(test_db,['binary',method],slug='other');outsider=_create_user(test_db,'outsider');_create_membership(test_db,other,outsider,'member');test_db.commit()
    pid=opened(client,election_org,method);p=test_db.get(models.Proposal,pid)
    path=f'/api/orgs/{org.slug}/elections/{pid}/candidacies'
    assert client.post(path,headers=_auth_header(outsider)).status_code==403
    with pytest.raises(HTTPException):declare_candidacy(test_db,p,outsider.id)
    assert client.post(path,headers=_auth_header(candidates[0])).status_code==201
    assert client.delete(path,headers=_auth_header(candidates[0])).status_code==204
    assert client.post(path,headers=_auth_header(candidates[0])).status_code==201
    options=nominate_and_open(client,election_org,pid,0)
    assert len(options)==1
    assert client.patch(f'/api/proposals/{pid}',headers=_auth_header(owner),json={'options':[{'label':outsider.id},{'label':candidates[1].id}]}).status_code==400
    assert client.patch(f'/api/proposals/{pid}/options/{options[0]["id"]}',headers=_auth_header(owner),json={'label':outsider.id}).status_code in (400,409)
    assert client.get(f'/api/proposals/{pid}/results',headers=_auth_header(outsider)).status_code==404
    assert client.post(f'/api/proposals/{pid}/vote',headers=_auth_header(outsider),json=ballot(method,options,0)).status_code==403
    assert client.delete(path,headers=_auth_header(candidates[0])).status_code==400

@pytest.mark.parametrize('method',METHODS)
def test_delegation_weight_direct_override_abstention_retraction(client,test_db,election_org,method):
    org,owner,candidates,title=election_org
    org.settings={**org.settings,'weighted_voting':{'enabled':True,'unit_label':'shares'}}
    for i,user in enumerate([owner,*candidates]):test_db.query(models.OrgMembership).filter_by(org_id=org.id,user_id=user.id).one().voting_weight=[2,3,1,1][i]
    test_db.add(models.Delegation(org_id=org.id,delegator_id=owner.id,delegate_id=candidates[0].id,chain_behavior='accept_sub'));test_db.commit()
    pid=opened(client,election_org,method);options=nominate_and_open(client,election_org,pid)
    path=f'/api/proposals/{pid}'
    assert client.post(path+'/vote',headers=_auth_header(candidates[0]),json=ballot(method,options)).status_code==200
    assert client.get(path+'/results',headers=_auth_header(owner)).json()['total_ballots_cast']=='5'
    assert client.post(path+'/vote',headers=_auth_header(owner),json=ballot(method,options,0)).status_code==200
    assert client.get(path+'/results',headers=_auth_header(owner)).json()['winners']==[options[1]['id']]
    assert client.post(path+'/vote',headers=_auth_header(owner),json={'abstain':True}).status_code==200
    assert client.get(path+'/results',headers=_auth_header(owner)).json()['total_abstain']=='2'
    assert client.delete(path+'/vote',headers=_auth_header(owner)).status_code==204
    assert client.get(path+'/results',headers=_auth_header(owner)).json()['total_abstain']=='0'
    assert close(client,test_db,election_org,pid,'generic')=='passed'
    assert test_db.get(models.Proposal,pid).final_method_result['election']['winner_user_id']==candidates[1].id

@pytest.mark.parametrize('method',METHODS)
def test_missing_rules_malformed_ballot_and_committed_tie(client,test_db,election_org,method):
    org,owner,candidates,title=election_org
    pid=opened(client,election_org,method);options=nominate_and_open(client,election_org,pid,2)
    path=f'/api/proposals/{pid}'
    assert client.post(path+'/vote',headers=_auth_header(owner),json={'scores':{'foreign':6}}).status_code==422
    p=test_db.get(models.Proposal,pid);rules=deepcopy(p.voting_rules);p.voting_rules=None;test_db.commit()
    with pytest.raises(ValueError):close(client,test_db,election_org,pid,'worker')
    test_db.rollback();p.voting_rules=rules;test_db.commit()
    for i,user in enumerate(candidates[:2]):assert client.post(path+'/vote',headers=_auth_header(user),json=ballot(method,options,i)).status_code==200
    live=client.get(path+'/results',headers=_auth_header(owner)).json()
    assert live['method_result']['priority_used'] is True
    from voting_methods import candidate_priority
    expected=min([o['id'] for o in options],key=lambda oid:candidate_priority(rules,pid,oid))
    assert live['winners']==[expected]
    assert close(client,test_db,election_org,pid,'worker')=='passed'
    outcome=p.final_method_result['election']
    assert outcome['counting_winner_option_id']==expected
    assert outcome['winner_user_id']==next(o['label'] for o in options if o['id']==expected)

@pytest.mark.parametrize('method',METHODS)
def test_member_cosign_creation_rules_and_suborg_service_scope(client,test_db,election_org,method):
    from experimental_voting import initialize_rules
    from elections import declare_candidacy
    org,owner,candidates,title=election_org
    response=client.post(f'/api/orgs/{org.slug}/elections',headers=_auth_header(candidates[0]),json={'title_id':title.id,'voting_method':method,'trigger':'member_cosign'})
    assert response.status_code==201,response.text
    assert response.json()['is_cosign_gated'] is True
    child=models.Organization(name='Child',slug='child',parent_org_id=org.id,settings={'allowed_voting_methods':[method]})
    test_db.add(child);test_db.flush()
    p=models.Proposal(title="Synthetic election",id=models._uuid(),author_id=owner.id,org_id=org.id,sub_org_id=child.id,voting_method=method,num_winners=1,is_election=True,election_title_id=title.id,election_trigger='admin_direct',election_slate_mode='fill_vacancies',status='deliberation')
    initialize_rules(p,test_db);test_db.add(p);test_db.commit()
    with pytest.raises(HTTPException,match='suborg'):declare_candidacy(test_db,p,candidates[1].id)
    test_db.add(models.SubOrgMembership(sub_org_id=child.id,user_id=candidates[1].id,role_id=test_db.query(models.Role).filter_by(org_id=org.id,system_key='member').one().id,status='active'));test_db.commit()
    declare_candidacy(test_db,p,candidates[1].id);test_db.commit()
    assert test_db.query(models.ElectionCandidacy).filter_by(proposal_id=p.id).count()==1

@pytest.mark.parametrize('method',METHODS)
def test_nomination_pre_voting_remains_closed_even_if_org_allows_it(client,test_db,election_org,method):
    org,owner,_,_=election_org
    org.settings={**org.settings,'pre_voting':{'allow_mode':'always_on'}};test_db.commit()
    pid=opened(client,election_org,method)
    assert client.post(f'/api/proposals/{pid}/vote',headers=_auth_header(owner),json={'abstain':True}).status_code==400
    assert test_db.query(models.Vote).filter_by(proposal_id=pid).count()==0
