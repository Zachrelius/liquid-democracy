"""Phase 113 disposable PostgreSQL 16 transactions; never accepts a prod URL."""
import os,sys,json,logging,subprocess,threading,time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,TimeoutError
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
BACKEND=Path(__file__).resolve().parents[1];sys.path.insert(0,str(BACKEND))
METHODS=('score','star','majority_judgment','ranked_pairs','allocated_score')
def child():
    if os.environ.get('PHASE113_DISPOSABLE')!='YES' or not os.environ['DATABASE_URL'].startswith('postgresql://smoke:smoke@localhost:55523/'):
        raise RuntimeError('Only the generated Phase113 local database is authorized')
    logging.disable(logging.CRITICAL)
    import models,auth,elections,audit_utils
    from database import Base,engine,SessionLocal
    from main import app
    from fastapi.testclient import TestClient
    from fastapi import HTTPException
    from experimental_voting import initialize_rules
    from sustained_majority_worker import _close_proposal_now
    from tests.test_ranked_choice_voting import _create_org,_create_user,_create_membership
    Base.metadata.create_all(engine);reports=[]
    def expression(method,ids):
        return {'rank_groups':[[ids[0]],[ids[1]]]} if method=='ranked_pairs' else {'grades' if method=='majority_judgment' else 'scores':{ids[0]:5,ids[1]:3}}
    def fixture(method,incumbent=True,source=None,selected=(1,2)):
        with SessionLocal() as db:
            key=models._uuid()[:8]
            if source:
                org=db.get(models.Organization,source['org']);title=db.get(models.OrgTitle,source['title']);users=[db.get(models.User,u) for u in source['users']]
            else:
                org=_create_org(db,['binary',*METHODS],slug='phase113-pg-'+key)
                org.settings={**org.settings,'allowed_multiwinner_methods':list(METHODS[:-1]),'elections':{'enabled':True,'trigger_sources':['admin_direct']}}
                users=[_create_user(db,f'p113pg-{key}-{i}') for i in range(5)]
                for i,u in enumerate(users):_create_membership(db,org,u,'steward' if i==0 else 'member')
                title=models.OrgTitle(org_id=org.id,name='Synthetic two-seat office',fill_method='both',cardinality_mode='multi',max_holders=2,bound_role='moderator',is_system=False)
                db.add(title);db.flush()
                if incumbent:db.add(models.OrgTitleAssignment(title_id=title.id,user_id=users[4].id))
            now=datetime.now(timezone.utc).replace(tzinfo=None)
            p=models.Proposal(title='Synthetic PG multiple election',org_id=org.id,author_id=users[0].id,voting_method=method,num_winners=2,status='voting',voting_start=now,voting_end=now+timedelta(days=1),is_election=True,election_title_id=title.id,election_trigger='admin_direct',election_slate_mode='refresh_slate' if incumbent else 'fill_vacancies',quorum_threshold=0)
            db.add(p);db.flush();initialize_rules(p,db)
            for i,u in enumerate(users[1:]):
                db.add(models.ElectionCandidacy(proposal_id=p.id,user_id=u.id,status='declared',declared_at=now+timedelta(seconds=i)))
                db.add(models.ProposalOption(proposal_id=p.id,label=u.id,description=u.display_name,display_order=i))
            db.flush();db.expire(p,['options']);by_user={o.label:o.id for o in p.options};ids=[by_user[users[i].id] for i in selected]
            db.add(models.Vote(proposal_id=p.id,user_id=users[0].id,cast_by_id=users[0].id,is_direct=True,ballot=expression(method,ids)))
            data={'pid':p.id,'org':org.id,'slug':org.slug,'title':title.id,'incumbents':[users[4].id] if incumbent else [],'winners':[users[i].id for i in selected],'users':[u.id for u in users],'options':[o.id for o in p.options],'token':auth.create_access_token(users[0].id),'method':method}
            db.commit();return data
    def worker(data):
        with SessionLocal() as db:
            result=_close_proposal_now(db,db.get(models.Proposal,data['pid']),trigger='phase113_scoped_pg_test',update_voting_end=False)
            db.commit();return result
    def request(data,suffix='/advance',payload=None,org_route=False):
        path=f"/api/orgs/{data['slug']}/proposals/{data['pid']}" if org_route else f"/api/proposals/{data['pid']}"
        return TestClient(app).post(path+suffix,headers={'Authorization':'Bearer '+data['token']},json={} if payload is None else payload)
    def manual(data,org_route=False):
        r=request(data,org_route=org_route);assert r.status_code in (200,400),r.text;return r.status_code
    def verify(data,installation='installed'):
        with SessionLocal() as db:
            p=db.get(models.Proposal,data['pid']);holders={r.user_id for r in db.query(models.OrgTitleAssignment).filter_by(title_id=data['title'])}
            if installation is None:
                assert p.status=='voting' and p.final_method_result is None and holders==set(data['incumbents'])
                assert db.query(models.AuditLog).filter_by(target_id=p.id,action='election.resolved').count()==0
            else:
                result=p.final_method_result
                assert p.status=='passed' and result['record_version']==2 and result['election']['installation']==installation
                assert set(result['election']['winner_user_ids'])==set(data['winners'])
                assert holders==set(data['winners'] if installation=='installed' else data['incumbents'])
                assert db.query(models.AuditLog).filter_by(target_id=p.id,action='election.resolved').count()==1
                assert db.query(models.AuditLog).filter_by(target_id=p.id,action='proposal.status_changed').count()==1
                assert result['notification_intent_staged']
            for uid in data['winners']:
                m=db.query(models.OrgMembership).filter_by(org_id=data['org'],user_id=uid).one()
                assert db.get(models.Role,m.role_id).system_key==('moderator' if installation=='installed' else 'member')
    def race(functions):
        barrier=threading.Barrier(len(functions))
        def run(fn):barrier.wait(timeout=10);return fn()
        with ThreadPoolExecutor(max_workers=len(functions)) as pool:return list(pool.map(run,functions))
    for method in METHODS:
        for kind in ('manual_manual','manual_worker'):
            d=fixture(method);values=race([lambda:manual(d,True),lambda:worker(d) if kind=='manual_worker' else manual(d)])
            verify(d);worker(d);verify(d);reports.append({'method':method,'race':kind,'responses':values,'single_whole_set':True})
        for stage in ('second_assignment','audit','expected_second_rejection'):
            d=fixture(method);module=audit_utils if stage=='audit' else elections;attr='log_audit_event' if stage=='audit' else '_apply_election_winner';real=getattr(module,attr);calls=[0]
            def injected(*args,**kwargs):
                value=real(*args,**kwargs);calls[0]+=1
                if stage=='audit' and kwargs.get('action')=='election.resolved':raise RuntimeError('Phase113 injected audit failure')
                if stage!='audit' and calls[0]==2:
                    if stage=='expected_second_rejection':raise HTTPException(400,'Phase113 expected second rejection')
                    raise RuntimeError('Phase113 injected second assignment failure')
                return value
            with patch.object(module,attr,injected):
                if stage=='expected_second_rejection':worker(d)
                else:
                    try:worker(d)
                    except RuntimeError as exc:assert 'Phase113 injected' in str(exc)
                    else:raise AssertionError('Failure did not fire')
            if stage=='expected_second_rejection':verify(d,'rejected');worker(d);verify(d,'rejected')
            else:verify(d,None);worker(d);verify(d)
            reports.append({'method':method,'failure_stage':stage,'atomic_rollback_and_retry':True})
        for kind in ('vote_close','option_close'):
            d=fixture(method)
            if kind=='option_close':
                with SessionLocal() as db:
                    p=db.get(models.Proposal,d['pid']);p.is_election=False;p.allow_write_in_options=True;p.allow_write_ins_during_voting=True;db.commit()
                mutate=lambda:request(d,'/options',{'label':'Synthetic racing late option'})
            else:mutate=lambda:request(d,'/vote',expression(method,list(reversed(d['options'][:2]))))
            result,closed=race([mutate,lambda:manual(d)])
            assert result.status_code in (200,201,400),result.text
            with SessionLocal() as db:
                p=db.get(models.Proposal,d['pid']);f=p.final_method_result;current={o.id for o in p.options}
                assert set(f['option_labels'])==current
                if kind=='option_close':assert (len(current)==5)==(result.status_code==201)
                else:
                    from multiwinner_tally import count_multiwinner
                    ballots=[(v.ballot,1) for v in db.query(models.Vote).filter_by(proposal_id=p.id)]
                    expected=count_multiwinner(method,list(current),ballots,p.voting_rules,p.id,2)
                    assert expected.method_result==f['tally']['method_result']
                assert db.query(models.AuditLog).filter_by(target_id=p.id,action='proposal.status_changed').count()==1
            reports.append({'method':method,'race':kind,'mutation_status':result.status_code,'coherent_frozen_snapshot':True})
        a=fixture(method,False);b=fixture(method,False,source=a,selected=(3,4));race([lambda:worker(a),lambda:worker(b)])
        with SessionLocal() as db:
            outcomes=[db.get(models.Proposal,d['pid']).final_method_result['election']['installation'] for d in (a,b)]
            holders={r.user_id for r in db.query(models.OrgTitleAssignment).filter_by(title_id=a['title'])}
            assert sorted(outcomes)==['installed','rejected'] and len(holders)==2
            assert holders in (set(a['winners']),set(b['winners']))
        reports.append({'method':method,'race':'overlapping_title_elections','capacity_preserved':True})
    # Hold close after its capacity preflight, then attempt a manual grant.
    # A FK wait at INSERT is too late: manual capacity must be read AFTER close.
    d=fixture('allocated_score',False);preflight=threading.Event();release=threading.Event();manual_checked=threading.Event()
    from routes import org_titles as title_routes
    real_cap=elections._cap_winners_to_title_capacity;real_count=title_routes.assignment_count
    def held_cap(db,title,winners,**kwargs):
        result=real_cap(db,title,winners,**kwargs)
        if title.id==d['title']:preflight.set();assert release.wait(timeout=10)
        return result
    def observed_count(*args,**kwargs):
        value=real_count(*args,**kwargs);manual_checked.set();return value
    def assign_during_close():return TestClient(app).post(f"/api/orgs/{d['slug']}/titles/{d['title']}/assignments",headers={'Authorization':'Bearer '+d['token']},json={'user_id':d['users'][3]})
    with patch.object(elections,'_cap_winners_to_title_capacity',held_cap),patch.object(title_routes,'assignment_count',observed_count),ThreadPoolExecutor(max_workers=2) as pool:
        closing=pool.submit(worker,d);assert preflight.wait(timeout=10)
        assigning=pool.submit(assign_during_close)
        # Distinguish a stale preflight from a safe org-row lock wait.
        stale=manual_checked.wait(timeout=0.5);release.set()
        assert closing.result(timeout=10)=='passed';assigned=assigning.result(timeout=10)
    with SessionLocal() as db:
        holders={r.user_id for r in db.query(models.OrgTitleAssignment).filter_by(title_id=d['title'])}
        assert not stale and assigned.status_code==400 and holders==set(d['winners']), (stale,assigned.status_code,len(holders))
    reports.append({'race':'manual_capacity_preflight_vs_close','no_stale_capacity_read_or_overgrant':True})
    # A manual assignment must wait for the same org/title locks as close.
    d=fixture('allocated_score',False)
    with SessionLocal() as holder,ThreadPoolExecutor(max_workers=1) as pool:
        holder.query(models.Organization).filter_by(id=d['org']).with_for_update().one()
        holder.query(models.OrgTitle).filter_by(id=d['title']).with_for_update().one()
        def assign():return TestClient(app).post(f"/api/orgs/{d['slug']}/titles/{d['title']}/assignments",headers={'Authorization':'Bearer '+d['token']},json={'user_id':d['users'][3]})
        pending=pool.submit(assign)
        try:pending.result(timeout=0.5)
        except TimeoutError:pass
        else:raise AssertionError('Manual assignment bypassed org/title close locks')
        holder.rollback();r=pending.result(timeout=10);assert r.status_code==201,r.text
    worker(d)
    with SessionLocal() as db:
        p=db.get(models.Proposal,d['pid']);assert p.final_method_result['election']['installation']=='rejected'
        assert [r.user_id for r in db.query(models.OrgTitleAssignment).filter_by(title_id=d['title'])]==[d['users'][3]]
    reports.append({'race':'manual_assignment_vs_close','same_lock_order_capacity_preserved':True})
    assert engine.pool.checkedout()==0
    print(json.dumps({'postgres':'16','autoflush':False,'checks':reports,'checked_out_after':0},indent=2));engine.dispose()
if __name__=='__main__':
    if '--child' in sys.argv:child()
    else:
        from pg_smoke import _pg_container
        with _pg_container(port=55523) as (_,url):
            env={**os.environ,'DATABASE_URL':url,'PHASE113_DISPOSABLE':'YES','DEBUG':'true','DISABLE_DIGEST_SCHEDULER':'true','SUSTAINED_MAJORITY_WORKER_DISABLE':'true','RESEND_API_KEY':'','SMTP_HOST':'','LOG_LEVEL':'ERROR'}
            subprocess.run([sys.executable,__file__,'--child'],env=env,cwd=BACKEND,check=True,timeout=240)
