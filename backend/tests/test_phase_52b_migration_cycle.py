"""Phase 52b migration cycle test."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import sqlalchemy as sa


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PHASE_52B_REVISION = "a2b3c4d5e6f7"
_PRIOR_REVISION = "f1a2b3c4d5e6"  # Phase 52d head


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


def _columns(db_url: str, table: str) -> set[str]:
    engine = sa.create_engine(db_url)
    try:
        return {c["name"] for c in sa.inspect(engine).get_columns(table)}
    finally:
        engine.dispose()


def _build_pre_52b(db_url: str) -> None:
    _create_all_subprocess(db_url)
    _run_alembic(db_url, "stamp", "head")
    _run_alembic(db_url, "downgrade", _PRIOR_REVISION)


def test_phase_52b_upgrade_adds_consumption_table_and_triggering_org_id():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_52b(db_url)
        pre_tables = _tables(db_url)
        pre_sess_cols = _columns(db_url, "verification_sessions")
        assert "verification_consumption" not in pre_tables
        assert "triggering_org_id" not in pre_sess_cols

        _run_alembic(db_url, "upgrade", "head")
        post_tables = _tables(db_url)
        post_sess_cols = _columns(db_url, "verification_sessions")
        assert "verification_consumption" in post_tables
        assert "triggering_org_id" in post_sess_cols

        cc = _columns(db_url, "verification_consumption")
        for col in ("id", "year_month", "org_id", "user_id",
                    "provider_session_id", "provenance", "created_at"):
            assert col in cc
    finally:
        try: os.unlink(path)
        except OSError: pass


def test_phase_52b_downgrade_upgrade_cycle():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_52b(db_url)
        _run_alembic(db_url, "upgrade", "head")
        assert "verification_consumption" in _tables(db_url)
        _run_alembic(db_url, "downgrade", _PRIOR_REVISION)
        assert "verification_consumption" not in _tables(db_url)
        assert "triggering_org_id" not in _columns(
            db_url, "verification_sessions",
        )
        _run_alembic(db_url, "upgrade", "head")
        assert "verification_consumption" in _tables(db_url)
        assert "triggering_org_id" in _columns(
            db_url, "verification_sessions",
        )
    finally:
        try: os.unlink(path)
        except OSError: pass
