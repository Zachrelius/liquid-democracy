"""Phase 13: notifications + notification_preferences tables + four new
``users`` columns (timezone, digest_cadence, quiet_hours_enabled,
notification_intro_dismissed).

Revision ID: f1a3c8d92e60
Revises: 41694d86821f
Create Date: 2026-05-04 18:00:00.000000

What this does
--------------

1. Creates ``notifications`` (the in-app feed source) with FK CASCADE on
   ``user_id`` so a user-delete takes their feed with them. ``org_id`` is
   a non-cascading FK (we don't want an org delete to wipe a user's
   account-level history; the ``Notification`` model treats org_id as
   informational for routing, not load-bearing identity). Indexed
   columns: ``user_id``, ``event_type``, ``org_id``, ``created_at``.

2. Creates ``notification_preferences`` (per-user-per-event-per-channel
   opt-in row, absent = False). Unique (user_id, event_type, channel).

3. Adds four columns to ``users``:
     - ``timezone``: nullable IANA tz string
     - ``digest_cadence``: NOT NULL, default ``'real_time'``
     - ``quiet_hours_enabled``: NOT NULL, default False
     - ``notification_intro_dismissed``: NOT NULL, default False

   The migration backfills the three NOT-NULL columns with their defaults
   for existing rows BEFORE the NOT NULL constraint is applied.

Idempotency
-----------

Standard introspect-and-skip pattern from Phase 8.6 / 9.5 / 9.8 / 10 / 12.
Re-running the upgrade after a partial earlier run (or a
``create_all``-then-``stamp`` deploy) is safe:

  - ``create_table`` checks for existence first.
  - ``add_column`` checks for column presence first.
  - The default-backfill UPDATE is a no-op for rows that already carry
    the default (it WHEREs on IS NULL anyway).

Downgrade
---------

Drops both new tables and removes the four columns from ``users``. Both
PG and SQLite paths are exercised; SQLite uses ``batch_alter_table`` for
the DROP COLUMN steps because legacy SQLite versions don't support DROP
COLUMN natively (Alembic handles the table-rebuild dance).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f1a3c8d92e60'
down_revision: Union[str, None] = '41694d86821f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_USER_COLUMNS: tuple[tuple[str, sa.types.TypeEngine, bool, object], ...] = (
    # (name, type, nullable, server_default)
    # Phase 13.2 fix: PostgreSQL strict-types BOOLEAN columns and rejects
    # `0` as a default (DatatypeMismatch). Use sa.false() so the dialect
    # emits FALSE on PG and 0 on SQLite. The original sa.text("0") passed
    # SQLite tests + create_all-based pg_smoke but failed prod's actual
    # alembic upgrade path with column "..." is of type boolean but
    # default expression is of type integer.
    ("timezone", sa.String(), True, None),
    ("digest_cadence", sa.String(), False, "real_time"),
    ("quiet_hours_enabled", sa.Boolean(), False, sa.false()),
    ("notification_intro_dismissed", sa.Boolean(), False, sa.false()),
)


def _existing_columns(inspector, table: str) -> set[str]:
    try:
        return {c["name"] for c in inspector.get_columns(table)}
    except Exception:
        return set()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # ----- 1. notifications table ---------------------------------------
    if "notifications" not in existing_tables:
        op.create_table(
            "notifications",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "user_id", sa.String(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column(
                "org_id", sa.String(),
                sa.ForeignKey("organizations.id"),
                nullable=True,
            ),
            sa.Column(
                "actor_id", sa.String(),
                sa.ForeignKey("users.id"),
                nullable=True,
            ),
            sa.Column("target_type", sa.String(), nullable=True),
            sa.Column("target_id", sa.String(), nullable=True),
            sa.Column("payload", sa.JSON(), nullable=True),
            sa.Column("read_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index(
            "ix_notifications_user_id", "notifications", ["user_id"],
            unique=False,
        )
        op.create_index(
            "ix_notifications_event_type", "notifications", ["event_type"],
            unique=False,
        )
        op.create_index(
            "ix_notifications_org_id", "notifications", ["org_id"],
            unique=False,
        )
        op.create_index(
            "ix_notifications_created_at", "notifications", ["created_at"],
            unique=False,
        )

    # ----- 2. notification_preferences table ----------------------------
    existing_tables = set(sa.inspect(bind).get_table_names())
    if "notification_preferences" not in existing_tables:
        op.create_table(
            "notification_preferences",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "user_id", sa.String(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("channel", sa.String(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "user_id", "event_type", "channel",
                name="uq_notif_pref_user_event_channel",
            ),
        )
        op.create_index(
            "ix_notification_preferences_user_id",
            "notification_preferences", ["user_id"], unique=False,
        )

    # ----- 3. users column additions ------------------------------------
    if "users" in set(sa.inspect(bind).get_table_names()):
        existing_user_cols = _existing_columns(sa.inspect(bind), "users")

        # Add columns one-by-one with batch_alter_table to satisfy SQLite.
        with op.batch_alter_table("users", schema=None) as batch_op:
            if "timezone" not in existing_user_cols:
                batch_op.add_column(
                    sa.Column("timezone", sa.String(), nullable=True),
                )
            if "digest_cadence" not in existing_user_cols:
                batch_op.add_column(
                    sa.Column(
                        "digest_cadence", sa.String(),
                        nullable=False, server_default="real_time",
                    ),
                )
            if "quiet_hours_enabled" not in existing_user_cols:
                batch_op.add_column(
                    sa.Column(
                        "quiet_hours_enabled", sa.Boolean(),
                        nullable=False, server_default=sa.false(),
                    ),
                )
            if "notification_intro_dismissed" not in existing_user_cols:
                batch_op.add_column(
                    sa.Column(
                        "notification_intro_dismissed", sa.Boolean(),
                        nullable=False, server_default=sa.false(),
                    ),
                )

        # Belt-and-braces backfill: any pre-existing rows that may have
        # snuck through without a server_default get patched here.
        bind2 = op.get_bind()
        bind2.execute(sa.text(
            "UPDATE users SET digest_cadence = 'real_time' "
            "WHERE digest_cadence IS NULL"
        ))
        # Boolean defaults — ANSI '0' works on SQLite; PG accepts FALSE.
        # Guard for pre-existing NULLs only.
        if bind2.dialect.name == "postgresql":
            bind2.execute(sa.text(
                "UPDATE users SET quiet_hours_enabled = FALSE "
                "WHERE quiet_hours_enabled IS NULL"
            ))
            bind2.execute(sa.text(
                "UPDATE users SET notification_intro_dismissed = FALSE "
                "WHERE notification_intro_dismissed IS NULL"
            ))
        else:
            bind2.execute(sa.text(
                "UPDATE users SET quiet_hours_enabled = 0 "
                "WHERE quiet_hours_enabled IS NULL"
            ))
            bind2.execute(sa.text(
                "UPDATE users SET notification_intro_dismissed = 0 "
                "WHERE notification_intro_dismissed IS NULL"
            ))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # ----- Reverse 3: drop user columns ---------------------------------
    if "users" in existing_tables:
        existing_user_cols = _existing_columns(sa.inspect(bind), "users")

        if bind.dialect.name == "postgresql":
            for col in (
                "notification_intro_dismissed",
                "quiet_hours_enabled",
                "digest_cadence",
                "timezone",
            ):
                if col in existing_user_cols:
                    op.execute(
                        f"ALTER TABLE users DROP COLUMN IF EXISTS {col} CASCADE"
                    )
        else:
            with op.batch_alter_table("users", schema=None) as batch_op:
                for col in (
                    "notification_intro_dismissed",
                    "quiet_hours_enabled",
                    "digest_cadence",
                    "timezone",
                ):
                    if col in existing_user_cols:
                        batch_op.drop_column(col)

    # ----- Reverse 2: drop notification_preferences ---------------------
    if "notification_preferences" in existing_tables:
        for ix in ("ix_notification_preferences_user_id",):
            try:
                op.drop_index(ix, table_name="notification_preferences")
            except Exception:
                pass
        op.drop_table("notification_preferences")

    # ----- Reverse 1: drop notifications --------------------------------
    if "notifications" in existing_tables:
        for ix in (
            "ix_notifications_created_at",
            "ix_notifications_org_id",
            "ix_notifications_event_type",
            "ix_notifications_user_id",
        ):
            try:
                op.drop_index(ix, table_name="notifications")
            except Exception:
                pass
        op.drop_table("notifications")
