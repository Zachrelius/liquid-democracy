"""phase 90a — share distribution rules + share_start_date + period_key index

Adds:
  * share_distribution_rules table (auto-distribution rules).
  * org_memberships.share_start_date (nullable Date) — anniversary anchor.
  * ix_share_events_rule_id index (rule_id column shipped bare in Phase 90).
  * partial-unique index on share_events(org_id, period_key) WHERE period_key
    is not null — the auto-distribution idempotency guard.

No hard FK on share_events.rule_id (rule deletion leaves orphaned ids by
design). Hex-prefix revision id. Reversible.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-07-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    try:
        return name in sa.inspect(op.get_bind()).get_table_names()
    except Exception:
        return False


def _cols(table: str) -> set[str]:
    try:
        return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}
    except Exception:
        return set()


def _indexes(table: str) -> set[str]:
    try:
        return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}
    except Exception:
        return set()


def upgrade() -> None:
    if not _has_table("share_distribution_rules"):
        op.create_table(
            "share_distribution_rules",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("org_id", sa.String(), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("created_by_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("amount", sa.Integer(), nullable=False),
            sa.Column("interval_months", sa.Integer(), nullable=False),
            sa.Column("schedule_mode", sa.String(), nullable=False),
            sa.Column("anchor_date", sa.Date(), nullable=True),
            sa.Column("targeting_mode", sa.String(), nullable=False),
            sa.Column("title_ids", sa.JSON(), nullable=True),
            sa.Column("last_run_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_share_distribution_rules_org_id", "share_distribution_rules", ["org_id"])

    if "share_start_date" not in _cols("org_memberships"):
        with op.batch_alter_table("org_memberships") as batch:
            batch.add_column(sa.Column("share_start_date", sa.Date(), nullable=True))

    ix = _indexes("share_events")
    if "ix_share_events_rule_id" not in ix:
        op.create_index("ix_share_events_rule_id", "share_events", ["rule_id"])
    if "uq_share_events_org_period_key" not in ix:
        # Partial-unique: idempotency for auto-distribution grants.
        op.create_index(
            "uq_share_events_org_period_key",
            "share_events",
            ["org_id", "period_key"],
            unique=True,
            postgresql_where=sa.text("period_key IS NOT NULL"),
            sqlite_where=sa.text("period_key IS NOT NULL"),
        )


def downgrade() -> None:
    ix = _indexes("share_events")
    if "uq_share_events_org_period_key" in ix:
        op.drop_index("uq_share_events_org_period_key", table_name="share_events")
    if "ix_share_events_rule_id" in ix:
        op.drop_index("ix_share_events_rule_id", table_name="share_events")
    if "share_start_date" in _cols("org_memberships"):
        with op.batch_alter_table("org_memberships") as batch:
            batch.drop_column("share_start_date")
    if _has_table("share_distribution_rules"):
        op.drop_index("ix_share_distribution_rules_org_id", table_name="share_distribution_rules")
        op.drop_table("share_distribution_rules")
