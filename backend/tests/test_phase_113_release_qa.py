"""Production helper boundaries tested against real autoflush=False storage."""
import pytest
import models
from scripts import phase113_release_qa as qa
from scripts.phase113_release_api_qa import ballot
from tests.test_ranked_choice_voting import test_db,client,_auth_header

@pytest.fixture
def release_fixture(test_db):
    passwords={u:'Fictional-only-113-'+str(i)+'-never-production-password' for i,u in enumerate(qa.USERNAMES)}
    data=qa.bootstrap(test_db,passwords);test_db.commit()
    return data,passwords

def test_bootstrap_privacy_collision_and_default_settings(test_db,release_fixture):
    data,passwords=release_fixture
    org,ids=qa.safety(test_db)
    assert org.settings['allowed_multiwinner_methods']==[]
    assert 'allocated_score' not in org.settings['allowed_voting_methods']
    assert org.settings['allowed_budget_aggregations']==['median']
    assert test_db.query(models.SubOrgMembership).filter_by(sub_org_id=data['child_id']).count()==4
    with pytest.raises(ValueError,match='refusing overwrite'):qa.bootstrap(test_db,passwords)
    pref=test_db.query(models.NotificationPreference).filter(models.NotificationPreference.user_id.in_(ids)).first();pref.enabled=True;test_db.flush()
    with pytest.raises(ValueError,match='stay off'):qa.safety(test_db)

def test_scoped_worker_all_five_sets_retry_and_foreign_rejection(client,test_db,release_fixture):
    data,_=release_fixture;org,_=qa.safety(test_db)
    org.settings={**org.settings,'allowed_voting_methods':[*org.settings['allowed_voting_methods'],'allocated_score'],'allowed_multiwinner_methods':list(qa.METHODS[:-1])}
    test_db.commit()
    people={u:test_db.query(models.User).filter_by(username=u).one() for u in qa.USERNAMES}
    owner=people[qa.USERNAMES[0]];ids={u:v.id for u,v in people.items()};manifest={}
    for method in qa.METHODS:
        r=client.post(f'/api/orgs/{qa.SLUG}/elections',headers=_auth_header(owner),json={'title_id':data['titles']['worker'][method],'voting_method':method,'num_winners':2})
        assert r.status_code==201,r.text
        pid=r.json()['id'];manifest[method]=pid
        for username in qa.USERNAMES[1:]:
            assert client.post(f'/api/orgs/{qa.SLUG}/elections/{pid}/candidacies',headers=_auth_header(people[username])).status_code==201
        r=client.post(f'/api/proposals/{pid}/advance',headers=_auth_header(owner),json={});assert r.status_code==200,r.text
        options=r.json()['options']
        for username in (qa.USERNAMES[0],qa.USERNAMES[3]):
            r=client.post(f'/api/proposals/{pid}/vote',headers=_auth_header(people[username]),json=ballot(method,options,ids))
            assert r.status_code==200,r.text
    assert qa.worker_close(test_db,manifest)['retry_noop']
    assert len(qa.inspect(test_db,manifest))==5
    with pytest.raises(ValueError,match='Fresh voting'):qa.worker_close(test_db,manifest)
    with pytest.raises(ValueError,match='Exactly five'):qa.worker_close(test_db,{'score':manifest['score']})

@pytest.mark.parametrize('site',('ordinary','manual'))
def test_api_prepare_and_finish_exact_private_fixtures(client,test_db,release_fixture,tmp_path,monkeypatch,site):
    import json
    from types import SimpleNamespace
    from scripts import phase113_release_api_qa as api
    data,passwords=release_fixture;org,_=qa.safety(test_db)
    org.settings={**org.settings,'allowed_voting_methods':[*org.settings['allowed_voting_methods'],'allocated_score'],'allowed_multiwinner_methods':list(qa.METHODS[:-1])};test_db.commit()
    class Adapter:
        def __init__(self,**kwargs):self.headers={}
        def request(self,method,path,**kwargs):return client.request(method,path,headers=self.headers,**kwargs)
        def get(self,path):return self.request('GET',path)
        def close(self):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
    monkeypatch.setattr(api.httpx,'Client',Adapter)
    fixture=tmp_path/'fixture.json';fixture.write_text(json.dumps(data))
    credentials=tmp_path/'credentials.json';credentials.write_text(json.dumps({'passwords':passwords}))
    output=tmp_path/'manifest.json'
    args=SimpleNamespace(base_url='http://127.0.0.1:8002',fixture=str(fixture),credentials=str(credentials),output=str(output),site=site,action='prepare',require_browser_ballots=True)
    result=api.run(args);assert result['public_privacy']=='PASS'
    owner=test_db.query(models.User).filter_by(username=qa.USERNAMES[0]).one();ids={u['username']:u['id'] for u in data['accounts']}
    for method,pid in result['prepared'].items():
        p=client.get(f'/api/proposals/{pid}',headers=_auth_header(owner)).json()
        assert client.post(f'/api/proposals/{pid}/vote',headers=_auth_header(owner),json=ballot(method,p['options'],None if site=='ordinary' else ids)).status_code==200
        assert client.post(f'/api/proposals/{pid}/advance',headers=_auth_header(owner),json={}).json()['status']=='passed'
    args.action='finish';assert len(api.run(args))==5
