"""phase 88 — backfill member.set_voting_weight grants for existing orgs

Phase 88 adds the ``member.set_voting_weight`` permission key to
PERMISSION_REGISTRY + DEFAULT_GRANTS (defaulting to steward + admin via
``set(ALL_PERMISSION_KEYS)``). New orgs pick it up through
``role_seed.seed_default_roles_for_org``; existing orgs (every prod org
pre-deploy) have no ``role_permissions`` row for the key, so
``has_permission`` returns False for steward + admin and the weight-edit
endpoint is unreachable for them.

This is the recurring "new key in DEFAULT_GRANTS only reaches NEW orgs"
failure (hotfixes 45a / 46 / 47 / 68b all traced to it). Backfills the
grant for steward + admin roles on every existing org, idempotently.
Moderator + member deliberately get no row.

Data-only migration (no schema change) — reversible; the downgrade drops
the backfilled rows by key.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-07-05 00:00:01.000000

"""
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa


revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KEY = "member.set_voting_weight"


def upgrade() -> None:
    bind = op.get_bind()
    role_rows = bind.execute(sa.text(
        "SELECT id FROM roles WHERE system_key IN ('steward', 'admin')"
    )).fetchall()
    for row in role_rows:
        role_id = row[0]
        existing = bind.execute(sa.text(
            "SELECT id FROM role_permissions "
            "WHERE role_id = :rid AND permission_key = :key"
        ), {"rid": role_id, "key": _KEY}).fetchone()
        if existing is not None:
            continue
        bind.execute(sa.text(
            "INSERT INTO role_permissions "
            "(id, role_id, permission_key, enabled, created_at) "
            "VALUES (:id, :rid, :key, :en, CURRENT_TIMESTAMP)"
        ), {"id": str(uuid.uuid4()), "rid": role_id, "key": _KEY, "en": True})


def downgrade() -> None:
    bind = op.get_bind()
    role_rows = bind.execute(sa.text(
        "SELECT id FROM roles WHERE system_key IN ('steward', 'admin')"
    )).fetchall()
    for row in role_rows:
        bind.execute(sa.text(
            "DELETE FROM role_permissions "
            "WHERE role_id = :rid AND permission_key = :key"
        ), {"rid": row[0], "key": _KEY})
