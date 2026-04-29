"""Phase 8.5: sub-organizations — Organization.parent_org_id, sub_org_memberships
table, and sub_org_id columns on Topic / Proposal / DelegateProfile.

Revision ID: d41a8c92f3b1
Revises: c5f3a2b81e07
Create Date: 2026-04-29 12:00:00.000000

Schema additions are purely additive — every new column is nullable and every
existing row remains untouched. Single-org installations keep bit-for-bit
behavior because every new column reads NULL after upgrade (NULL = parent-org-
wide / unscoped, the existing semantic).

Dialect notes:
  - SQLite: batch_alter_table is required to add foreign-key columns; the
    self-referential FK on organizations works fine inside a batch.
  - PostgreSQL: simple ADD COLUMN ... REFERENCES organizations(id); no enum
    rebuilds needed (no enum types touched).

Downgrade drops the new column / table cleanly. Because all rows have NULL in
the new columns, no data coercion is required (unlike Phase 8's enum-value
removal).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd41a8c92f3b1'
down_revision: Union[str, None] = 'c5f3a2b81e07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Hot-fix path: start.sh runs SQLAlchemy create_tables() BEFORE alembic
    # upgrade. On an existing prod DB getting Phase 8.5 for the first time,
    # create_tables sees the new SubOrgMembership model class and creates
    # the sub_org_memberships table directly. Then this migration runs and
    # would fail trying to op.create_table the same table again.
    # Existing-table-add-column ops are not affected (create_tables only
    # creates missing tables; it doesn't sync columns on existing ones),
    # but we defensive-skip those too in case a partial earlier run left
    # them in place.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    def _has_column(table: str, column: str) -> bool:
        try:
            return column in {c['name'] for c in inspector.get_columns(table)}
        except Exception:
            return False

    # 1. Organization.parent_org_id (nullable, self-referential FK, indexed).
    if not _has_column('organizations', 'parent_org_id'):
        with op.batch_alter_table('organizations', schema=None) as batch_op:
            batch_op.add_column(
                sa.Column('parent_org_id', sa.String(), nullable=True)
            )
            batch_op.create_foreign_key(
                'fk_organizations_parent_org_id',
                'organizations', ['parent_org_id'], ['id'],
            )
            batch_op.create_index(
                'ix_organizations_parent_org_id', ['parent_org_id'], unique=False,
            )

    # 2. New table sub_org_memberships (parallel to org_memberships).
    if 'sub_org_memberships' not in existing_tables:
        op.create_table(
            'sub_org_memberships',
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('user_id', sa.String(), nullable=False),
            sa.Column('sub_org_id', sa.String(), nullable=False),
            sa.Column('role', sa.String(), nullable=False, server_default='member'),
            sa.Column('status', sa.String(), nullable=False, server_default='active'),
            sa.Column('joined_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.ForeignKeyConstraint(['sub_org_id'], ['organizations.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id', 'sub_org_id', name='uq_sub_org_membership_user_sub_org'),
        )
        op.create_index(
            'ix_sub_org_memberships_user_id', 'sub_org_memberships', ['user_id'], unique=False,
        )
        op.create_index(
            'ix_sub_org_memberships_sub_org_id', 'sub_org_memberships', ['sub_org_id'], unique=False,
        )

    # 3. Topic.sub_org_id
    if not _has_column('topics', 'sub_org_id'):
        with op.batch_alter_table('topics', schema=None) as batch_op:
            batch_op.add_column(sa.Column('sub_org_id', sa.String(), nullable=True))
            batch_op.create_foreign_key(
                'fk_topics_sub_org_id', 'organizations', ['sub_org_id'], ['id'],
            )
            batch_op.create_index(
                'ix_topics_sub_org_id', ['sub_org_id'], unique=False,
            )

    # 4. Proposal.sub_org_id
    if not _has_column('proposals', 'sub_org_id'):
        with op.batch_alter_table('proposals', schema=None) as batch_op:
            batch_op.add_column(sa.Column('sub_org_id', sa.String(), nullable=True))
            batch_op.create_foreign_key(
                'fk_proposals_sub_org_id', 'organizations', ['sub_org_id'], ['id'],
            )
            batch_op.create_index(
                'ix_proposals_sub_org_id', ['sub_org_id'], unique=False,
            )

    # 5. DelegateProfile.sub_org_id
    if not _has_column('delegate_profiles', 'sub_org_id'):
        with op.batch_alter_table('delegate_profiles', schema=None) as batch_op:
            batch_op.add_column(sa.Column('sub_org_id', sa.String(), nullable=True))
            batch_op.create_foreign_key(
                'fk_delegate_profiles_sub_org_id', 'organizations', ['sub_org_id'], ['id'],
            )
            batch_op.create_index(
                'ix_delegate_profiles_sub_org_id', ['sub_org_id'], unique=False,
            )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # On PostgreSQL, dropping a column auto-drops its FK constraint and any
    # index that references only that column. On SQLite, batch_alter_table
    # rebuilds the whole table so FK constraints / indexes go with it.
    # We therefore avoid drop_constraint by name — the migration's create_*
    # name only matches when the migration created the constraint, but
    # production DBs that came up via create_tables() + alembic stamp use
    # SQLAlchemy's auto-generated names (<table>_<col>_fkey). Letting the
    # column drop cascade keeps the downgrade name-agnostic on both engines.

    # 5. DelegateProfile.sub_org_id
    if dialect == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_delegate_profiles_sub_org_id")
        op.execute(
            "ALTER TABLE delegate_profiles DROP COLUMN IF EXISTS sub_org_id CASCADE"
        )
    else:
        with op.batch_alter_table('delegate_profiles', schema=None) as batch_op:
            batch_op.drop_index('ix_delegate_profiles_sub_org_id')
            batch_op.drop_column('sub_org_id')

    # 4. Proposal.sub_org_id
    if dialect == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_proposals_sub_org_id")
        op.execute(
            "ALTER TABLE proposals DROP COLUMN IF EXISTS sub_org_id CASCADE"
        )
    else:
        with op.batch_alter_table('proposals', schema=None) as batch_op:
            batch_op.drop_index('ix_proposals_sub_org_id')
            batch_op.drop_column('sub_org_id')

    # 3. Topic.sub_org_id
    if dialect == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_topics_sub_org_id")
        op.execute(
            "ALTER TABLE topics DROP COLUMN IF EXISTS sub_org_id CASCADE"
        )
    else:
        with op.batch_alter_table('topics', schema=None) as batch_op:
            batch_op.drop_index('ix_topics_sub_org_id')
            batch_op.drop_column('sub_org_id')

    # 2. Drop sub_org_memberships (tables drop their own indexes / FKs).
    op.drop_table('sub_org_memberships')

    # 1. Organization.parent_org_id
    if dialect == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_organizations_parent_org_id")
        op.execute(
            "ALTER TABLE organizations DROP COLUMN IF EXISTS parent_org_id CASCADE"
        )
    else:
        with op.batch_alter_table('organizations', schema=None) as batch_op:
            batch_op.drop_index('ix_organizations_parent_org_id')
            batch_op.drop_column('parent_org_id')
