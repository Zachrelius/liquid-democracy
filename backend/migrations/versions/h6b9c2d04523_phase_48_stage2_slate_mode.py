"""phase 48 stage 2 — election slate mode column

Adds ``proposals.election_slate_mode`` per D10. Two values:
  * ``fill_vacancies`` (default): winners are added to current holders.
  * ``refresh_slate``: winners REPLACE all current holders of the
    target title before being installed (whole-slate refresh).

Default + server_default 'fill_vacancies' so non-election proposals +
existing Stage 1 elections are unchanged.

Revision ID: h6b9c2d04523
Revises: g5a8b1c93412
Create Date: 2026-06-01 07:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h6b9c2d04523"
down_revision: Union[str, None] = "g5a8b1c93412"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns(table: str) -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        return {c["name"] for c in insp.get_columns(table)}
    except Exception:
        return set()


def upgrade() -> None:
    cols = _existing_columns("proposals")
    if "election_slate_mode" not in cols:
        # Add via batch for dialect parity with Stage 1's migration.
        with op.batch_alter_table("proposals") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "election_slate_mode",
                    sa.String(length=16),
                    nullable=False,
                    server_default="fill_vacancies",
                ),
            )


def downgrade() -> None:
    cols = _existing_columns("proposals")
    if "election_slate_mode" in cols:
        with op.batch_alter_table("proposals") as batch_op:
            batch_op.drop_column("election_slate_mode")
