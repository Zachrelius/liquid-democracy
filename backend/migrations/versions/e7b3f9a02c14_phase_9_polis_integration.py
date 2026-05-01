"""Phase 9: pol.is integration data layer — `polises` and `polis_xids` tables,
plus `proposals.linked_polis_ids` JSON column for structurally-recorded
proposal -> Polis links.

Revision ID: e7b3f9a02c14
Revises: d41a8c92f3b1
Create Date: 2026-04-29 13:00:00.000000

Schema additions are purely additive — new tables get NULL on every existing
join, the new JSON column on `proposals` defaults to NULL, and no enum types
are touched. Existing single-org behavior is bit-for-bit unchanged because
nothing reads the new tables until an admin creates the first Polis.

Mirrors Phase 8.5 / 8.6's introspect-and-skip pattern:
  - SQLite: batch_alter_table for FK-bearing column additions; create_table
    for the two new tables.
  - PostgreSQL: simple ADD COLUMN ... REFERENCES; CREATE TABLE.
  - Idempotent against partial-state DBs (start.sh's create_tables() may have
    already created the new tables on a fresh prod-deploy bring-up; the
    migration must not collide).

Downgrade drops both new tables and the new column cleanly. Because every
existing row has NULL in `proposals.linked_polis_ids`, no data coercion is
needed (unlike Phase 8's enum-value cleanup).

Note on ``Organization.settings.require_polis_for_new_proposals``: that
config key is purely a JSON-key default resolved by ``get_org_config(...,
default=False)`` per Phase 8.5 Decision 9. No migration is required for the
key itself; new orgs created via routes/organizations.py with the updated
DEFAULT_ORG_SETTINGS will pick it up, and existing orgs read False via the
default until an admin opts in.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e7b3f9a02c14'
down_revision: Union[str, None] = 'd41a8c92f3b1'
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

    # 1. New `polises` table.
    if 'polises' not in existing_tables:
        op.create_table(
            'polises',
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('org_id', sa.String(), nullable=False),
            sa.Column('sub_org_id', sa.String(), nullable=True),
            sa.Column('polis_conversation_id', sa.String(length=64), nullable=True),
            sa.Column('title', sa.String(), nullable=False),
            sa.Column('prompt', sa.Text(), nullable=False),
            sa.Column('created_by', sa.String(), nullable=False),
            sa.Column(
                'status', sa.String(), nullable=False, server_default='active',
            ),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.Column('archived_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['org_id'], ['organizations.id']),
            sa.ForeignKeyConstraint(['sub_org_id'], ['organizations.id']),
            sa.ForeignKeyConstraint(['created_by'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(
            'ix_polises_org_id', 'polises', ['org_id'], unique=False,
        )
        op.create_index(
            'ix_polises_sub_org_id', 'polises', ['sub_org_id'], unique=False,
        )
        op.create_index(
            'ix_polises_polis_conversation_id', 'polises',
            ['polis_conversation_id'], unique=False,
        )
        op.create_index(
            'ix_polises_created_by', 'polises', ['created_by'], unique=False,
        )

    # 2. New `polis_xids` table.
    if 'polis_xids' not in existing_tables:
        op.create_table(
            'polis_xids',
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('user_id', sa.String(), nullable=False),
            sa.Column('org_id', sa.String(), nullable=False),
            sa.Column('polis_xid', sa.String(length=64), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.ForeignKeyConstraint(['org_id'], ['organizations.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint(
                'user_id', 'org_id', name='uq_polis_xid_user_org',
            ),
            sa.UniqueConstraint('polis_xid'),
        )
        op.create_index(
            'ix_polis_xids_user_id', 'polis_xids', ['user_id'], unique=False,
        )
        op.create_index(
            'ix_polis_xids_org_id', 'polis_xids', ['org_id'], unique=False,
        )

    # 3. proposals.linked_polis_ids — JSON, nullable, no FK (the IDs reference
    #    polises.id but we don't enforce this at the DB level; validation is
    #    at the API layer when authors set linked_polis_ids, mirroring how
    #    proposal.body URL-detection links don't carry FK constraints either).
    if not _has_column('proposals', 'linked_polis_ids'):
        with op.batch_alter_table('proposals', schema=None) as batch_op:
            batch_op.add_column(
                sa.Column('linked_polis_ids', sa.JSON(), nullable=True),
            )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # 3. Drop proposals.linked_polis_ids.
    if dialect == "postgresql":
        op.execute(
            "ALTER TABLE proposals DROP COLUMN IF EXISTS linked_polis_ids CASCADE"
        )
    else:
        with op.batch_alter_table('proposals', schema=None) as batch_op:
            batch_op.drop_column('linked_polis_ids')

    # 2. Drop polis_xids.
    if dialect == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_polis_xids_org_id")
        op.execute("DROP INDEX IF EXISTS ix_polis_xids_user_id")
        op.execute("DROP TABLE IF EXISTS polis_xids CASCADE")
    else:
        op.drop_table('polis_xids')

    # 1. Drop polises.
    if dialect == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_polises_created_by")
        op.execute("DROP INDEX IF EXISTS ix_polises_polis_conversation_id")
        op.execute("DROP INDEX IF EXISTS ix_polises_sub_org_id")
        op.execute("DROP INDEX IF EXISTS ix_polises_org_id")
        op.execute("DROP TABLE IF EXISTS polises CASCADE")
    else:
        op.drop_table('polises')
