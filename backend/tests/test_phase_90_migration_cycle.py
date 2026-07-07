"""Phase 90 migration: upgrade -> downgrade -> upgrade on SQLite.

Adds the share_events table. Verifies it exists after upgrade, is gone after
downgrade, and returns on re-upgrade. Mirrors the Phase 88 cycle test shape.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import sqlalchemy as sa

_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PHASE_90 = "c9d0e1f2a3b4"
_PRIOR = "b8c9d0e1f2a3"


def _run_alembic(db_url: str, *args: str) -> None:
    env = dict(os.environ)
    env["DATABASE_URL"] = db_url
    res = subprocess.run([sys.executable, "-m", "alembic", *args],
                         cwd=_BACKEND_DIR, env=env, capture_output=True, text=True)
    assert res.returncode == 0, (
        f"alembic {' '.join(args)} failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    )


def _create_all(db_url: str) -> None:
    code = (f"import os; os.environ['DATABASE_URL']={db_url!r}; "
            "from database import create_tables; create_tables()")
    res = subprocess.run([sys.executable, "-c", code], cwd=_BACKEND_DIR,
                         capture_output=True, text=True)
    assert res.returncode == 0, f"create_tables failed:\n{res.stdout}\n{res.stderr}"


def _tables(db_url: str) -> set[str]:
    engine = sa.create_engine(db_url)
    try:
        return set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_phase90_migration_cycle():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _create_all(db_url)
        _run_alembic(db_url, "stamp", _PRIOR)
        _run_alembic(db_url, "upgrade", _PHASE_90)
        assert "share_events" in _tables(db_url)
        _run_alembic(db_url, "downgrade", _PRIOR)
        assert "share_events" not in _tables(db_url)
        _run_alembic(db_url, "upgrade", _PHASE_90)
        assert "share_events" in _tables(db_url)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
