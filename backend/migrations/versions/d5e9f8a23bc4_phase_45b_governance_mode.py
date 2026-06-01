"""phase 45b governance mode

Adds Organization.governance_mode column (B1). Two values:
  - ``single_steward`` (default — today's behavior)
  - ``admin_council`` (opt-in)

All existing rows + new rows default to ``single_steward`` so untouched
orgs behave exactly as Phase 45a left them. Reversible.

Revision ID: d5e9f8a23bc4
Revises: c1a4d8b7e2f1
Create Date: 2026-05-31 19:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d5e9f8a23bc4"
down_revision: Union[str, None] = "c1a4d8b7e2f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns(table: str) -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    cols = _existing_columns("organizations")
    if "governance_mode" not in cols:
        op.add_column(
            "organizations",
            sa.Column(
                "governance_mode",
                sa.String(length=32),
                nullable=False,
                server_default="single_steward",
            ),
        )
        op.create_index(
            "ix_organizations_governance_mode",
            "organizations",
            ["governance_mode"],
        )


def downgrade() -> None:
    cols = _existing_columns("organizations")
    if "governance_mode" in cols:
        op.drop_index(
            "ix_organizations_governance_mode", table_name="organizations",
        )
        op.drop_column("organizations", "governance_mode")
