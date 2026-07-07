"""Phase 90a migration cycle: upgrade -> downgrade -> upgrade on SQLite.

Adds share_distribution_rules, org_memberships.share_start_date, the
share_events.rule_id index, and the partial-unique period_key index.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import sqlalchemy as sa

_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PHASE_90A = "d0e1f2a3b4c5"
_PRIOR = "c9d0e1f2a3b4"


def _run_alembic(db_url: str, *args: str) -> None:
    env = dict(os.environ); env["DATABASE_URL"] = db_url
    res = subprocess.run([sys.executable, "-m", "alembic", *args],
                         cwd=_BACKEND_DIR, env=env, capture_output=True, text=True)
    assert res.returncode == 0, (
        f"alembic {' '.join(args)} failed:\n{res.stdout}\n{res.stderr}")


def _create_all(db_url: str) -> None:
    code = (f"import os; os.environ['DATABASE_URL']={db_url!r}; "
            "from database import create_tables; create_tables()")
    res = subprocess.run([sys.executable, "-c", code], cwd=_BACKEND_DIR,
                         capture_output=True, text=True)
    assert res.returncode == 0, f"create_tables failed:\n{res.stdout}\n{res.stderr}"


def _tables(db_url: str) -> set[str]:
    e = sa.create_engine(db_url)
    try:
        return set(sa.inspect(e).get_table_names())
    finally:
        e.dispose()


def _cols(db_url: str, table: str) -> set[str]:
    e = sa.create_engine(db_url)
    try:
        return {c["name"] for c in sa.inspect(e).get_columns(table)}
    finally:
        e.dispose()


def test_phase90a_migration_cycle():
    fd, path = tempfile.mkstemp(suffix=".db"); os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _create_all(db_url)
        _run_alembic(db_url, "stamp", _PRIOR)
        _run_alembic(db_url, "upgrade", _PHASE_90A)
        assert "share_distribution_rules" in _tables(db_url)
        assert "share_start_date" in _cols(db_url, "org_memberships")
        _run_alembic(db_url, "downgrade", _PRIOR)
        assert "share_distribution_rules" not in _tables(db_url)
        assert "share_start_date" not in _cols(db_url, "org_memberships")
        _run_alembic(db_url, "upgrade", _PHASE_90A)
        assert "share_distribution_rules" in _tables(db_url)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
