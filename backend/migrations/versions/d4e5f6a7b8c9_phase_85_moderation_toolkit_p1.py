"""phase 85 — moderation toolkit p1: attributed comment removal + rejoin ban

Two additive, reversible schema changes:

  1. ``comments.removed_by_id`` — nullable FK to users (ondelete SET NULL).
     Distinguishes moderator removal (set) from author self-delete (NULL)
     on an already-soft-deleted row. See models.Comment (B-1 fix).
  2. ``org_bans`` table — org-scoped rejoin ban with a partial unique index
     enforcing at most one ACTIVE (revoked_at IS NULL) ban per
     (org_id, user_id). See models.OrgBan (B-8 fix).

No backfill: the new column is nullable (existing self-deletes stay NULL =
author self-delete, which is the correct historical semantic) and the new
table starts empty (nothing seeded at org creation). Stated explicitly per
the Phase 85 verification matrix.

Hex-prefix revision id. Reversible.

Revision ID: d4e5f6a7b8c9
Revises: c2d3e4f5a6b7
Create Date: 2026-07-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c2d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_tables() -> set[str]:
    bind = op.get_bind()
    return set(sa.inspect(bind).get_table_names())


def _existing_columns(table: str) -> set[str]:
    bind = op.get_bind()
    try:
        return {c["name"] for c in sa.inspect(bind).get_columns(table)}
    except Exception:
        return set()


def upgrade() -> None:
    # 1. comments.removed_by_id
    if "removed_by_id" not in _existing_columns("comments"):
        with op.batch_alter_table("comments") as batch_op:
            batch_op.add_column(
                sa.Column("removed_by_id", sa.String(), nullable=True)
            )
        op.create_index(
            "ix_comments_removed_by_id", "comments", ["removed_by_id"]
        )

    # 2. org_bans table
    if "org_bans" not in _existing_tables():
        op.create_table(
            "org_bans",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "org_id", sa.String(),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "user_id", sa.String(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "banned_by_id", sa.String(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column(
                "revoked_by_id", sa.String(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.create_index("ix_org_bans_org_id", "org_bans", ["org_id"])
        op.create_index("ix_org_bans_user_id", "org_bans", ["user_id"])
        # At most one active (un-revoked) ban per (org_id, user_id).
        op.create_index(
            "uq_org_ban_active",
            "org_bans",
            ["org_id", "user_id"],
            unique=True,
            postgresql_where=sa.text("revoked_at IS NULL"),
            sqlite_where=sa.text("revoked_at IS NULL"),
        )


def downgrade() -> None:
    if "org_bans" in _existing_tables():
        op.drop_index("uq_org_ban_active", table_name="org_bans")
        op.drop_index("ix_org_bans_user_id", table_name="org_bans")
        op.drop_index("ix_org_bans_org_id", table_name="org_bans")
        op.drop_table("org_bans")

    if "removed_by_id" in _existing_columns("comments"):
        op.drop_index("ix_comments_removed_by_id", table_name="comments")
        with op.batch_alter_table("comments") as batch_op:
            batch_op.drop_column("removed_by_id")
