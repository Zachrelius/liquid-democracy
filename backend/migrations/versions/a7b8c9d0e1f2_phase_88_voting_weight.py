"""phase 88 — OrgMembership.voting_weight column (weighted voting)

Adds a single non-null integer column ``voting_weight`` to ``org_memberships``
with ``server_default='1'`` so every existing membership row backfills to
weight 1 (no separate data migration needed). The column is only load-bearing
when an org sets ``settings.weighted_voting.enabled``; otherwise the tally
layer reads a uniform weight of 1 and all math reduces to headcount.

Integer is load-bearing: VoteSnapshot counters are Integer, so integer shares
keep weighted sums integral and the snapshot table needs no migration.

Hex-prefix revision id. Reversible.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-07-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns(table: str) -> set[str]:
    bind = op.get_bind()
    try:
        return {c["name"] for c in sa.inspect(bind).get_columns(table)}
    except Exception:
        return set()


def upgrade() -> None:
    cols = _existing_columns("org_memberships")
    if "voting_weight" not in cols:
        with op.batch_alter_table("org_memberships") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "voting_weight",
                    sa.Integer(),
                    nullable=False,
                    server_default="1",
                )
            )


def downgrade() -> None:
    cols = _existing_columns("org_memberships")
    if "voting_weight" in cols:
        with op.batch_alter_table("org_memberships") as batch_op:
            batch_op.drop_column("voting_weight")
