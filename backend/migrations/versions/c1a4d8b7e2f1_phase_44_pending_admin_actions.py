"""phase 44 pending admin actions

Adds the multi-admin approval ratification foundation: two new tables
backing an N-of-M opt-in approval queue over destructive admin actions.

  * ``pending_admin_actions`` — one row per submitted destructive action
    awaiting ratification. Carries ``action_type`` + ``payload`` JSON +
    ``initiator_id`` + ``status`` (pending → executed | declined |
    expired | failed) + threshold + expiry window.
  * ``pending_action_approvals`` — one row per approver decision
    (approve or decline) on a pending action. First-class child table
    rather than a JSON blob so the audit trail is queryable.

Per Phase 44 D1 the feature itself is opt-in via Organization.settings;
the schema lands universally so any org can enable it.

Revision ID: c1a4d8b7e2f1
Revises: 4b0bf8f1761f
Create Date: 2026-05-31 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c1a4d8b7e2f1"
down_revision: Union[str, None] = "4b0bf8f1761f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_tables() -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return set(insp.get_table_names())


def upgrade() -> None:
    existing = _existing_tables()

    if "pending_admin_actions" not in existing:
        op.create_table(
            "pending_admin_actions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "org_id",
                sa.String(),
                sa.ForeignKey("organizations.id"),
                nullable=False,
                index=True,
            ),
            sa.Column("action_type", sa.String(), nullable=False, index=True),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column(
                "initiator_id",
                sa.String(),
                sa.ForeignKey("users.id"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "status",
                sa.String(),
                nullable=False,
                server_default="pending",
                index=True,
            ),
            sa.Column("threshold", sa.Integer(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False, index=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
            sa.Column("resolution_detail", sa.JSON(), nullable=True),
        )

    existing = _existing_tables()
    if "pending_action_approvals" not in existing:
        op.create_table(
            "pending_action_approvals",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "pending_action_id",
                sa.String(),
                sa.ForeignKey("pending_admin_actions.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "approver_id",
                sa.String(),
                sa.ForeignKey("users.id"),
                nullable=False,
                index=True,
            ),
            sa.Column("decision", sa.String(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "pending_action_id",
                "approver_id",
                name="uq_pending_action_one_decision_per_approver",
            ),
        )


def downgrade() -> None:
    existing = _existing_tables()
    if "pending_action_approvals" in existing:
        op.drop_table("pending_action_approvals")
    existing = _existing_tables()
    if "pending_admin_actions" in existing:
        op.drop_table("pending_admin_actions")
