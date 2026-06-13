"""PG-smoke seed module for the Phase 68b backfill (actual-upgrade mode).

Seeds an org with default roles but WITHOUT the proposal.archive grant
(simulating a pre-68b existing org), then verifies the upgrade backfilled
proposal.archive onto steward + admin (and not member) on real Postgres.

Usage:
  python scripts/pg_smoke.py --mode actual-upgrade \
    --prior-revision a3f6c8e21b94 \
    --sample-data-script scripts/pg_smoke_seed_phase68b.py
"""
from __future__ import annotations

from sqlalchemy.orm import sessionmaker

_ORG_SLUG = "pg-smoke-68b"


def seed(engine) -> None:
    import models
    from role_seed import seed_default_roles_for_org

    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        org = models.Organization(name="PGSmoke68b", slug=_ORG_SLUG, description="")
        db.add(org)
        db.flush()
        seed_default_roles_for_org(db, org.id)
        # Simulate pre-68b: drop the proposal.archive rows the current seed
        # helper would have written.
        role_ids = db.query(models.Role.id).filter_by(org_id=org.id)
        db.query(models.RolePermission).filter(
            models.RolePermission.permission_key == "proposal.archive",
            models.RolePermission.role_id.in_(role_ids),
        ).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def verify(engine) -> None:
    import models

    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        org = db.query(models.Organization).filter_by(slug=_ORG_SLUG).one()
        grants: dict[str, int] = {}
        for role in db.query(models.Role).filter_by(org_id=org.id).all():
            n = db.query(models.RolePermission).filter_by(
                role_id=role.id, permission_key="proposal.archive", enabled=True,
            ).count()
            grants[role.system_key] = n
        assert grants.get("steward") == 1, grants
        assert grants.get("admin") == 1, grants
        assert grants.get("member", 0) == 0, grants
        assert grants.get("moderator", 0) == 0, grants
        print(f"[seed-verify] proposal.archive backfill parity OK: {grants}")
    finally:
        db.close()
