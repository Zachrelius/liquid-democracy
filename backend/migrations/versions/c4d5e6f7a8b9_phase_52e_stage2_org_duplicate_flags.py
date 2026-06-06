"""phase 52e stage 2 — org_duplicate_flags table

Adds one table for the org-scoped duplicate-identity flag system:

  ``org_duplicate_flags``
    - ``id`` (uuid pk)
    - ``org_id`` (FK organizations.id, CASCADE, indexed)
    - ``user_a_id`` (FK users.id, CASCADE, indexed) — incumbent
    - ``user_b_id`` (FK users.id, CASCADE, indexed) — new applicant
    - ``confidence`` (String 32) — ``name_dob_address`` (high) or
      ``name_dob`` (low)
    - ``status`` (String 32, server_default 'open', indexed) —
      ``open`` / ``resolved_distinct`` / ``resolved_same``
    - ``resolved_by_id`` (FK users.id, SET NULL, nullable)
    - ``resolved_at`` (DateTime, nullable)
    - ``created_at`` (DateTime, default now)
    - UNIQUE (org_id, user_a_id, user_b_id, confidence) so the same
      pair never gets two open flags for the same hash kind.

No PII stored — only user_ids + the confidence tier + status. The
admin adjudication surface joins through user_ids to display names
the admin already knows.

Hex-prefix revision id. Reversible via op.drop_table.

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-06-06 14:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, None] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_tables() -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        return set(insp.get_table_names())
    except Exception:
        return set()


def upgrade() -> None:
    tables = _existing_tables()
    if "org_duplicate_flags" not in tables:
        op.create_table(
            "org_duplicate_flags",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "org_id", sa.String(length=36),
                sa.ForeignKey(
                    "organizations.id", ondelete="CASCADE",
                    name="fk_org_duplicate_flags_org",
                ),
                nullable=False, index=True,
            ),
            sa.Column(
                "user_a_id", sa.String(length=36),
                sa.ForeignKey(
                    "users.id", ondelete="CASCADE",
                    name="fk_org_duplicate_flags_user_a",
                ),
                nullable=False, index=True,
            ),
            sa.Column(
                "user_b_id", sa.String(length=36),
                sa.ForeignKey(
                    "users.id", ondelete="CASCADE",
                    name="fk_org_duplicate_flags_user_b",
                ),
                nullable=False, index=True,
            ),
            sa.Column(
                "confidence", sa.String(length=32), nullable=False,
            ),
            sa.Column(
                "status", sa.String(length=32),
                nullable=False, server_default="open", index=True,
            ),
            sa.Column(
                "resolved_by_id", sa.String(length=36),
                sa.ForeignKey(
                    "users.id", ondelete="SET NULL",
                    name="fk_org_duplicate_flags_resolved_by",
                ),
                nullable=True,
            ),
            sa.Column(
                "resolved_at", sa.DateTime, nullable=True,
            ),
            sa.Column(
                "created_at", sa.DateTime,
                nullable=False, server_default=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "org_id", "user_a_id", "user_b_id", "confidence",
                name="uq_org_duplicate_flags_pair",
            ),
        )


def downgrade() -> None:
    tables = _existing_tables()
    if "org_duplicate_flags" in tables:
        op.drop_table("org_duplicate_flags")
