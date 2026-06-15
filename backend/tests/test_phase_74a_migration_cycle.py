"""Phase 74a migration: drop proposal_options.budget_is_mandatory.

upgrade -> column gone; downgrade -> column re-added; re-upgrade -> gone again.
Mirrors the other budget migration-cycle tests (subprocess + create_tables +
stamp prior). NB: create_tables builds today's schema, which NO LONGER has
budget_is_mandatory (the model dropped it), so we add the column back before
stamping so the upgrade's drop has something to remove (simulating a prod DB
still carrying the core-migration column).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import sqlalchemy as sa

_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PHASE_74A_REVISION = "a5b6c7d8e9f0"
_PRIOR_REVISION = "f4a5b6c7d8e9"


def _run_alembic(db_url: str, *args: str) -> None:
    env = dict(os.environ)
    env["DATABASE_URL"] = db_url
    res = subprocess.run([sys.executable, "-m", "alembic", *args],
                         cwd=_BACKEND_DIR, env=env, capture_output=True, text=True)
    assert res.returncode == 0, (
        f"alembic {' '.join(args)} failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    )


def _create_all_subprocess(db_url: str) -> None:
    code = (f"import os; os.environ['DATABASE_URL']={db_url!r}; "
            "from database import create_tables; create_tables()")
    res = subprocess.run([sys.executable, "-c", code], cwd=_BACKEND_DIR,
                         capture_output=True, text=True)
    assert res.returncode == 0, (
        f"create_tables failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    )


def _cols(db_url: str) -> set[str]:
    engine = sa.create_engine(db_url)
    try:
        return {c["name"] for c in sa.inspect(engine).get_columns("proposal_options")}
    finally:
        engine.dispose()


def _add_mandatory(db_url: str) -> None:
    engine = sa.create_engine(db_url)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text(
                "ALTER TABLE proposal_options ADD COLUMN budget_is_mandatory BOOLEAN"
            ))
    finally:
        engine.dispose()


def test_phase74a_drop_column_cycle():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _create_all_subprocess(db_url)
        # Simulate a prod DB that still carries the core-migration column.
        _add_mandatory(db_url)
        assert "budget_is_mandatory" in _cols(db_url)
        _run_alembic(db_url, "stamp", _PRIOR_REVISION)

        _run_alembic(db_url, "upgrade", _PHASE_74A_REVISION)
        assert "budget_is_mandatory" not in _cols(db_url)

        _run_alembic(db_url, "downgrade", _PRIOR_REVISION)
        assert "budget_is_mandatory" in _cols(db_url)

        _run_alembic(db_url, "upgrade", _PHASE_74A_REVISION)
        assert "budget_is_mandatory" not in _cols(db_url)
        # The live cost columns are untouched by the drop.
        assert {"budget_floor_amount", "budget_kind", "budget_tier_parent_id",
                "tier_allow_fallback", "budget_max_amount"} <= _cols(db_url)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
