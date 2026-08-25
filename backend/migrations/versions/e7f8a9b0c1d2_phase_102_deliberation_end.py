"""phase 102 — durable proposal deliberation deadline

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-08-24 00:00:00.000000

Historical proposals that have already left active deliberation receive the
deadline derivable from their stored start + duration.  Active deliberation
rows deliberately remain NULL for the gated, org-aware reconciliation.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, None] = "d6e7f8a9b0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    column_names = {row["name"] for row in inspector.get_columns("proposals")}
    if "deliberation_end" not in column_names:
        op.add_column(
            "proposals",
            sa.Column("deliberation_end", sa.DateTime(), nullable=True),
        )
    index_names = {
        row["name"] for row in sa.inspect(bind).get_indexes("proposals")
    }
    if "ix_proposals_deliberation_end" not in index_names:
        op.create_index(
            "ix_proposals_deliberation_end",
            "proposals",
            ["deliberation_end"],
            unique=False,
        )
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text(
            "UPDATE proposals "
            "SET deliberation_end = deliberation_start "
            "+ (deliberation_days * INTERVAL '1 day') "
            "WHERE status <> 'deliberation' "
            "AND deliberation_start IS NOT NULL "
            "AND deliberation_days IS NOT NULL"
        ))
    else:
        # SQLite migration-cycle tests use julianday arithmetic.
        bind.execute(sa.text(
            "UPDATE proposals "
            "SET deliberation_end = datetime(deliberation_start, "
            "printf('%+f days', deliberation_days)) "
            "WHERE status <> 'deliberation' "
            "AND deliberation_start IS NOT NULL "
            "AND deliberation_days IS NOT NULL"
        ))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    index_names = {row["name"] for row in inspector.get_indexes("proposals")}
    if "ix_proposals_deliberation_end" in index_names:
        op.drop_index("ix_proposals_deliberation_end", table_name="proposals")
    column_names = {row["name"] for row in sa.inspect(bind).get_columns("proposals")}
    if "deliberation_end" in column_names:
        op.drop_column("proposals", "deliberation_end")
