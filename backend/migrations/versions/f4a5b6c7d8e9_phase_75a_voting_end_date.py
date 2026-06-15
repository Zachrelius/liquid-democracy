"""phase 75a — absolute voting end date

Adds ``proposals.voting_end_date`` (DateTime, nullable). NULL = use voting_days
or the org default (today's behavior); set = an absolute deadline that wins
over voting_days at advance time. Pure additive layer — no backfill (every
existing proposal is NULL, which falls through to the existing chain).

Reversible: downgrade drops the column.

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-06-14
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "f4a5b6c7d8e9"
down_revision: Union[str, None] = "e3f4a5b6c7d8"
branch_labels = None
depends_on = None


def _has_column(bind, table: str, column: str) -> bool:
    return column in {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_column(bind, "proposals", "voting_end_date"):
        with op.batch_alter_table("proposals", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column("voting_end_date", sa.DateTime(), nullable=True),
            )


def downgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind, "proposals", "voting_end_date"):
        with op.batch_alter_table("proposals", schema=None) as batch_op:
            batch_op.drop_column("voting_end_date")
