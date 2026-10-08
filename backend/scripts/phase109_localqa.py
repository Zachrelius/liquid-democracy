"""Create synthetic local-only browser fixtures; never connect to production."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import datetime, timedelta, timezone
import auth
import models
from database import Base, engine, SessionLocal
from experimental_voting import initialize_rules
from role_seed import seed_default_roles_for_org

if engine.url.get_backend_name() != "sqlite":
    raise SystemExit("Local QA fixture requires SQLite")
Base.metadata.create_all(engine)
with SessionLocal() as db:
    if db.query(models.Organization).filter_by(slug="phase109-qa").first():
        raise SystemExit("Fixture already exists; preserving existing ballots")
    user = models.User(username="phase109qa", display_name="Phase 109 Tester",
                       email="phase109qa@demo.example", email_verified=True,
                       password_hash=auth.hash_password("LocalQA109-only!"), is_admin=True)
    org = models.Organization(name="Phase 109 Local QA", slug="phase109-qa", join_policy="open",
                              settings={"allowed_voting_methods": ["binary", "approval", "star"],
                                        "verification_proposal_policy": "never"})
    db.add_all([user, org]); db.flush()
    seed_default_roles_for_org(db, org.id)
    role = db.query(models.Role).filter_by(org_id=org.id, system_key="steward").one()
    db.add(models.OrgMembership(user_id=user.id, org_id=org.id, role_id=role.id, status="active"))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for name, state in [("STAR browser journey", "voting"), ("STAR early ballot", "deliberation")]:
        p = models.Proposal(title=name, body="Choose one community project. Synthetic local test only.",
                            org_id=org.id, author_id=user.id, voting_method="star", num_winners=1,
                            status=state, quorum_threshold=0, voting_start=now,
                            voting_end=now + timedelta(days=7), deliberation_start=now,
                            allow_pre_voting=True, allow_write_in_options=True,
                            allow_write_ins_during_voting=True, show_votes_during_deliberation=False)
        db.add(p); db.flush(); initialize_rules(p)
        db.add_all([models.ProposalOption(proposal_id=p.id, label=label, display_order=i)
                    for i, label in enumerate(["Community center", "Playground", "Parking"])])
        print(name, p.id)
    db.commit()
    print("Local QA ready: phase109qa / LocalQA109-only!")
