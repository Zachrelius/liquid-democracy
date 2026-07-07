"""phase 90b — share_events.from_resulting_balance column

One nullable Integer column carrying the SENDER's balance after a transfer
(serialized only to the sender). NULL for admin_set / auto_distribution.

Hex-prefix revision id. Reversible.

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-07-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "d0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _cols(table: str) -> set[str]:
    try:
        return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}
    except Exception:
        return set()


def upgrade() -> None:
    if "from_resulting_balance" not in _cols("share_events"):
        with op.batch_alter_table("share_events") as batch:
            batch.add_column(sa.Column("from_resulting_balance", sa.Integer(), nullable=True))


def downgrade() -> None:
    if "from_resulting_balance" in _cols("share_events"):
        with op.batch_alter_table("share_events") as batch:
            batch.drop_column("from_resulting_balance")
