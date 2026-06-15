"""Phase 75a migration: upgrade -> downgrade -> upgrade on SQLite.

Adds proposals.voting_end_date (DateTime, nullable). Verifies it appears after
upgrade, is gone after downgrade, and returns after re-upgrade.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import sqlalchemy as sa

_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PHASE_75A_REVISION = "f4a5b6c7d8e9"
_PRIOR_REVISION = "e3f4a5b6c7d8"


def _run_alembic(db_url: str, *args: str) -> None:
    env = dict(os.environ)
    env["DATABASE_URL"] = db_url
    res = subprocess.run([sys.executable, "-m", "alembic", *args],
                         cwd=_BACKEND_DIR, env=env, capture_output=True, text=True)
    assert res.returncode == 0, (
        f"alembic {' '.join(args)} failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    )


def _create_all_subprocess(db_url: str) -> None:
    code = (f"import os; os.environ['DATABASE_URL']={db_url!r}; "
            "from database import create_tables; create_tables()")
    res = subprocess.run([sys.executable, "-c", code], cwd=_BACKEND_DIR,
                         capture_output=True, text=True)
    assert res.returncode == 0, (
        f"create_tables failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    )


def _cols(db_url: str) -> set[str]:
    engine = sa.create_engine(db_url)
    try:
        return {c["name"] for c in sa.inspect(engine).get_columns("proposals")}
    finally:
        engine.dispose()


def test_phase75a_migration_cycle():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _create_all_subprocess(db_url)
        _run_alembic(db_url, "stamp", _PRIOR_REVISION)
        _run_alembic(db_url, "upgrade", _PHASE_75A_REVISION)
        assert "voting_end_date" in _cols(db_url)
        _run_alembic(db_url, "downgrade", _PRIOR_REVISION)
        assert "voting_end_date" not in _cols(db_url)
        _run_alembic(db_url, "upgrade", _PHASE_75A_REVISION)
        assert "voting_end_date" in _cols(db_url)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
