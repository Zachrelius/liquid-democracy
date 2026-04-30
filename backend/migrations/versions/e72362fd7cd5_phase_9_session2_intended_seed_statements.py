"""Phase 9 Session 2: add `polises.intended_seed_statements` JSON column.

Revision ID: e72362fd7cd5
Revises: e7b3f9a02c14
Create Date: 2026-04-29 16:00:00.000000

The new column stores the operator-entered seed statements at create-Polis
time. Source of truth for `polis_service.add_seed_statements()` when
`POLIS_AUTH_TOKEN` is configured (programmatic path); reference list for the
"paste these into the pol.is admin UI" UX when it isn't (manual-fallback
path). Both flows preserve the operator's intent platform-side.

Idempotent introspect-and-skip pattern from `e7b3f9a02c14` /
Phase 8.6 hot-fix `b1ab5db`. Reversible. SQLite uses batch_alter_table for
nullable JSON additions; PG uses plain ALTER TABLE ADD COLUMN.

Existing data unaffected — every existing `polises` row has NULL in the
new column, which `polis_service` and routes treat as "no seed statements
recorded" (semantically equivalent to an empty list).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e72362fd7cd5'
down_revision: Union[str, None] = 'e7b3f9a02c14'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    def _has_column(table: str, column: str) -> bool:
        try:
            return column in {c['name'] for c in inspector.get_columns(table)}
        except Exception:
            return False

    if 'polises' not in set(inspector.get_table_names()):
        # Defensive: should never happen because down_revision is the
        # Phase 9 Session 1 migration that creates `polises`, but if a
        # partial-state DB ran create_all before this revision the table
        # exists already; if it doesn't, there's nothing to alter.
        return

    if not _has_column('polises', 'intended_seed_statements'):
        with op.batch_alter_table('polises', schema=None) as batch_op:
            batch_op.add_column(
                sa.Column('intended_seed_statements', sa.JSON(), nullable=True),
            )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        op.execute(
            "ALTER TABLE polises DROP COLUMN IF EXISTS "
            "intended_seed_statements CASCADE"
        )
    else:
        with op.batch_alter_table('polises', schema=None) as batch_op:
            batch_op.drop_column('intended_seed_statements')
