"""phase 90 — share_events ledger table

Append-only ledger of every voting-weight ("share") movement (admin set,
auto-distribution, transfer). Independent of 90a: rule_id / period_key ship as
bare nullable columns (no FK / no index yet) so this stage stands alone.

Hex-prefix revision id. Reversible.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-07-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    try:
        return name in sa.inspect(bind).get_table_names()
    except Exception:
        return False


def upgrade() -> None:
    if _has_table("share_events"):
        return
    op.create_table(
        "share_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("from_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("to_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("resulting_balance", sa.Integer(), nullable=True),
        sa.Column("actor_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("rule_id", sa.String(), nullable=True),
        sa.Column("period_key", sa.String(), nullable=True),
    )
    op.create_index("ix_share_events_org_id", "share_events", ["org_id"])
    op.create_index("ix_share_events_created_at", "share_events", ["created_at"])
    op.create_index("ix_share_events_event_type", "share_events", ["event_type"])
    op.create_index("ix_share_events_user_id", "share_events", ["user_id"])


def downgrade() -> None:
    if not _has_table("share_events"):
        return
    op.drop_index("ix_share_events_user_id", table_name="share_events")
    op.drop_index("ix_share_events_event_type", table_name="share_events")
    op.drop_index("ix_share_events_created_at", table_name="share_events")
    op.drop_index("ix_share_events_org_id", table_name="share_events")
    op.drop_table("share_events")
