"""Phase 49 migration cycle test."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import sqlalchemy as sa


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PHASE_49_REVISION = "a7c1d8e94521"
_PRIOR_REVISION = "h6b9c2d04523"  # Phase 48 Stage 2 (slate mode)


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


def _build_pre_49(db_url: str) -> None:
    """Build the pre-Phase-49 schema state: create today's full schema
    via create_tables, stamp head, then downgrade to the Phase 48 Stage 2
    revision so the Phase 49 columns are absent."""
    _create_all_subprocess(db_url)
    _run_alembic(db_url, "stamp", "head")
    _run_alembic(db_url, "downgrade", _PRIOR_REVISION)


def _columns(db_url: str, table: str) -> set[str]:
    engine = sa.create_engine(db_url)
    try:
        return {c["name"] for c in sa.inspect(engine).get_columns(table)}
    finally:
        engine.dispose()


def test_phase_49_upgrade_adds_schema():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_49(db_url)
        title_cols = _columns(db_url, "org_titles")
        assert "term_length_days" not in title_cols
        assert "election_lead_time_days" not in title_cols
        assert "next_election_due_at" not in title_cols
        assert "election_trigger" not in _columns(db_url, "proposals")

        _run_alembic(db_url, "upgrade", "head")
        title_cols = _columns(db_url, "org_titles")
        assert "term_length_days" in title_cols
        assert "election_lead_time_days" in title_cols
        assert "next_election_due_at" in title_cols
        assert "election_trigger" in _columns(db_url, "proposals")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase_49_upgrade_downgrade_upgrade_cycle():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_49(db_url)

        _run_alembic(db_url, "upgrade", "head")
        assert "term_length_days" in _columns(db_url, "org_titles")
        assert "election_trigger" in _columns(db_url, "proposals")

        _run_alembic(db_url, "downgrade", _PRIOR_REVISION)
        assert "term_length_days" not in _columns(db_url, "org_titles")
        assert "election_trigger" not in _columns(db_url, "proposals")

        _run_alembic(db_url, "upgrade", "head")
        assert "term_length_days" in _columns(db_url, "org_titles")
        assert "election_trigger" in _columns(db_url, "proposals")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
