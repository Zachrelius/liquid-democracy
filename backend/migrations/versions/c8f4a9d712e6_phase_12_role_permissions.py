"""Phase 12 Stage 1: configurable role permissions — ``roles`` table,
``role_permissions`` table, FK migration on ``OrgMembership.role`` (string
column dropped), and the "owner" -> "steward" rename in lockstep.

Revision ID: c8f4a9d712e6
Revises: b2d5f1a3c7e4
Create Date: 2026-05-03 19:30:00.000000

What this does
--------------

1. Creates the ``roles`` table (per-org role definitions; four preset rows
   per existing org seeded in step 4).
2. Creates the ``role_permissions`` table (per-role permission grants;
   default rows from the spec's permission registry seeded in step 4).
3. Adds a nullable ``role_id`` FK column to ``org_memberships``.
4. For every existing organization:
     - inserts the four preset Role rows (steward, admin, moderator, member)
     - inserts the default RolePermission rows for each preset role
       (steward + admin both get all 23 permission keys; moderator gets the
       8 keys the spec lists with "moderator"; member gets none)
5. Backfills ``org_memberships.role_id`` by joining to the new ``roles``
   table. The legacy string ``role`` column maps as:
       ``"owner" -> roles.system_key="steward"``  (the rename happens here)
       ``"admin"     -> roles.system_key="admin"``
       ``"moderator" -> roles.system_key="moderator"``
       ``"member"    -> roles.system_key="member"``
   After the backfill no row in the database references the literal string
   ``"owner"`` anywhere.
6. Flips ``org_memberships.role_id`` to NOT NULL.
7. Drops the legacy ``org_memberships.role`` string column.

Idempotency
-----------

Standard introspect-and-skip pattern from Phase 8.6 / 9.5 / 10. Re-running
the upgrade after a partial earlier run (or a ``create_all``-then-``stamp``
deploy) is safe:
  - the ``create_table`` calls check ``inspector.get_table_names()`` first;
  - the ``add_column`` checks for ``role_id`` first;
  - the seed inserts use ``WHERE NOT EXISTS`` (or equivalent SELECT-then-
    INSERT) so re-running never duplicates rows;
  - the backfill update is a no-op for rows that already have role_id set;
  - the NOT NULL flip and column drop are guarded.

Downgrade
---------

Best-effort reverse: re-adds the ``role`` string column on org_memberships,
populates it from ``roles.system_key`` joined via ``role_id``, drops the
``role_id`` column, drops the ``role_permissions`` and ``roles`` tables.

NOTE: a downgrade re-introduces the legacy ``"owner"`` string for any
membership whose role.system_key is ``"steward"``. This is the
information-preserving inverse of the upgrade's "owner" -> "steward"
rename. If the downgrade is ever run on production data that had custom
(non-preset) roles created in Stage 2+, those memberships will downgrade
to whatever ``role.system_key`` they had — which may not match the old
{owner, admin, moderator, member} vocabulary. Stage 1 only ships the four
presets, so on any DB this migration will downgrade against, the
roundtrip is lossless.
"""
from datetime import datetime, timezone
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa


revision: str = 'c8f4a9d712e6'
down_revision: Union[str, None] = 'b2d5f1a3c7e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Preset role + default-grants tables (duplicated from backend/role_seed.py
# so the migration can run inside the Alembic env without depending on the
# application's import path).
# ---------------------------------------------------------------------------

# (system_key, display_name, display_order)
_PRESET_ROLES: list[tuple[str, str, int]] = [
    ("steward", "Steward", 0),
    ("admin", "Admin", 1),
    ("moderator", "Moderator", 2),
    ("member", "Member", 3),
]

_ALL_PERMISSIONS: tuple[str, ...] = (
    "proposal.create", "proposal.delete", "proposal.advance_phase",
    "proposal.resolve_tie",
    "topic.create", "topic.edit", "topic.delete",
    "member.approve_join", "member.remove", "member.suspend",
    "member.change_role", "member.invite",
    "sub_org.create", "sub_org.delete", "sub_org.edit_settings",
    "delegate_application.approve",
    "polis.create", "polis.manage",
    "comment.moderate",
    "org.edit_settings", "org.edit_branding",
    "audit.view_org", "analytics.view",
)

_MODERATOR_GRANTS: frozenset[str] = frozenset({
    "proposal.create", "proposal.advance_phase",
    "topic.create", "topic.edit",
    "member.approve_join", "member.invite",
    "polis.create", "comment.moderate",
})

_DEFAULT_GRANTS: dict[str, frozenset[str]] = {
    "steward": frozenset(_ALL_PERMISSIONS),
    "admin": frozenset(_ALL_PERMISSIONS),
    "moderator": _MODERATOR_GRANTS,
    "member": frozenset(),
}

# Legacy role-string -> new system_key map (the "owner" -> "steward" rename
# happens here).
_ROLE_RENAME: dict[str, str] = {
    "owner": "steward",
    "admin": "admin",
    "moderator": "moderator",
    "member": "member",
}


def _now_naive() -> datetime:
    """UTC timestamp without tzinfo (matches the rest of the codebase's
    DateTime columns that aren't timezone=True)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    def _has_column(table: str, column: str) -> bool:
        try:
            return column in {c['name'] for c in inspector.get_columns(table)}
        except Exception:
            return False

    # -----------------------------------------------------------------
    # 1. Create roles table
    # -----------------------------------------------------------------
    if 'roles' not in existing_tables:
        op.create_table(
            'roles',
            sa.Column('id', sa.String(), primary_key=True),
            sa.Column(
                'org_id', sa.String(),
                sa.ForeignKey('organizations.id', ondelete='CASCADE'),
                nullable=False,
            ),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('system_key', sa.String(), nullable=False),
            sa.Column('is_system_preset', sa.Boolean(), nullable=False),
            sa.Column('display_order', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                'org_id', 'system_key', name='uq_roles_org_system_key',
            ),
        )
        op.create_index(
            'ix_roles_org_id', 'roles', ['org_id'], unique=False,
        )

    # -----------------------------------------------------------------
    # 2. Create role_permissions table
    # -----------------------------------------------------------------
    # Re-introspect (we may have just created `roles` above).
    existing_tables = set(sa.inspect(bind).get_table_names())
    if 'role_permissions' not in existing_tables:
        op.create_table(
            'role_permissions',
            sa.Column('id', sa.String(), primary_key=True),
            sa.Column(
                'role_id', sa.String(),
                sa.ForeignKey('roles.id', ondelete='CASCADE'),
                nullable=False,
            ),
            sa.Column('permission_key', sa.String(), nullable=False),
            sa.Column('enabled', sa.Boolean(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                'role_id', 'permission_key',
                name='uq_role_permissions_role_key',
            ),
        )
        op.create_index(
            'ix_role_permissions_role_id', 'role_permissions',
            ['role_id'], unique=False,
        )

    # -----------------------------------------------------------------
    # 3. Add nullable role_id FK column to org_memberships
    # -----------------------------------------------------------------
    if not _has_column('org_memberships', 'role_id'):
        with op.batch_alter_table('org_memberships', schema=None) as batch_op:
            batch_op.add_column(
                sa.Column('role_id', sa.String(), nullable=True),
            )
            batch_op.create_foreign_key(
                'fk_org_memberships_role_id',
                'roles', ['role_id'], ['id'],
            )
            batch_op.create_index(
                'ix_org_memberships_role_id', ['role_id'], unique=False,
            )

    # -----------------------------------------------------------------
    # 4. Seed roles + role_permissions for every existing org
    # -----------------------------------------------------------------
    org_ids = [
        row[0] for row in
        bind.execute(sa.text("SELECT id FROM organizations")).fetchall()
    ]
    now = _now_naive()
    for org_id in org_ids:
        # Insert preset roles (idempotent: skip any system_key that already
        # has a row for this org).
        existing_role_keys: dict[str, str] = {
            row[0]: row[1] for row in bind.execute(
                sa.text(
                    "SELECT system_key, id FROM roles WHERE org_id = :org_id"
                ),
                {"org_id": org_id},
            ).fetchall()
        }
        for system_key, display_name, display_order in _PRESET_ROLES:
            if system_key in existing_role_keys:
                continue
            new_id = str(uuid.uuid4())
            bind.execute(
                sa.text(
                    "INSERT INTO roles "
                    "(id, org_id, name, system_key, is_system_preset, "
                    " display_order, created_at) "
                    "VALUES (:id, :org_id, :name, :system_key, :preset, "
                    ":display_order, :created_at)"
                ),
                {
                    "id": new_id,
                    "org_id": org_id,
                    "name": display_name,
                    "system_key": system_key,
                    "preset": True,
                    "display_order": display_order,
                    "created_at": now,
                },
            )
            existing_role_keys[system_key] = new_id

        # Insert role_permissions for each preset role (idempotent).
        for system_key, _, _ in _PRESET_ROLES:
            role_id = existing_role_keys[system_key]
            granted = _DEFAULT_GRANTS.get(system_key, frozenset())
            if not granted:
                continue
            already = {
                row[0] for row in bind.execute(
                    sa.text(
                        "SELECT permission_key FROM role_permissions "
                        "WHERE role_id = :role_id"
                    ),
                    {"role_id": role_id},
                ).fetchall()
            }
            for permission_key in sorted(granted):
                if permission_key in already:
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
                        "pkey": permission_key,
                        "enabled": True,
                        "created_at": now,
                    },
                )

    # -----------------------------------------------------------------
    # 5. Backfill org_memberships.role_id from the legacy `role` column
    #    (with the "owner" -> "steward" rename baked in).
    # -----------------------------------------------------------------
    if _has_column('org_memberships', 'role'):
        memberships = bind.execute(
            sa.text(
                "SELECT id, org_id, role FROM org_memberships "
                "WHERE role_id IS NULL"
            )
        ).fetchall()
        for m_id, m_org_id, m_role in memberships:
            target_system_key = _ROLE_RENAME.get(m_role, m_role)
            row = bind.execute(
                sa.text(
                    "SELECT id FROM roles "
                    "WHERE org_id = :org_id AND system_key = :sk"
                ),
                {"org_id": m_org_id, "sk": target_system_key},
            ).first()
            if row is None:
                # Defensive: should never happen because step 4 seeded all
                # four presets. If a custom legacy role string somehow
                # exists, fall back to "member" to avoid leaving role_id
                # NULL (which would block step 6).
                row = bind.execute(
                    sa.text(
                        "SELECT id FROM roles "
                        "WHERE org_id = :org_id AND system_key = 'member'"
                    ),
                    {"org_id": m_org_id},
                ).first()
            bind.execute(
                sa.text(
                    "UPDATE org_memberships SET role_id = :role_id "
                    "WHERE id = :id"
                ),
                {"role_id": row[0], "id": m_id},
            )
    else:
        # Fresh DB path (create_all already populated org_memberships
        # without the legacy `role` column). Any rows without role_id are
        # backfilled to the org's "member" role.
        memberships = bind.execute(
            sa.text(
                "SELECT id, org_id FROM org_memberships WHERE role_id IS NULL"
            )
        ).fetchall()
        for m_id, m_org_id in memberships:
            row = bind.execute(
                sa.text(
                    "SELECT id FROM roles "
                    "WHERE org_id = :org_id AND system_key = 'member'"
                ),
                {"org_id": m_org_id},
            ).first()
            if row is None:
                continue
            bind.execute(
                sa.text(
                    "UPDATE org_memberships SET role_id = :role_id "
                    "WHERE id = :id"
                ),
                {"role_id": row[0], "id": m_id},
            )

    # -----------------------------------------------------------------
    # 6. Flip role_id to NOT NULL
    # -----------------------------------------------------------------
    # Only flip if there are no remaining NULL rows (defensive).
    null_count = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM org_memberships WHERE role_id IS NULL"
        )
    ).scalar() or 0
    if null_count == 0:
        with op.batch_alter_table('org_memberships', schema=None) as batch_op:
            batch_op.alter_column(
                'role_id', existing_type=sa.String(), nullable=False,
            )

    # -----------------------------------------------------------------
    # 7. Drop the legacy `role` string column
    # -----------------------------------------------------------------
    if _has_column('org_memberships', 'role'):
        with op.batch_alter_table('org_memberships', schema=None) as batch_op:
            batch_op.drop_column('role')


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    def _has_column(table: str, column: str) -> bool:
        try:
            return column in {c['name'] for c in inspector.get_columns(table)}
        except Exception:
            return False

    # -----------------------------------------------------------------
    # 1. Re-add the legacy `role` string column
    # -----------------------------------------------------------------
    if not _has_column('org_memberships', 'role'):
        with op.batch_alter_table('org_memberships', schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    'role', sa.String(),
                    nullable=False, server_default='member',
                ),
            )

    # -----------------------------------------------------------------
    # 2. Backfill `role` from roles.system_key joined via role_id, with
    #    the inverse "steward" -> "owner" rename baked in.
    # -----------------------------------------------------------------
    if 'roles' in existing_tables and _has_column('org_memberships', 'role_id'):
        rows = bind.execute(
            sa.text(
                "SELECT om.id, r.system_key "
                "FROM org_memberships om "
                "JOIN roles r ON r.id = om.role_id"
            )
        ).fetchall()
        for m_id, system_key in rows:
            legacy_role = "owner" if system_key == "steward" else system_key
            bind.execute(
                sa.text(
                    "UPDATE org_memberships SET role = :role WHERE id = :id"
                ),
                {"role": legacy_role, "id": m_id},
            )

    # -----------------------------------------------------------------
    # 3. Drop the role_id FK column (and its index/FK constraint).
    #    Best-effort: try the index drop outside batch first (so a missing
    #    one doesn't sabotage the column-drop batch). Then drop the column
    #    in a batch where any name we don't recognize is silently skipped.
    # -----------------------------------------------------------------
    if _has_column('org_memberships', 'role_id'):
        try:
            op.drop_index(
                'ix_org_memberships_role_id', table_name='org_memberships',
            )
        except Exception:
            pass
        # Within batch_alter_table on SQLite, drop_constraint must match a
        # name Alembic introspects from the existing table. When the table
        # was built by ``Base.metadata.create_all`` (test path) the FK was
        # created without our explicit name, so we can't reliably drop by
        # name. Instead, we just drop the column — SQLite's batch rebuild
        # will reconstruct the table without the FK regardless of its name.
        with op.batch_alter_table('org_memberships', schema=None) as batch_op:
            batch_op.drop_column('role_id')

    # -----------------------------------------------------------------
    # 4. Drop role_permissions and roles tables
    # -----------------------------------------------------------------
    existing_tables = set(sa.inspect(bind).get_table_names())
    if 'role_permissions' in existing_tables:
        try:
            op.drop_index(
                'ix_role_permissions_role_id', table_name='role_permissions',
            )
        except Exception:
            pass
        op.drop_table('role_permissions')

    existing_tables = set(sa.inspect(bind).get_table_names())
    if 'roles' in existing_tables:
        try:
            op.drop_index('ix_roles_org_id', table_name='roles')
        except Exception:
            pass
        op.drop_table('roles')
