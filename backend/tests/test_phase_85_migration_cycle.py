"""Phase 85 migration cycle — upgrade → downgrade → upgrade on SQLite.

The Phase 85 migration (d4e5f6a7b8c9) is additive schema only:
  * adds ``comments.removed_by_id`` (nullable FK column + index)
  * creates the ``org_bans`` table + its partial-unique active-ban index

Verifies the column + table appear after upgrade, disappear after downgrade,
and reappear after re-upgrade (reversibility). Mirrors the subprocess alembic
harness used by the other phase migration-cycle tests.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import sqlalchemy as sa


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PHASE_85_REVISION = "d4e5f6a7b8c9"
_PRIOR_REVISION = "c2d3e4f5a6b7"


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


def _has_column(db_url: str, table: str, column: str) -> bool:
    eng = sa.create_engine(db_url)
    try:
        cols = {c["name"] for c in sa.inspect(eng).get_columns(table)}
        return column in cols
    finally:
        eng.dispose()


def _has_table(db_url: str, table: str) -> bool:
    eng = sa.create_engine(db_url)
    try:
        return table in set(sa.inspect(eng).get_table_names())
    finally:
        eng.dispose()


def _bootstrap_schema_at_prior(db_url: str) -> None:
    """Build the full current schema (Base.metadata.create_all) then stamp the
    prior revision. The project's early migrations aren't clean-from-base on
    SQLite, so every migration-cycle test bootstraps this way (see
    test_phase_71a_migration_cycle). create_tables() already includes the
    Phase 85 column + table; the migration's idempotent guards make the first
    upgrade a no-op. The load-bearing assertions are on downgrade (drop) then
    re-upgrade (re-add)."""
    code = (
        "import os;"
        f"os.environ['DATABASE_URL']={db_url!r};"
        "from database import create_tables; create_tables()"
    )
    res = subprocess.run(
        [sys.executable, "-c", code], cwd=_BACKEND_DIR, capture_output=True, text=True,
    )
    assert res.returncode == 0, f"schema bootstrap failed:\n{res.stderr}"
    _run_alembic(db_url, "stamp", _PRIOR_REVISION)


def test_phase_85_migration_cycle():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _bootstrap_schema_at_prior(db_url)

        # Upgrade to Phase 85 head — idempotent no-op over the create_all
        # schema, but confirms the migration applies cleanly.
        _run_alembic(db_url, "upgrade", _PHASE_85_REVISION)
        assert _has_column(db_url, "comments", "removed_by_id")
        assert _has_table(db_url, "org_bans")

        # Downgrade — both removed (proves down() works).
        _run_alembic(db_url, "downgrade", _PRIOR_REVISION)
        assert not _has_column(db_url, "comments", "removed_by_id")
        assert not _has_table(db_url, "org_bans")

        # Re-upgrade — both back (reversibility proven).
        _run_alembic(db_url, "upgrade", _PHASE_85_REVISION)
        assert _has_column(db_url, "comments", "removed_by_id")
        assert _has_table(db_url, "org_bans")
    finally:
        if os.path.exists(path):
            os.remove(path)
