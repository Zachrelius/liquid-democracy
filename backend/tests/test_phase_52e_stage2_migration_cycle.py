"""Phase 52e Stage 2 migration cycle test."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import sqlalchemy as sa


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PHASE_52E_S2_REVISION = "c4d5e6f7a8b9"
_PRIOR_REVISION = "b3c4d5e6f7a8"  # Phase 56 head


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


def _build_pre(db_url: str) -> None:
    _create_all_subprocess(db_url)
    _run_alembic(db_url, "stamp", "head")
    _run_alembic(db_url, "downgrade", _PRIOR_REVISION)


def test_phase_52e_stage2_upgrade_adds_flag_table():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre(db_url)
        assert "org_duplicate_flags" not in _tables(db_url)
        _run_alembic(db_url, "upgrade", "head")
        assert "org_duplicate_flags" in _tables(db_url)
    finally:
        try: os.unlink(path)
        except OSError: pass


def test_phase_52e_stage2_downgrade_upgrade_cycle():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre(db_url)
        _run_alembic(db_url, "upgrade", "head")
        assert "org_duplicate_flags" in _tables(db_url)
        _run_alembic(db_url, "downgrade", _PRIOR_REVISION)
        assert "org_duplicate_flags" not in _tables(db_url)
        _run_alembic(db_url, "upgrade", "head")
        assert "org_duplicate_flags" in _tables(db_url)
    finally:
        try: os.unlink(path)
        except OSError: pass
