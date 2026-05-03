"""Phase 10: add ``comments`` table.

Revision ID: b2d5f1a3c7e4
Revises: a1c4e9d2f8b3
Create Date: 2026-05-02 14:00:00.000000

Adds the proposal-comments table for Phase 10's engagement layer:

  - ``proposal_id`` / ``author_id`` are FK CASCADE so deleting a proposal or
    user takes their comments with it (matches the existing privacy /
    cleanup posture).
  - ``parent_comment_id`` is nullable; non-null = reply (the route layer
    enforces "must point at a top-level comment").
  - ``body`` is sanitized markdown source (sanitization happens at the route
    layer via ``schemas._sanitize_markdown``).
  - ``deleted_at`` is the soft-delete sentinel — the row stays so reply
    children still render correctly.

Idempotent introspect-and-skip pattern from Phase 8.6 b1ab5db / Phase 9.5
373e1f066cc1 / Phase 9.8 a1c4e9d2f8b3 — re-running the upgrade after a
partial earlier run (or a ``create_all``-then-``stamp`` deploy) is safe.
Reversible: ``downgrade`` drops the table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2d5f1a3c7e4'
down_revision: Union[str, None] = 'a1c4e9d2f8b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_tables = set(inspector.get_table_names())
    if 'comments' in existing_tables:
        # Table already present (probably from create_all on a fresh DB
        # followed by `alembic stamp head`). Nothing to do — the SQLAlchemy
        # model is the source of truth for column shape in that case.
        return

    op.create_table(
        'comments',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column(
            'proposal_id', sa.String(),
            sa.ForeignKey('proposals.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'author_id', sa.String(),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'parent_comment_id', sa.String(),
            sa.ForeignKey('comments.id', ondelete='CASCADE'),
            nullable=True,
        ),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
    )

    # Indices on the FK columns (matches the model's `index=True`).
    op.create_index(
        'ix_comments_proposal_id', 'comments', ['proposal_id'], unique=False,
    )
    op.create_index(
        'ix_comments_author_id', 'comments', ['author_id'], unique=False,
    )
    op.create_index(
        'ix_comments_parent_comment_id', 'comments', ['parent_comment_id'],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if 'comments' not in set(inspector.get_table_names()):
        return

    # Drop indices first (no-op on PG when dropping the table cascades them
    # but explicit is clearer for SQLite where Alembic emits separate DDL).
    for ix in (
        'ix_comments_parent_comment_id',
        'ix_comments_author_id',
        'ix_comments_proposal_id',
    ):
        try:
            op.drop_index(ix, table_name='comments')
        except Exception:
            # Index may not exist if create failed mid-way. Press on.
            pass

    op.drop_table('comments')
