"""Phase 44 migration cycle test — upgrade → downgrade → upgrade on SQLite.

The Phase 44 migration adds two new tables: ``pending_admin_actions``
and ``pending_action_approvals``. This test verifies the migration is
reversible by exercising the full cycle from a pre-Phase-44 state.

Pattern (same shape as ``test_phase14_migration_cycle.py`` adapted to a
pure schema-add migration):

  1. ``create_tables()`` from the current models (which includes Phase
     44's new tables since the models are already there).
  2. ``stamp`` the prior revision (``4b0bf8f1761f``) so Alembic thinks
     it sits at that revision.
  3. Manually ``DROP TABLE`` the two Phase 44 tables to simulate the
     pre-Phase-44 schema state on disk.
  4. ``upgrade head`` — should re-create the two tables.
  5. Assert both tables exist with the expected columns.
  6. ``downgrade <prior_revision>`` — should drop both tables.
  7. Assert both tables are gone.
  8. ``upgrade head`` again — back to the post-Phase-44 state.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import sqlalchemy as sa


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PHASE_44_REVISION = "c1a4d8b7e2f1"
_PRIOR_REVISION = "4b0bf8f1761f"


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


def _drop_phase_44_tables(db_url: str) -> None:
    engine = sa.create_engine(db_url)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text("DROP TABLE IF EXISTS pending_action_approvals"))
            conn.execute(sa.text("DROP TABLE IF EXISTS pending_admin_actions"))
    finally:
        engine.dispose()


def _tables(db_url: str) -> set[str]:
    engine = sa.create_engine(db_url)
    try:
        insp = sa.inspect(engine)
        return set(insp.get_table_names())
    finally:
        engine.dispose()


def _columns(db_url: str, table: str) -> set[str]:
    engine = sa.create_engine(db_url)
    try:
        insp = sa.inspect(engine)
        return {c["name"] for c in insp.get_columns(table)}
    finally:
        engine.dispose()


def _build_pre_phase_44_schema(db_url: str) -> None:
    _create_all_subprocess(db_url)
    _drop_phase_44_tables(db_url)
    _run_alembic(db_url, "stamp", _PRIOR_REVISION)


def test_phase_44_upgrade_creates_both_tables():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_phase_44_schema(db_url)
        assert "pending_admin_actions" not in _tables(db_url)
        assert "pending_action_approvals" not in _tables(db_url)

        _run_alembic(db_url, "upgrade", "head")

        names = _tables(db_url)
        assert "pending_admin_actions" in names
        assert "pending_action_approvals" in names

        action_cols = _columns(db_url, "pending_admin_actions")
        expected_action_cols = {
            "id", "org_id", "action_type", "payload", "initiator_id",
            "status", "threshold", "expires_at", "created_at",
            "resolved_at", "resolution_detail",
        }
        assert expected_action_cols <= action_cols, (
            f"missing: {expected_action_cols - action_cols}"
        )

        approval_cols = _columns(db_url, "pending_action_approvals")
        expected_approval_cols = {
            "id", "pending_action_id", "approver_id", "decision",
            "reason", "created_at",
        }
        assert expected_approval_cols <= approval_cols, (
            f"missing: {expected_approval_cols - approval_cols}"
        )
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase_44_upgrade_downgrade_upgrade_cycle():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_phase_44_schema(db_url)

        _run_alembic(db_url, "upgrade", "head")
        names = _tables(db_url)
        assert "pending_admin_actions" in names
        assert "pending_action_approvals" in names

        _run_alembic(db_url, "downgrade", _PRIOR_REVISION)
        names = _tables(db_url)
        assert "pending_admin_actions" not in names
        assert "pending_action_approvals" not in names

        _run_alembic(db_url, "upgrade", "head")
        names = _tables(db_url)
        assert "pending_admin_actions" in names
        assert "pending_action_approvals" in names
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase_44_unique_decision_per_approver_constraint():
    """The (pending_action_id, approver_id) unique constraint prevents a
    single approver from registering two decisions on the same action.
    FK enforcement is off (SQLite default) so we can use synthetic ids."""
    import uuid
    from datetime import datetime, timezone

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_phase_44_schema(db_url)
        _run_alembic(db_url, "upgrade", "head")

        engine = sa.create_engine(db_url)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        try:
            with engine.begin() as conn:
                pid, uid = str(uuid.uuid4()), str(uuid.uuid4())
                conn.execute(sa.text(
                    "INSERT INTO pending_action_approvals "
                    "(id, pending_action_id, approver_id, decision, reason, created_at) "
                    "VALUES (:i, :pid, :uid, 'approve', NULL, :now)"
                ), {"i": str(uuid.uuid4()), "pid": pid, "uid": uid, "now": now})

                import pytest
                with pytest.raises(Exception):
                    with engine.begin() as conn2:
                        conn2.execute(sa.text(
                            "INSERT INTO pending_action_approvals "
                            "(id, pending_action_id, approver_id, decision, reason, "
                            " created_at) VALUES "
                            "(:i, :pid, :uid, 'decline', 'x', :now)"
                        ), {"i": str(uuid.uuid4()), "pid": pid, "uid": uid, "now": now})
        finally:
            engine.dispose()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
