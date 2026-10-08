"""Add Majority Judgment journeys to the disposable Phase 109 SQLite fixture, preserving STAR."""
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

root = Path(__file__).resolve().parents[1]
fixture = root / "phase109_localqa.db"
if not fixture.is_file():
    raise SystemExit("Expected existing local Phase 109 fixture")
os.environ["DATABASE_URL"] = "sqlite:///" + fixture.as_posix()
sys.path.insert(0, str(root))

import models
from database import engine, SessionLocal
from experimental_voting import initialize_rules

if engine.url.get_backend_name() != "sqlite" or Path(engine.url.database).resolve() != fixture.resolve():
    raise SystemExit("Refusing a database other than the isolated local QA fixture")

with SessionLocal() as db:
    org = db.query(models.Organization).filter_by(slug="phase109-qa").one()
    user = db.query(models.User).filter_by(username="phase109qa").one()
    delegate = db.query(models.User).filter_by(username="phase109delegate").one()
    topic = db.query(models.Topic).filter_by(org_id=org.id, name="STAR community projects").one()
    settings = dict(org.settings or {})
    settings["allowed_voting_methods"] = list(dict.fromkeys([*settings.get("allowed_voting_methods", ["binary"]), "star", "score", "ranked_pairs", "majority_judgment"]))
    org.settings = settings
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for title, status in [("Majority Judgment browser journey", "voting"), ("Majority Judgment early ballot", "deliberation")]:
        proposal = db.query(models.Proposal).filter_by(org_id=org.id, title=title, voting_method="majority_judgment").first()
        if proposal is None:
            proposal = models.Proposal(title=title, body="Synthetic local Majority Judgment QA. Verbal grades and original distributions.",
                org_id=org.id, author_id=user.id, voting_method="majority_judgment", num_winners=1,
                status=status, quorum_threshold=0, voting_start=now, voting_end=now + timedelta(days=7),
                deliberation_start=now, allow_pre_voting=True, allow_write_in_options=True,
                allow_write_ins_during_voting=True, show_votes_during_deliberation=False)
            db.add(proposal)
            db.flush()
            initialize_rules(proposal)
            options = [models.ProposalOption(proposal_id=proposal.id, label=label, display_order=i)
                       for i, label in enumerate(["Community center", "Playground", "Parking"])]
            db.add_all(options)
            db.add(models.ProposalTopic(proposal_id=proposal.id, topic_id=topic.id, relevance=1.0))
            db.flush()
            grades = {option.id: {"Playground": 5, "Community center": 2}.get(option.label, 0) for option in options}
            db.add(models.Vote(proposal_id=proposal.id, user_id=delegate.id, cast_by_id=delegate.id,
                               is_direct=True, ballot={"grades": grades}))
        print(title, proposal.id)
    db.commit()
    print("All four experimental methods enabled only in synthetic local org. Existing ballots/statuses preserved.")
