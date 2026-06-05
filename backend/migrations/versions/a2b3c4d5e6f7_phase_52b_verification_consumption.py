"""phase 52b — verification_consumption table (free-pool metering)

Two additions:

  1. ``verification_consumption`` table
    - ``id`` (uuid pk)
    - ``year_month`` (String(7), indexed) — "YYYY-MM" bucket key.
      Implicit monthly reset via this key (no cron).
    - ``org_id`` (FK organizations.id, nullable, indexed) —
      triggering org if known; null for Settings-initiated
      verifications without an org context.
    - ``user_id`` (FK users.id, indexed) — who got verified.
    - ``provider_session_id`` (String(128), nullable) — for audit /
      double-call detection.
    - ``provenance`` (String(16), server_default 'didit').
    - ``created_at`` (DateTime, default now).

  2. ``verification_sessions.triggering_org_id`` column (FK
     organizations.id, nullable, indexed) — threaded from the
     session-create body through to the consumption row at webhook
     approval. NULL = Settings-initiated, no org context.

Append-only consumption rows. Current-month total = COUNT(*) WHERE
year_month = current. Per-org breakdown = GROUP BY org_id. No unique
constraints on the consumption table — one row per real verification,
demo_stub / backdoor provenance NEVER inserts (enforced at
``verification_metering.record_consumption``).

Hex-prefix revision id. Reversible via op.drop_table.

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-06-05 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a2b3c4d5e6f7"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_tables() -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        return set(insp.get_table_names())
    except Exception:
        return set()


def _existing_columns(table: str) -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        return {c["name"] for c in insp.get_columns(table)}
    except Exception:
        return set()


def _existing_indexes(table: str) -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        return {ix["name"] for ix in insp.get_indexes(table)}
    except Exception:
        return set()


TRIGGERING_ORG_INDEX = "ix_verification_sessions_triggering_org_id"


def upgrade() -> None:
    tables = _existing_tables()

    sess_cols = _existing_columns("verification_sessions")
    if "triggering_org_id" not in sess_cols:
        with op.batch_alter_table("verification_sessions") as batch_op:
            batch_op.add_column(sa.Column(
                "triggering_org_id", sa.String(length=36),
                sa.ForeignKey(
                    "organizations.id",
                    ondelete="SET NULL",
                    name="fk_verification_sessions_triggering_org_id",
                ),
                nullable=True,
            ))

    sess_indexes = _existing_indexes("verification_sessions")
    if TRIGGERING_ORG_INDEX not in sess_indexes:
        op.create_index(
            TRIGGERING_ORG_INDEX, "verification_sessions",
            ["triggering_org_id"],
        )

    if "verification_consumption" not in tables:
        op.create_table(
            "verification_consumption",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "year_month", sa.String(length=7),
                nullable=False, index=True,
            ),
            sa.Column(
                "org_id", sa.String(length=36),
                sa.ForeignKey("organizations.id", ondelete="SET NULL"),
                nullable=True, index=True,
            ),
            sa.Column(
                "user_id", sa.String(length=36),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False, index=True,
            ),
            sa.Column(
                "provider_session_id", sa.String(length=128),
                nullable=True,
            ),
            sa.Column(
                "provenance", sa.String(length=16),
                nullable=False, server_default="didit",
            ),
            sa.Column(
                "created_at", sa.DateTime,
                nullable=False, server_default=sa.func.now(),
            ),
        )


def downgrade() -> None:
    tables = _existing_tables()
    if "verification_consumption" in tables:
        op.drop_table("verification_consumption")
    sess_indexes = _existing_indexes("verification_sessions")
    if TRIGGERING_ORG_INDEX in sess_indexes:
        op.drop_index(
            TRIGGERING_ORG_INDEX, table_name="verification_sessions",
        )
    sess_cols = _existing_columns("verification_sessions")
    if "triggering_org_id" in sess_cols:
        with op.batch_alter_table("verification_sessions") as batch_op:
            batch_op.drop_column("triggering_org_id")
