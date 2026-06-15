"""phase 74a — drop dead proposal_options.budget_is_mandatory column

The mandatory-minimum budget feature was CUT in the Phase 74 follow-up (Z's
call: orgs fund must-funds outside the vote and run the discretionary remainder
as the envelope). The column was added as a forward-compat placeholder by the
Stage-74-core migration (e3f4a5b6c7d8) but is never read or written, so it's
dead schema. This drops it while nothing depends on it.

Pure cleanup, zero behavior change (the core tally never referenced it).
Reversible: downgrade re-adds it nullable.

Revision ID: a5b6c7d8e9f0
Revises: f4a5b6c7d8e9
Create Date: 2026-06-15
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "a5b6c7d8e9f0"
down_revision: Union[str, None] = "f4a5b6c7d8e9"
branch_labels = None
depends_on = None


def _has_column(bind, table: str, column: str) -> bool:
    return column in {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind, "proposal_options", "budget_is_mandatory"):
        with op.batch_alter_table("proposal_options", schema=None) as batch_op:
            batch_op.drop_column("budget_is_mandatory")


def downgrade() -> None:
    bind = op.get_bind()
    if not _has_column(bind, "proposal_options", "budget_is_mandatory"):
        with op.batch_alter_table("proposal_options", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column("budget_is_mandatory", sa.Boolean(), nullable=True),
            )
