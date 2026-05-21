"""Phase 33 D1 + D2: migration cycle test.

Subprocess-invoke alembic so each call gets a fresh process + clean
SQLite connection. Pattern matches Phase 32 / 32.1 / 32.2's
migration_cycle tests.

Load-bearing assertions:

1. After ``create_tables()`` + stamp at Phase 33 head: the legacy columns
   (``delegate_profiles.is_active``, ``topics.description``) are absent
   from the live schema.
2. Phase 33 → Phase 32.2 downgrade re-adds both columns.
3. Re-upgrade is idempotent (the second upgrade traversal finds the
   columns absent again and exits cleanly).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import sqlalchemy as sa


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PHASE_33_REVISION = "b6d8e2f1a350"
_PRIOR_REVISION = "e7a3d1c84920"  # Phase 32.2


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


def _bootstrap_at_head(db_url: str) -> None:
    env = dict(os.environ)
    env["DATABASE_URL"] = db_url
    res = subprocess.run(
        [sys.executable, "-c",
         "from database import create_tables; create_tables()"],
        cwd=_BACKEND_DIR, env=env, capture_output=True, text=True,
    )
    assert res.returncode == 0, (
        f"create_tables failed:\nSTDOUT:\n{res.stdout}\n"
        f"STDERR:\n{res.stderr}"
    )
    _run_alembic(db_url, "stamp", _PHASE_33_REVISION)


def _columns(db_url: str, table: str) -> set[str]:
    engine = sa.create_engine(db_url)
    inspector = sa.inspect(engine)
    try:
        return {c["name"] for c in inspector.get_columns(table)}
    finally:
        engine.dispose()


def test_phase33_columns_absent_at_head():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _bootstrap_at_head(db_url)
        assert "is_active" not in _columns(db_url, "delegate_profiles")
        assert "description" not in _columns(db_url, "topics")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase33_downgrade_restores_columns():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _bootstrap_at_head(db_url)

        _run_alembic(db_url, "downgrade", _PRIOR_REVISION)
        assert "is_active" in _columns(db_url, "delegate_profiles")
        assert "description" in _columns(db_url, "topics")

        # Re-upgrade
        _run_alembic(db_url, "upgrade", _PHASE_33_REVISION)
        assert "is_active" not in _columns(db_url, "delegate_profiles")
        assert "description" not in _columns(db_url, "topics")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
