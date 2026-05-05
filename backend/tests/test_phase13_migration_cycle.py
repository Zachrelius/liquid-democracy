"""Phase 13 migration: verify upgrade -> downgrade -> upgrade cycle on
SQLite for the new ``notifications`` + ``notification_preferences`` tables
and the four new ``users`` columns.

Mirrors ``test_phase_12_stage2_migration_cycle.py`` and the other
``test_phase*_migration_cycle.py`` patterns:

  - Build the schema from scratch via ``create_tables`` then stamp it at
    the prior revision (e6371e56e860, Phase 12 Stage 2).
  - Seed one user so the column-default backfills have something to
    operate on.
  - Drop the new tables + columns to simulate the pre-Phase-13 state.
  - Upgrade head -> tables + columns appear with the spec'd defaults.
  - Downgrade -1 -> tables + columns disappear.
  - Re-upgrade head -> tables + columns are back, idempotent.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PHASE_13_REVISION = "f1a3c8d92e60"
_PRIOR_REVISION = "41694d86821f"


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


def _build_pre_phase13_schema(db_url: str) -> None:
    """Build the full schema via create_tables, drop the Phase-13 surface,
    stamp at the prior revision so alembic believes we're pre-13.
    """
    _create_all_subprocess(db_url)
    engine = sa.create_engine(db_url)
    try:
        with engine.begin() as conn:
            tables = set(sa.inspect(conn).get_table_names())
            for tname in ("notification_preferences", "notifications"):
                if tname in tables:
                    conn.execute(sa.text(f"DROP TABLE {tname}"))
            # Drop the four new user columns. SQLite supports DROP COLUMN
            # natively in modern versions; a CREATE-INSERT-DROP rebuild
            # would be needed otherwise. The test environment uses recent
            # SQLite (Python 3.12 ships sqlite >= 3.40 which has DROP
            # COLUMN); fall back gracefully if the test runs on an older
            # version.
            user_cols = {c["name"] for c in sa.inspect(conn).get_columns("users")}
            for col in (
                "timezone",
                "digest_cadence",
                "quiet_hours_enabled",
                "notification_intro_dismissed",
            ):
                if col in user_cols:
                    try:
                        conn.execute(sa.text(f"ALTER TABLE users DROP COLUMN {col}"))
                    except Exception:
                        # Older SQLite — rebuild the table without the col.
                        # For this test setup that situation isn't expected;
                        # if it happens, surface a clear error.
                        raise RuntimeError(
                            f"SQLite version too old to DROP COLUMN {col}; "
                            "test setup needs a manual table rebuild."
                        )
    finally:
        engine.dispose()
    _run_alembic(db_url, "stamp", _PRIOR_REVISION)


def _seed_one_user(db_url: str) -> str:
    """Insert a user row in the pre-Phase-13 schema (no new cols).
    Returns the user_id."""
    engine = sa.create_engine(db_url)
    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text(
                "INSERT INTO users "
                "(id, username, display_name, password_hash, is_admin, "
                "user_type, delegation_strategy, email_verified, "
                "default_follow_policy, created_at) "
                "VALUES (:id, :u, :dn, 'x', 0, 'human', "
                "'strict_precedence', 0, 'require_approval', :now)"
            ), {"id": user_id, "u": "ph13_user", "dn": "Phase 13 Tester", "now": now})
    finally:
        engine.dispose()
    return user_id


def _has_table(db_url: str, name: str) -> bool:
    engine = sa.create_engine(db_url)
    try:
        with engine.connect() as conn:
            return name in set(sa.inspect(conn).get_table_names())
    finally:
        engine.dispose()


def _has_column(db_url: str, table: str, col: str) -> bool:
    engine = sa.create_engine(db_url)
    try:
        with engine.connect() as conn:
            cols = {c["name"] for c in sa.inspect(conn).get_columns(table)}
            return col in cols
    finally:
        engine.dispose()


def _user_column_value(db_url: str, user_id: str, col: str):
    engine = sa.create_engine(db_url)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                sa.text(f"SELECT {col} FROM users WHERE id = :uid"),
                {"uid": user_id},
            ).first()
            return None if row is None else row[0]
    finally:
        engine.dispose()


def test_phase13_upgrade_downgrade_upgrade_cycle():
    """Phase 13 migration is reversible and idempotent on SQLite.

    Cycle: pre-13 -> upgrade head -> downgrade -1 -> re-upgrade head.
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"

    try:
        _build_pre_phase13_schema(db_url)
        user_id = _seed_one_user(db_url)

        # Pre-state: tables and cols absent.
        assert not _has_table(db_url, "notifications")
        assert not _has_table(db_url, "notification_preferences")
        for col in (
            "timezone",
            "digest_cadence",
            "quiet_hours_enabled",
            "notification_intro_dismissed",
        ):
            assert not _has_column(db_url, "users", col), (
                f"Pre-state should not have users.{col}"
            )

        # 1. Upgrade head — applies Phase 13.
        _run_alembic(db_url, "upgrade", "head")
        assert _has_table(db_url, "notifications")
        assert _has_table(db_url, "notification_preferences")
        for col in (
            "timezone",
            "digest_cadence",
            "quiet_hours_enabled",
            "notification_intro_dismissed",
        ):
            assert _has_column(db_url, "users", col), (
                f"Post-upgrade should have users.{col}"
            )

        # Defaults backfilled correctly for the pre-existing user row.
        assert _user_column_value(db_url, user_id, "digest_cadence") == "real_time"
        # Boolean values come back as 0/1 on SQLite.
        assert int(_user_column_value(db_url, user_id, "quiet_hours_enabled")) == 0
        assert int(
            _user_column_value(db_url, user_id, "notification_intro_dismissed")
        ) == 0
        # Timezone is nullable; new column with no default = NULL.
        assert _user_column_value(db_url, user_id, "timezone") is None

        # 2. Downgrade -1 — reverses Phase 13.
        _run_alembic(db_url, "downgrade", "-1")
        assert not _has_table(db_url, "notifications")
        assert not _has_table(db_url, "notification_preferences")
        for col in (
            "timezone",
            "digest_cadence",
            "quiet_hours_enabled",
            "notification_intro_dismissed",
        ):
            assert not _has_column(db_url, "users", col), (
                f"Post-downgrade users.{col} should be gone"
            )

        # 3. Re-upgrade head — idempotent re-application.
        _run_alembic(db_url, "upgrade", "head")
        assert _has_table(db_url, "notifications")
        assert _has_table(db_url, "notification_preferences")
        for col in (
            "timezone",
            "digest_cadence",
            "quiet_hours_enabled",
            "notification_intro_dismissed",
        ):
            assert _has_column(db_url, "users", col)

        # Pre-existing user row defaults backfilled again.
        assert _user_column_value(db_url, user_id, "digest_cadence") == "real_time"

    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase13_upgrade_idempotent_when_re_applied():
    """Running upgrade twice with no intervening downgrade is a no-op
    on the second run — validates the introspect-and-skip guards."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"

    try:
        _build_pre_phase13_schema(db_url)
        _seed_one_user(db_url)

        _run_alembic(db_url, "upgrade", "head")
        # No-op second invocation. alembic upgrade head when at head is
        # a no-op anyway, but we exercise the path explicitly via
        # downgrade+re-upgrade to prove the migration's own guards work.
        _run_alembic(db_url, "downgrade", "-1")
        _run_alembic(db_url, "upgrade", "head")
        _run_alembic(db_url, "upgrade", "head")

        assert _has_table(db_url, "notifications")
        assert _has_table(db_url, "notification_preferences")
        assert _has_column(db_url, "users", "digest_cadence")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
