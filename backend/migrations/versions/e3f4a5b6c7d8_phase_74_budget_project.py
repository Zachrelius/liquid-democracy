"""phase 74 — budget project (Mode B) discrete-item columns

Extends ``proposal_options`` (Phase 73 added ``budget_max_amount``) with the
discrete project-item cost metadata for Mode B:

  * budget_floor_amount  (Float)   — the all-or-nothing cost (funded at this/$0)
  * budget_kind          (String)  — discrete | continuous-as-discrete | tier_parent
  * budget_is_mandatory  (Boolean) — fund off-the-top before the ranked walk (74a)
  * budget_tier_parent_id(String)  — FK→proposal_options.id on tier children (74b)
  * tier_allow_fallback  (Boolean) — tier fall-back toggle (74b)

All nullable, no server default — pure additive layer (NULL on every existing
option = byte-for-byte unchanged). Project mode reuses ``proposals.budget_config``
(added in 73) with ``mode == "project"``; no new ``proposals`` column.

Stage-74 core reads only budget_floor_amount + budget_kind; the mandatory/tier
columns are added now (one migration) so 74a/74b don't need their own.

Reversible. SQLite needs batch_alter_table for the column ops; PG gets the same.

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-06-14
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, None] = "d2e3f4a5b6c7"
branch_labels = None
depends_on = None

_COLUMNS = [
    ("budget_floor_amount", sa.Float()),
    ("budget_kind", sa.String()),
    ("budget_is_mandatory", sa.Boolean()),
    ("budget_tier_parent_id", sa.String()),
    ("tier_allow_fallback", sa.Boolean()),
]


def _existing(bind) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns("proposal_options")}


def upgrade() -> None:
    bind = op.get_bind()
    have = _existing(bind)
    with op.batch_alter_table("proposal_options", schema=None) as batch_op:
        for name, coltype in _COLUMNS:
            if name not in have:
                batch_op.add_column(sa.Column(name, coltype, nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    have = _existing(bind)
    with op.batch_alter_table("proposal_options", schema=None) as batch_op:
        for name, _coltype in reversed(_COLUMNS):
            if name in have:
                batch_op.drop_column(name)
