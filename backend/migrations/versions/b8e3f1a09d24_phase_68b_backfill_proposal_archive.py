"""phase 68b — backfill proposal.archive grants for existing orgs

Phase 68b adds the ``proposal.archive`` permission key to
PERMISSION_REGISTRY + DEFAULT_GRANTS (defaulting to steward + admin via
``set(ALL_PERMISSION_KEYS)``). For *new* orgs created after the Phase 68b
deploy, ``role_seed.seed_default_roles_for_org`` picks the key up via
DEFAULT_GRANTS. For *existing* orgs (every prod org pre-deploy),
``role_permissions`` rows were seeded with the pre-68b grant set — they
have no row for ``proposal.archive``, so ``has_permission`` returns False
for steward + admin on the new key and the any-phase archive capability
is unreachable for them.

This is the recurring "new key in DEFAULT_GRANTS only reaches NEW orgs"
failure (hotfixes 45a / 46 / 47 all traced to it). This migration
backfills the grant for steward + admin roles on every existing org,
idempotently (skips rows that already exist). Authors don't need the key
to archive their own draft/deliberation proposals, so members/moderators
deliberately get no backfilled row.

Data-only migration (no schema change) — fully reversible; the downgrade
drops the backfilled rows by key (defensive, so a hand-edited row isn't
stripped by a role-tier join).

Revision ID: b8e3f1a09d24
Revises: a3f6c8e21b94
Create Date: 2026-06-13 12:00:00.000000

"""
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa


revision: str = "b8e3f1a09d24"
down_revision: Union[str, None] = "a3f6c8e21b94"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    # Every steward + admin role row across all orgs (matches DEFAULT_GRANTS).
    role_rows = bind.execute(sa.text(
        "SELECT id FROM roles WHERE system_key IN ('steward', 'admin')"
    )).fetchall()
    for row in role_rows:
        role_id = row[0]
        existing = bind.execute(sa.text(
            "SELECT id FROM role_permissions "
            "WHERE role_id = :rid AND permission_key = 'proposal.archive'"
        ), {"rid": role_id}).fetchone()
        if existing is not None:
            continue
        bind.execute(sa.text(
            "INSERT INTO role_permissions "
            "(id, role_id, permission_key, enabled, created_at) "
            "VALUES (:id, :rid, 'proposal.archive', :en, CURRENT_TIMESTAMP)"
        ), {"id": str(uuid.uuid4()), "rid": role_id, "en": True})


def downgrade() -> None:
    bind = op.get_bind()
    # Drop the backfilled rows. Defensive (uses key, not role-tier joins)
    # so we don't strip a hand-edited row by accident.
    role_rows = bind.execute(sa.text(
        "SELECT id FROM roles WHERE system_key IN ('steward', 'admin')"
    )).fetchall()
    for row in role_rows:
        bind.execute(sa.text(
            "DELETE FROM role_permissions "
            "WHERE role_id = :rid AND permission_key = 'proposal.archive'"
        ), {"rid": row[0]})
