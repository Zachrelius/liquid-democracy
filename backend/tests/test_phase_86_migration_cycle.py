"""Phase 86 migration cycle — upgrade → downgrade → upgrade on SQLite.

The Phase 86 migration (e5f6a7b8c9d0) creates the ``content_reports`` table
(with a partial-unique open-report index). Verifies the table appears after
upgrade, disappears after downgrade, and reappears after re-upgrade. Mirrors
the Phase 85 cycle harness (bootstrap via create_tables + stamp prior, since
the project's early migrations aren't clean-from-base on SQLite).
"""
import os
import subprocess
import sys
import tempfile

import sqlalchemy as sa


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PHASE_86_REVISION = "e5f6a7b8c9d0"
_PRIOR_REVISION = "d4e5f6a7b8c9"


def _run_alembic(db_url: str, *args: str) -> None:
    env = dict(os.environ)
    env["DATABASE_URL"] = db_url
    res = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=_BACKEND_DIR, env=env, capture_output=True, text=True,
    )
    assert res.returncode == 0, (
        f"alembic {' '.join(args)} failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    )


def _has_table(db_url: str, table: str) -> bool:
    eng = sa.create_engine(db_url)
    try:
        return table in set(sa.inspect(eng).get_table_names())
    finally:
        eng.dispose()


def _bootstrap_schema_at_prior(db_url: str) -> None:
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


def test_phase_86_migration_cycle():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _bootstrap_schema_at_prior(db_url)

        _run_alembic(db_url, "upgrade", _PHASE_86_REVISION)
        assert _has_table(db_url, "content_reports")

        _run_alembic(db_url, "downgrade", _PRIOR_REVISION)
        assert not _has_table(db_url, "content_reports")

        _run_alembic(db_url, "upgrade", _PHASE_86_REVISION)
        assert _has_table(db_url, "content_reports")
    finally:
        if os.path.exists(path):
            os.remove(path)
