"""Phase 71a migration cycle + backfill parity — upgrade → downgrade → upgrade.

The Phase 71a migration (c1d2e3f4a5b6) is a data-only backfill that seeds
``role_permissions`` rows for the keys Phase 71 (71a+71b) makes config-
authoritative, to match CURRENT behavior so enforcement is a no-op for
existing orgs. The genuinely-new rows for the existing-org population are
the moderator's ``member.suspend`` and ``polis.manage`` (moderators could
already do both via the moderator+ tier; the rows just make the config
honest). Steward/admin already hold every key.

Verifies:
  1. An org created BEFORE the migration (moderator missing member.suspend
     + polis.manage) reaches parity with a freshly-seeded org after upgrade.
  2. Downgrade removes exactly the net-new moderator rows; re-upgrade
     restores them. Steward/admin rows are never touched.
  3. The backfill is idempotent — a moderator that already holds
     member.suspend is not duplicated.

Mirrors the subprocess alembic harness in test_phase_68b_migration_cycle.py.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import sqlalchemy as sa


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PHASE_71A_REVISION = "c1d2e3f4a5b6"
_PRIOR_REVISION = "b8e3f1a09d24"
_NET_NEW_MODERATOR_KEYS = ("member.suspend", "polis.manage")


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


def _seed_pre_71a_org(db_url: str, *, keep_suspend_for_moderator: bool = False) -> str:
    """Create schema, insert an org seeded with default roles, then delete
    the moderator's member.suspend + polis.manage rows (simulating a pre-71
    org seeded with the old DEFAULT_GRANTS). Stamp the prior revision.

    ``keep_suspend_for_moderator`` — keep the moderator's member.suspend row
    to prove the upgrade is idempotent (skip-if-exists)."""
    drop_keys = "['polis.manage']" if keep_suspend_for_moderator else \
        "['member.suspend','polis.manage']"
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
        "mod=db.query(models.Role.id).filter_by(org_id=o.id, system_key='moderator').scalar();"
        f"db.query(models.RolePermission).filter("
        "models.RolePermission.role_id==mod,"
        f"models.RolePermission.permission_key.in_({drop_keys})"
        ").delete(synchronize_session=False);"
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


def _grants(db_url: str, org_id: str, key: str) -> dict[str, int]:
    """Return {system_key: count of enabled rows for ``key``}."""
    engine = sa.create_engine(db_url)
    try:
        rows = engine.connect().execute(sa.text(
            "SELECT r.system_key, COUNT(rp.id) "
            "FROM roles r "
            "LEFT JOIN role_permissions rp "
            "  ON rp.role_id = r.id "
            "  AND rp.permission_key = :k "
            "  AND rp.enabled = 1 "
            "WHERE r.org_id = :oid "
            "GROUP BY r.system_key"
        ), {"k": key, "oid": org_id}).fetchall()
        return {r[0]: r[1] for r in rows}
    finally:
        engine.dispose()


def test_phase_71a_backfill_brings_existing_org_to_parity():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        org_id = _seed_pre_71a_org(db_url)
        before = _grants(db_url, org_id, "member.suspend")
        assert before.get("moderator", 0) == 0  # simulated pre-71

        _run_alembic(db_url, "upgrade", "head")

        for key in _NET_NEW_MODERATOR_KEYS:
            after = _grants(db_url, org_id, key)
            assert after["moderator"] == 1, f"{key} not backfilled for moderator"
            assert after["steward"] == 1
            assert after["admin"] == 1
            assert after.get("member", 0) == 0
        # Admin-only key stays admin-only (no moderator row).
        td = _grants(db_url, org_id, "topic.delete")
        assert td["steward"] == 1 and td["admin"] == 1
        assert td.get("moderator", 0) == 0
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase_71a_upgrade_downgrade_upgrade_cycle():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        org_id = _seed_pre_71a_org(db_url)

        _run_alembic(db_url, "upgrade", "head")
        assert _grants(db_url, org_id, "member.suspend")["moderator"] == 1
        assert _grants(db_url, org_id, "polis.manage")["moderator"] == 1
        # Steward/admin held member.suspend before the migration too.
        assert _grants(db_url, org_id, "member.suspend")["steward"] == 1

        _run_alembic(db_url, "downgrade", _PRIOR_REVISION)
        # Net-new moderator rows removed...
        assert _grants(db_url, org_id, "member.suspend").get("moderator", 0) == 0
        assert _grants(db_url, org_id, "polis.manage").get("moderator", 0) == 0
        # ...but steward/admin rows are untouched (pre-dated the migration).
        assert _grants(db_url, org_id, "member.suspend")["steward"] == 1
        assert _grants(db_url, org_id, "member.suspend")["admin"] == 1

        _run_alembic(db_url, "upgrade", "head")
        assert _grants(db_url, org_id, "member.suspend")["moderator"] == 1
        assert _grants(db_url, org_id, "polis.manage")["moderator"] == 1
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase_71a_backfill_is_idempotent():
    """A moderator that already holds member.suspend (hand-edited / partially
    backfilled) is not duplicated by the upgrade."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        org_id = _seed_pre_71a_org(db_url, keep_suspend_for_moderator=True)
        before = _grants(db_url, org_id, "member.suspend")
        assert before["moderator"] == 1  # kept
        assert _grants(db_url, org_id, "polis.manage").get("moderator", 0) == 0

        _run_alembic(db_url, "upgrade", "head")
        after = _grants(db_url, org_id, "member.suspend")
        # Still exactly one (not duplicated); polis.manage backfilled.
        assert after["moderator"] == 1
        assert _grants(db_url, org_id, "polis.manage")["moderator"] == 1
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
