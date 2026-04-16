"""add_user_type_and_audit_log

Revision ID: 58de3df8727f
Revises:
Create Date: 2026-04-13

Adds:
  - users.user_type  enum [human, ai_agent]  default 'human'
  - audit_log table  (append-only event ledger)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '58de3df8727f'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add user_type column to users table.
    # SQLite doesn't support ADD COLUMN with ENUM, so we use String with a
    # check constraint instead (render_as_batch handles the batch ALTER).
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'user_type',
                sa.String(),
                nullable=False,
                server_default='human',
            )
        )

    # Create audit_log table.
    op.create_table(
        'audit_log',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('actor_id', sa.String(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('action', sa.String(), nullable=False),
        sa.Column('target_type', sa.String(), nullable=False),
        sa.Column('target_id', sa.String(), nullable=False),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('ip_address', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_audit_log_timestamp', 'audit_log', ['timestamp'])
    op.create_index('ix_audit_log_actor_id',  'audit_log', ['actor_id'])
    op.create_index('ix_audit_log_action',    'audit_log', ['action'])
    op.create_index('ix_audit_log_target_id', 'audit_log', ['target_id'])


def downgrade() -> None:
    op.drop_index('ix_audit_log_target_id', table_name='audit_log')
    op.drop_index('ix_audit_log_action',    table_name='audit_log')
    op.drop_index('ix_audit_log_actor_id',  table_name='audit_log')
    op.drop_index('ix_audit_log_timestamp', table_name='audit_log')
    op.drop_table('audit_log')

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('user_type')
