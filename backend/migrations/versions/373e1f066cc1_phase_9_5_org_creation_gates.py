"""Phase 9.5: org-creation gates — `users.org_creation_limit` column +
`platform_settings` table (seeded with `org_creation_mode='open'`).

Revision ID: 373e1f066cc1
Revises: e72362fd7cd5
Create Date: 2026-04-30 00:00:00.000000

Closes the spam/cap/kill-switch gap on `POST /api/orgs`. Two purely additive
schema changes:

  1. `users.org_creation_limit`  Integer, nullable. NULL = use platform
     default (3). A non-null override raises (or lowers) the per-user cap.
  2. `platform_settings`         (key TEXT PK, value JSON, updated_at).
     Single source of truth for platform-wide config. Seeded with the row
     `('org_creation_mode', 'open', now())` so existing prod containers come
     up in the correct default mode without any further intervention.

Idempotent introspect-and-skip pattern from Phase 8.6 b1ab5db / Phase 9
sessions: every operation checks first for existing tables/columns so that
a partial earlier run (or a `create_all`-then-`stamp` deploy) does not blow
up on re-apply. Reversible: downgrade drops the column and table cleanly.
SQLite uses batch_alter_table for the ALTER; PG gets plain ALTER TABLE.
"""
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '373e1f066cc1'
down_revision: Union[str, None] = 'e72362fd7cd5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    def _has_column(table: str, column: str) -> bool:
        try:
            return column in {c['name'] for c in inspector.get_columns(table)}
        except Exception:
            return False

    # 1. users.org_creation_limit  nullable Integer, no FK, no index needed
    #    (read on every POST /api/orgs but as part of the already-fetched
    #    current_user row, not a separate query).
    if not _has_column('users', 'org_creation_limit'):
        with op.batch_alter_table('users', schema=None) as batch_op:
            batch_op.add_column(
                sa.Column('org_creation_limit', sa.Integer(), nullable=True),
            )

    # 2. platform_settings table
    if 'platform_settings' not in existing_tables:
        op.create_table(
            'platform_settings',
            sa.Column('key', sa.String(length=100), nullable=False),
            sa.Column('value', sa.JSON(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('key'),
        )

    # 3. Seed `org_creation_mode='open'` if not already present. Use a raw
    #    SQL upsert pattern that's safe across PG and SQLite (we just check
    #    first then INSERT). This is idempotent so re-running the migration
    #    on a partial state never duplicates.
    settings_table = sa.table(
        'platform_settings',
        sa.column('key', sa.String),
        sa.column('value', sa.JSON),
        sa.column('updated_at', sa.DateTime),
    )
    existing = bind.execute(
        sa.text("SELECT 1 FROM platform_settings WHERE key = :k"),
        {"k": "org_creation_mode"},
    ).first()
    if not existing:
        bind.execute(
            settings_table.insert().values(
                key='org_creation_mode',
                value='open',
                updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # Drop the platform_settings table first (its rows go with it).
    if dialect == "postgresql":
        op.execute("DROP TABLE IF EXISTS platform_settings CASCADE")
    else:
        op.drop_table('platform_settings')

    # Drop users.org_creation_limit. Same name-agnostic pattern as Phase 8.5.
    if dialect == "postgresql":
        op.execute(
            "ALTER TABLE users DROP COLUMN IF EXISTS org_creation_limit CASCADE"
        )
    else:
        with op.batch_alter_table('users', schema=None) as batch_op:
            batch_op.drop_column('org_creation_limit')
