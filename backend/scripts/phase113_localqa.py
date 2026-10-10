"""Additive isolated SQLite browser fixtures. Refuses production and collisions."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import models, auth
from database import Base, engine, SessionLocal
from role_seed import seed_default_roles_for_org
from notification_events import EVENT_REGISTRY
from routes.organizations import DEFAULT_ORG_SETTINGS
if engine.url.get_backend_name() != "sqlite" or Path(engine.url.database).name != ".tmp_phase113_localqa.db":
    raise SystemExit("Exact local Phase113 SQLite path required")
Base.metadata.create_all(engine)
with SessionLocal() as db:
    if db.query(models.Organization).filter_by(slug="phase113-localqa").first():
        raise SystemExit("Fixture exists; refusing overwrite")
    root = models.Organization(name="Phase 113 Local QA", slug="phase113-localqa", join_policy="invite", discoverability="hidden", activity_visibility="members_only", settings={**DEFAULT_ORG_SETTINGS, "verification_proposal_policy":"never"})
    user = models.User(username="phase113localowner", display_name="Phase 113 Fictional Owner", email="phase113localowner@demo.example", email_verified=True, is_admin=False, notification_intro_dismissed=True, password_hash=auth.hash_password("LocalQA113-only-fictional!"))
    db.add_all([root,user]);db.flush()
    roles = seed_default_roles_for_org(db,root.id)
    db.add(models.OrgMembership(org_id=root.id,user_id=user.id,role_id=roles["steward"].id,status="active"))
    for entry in EVENT_REGISTRY:
        for channel in ("in_app","email_immediate","email_daily","email_weekly"):
            db.add(models.NotificationPreference(user_id=user.id,event_type=entry.key,channel=channel,enabled=False))
    child = models.Organization(name="Phase 113 Child",slug="phase113-child",parent_org=root,settings={},join_policy="invite",discoverability="hidden",activity_visibility="members_only")
    db.add(child);db.flush()
    db.add(models.SubOrgMembership(sub_org_id=child.id,user_id=user.id,role_id=roles["admin"].id,status="active"))
    db.commit()
    print("Synthetic local fixture created; notification channels disabled")
