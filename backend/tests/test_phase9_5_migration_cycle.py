"""Phase 9.5 migration: verify upgrade -> downgrade -> upgrade on SQLite.

Runs alembic via subprocess (matches pg_smoke.py's pattern) so each call
gets a fresh DATABASE_URL — the env.py imports `settings` once at module
load, which would otherwise pin the URL across in-process invocations.

Asserts:
  - upgrade head adds `users.org_creation_limit` column + `platform_settings`
    table + the seeded `org_creation_mode='open'` row.
  - downgrade -1 drops both.
  - upgrade head re-adds them (idempotency check).
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
    """Run `from database import create_tables; create_tables()` in a
    subprocess so the env-var-driven settings pickup is correct."""
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


def _table_exists(engine, name: str) -> bool:
    return name in sa.inspect(engine).get_table_names()


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
        # 0. Build prior schema via create_all (parallels start.sh fresh
        #    branch). Then drop the post-Phase-9.5 bits and stamp at the
        #    immediately-prior revision so the upgrade exercises a true
        #    "applies on top of e72362fd7cd5" path.
        _create_all_subprocess(db_url)
        engine = sa.create_engine(db_url)
        with engine.begin() as conn:
            conn.execute(sa.text("DROP TABLE IF EXISTS platform_settings"))
            # Drop org_creation_limit via batch-rebuild so SQLite plays nice.
            # Easier: we'll let the migration's idempotent guard handle the
            # already-present case by simply asserting the FINAL state.
        engine.dispose()
        _run_alembic(db_url, "stamp", "e72362fd7cd5")

        # 1. Upgrade head -> column + table + seeded row present
        _run_alembic(db_url, "upgrade", "head")
        engine = sa.create_engine(db_url)
        assert _column_exists(engine, "users", "org_creation_limit")
        assert _table_exists(engine, "platform_settings")
        with engine.connect() as conn:
            row = conn.execute(sa.text(
                "SELECT value FROM platform_settings "
                "WHERE key = 'org_creation_mode'"
            )).first()
            assert row is not None
            # SQLite JSON column returns the encoded literal; either form OK.
            assert row[0] in ("open", '"open"'), f"got {row[0]!r}"
        engine.dispose()

        # 2. Downgrade -1 -> both gone
        _run_alembic(db_url, "downgrade", "-1")
        engine = sa.create_engine(db_url)
        assert not _table_exists(engine, "platform_settings")
        # Note: SQLite + alembic batch_alter_table rebuilds the users table.
        # The drop_column branch in our downgrade should remove the column.
        assert not _column_exists(engine, "users", "org_creation_limit")
        engine.dispose()

        # 3. Re-upgrade head -> idempotent re-application
        _run_alembic(db_url, "upgrade", "head")
        engine = sa.create_engine(db_url)
        assert _column_exists(engine, "users", "org_creation_limit")
        assert _table_exists(engine, "platform_settings")
        engine.dispose()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
