"""Phase 47 migration cycle test — upgrade → downgrade → upgrade.

Verifies:
  1. Pre-Phase-47 schema lacks the new tables.
  2. Upgrade adds them both + backfills system titles per org.
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
_PHASE_47_REVISION = "f3c7e9b48201"
_PRIOR_REVISION = "e8b4d6f31a92"


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


def _drop_phase_47(db_url: str) -> None:
    engine = sa.create_engine(db_url)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text("DROP TABLE IF EXISTS org_title_assignments"))
            conn.execute(sa.text("DROP TABLE IF EXISTS org_titles"))
    finally:
        engine.dispose()


def _tables(db_url: str) -> set[str]:
    engine = sa.create_engine(db_url)
    try:
        insp = sa.inspect(engine)
        return set(insp.get_table_names())
    finally:
        engine.dispose()


def _build_pre_47_schema(db_url: str) -> None:
    _create_all_subprocess(db_url)
    _drop_phase_47(db_url)
    _run_alembic(db_url, "stamp", _PRIOR_REVISION)


def test_phase_47_upgrade_adds_tables():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_47_schema(db_url)
        assert "org_titles" not in _tables(db_url)
        assert "org_title_assignments" not in _tables(db_url)

        _run_alembic(db_url, "upgrade", "head")
        names = _tables(db_url)
        assert "org_titles" in names
        assert "org_title_assignments" in names
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase_47_upgrade_downgrade_upgrade_cycle():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_47_schema(db_url)

        _run_alembic(db_url, "upgrade", "head")
        assert "org_titles" in _tables(db_url)
        assert "org_title_assignments" in _tables(db_url)

        _run_alembic(db_url, "downgrade", _PRIOR_REVISION)
        assert "org_titles" not in _tables(db_url)
        assert "org_title_assignments" not in _tables(db_url)

        _run_alembic(db_url, "upgrade", "head")
        assert "org_titles" in _tables(db_url)
        assert "org_title_assignments" in _tables(db_url)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase_47_backfills_system_titles_for_existing_orgs():
    """Existing org rows at upgrade time get the two system titles
    seeded (Steward + Admin). Idempotent across re-run."""
    import uuid

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_47_schema(db_url)

        # Insert an org BEFORE upgrade to simulate an existing org.
        engine = sa.create_engine(db_url)
        try:
            with engine.begin() as conn:
                oid = str(uuid.uuid4())
                conn.execute(sa.text(
                    "INSERT INTO organizations "
                    "(id, name, slug, description, join_policy, is_demo, "
                    " is_demo_resetting, created_at, updated_at) "
                    "VALUES (:id, 'OldOrg', :slug, '', 'open', 0, 0, "
                    " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ), {"id": oid, "slug": "old-" + oid[:8]})
        finally:
            engine.dispose()

        _run_alembic(db_url, "upgrade", "head")

        engine = sa.create_engine(db_url)
        try:
            rows = engine.connect().execute(sa.text(
                "SELECT name, bound_role, is_system FROM org_titles "
                "WHERE org_id = :oid ORDER BY display_order"
            ), {"oid": oid}).fetchall()
            assert len(rows) == 2
            names = {r[0] for r in rows}
            assert names == {"Steward", "Admin"}
            bound = {r[0]: r[1] for r in rows}
            assert bound["Steward"] == "steward"
            assert bound["Admin"] == "admin"
            # All system.
            assert all(r[2] in (1, True) for r in rows)
        finally:
            engine.dispose()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
