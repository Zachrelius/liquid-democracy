"""Phase 87 migration cycle — upgrade -> downgrade -> upgrade on SQLite.

Migration f6a7b8c9d0e1 adds the four nullable org-restriction columns. Same
bootstrap pattern as prior phases (create_tables + stamp prior, since early
migrations aren't clean-from-base on SQLite).
"""
import os
import subprocess
import sys
import tempfile

import sqlalchemy as sa


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PHASE_87_REVISION = "f6a7b8c9d0e1"
_PRIOR_REVISION = "e5f6a7b8c9d0"
_COLS = ("platform_restriction", "restricted_at", "restricted_by_id", "restriction_reason")


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


def _cols(db_url: str) -> set[str]:
    eng = sa.create_engine(db_url)
    try:
        return {c["name"] for c in sa.inspect(eng).get_columns("organizations")}
    finally:
        eng.dispose()


def _bootstrap(db_url: str) -> None:
    code = (
        "import os;"
        f"os.environ['DATABASE_URL']={db_url!r};"
        "from database import create_tables; create_tables()"
    )
    res = subprocess.run([sys.executable, "-c", code], cwd=_BACKEND_DIR, capture_output=True, text=True)
    assert res.returncode == 0, f"schema bootstrap failed:\n{res.stderr}"
    _run_alembic(db_url, "stamp", _PRIOR_REVISION)


def test_phase_87_migration_cycle():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _bootstrap(db_url)
        _run_alembic(db_url, "upgrade", _PHASE_87_REVISION)
        assert all(c in _cols(db_url) for c in _COLS)
        _run_alembic(db_url, "downgrade", _PRIOR_REVISION)
        assert not any(c in _cols(db_url) for c in _COLS)
        _run_alembic(db_url, "upgrade", _PHASE_87_REVISION)
        assert all(c in _cols(db_url) for c in _COLS)
    finally:
        if os.path.exists(path):
            os.remove(path)
