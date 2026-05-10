"""Phase 13.3 actual-upgrade-path seed module — Phase 15 G5 equivalence test.

Re-implements the seed + reshape + verify logic from
``phase13_3_actual_upgrade_path_check.py`` against the standard
``pg_smoke.py --mode actual-upgrade`` interface. Used as a regression
gate when introducing the new mode — running this against
``--prior-revision f1a3c8d92e60`` should produce equivalent pre/post
counts to the single-purpose script.

Phase 13.3's migration DROPs ``users.digest_cadence`` and ADDs
``users.quiet_hours_start/end``. To stage the prior schema correctly,
``reshape(engine)`` undoes the post-migration shape (drop the new cols,
re-add the legacy col with default 'real_time') BEFORE the seed runs —
so seeded users can carry the legacy ``digest_cadence`` value the
migration's data step transforms.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def reshape(engine) -> None:
    """Undo today's schema additions to match the prior revision shape.

    Drops the post-13.3 ``quiet_hours_start/end`` cols and re-adds the
    legacy ``digest_cadence`` col with default 'real_time'. Idempotent.
    """
    from sqlalchemy import text, inspect
    with engine.begin() as conn:
        cols = {c["name"] for c in inspect(conn).get_columns("users")}
        for col in ("quiet_hours_start", "quiet_hours_end"):
            if col in cols:
                conn.execute(text(
                    f"ALTER TABLE users DROP COLUMN IF EXISTS {col} CASCADE"
                ))
        cols = {c["name"] for c in inspect(conn).get_columns("users")}
        if "digest_cadence" not in cols:
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN digest_cadence VARCHAR "
                "NOT NULL DEFAULT 'real_time'"
            ))


def seed(engine) -> None:
    """Insert 4 users with the four legacy ``digest_cadence`` values plus
    matching email-channel preferences and one floor_approached pref.
    """
    from sqlalchemy import text
    now = _now_naive()

    cadences = ("real_time", "daily", "weekly", "off")
    user_ids: dict[str, str] = {}

    with engine.begin() as conn:
        for cadence in cadences:
            uid = str(uuid.uuid4())
            user_ids[cadence] = uid
            conn.execute(text(
                "INSERT INTO users "
                "(id, username, display_name, password_hash, is_admin, "
                " user_type, delegation_strategy, email_verified, "
                " default_follow_policy, digest_cadence, "
                " quiet_hours_enabled, notification_intro_dismissed, created_at) "
                "VALUES (:id, :u, :dn, 'x', FALSE, 'human', "
                "'strict_precedence', FALSE, 'require_approval', :dc, "
                "FALSE, FALSE, :now)"
            ), {
                "id": uid, "u": f"u_{cadence}", "dn": f"u_{cadence}",
                "dc": cadence, "now": now,
            })
            # email + in_app prefs for each user (legacy 'email' channel).
            for channel in ("email", "in_app"):
                conn.execute(text(
                    "INSERT INTO notification_preferences "
                    "(id, user_id, event_type, channel, enabled, "
                    " created_at, updated_at) "
                    "VALUES (:id, :uid, :ev, :ch, TRUE, :now, :now)"
                ), {
                    "id": str(uuid.uuid4()), "uid": uid,
                    "ev": "comment.replied", "ch": channel, "now": now,
                })

        # One floor_approached pref to verify deletion.
        conn.execute(text(
            "INSERT INTO notification_preferences "
            "(id, user_id, event_type, channel, enabled, "
            " created_at, updated_at) "
            "VALUES (:id, :uid, :ev, 'in_app', TRUE, :now, :now)"
        ), {
            "id": str(uuid.uuid4()), "uid": user_ids["real_time"],
            "ev": "sustained_majority.floor_approached", "now": now,
        })


def verify(engine) -> None:
    """Post-upgrade assertions identical to the single-purpose script."""
    from sqlalchemy import text, inspect
    with engine.connect() as conn:
        cols = {c["name"] for c in inspect(conn).get_columns("users")}
        assert "digest_cadence" not in cols, (
            "digest_cadence should be dropped post-upgrade"
        )
        assert "quiet_hours_start" in cols and "quiet_hours_end" in cols

        def count(where: str) -> int:
            return int(conn.execute(text(
                f"SELECT COUNT(*) FROM notification_preferences WHERE {where}"
            )).scalar() or 0)

        post_email = count("channel = 'email'")
        post_floor = count(
            "event_type = 'sustained_majority.floor_approached'"
        )
        post_imm = count("channel = 'email_immediate'")
        post_daily = count("channel = 'email_daily'")
        post_weekly = count("channel = 'email_weekly'")

        print(
            f"[seed_phase13_3] POST-upgrade counts: "
            f"email={post_email}, floor_approached={post_floor}, "
            f"email_immediate={post_imm}, email_daily={post_daily}, "
            f"email_weekly={post_weekly}",
            flush=True,
        )

        assert post_email == 0, "legacy 'email' rows must be deleted"
        assert post_floor == 0, "floor_approached prefs must be deleted"
        assert post_imm == 1, f"expected 1 email_immediate, got {post_imm}"
        assert post_daily == 1, f"expected 1 email_daily, got {post_daily}"
        assert post_weekly == 1, f"expected 1 email_weekly, got {post_weekly}"
