"""Phase 13.3 migration: verify upgrade -> downgrade -> upgrade cycle on
SQLite, plus the data-migration step that maps legacy email-channel rows
to the new email_immediate / email_daily / email_weekly channels based
on each user's prior digest_cadence.

Mirrors ``test_phase13_migration_cycle.py`` but:

  - Stamps at the Phase 13 head (f1a3c8d92e60) so the upgrade runs the
    13.3 migration only.
  - Seeds users with different ``digest_cadence`` values + matching
    ``notification_preferences`` rows on the legacy ``email`` channel.
  - After upgrade, asserts the new channel rows are present with the
    correct mapping; the legacy ``email`` rows are gone; the
    ``digest_cadence`` column is dropped; the ``quiet_hours_start`` /
    ``quiet_hours_end`` columns exist with defaults.
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
_PHASE_13_3_REVISION = "b9e2f4a17c83"
_PRIOR_REVISION = "f1a3c8d92e60"


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


def _build_pre_phase13_3_schema(db_url: str) -> None:
    """Build today's schema via create_tables, then patch it to look
    like a stamped-but-not-fresh DB at the prior revision (f1a3c8d92e60):

      - DROP the new 13.3 columns (quiet_hours_start, quiet_hours_end).
      - ADD the legacy digest_cadence column back with default
        'real_time' so we can seed the data-migration test cases.
      - Stamp alembic at the prior revision so ``upgrade head`` runs the
        13.3 migration on top of pre-13.3 shape.
    """
    _create_all_subprocess(db_url)
    engine = sa.create_engine(db_url)
    try:
        with engine.begin() as conn:
            user_cols = {c["name"] for c in sa.inspect(conn).get_columns("users")}
            # Drop 13.3 columns if create_tables added them (today's models).
            for col in ("quiet_hours_start", "quiet_hours_end"):
                if col in user_cols:
                    conn.execute(sa.text(f"ALTER TABLE users DROP COLUMN {col}"))
            # Re-add digest_cadence as it would have existed pre-13.3.
            user_cols = {c["name"] for c in sa.inspect(conn).get_columns("users")}
            if "digest_cadence" not in user_cols:
                conn.execute(sa.text(
                    "ALTER TABLE users ADD COLUMN digest_cadence "
                    "VARCHAR NOT NULL DEFAULT 'real_time'"
                ))
    finally:
        engine.dispose()
    _run_alembic(db_url, "stamp", _PRIOR_REVISION)


def _seed_user(
    db_url: str, *, username: str, digest_cadence: str,
) -> str:
    """Insert a user with the given digest_cadence."""
    engine = sa.create_engine(db_url)
    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text(
                "INSERT INTO users "
                "(id, username, display_name, password_hash, is_admin, "
                " user_type, delegation_strategy, email_verified, "
                " default_follow_policy, "
                " digest_cadence, quiet_hours_enabled, "
                " notification_intro_dismissed, created_at) "
                "VALUES (:id, :u, :dn, 'x', 0, 'human', "
                "'strict_precedence', 0, 'require_approval', :dc, 0, 0, :now)"
            ), {
                "id": user_id, "u": username, "dn": username,
                "dc": digest_cadence, "now": now,
            })
    finally:
        engine.dispose()
    return user_id


def _seed_legacy_email_pref(
    db_url: str, *, user_id: str, event_type: str,
) -> None:
    """Insert a legacy notification_preferences row with channel='email'
    and enabled=True."""
    engine = sa.create_engine(db_url)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text(
                "INSERT INTO notification_preferences "
                "(id, user_id, event_type, channel, enabled, "
                " created_at, updated_at) "
                "VALUES (:id, :uid, :ev, 'email', 1, :now, :now)"
            ), {
                "id": str(uuid.uuid4()), "uid": user_id, "ev": event_type,
                "now": now,
            })
    finally:
        engine.dispose()


def _seed_floor_approached_pref(db_url: str, *, user_id: str) -> None:
    engine = sa.create_engine(db_url)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text(
                "INSERT INTO notification_preferences "
                "(id, user_id, event_type, channel, enabled, "
                " created_at, updated_at) "
                "VALUES (:id, :uid, "
                "'sustained_majority.floor_approached', 'in_app', 1, "
                ":now, :now)"
            ), {
                "id": str(uuid.uuid4()), "uid": user_id, "now": now,
            })
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


def _prefs_for(db_url: str, user_id: str) -> list[tuple[str, str, int]]:
    """Return [(event_type, channel, enabled_int), ...] for a user."""
    engine = sa.create_engine(db_url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(sa.text(
                "SELECT event_type, channel, enabled "
                "FROM notification_preferences "
                "WHERE user_id = :uid "
                "ORDER BY event_type, channel"
            ), {"uid": user_id}).fetchall()
            return [(r[0], r[1], int(r[2])) for r in rows]
    finally:
        engine.dispose()


def _count_prefs(db_url: str) -> int:
    engine = sa.create_engine(db_url)
    try:
        with engine.connect() as conn:
            return conn.execute(sa.text(
                "SELECT COUNT(*) FROM notification_preferences"
            )).scalar() or 0
    finally:
        engine.dispose()


def test_phase13_3_upgrade_data_migration_real_time_to_immediate():
    """digest_cadence='real_time' + email pref => email_immediate row."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_phase13_3_schema(db_url)
        uid = _seed_user(db_url, username="rt_user", digest_cadence="real_time")
        _seed_legacy_email_pref(db_url, user_id=uid, event_type="comment.replied")

        _run_alembic(db_url, "upgrade", "head")

        prefs = _prefs_for(db_url, uid)
        # Legacy email row deleted, email_immediate row inserted.
        assert ("comment.replied", "email", 1) not in prefs
        assert ("comment.replied", "email_immediate", 1) in prefs
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase13_3_upgrade_data_migration_daily_to_email_daily():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_phase13_3_schema(db_url)
        uid = _seed_user(db_url, username="d_user", digest_cadence="daily")
        _seed_legacy_email_pref(db_url, user_id=uid, event_type="proposal.entered_voting")

        _run_alembic(db_url, "upgrade", "head")

        prefs = _prefs_for(db_url, uid)
        assert ("proposal.entered_voting", "email", 1) not in prefs
        assert ("proposal.entered_voting", "email_daily", 1) in prefs
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase13_3_upgrade_data_migration_weekly_to_email_weekly():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_phase13_3_schema(db_url)
        uid = _seed_user(db_url, username="w_user", digest_cadence="weekly")
        _seed_legacy_email_pref(db_url, user_id=uid, event_type="follow.requested")

        _run_alembic(db_url, "upgrade", "head")

        prefs = _prefs_for(db_url, uid)
        assert ("follow.requested", "email", 1) not in prefs
        assert ("follow.requested", "email_weekly", 1) in prefs
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase13_3_upgrade_data_migration_off_drops_email_row():
    """digest_cadence='off' => no new channel row inserted; legacy email
    row still deleted (the user explicitly chose off)."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_phase13_3_schema(db_url)
        uid = _seed_user(db_url, username="off_user", digest_cadence="off")
        _seed_legacy_email_pref(db_url, user_id=uid, event_type="comment.replied")

        _run_alembic(db_url, "upgrade", "head")

        prefs = _prefs_for(db_url, uid)
        # No email channels at all post-migration.
        for ev, ch, _ in prefs:
            assert ch != "email"
            assert ch != "email_immediate"
            assert ch != "email_daily"
            assert ch != "email_weekly"
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase13_3_upgrade_floor_approached_pref_deleted():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_phase13_3_schema(db_url)
        uid = _seed_user(db_url, username="fa_user", digest_cadence="real_time")
        _seed_floor_approached_pref(db_url, user_id=uid)

        _run_alembic(db_url, "upgrade", "head")

        prefs = _prefs_for(db_url, uid)
        for ev, _, _ in prefs:
            assert ev != "sustained_majority.floor_approached"
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase13_3_upgrade_schema_changes():
    """Post-upgrade: digest_cadence is gone; quiet_hours_start/end exist
    with defaults."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_phase13_3_schema(db_url)
        uid = _seed_user(db_url, username="sch_user", digest_cadence="real_time")

        _run_alembic(db_url, "upgrade", "head")

        assert not _has_column(db_url, "users", "digest_cadence")
        assert _has_column(db_url, "users", "quiet_hours_start")
        assert _has_column(db_url, "users", "quiet_hours_end")
        # Defaults applied.
        assert _user_column_value(db_url, uid, "quiet_hours_start") == "21:00"
        assert _user_column_value(db_url, uid, "quiet_hours_end") == "09:00"
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase13_3_upgrade_downgrade_upgrade_cycle():
    """Full cycle reversibility on SQLite, with sample data."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_phase13_3_schema(db_url)
        uid = _seed_user(db_url, username="cyc_user", digest_cadence="daily")
        _seed_legacy_email_pref(db_url, user_id=uid, event_type="comment.replied")

        # 1. Upgrade to the Phase 13.3 head specifically (so newer
        # migrations can't make `downgrade -1` cross too many revisions).
        # Post-Phase-14 the head is c0a3e5d12f4a; we want to test the
        # 13.3 migration's reversibility in isolation.
        _run_alembic(db_url, "upgrade", _PHASE_13_3_REVISION)
        assert _has_column(db_url, "users", "quiet_hours_start")
        assert not _has_column(db_url, "users", "digest_cadence")
        prefs = _prefs_for(db_url, uid)
        assert ("comment.replied", "email_daily", 1) in prefs
        assert all(ch != "email" for _, ch, _ in prefs)

        # 2. Downgrade -1 from the 13.3 head -> back to f1a3c8d92e60.
        _run_alembic(db_url, "downgrade", "-1")
        assert not _has_column(db_url, "users", "quiet_hours_start")
        assert not _has_column(db_url, "users", "quiet_hours_end")
        assert _has_column(db_url, "users", "digest_cadence")
        # digest_cadence restored (best-effort: the user's most-frequent
        # email_* channel was email_daily, mapped back to 'daily').
        assert _user_column_value(db_url, uid, "digest_cadence") == "daily"
        # Legacy email row reconstructed.
        prefs = _prefs_for(db_url, uid)
        events_with_email = {ev for ev, ch, _ in prefs if ch == "email"}
        assert "comment.replied" in events_with_email

        # 3. Re-upgrade to the 13.3 head.
        _run_alembic(db_url, "upgrade", _PHASE_13_3_REVISION)
        assert _has_column(db_url, "users", "quiet_hours_start")
        assert not _has_column(db_url, "users", "digest_cadence")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase13_3_upgrade_preserves_unrelated_prefs():
    """In-app prefs and other event types must be left alone."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_phase13_3_schema(db_url)
        uid = _seed_user(db_url, username="pres_user", digest_cadence="real_time")
        # in-app pref on a normal event — must survive the migration.
        engine = sa.create_engine(db_url)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        try:
            with engine.begin() as conn:
                conn.execute(sa.text(
                    "INSERT INTO notification_preferences "
                    "(id, user_id, event_type, channel, enabled, "
                    " created_at, updated_at) "
                    "VALUES (:id, :uid, 'comment.replied', 'in_app', 1, "
                    ":now, :now)"
                ), {
                    "id": str(uuid.uuid4()), "uid": uid, "now": now,
                })
        finally:
            engine.dispose()

        before = _count_prefs(db_url)
        assert before == 1

        _run_alembic(db_url, "upgrade", "head")

        prefs = _prefs_for(db_url, uid)
        assert ("comment.replied", "in_app", 1) in prefs
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
