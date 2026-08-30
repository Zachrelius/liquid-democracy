"""phase 105 — proposal shared-residency policy metadata

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
Create Date: 2026-08-30 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f8a9b0c1d2e3"
down_revision: Union[str, None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {row["name"] for row in sa.inspect(bind).get_columns("proposals")}
    if "verification_require_residency" not in columns:
        op.add_column(
            "proposals",
            sa.Column("verification_require_residency", sa.Boolean(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {row["name"] for row in sa.inspect(bind).get_columns("proposals")}
    if "verification_require_residency" in columns:
        op.drop_column("proposals", "verification_require_residency")
