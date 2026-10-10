"""Duplicate the local fictional owner's ordinary ballot via the normal endpoint."""
import argparse,json,sys,urllib.request
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from database import engine,SessionLocal
import models,auth
parser=argparse.ArgumentParser();parser.add_argument("--proposal",required=True);args=parser.parse_args()
if engine.url.get_backend_name()!="sqlite" or Path(engine.url.database).name!=".tmp_phase113_localqa.db":
    raise SystemExit("Exact local SQLite database required")
with SessionLocal() as db:
    org=db.query(models.Organization).filter_by(slug="phase113-localqa").one()
    proposal=db.get(models.Proposal,args.proposal)
    if not proposal or proposal.org_id!=org.id or proposal.is_election or proposal.status!="voting":raise SystemExit("Local ordinary vote required")
    owner=db.query(models.User).filter_by(username="phase113localowner").one()
    voter=db.query(models.User).filter_by(username="phase113candidate1").one()
    if db.query(models.Vote).filter_by(proposal_id=proposal.id,user_id=voter.id).first():raise SystemExit("Refusing ballot overwrite")
    ballot=db.query(models.Vote).filter_by(proposal_id=proposal.id,user_id=owner.id).one().ballot
    token=auth.create_access_token(voter.id)
request=urllib.request.Request(f"http://127.0.0.1:8002/api/proposals/{args.proposal}/vote",data=json.dumps(ballot).encode(),headers={"Authorization":f"Bearer {token}","Content-Type":"application/json"})
with urllib.request.urlopen(request) as response:print("Fictional quorum ballot submitted through ordinary API:",response.status)
