"""Phase 101 data-backfill migration cycle and preservation coverage."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import sqlalchemy as sa


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_REVISION = "d6e7f8a9b0c1"
_PRIOR_REVISION = "c5d6e7f8a9b0"
_KEY = "proposal.high_volume_create"


def _run_alembic(db_url: str, *args: str) -> None:
    env = dict(os.environ)
    env["DATABASE_URL"] = db_url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=_BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"alembic {' '.join(args)} failed:\nSTDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )


def _seed_pre_phase_101_org(
    db_url: str,
    *,
    preexisting_admin_enabled: bool | None = None,
) -> str:
    code = (
        "import os;"
        f"os.environ['DATABASE_URL']={db_url!r};"
        "from database import create_tables; create_tables();"
        "from sqlalchemy import create_engine;"
        "from sqlalchemy.orm import sessionmaker;"
        "import models;"
        "from role_seed import seed_default_roles_for_org;"
        f"engine=create_engine({db_url!r});"
        "Session=sessionmaker(bind=engine); db=Session();"
        "org=models.Organization(name='Old Org', slug='old-org', description='');"
        "db.add(org); db.flush(); seed_default_roles_for_org(db, org.id);"
        f"db.query(models.RolePermission).filter(models.RolePermission.permission_key=={_KEY!r}).delete(synchronize_session=False);"
        "custom=models.Role(org_id=org.id, name='Custom', system_key='custom', display_order=5);"
        "db.add(custom); db.flush();"
    )
    if preexisting_admin_enabled is not None:
        code += (
            "admin=db.query(models.Role).filter_by(org_id=org.id, system_key='admin').one();"
            "db.add(models.RolePermission(role_id=admin.id, "
            f"permission_key={_KEY!r}, enabled={preexisting_admin_enabled!r}));"
        )
    code += "db.commit(); print(org.id)"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=_BACKEND_DIR,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"seed failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    org_id = result.stdout.strip().splitlines()[-1]
    _run_alembic(db_url, "stamp", _PRIOR_REVISION)
    return org_id


def _rows_by_role(db_url: str, org_id: str) -> dict[str, list[bool]]:
    engine = sa.create_engine(db_url)
    try:
        with engine.connect() as connection:
            rows = connection.execute(sa.text(
                "SELECT r.system_key, rp.enabled "
                "FROM roles r LEFT JOIN role_permissions rp "
                "ON rp.role_id = r.id AND rp.permission_key = :key "
                "WHERE r.org_id = :org_id AND rp.id IS NOT NULL "
                "ORDER BY r.system_key"
            ), {"key": _KEY, "org_id": org_id}).fetchall()
        result: dict[str, list[bool]] = {}
        for system_key, enabled in rows:
            result.setdefault(system_key, []).append(bool(enabled))
        return result
    finally:
        engine.dispose()


def test_phase_101_backfill_defaults_and_preserves_explicit_disabled_row():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        org_id = _seed_pre_phase_101_org(
            db_url, preexisting_admin_enabled=False,
        )
        _run_alembic(db_url, "upgrade", _REVISION)
        rows = _rows_by_role(db_url, org_id)
        assert rows == {"admin": [False], "steward": [True]}
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase_101_upgrade_downgrade_upgrade_is_surgical_and_idempotent():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        org_id = _seed_pre_phase_101_org(db_url)
        _run_alembic(db_url, "upgrade", "head")
        assert _rows_by_role(db_url, org_id) == {
            "admin": [True], "steward": [True],
        }

        # Re-running the migration does not duplicate rows.
        _run_alembic(db_url, "upgrade", "head")
        assert _rows_by_role(db_url, org_id) == {
            "admin": [True], "steward": [True],
        }

        _run_alembic(db_url, "downgrade", _PRIOR_REVISION)
        assert _rows_by_role(db_url, org_id) == {}

        _run_alembic(db_url, "upgrade", "head")
        assert _rows_by_role(db_url, org_id) == {
            "admin": [True], "steward": [True],
        }
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
