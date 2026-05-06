"""Phase 13.3 — Preferences refinements: split email channel into 3
discrete channels, add adjustable quiet-hours start/end columns to users,
drop the global digest_cadence column, and clean up the deleted
sustained_majority.floor_approached event type's preference rows.

Revision ID: b9e2f4a17c83
Revises: f1a3c8d92e60
Create Date: 2026-05-04 21:00:00.000000

What this does
--------------

Three coordinated changes:

1. **Data migration (BEFORE schema alter):**
   For every ``notification_preferences`` row with ``channel='email'``
   and ``enabled=True``, look up the user's existing ``digest_cadence``
   and insert a new row with the corresponding new channel:
     - ``digest_cadence='real_time'`` -> ``channel='email_immediate'``
     - ``digest_cadence='daily'``     -> ``channel='email_daily'``
     - ``digest_cadence='weekly'``    -> ``channel='email_weekly'``
     - ``digest_cadence='off'``       -> no insert (their explicit "off")
   Then DELETE all rows with ``channel='email'`` (the legacy channel
   value is gone).

2. **Schema:**
   - Add ``users.quiet_hours_start`` (String HH:MM, NOT NULL,
     default '21:00').
   - Add ``users.quiet_hours_end`` (String HH:MM, NOT NULL,
     default '09:00').
   - Drop ``users.digest_cadence`` (the data migration above has
     already extracted whatever signal it carried).

3. **Floor-approached cleanup:**
   DELETE all ``notification_preferences`` rows where
   ``event_type='sustained_majority.floor_approached'``. Idempotent.

We use String HH:MM rather than TIME because TIME defaults are awkward
across SQLite + PG; HH:MM strings keep the schema portable and the
endpoint validation is straightforward.

Downgrade
---------

Best-effort reversal. The data migration's reverse is lossy — if a user
had multiple cadences across events post-13.3 (which 13.3 enables), we
pick the most-frequent one when restoring digest_cadence. Floor-
approached preference rows are NOT reconstructed (the source data is
gone).
"""
from typing import Sequence, Union
from collections import Counter

from alembic import op
import sqlalchemy as sa


revision: str = 'b9e2f4a17c83'
down_revision: Union[str, None] = 'f1a3c8d92e60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns(inspector, table: str) -> set[str]:
    try:
        return {c["name"] for c in inspector.get_columns(table)}
    except Exception:
        return set()


def _existing_tables(inspector) -> set[str]:
    try:
        return set(inspector.get_table_names())
    except Exception:
        return set()


def _now_iso() -> str:
    """Naive UTC ISO timestamp string for INSERT defaults."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")


def _new_uuid() -> str:
    import uuid
    return str(uuid.uuid4())


# Mapping of digest_cadence -> new channel name. ``off`` and any unknown
# value yields no insert.
_CADENCE_TO_CHANNEL: dict[str, str] = {
    "real_time": "email_immediate",
    "daily": "email_daily",
    "weekly": "email_weekly",
}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = _existing_tables(inspector)
    is_pg = bind.dialect.name == "postgresql"

    # ----- 0. Floor-approached cleanup (idempotent first; harmless if
    #          notification_preferences doesn't exist yet) ---------------
    if "notification_preferences" in tables:
        bind.execute(sa.text(
            "DELETE FROM notification_preferences "
            "WHERE event_type = 'sustained_majority.floor_approached'"
        ))

    # ----- 1. Data migration: expand legacy email rows -------------------
    # Only run if both notification_preferences and the digest_cadence
    # column exist. Otherwise we're either pre-13 (nothing to migrate) or
    # post-13.3 already (idempotent re-run).
    user_cols = _existing_columns(inspector, "users") if "users" in tables else set()
    if (
        "notification_preferences" in tables
        and "digest_cadence" in user_cols
    ):
        # Pull (user_id, event_type, digest_cadence) for every legacy
        # email-enabled row.
        rows = bind.execute(sa.text(
            "SELECT np.user_id, np.event_type, u.digest_cadence "
            "FROM notification_preferences np "
            "JOIN users u ON u.id = np.user_id "
            "WHERE np.channel = 'email' AND np.enabled = "
            + ("TRUE" if is_pg else "1")
        )).fetchall()

        now_str = _now_iso()
        for row in rows:
            user_id = row[0]
            event_type = row[1]
            cadence = (row[2] or "").strip()
            new_channel = _CADENCE_TO_CHANNEL.get(cadence)
            if new_channel is None:
                continue
            # Insert with ON CONFLICT DO NOTHING (PG) /
            # INSERT OR IGNORE (SQLite) so re-runs are idempotent.
            new_id = _new_uuid()
            if is_pg:
                bind.execute(
                    sa.text(
                        "INSERT INTO notification_preferences "
                        "(id, user_id, event_type, channel, enabled, "
                        " created_at, updated_at) "
                        "VALUES (:id, :uid, :ev, :ch, TRUE, :now, :now) "
                        "ON CONFLICT (user_id, event_type, channel) "
                        "DO NOTHING"
                    ),
                    {
                        "id": new_id, "uid": user_id, "ev": event_type,
                        "ch": new_channel, "now": now_str,
                    },
                )
            else:
                bind.execute(
                    sa.text(
                        "INSERT OR IGNORE INTO notification_preferences "
                        "(id, user_id, event_type, channel, enabled, "
                        " created_at, updated_at) "
                        "VALUES (:id, :uid, :ev, :ch, 1, :now, :now)"
                    ),
                    {
                        "id": new_id, "uid": user_id, "ev": event_type,
                        "ch": new_channel, "now": now_str,
                    },
                )

        # Delete legacy email rows after expansion.
        bind.execute(sa.text(
            "DELETE FROM notification_preferences WHERE channel = 'email'"
        ))

    # ----- 2. Schema: add quiet_hours_start/end + drop digest_cadence ----
    if "users" in tables:
        user_cols = _existing_columns(sa.inspect(bind), "users")

        with op.batch_alter_table("users", schema=None) as batch_op:
            if "quiet_hours_start" not in user_cols:
                batch_op.add_column(
                    sa.Column(
                        "quiet_hours_start",
                        sa.String(length=5),
                        nullable=False,
                        server_default=sa.text("'21:00'"),
                    ),
                )
            if "quiet_hours_end" not in user_cols:
                batch_op.add_column(
                    sa.Column(
                        "quiet_hours_end",
                        sa.String(length=5),
                        nullable=False,
                        server_default=sa.text("'09:00'"),
                    ),
                )

        # Belt-and-braces backfill in case rows snuck through without the
        # default (idempotent — WHERE IS NULL guards).
        bind.execute(sa.text(
            "UPDATE users SET quiet_hours_start = '21:00' "
            "WHERE quiet_hours_start IS NULL"
        ))
        bind.execute(sa.text(
            "UPDATE users SET quiet_hours_end = '09:00' "
            "WHERE quiet_hours_end IS NULL"
        ))

        # Drop digest_cadence (after data migration extracted its signal).
        user_cols = _existing_columns(sa.inspect(bind), "users")
        if "digest_cadence" in user_cols:
            if is_pg:
                op.execute(
                    "ALTER TABLE users DROP COLUMN IF EXISTS digest_cadence CASCADE"
                )
            else:
                with op.batch_alter_table("users", schema=None) as batch_op:
                    batch_op.drop_column("digest_cadence")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = _existing_tables(inspector)
    is_pg = bind.dialect.name == "postgresql"

    if "users" in tables:
        user_cols = _existing_columns(inspector, "users")

        # Re-add digest_cadence with default 'real_time'. Compute a
        # per-user best-effort restore value from the new channel rows
        # (most-frequent cadence among that user's email_* prefs).
        if "digest_cadence" not in user_cols:
            with op.batch_alter_table("users", schema=None) as batch_op:
                batch_op.add_column(
                    sa.Column(
                        "digest_cadence",
                        sa.String(),
                        nullable=False,
                        server_default="real_time",
                    ),
                )
            bind.execute(sa.text(
                "UPDATE users SET digest_cadence = 'real_time' "
                "WHERE digest_cadence IS NULL"
            ))

        # Best-effort restore: if notification_preferences exists, pick
        # each user's most-frequent email_* channel and map back to
        # digest_cadence.
        tables = _existing_tables(sa.inspect(bind))
        if "notification_preferences" in tables:
            channel_to_cadence = {
                "email_immediate": "real_time",
                "email_daily": "daily",
                "email_weekly": "weekly",
            }
            rows = bind.execute(sa.text(
                "SELECT user_id, channel FROM notification_preferences "
                "WHERE channel IN ('email_immediate','email_daily','email_weekly') "
                "  AND enabled = " + ("TRUE" if is_pg else "1")
            )).fetchall()
            counts: dict[str, Counter] = {}
            for row in rows:
                counts.setdefault(row[0], Counter())[row[1]] += 1
            for uid, ctr in counts.items():
                most_common_channel = ctr.most_common(1)[0][0]
                cadence = channel_to_cadence.get(most_common_channel, "real_time")
                bind.execute(
                    sa.text(
                        "UPDATE users SET digest_cadence = :c WHERE id = :u"
                    ),
                    {"c": cadence, "u": uid},
                )

            # Reverse-data-migrate: insert legacy email rows for any user
            # who has at least one of the new email_* rows enabled.
            now_str = _now_iso()
            distinct = bind.execute(sa.text(
                "SELECT DISTINCT user_id, event_type "
                "FROM notification_preferences "
                "WHERE channel IN ('email_immediate','email_daily','email_weekly') "
                "  AND enabled = " + ("TRUE" if is_pg else "1")
            )).fetchall()
            for row in distinct:
                new_id = _new_uuid()
                if is_pg:
                    bind.execute(
                        sa.text(
                            "INSERT INTO notification_preferences "
                            "(id, user_id, event_type, channel, enabled, "
                            " created_at, updated_at) "
                            "VALUES (:id, :uid, :ev, 'email', TRUE, :now, :now) "
                            "ON CONFLICT (user_id, event_type, channel) "
                            "DO NOTHING"
                        ),
                        {
                            "id": new_id, "uid": row[0], "ev": row[1],
                            "now": now_str,
                        },
                    )
                else:
                    bind.execute(
                        sa.text(
                            "INSERT OR IGNORE INTO notification_preferences "
                            "(id, user_id, event_type, channel, enabled, "
                            " created_at, updated_at) "
                            "VALUES (:id, :uid, :ev, 'email', 1, :now, :now)"
                        ),
                        {
                            "id": new_id, "uid": row[0], "ev": row[1],
                            "now": now_str,
                        },
                    )

            # Delete the new email_* rows.
            bind.execute(sa.text(
                "DELETE FROM notification_preferences "
                "WHERE channel IN ('email_immediate','email_daily','email_weekly')"
            ))

        # Drop quiet_hours_start / quiet_hours_end.
        user_cols = _existing_columns(sa.inspect(bind), "users")
        if is_pg:
            for col in ("quiet_hours_end", "quiet_hours_start"):
                if col in user_cols:
                    op.execute(
                        f"ALTER TABLE users DROP COLUMN IF EXISTS {col} CASCADE"
                    )
        else:
            with op.batch_alter_table("users", schema=None) as batch_op:
                for col in ("quiet_hours_end", "quiet_hours_start"):
                    if col in user_cols:
                        batch_op.drop_column(col)
