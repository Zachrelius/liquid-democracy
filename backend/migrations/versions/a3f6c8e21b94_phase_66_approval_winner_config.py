"""phase 66 approval winner config

Adds ``proposals.approval_winner_config`` (JSON, nullable) — the
generalized multi-winner approval selection config (Phase 66 D1):
``{min_winners, max_winners, approval_threshold}``. NULL = legacy
single-winner behavior, byte-for-byte (additive-layer invariant), so no
backfill step is needed and every existing row keeps today's tally.

Idempotency guard mirrors the Phase 65 pattern (e7a9c4d2b8f1):
pg_smoke's ``upgrade`` mode runs ``create_all`` (which already builds
the post-Phase-66 column from models.py) BEFORE ``alembic stamp <prior>``
+ ``upgrade head``, so a naive ``op.add_column`` would collide. Pre-
inspect, no-op if present.

Revision ID: a3f6c8e21b94
Revises: e7a9c4d2b8f1
Create Date: 2026-06-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3f6c8e21b94'
down_revision: Union[str, None] = 'e7a9c4d2b8f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _proposals_columns() -> set[str]:
    """Return the set of column names currently present on ``proposals``."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return {c["name"] for c in insp.get_columns("proposals")}


def upgrade() -> None:
    if "approval_winner_config" not in _proposals_columns():
        op.add_column(
            "proposals",
            sa.Column("approval_winner_config", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    if "approval_winner_config" in _proposals_columns():
        op.drop_column("proposals", "approval_winner_config")
