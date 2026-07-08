"""phase 90e — issuance proposal columns

Adds three columns to ``proposals`` for vote-gated share issuance:
  * ``is_issuance``   BOOLEAN NOT NULL DEFAULT 0
  * ``issuance_payload`` JSON  NULL  ({action, params} snapshot)
  * ``issuance_executed`` BOOLEAN NULL (close-hook outcome; NULL until closed)

Hex-prefix revision id. Reversible.

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-07-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, None] = "a3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _cols(table: str) -> set[str]:
    try:
        return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}
    except Exception:
        return set()


def upgrade() -> None:
    cols = _cols("proposals")
    with op.batch_alter_table("proposals") as batch:
        if "is_issuance" not in cols:
            batch.add_column(sa.Column(
                "is_issuance", sa.Boolean(), nullable=False, server_default="0",
            ))
        if "issuance_payload" not in cols:
            batch.add_column(sa.Column("issuance_payload", sa.JSON(), nullable=True))
        if "issuance_executed" not in cols:
            batch.add_column(sa.Column("issuance_executed", sa.Boolean(), nullable=True))


def downgrade() -> None:
    cols = _cols("proposals")
    with op.batch_alter_table("proposals") as batch:
        if "issuance_executed" in cols:
            batch.drop_column("issuance_executed")
        if "issuance_payload" in cols:
            batch.drop_column("issuance_payload")
        if "is_issuance" in cols:
            batch.drop_column("is_issuance")
