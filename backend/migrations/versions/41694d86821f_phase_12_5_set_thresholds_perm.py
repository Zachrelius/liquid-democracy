"""Phase 12.5: add the ``proposal.set_thresholds`` permission key.

Revision ID: 41694d86821f
Revises: e6371e56e860
Create Date: 2026-05-02 00:00:00.000000

What this does
--------------

For every existing organization, inserts one ``role_permissions`` row per
preset role with ``permission_key='proposal.set_thresholds'`` and the
appropriate ``enabled`` value:

  - steward -> enabled=True
  - admin -> enabled=True
  - moderator -> enabled=False
  - member -> enabled=False

Per Phase 12.5 Q2 decision: reserved for Steward / maybe Admin. Members
and Moderators with ``proposal.create`` granted use the org's default
thresholds; only those with this new key can override per-proposal.

Mirrors the Stage 2 (e6371e56e860) shape exactly: explicit-False rows
for moderator/member kept for matrix-UI consistency (the matrix renders
all 25 cells per role; absence-as-False would still work in
``has_permission`` but the explicit row keeps the matrix's row-counts
deterministic across orgs).

Idempotency
-----------

Per-row check via ``WHERE NOT EXISTS`` guards so a re-run is a no-op:
existing rows are not duplicated, missing rows are inserted.

Downgrade
---------

Deletes every ``role_permissions`` row whose
``permission_key='proposal.set_thresholds'``.
"""
from datetime import datetime, timezone
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa


revision: str = '41694d86821f'
down_revision: Union[str, None] = 'e6371e56e860'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Per-system_key default for the new key. True for steward and admin; False
# for moderator and member. Per Phase 12.5 Q2 decision.
_DEFAULTS_BY_SYSTEM_KEY: dict[str, bool] = {
    "steward": True,
    "admin": True,
    "moderator": False,
    "member": False,
}

_PERMISSION_KEY = "proposal.set_thresholds"


def _now_naive() -> datetime:
    """UTC timestamp without tzinfo (matches the rest of the codebase's
    DateTime columns that aren't timezone=True)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # Defensive: if the Stage 1 tables are missing, there's nothing to do.
    if 'roles' not in existing_tables or 'role_permissions' not in existing_tables:
        return

    now = _now_naive()

    # Pull every preset role (id + system_key) across every org.
    rows = bind.execute(
        sa.text(
            "SELECT id, system_key FROM roles "
            "WHERE system_key IN ('steward', 'admin', 'moderator', 'member')"
        )
    ).fetchall()

    for role_id, system_key in rows:
        enabled = _DEFAULTS_BY_SYSTEM_KEY.get(system_key, False)

        # Idempotency: skip if a row already exists for this (role, key).
        already = bind.execute(
            sa.text(
                "SELECT id FROM role_permissions "
                "WHERE role_id = :role_id AND permission_key = :pkey"
            ),
            {"role_id": role_id, "pkey": _PERMISSION_KEY},
        ).first()
        if already is not None:
            continue

        bind.execute(
            sa.text(
                "INSERT INTO role_permissions "
                "(id, role_id, permission_key, enabled, created_at) "
                "VALUES (:id, :role_id, :pkey, :enabled, :created_at)"
            ),
            {
                "id": str(uuid.uuid4()),
                "role_id": role_id,
                "pkey": _PERMISSION_KEY,
                "enabled": enabled,
                "created_at": now,
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'role_permissions' not in existing_tables:
        return

    bind.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_key = :pkey"
        ),
        {"pkey": _PERMISSION_KEY},
    )
