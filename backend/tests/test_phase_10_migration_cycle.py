"""Phase 10 migration: verify upgrade -> downgrade -> upgrade on SQLite.

Mirrors the Phase 9.8 cycle test (`test_phase9_8_migration_cycle.py`):
runs alembic via subprocess so each invocation gets a fresh DATABASE_URL,
asserts the table shows up, asserts it's gone after downgrade, asserts
re-upgrade is idempotent.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

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


def _table_exists(engine, table: str) -> bool:
    insp = sa.inspect(engine)
    return table in set(insp.get_table_names())


def test_upgrade_downgrade_upgrade_cycle():
    """Migration is reversible and idempotent on SQLite."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"

    try:
        # Build the prior schema (post-Phase-9.8) via create_all then stamp at
        # the prior revision. We then drop the comments table so the upgrade
        # exercises the create path; create_all leaves it present because
        # models.py declares it.
        _create_all_subprocess(db_url)
        engine = sa.create_engine(db_url)
        with engine.begin() as conn:
            if 'comments' in set(sa.inspect(conn).get_table_names()):
                conn.execute(sa.text("DROP TABLE comments"))
        engine.dispose()
        _run_alembic(db_url, "stamp", "a1c4e9d2f8b3")

        # 1. Upgrade head -> comments table present
        _run_alembic(db_url, "upgrade", "head")
        engine = sa.create_engine(db_url)
        assert _table_exists(engine, "comments")
        # Sanity-check columns are what we expect.
        cols = {c["name"] for c in sa.inspect(engine).get_columns("comments")}
        assert {
            "id", "proposal_id", "author_id", "parent_comment_id", "body",
            "created_at", "updated_at", "deleted_at",
        } <= cols
        engine.dispose()

        # 2. Downgrade -1 -> comments table gone
        _run_alembic(db_url, "downgrade", "-1")
        engine = sa.create_engine(db_url)
        assert not _table_exists(engine, "comments")
        engine.dispose()

        # 3. Re-upgrade head -> idempotent re-application
        _run_alembic(db_url, "upgrade", "head")
        engine = sa.create_engine(db_url)
        assert _table_exists(engine, "comments")
        engine.dispose()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
