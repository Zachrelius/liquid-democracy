"""Phase 102 migration upgrade -> downgrade -> upgrade on SQLite."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile

import sqlalchemy as sa


BACKEND = Path(__file__).resolve().parents[1]
PRIOR = "d6e7f8a9b0c1"
REVISION = "e7f8a9b0c1d2"


def _alembic(url: str, *args: str) -> None:
    env = {**os.environ, "DATABASE_URL": url}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=BACKEND,
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _shape(url: str):
    engine = sa.create_engine(url)
    try:
        inspector = sa.inspect(engine)
        columns = {row["name"] for row in inspector.get_columns("proposals")}
        indexes = {row["name"] for row in inspector.get_indexes("proposals")}
        return columns, indexes
    finally:
        engine.dispose()


def test_phase102_migration_cycle():
    handle, path = tempfile.mkstemp(suffix=".db")
    os.close(handle)
    url = f"sqlite:///{path}"
    try:
        # Build the current production-shaped schema, remove only the Phase
        # 102 artifact, then stamp the real prior revision. This avoids the
        # repository's pre-Alembic base migrations, which assume core tables
        # already exist.
        env = {**os.environ, "DATABASE_URL": url}
        setup = subprocess.run(
            [sys.executable, "-c", (
                "from database import Base,engine; import models; "
                "from sqlalchemy import text; Base.metadata.create_all(engine); "
                "c=engine.connect(); "
                "c.execute(text('DROP INDEX ix_proposals_deliberation_end')); "
                "c.execute(text('ALTER TABLE proposals DROP COLUMN deliberation_end')); "
                "c.commit(); c.close()"
            )], cwd=BACKEND, env=env, capture_output=True, text=True,
        )
        assert setup.returncode == 0, setup.stdout + setup.stderr
        _alembic(url, "stamp", PRIOR)
        _alembic(url, "upgrade", REVISION)
        columns, indexes = _shape(url)
        assert "deliberation_end" in columns
        assert "ix_proposals_deliberation_end" in indexes
        _alembic(url, "downgrade", PRIOR)
        columns, indexes = _shape(url)
        assert "deliberation_end" not in columns
        assert "ix_proposals_deliberation_end" not in indexes
        _alembic(url, "upgrade", REVISION)
        assert "deliberation_end" in _shape(url)[0]
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
