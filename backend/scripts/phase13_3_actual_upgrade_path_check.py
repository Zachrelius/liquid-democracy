"""Phase 13.3 — actual upgrade path verification (Phase 13 learning #7).

Spins up a fresh PG container, stamps at f1a3c8d92e60 (Phase 13 head),
seeds sample data (users with different digest_cadence values + matching
email-channel preference rows + a floor_approached preference row),
then runs ``alembic upgrade head`` directly. Asserts:

  - The data migration produced the expected new channel rows
    (email_immediate / email_daily / email_weekly).
  - Legacy email rows are deleted.
  - floor_approached preference rows are deleted.
  - digest_cadence column is dropped from users.
  - quiet_hours_start / quiet_hours_end columns added with defaults.
  - Pre/post counts on notification_preferences are reported.

This is the verification gap from Phase 13 — pg_smoke's upgrade mode runs
``create_all + stamp + upgrade`` which over-shapes the schema (today's
columns exist before the migration runs); seeding sample data + running
the migration on a stamped-but-not-fresh DB is what catches data-
migration bugs.
"""
from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone

_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)


_PRIOR_REV = "f1a3c8d92e60"
_PG_IMAGE = "postgres:16-alpine"
_PG_PORT = 55434
_PG_DB = "ld_phase13_3_check"
_PG_USER = "smoke"
_PG_PASSWORD = "smoke"


def _run_alembic(db_url: str, *args: str) -> None:
    env = dict(os.environ)
    env["DATABASE_URL"] = db_url
    res = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=_BACKEND_DIR, env=env, capture_output=True, text=True,
    )
    if res.returncode != 0:
        sys.stdout.write(res.stdout)
        sys.stderr.write(res.stderr)
        raise RuntimeError(f"alembic {' '.join(args)} failed")


@contextlib.contextmanager
def _pg_container():
    name = f"ld-13-3-check-{uuid.uuid4().hex[:8]}"
    print(f"[check] starting {_PG_IMAGE} as {name}")
    subprocess.run([
        "docker", "run", "-d", "--rm", "--name", name,
        "-e", f"POSTGRES_DB={_PG_DB}",
        "-e", f"POSTGRES_USER={_PG_USER}",
        "-e", f"POSTGRES_PASSWORD={_PG_PASSWORD}",
        "-p", f"{_PG_PORT}:5432", _PG_IMAGE,
    ], check=True, stdout=subprocess.DEVNULL)
    db_url = f"postgresql://{_PG_USER}:{_PG_PASSWORD}@localhost:{_PG_PORT}/{_PG_DB}"
    try:
        from sqlalchemy import create_engine, text
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                eng = create_engine(db_url)
                with eng.connect() as c:
                    c.execute(text("SELECT 1"))
                eng.dispose()
                break
            except Exception:
                time.sleep(0.5)
        yield db_url
    finally:
        print(f"[check] tearing down {name}")
        subprocess.run(["docker", "rm", "-f", name], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _create_all(db_url: str) -> None:
    code = (
        f"import os; os.environ['DATABASE_URL']={db_url!r}; "
        "from database import create_tables; create_tables()"
    )
    res = subprocess.run([sys.executable, "-c", code], cwd=_BACKEND_DIR,
                         capture_output=True, text=True)
    if res.returncode != 0:
        sys.stdout.write(res.stdout)
        sys.stderr.write(res.stderr)
        raise RuntimeError("create_tables failed")


def _drop_phase13_3_cols_and_add_digest_cadence(db_url: str) -> None:
    """Reshape today's create_all-built schema to look like a stamped-
    but-not-fresh PG at the prior revision (f1a3c8d92e60). We:
      - DROP the new 13.3 columns (quiet_hours_start, quiet_hours_end).
      - ADD the legacy digest_cadence column back with default
        'real_time' so we can seed the data-migration test cases.
    """
    from sqlalchemy import create_engine, text, inspect
    eng = create_engine(db_url)
    with eng.begin() as conn:
        cols = {c["name"] for c in inspect(conn).get_columns("users")}
        for col in ("quiet_hours_start", "quiet_hours_end"):
            if col in cols:
                conn.execute(text(f"ALTER TABLE users DROP COLUMN IF EXISTS {col} CASCADE"))
        cols = {c["name"] for c in inspect(conn).get_columns("users")}
        if "digest_cadence" not in cols:
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN digest_cadence VARCHAR "
                "NOT NULL DEFAULT 'real_time'"
            ))
    eng.dispose()


def _insert_user(db_url: str, *, username: str, digest_cadence: str) -> str:
    from sqlalchemy import create_engine, text
    eng = create_engine(db_url)
    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with eng.begin() as conn:
        conn.execute(text(
            "INSERT INTO users "
            "(id, username, display_name, password_hash, is_admin, "
            " user_type, delegation_strategy, email_verified, "
            " default_follow_policy, digest_cadence, "
            " quiet_hours_enabled, notification_intro_dismissed, created_at) "
            "VALUES (:id, :u, :dn, 'x', FALSE, 'human', "
            "'strict_precedence', FALSE, 'require_approval', :dc, "
            "FALSE, FALSE, :now)"
        ), {"id": user_id, "u": username, "dn": username,
             "dc": digest_cadence, "now": now})
    eng.dispose()
    return user_id


def _insert_pref(
    db_url: str, *, user_id: str, event_type: str, channel: str,
    enabled: bool = True,
) -> None:
    from sqlalchemy import create_engine, text
    eng = create_engine(db_url)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with eng.begin() as conn:
        conn.execute(text(
            "INSERT INTO notification_preferences "
            "(id, user_id, event_type, channel, enabled, "
            " created_at, updated_at) "
            "VALUES (:id, :uid, :ev, :ch, :en, :now, :now)"
        ), {"id": str(uuid.uuid4()), "uid": user_id, "ev": event_type,
             "ch": channel, "en": enabled, "now": now})
    eng.dispose()


def _count_prefs(db_url: str, where: str = "TRUE") -> int:
    from sqlalchemy import create_engine, text
    eng = create_engine(db_url)
    with eng.connect() as conn:
        n = conn.execute(text(
            f"SELECT COUNT(*) FROM notification_preferences WHERE {where}"
        )).scalar() or 0
    eng.dispose()
    return int(n)


def _has_column(db_url: str, table: str, col: str) -> bool:
    from sqlalchemy import create_engine, inspect
    eng = create_engine(db_url)
    try:
        with eng.connect() as conn:
            cols = {c["name"] for c in inspect(conn).get_columns(table)}
            return col in cols
    finally:
        eng.dispose()


def _user_field(db_url: str, user_id: str, field: str):
    from sqlalchemy import create_engine, text
    eng = create_engine(db_url)
    try:
        with eng.connect() as conn:
            row = conn.execute(text(
                f"SELECT {field} FROM users WHERE id = :uid"
            ), {"uid": user_id}).first()
            return None if row is None else row[0]
    finally:
        eng.dispose()


def _prefs_for_user(db_url: str, user_id: str) -> list[tuple[str, str, bool]]:
    from sqlalchemy import create_engine, text
    eng = create_engine(db_url)
    try:
        with eng.connect() as conn:
            rows = conn.execute(text(
                "SELECT event_type, channel, enabled "
                "FROM notification_preferences "
                "WHERE user_id = :uid ORDER BY event_type, channel"
            ), {"uid": user_id}).fetchall()
            return [(r[0], r[1], bool(r[2])) for r in rows]
    finally:
        eng.dispose()


def main() -> int:
    if shutil.which("docker") is None:
        print("ERROR: docker not on PATH", file=sys.stderr)
        return 1

    with _pg_container() as db_url:
        # Phase 1: build today's schema, then patch back to the
        # pre-13.3 shape (drop new cols + re-add digest_cadence).
        _create_all(db_url)
        _drop_phase13_3_cols_and_add_digest_cadence(db_url)

        # Stamp at the prior revision so alembic believes we're at 13.
        _run_alembic(db_url, "stamp", _PRIOR_REV)

        # Sanity: digest_cadence present, quiet_hours_start/end absent.
        assert _has_column(db_url, "users", "digest_cadence")
        assert not _has_column(db_url, "users", "quiet_hours_start")

        # Seed sample data: 4 users with different cadences + email rows.
        u_rt = _insert_user(db_url, username="rt_user", digest_cadence="real_time")
        u_d = _insert_user(db_url, username="d_user", digest_cadence="daily")
        u_w = _insert_user(db_url, username="w_user", digest_cadence="weekly")
        u_off = _insert_user(db_url, username="off_user", digest_cadence="off")

        for uid in (u_rt, u_d, u_w, u_off):
            _insert_pref(db_url, user_id=uid, event_type="comment.replied",
                         channel="email")
            _insert_pref(db_url, user_id=uid, event_type="comment.replied",
                         channel="in_app")  # untouched by 13.3
        # Also seed a floor_approached pref to verify deletion.
        _insert_pref(db_url, user_id=u_rt,
                     event_type="sustained_majority.floor_approached",
                     channel="in_app")

        pre_count = _count_prefs(db_url)
        pre_email_count = _count_prefs(db_url, "channel = 'email'")
        pre_floor_count = _count_prefs(
            db_url, "event_type = 'sustained_majority.floor_approached'"
        )
        print(f"[check] PRE-upgrade: notification_preferences = {pre_count}")
        print(f"[check] PRE-upgrade:   channel='email' rows = {pre_email_count}")
        print(f"[check] PRE-upgrade:   floor_approached rows = {pre_floor_count}")
        assert pre_count == 9, f"expected 9 pre rows, got {pre_count}"
        assert pre_email_count == 4
        assert pre_floor_count == 1

        # Run the actual upgrade.
        _run_alembic(db_url, "upgrade", "head")

        # Schema assertions.
        assert not _has_column(db_url, "users", "digest_cadence"), (
            "digest_cadence should be dropped"
        )
        assert _has_column(db_url, "users", "quiet_hours_start")
        assert _has_column(db_url, "users", "quiet_hours_end")
        assert _user_field(db_url, u_rt, "quiet_hours_start") == "21:00"
        assert _user_field(db_url, u_rt, "quiet_hours_end") == "09:00"

        # Data-migration assertions.
        post_count = _count_prefs(db_url)
        post_email_count = _count_prefs(db_url, "channel = 'email'")
        post_floor_count = _count_prefs(
            db_url, "event_type = 'sustained_majority.floor_approached'"
        )
        post_imm = _count_prefs(db_url, "channel = 'email_immediate'")
        post_daily = _count_prefs(db_url, "channel = 'email_daily'")
        post_weekly = _count_prefs(db_url, "channel = 'email_weekly'")
        print(f"[check] POST-upgrade: notification_preferences = {post_count}")
        print(f"[check] POST-upgrade:   channel='email' rows = {post_email_count}")
        print(f"[check] POST-upgrade:   floor_approached rows = {post_floor_count}")
        print(f"[check] POST-upgrade:   email_immediate = {post_imm}")
        print(f"[check] POST-upgrade:   email_daily = {post_daily}")
        print(f"[check] POST-upgrade:   email_weekly = {post_weekly}")

        assert post_email_count == 0, "legacy 'email' rows must be deleted"
        assert post_floor_count == 0, "floor_approached prefs must be deleted"
        assert post_imm == 1, f"expected 1 email_immediate, got {post_imm}"
        assert post_daily == 1, f"expected 1 email_daily, got {post_daily}"
        assert post_weekly == 1, f"expected 1 email_weekly, got {post_weekly}"

        # Per-user mapping correctness.
        rt_prefs = _prefs_for_user(db_url, u_rt)
        d_prefs = _prefs_for_user(db_url, u_d)
        w_prefs = _prefs_for_user(db_url, u_w)
        off_prefs = _prefs_for_user(db_url, u_off)
        assert ("comment.replied", "email_immediate", True) in rt_prefs
        assert ("comment.replied", "email_daily", True) in d_prefs
        assert ("comment.replied", "email_weekly", True) in w_prefs
        # off_user has neither legacy email nor any new cadence row.
        for ev, ch, _ in off_prefs:
            assert ch not in ("email", "email_immediate", "email_daily", "email_weekly"), (
                f"off_user should have no email channels, got {ch}"
            )
        # in_app rows preserved on all four.
        for prefs in (rt_prefs, d_prefs, w_prefs, off_prefs):
            assert ("comment.replied", "in_app", True) in prefs

        print("\n[check] PHASE 13.3 ACTUAL-UPGRADE-PATH CHECK: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
