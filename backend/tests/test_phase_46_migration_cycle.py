"""Phase 46 migration cycle test — upgrade → downgrade → upgrade.

Verifies:
  1. Pre-Phase-46 schema lacks the new columns + table.
  2. Upgrade adds them all.
  3. Downgrade removes them cleanly.
  4. Upgrade re-applies idempotently.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import sqlalchemy as sa


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PHASE_46_REVISION = "e8b4d6f31a92"
_PRIOR_REVISION = "d5e9f8a23bc4"


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


def _drop_phase_46(db_url: str) -> None:
    """Drop the table + columns added by Phase 46 to simulate the
    pre-46 schema state. SQLite needs index-dropping before column drop.
    """
    engine = sa.create_engine(db_url)
    try:
        with engine.begin() as conn:
            insp = sa.inspect(conn)
            if "proposal_cosignatures" in insp.get_table_names():
                conn.execute(sa.text("DROP TABLE IF EXISTS proposal_cosignatures"))
            proposal_cols = {c["name"] for c in insp.get_columns("proposals")}
            if "cosign_expires_at" in proposal_cols:
                # Drop any dependent indexes first.
                for idx in insp.get_indexes("proposals"):
                    if "cosign_expires_at" in (idx.get("column_names") or []):
                        conn.execute(sa.text(
                            f"DROP INDEX IF EXISTS {idx['name']}"
                        ))
                conn.execute(sa.text(
                    "ALTER TABLE proposals DROP COLUMN cosign_expires_at"
                ))
            if "cosign_threshold_snapshot" in proposal_cols:
                conn.execute(sa.text(
                    "ALTER TABLE proposals DROP COLUMN cosign_threshold_snapshot"
                ))
            if "is_cosign_gated" in proposal_cols:
                conn.execute(sa.text(
                    "ALTER TABLE proposals DROP COLUMN is_cosign_gated"
                ))
            org_cols = {c["name"] for c in insp.get_columns("organizations")}
            if "proposal_creation_mode" in org_cols:
                for idx in insp.get_indexes("organizations"):
                    if "proposal_creation_mode" in (idx.get("column_names") or []):
                        conn.execute(sa.text(
                            f"DROP INDEX IF EXISTS {idx['name']}"
                        ))
                conn.execute(sa.text(
                    "ALTER TABLE organizations DROP COLUMN proposal_creation_mode"
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


def _tables(db_url: str) -> set[str]:
    engine = sa.create_engine(db_url)
    try:
        insp = sa.inspect(engine)
        return set(insp.get_table_names())
    finally:
        engine.dispose()


def _build_pre_46_schema(db_url: str) -> None:
    _create_all_subprocess(db_url)
    _drop_phase_46(db_url)
    _run_alembic(db_url, "stamp", _PRIOR_REVISION)


def test_phase_46_upgrade_adds_everything():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_46_schema(db_url)
        assert "proposal_cosignatures" not in _tables(db_url)
        assert "proposal_creation_mode" not in _columns(db_url, "organizations")
        assert "is_cosign_gated" not in _columns(db_url, "proposals")

        _run_alembic(db_url, "upgrade", "head")
        assert "proposal_cosignatures" in _tables(db_url)
        assert "proposal_creation_mode" in _columns(db_url, "organizations")
        for c in ("is_cosign_gated", "cosign_threshold_snapshot", "cosign_expires_at"):
            assert c in _columns(db_url, "proposals"), f"missing column: {c}"
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase_46_upgrade_downgrade_upgrade_cycle():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_46_schema(db_url)

        _run_alembic(db_url, "upgrade", "head")
        assert "proposal_cosignatures" in _tables(db_url)

        _run_alembic(db_url, "downgrade", _PRIOR_REVISION)
        assert "proposal_cosignatures" not in _tables(db_url)
        assert "proposal_creation_mode" not in _columns(db_url, "organizations")
        assert "is_cosign_gated" not in _columns(db_url, "proposals")

        _run_alembic(db_url, "upgrade", "head")
        assert "proposal_cosignatures" in _tables(db_url)
        assert "proposal_creation_mode" in _columns(db_url, "organizations")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase_46_org_default_value_is_open():
    """Newly-created org rows pick up the server_default 'open' so the
    migration is safe against live data."""
    import uuid

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_46_schema(db_url)
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
                ), {"id": oid, "slug": "p46-" + oid[:8]})
                row = conn.execute(sa.text(
                    "SELECT proposal_creation_mode FROM organizations "
                    "WHERE id = :id"
                ), {"id": oid}).fetchone()
                assert row[0] == "open"
        finally:
            engine.dispose()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
