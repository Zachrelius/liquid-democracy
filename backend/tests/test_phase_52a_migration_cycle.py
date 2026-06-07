"""Phase 52a migration cycle test.

Verifies the upgrade adds the ``verification_sessions`` table and the
nullifier unique index, the downgrade removes them, and a re-upgrade
restores the schema. Subprocesses an alembic run against SQLite so
the test exercises the migration script exactly as a deploy would.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import sqlalchemy as sa


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PHASE_52A_REVISION = "e0a1b2c3d4f5"
_PRIOR_REVISION = "d9e4f2a78543"  # Phase 52 Stage 1 proposal floor
NULLIFIER_UNIQUE_INDEX = "ix_users_verification_nullifier_unique"


def _run_alembic(db_url: str, *args: str) -> None:
    env = dict(os.environ)
    env["DATABASE_URL"] = db_url
    res = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=_BACKEND_DIR, env=env,
        capture_output=True, text=True,
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


def _tables(db_url: str) -> set[str]:
    engine = sa.create_engine(db_url)
    try:
        return set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()


def _indexes(db_url: str, table: str) -> set[str]:
    engine = sa.create_engine(db_url)
    try:
        return {ix["name"] for ix in sa.inspect(engine).get_indexes(table)}
    finally:
        engine.dispose()


def _build_pre_52a(db_url: str) -> None:
    _create_all_subprocess(db_url)
    _run_alembic(db_url, "stamp", "head")
    _run_alembic(db_url, "downgrade", _PRIOR_REVISION)


def test_phase_52a_upgrade_adds_table_and_index():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_52a(db_url)
        pre_tables = _tables(db_url)
        pre_indexes = _indexes(db_url, "users")
        assert "verification_sessions" not in pre_tables
        assert NULLIFIER_UNIQUE_INDEX not in pre_indexes
        _run_alembic(db_url, "upgrade", _PHASE_52A_REVISION)
        post_tables = _tables(db_url)
        post_indexes = _indexes(db_url, "users")
        assert "verification_sessions" in post_tables
        assert NULLIFIER_UNIQUE_INDEX in post_indexes
    finally:
        try: os.unlink(path)
        except OSError: pass


def test_phase_52a_downgrade_upgrade_cycle():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_52a(db_url)
        _run_alembic(db_url, "upgrade", _PHASE_52A_REVISION)
        assert "verification_sessions" in _tables(db_url)
        _run_alembic(db_url, "downgrade", _PRIOR_REVISION)
        assert "verification_sessions" not in _tables(db_url)
        assert NULLIFIER_UNIQUE_INDEX not in _indexes(db_url, "users")
        _run_alembic(db_url, "upgrade", _PHASE_52A_REVISION)
        assert "verification_sessions" in _tables(db_url)
        assert NULLIFIER_UNIQUE_INDEX in _indexes(db_url, "users")
    finally:
        try: os.unlink(path)
        except OSError: pass


# Phase 58 Cluster C — `test_nullifier_unique_index_allows_multiple_nulls`
# removed. It asserted partial-unique-index NULL tolerance on the
# `verification_nullifier` column. The column itself was dropped in
# migration `c0d1e2f3a4b5` (this pass), so the property the test guarded
# is moot. The Phase 58 migration cycle test asserts the column is gone,
# which is the natural successor guard.
