"""Phase 8: sustained-majority — Proposal.sustained_majority_enabled column +
proposal_status enum 'unresolved'.

Revision ID: c5f3a2b81e07
Revises: 3b89f18aceda
Create Date: 2026-04-28 09:00:00.000000

The new `sustained_majority_enabled` column is nullable (three-state: null=
inherit org default, true/false = explicit per-proposal override). The status
enum gains `unresolved` which is only reachable when failure_mode == "escalate"
and the floor was breached during the voting window.

PostgreSQL: native enum types require ALTER TYPE ... ADD VALUE to extend.
SQLite: Enum is a CHECK constraint that batch_alter_table rebuilds; the column
re-add via batch covers it. Both paths are guarded by a dialect check.

Downgrade: `unresolved` proposals are coerced to `failed` before the enum value
is dropped (Postgres requires no rows to reference the value being removed).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c5f3a2b81e07'
down_revision: Union[str, None] = '3b89f18aceda'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # 1. Extend the proposal_status enum with `unresolved`.
    if dialect == "postgresql":
        # ALTER TYPE ... ADD VALUE cannot run inside a transaction block in
        # older Postgres; in modern (>= 12) versions it works inside a tx, and
        # alembic wraps each migration in a tx. Use IF NOT EXISTS for idempotency
        # in case the migration is re-run after a partial failure.
        op.execute("ALTER TYPE proposal_status ADD VALUE IF NOT EXISTS 'unresolved'")

    # 2. Add the nullable boolean override column.
    with op.batch_alter_table('proposals', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('sustained_majority_enabled', sa.Boolean(), nullable=True)
        )

    # 3. Add multi_option_winners JSON column to vote_snapshots so the worker
    # can record the live winner set per snapshot for stable-result tracking.
    # Null for binary; object {"winners": [...], "total_ballots_cast": N} for
    # approval / ranked_choice.
    with op.batch_alter_table('vote_snapshots', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('multi_option_winners', sa.JSON(), nullable=True)
        )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # 1. Coerce any `unresolved` proposals to `failed` so the enum value can go.
    op.execute(
        "UPDATE proposals SET status = 'failed' WHERE status = 'unresolved'"
    )

    # 2. Drop the columns.
    with op.batch_alter_table('vote_snapshots', schema=None) as batch_op:
        batch_op.drop_column('multi_option_winners')
    with op.batch_alter_table('proposals', schema=None) as batch_op:
        batch_op.drop_column('sustained_majority_enabled')

    # 3. On Postgres, rebuild the enum without `unresolved`. SQLite uses a
    # check constraint that batch_alter_table re-creates implicitly when the
    # ORM metadata next regenerates — nothing further required.
    if dialect == "postgresql":
        # Postgres can't drop a single enum value; recreate the type.
        op.execute("ALTER TYPE proposal_status RENAME TO proposal_status_old")
        op.execute(
            "CREATE TYPE proposal_status AS ENUM "
            "('draft', 'deliberation', 'voting', 'passed', 'failed', 'withdrawn')"
        )
        op.execute(
            "ALTER TABLE proposals "
            "ALTER COLUMN status TYPE proposal_status "
            "USING status::text::proposal_status"
        )
        op.execute("DROP TYPE proposal_status_old")
