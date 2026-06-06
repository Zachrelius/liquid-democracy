"""Phase 52i migration cycle test."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import sqlalchemy as sa


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_REV = "a8b9c0d1e2f3"
_PRIOR = "f7a8b9c0d1e2"  # Phase 52f+52g


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


def _columns(db_url: str, table: str) -> set[str]:
    engine = sa.create_engine(db_url)
    try:
        return {c["name"] for c in sa.inspect(engine).get_columns(table)}
    finally:
        engine.dispose()


def _build_pre(db_url: str) -> None:
    _create_all_subprocess(db_url)
    _run_alembic(db_url, "stamp", "head")
    _run_alembic(db_url, "downgrade", _PRIOR)


def test_upgrade_adds_locality_hash_column():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre(db_url)
        assert "verification_locality_hash" not in _columns(db_url, "users")
        _run_alembic(db_url, "upgrade", "head")
        assert "verification_locality_hash" in _columns(db_url, "users")
    finally:
        try: os.unlink(path)
        except OSError: pass


def test_downgrade_upgrade_cycle():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre(db_url)
        _run_alembic(db_url, "upgrade", "head")
        assert "verification_locality_hash" in _columns(db_url, "users")
        _run_alembic(db_url, "downgrade", _PRIOR)
        assert "verification_locality_hash" not in _columns(db_url, "users")
        _run_alembic(db_url, "upgrade", "head")
        assert "verification_locality_hash" in _columns(db_url, "users")
    finally:
        try: os.unlink(path)
        except OSError: pass
