"""Phase 65 — topics.allow_delegation migration cycle test.

Subprocess upgrade → downgrade → upgrade on SQLite proving the
``e7a9c4d2b8f1`` migration is reversible, plus the explicit parity
assertion that PRE-EXISTING topic rows read ``allow_delegation=True``
after upgrade (via server_default — no data backfill step).

Pattern mirrors test_phase_52j_migration_cycle.py.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import sqlalchemy as sa


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_REV = "e7a9c4d2b8f1"
_PRIOR = "d1e2f3a4b5c6"  # Phase 52j


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


def _build_pre(db_url: str) -> None:
    """Build schema + stamp + downgrade to the migration prior (this
    exercises downgrade() once, dropping the new column)."""
    _create_all_subprocess(db_url)
    _run_alembic(db_url, "stamp", "head")
    _run_alembic(db_url, "downgrade", _PRIOR)


def _topics_columns(db_url: str) -> set[str]:
    engine = sa.create_engine(db_url)
    try:
        insp = sa.inspect(engine)
        return {c["name"] for c in insp.get_columns("topics")}
    finally:
        engine.dispose()


def _seed_pre_existing_topic(db_url: str, *, topic_id: str, name: str) -> None:
    """Insert a topic row at the pre-65 schema (no allow_delegation)."""
    engine = sa.create_engine(db_url)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text(
                "INSERT INTO topics (id, name, color) "
                "VALUES (:id, :name, '#000000')"
            ), {"id": topic_id, "name": name})
    finally:
        engine.dispose()


def _read_allow_delegation(db_url: str, topic_id: str):
    engine = sa.create_engine(db_url)
    try:
        with engine.begin() as conn:
            row = conn.execute(
                sa.text("SELECT allow_delegation FROM topics WHERE id=:i"),
                {"i": topic_id},
            ).first()
            assert row is not None
            return row[0]
    finally:
        engine.dispose()


def test_phase_65_migration_cycle():
    """upgrade → downgrade → upgrade, with the existing-rows parity
    assertion (pre-existing topic reads allow_delegation=True after
    upgrade via server_default)."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre(db_url)
        assert "allow_delegation" not in _topics_columns(db_url), (
            "downgrade to prior did not drop allow_delegation"
        )

        # A topic created BEFORE the Phase 65 migration ran.
        _seed_pre_existing_topic(db_url, topic_id="t-old", name="Pre65")

        # Upgrade — column added; existing row backfilled true at the
        # SQL layer (server_default), no data backfill step.
        _run_alembic(db_url, "upgrade", _REV)
        assert "allow_delegation" in _topics_columns(db_url)
        val = _read_allow_delegation(db_url, "t-old")
        assert val in (1, True), (
            f"pre-existing topic should default allow_delegation=true, "
            f"got {val!r}"
        )

        # Downgrade — column dropped, row survives.
        _run_alembic(db_url, "downgrade", _PRIOR)
        assert "allow_delegation" not in _topics_columns(db_url)
        engine = sa.create_engine(db_url)
        try:
            with engine.begin() as conn:
                n = conn.execute(
                    sa.text("SELECT COUNT(*) FROM topics"),
                ).scalar()
                assert n == 1
        finally:
            engine.dispose()

        # Second upgrade — idempotent re-add, same default behavior.
        _run_alembic(db_url, "upgrade", _REV)
        assert "allow_delegation" in _topics_columns(db_url)
        assert _read_allow_delegation(db_url, "t-old") in (1, True)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
