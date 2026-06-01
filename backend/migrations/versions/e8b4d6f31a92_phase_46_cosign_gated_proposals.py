"""phase 46 cosign-gated proposals

Adds the cosign primitive:
  * ``organizations.proposal_creation_mode`` column ('open' default,
    'cosign_required', 'admin_only').
  * ``proposals.is_cosign_gated`` + ``cosign_threshold_snapshot`` +
    ``cosign_expires_at`` columns.
  * ``proposals.status`` enum gains ``expired_unsigned`` (terminal state
    for petitions that didn't reach threshold within their window).
  * ``proposal_cosignatures`` table — one row per (proposal, user).

Default for ``proposal_creation_mode`` is 'open' (server_default) so
untouched orgs behave byte-for-byte as pre-46.

Revision ID: e8b4d6f31a92
Revises: d5e9f8a23bc4
Create Date: 2026-05-31 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e8b4d6f31a92"
down_revision: Union[str, None] = "d5e9f8a23bc4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns(table: str) -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        return {c["name"] for c in insp.get_columns(table)}
    except Exception:
        return set()


def _existing_tables() -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return set(insp.get_table_names())


def upgrade() -> None:
    # 1) organizations.proposal_creation_mode
    org_cols = _existing_columns("organizations")
    if "proposal_creation_mode" not in org_cols:
        op.add_column(
            "organizations",
            sa.Column(
                "proposal_creation_mode",
                sa.String(length=32),
                nullable=False,
                server_default="open",
            ),
        )
        op.create_index(
            "ix_organizations_proposal_creation_mode",
            "organizations",
            ["proposal_creation_mode"],
        )

    # 2) proposals cosign columns
    proposal_cols = _existing_columns("proposals")
    if "is_cosign_gated" not in proposal_cols:
        op.add_column(
            "proposals",
            sa.Column(
                "is_cosign_gated",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
    if "cosign_threshold_snapshot" not in proposal_cols:
        op.add_column(
            "proposals",
            sa.Column(
                "cosign_threshold_snapshot",
                sa.Integer(),
                nullable=True,
            ),
        )
    if "cosign_expires_at" not in proposal_cols:
        op.add_column(
            "proposals",
            sa.Column(
                "cosign_expires_at",
                sa.DateTime(),
                nullable=True,
            ),
        )
        op.create_index(
            "ix_proposals_cosign_expires_at",
            "proposals",
            ["cosign_expires_at"],
        )

    # 3) proposal_cosignatures table.
    if "proposal_cosignatures" not in _existing_tables():
        op.create_table(
            "proposal_cosignatures",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "proposal_id",
                sa.String(),
                sa.ForeignKey("proposals.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "user_id",
                sa.String(),
                sa.ForeignKey("users.id"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "proposal_id", "user_id",
                name="uq_proposal_cosignatures_proposal_user",
            ),
        )

    # 4) proposals.status enum: add 'expired_unsigned' on Postgres.
    # SQLite stores enums as TEXT with a CHECK constraint Alembic
    # re-creates on rebuild; the alembic batch dance is intrusive for
    # an additive enum value, so we no-op on SQLite. The new value is
    # accepted at the application layer regardless.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "ALTER TYPE proposal_status ADD VALUE IF NOT EXISTS 'expired_unsigned'"
        )


def downgrade() -> None:
    if "proposal_cosignatures" in _existing_tables():
        op.drop_table("proposal_cosignatures")

    proposal_cols = _existing_columns("proposals")
    if "cosign_expires_at" in proposal_cols:
        op.drop_index(
            "ix_proposals_cosign_expires_at", table_name="proposals",
        )
        op.drop_column("proposals", "cosign_expires_at")
    if "cosign_threshold_snapshot" in proposal_cols:
        op.drop_column("proposals", "cosign_threshold_snapshot")
    if "is_cosign_gated" in proposal_cols:
        op.drop_column("proposals", "is_cosign_gated")

    org_cols = _existing_columns("organizations")
    if "proposal_creation_mode" in org_cols:
        op.drop_index(
            "ix_organizations_proposal_creation_mode",
            table_name="organizations",
        )
        op.drop_column("organizations", "proposal_creation_mode")

    # Note: 'expired_unsigned' enum value is left in place on downgrade
    # (PG enum value removal requires a full type recreate; not worth
    # the complexity for a downgrade path that's only used in dev/CI).
