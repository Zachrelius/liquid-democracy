"""Phase 109 server-owned voting rules and immutable final method results.

Revision ID: a109b0c1d2e3
Revises: f8a9b0c1d2e3
"""
from alembic import op
import sqlalchemy as sa

revision = "a109b0c1d2e3"
down_revision = "f8a9b0c1d2e3"
branch_labels = None
depends_on = None


def upgrade():
    # Bootstrap uses create_all before migration; tolerate the over-shaped DB.
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("proposals")}
    for name in ("voting_rules", "final_method_result"):
        if name not in columns:
            op.add_column("proposals", sa.Column(name, sa.JSON(), nullable=True))


def downgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("proposals")}
    for name in ("final_method_result", "voting_rules"):
        if name in columns:
            op.drop_column("proposals", name)
