"""add_delegation_strategy_and_topic_relevance

Revision ID: a23af9c11dcb
Revises: 58de3df8727f
Create Date: 2026-04-13

Adds:
  - users.delegation_strategy  string  default 'strict_precedence'
  - proposal_topics.relevance  float   default 1.0
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a23af9c11dcb'
down_revision: Union[str, None] = '58de3df8727f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('delegation_strategy', sa.String(), nullable=False, server_default='strict_precedence')
        )

    with op.batch_alter_table('proposal_topics', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('relevance', sa.Float(), nullable=False, server_default='1.0')
        )


def downgrade() -> None:
    with op.batch_alter_table('proposal_topics', schema=None) as batch_op:
        batch_op.drop_column('relevance')

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('delegation_strategy')
