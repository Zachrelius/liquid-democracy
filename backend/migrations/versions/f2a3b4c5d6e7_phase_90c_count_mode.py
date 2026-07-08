"""phase 90c — proposals.count_mode column

Nullable string: 'weighted' | 'one_per_member' | NULL (org default). Only
meaningful in weighted orgs.

Hex-prefix revision id. Reversible.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-07-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _cols(table: str) -> set[str]:
    try:
        return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}
    except Exception:
        return set()


def upgrade() -> None:
    if "count_mode" not in _cols("proposals"):
        with op.batch_alter_table("proposals") as batch:
            batch.add_column(sa.Column("count_mode", sa.String(), nullable=True))


def downgrade() -> None:
    if "count_mode" in _cols("proposals"):
        with op.batch_alter_table("proposals") as batch:
            batch.drop_column("count_mode")
