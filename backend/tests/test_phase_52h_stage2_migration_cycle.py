"""Phase 52h Stage 2 migration cycle test."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import sqlalchemy as sa


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PHASE_REVISION = "e6f7a8b9c0d1"
_PRIOR_REVISION = "d5e6f7a8b9c0"  # Phase 52h Stage 1
DOC_NUMBER_UNIQUE_INDEX = "ix_users_doc_number_hash_unique"


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


def _indexes(db_url: str, table: str) -> set[str]:
    engine = sa.create_engine(db_url)
    try:
        return {ix["name"] for ix in sa.inspect(engine).get_indexes(table)}
    finally:
        engine.dispose()


def _build_pre(db_url: str) -> None:
    _create_all_subprocess(db_url)
    _run_alembic(db_url, "stamp", "head")
    _run_alembic(db_url, "downgrade", _PRIOR_REVISION)


def test_upgrade_drops_doc_number_unique_index():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre(db_url)
        # Pre-state: the partial-unique index exists (it's created
        # at d5e6f7a8b9c0 and prior).
        assert DOC_NUMBER_UNIQUE_INDEX in _indexes(db_url, "users")
        _run_alembic(db_url, "upgrade", "head")
        # Post-state: the index is gone.
        assert DOC_NUMBER_UNIQUE_INDEX not in _indexes(db_url, "users")
    finally:
        try: os.unlink(path)
        except OSError: pass


def test_downgrade_upgrade_cycle_recreates_index():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre(db_url)
        _run_alembic(db_url, "upgrade", "head")
        assert DOC_NUMBER_UNIQUE_INDEX not in _indexes(db_url, "users")
        _run_alembic(db_url, "downgrade", _PRIOR_REVISION)
        assert DOC_NUMBER_UNIQUE_INDEX in _indexes(db_url, "users")
        _run_alembic(db_url, "upgrade", "head")
        assert DOC_NUMBER_UNIQUE_INDEX not in _indexes(db_url, "users")
    finally:
        try: os.unlink(path)
        except OSError: pass
