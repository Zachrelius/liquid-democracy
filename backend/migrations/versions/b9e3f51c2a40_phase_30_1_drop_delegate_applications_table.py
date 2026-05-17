"""Phase 30.1 B4 — drop legacy delegate_applications table.

Revision ID: b9e3f51c2a40
Revises: a8c2d51e9f10
Create Date: 2026-05-16 18:35:00.000000

The Phase 19 DelegateProfile lifecycle (visibility transitions through
private / public / public_accepting + per-profile submit/approve/deny
state on the DP row itself) supersedes the legacy
``delegate_applications`` table. Phase 30.1 B4 removes the orphaned
backend routes + schemas + frontend page + model class; this migration
drops the table itself.

Downgrade recreates the table shape from models.py at the time of
Phase 4c (the last migration that referenced it). The old row content
is NOT preserved across the drop — per dispatch B4.1, prod had no
non-test consumers of this table.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b9e3f51c2a40"
down_revision = "a8c2d51e9f10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Conditional drop — the table may not exist on test DBs that built
    # the schema via ``Base.metadata.create_all`` AFTER Phase 30.1
    # removed the ``DelegateApplication`` model class. In production
    # (PG, which built the schema via earlier migrations when the model
    # was still present) the table exists and gets dropped here.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "delegate_applications" in inspector.get_table_names():
        op.drop_table("delegate_applications")


def downgrade() -> None:
    op.create_table(
        "delegate_applications",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(),
                  sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("org_id", sa.String(),
                  sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("topic_id", sa.String(),
                  sa.ForeignKey("topics.id"), nullable=False),
        sa.Column("bio", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False,
                  server_default="pending"),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.String(),
                  sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
    )
