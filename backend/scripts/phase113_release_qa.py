"""Fresh additive Phase113 fixtures (internal Phase110 helper adaptation) and strictly scoped release verification.
Production requires --production and explicit DATABASE_URL. No global tick.
Accounts are fictional non-platform-admins; all notification channels are off.
"""
import argparse,json,os,sys
from pathlib import Path
from copy import deepcopy
from datetime import timedelta
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
METHODS=('score','star','majority_judgment','ranked_pairs','allocated_score')
SLUG='phase113-release-qa-20261010'
USERNAMES=('phase113releaseowner','phase113candidateada','phase113candidatebea','phase113candidatecy')
NAMES=('Phase 113 Synthetic Steward','Ada Fictional','Bea Fictional','Cy Fictional')

def require(condition,message):
    if not condition:raise ValueError(message)

def bootstrap(db,passwords):
    import models,auth
    from sqlalchemy import or_
    from role_seed import seed_default_roles_for_org
    from notification_events import EVENT_REGISTRY
    require(set(passwords)==set(USERNAMES) and all(len(p)>=24 for p in passwords.values()),'Four distinct synthetic credentials required')
    require(len(set(passwords.values()))==4,'Credentials must be distinct')
    require(not db.query(models.Organization).filter(models.Organization.slug.in_((SLUG,'phase113-release-child'))).first(),'QA org exists; refusing overwrite')
    require(not db.query(models.User).filter(or_(models.User.username.in_(USERNAMES),models.User.email.in_([u+'@demo.example' for u in USERNAMES]))).first(),'Account collision; refusing overwrite')
    org=models.Organization(name='Phase 113 Isolated Election QA',slug=SLUG,description='Fictional release fixtures only',join_policy='invite',discoverability='hidden',activity_visibility='members_only',is_demo=False,settings={'allowed_voting_methods':['binary','approval','ranked_choice',*METHODS[:-1],'budget_allocation'],'allowed_multiwinner_methods':[],'allowed_budget_aggregations':['median'],'verification_proposal_policy':'never','elections':{'enabled':True,'trigger_sources':['admin_direct','member_cosign']}})
    db.add(org);db.flush();roles=seed_default_roles_for_org(db,org.id)
    users=[]
    for i,(username,name) in enumerate(zip(USERNAMES,NAMES)):
        user=models.User(username=username,display_name=name,email=username+'@demo.example',email_verified=True,is_admin=False,notification_intro_dismissed=True,password_hash=auth.hash_password(passwords[username]))
        db.add(user);db.flush();db.add(models.OrgMembership(org_id=org.id,user_id=user.id,role_id=roles['steward' if i==0 else 'member'].id,status='active'))
        for event in EVENT_REGISTRY:
            for channel in ('in_app','email_immediate','email_daily','email_weekly'):db.add(models.NotificationPreference(user_id=user.id,event_type=event.key,channel=channel,enabled=False))
        users.append({'id':user.id,'username':username,'display_name':name})
    titles={}
    for site in ('manual','worker'):
        titles[site]={}
        for method in METHODS:
            title=models.OrgTitle(org_id=org.id,name=f'Phase113 {site} {method}',fill_method='elected',bound_role='moderator',cardinality_mode='multi',max_holders=2,is_system=False)
            db.add(title);db.flush();titles[site][method]=title.id
    child=models.Organization(name='Phase 113 QA Child',slug='phase113-release-child',parent_org_id=org.id,join_policy='invite',discoverability='hidden',activity_visibility='members_only',is_demo=False,settings={'allowed_voting_methods':None})
    db.add(child);db.flush()
    for i,user in enumerate(users):
        db.add(models.SubOrgMembership(sub_org_id=child.id,user_id=user['id'],role_id=roles['steward' if i==0 else 'member'].id,status='active'))
    return {'org_slug':SLUG,'org_id':org.id,'child_slug':child.slug,'child_id':child.id,'accounts':users,'titles':titles,'notifications_enabled':False,'proposals_created':0}

def safety(db):
    import models
    org=db.query(models.Organization).filter_by(slug=SLUG).one()
    require(org.join_policy=='invite' and org.discoverability=='hidden' and org.activity_visibility=='members_only' and not org.is_demo,'QA privacy boundary changed')
    users=db.query(models.User).filter(models.User.username.in_(USERNAMES)).all();ids={u.id for u in users}
    require(len(users)==4 and all(not u.is_admin and u.email==u.username+'@demo.example' for u in users),'Synthetic account boundary changed')
    members=db.query(models.OrgMembership).filter_by(org_id=org.id).all()
    require({m.user_id for m in members}==ids and all(m.status=='active' for m in members),'Unexpected QA memberships')
    require(not db.query(models.NotificationPreference).filter(models.NotificationPreference.user_id.in_(ids),models.NotificationPreference.enabled.is_(True)).first(),'QA notifications must stay off')
    require(len(db.query(models.NotificationPreference).filter(models.NotificationPreference.user_id.in_(ids)).all())==len(users)*len(__import__('notification_events').EVENT_REGISTRY)*4,'Missing disabled preferences')
    return org,ids

def inspect(db,proposal_ids):
    import models
    org,ids=safety(db);result={}
    for method,pid in proposal_ids.items():
        require(method in METHODS,'Unsupported method')
        p=db.get(models.Proposal,pid)
        require(p and p.org_id==org.id and p.author_id in ids and p.is_election and p.voting_method==method,'Proposal outside fixture boundary')
        title=db.get(models.OrgTitle,p.election_title_id);require(title.org_id==org.id and title.name.startswith('Phase113 '),'Title outside fixture boundary')
        outcome=p.final_method_result['election']
        winners=db.query(models.User).filter(models.User.username.in_(USERNAMES[1:3])).all()
        expected={u.id for u in winners}
        require(p.num_winners==2 and p.final_method_result['record_version']==2,'Expected v2/K2')
        require(set(outcome['winner_user_ids'])==expected and outcome['installation']=='installed','Unexpected winner set')
        require({a.user_id for a in db.query(models.OrgTitleAssignment).filter_by(title_id=title.id)}==expected,'Whole set not installed')
        for winner in winners:
            member=db.query(models.OrgMembership).filter_by(org_id=org.id,user_id=winner.id).one()
            require(db.get(models.Role,member.role_id).system_key=='moderator','Bound role not installed')
        require(db.query(models.AuditLog).filter_by(target_id=p.id,action='election.resolved').count()==1,'Duplicate/missing resolution audit')
        result[method]={'proposal_id':pid,'status':p.status,'winners':['Ada Fictional','Bea Fictional'],'installation':'installed','bound_roles':'moderator','election_resolved_audits':1,'notification_intent_staged':p.final_method_result.get('notification_intent_staged')}

    return result

def worker_close(db,proposal_ids):
    import models,sustained_majority_worker as worker
    from experimental_voting import lock_proposal
    org,ids=safety(db)
    require(set(proposal_ids)==set(METHODS) and len(set(proposal_ids.values()))==5,'Exactly five distinct worker fixtures required')
    proposals=[];now=worker._now_naive()
    for method,pid in sorted(proposal_ids.items(),key=lambda x:x[1]):
        p=db.get(models.Proposal,pid);require(p is not None,'Missing proposal');lock_proposal(db,p)
        title=db.get(models.OrgTitle,p.election_title_id)
        require(p.org_id==org.id and p.sub_org_id is None and p.author_id in ids and p.is_election and p.num_winners==2 and p.voting_method==method,'Worker proposal outside QA boundary')
        require(title.org_id==org.id and title.name==f'Phase113 worker {method}','Worker title outside QA boundary')
        require(p.status=='voting' and p.final_method_result is None and p.voting_start<now,'Fresh voting fixtures required')
        proposals.append(p)
    for p in proposals:
        p.voting_end=now-timedelta(microseconds=1);p.stable_result_required=False;db.flush()
        require(worker.evaluate_proposal(db,p)=='closed_on_time','Due scoped worker did not close fixture')
    db.commit();result=inspect(db,proposal_ids)
    records={p.id:deepcopy(p.final_method_result) for p in proposals}
    for p in proposals:
        require(worker.evaluate_proposal(db,p) is None,'Worker retry was not a no-op')
        require(p.final_method_result==records[p.id],'Worker retry changed frozen result')
    inspect(db,proposal_ids);db.commit()
    return {'worker_fixtures':result,'retry_noop':True}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('bootstrap','inspect','worker'));parser.add_argument('--production',action='store_true');parser.add_argument('--local',action='store_true');args=parser.parse_args()
    require(args.production != args.local,'Select explicit production or local execution')
    url=os.environ.get('DATABASE_URL','');require(url.startswith(('postgresql://','postgresql+psycopg2://','postgres://') if args.production else ('sqlite:///',)),'Explicit correct database required')
    from database import SessionLocal
    with SessionLocal() as db:
        try:
            if args.action=='bootstrap':result=bootstrap(db,json.loads(os.environ['PHASE113_QA_PASSWORDS']));db.commit()
            else:result=(worker_close if args.action=='worker' else inspect)(db,json.loads(sys.stdin.read(4096)))
        except Exception:db.rollback();raise
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
