"""Phase 16: add the ``proposal.set_durations`` permission key + per-proposal
duration columns on ``proposals``.

Revision ID: 9a8910210205
Revises: 98dcd0058ba2
Create Date: 2026-05-04 00:00:00.000000

What this does
--------------

Two parts:

1. **Permission seed** (mirrors Phase 12.5).
   For every existing organization, inserts one ``role_permissions`` row
   per preset role with ``permission_key='proposal.set_durations'`` and
   the appropriate ``enabled`` value:

     - steward -> enabled=True
     - admin -> enabled=True
     - moderator -> enabled=True   (Phase 16 Q1 — durations are logistics,
                                     not governance: a Moderator
                                     scheduling a sub-org event vote
                                     shouldn't need an admin to set the
                                     window)
     - member -> enabled=False

   This is more permissive than ``proposal.set_thresholds`` (Phase 12.5,
   Steward + Admin only) by deliberate design.

   Mirrors the Phase 12.5 (41694d86821f) migration shape exactly: explicit
   rows for every preset role kept for matrix-UI consistency (the matrix
   renders all 26 cells per role; absence-as-False would still work in
   ``has_permission`` but the explicit row keeps row-counts deterministic
   across orgs).

2. **Schema additions for B4** — two new nullable Float columns on
   ``proposals``:

     - ``deliberation_days`` (Float, nullable)
     - ``voting_days`` (Float, nullable)

   B4 schema check result (reported in closeout): the existing Proposal
   model had NEITHER ``voting_days`` NOR ``deliberation_days`` columns
   prior to this pass — durations were defined only via org-level
   settings (``Organization.settings.default_*``) and applied indirectly
   by the advance-phase caller passing ``voting_end`` explicitly. Phase
   16 introduces per-proposal overrides so we add both columns. Float
   from the start (no Int → Float migration step needed) so live-poll
   sub-day voting windows (>= 0.05 days = 72 minutes) are representable.

Idempotency
-----------

Per-row check via existence guard so a re-run of the permission seed is
a no-op. The column additions guard via ``inspector.get_columns`` — only
add the column if it isn't already present. Both halves are safe to
re-run on a partially-applied DB.

Downgrade
---------

Deletes every ``role_permissions`` row whose
``permission_key='proposal.set_durations'`` and drops the two new
columns from ``proposals``.
"""
from datetime import datetime, timezone
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa


revision: str = '9a8910210205'
down_revision: Union[str, None] = '98dcd0058ba2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Per-system_key default for the new key. True for steward, admin, AND
# moderator (durations are logistics — Phase 16 Q1); False for member.
_DEFAULTS_BY_SYSTEM_KEY: dict[str, bool] = {
    "steward": True,
    "admin": True,
    "moderator": True,
    "member": False,
}

_PERMISSION_KEY = "proposal.set_durations"


def _now_naive() -> datetime:
    """UTC timestamp without tzinfo (matches the rest of the codebase's
    DateTime columns that aren't timezone=True)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # ----- Part 2: schema additions on proposals (run BEFORE the
    # permission seed so a partial-failure on the seed leaves a
    # consistent schema state). Idempotent: skip columns that already
    # exist (e.g., when create_all already shaped the table on a fresh
    # container).
    if 'proposals' in existing_tables:
        existing_cols = {
            c["name"] for c in inspector.get_columns("proposals")
        }
        if 'deliberation_days' not in existing_cols:
            op.add_column(
                'proposals',
                sa.Column('deliberation_days', sa.Float(), nullable=True),
            )
        if 'voting_days' not in existing_cols:
            op.add_column(
                'proposals',
                sa.Column('voting_days', sa.Float(), nullable=True),
            )

    # ----- Part 1: permission seed.
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

    # Reverse the permission seed first (the row-delete is harmless if
    # the table is gone; guard anyway).
    if 'role_permissions' in existing_tables:
        bind.execute(
            sa.text(
                "DELETE FROM role_permissions WHERE permission_key = :pkey"
            ),
            {"pkey": _PERMISSION_KEY},
        )

    # Then drop the two new columns from proposals (no-op if absent).
    if 'proposals' in existing_tables:
        existing_cols = {
            c["name"] for c in inspector.get_columns("proposals")
        }
        if 'voting_days' in existing_cols:
            op.drop_column('proposals', 'voting_days')
        if 'deliberation_days' in existing_cols:
            op.drop_column('proposals', 'deliberation_days')
