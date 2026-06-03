"""Phase 52 Stage 1 migration cycle test."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import sqlalchemy as sa


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PHASE_52_REVISION = "d9e4f2a78543"
_PRIOR_REVISION = "c8d3e1f56432"  # Phase 51 verification state model


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


def _columns(db_url: str, table: str) -> set[str]:
    engine = sa.create_engine(db_url)
    try:
        return {c["name"] for c in sa.inspect(engine).get_columns(table)}
    finally:
        engine.dispose()


def _build_pre_52(db_url: str) -> None:
    _create_all_subprocess(db_url)
    _run_alembic(db_url, "stamp", "head")
    _run_alembic(db_url, "downgrade", _PRIOR_REVISION)


def test_phase_52_upgrade_adds_proposal_columns():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_52(db_url)
        pre = _columns(db_url, "proposals")
        assert "verification_floor" not in pre
        assert "verification_jurisdiction" not in pre
        _run_alembic(db_url, "upgrade", "head")
        post = _columns(db_url, "proposals")
        assert "verification_floor" in post
        assert "verification_jurisdiction" in post
    finally:
        try: os.unlink(path)
        except OSError: pass


def test_phase_52_upgrade_downgrade_upgrade_cycle():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_52(db_url)
        _run_alembic(db_url, "upgrade", "head")
        assert "verification_floor" in _columns(db_url, "proposals")
        _run_alembic(db_url, "downgrade", _PRIOR_REVISION)
        post_down = _columns(db_url, "proposals")
        assert "verification_floor" not in post_down
        assert "verification_jurisdiction" not in post_down
        _run_alembic(db_url, "upgrade", "head")
        assert "verification_floor" in _columns(db_url, "proposals")
    finally:
        try: os.unlink(path)
        except OSError: pass
