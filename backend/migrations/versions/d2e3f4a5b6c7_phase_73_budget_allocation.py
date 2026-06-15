"""phase 73 — budget allocation voting method columns

Adds the additive-layer columns for Mode A (allocation) budget voting:

  * ``proposals.budget_config`` (JSON, nullable) — the budget-proposal config
    blob. NULL on every existing row => not a budget proposal (byte-for-byte
    unchanged). Shared across budget modes; ``mode`` inside selects the tally.
  * ``proposal_options.budget_max_amount`` (Float, nullable) — per-bucket
    ceiling for allocation buckets. NULL on every non-budget option.

Both columns are nullable with no server default, so the migration is a pure
additive layer: no data backfill, no behavior change for existing rows.

NOTE: Phase 74 (Project budget, Mode B) will extend ``proposal_options`` AGAIN
with discrete-item columns (budget_floor_amount, budget_kind, mandatory, tier
columns). The next migration author should expect to stack on top of this one.

Reversible: downgrade drops both columns. SQLite needs batch_alter_table for
the column ops; PG gets the same DDL.

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-06-14
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, None] = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def _has_column(bind, table: str, column: str) -> bool:
    insp = sa.inspect(bind)
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()

    if not _has_column(bind, "proposals", "budget_config"):
        with op.batch_alter_table("proposals", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column("budget_config", sa.JSON(), nullable=True),
            )

    if not _has_column(bind, "proposal_options", "budget_max_amount"):
        with op.batch_alter_table("proposal_options", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column("budget_max_amount", sa.Float(), nullable=True),
            )


def downgrade() -> None:
    bind = op.get_bind()

    if _has_column(bind, "proposal_options", "budget_max_amount"):
        with op.batch_alter_table("proposal_options", schema=None) as batch_op:
            batch_op.drop_column("budget_max_amount")

    if _has_column(bind, "proposals", "budget_config"):
        with op.batch_alter_table("proposals", schema=None) as batch_op:
            batch_op.drop_column("budget_config")
