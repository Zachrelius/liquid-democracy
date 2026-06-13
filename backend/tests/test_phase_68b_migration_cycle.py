"""Phase 68b migration cycle + backfill parity — upgrade → downgrade → upgrade.

The Phase 68b migration (b8e3f1a09d24) is a data-only backfill: it grants
``proposal.archive`` to the steward + admin roles of every EXISTING org
(matching DEFAULT_GRANTS, which new orgs already pick up at seed time).

This closes the recurring "new DEFAULT_GRANTS key only reaches new orgs"
gap (hotfixes 45a / 46 / 47). Verifies:
  1. An org created BEFORE the migration (no proposal.archive row) reaches
     parity with a newly-seeded org after upgrade — steward + admin hold
     the key; member does not.
  2. Downgrade removes the backfilled rows; re-upgrade restores them.
  3. The backfill is idempotent — a pre-existing row is not duplicated.

Mirrors the subprocess alembic harness in test_phase_47_migration_cycle.py.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import sqlalchemy as sa


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PHASE_68B_REVISION = "b8e3f1a09d24"
_PRIOR_REVISION = "a3f6c8e21b94"


def _run_alembic(db_url: str, *args: str) -> None:
    env = dict(os.environ)
    env["DATABASE_URL"] = db_url
    res = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=_BACKEND_DIR, env=env, capture_output=True, text=True,
    )
    assert res.returncode == 0, (
        f"alembic {' '.join(args)} failed:\nSTDOUT:\n{res.stdout}\n"
        f"STDERR:\n{res.stderr}"
    )


def _seed_pre_68b_org(db_url: str, *, keep_archive_for: str | None = None) -> str:
    """Create the schema, stamp the prior revision, then insert an org with
    seeded roles whose proposal.archive rows have been removed (simulating
    a pre-68b existing org). Returns the org id.

    ``keep_archive_for`` — if a system_key (e.g. 'steward'), that role
    KEEPS its proposal.archive row, simulating a partially-backfilled /
    hand-edited org (used to prove idempotency).
    """
    code = (
        "import os;"
        f"os.environ['DATABASE_URL']={db_url!r};"
        "from database import create_tables; create_tables();"
        "from sqlalchemy import create_engine;"
        "from sqlalchemy.orm import sessionmaker;"
        "import models;"
        "from role_seed import seed_default_roles_for_org;"
        f"eng=create_engine({db_url!r});"
        "S=sessionmaker(bind=eng); db=S();"
        "o=models.Organization(name='Old', slug='old-org', description='');"
        "db.add(o); db.flush();"
        "seed_default_roles_for_org(db, o.id);"
        "rid_sub=db.query(models.Role.id).filter_by(org_id=o.id);"
        "q=db.query(models.RolePermission).filter("
        "models.RolePermission.permission_key=='proposal.archive',"
        "models.RolePermission.role_id.in_(rid_sub));"
        + (
            "keep=db.query(models.Role.id).filter_by(org_id=o.id, "
            f"system_key={keep_archive_for!r}).scalar();"
            "q=q.filter(models.RolePermission.role_id!=keep);"
            if keep_archive_for else ""
        )
        + "q.delete(synchronize_session=False);"
        "db.commit();"
        "print(o.id)"
    )
    res = subprocess.run(
        [sys.executable, "-c", code],
        cwd=_BACKEND_DIR, capture_output=True, text=True,
    )
    assert res.returncode == 0, (
        f"seed failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    )
    org_id = res.stdout.strip().splitlines()[-1]
    _run_alembic(db_url, "stamp", _PRIOR_REVISION)
    return org_id


def _archive_grants(db_url: str, org_id: str) -> dict[str, int]:
    """Return {system_key: count of enabled proposal.archive rows}."""
    engine = sa.create_engine(db_url)
    try:
        rows = engine.connect().execute(sa.text(
            "SELECT r.system_key, COUNT(rp.id) "
            "FROM roles r "
            "LEFT JOIN role_permissions rp "
            "  ON rp.role_id = r.id "
            "  AND rp.permission_key = 'proposal.archive' "
            "  AND rp.enabled = 1 "
            "WHERE r.org_id = :oid "
            "GROUP BY r.system_key"
        ), {"oid": org_id}).fetchall()
        return {r[0]: r[1] for r in rows}
    finally:
        engine.dispose()


def test_phase_68b_backfill_brings_existing_org_to_parity():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        org_id = _seed_pre_68b_org(db_url)
        # Pre-upgrade: no role holds proposal.archive (simulated pre-68b).
        before = _archive_grants(db_url, org_id)
        assert before.get("steward", 0) == 0
        assert before.get("admin", 0) == 0

        _run_alembic(db_url, "upgrade", "head")
        after = _archive_grants(db_url, org_id)
        # Steward + admin reach parity; member does NOT get the key.
        assert after["steward"] == 1
        assert after["admin"] == 1
        assert after.get("member", 0) == 0
        assert after.get("moderator", 0) == 0
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase_68b_upgrade_downgrade_upgrade_cycle():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        org_id = _seed_pre_68b_org(db_url)

        _run_alembic(db_url, "upgrade", "head")
        assert _archive_grants(db_url, org_id)["steward"] == 1

        _run_alembic(db_url, "downgrade", _PRIOR_REVISION)
        assert _archive_grants(db_url, org_id).get("steward", 0) == 0
        assert _archive_grants(db_url, org_id).get("admin", 0) == 0

        _run_alembic(db_url, "upgrade", "head")
        assert _archive_grants(db_url, org_id)["steward"] == 1
        assert _archive_grants(db_url, org_id)["admin"] == 1
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase_68b_backfill_is_idempotent():
    """A role that ALREADY holds proposal.archive (hand-edited / partially
    backfilled) is not duplicated by the upgrade — skip-if-exists."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        # Steward keeps its proposal.archive row; admin's is removed.
        org_id = _seed_pre_68b_org(db_url, keep_archive_for="steward")
        before = _archive_grants(db_url, org_id)
        assert before["steward"] == 1
        assert before.get("admin", 0) == 0

        _run_alembic(db_url, "upgrade", "head")
        after = _archive_grants(db_url, org_id)
        # Steward still exactly one (not duplicated); admin backfilled to one.
        assert after["steward"] == 1
        assert after["admin"] == 1
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
