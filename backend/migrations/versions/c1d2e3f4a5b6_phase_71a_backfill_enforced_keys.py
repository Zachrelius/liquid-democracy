"""phase 71a — backfill role_permissions for keys 71a+71b make authoritative

Phase 71 makes the per-org permission config authoritative for ~12 keys
that were previously gated only by a coarse role tier
(``require_org_admin`` / ``require_org_moderator_or_admin``). Enforcement
reads ``has_permission`` which reads ``role_permissions`` rows — and an
ABSENT row reads as False. So before the route conversions (71a + 71b)
turn enforcement on, every existing org must already hold a row for each
newly-enforced (role, key) pair that matches CURRENT behavior, or the
conversion would silently strip a capability live orgs have today (the
recurring 45a / 46 / 47 "new grant only reaches new orgs" failure, here
multiplied across the whole key set).

This migration (shipped in 71a, but covering the FULL 71a+71b set per the
spec's "one migration seeds them all" rule) backfills those rows to match
current behavior, idempotently (skip-if-exists). Because the seeded values
equal what the tier allows today, turning enforcement on in 71a/71b is a
no-op for existing orgs — nobody loses a capability they have now. That
is the property that makes the staged rollout safe.

Current-behavior map (verified against the live routes, Phase 69 audit):
  * steward + admin: hold EVERY enforced key already (DEFAULT_GRANTS =
    ALL_PERMISSION_KEYS). Their inserts here are defensive no-ops.
  * moderator: holds the moderator-tier keys. Genuinely NEW rows for the
    existing-org population are ``member.suspend`` and ``polis.manage``
    (moderators can do both today via the moderator+ tier, but these were
    not in moderator DEFAULT_GRANTS). The other moderator keys
    (``topic.edit``, ``member.approve_join``, ``member.invite``,
    ``polis.create``) are already seeded for existing orgs.
  * member: no enforced key (every gate floors at moderator+ or admin+).

NOTE — spec-table correction: the 71b table lists ``topic.delete`` as
"moderator ON", but the live route ``delete_org_topic`` uses
``require_org_admin`` (admin+). Seeding moderator would CHANGE behavior,
so this migration seeds ``topic.delete`` admin-only (steward + admin),
matching current behavior per the load-bearing no-change invariant.

Data-only migration (no schema change) — reversible + idempotent. The
downgrade removes only the genuinely-new rows the upgrade introduces into
the existing-org population (moderator ``member.suspend`` +
``polis.manage``); it deliberately does NOT touch steward/admin rows or
the already-present moderator rows, which pre-date this migration.

Revision ID: c1d2e3f4a5b6
Revises: b8e3f1a09d24
Create Date: 2026-06-14 12:00:00.000000

"""
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa


revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "b8e3f1a09d24"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# All keys Phase 71 (71a + 71b) makes config-authoritative.
_ENFORCED_KEYS = (
    "member.suspend",
    "analytics.view",
    "topic.edit",
    "topic.delete",
    "member.approve_join",
    "member.remove",
    "member.invite",
    "sub_org.create",
    "sub_org.delete",
    "sub_org.edit_settings",
    "polis.create",
    "polis.manage",
)

# Per-role TRUE set matching CURRENT behavior. Steward + admin get every
# enforced key (they already do); moderator gets the moderator-tier keys.
_MODERATOR_TRUE = {
    "member.suspend",
    "topic.edit",
    "member.approve_join",
    "member.invite",
    "polis.create",
    "polis.manage",
}
_GRANTS: dict[str, set[str]] = {
    "steward": set(_ENFORCED_KEYS),
    "admin": set(_ENFORCED_KEYS),
    "moderator": set(_MODERATOR_TRUE),
}

# The rows that did NOT exist in the pre-71 existing-org population and so
# are the upgrade's true net-new contribution — what downgrade reverses.
_DOWNGRADE_MODERATOR_KEYS = ("member.suspend", "polis.manage")


def upgrade() -> None:
    bind = op.get_bind()
    for system_key, keys in _GRANTS.items():
        role_rows = bind.execute(
            sa.text("SELECT id FROM roles WHERE system_key = :sk"),
            {"sk": system_key},
        ).fetchall()
        for row in role_rows:
            role_id = row[0]
            for permission_key in keys:
                existing = bind.execute(
                    sa.text(
                        "SELECT id FROM role_permissions "
                        "WHERE role_id = :rid AND permission_key = :pk"
                    ),
                    {"rid": role_id, "pk": permission_key},
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
                        "pk": permission_key,
                        "en": True,
                    },
                )


def downgrade() -> None:
    bind = op.get_bind()
    # Reverse only the net-new rows: moderator member.suspend + polis.manage.
    # Steward/admin rows and the other moderator rows pre-date this
    # migration (seeded at org creation), so they are left intact.
    role_rows = bind.execute(
        sa.text("SELECT id FROM roles WHERE system_key = 'moderator'")
    ).fetchall()
    for row in role_rows:
        for permission_key in _DOWNGRADE_MODERATOR_KEYS:
            bind.execute(
                sa.text(
                    "DELETE FROM role_permissions "
                    "WHERE role_id = :rid AND permission_key = :pk"
                ),
                {"rid": row[0], "pk": permission_key},
            )
