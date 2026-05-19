"""Phase 32 migration cycle: ``ProposalRevision`` table + override columns
on ``proposals`` + write-in attribution columns on ``proposal_options``.

Pattern mirrors Phase 20's migration-cycle test: subprocess-invoke
alembic so each call gets a fresh process + clean SQLite connection
(batch_alter_table requires its own transaction handling).

Approach: bootstrap full schema via ``create_tables()``, stamp at the
Phase 32 head (since models.py reflects post-Phase-32 state), then
exercise the down → up cycle. The migration's own downgrade is what
rolls Phase 32 back; this is the canonical round-trip test.

The load-bearing assertions:

1. After ``create_tables()`` + stamp at Phase 32: new table + columns
   exist (sanity check on the schema-vs-migration alignment).
2. Post-downgrade to Phase 30.3: table dropped, columns dropped.
3. Re-upgrade is idempotent (same end state as #1).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import sqlalchemy as sa


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PHASE_32_REVISION = "d4f8e2a91c50"
_PRIOR_REVISION = "c7d4e0a91f23"  # Phase 30.3

_PROPOSAL_NEW_COLS = [
    "allow_write_in_options",
    "allow_write_ins_during_voting",
    "max_write_ins",
    "allow_pre_voting",
    "show_votes_during_deliberation",
    "edit_lockout_fraction",
]
_OPTION_NEW_COLS = ["added_by_user_id", "added_at", "is_write_in"]


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
    """Build the full schema via ``create_tables()`` and stamp at Phase 32 head.

    Bypasses the alembic-from-base path (older migrations have ordering
    issues on SQLite). Since ``models.py`` is at Phase 32 HEAD, this
    creates the right schema; alembic just needs to know where we are.
    """
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
    _run_alembic(db_url, "stamp", _PHASE_32_REVISION)


def _has_column(engine, table: str, column: str) -> bool:
    insp = sa.inspect(engine)
    if table not in set(insp.get_table_names()):
        return False
    return column in {c["name"] for c in insp.get_columns(table)}


def _has_table(engine, table: str) -> bool:
    return table in set(sa.inspect(engine).get_table_names())


def test_phase32_schema_matches_head():
    """``create_tables()`` produces the Phase 32 columns + table."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _bootstrap_at_head(db_url)
        engine = sa.create_engine(db_url)
        try:
            assert _has_table(engine, "proposal_revisions")
            for col in _PROPOSAL_NEW_COLS:
                assert _has_column(engine, "proposals", col), (
                    f"proposals.{col} missing from create_tables() output"
                )
            for col in _OPTION_NEW_COLS:
                assert _has_column(engine, "proposal_options", col), (
                    f"proposal_options.{col} missing from create_tables()"
                )
        finally:
            engine.dispose()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase32_downgrade_upgrade_cycle():
    """Downgrade to Phase 30.3 drops the added columns + table; re-upgrade
    restores them. Exercises the migration's down → up symmetry."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        # 1. Start at Phase 32 head (post-create_tables + stamp).
        _bootstrap_at_head(db_url)

        # 2. Downgrade Phase 32 → Phase 30.3.
        _run_alembic(db_url, "downgrade", _PRIOR_REVISION)
        engine = sa.create_engine(db_url)
        try:
            assert not _has_table(engine, "proposal_revisions"), (
                "proposal_revisions table still present after downgrade"
            )
            for col in _PROPOSAL_NEW_COLS:
                assert not _has_column(engine, "proposals", col), (
                    f"proposals.{col} still present after downgrade"
                )
            for col in _OPTION_NEW_COLS:
                assert not _has_column(engine, "proposal_options", col), (
                    f"proposal_options.{col} still present after downgrade"
                )
        finally:
            engine.dispose()

        # 3. Re-upgrade is idempotent.
        _run_alembic(db_url, "upgrade", _PHASE_32_REVISION)
        engine = sa.create_engine(db_url)
        try:
            assert _has_table(engine, "proposal_revisions")
            for col in _PROPOSAL_NEW_COLS:
                assert _has_column(engine, "proposals", col)
            for col in _OPTION_NEW_COLS:
                assert _has_column(engine, "proposal_options", col)
        finally:
            engine.dispose()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
