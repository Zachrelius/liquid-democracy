"""phase 56 — add nullable purpose + category columns to topics

Two additive nullable columns on ``topics``:

  * ``purpose`` (Text, nullable) — an optional one-line description of
    what a topic is for. Shown as a subtitle in topic-management and
    surfaced at topic-creation / proposal-creation pickers. Plain
    text (NOT markdown — XSS-safe by treating it as text on render).
  * ``category`` (String(80), nullable) — an optional free-text label
    used to group topics in the picker when an org opts into the
    ``settings.topic_categories_enabled`` toggle. No validation
    beyond length; orgs name their own categories. When the toggle
    is OFF, category values are RETAINED on the rows (toggling back
    on restores grouping).

Both columns default NULL on existing rows. No backfill is required:
the FE renders NULL purpose as "no purpose shown" and NULL category
as "Uncategorized" (only when grouping is enabled). This is the safe
case of the seed-path gotcha — additive nullable columns with
graceful NULL handling on both new and existing orgs, no seed-time
default that would diverge.

**Phase 33 guard** (spec B1, repeated for any future reader): Phase 33
DROPPED a same-value clone column ``Topic.description`` because the
Phase 30.1 root-cause fix made ``Topic.name`` the canonical display
name. This new ``purpose`` column is a DIFFERENT, genuinely-optional
field — it must NOT be wired into display-name fallback logic, must
NOT be renamed to ``description``, and must NOT resurrect the old
Phase-33 column. Keep ``name`` canonical.

Hex-prefix revision id (Phase 48 Stage 2 lesson). Reversible via
op.drop_column for both new columns.

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-06-05 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, None] = "a2b3c4d5e6f7"
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
    cols = _existing_columns("topics")
    if "purpose" not in cols:
        op.add_column("topics", sa.Column("purpose", sa.Text(), nullable=True))
    if "category" not in cols:
        op.add_column(
            "topics",
            sa.Column("category", sa.String(length=80), nullable=True),
        )


def downgrade() -> None:
    cols = _existing_columns("topics")
    if "category" in cols:
        op.drop_column("topics", "category")
    if "purpose" in cols:
        op.drop_column("topics", "purpose")
