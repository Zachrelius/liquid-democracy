"""phase 101 — backfill trusted high-volume proposal-create permission

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-08-23 00:00:00.000000

New organizations receive ``proposal.high_volume_create`` through
``DEFAULT_GRANTS``. Existing Steward and Admin roles need the same enabled
row. Existing explicit rows are never overwritten; Moderator, Member, and
custom/nonmatching system roles receive nothing.
"""
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa


revision: str = "d6e7f8a9b0c1"
down_revision: Union[str, None] = "c5d6e7f8a9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KEY = "proposal.high_volume_create"


def upgrade() -> None:
    bind = op.get_bind()
    roles = bind.execute(sa.text(
        "SELECT id FROM roles WHERE system_key IN ('steward', 'admin')"
    )).fetchall()
    for role in roles:
        role_id = role[0]
        existing = bind.execute(sa.text(
            "SELECT id FROM role_permissions "
            "WHERE role_id = :role_id AND permission_key = :permission_key"
        ), {
            "role_id": role_id,
            "permission_key": _KEY,
        }).fetchone()
        if existing is not None:
            continue
        bind.execute(sa.text(
            "INSERT INTO role_permissions "
            "(id, role_id, permission_key, enabled, created_at) "
            "VALUES (:id, :role_id, :permission_key, :enabled, CURRENT_TIMESTAMP)"
        ), {
            "id": str(uuid.uuid4()),
            "role_id": role_id,
            "permission_key": _KEY,
            "enabled": True,
        })


def downgrade() -> None:
    op.get_bind().execute(sa.text(
        "DELETE FROM role_permissions WHERE permission_key = :permission_key"
    ), {"permission_key": _KEY})
