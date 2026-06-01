"""Phase 48 Stage 1 migration cycle test."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import sqlalchemy as sa


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PHASE_48_S1_REVISION = "g5a8b1c93412"
_PRIOR_REVISION = "f4d8a9c52312"  # Phase 47 hotfix #1


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


def _build_pre_48_s1_via_downgrade(db_url: str) -> None:
    """Build the pre-Phase-48-Stage-1 schema state by running the full
    create_tables (which includes the Stage 1 columns), then alembic
    upgrade head + downgrade to the prior revision. SQLite's
    ALTER TABLE DROP COLUMN doesn't tolerate dropping FK-bearing
    columns directly, but the migration's own downgrade() handles the
    rebuild correctly. Net: this is the test analogue of a freshly-
    deployed pre-48 prod DB."""
    _create_all_subprocess(db_url)
    _run_alembic(db_url, "stamp", "head")
    _run_alembic(db_url, "downgrade", _PRIOR_REVISION)


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


def _build_pre_48_s1(db_url: str) -> None:
    _build_pre_48_s1_via_downgrade(db_url)


def test_phase_48_s1_upgrade_adds_schema():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_48_s1(db_url)
        assert "election_candidacies" not in _tables(db_url)
        assert "is_election" not in _columns(db_url, "proposals")

        _run_alembic(db_url, "upgrade", "head")
        assert "election_candidacies" in _tables(db_url)
        cols = _columns(db_url, "proposals")
        assert "is_election" in cols
        assert "election_title_id" in cols
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase_48_s1_upgrade_downgrade_upgrade_cycle():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_48_s1(db_url)

        _run_alembic(db_url, "upgrade", "head")
        assert "election_candidacies" in _tables(db_url)

        _run_alembic(db_url, "downgrade", _PRIOR_REVISION)
        assert "election_candidacies" not in _tables(db_url)
        assert "is_election" not in _columns(db_url, "proposals")

        _run_alembic(db_url, "upgrade", "head")
        assert "election_candidacies" in _tables(db_url)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
