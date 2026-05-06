"""Phase 15 — Sub-org permission inheritance: SubOrgMembership.role string
column → role_id FK to roles, with the load-bearing ``"owner" → Steward``
mapping from Phase 12.5.

Revision ID: 98dcd0058ba2
Revises: c0a3e5d12f4a
Create Date: 2026-05-06 14:00:00.000000

What this does
--------------

Brings sub-org membership roles into the Phase 12 matrix model. Until
this migration ran, ``SubOrgMembership.role`` was a legacy string column
with values ``member, moderator, admin, owner`` (note: pre-Phase-12
``owner`` — sub-org membership stayed in pre-Phase-12 land while parent
orgs migrated). Cluster S brings sub-orgs into the matrix:

1. Add ``role_id`` column to ``sub_org_memberships`` (nullable initially;
   FK to ``roles.id``).
2. Backfill: for each existing SubOrgMembership row, look up the parent
   org's Role row matching the legacy string. Mapping:

       ``"member"``    → parent's Member role
       ``"moderator"`` → parent's Moderator role
       ``"admin"``     → parent's Admin role
       ``"owner"``     → parent's **Steward** role  (load-bearing —
                          the Phase 12.5 rename applies here too)

   After backfill, no row in ``sub_org_memberships`` references the
   legacy ``"owner"`` string. The Steward target is the parent-org's
   role row whose ``system_key='steward'`` (the Phase 12 backfill
   already mapped any existing ``"owner"`` rows in ``OrgMembership``;
   the Steward role row exists for every org, so the lookup is total).

3. Set ``role_id NOT NULL`` after backfill.
4. Drop the legacy ``role`` string column.

Idempotent (Phase 8.6/9.5/12 introspect-and-skip pattern):
  - the ``add_column`` checks for ``role_id`` first;
  - the backfill update is a no-op for rows that already have ``role_id``
    set;
  - the NOT NULL flip and column drop are guarded.

Downgrade
---------

Best-effort reverse, paralleling Phase 12 Stage 1's downgrade precedent:

1. Re-add the ``role`` string column on ``sub_org_memberships`` (nullable).
2. Backfill ``role`` from ``roles.system_key`` joined via ``role_id``,
   with the inverse rename baked in: ``steward → owner``. Lossy by
   construction — post-Phase-12.5 Stewards weren't all originally
   Owners, so the reverse mapping collapses any custom Steward state to
   ``"owner"``. Acceptable per Phase 12 Stage 1's downgrade precedent
   (lossy reverse > nothing, since the upgrade is the load-bearing path).
3. Set ``role NOT NULL``.
4. Drop the ``role_id`` column (and its FK/index).
"""
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '98dcd0058ba2'
down_revision: Union[str, None] = 'c0a3e5d12f4a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Legacy role-string -> parent-Role.system_key. The "owner" -> "steward"
# rename is the load-bearing piece (see module docstring).
_ROLE_RENAME: dict[str, str] = {
    "owner": "steward",
    "admin": "admin",
    "moderator": "moderator",
    "member": "member",
}

# Inverse for downgrade. Lossy: any post-rename Steward (whether that's a
# preserved owner-equivalent or a Phase-12.5+ custom Steward) collapses
# to "owner".
_ROLE_RENAME_INVERSE: dict[str, str] = {
    "steward": "owner",
    "admin": "admin",
    "moderator": "moderator",
    "member": "member",
}


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    def _has_column(table: str, column: str) -> bool:
        try:
            return column in {c['name'] for c in inspector.get_columns(table)}
        except Exception:
            return False

    if "sub_org_memberships" not in set(inspector.get_table_names()):
        # Defensive: nothing to migrate (fresh DB before Phase 8.5 ran).
        # Phase 8.5's d41a8c92f3b1 migration creates the table; if it's
        # missing here, we're on a chain that hasn't reached 8.5 yet —
        # which shouldn't happen, but bail rather than fail.
        return

    # -----------------------------------------------------------------
    # 1. Add nullable role_id FK column to sub_org_memberships
    # -----------------------------------------------------------------
    if not _has_column("sub_org_memberships", "role_id"):
        with op.batch_alter_table("sub_org_memberships", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column("role_id", sa.String(), nullable=True),
            )
            batch_op.create_foreign_key(
                "fk_sub_org_memberships_role_id",
                "roles", ["role_id"], ["id"],
            )
            batch_op.create_index(
                "ix_sub_org_memberships_role_id", ["role_id"], unique=False,
            )

    # -----------------------------------------------------------------
    # 2. Backfill sub_org_memberships.role_id from the legacy `role`
    #    column. Look up the PARENT org's Role row matching the legacy
    #    string (with "owner" -> "steward" rename baked in). Sub-orgs
    #    inherit the parent's matrix wholesale; there is no per-sub-org
    #    `roles` row.
    # -----------------------------------------------------------------
    if _has_column("sub_org_memberships", "role"):
        memberships = bind.execute(sa.text(
            "SELECT som.id, som.role, o.parent_org_id "
            "FROM sub_org_memberships som "
            "JOIN organizations o ON o.id = som.sub_org_id "
            "WHERE som.role_id IS NULL"
        )).fetchall()
        for m_id, m_role, parent_org_id in memberships:
            if parent_org_id is None:
                # Defensive: a sub_org_membership pointing at a non-sub-org
                # is malformed. Skip; the NOT NULL flip below will detect
                # this if it ever happens.
                continue
            target_system_key = _ROLE_RENAME.get(m_role, m_role)
            row = bind.execute(sa.text(
                "SELECT id FROM roles "
                "WHERE org_id = :org_id AND system_key = :sk"
            ), {"org_id": parent_org_id, "sk": target_system_key}).first()
            if row is None:
                # Defensive fallback to the parent's Member role. Phase 12
                # Stage 1 seeded all four presets per org, so this branch
                # should never fire; if it does, prefer the lossy fallback
                # over leaving role_id NULL (which blocks step 3).
                row = bind.execute(sa.text(
                    "SELECT id FROM roles "
                    "WHERE org_id = :org_id AND system_key = 'member'"
                ), {"org_id": parent_org_id}).first()
            if row is None:
                continue
            bind.execute(sa.text(
                "UPDATE sub_org_memberships SET role_id = :role_id "
                "WHERE id = :id"
            ), {"role_id": row[0], "id": m_id})
    else:
        # Fresh DB path (create_all already populated sub_org_memberships
        # without the legacy `role` column). Backfill remaining NULL
        # role_id rows to the parent org's Member role.
        memberships = bind.execute(sa.text(
            "SELECT som.id, o.parent_org_id "
            "FROM sub_org_memberships som "
            "JOIN organizations o ON o.id = som.sub_org_id "
            "WHERE som.role_id IS NULL"
        )).fetchall()
        for m_id, parent_org_id in memberships:
            if parent_org_id is None:
                continue
            row = bind.execute(sa.text(
                "SELECT id FROM roles "
                "WHERE org_id = :org_id AND system_key = 'member'"
            ), {"org_id": parent_org_id}).first()
            if row is None:
                continue
            bind.execute(sa.text(
                "UPDATE sub_org_memberships SET role_id = :role_id "
                "WHERE id = :id"
            ), {"role_id": row[0], "id": m_id})

    # -----------------------------------------------------------------
    # 3. Flip role_id to NOT NULL (only if no remaining NULL rows)
    # -----------------------------------------------------------------
    null_count = bind.execute(sa.text(
        "SELECT COUNT(*) FROM sub_org_memberships WHERE role_id IS NULL"
    )).scalar() or 0
    if null_count == 0:
        with op.batch_alter_table("sub_org_memberships", schema=None) as batch_op:
            batch_op.alter_column(
                "role_id", existing_type=sa.String(), nullable=False,
            )

    # -----------------------------------------------------------------
    # 4. Drop the legacy `role` string column
    # -----------------------------------------------------------------
    if _has_column("sub_org_memberships", "role"):
        with op.batch_alter_table("sub_org_memberships", schema=None) as batch_op:
            batch_op.drop_column("role")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    def _has_column(table: str, column: str) -> bool:
        try:
            return column in {c['name'] for c in inspector.get_columns(table)}
        except Exception:
            return False

    if "sub_org_memberships" not in set(inspector.get_table_names()):
        return

    # -----------------------------------------------------------------
    # 1. Re-add the legacy `role` string column (nullable initially so
    #    the backfill can populate before flipping NOT NULL).
    # -----------------------------------------------------------------
    if not _has_column("sub_org_memberships", "role"):
        with op.batch_alter_table("sub_org_memberships", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "role", sa.String(),
                    nullable=False, server_default="member",
                ),
            )

    # -----------------------------------------------------------------
    # 2. Backfill `role` from roles.system_key joined via role_id, with
    #    the inverse "steward" -> "owner" rename baked in. Lossy on
    #    custom Stewards (see module docstring).
    # -----------------------------------------------------------------
    if "roles" in set(inspector.get_table_names()) and _has_column(
        "sub_org_memberships", "role_id"
    ):
        rows = bind.execute(sa.text(
            "SELECT som.id, r.system_key "
            "FROM sub_org_memberships som "
            "JOIN roles r ON r.id = som.role_id"
        )).fetchall()
        for m_id, system_key in rows:
            legacy_role = _ROLE_RENAME_INVERSE.get(system_key, "member")
            bind.execute(sa.text(
                "UPDATE sub_org_memberships SET role = :role WHERE id = :id"
            ), {"role": legacy_role, "id": m_id})

    # -----------------------------------------------------------------
    # 3. Drop the role_id FK column.
    # -----------------------------------------------------------------
    if _has_column("sub_org_memberships", "role_id"):
        try:
            op.drop_index(
                "ix_sub_org_memberships_role_id",
                table_name="sub_org_memberships",
            )
        except Exception:
            pass
        # Same SQLite-batch caveat as Phase 12 Stage 1's downgrade: the
        # FK might have been created without our explicit name (test
        # path via create_all), so we just drop the column and let the
        # batch rebuild reconstruct without the FK.
        with op.batch_alter_table("sub_org_memberships", schema=None) as batch_op:
            batch_op.drop_column("role_id")
