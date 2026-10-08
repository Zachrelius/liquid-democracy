"""Add a synthetic delegate to the existing, disposable Phase 109 SQLite fixture."""
import os
import sys
from pathlib import Path
from datetime import datetime

root = Path(__file__).resolve().parents[1]
fixture = root / "phase109_localqa.db"
if not fixture.is_file():
    raise SystemExit("Expected existing phase109_localqa.db beside this script's backend")
os.environ["DATABASE_URL"] = "sqlite:///" + fixture.as_posix()
sys.path.insert(0, str(root))

import models
from database import engine, SessionLocal

if engine.url.get_backend_name() != "sqlite" or Path(engine.url.database).resolve() != fixture.resolve():
    raise SystemExit("Refusing a database other than the isolated local QA fixture")

with SessionLocal() as db:
    org = db.query(models.Organization).filter_by(slug="phase109-qa").one()
    topic = db.query(models.Topic).filter_by(org_id=org.id, name="STAR community projects").first()
    if topic is None:
        topic = models.Topic(org_id=org.id, name="STAR community projects")
        db.add(topic)
        db.flush()
    user = db.query(models.User).filter_by(username="phase109delegate").first()
    if user is None:
        user = models.User(username="phase109delegate", display_name="STAR QA Delegate",
                           delegate_handle="star-qa-delegate", email="phase109delegate@demo.example",
                           email_verified=True, password_hash="!disabled-local-fixture")
        db.add(user)
        db.flush()
    if not db.query(models.OrgMembership).filter_by(org_id=org.id, user_id=user.id).first():
        role = db.query(models.Role).filter_by(org_id=org.id, system_key="member").one()
        db.add(models.OrgMembership(org_id=org.id, user_id=user.id, role_id=role.id, status="active"))
    if not db.query(models.DelegateProfile).filter_by(user_id=user.id, topic_id=topic.id).first():
        db.add(models.DelegateProfile(org_id=org.id, user_id=user.id, topic_id=topic.id,
                                      visibility="public_accepting", bio="Synthetic local STAR delegate",
                                      public_accepting_approved_at=datetime.now()))
    if not db.query(models.OrgDelegateProfile).filter_by(org_id=org.id, user_id=user.id).first():
        db.add(models.OrgDelegateProfile(org_id=org.id, user_id=user.id,
                                         intro="Synthetic local delegate. Playground 5, Community center 1."))
    proposals = db.query(models.Proposal).filter_by(org_id=org.id, voting_method="star").all()
    for proposal in proposals:
        if proposal.final_method_result is not None or proposal.status not in ("voting", "deliberation"):
            continue
        if not db.query(models.ProposalTopic).filter_by(proposal_id=proposal.id, topic_id=topic.id).first():
            db.add(models.ProposalTopic(proposal_id=proposal.id, topic_id=topic.id, relevance=1.0))
        if not db.query(models.Vote).filter_by(proposal_id=proposal.id, user_id=user.id).first():
            scores = {option.id: {"Playground": 5, "Community center": 1}.get(option.label, 0)
                      for option in proposal.options}
            db.add(models.Vote(proposal_id=proposal.id, user_id=user.id, cast_by_id=user.id,
                               is_direct=True, ballot={"scores": scores}))
        print(proposal.title, proposal.id)
    db.commit()
    print("Delegate: STAR QA Delegate / star-qa-delegate; topic: STAR community projects")
    print("Browse /phase109-qa/delegates; no tester ballots or proposal statuses changed")
