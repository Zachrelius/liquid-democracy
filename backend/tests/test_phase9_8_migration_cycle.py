"""Phase 9.8 migration: verify upgrade -> downgrade -> upgrade on SQLite.

Mirrors the Phase 9.5 cycle test (`test_phase9_5_migration_cycle.py`):
runs alembic via subprocess so each invocation gets a fresh DATABASE_URL,
asserts the column shows up, asserts it's gone after downgrade, asserts
re-upgrade is idempotent.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import pytest
import sqlalchemy as sa


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


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


def _column_exists(engine, table: str, column: str) -> bool:
    insp = sa.inspect(engine)
    if table not in insp.get_table_names():
        return False
    return column in {c["name"] for c in insp.get_columns(table)}


def test_upgrade_downgrade_upgrade_cycle():
    """Migration is reversible and idempotent on SQLite."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"

    try:
        # Build the prior schema (post-Phase-9.5) via create_all then stamp.
        # We then drop the avatar_url column so the upgrade can exercise the
        # add path; create_all leaves it present because models.py declares it.
        _create_all_subprocess(db_url)
        engine = sa.create_engine(db_url)
        # SQLite: reconstruct users table without avatar_url so we can verify
        # the upgrade ADDs the column (otherwise create_all already put it
        # there and the upgrade is just an introspect-skip).
        with engine.begin() as conn:
            cols = sa.inspect(conn).get_columns("users")
            keep_cols = [c for c in cols if c["name"] != "avatar_url"]
            if any(c["name"] == "avatar_url" for c in cols):
                # Build a SELECT of remaining columns into a temp table, drop
                # the original, recreate without avatar_url, copy back.
                col_names = ", ".join(c["name"] for c in keep_cols)
                conn.execute(sa.text(f"CREATE TABLE users_tmp AS SELECT {col_names} FROM users"))
                conn.execute(sa.text("DROP TABLE users"))
                conn.execute(sa.text(f"ALTER TABLE users_tmp RENAME TO users"))
        engine.dispose()
        _run_alembic(db_url, "stamp", "373e1f066cc1")

        # 1. Upgrade to the Phase 9.8 head -> avatar_url present.
        # Pin to the specific revision (rather than `head`) so this test
        # stays focused on the Phase 9.8 cycle even as later migrations
        # land on top (Phase 10 added b2d5f1a3c7e4 above this revision).
        _run_alembic(db_url, "upgrade", "a1c4e9d2f8b3")
        engine = sa.create_engine(db_url)
        assert _column_exists(engine, "users", "avatar_url")
        engine.dispose()

        # 2. Downgrade -1 from this revision -> avatar_url gone
        _run_alembic(db_url, "downgrade", "-1")
        engine = sa.create_engine(db_url)
        assert not _column_exists(engine, "users", "avatar_url")
        engine.dispose()

        # 3. Re-upgrade to this revision -> idempotent re-application
        _run_alembic(db_url, "upgrade", "a1c4e9d2f8b3")
        engine = sa.create_engine(db_url)
        assert _column_exists(engine, "users", "avatar_url")
        engine.dispose()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
