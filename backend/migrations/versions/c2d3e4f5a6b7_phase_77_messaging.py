"""phase 77 — org-scoped direct messaging

Creates the four messaging tables (conversations, messages,
conversation_reads, message_blocks) with their indexes + unique
constraints, adds the ``users.dm_disabled`` opt-out column, and backfills
the new ``org_inbox.view`` permission onto every existing org's steward +
admin roles (the load-bearing backfill — without it existing orgs' admins
couldn't read the org inbox, since an absent role_permissions row reads as
False).

No org-settings backfill needed: ``member_dm_policy`` defaults to
``follow_only`` via ``settings.get(...)``. No user-settings backfill
needed beyond the column add: ``dm_disabled`` server_default is '0'.

Hex-prefix revision id. Reversible.

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-06-20 00:00:00.000000

"""
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa


revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_BACKFILL_KEY = "org_inbox.view"
_BACKFILL_ROLES = ("steward", "admin")


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
    tables = _existing_tables()

    if "conversations" not in tables:
        op.create_table(
            "conversations",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("org_id", sa.String(), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("conversation_type", sa.String(), nullable=False),
            sa.Column("initiator_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("recipient_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("context_proposal_id", sa.String(), sa.ForeignKey("proposals.id"), nullable=True),
            sa.Column("subject", sa.String(length=200), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="active"),
            sa.Column("last_message_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "org_id", "conversation_type", "initiator_id", "recipient_id",
                name="uq_conversation_participants",
            ),
        )
        op.create_index("ix_conversations_org_id", "conversations", ["org_id"])
        op.create_index(
            "ix_conversations_org_recipient_status", "conversations",
            ["org_id", "recipient_id", "status"],
        )
        op.create_index(
            "ix_conversations_org_initiator_status", "conversations",
            ["org_id", "initiator_id", "status"],
        )
        op.create_index(
            "ix_conversations_org_type", "conversations",
            ["org_id", "conversation_type"],
        )

    if "messages" not in tables:
        op.create_table(
            "messages",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("conversation_id", sa.String(), sa.ForeignKey("conversations.id"), nullable=False),
            sa.Column("sender_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("is_system", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
        op.create_index(
            "ix_messages_conversation_created", "messages",
            ["conversation_id", "created_at"],
        )

    if "conversation_reads" not in tables:
        op.create_table(
            "conversation_reads",
            sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), primary_key=True),
            sa.Column("conversation_id", sa.String(), sa.ForeignKey("conversations.id"), primary_key=True),
            sa.Column("last_read_at", sa.DateTime(), nullable=False),
        )

    if "message_blocks" not in tables:
        op.create_table(
            "message_blocks",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("blocker_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("blocked_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("org_id", sa.String(), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "blocker_id", "blocked_id", "org_id",
                name="uq_message_block_pair_org",
            ),
        )
        op.create_index("ix_message_blocks_blocker_id", "message_blocks", ["blocker_id"])
        op.create_index("ix_message_blocks_blocked_id", "message_blocks", ["blocked_id"])
        op.create_index("ix_message_blocks_org_id", "message_blocks", ["org_id"])

    # users.dm_disabled
    if "dm_disabled" not in _existing_columns("users"):
        with op.batch_alter_table("users") as batch_op:
            batch_op.add_column(sa.Column(
                "dm_disabled", sa.Boolean(), nullable=False, server_default="0",
            ))

    # Permission backfill: org_inbox.view for existing steward + admin roles.
    bind = op.get_bind()
    for system_key in _BACKFILL_ROLES:
        role_rows = bind.execute(
            sa.text("SELECT id FROM roles WHERE system_key = :sk"),
            {"sk": system_key},
        ).fetchall()
        for row in role_rows:
            role_id = row[0]
            existing = bind.execute(
                sa.text(
                    "SELECT id FROM role_permissions "
                    "WHERE role_id = :rid AND permission_key = :pk"
                ),
                {"rid": role_id, "pk": _BACKFILL_KEY},
            ).fetchone()
            if existing is not None:
                continue
            bind.execute(
                sa.text(
                    "INSERT INTO role_permissions "
                    "(id, role_id, permission_key, enabled, created_at) "
                    "VALUES (:id, :rid, :pk, :en, CURRENT_TIMESTAMP)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "rid": role_id,
                    "pk": _BACKFILL_KEY,
                    "en": True,
                },
            )


def downgrade() -> None:
    bind = op.get_bind()
    # Remove the backfilled permission rows.
    bind.execute(
        sa.text("DELETE FROM role_permissions WHERE permission_key = :pk"),
        {"pk": _BACKFILL_KEY},
    )

    if "dm_disabled" in _existing_columns("users"):
        with op.batch_alter_table("users") as batch_op:
            batch_op.drop_column("dm_disabled")

    tables = _existing_tables()
    if "message_blocks" in tables:
        op.drop_table("message_blocks")
    if "conversation_reads" in tables:
        op.drop_table("conversation_reads")
    if "messages" in tables:
        op.drop_table("messages")
    if "conversations" in tables:
        op.drop_table("conversations")
