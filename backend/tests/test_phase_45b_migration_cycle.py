"""Phase 45b migration cycle test — upgrade → downgrade → upgrade.

Adds the ``governance_mode`` column to ``organizations``. Verifies:
  1. Pre-Phase-45b schema lacks the column.
  2. ``upgrade head`` adds it with the expected default + index.
  3. ``downgrade <prior>`` drops it cleanly.
  4. ``upgrade head`` re-adds it (idempotent guard works).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import sqlalchemy as sa


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PHASE_45B_REVISION = "d5e9f8a23bc4"
_PRIOR_REVISION = "c1a4d8b7e2f1"


def _run_alembic(db_url: str, *args: str) -> None:
    env = dict(os.environ)
    env["DATABASE_URL"] = db_url
    res = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=_BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
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
        cwd=_BACKEND_DIR,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, (
        f"create_tables failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    )


def _drop_governance_mode(db_url: str) -> None:
    """Drop the column added by Phase 45b so we can simulate the pre-45b
    schema state. SQLite refuses to drop a column that has a dependent
    index, so drop the index first.
    """
    engine = sa.create_engine(db_url)
    try:
        with engine.begin() as conn:
            insp = sa.inspect(conn)
            cols = insp.get_columns("organizations")
            if any(c["name"] == "governance_mode" for c in cols):
                idxs = insp.get_indexes("organizations")
                for idx in idxs:
                    if "governance_mode" in (idx.get("column_names") or []):
                        conn.execute(sa.text(
                            f"DROP INDEX IF EXISTS {idx['name']}"
                        ))
                conn.execute(sa.text(
                    "ALTER TABLE organizations DROP COLUMN governance_mode"
                ))
    finally:
        engine.dispose()


def _columns(db_url: str, table: str) -> set[str]:
    engine = sa.create_engine(db_url)
    try:
        insp = sa.inspect(engine)
        return {c["name"] for c in insp.get_columns(table)}
    finally:
        engine.dispose()


def _build_pre_phase_45b_schema(db_url: str) -> None:
    _create_all_subprocess(db_url)
    _drop_governance_mode(db_url)
    _run_alembic(db_url, "stamp", _PRIOR_REVISION)


def test_phase_45b_upgrade_adds_column():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_phase_45b_schema(db_url)
        assert "governance_mode" not in _columns(db_url, "organizations")

        _run_alembic(db_url, "upgrade", "head")
        assert "governance_mode" in _columns(db_url, "organizations")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase_45b_upgrade_downgrade_upgrade_cycle():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_phase_45b_schema(db_url)

        _run_alembic(db_url, "upgrade", "head")
        assert "governance_mode" in _columns(db_url, "organizations")

        _run_alembic(db_url, "downgrade", _PRIOR_REVISION)
        assert "governance_mode" not in _columns(db_url, "organizations")

        _run_alembic(db_url, "upgrade", "head")
        assert "governance_mode" in _columns(db_url, "organizations")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase_45b_default_value_is_single_steward():
    """After migration, an INSERT that omits governance_mode produces a
    row whose governance_mode == 'single_steward' — the server_default
    that makes the migration safe for live data."""
    import uuid

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_phase_45b_schema(db_url)
        _run_alembic(db_url, "upgrade", "head")

        engine = sa.create_engine(db_url)
        try:
            with engine.begin() as conn:
                oid = str(uuid.uuid4())
                conn.execute(sa.text(
                    "INSERT INTO organizations "
                    "(id, name, slug, description, join_policy, is_demo, "
                    " is_demo_resetting, created_at, updated_at) "
                    "VALUES (:id, 'X', :slug, '', 'open', 0, 0, "
                    " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ), {"id": oid, "slug": "test-" + oid[:8]})
                row = conn.execute(sa.text(
                    "SELECT governance_mode FROM organizations WHERE id = :id"
                ), {"id": oid}).fetchone()
                assert row[0] == "single_steward"
        finally:
            engine.dispose()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
