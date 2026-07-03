"""phase 87 — org platform-restriction columns (takedown)

Adds four nullable columns to ``organizations`` for the platform-moderation
takedown state machine (B-10):
  * platform_restriction  (nullable string: NULL | 'delisted' | 'suspended')
  * restricted_at         (nullable datetime)
  * restricted_by_id      (nullable FK users, ondelete SET NULL)
  * restriction_reason    (nullable text, admin-facing only)

All nullable, no backfill (existing orgs are unrestricted = NULL). Enforcement
is read-time via org_restriction helpers; org settings are never overwritten.

Hex-prefix revision id. Reversible.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns(table: str) -> set[str]:
    bind = op.get_bind()
    try:
        return {c["name"] for c in sa.inspect(bind).get_columns(table)}
    except Exception:
        return set()


def upgrade() -> None:
    cols = _existing_columns("organizations")
    with op.batch_alter_table("organizations") as batch_op:
        if "platform_restriction" not in cols:
            batch_op.add_column(sa.Column("platform_restriction", sa.String(length=16), nullable=True))
        if "restricted_at" not in cols:
            batch_op.add_column(sa.Column("restricted_at", sa.DateTime(), nullable=True))
        if "restricted_by_id" not in cols:
            batch_op.add_column(sa.Column("restricted_by_id", sa.String(), nullable=True))
        if "restriction_reason" not in cols:
            batch_op.add_column(sa.Column("restriction_reason", sa.Text(), nullable=True))
    if "platform_restriction" not in cols:
        op.create_index(
            "ix_organizations_platform_restriction",
            "organizations",
            ["platform_restriction"],
        )


def downgrade() -> None:
    cols = _existing_columns("organizations")
    if "platform_restriction" in cols:
        op.drop_index("ix_organizations_platform_restriction", table_name="organizations")
    with op.batch_alter_table("organizations") as batch_op:
        if "restriction_reason" in cols:
            batch_op.drop_column("restriction_reason")
        if "restricted_by_id" in cols:
            batch_op.drop_column("restricted_by_id")
        if "restricted_at" in cols:
            batch_op.drop_column("restricted_at")
        if "platform_restriction" in cols:
            batch_op.drop_column("platform_restriction")
