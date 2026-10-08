"""Explicit, additive-only bootstrap for the isolated Phase 109 release QA org.

Does not create proposals: exercise normal authenticated API/UI creation after
bootstrap so server initialization creates fresh committed voting rules.
Never prints passwords, hashes, access tokens or database connection strings.
"""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SLUG = "phase109-release-qa-20261008"
ACCOUNTS = (("phase109releaseowner", "Phase 109 Release Owner", "steward"),
            ("phase109releasemember", "Phase 109 Release Member", "member"))


def bootstrap(db, owner_password, member_password):
    import auth
    import models
    from notification_events import EVENT_REGISTRY
    from role_seed import seed_default_roles_for_org
    from sqlalchemy import or_
    from voting_methods import DEFAULT_ENABLED_VOTING_METHODS, EXPERIMENTAL_VOTING_METHODS

    passwords = [owner_password, member_password]
    if any(not isinstance(password, str) or len(password) < 20 for password in passwords):
        raise ValueError("Supply two new synthetic passwords of at least 20 characters")
    if owner_password == member_password:
        raise ValueError("Synthetic accounts require distinct passwords")
    usernames = [row[0] for row in ACCOUNTS]
    emails = [username + "@demo.example" for username in usernames]
    # Check every collision before inserting anything; caller owns rollback.
    if db.query(models.Organization.id).filter_by(slug=SLUG).first():
        raise ValueError("QA organization already exists; refusing to modify it")
    if db.query(models.User.id).filter(or_(models.User.username.in_(usernames), models.User.email.in_(emails))).first():
        raise ValueError("QA account identity already exists; refusing to modify it")
    org = models.Organization(name="Phase 109 Isolated Release QA", slug=SLUG,
        description="Synthetic private release verification; no real members or decisions.",
        join_policy="invite", discoverability="hidden", activity_visibility="members_only", is_demo=False,
        settings={"allowed_voting_methods": list(DEFAULT_ENABLED_VOTING_METHODS + EXPERIMENTAL_VOTING_METHODS),
                  "verification_proposal_policy": "never"})
    db.add(org)
    db.flush()
    roles = seed_default_roles_for_org(db, org.id)
    identities = []
    for (username, display_name, role), password in zip(ACCOUNTS, passwords):
        user = models.User(username=username, display_name=display_name,
                          email=username + "@demo.example", email_verified=True,
                          password_hash=auth.hash_password(password), is_admin=False,
                          notification_intro_dismissed=True)
        db.add(user)
        db.flush()
        db.add(models.OrgMembership(org_id=org.id, user_id=user.id, role_id=roles[role].id, status="active"))
        for event in EVENT_REGISTRY:
            for channel in ("in_app", "email_immediate", "email_daily", "email_weekly"):
                db.add(models.NotificationPreference(user_id=user.id, event_type=event.key,
                                                     channel=channel, enabled=False))
        identities.append({"id": user.id, "username": username, "org_role": role})
    db.flush()
    return {"org_id": org.id, "org_slug": org.slug, "accounts": identities,
            "proposals_created": 0, "identity_provider_calls": 0, "email_sends": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-isolated-production-qa", action="store_true")
    args = parser.parse_args()
    if not args.confirm_isolated_production_qa:
        parser.error("Explicit --confirm-isolated-production-qa is required; no writes performed")
    # Require an explicit connection selected by the operator; do not silently
    # inherit a developer .env or create a local SQLite database.
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith(("postgresql://", "postgresql+psycopg2://", "postgres://")):
        parser.error("An explicit PostgreSQL DATABASE_URL is required")
    owner = os.environ.get("PHASE109_QA_OWNER_PASSWORD")
    member = os.environ.get("PHASE109_QA_MEMBER_PASSWORD")
    from database import SessionLocal
    with SessionLocal() as db:
        with db.begin():
            result = bootstrap(db, owner, member)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
