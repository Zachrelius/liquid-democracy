"""phase 90d — share_events.authorization_ref column

Nullable string recording what authorized a ledger event beyond the direct
key-holder path: 'pending_action:<id>' for multi-admin ratified issuance (90d)
and 'proposal:<id>' for vote-authorized issuance (90e). NULL for direct/
admin_set/transfer/auto_distribution events.

Hex-prefix revision id. Reversible.

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-07-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a3b4c5d6e7f8"
down_revision: Union[str, None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _cols(table: str) -> set[str]:
    try:
        return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}
    except Exception:
        return set()


def upgrade() -> None:
    if "authorization_ref" not in _cols("share_events"):
        with op.batch_alter_table("share_events") as batch:
            batch.add_column(sa.Column("authorization_ref", sa.String(), nullable=True))


def downgrade() -> None:
    if "authorization_ref" in _cols("share_events"):
        with op.batch_alter_table("share_events") as batch:
            batch.drop_column("authorization_ref")
