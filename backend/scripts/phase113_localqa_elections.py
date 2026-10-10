"""Additive fictional nominations, restricted to the exact local SQLite fixture."""
import argparse,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import models,auth
from database import engine,SessionLocal
from notification_events import EVENT_REGISTRY
from elections import declare_candidacy
parser=argparse.ArgumentParser();parser.add_argument("--proposal");parser.add_argument("--title-method",choices=["star","majority_judgment","ranked_pairs"]);args=parser.parse_args()
if engine.url.get_backend_name()!="sqlite" or Path(engine.url.database).name!=".tmp_phase113_localqa.db":
    raise SystemExit("Exact local database required")
with SessionLocal() as db:
    org=db.query(models.Organization).filter_by(slug="phase113-localqa").one()
    names=[f"phase113candidate{i}" for i in range(1,4)]
    if args.title_method:
        title_name={"star":"W3 Fictional Council","majority_judgment":"W4 Fictional Council","ranked_pairs":"W5 Fictional Council"}[args.title_method]
        if db.query(models.OrgTitle).filter_by(org_id=org.id,name=title_name).first():raise SystemExit("Refusing title overwrite")
        db.add(models.OrgTitle(org_id=org.id,name=title_name,fill_method="elected",cardinality_mode="multi",max_holders=2,bound_role="moderator",is_system=False))
        db.commit();print(f"{title_name} created; existing fixture people reused")
    elif args.proposal:
        p=db.get(models.Proposal,args.proposal)
        if p is None or p.org_id!=org.id or not p.is_election or p.status!="deliberation" or p.voting_method not in ("score","star","majority_judgment","ranked_pairs"):raise SystemExit("Exact local Score nomination required")
        if db.query(models.ElectionCandidacy).filter_by(proposal_id=p.id).first():raise SystemExit("Refusing nomination overwrite")
        for name in names:declare_candidacy(db,p,db.query(models.User).filter_by(username=name).one().id)
        db.commit();print("Three fictional candidates nominated; no notifications")
    else:
        if db.query(models.User).filter(models.User.username.in_(names)).first():raise SystemExit("Refusing fixture overwrite")
        role=db.query(models.Role).filter_by(org_id=org.id,system_key="member").one()
        for i,name in enumerate(names,1):
            user=models.User(username=name,display_name=f"Fictional Candidate {i}",email=f"{name}@demo.example",email_verified=True,is_admin=False,notification_intro_dismissed=True,password_hash=auth.hash_password("LocalQA113-only-fictional!"))
            db.add(user);db.flush();db.add(models.OrgMembership(org_id=org.id,user_id=user.id,role_id=role.id,status="active"))
            for entry in EVENT_REGISTRY:
                for channel in ("in_app","email_immediate","email_daily","email_weekly"):db.add(models.NotificationPreference(user_id=user.id,event_type=entry.key,channel=channel,enabled=False))
        org.settings={**org.settings,"elections":{"enabled":True,"trigger_sources":["admin_direct","member_cosign"]}}
        db.add(models.OrgTitle(org_id=org.id,name="W2 Fictional Council",fill_method="elected",cardinality_mode="multi",max_holders=2,bound_role="moderator",is_system=False))
        db.commit();print("Fictional two-holder title and candidates created; notification channels disabled")
