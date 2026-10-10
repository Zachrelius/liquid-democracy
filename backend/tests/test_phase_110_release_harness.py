"""Release helper boundaries + final policy/notification transaction checks."""
import pytest
from fastapi import HTTPException
import models
from tests.test_phase_110_elections import election_org, METHODS, opened, nominate_and_open, ballot, close
from tests.test_ranked_choice_voting import test_db,client,_auth_header,_create_user,_create_membership
from scripts.phase110_release_qa import bootstrap,safety,worker_close,USERNAMES

@pytest.mark.parametrize('method',METHODS)
def test_expected_assignment_rejection_rolls_back_staged_grant(client,test_db,election_org,method,monkeypatch):
    import elections
    org,owner,candidates,title=election_org
    test_db.add(models.OrgTitleAssignment(title_id=title.id,user_id=owner.id));test_db.commit()
    pid=opened(client,election_org,method,slate_mode='refresh_slate');options=nominate_and_open(client,election_org,pid)
    assert client.post(f'/api/proposals/{pid}/vote',headers=_auth_header(candidates[1]),json=ballot(method,options)).status_code==200
    real=elections._apply_election_winner
    def reject_after_grant(*args,**kwargs):
        real(*args,**kwargs)
        raise HTTPException(400,'Synthetic late policy rejection')
    monkeypatch.setattr(elections,'_apply_election_winner',reject_after_grant)
    assert close(client,test_db,election_org,pid,'generic')=='passed'
    outcome=test_db.get(models.Proposal,pid).final_method_result['election']
    assert outcome['installation']=='rejected' and outcome['title_granted'] is False
    assert [a.user_id for a in test_db.query(models.OrgTitleAssignment).filter_by(title_id=title.id)]==[owner.id]
    member=test_db.query(models.OrgMembership).filter_by(org_id=org.id,user_id=candidates[1].id).one()
    assert test_db.get(models.Role,member.role_id).system_key=='member'
    assert test_db.query(models.AuditLog).filter_by(target_id=title.id,action='title.assigned').count()==0

@pytest.mark.parametrize('method',METHODS)
def test_notification_intent_failure_rolls_back_office_then_single_retry(client,test_db,election_org,method,monkeypatch):
    import proposal_lifecycle
    org,owner,candidates,title=election_org
    pid=opened(client,election_org,method);options=nominate_and_open(client,election_org,pid)
    assert client.post(f'/api/proposals/{pid}/vote',headers=_auth_header(owner),json=ballot(method,options)).status_code==200
    test_db.add(models.NotificationPreference(user_id=owner.id,event_type='proposal.closed',channel='in_app',enabled=True));test_db.commit()
    real=proposal_lifecycle.emit_notification
    def fail(*args,**kwargs):
        real(*args,**kwargs);raise RuntimeError('Injected notification failure')
    monkeypatch.setattr(proposal_lifecycle,'emit_notification',fail)
    with pytest.raises(RuntimeError,match='notification'):close(client,test_db,election_org,pid,'org')
    test_db.expire_all();p=test_db.get(models.Proposal,pid)
    assert p.status=='voting' and p.final_method_result is None
    assert test_db.query(models.OrgTitleAssignment).filter_by(title_id=title.id).count()==0
    assert test_db.query(models.Notification).filter_by(target_id=pid).count()==0
    monkeypatch.setattr(proposal_lifecycle,'emit_notification',real)
    assert close(client,test_db,election_org,pid,'org')=='passed'
    notice=test_db.query(models.Notification).filter_by(target_id=pid,event_type='proposal.closed').one()
    assert candidates[1].display_name in notice.payload['outcome_detail']
    assert notice.payload['office_installation']=='installed'
    assert 'Office installation completed' in notice.payload['outcome_detail']

@pytest.fixture
def release_fixture(test_db):
    data=bootstrap(test_db,{name:'SyntheticDistinctPassword-'+name for name in USERNAMES});test_db.commit();return data

def test_bootstrap_privacy_notifications_collision_boundary(test_db,release_fixture):
    org,ids=safety(test_db)
    assert org.discoverability=='hidden' and len(ids)==4
    assert test_db.query(models.OrgTitle).filter_by(org_id=org.id).count()==9
    assert test_db.query(models.Proposal).count()==0
    with pytest.raises(ValueError,match='exists'):bootstrap(test_db,{name:'SyntheticDistinctPassword-'+name for name in USERNAMES})
    assert test_db.query(models.Organization).count()==1

def test_scoped_worker_rejects_unexpected_member_before_any_mutation(test_db,release_fixture):
    org,ids=safety(test_db)
    outsider=_create_user(test_db,'unexpected-person');_create_membership(test_db,org,outsider,'member');test_db.commit()
    with pytest.raises(ValueError,match='memberships'):worker_close(test_db,{method:models._uuid() for method in METHODS})
    assert test_db.query(models.Proposal).count()==0
    assert test_db.query(models.OrgTitleAssignment).count()==0

def test_scoped_worker_rejects_incomplete_ids_without_closing(test_db,release_fixture):
    with pytest.raises(ValueError,match='Exactly four'):worker_close(test_db,{'star':models._uuid()})
    assert test_db.query(models.OrgTitleAssignment).count()==0

@pytest.mark.parametrize('method',METHODS)
@pytest.mark.parametrize('allow_revert',(False,True))
def test_authorized_council_revert_preserves_governance_floor(client,test_db,election_org,method,allow_revert):
    org,owner,candidates,title=election_org
    org.governance_mode='admin_council';title.bound_role='steward'
    org.settings={**org.settings,'elections':{**org.settings['elections'],'allow_elected_revert':allow_revert}}
    admin=test_db.query(models.Role).filter_by(org_id=org.id,system_key='admin').one()
    owner_member=test_db.query(models.OrgMembership).filter_by(org_id=org.id,user_id=owner.id).one();owner_member.role_id=admin.id;test_db.commit()
    if not allow_revert:
        response=client.post(f'/api/orgs/{org.slug}/elections',headers=_auth_header(owner),json={'title_id':title.id,'voting_method':method})
        assert response.status_code==400
        assert org.governance_mode=='admin_council'
        return
    pid=opened(client,election_org,method);options=nominate_and_open(client,election_org,pid)
    assert client.post(f'/api/proposals/{pid}/vote',headers=_auth_header(owner),json=ballot(method,options)).status_code==200
    # At close the winner is the sole admin; a promotion + authorized mode
    # flip is not a forbidden demotion leaving the council empty.
    owner_member.role_id=test_db.query(models.Role).filter_by(org_id=org.id,system_key='member').one().id
    winner_member=test_db.query(models.OrgMembership).filter_by(org_id=org.id,user_id=candidates[1].id).one();winner_member.role_id=admin.id;test_db.commit()
    assert close(client,test_db,election_org,pid,'worker')=='passed'
    assert org.governance_mode=='single_steward'
    assert test_db.get(models.Role,winner_member.role_id).system_key=='steward'
    assert test_db.get(models.Proposal,pid).final_method_result['election']['installation']=='installed'
    assert test_db.query(models.AuditLog).filter_by(target_id=org.id,action='org.governance_mode_changed').count()==1
