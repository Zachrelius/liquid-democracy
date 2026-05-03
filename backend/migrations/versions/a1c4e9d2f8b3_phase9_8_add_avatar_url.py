"""Phase 9.8: add `users.avatar_url` nullable String column.

Revision ID: a1c4e9d2f8b3
Revises: 373e1f066cc1
Create Date: 2026-05-02 12:00:00.000000

Adds a nullable ``avatar_url`` column on ``users`` that stores the relative
path under the static-files mount (e.g. ``/uploads/avatars/{user_id}/128.jpg``).
NULL means the user has not uploaded an avatar — the frontend renders the
initials-on-colored-background fallback in that case.

Idempotent introspect-and-skip pattern from Phase 8.6 b1ab5db / Phase 9.5
373e1f066cc1: every operation checks first for existing tables/columns so
that a partial earlier run (or a ``create_all``-then-``stamp`` deploy) does
not blow up on re-apply. Reversible: ``downgrade`` drops the column cleanly
on both PG and SQLite (the SQLite branch uses ``batch_alter_table`` to
trigger the table-rebuild dance Alembic needs there).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1c4e9d2f8b3'
down_revision: Union[str, None] = '373e1f066cc1'
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

    if 'users' not in set(inspector.get_table_names()):
        # Defensive: should never happen because down_revision implies the
        # users table is already established. If we somehow reach this
        # without users present, there's nothing to alter.
        return

    if not _has_column('users', 'avatar_url'):
        with op.batch_alter_table('users', schema=None) as batch_op:
            batch_op.add_column(
                sa.Column('avatar_url', sa.String(), nullable=True),
            )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        op.execute(
            "ALTER TABLE users DROP COLUMN IF EXISTS avatar_url CASCADE"
        )
    else:
        with op.batch_alter_table('users', schema=None) as batch_op:
            batch_op.drop_column('avatar_url')
