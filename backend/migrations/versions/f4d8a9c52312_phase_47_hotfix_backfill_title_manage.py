"""phase 47 hotfix — backfill title.manage grants for existing orgs

Phase 47 added the ``title.manage`` permission key to PERMISSION_REGISTRY
+ DEFAULT_GRANTS (defaulting to steward + admin via
``set(ALL_PERMISSION_KEYS)``). For *new* orgs created after the Phase 47
deploy, ``role_seed.seed_default_roles_for_org`` picks the key up via
DEFAULT_GRANTS. For *existing* orgs (every prod org pre-deploy),
``role_permissions`` rows were seeded with the pre-47 grant set — they
have no row for ``title.manage``, so ``has_permission`` returns False
for steward + admin on the new key, and the entire B2/B3 surface is
unreachable (the FE panel is hidden; the API returns 403).

QA on the Phase 47 prod deploy surfaced this — the legacy /demo org
Steward had 29 user_permissions including OWNER_ONLY_KEYS but NOT
``title.manage``. This migration backfills the grant for steward +
admin roles on every existing org. Idempotent — skips rows that
already exist.

Revision ID: f4d8a9c52312
Revises: f3c7e9b48201
Create Date: 2026-06-01 06:30:00.000000

"""
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa


revision: str = "f4d8a9c52312"
down_revision: Union[str, None] = "f3c7e9b48201"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    # Find every steward + admin role row across all orgs.
    role_rows = bind.execute(sa.text(
        "SELECT id FROM roles WHERE system_key IN ('steward', 'admin')"
    )).fetchall()
    for row in role_rows:
        role_id = row[0]
        existing = bind.execute(sa.text(
            "SELECT id FROM role_permissions "
            "WHERE role_id = :rid AND permission_key = 'title.manage'"
        ), {"rid": role_id}).fetchone()
        if existing is not None:
            continue
        bind.execute(sa.text(
            "INSERT INTO role_permissions "
            "(id, role_id, permission_key, enabled, created_at) "
            "VALUES (:id, :rid, 'title.manage', :en, "
            " CURRENT_TIMESTAMP)"
        ), {"id": str(uuid.uuid4()), "rid": role_id, "en": True})


def downgrade() -> None:
    bind = op.get_bind()
    # Drop the backfilled rows. Defensive (uses key, not role-tier
    # joins) so we don't strip a hand-edited row by accident.
    role_rows = bind.execute(sa.text(
        "SELECT id FROM roles WHERE system_key IN ('steward', 'admin')"
    )).fetchall()
    for row in role_rows:
        bind.execute(sa.text(
            "DELETE FROM role_permissions "
            "WHERE role_id = :rid AND permission_key = 'title.manage'"
        ), {"rid": row[0]})
