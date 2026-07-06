"""Phase 88 migration: upgrade -> downgrade -> upgrade on SQLite.

Two chained revisions:
  * a7b8c9d0e1f2 — adds org_memberships.voting_weight (Integer, default 1).
  * b8c9d0e1f2a3 — data-only backfill of member.set_voting_weight grants.

Verifies the column exists after upgrade, is gone after the column
migration's downgrade, and returns on re-upgrade. Mirrors
test_phase_73_migration_cycle.py's subprocess shape.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import sqlalchemy as sa

_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PHASE_88_COLUMN = "a7b8c9d0e1f2"
_PHASE_88_BACKFILL = "b8c9d0e1f2a3"
_PRIOR_REVISION = "f6a7b8c9d0e1"


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


def _create_all_subprocess(db_url: str) -> None:
    code = (
        f"import os; os.environ['DATABASE_URL']={db_url!r}; "
        "from database import create_tables; create_tables()"
    )
    res = subprocess.run(
        [sys.executable, "-c", code],
        cwd=_BACKEND_DIR, capture_output=True, text=True,
    )
    assert res.returncode == 0, (
        f"create_tables failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    )


def _cols(db_url: str, table: str) -> set[str]:
    engine = sa.create_engine(db_url)
    try:
        return {c["name"] for c in sa.inspect(engine).get_columns(table)}
    finally:
        engine.dispose()


def test_phase88_migration_upgrade_downgrade_upgrade():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _create_all_subprocess(db_url)
        _run_alembic(db_url, "stamp", _PRIOR_REVISION)

        # Upgrade through both Phase 88 revisions (column add is idempotent
        # because create_tables already made the column; the backfill is a
        # data-only no-op on an empty roles table).
        _run_alembic(db_url, "upgrade", _PHASE_88_BACKFILL)
        assert "voting_weight" in _cols(db_url, "org_memberships")

        # Downgrade the backfill (data-only) then the column migration.
        _run_alembic(db_url, "downgrade", _PRIOR_REVISION)
        assert "voting_weight" not in _cols(db_url, "org_memberships")

        # Re-upgrade restores the column.
        _run_alembic(db_url, "upgrade", _PHASE_88_BACKFILL)
        assert "voting_weight" in _cols(db_url, "org_memberships")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
