"""Phase 110 disposable PG16 close races + assignment/audit rollback.
Never accepts a production URL; creates/tears down only its own container.
Run from repo root: python backend/scripts/phase110_pg_elections.py
"""
import os, sys, json, subprocess, logging, threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
BACKEND=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BACKEND))
METHODS=('star','score','ranked_pairs','majority_judgment')

def child():
    if os.environ.get('PHASE110_DISPOSABLE')!='YES' or not os.environ['DATABASE_URL'].startswith('postgresql://smoke:smoke@localhost:55520/'):
        raise RuntimeError('Only the isolated Phase110 database is authorized')
    logging.disable(logging.CRITICAL)
    import models, auth, elections, audit_utils
    from database import Base, engine, SessionLocal
    from main import app
    from fastapi.testclient import TestClient
    from experimental_voting import initialize_rules
    from sustained_majority_worker import _close_proposal_now
    from tests.test_ranked_choice_voting import _create_org,_create_user,_create_membership
    Base.metadata.create_all(engine)
    reports=[]
    def fixture(method):
        with SessionLocal() as db:
            key=models._uuid()[:8]
            org=_create_org(db,['binary',*METHODS],slug='phase110-pg-'+key)
            org.settings={**org.settings,'elections':{'enabled':True,'trigger_sources':['admin_direct']}}
            users=[_create_user(db,f'p110pg-{key}-{i}') for i in range(4)]
            for i,u in enumerate(users):_create_membership(db,org,u,'steward' if i==0 else 'member')
            title=models.OrgTitle(org_id=org.id,name='Synthetic office',fill_method='elected',cardinality_mode='single',bound_role='moderator',is_system=False)
            db.add(title);db.flush()
            db.add(models.OrgTitleAssignment(title_id=title.id,user_id=users[3].id))
            now=datetime.now(timezone.utc).replace(tzinfo=None)
            p=models.Proposal(title='Synthetic PG election',org_id=org.id,author_id=users[0].id,voting_method=method,num_winners=1,status='voting',voting_start=now,voting_end=now+timedelta(days=1),is_election=True,election_title_id=title.id,election_trigger='admin_direct',election_slate_mode='refresh_slate',quorum_threshold=0)
            db.add(p);db.flush();initialize_rules(p,db)
            for i,u in enumerate(users[1:]):
                db.add(models.ElectionCandidacy(proposal_id=p.id,user_id=u.id,status='declared',declared_at=now+timedelta(seconds=i)))
                db.add(models.ProposalOption(proposal_id=p.id,label=u.id,description=u.display_name,display_order=i))
            db.flush();db.expire(p,['options']);opts=p.options
            expression={'rank_groups':[[opts[1].id]]} if method=='ranked_pairs' else {('grades' if method=='majority_judgment' else 'scores'):{opts[1].id:5}}
            db.add(models.Vote(proposal_id=p.id,user_id=users[0].id,cast_by_id=users[0].id,is_direct=True,ballot=expression))
            db.add(models.NotificationPreference(user_id=users[0].id,event_type='proposal.closed',channel='in_app',enabled=True))
            data={'pid':p.id,'org':org.id,'slug':org.slug,'title':title.id,'incumbent':users[3].id,'winner':users[2].id,'token':auth.create_access_token(users[0].id)}
            db.commit();return data
    def worker(data):
        with SessionLocal() as db:
            p=db.get(models.Proposal,data['pid'])
            result=_close_proposal_now(db,p,trigger='phase110_scoped_pg_test',update_voting_end=False)
            db.commit();return result
    def manual(data,org_route=False):
        path=f"/api/orgs/{data['slug']}/proposals/{data['pid']}/advance" if org_route else f"/api/proposals/{data['pid']}/advance"
        response=TestClient(app).post(path,headers={'Authorization':'Bearer '+data['token']},json={})
        assert response.status_code in (200,400),response.text
        return response.status_code
    def verify(data,closed):
        with SessionLocal() as db:
            p=db.get(models.Proposal,data['pid'])
            holders=[r.user_id for r in db.query(models.OrgTitleAssignment).filter_by(title_id=data['title'])]
            if closed:
                assert p.status=='passed' and p.final_method_result['election']['installation']=='installed'
                assert p.final_method_result['election']['winner_user_id']==data['winner']
                assert holders==[data['winner']]
                member=db.query(models.OrgMembership).filter_by(org_id=data['org'],user_id=data['winner']).one()
                assert db.get(models.Role,member.role_id).system_key=='moderator'
                assert db.query(models.AuditLog).filter_by(target_id=p.id,action='election.resolved').count()==1
                assert db.query(models.AuditLog).filter_by(target_id=p.id,action='proposal.status_changed').count()==1
                notice=db.query(models.Notification).filter_by(target_id=p.id,event_type='proposal.closed').one()
                assert notice.payload['office_installation']=='installed'
                assert 'Office installation completed' in notice.payload['outcome_detail']
                assert p.final_method_result['notification_intent_staged']
            else:
                assert p.status=='voting' and p.final_method_result is None
                assert holders==[data['incumbent']]
                member=db.query(models.OrgMembership).filter_by(org_id=data['org'],user_id=data['winner']).one()
                assert db.get(models.Role,member.role_id).system_key=='member'
                assert db.query(models.AuditLog).filter_by(target_id=p.id,action='election.resolved').count()==0
                assert db.query(models.Notification).filter_by(target_id=p.id,event_type='proposal.closed').count()==0
    for method in METHODS:
        for race in ('manual_manual','manual_worker'):
            data=fixture(method);barrier=threading.Barrier(2)
            def run(which):
                barrier.wait(timeout=10)
                return manual(data,True) if which==0 else (worker(data) if race=='manual_worker' else manual(data))
            with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,[0,1]))
            verify(data,True);worker(data);verify(data,True)
            reports.append({'method':method,'race':race,'responses':results,'one_install_audit_and_notification':True})
        for stage in ('assignment','audit'):
            data=fixture(method);module=elections if stage=='assignment' else audit_utils
            attr='_apply_election_winner' if stage=='assignment' else 'log_audit_event';real=getattr(module,attr)
            def injected(*args,**kwargs):
                value=real(*args,**kwargs)
                if stage=='assignment' or kwargs.get('action')=='election.resolved':raise RuntimeError('Phase110 injected staging failure')
                return value
            with patch.object(module,attr,injected):
                try:worker(data)
                except RuntimeError as exc:assert 'Phase110 injected' in str(exc)
                else:raise AssertionError('Failure injection did not fire')
            verify(data,False);worker(data);verify(data,True)
            reports.append({'method':method,'failure_stage':stage,'rollback_then_single_retry':True})
    assert engine.pool.checkedout()==0
    print(json.dumps({'postgres':'16','autoflush':False,'checks':reports,'checked_out_after':0},indent=2))
    engine.dispose()

if __name__=='__main__':
    if '--child' in sys.argv:child()
    else:
        from pg_smoke import _pg_container
        with _pg_container(port=55520) as (_,url):
            env={**os.environ,'DATABASE_URL':url,'PHASE110_DISPOSABLE':'YES','DEBUG':'true','DISABLE_DIGEST_SCHEDULER':'true','RESEND_API_KEY':'','SMTP_HOST':'','LOG_LEVEL':'ERROR'}
            subprocess.run([sys.executable,__file__,'--child'],env=env,cwd=BACKEND,check=True,timeout=180)
