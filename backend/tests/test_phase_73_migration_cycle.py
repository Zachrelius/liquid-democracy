"""Phase 73 migration: upgrade -> downgrade -> upgrade on SQLite.

Adds two additive columns (proposals.budget_config JSON,
proposal_options.budget_max_amount Float). Verifies the columns exist after
upgrade, are gone after downgrade, and return after re-upgrade.

Mirrors test_phase14_migration_cycle.py's subprocess shape: build today's
schema via create_tables, stamp at the prior revision, then run the Phase 73
migration. The migration's add steps are guarded with _has_column so stamping
on a create_tables schema (which already has the columns) is a no-op upgrade —
the downgrade/re-upgrade pair is what exercises the real DDL.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import sqlalchemy as sa

_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PHASE_73_REVISION = "d2e3f4a5b6c7"
_PRIOR_REVISION = "c1d2e3f4a5b6"


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


def test_phase73_migration_upgrade_downgrade_upgrade():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _create_all_subprocess(db_url)
        _run_alembic(db_url, "stamp", _PRIOR_REVISION)

        # Upgrade (idempotent — columns already present from create_tables).
        _run_alembic(db_url, "upgrade", _PHASE_73_REVISION)
        assert "budget_config" in _cols(db_url, "proposals")
        assert "budget_max_amount" in _cols(db_url, "proposal_options")

        # Downgrade drops both columns.
        _run_alembic(db_url, "downgrade", _PRIOR_REVISION)
        assert "budget_config" not in _cols(db_url, "proposals")
        assert "budget_max_amount" not in _cols(db_url, "proposal_options")

        # Re-upgrade restores them.
        _run_alembic(db_url, "upgrade", _PHASE_73_REVISION)
        assert "budget_config" in _cols(db_url, "proposals")
        assert "budget_max_amount" in _cols(db_url, "proposal_options")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
