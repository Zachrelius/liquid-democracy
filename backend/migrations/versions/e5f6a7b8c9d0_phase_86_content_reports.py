"""phase 86 — content_reports (member report/flag queue)

Additive schema only: creates the ``content_reports`` table with a partial
unique index enforcing at most one OPEN report per
(reporter_id, target_type, target_id), plus org+status and target lookup
indexes. See models.ContentReport (B-4 fix).

No backfill: new table starts empty; nothing is seeded at org creation.

Hex-prefix revision id. Reversible.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_tables() -> set[str]:
    bind = op.get_bind()
    return set(sa.inspect(bind).get_table_names())


def upgrade() -> None:
    if "content_reports" not in _existing_tables():
        op.create_table(
            "content_reports",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "org_id", sa.String(),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "reporter_id", sa.String(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("target_type", sa.String(), nullable=False),
            sa.Column("target_id", sa.String(), nullable=False),
            sa.Column("reason", sa.String(), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="open"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column(
                "resolved_by_id", sa.String(),
                sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
            ),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_content_reports_org_id", "content_reports", ["org_id"])
        op.create_index("ix_content_reports_reporter_id", "content_reports", ["reporter_id"])
        op.create_index(
            "ix_content_reports_org_status", "content_reports", ["org_id", "status"],
        )
        op.create_index(
            "ix_content_reports_target", "content_reports", ["target_type", "target_id"],
        )
        # At most one OPEN report per (reporter, target).
        op.create_index(
            "uq_content_report_open",
            "content_reports",
            ["reporter_id", "target_type", "target_id"],
            unique=True,
            postgresql_where=sa.text("status = 'open'"),
            sqlite_where=sa.text("status = 'open'"),
        )


def downgrade() -> None:
    if "content_reports" in _existing_tables():
        op.drop_index("uq_content_report_open", table_name="content_reports")
        op.drop_index("ix_content_reports_target", table_name="content_reports")
        op.drop_index("ix_content_reports_org_status", table_name="content_reports")
        op.drop_index("ix_content_reports_reporter_id", table_name="content_reports")
        op.drop_index("ix_content_reports_org_id", table_name="content_reports")
        op.drop_table("content_reports")
