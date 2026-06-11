"""phase 65 topic allow_delegation

Adds ``topics.allow_delegation`` (Boolean, NOT NULL, server_default true)
— the per-topic delegation disallow flag (Phase 65 D3). ``server_default
true`` backfills every existing topic row at the SQL layer so existing
orgs keep today's behavior (delegation allowed everywhere) with no data
backfill step. The org-wide master switch is a read-time-defaulted
settings key (``settings.delegation.enabled``) and needs no migration.

Idempotency guard mirrors the Phase 39 pattern (4b0bf8f1761f):
pg_smoke's ``upgrade`` mode runs ``create_all`` (which already builds
the post-Phase-65 column from models.py) BEFORE ``alembic stamp <prior>``
+ ``upgrade head``, so a naive ``op.add_column`` would collide. Pre-
inspect, no-op if present.

Revision ID: e7a9c4d2b8f1
Revises: d1e2f3a4b5c6
Create Date: 2026-06-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7a9c4d2b8f1'
down_revision: Union[str, None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _topics_columns() -> set[str]:
    """Return the set of column names currently present on ``topics``."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return {c["name"] for c in insp.get_columns("topics")}


def upgrade() -> None:
    if "allow_delegation" not in _topics_columns():
        op.add_column(
            "topics",
            sa.Column(
                "allow_delegation",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
        )


def downgrade() -> None:
    if "allow_delegation" in _topics_columns():
        op.drop_column("topics", "allow_delegation")
