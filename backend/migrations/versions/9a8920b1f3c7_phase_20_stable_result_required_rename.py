"""Phase 20: rename Proposal.sustained_majority_enabled -> stable_result_required.

Revision ID: 9a8920b1f3c7
Revises: 47eb5d38eb58
Create Date: 2026-05-10 14:00:00.000000

What this does
--------------

The Phase 20 spec (``phase20_stable_result_required_spec.md`` §B1, D12)
renames the per-proposal sustained-majority override column to align
with the user-facing rebrand: "Stable Result Required."

The column's nullability and type are unchanged (Boolean, nullable).
Existing values (``NULL`` / ``True`` / ``False``) flow through the
rename untouched — semantically equivalent because the unified mechanic
behaves identically whether the proposal is opted-in via the legacy
"sustained_majority" surface or the new "stable_result" surface.

Notes / risks
-------------

- **SQLite + PG compatible.** ``op.alter_column(..., new_column_name=...)``
  is the standard alembic API for a pure rename; alembic emits
  ``ALTER TABLE ... RENAME COLUMN`` on Postgres and uses batch_alter_table
  (table rebuild) on SQLite. We avoid ``batch_alter_table`` here because
  PG handles it natively and Phase 19's incident showed that batch is
  the riskier path on PG (the ``CREATE TYPE`` autogeneration leaks into
  batch operations on enum-bearing tables).
- **No data migration required.** The column's stored values map 1:1
  through the rename.
- **No new tables, no new columns.** All new config knobs live in the
  ``Organization.settings`` JSON blob, which doesn't require schema
  migration.

Downgrade reverses the rename — same alembic primitive in reverse.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '9a8920b1f3c7'
down_revision: Union[str, None] = '47eb5d38eb58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _proposals_columns(bind) -> set[str]:
    inspector = sa.inspect(bind)
    return {c["name"] for c in inspector.get_columns("proposals")}


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # Defensive idempotent check (Phase 19 lesson — pg_smoke + SQLite migration-
    # cycle tests bootstrap via Base.metadata.create_all which builds today's
    # schema. The new column name (`stable_result_required`) is already in
    # models.py, so create_all-bootstrapped DBs already have the new name and
    # NOT the old one — `op.alter_column` with the old name as source raises
    # KeyError on SQLite batch_alter_table OR UndefinedColumn on PG. This
    # pre-check makes the migration a no-op when the schema is already at the
    # post-rename shape, which is the case for every test fixture and for the
    # actual-upgrade gate. Real prod still has the old column name and the
    # rename runs normally.
    cols = _proposals_columns(bind)
    if "stable_result_required" in cols:
        # Already renamed (or create_all-bootstrapped at the new shape).
        return
    if "sustained_majority_enabled" not in cols:
        raise RuntimeError(
            "Phase 20 migration: proposals table has neither "
            "'sustained_majority_enabled' nor 'stable_result_required'; "
            "cannot rename."
        )

    if dialect == "sqlite":
        # SQLite cannot rename a column with a bare ALTER TABLE in older
        # SQLite versions; use batch_alter_table for the table-rebuild path.
        # No enum types involved here, so the Phase 19 risk doesn't apply.
        with op.batch_alter_table('proposals', schema=None) as batch_op:
            batch_op.alter_column(
                'sustained_majority_enabled',
                new_column_name='stable_result_required',
                existing_type=sa.Boolean(),
                existing_nullable=True,
            )
    else:
        # Postgres handles RENAME COLUMN natively without a table rebuild.
        op.alter_column(
            'proposals',
            'sustained_majority_enabled',
            new_column_name='stable_result_required',
            existing_type=sa.Boolean(),
            existing_nullable=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # Mirror of upgrade's idempotent check.
    cols = _proposals_columns(bind)
    if "sustained_majority_enabled" in cols:
        # Already downgraded.
        return
    if "stable_result_required" not in cols:
        raise RuntimeError(
            "Phase 20 downgrade: proposals table has neither column; "
            "cannot rename back."
        )

    if dialect == "sqlite":
        with op.batch_alter_table('proposals', schema=None) as batch_op:
            batch_op.alter_column(
                'stable_result_required',
                new_column_name='sustained_majority_enabled',
                existing_type=sa.Boolean(),
                existing_nullable=True,
            )
    else:
        op.alter_column(
            'proposals',
            'stable_result_required',
            new_column_name='sustained_majority_enabled',
            existing_type=sa.Boolean(),
            existing_nullable=True,
        )
