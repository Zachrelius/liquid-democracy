"""Phase 30.3 — visibility consolidation: new `followers_only` ladder
value, backfill of `private` → `followers_only`, drop of the
`OrgDelegateProfile.page_visibility` column + its supporting enum.

Revision ID: c7d4e0a91f23
Revises: b9e3f51c2a40
Create Date: 2026-05-17 10:00:00.000000

Phase 30.3 collapses the two-layer visibility model (`OrgDelegateProfile.
page_visibility` × per-topic `DelegateProfile.visibility`) into a single
per-topic ladder:

    private  <  followers_only  <  public  <  public_accepting

Default for new ``DelegateProfile`` rows shifts from ``private`` to
``followers_only`` (preserves the de-facto pre-Phase-30.3 behavior where
any FollowRelationship row granted vote visibility).

Backfill: every existing ``private`` row is migrated to ``followers_only``.
This is **information-lossy on downgrade** — the downgrade restores rows
to ``private`` indiscriminately, including rows that were created at
``followers_only`` post-Phase-30.3 and never were ``private``. Downgrade
is operational rollback, not production-grade reversal.

Postgres limitations:
  - ``ALTER TYPE ... ADD VALUE`` cannot run inside a transaction; the
    migration handles this with explicit transaction control.
  - There is no clean way to remove an enum value, so the downgrade
    leaves ``followers_only`` in the type vocabulary. Acceptable.

Spec: phase30_3_visibility_consolidation_dispatch_2026-05-17.md
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = "c7d4e0a91f23"
down_revision = "b9e3f51c2a40"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    # ---- B1: add the new enum value -----------------------------------
    if is_pg:
        # ALTER TYPE ADD VALUE must run outside any transaction block on
        # PG. Alembic wraps each migration in a transaction by default;
        # use COMMIT to break out and then resume.
        # Idempotent: IF NOT EXISTS skips if value already present (from
        # a prior partial run).
        with op.get_context().autocommit_block():
            bind.execute(text(
                "ALTER TYPE delegate_profile_visibility "
                "ADD VALUE IF NOT EXISTS 'followers_only' BEFORE 'public'"
            ))
    # SQLite: enums are stored as plain strings with a CHECK constraint.
    # Updating the constraint requires recreating the table; do it
    # inside batch_alter_table for a clean rewrite.
    else:
        with op.batch_alter_table("delegate_profiles") as batch_op:
            batch_op.alter_column(
                "visibility",
                existing_type=sa.Enum(
                    "private", "public", "public_accepting",
                    name="delegate_profile_visibility",
                ),
                type_=sa.Enum(
                    "private", "followers_only", "public", "public_accepting",
                    name="delegate_profile_visibility",
                ),
                existing_nullable=False,
                existing_server_default="public_accepting",
            )

    # ---- B2: backfill private → followers_only -----------------------
    bind.execute(text(
        "UPDATE delegate_profiles "
        "SET visibility = 'followers_only' "
        "WHERE visibility = 'private'"
    ))

    # ---- B3: drop org_delegate_profiles.page_visibility + its enum ---
    # Use batch_alter_table for SQLite compatibility; on PG this is an
    # in-place ALTER TABLE.
    inspector = sa.inspect(bind)
    odp_columns = {c["name"] for c in inspector.get_columns("org_delegate_profiles")}
    if "page_visibility" in odp_columns:
        with op.batch_alter_table("org_delegate_profiles") as batch_op:
            batch_op.drop_column("page_visibility")

    # Drop the supporting enum type on PG (no-op on SQLite — enums are
    # constraint-only there).
    if is_pg:
        bind.execute(text(
            "DROP TYPE IF EXISTS org_delegate_page_visibility"
        ))


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    # ---- Reverse B3: recreate the enum + column ----------------------
    if is_pg:
        bind.execute(text(
            "CREATE TYPE org_delegate_page_visibility AS ENUM "
            "('private', 'private_delegators')"
        ))
        op.add_column(
            "org_delegate_profiles",
            sa.Column(
                "page_visibility",
                sa.Enum(
                    "private", "private_delegators",
                    name="org_delegate_page_visibility",
                ),
                nullable=False,
                server_default="private",
            ),
        )
    else:
        with op.batch_alter_table("org_delegate_profiles") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "page_visibility",
                    sa.Enum(
                        "private", "private_delegators",
                        name="org_delegate_page_visibility",
                    ),
                    nullable=False,
                    server_default="private",
                ),
            )

    # ---- Reverse B2: followers_only → private (information-lossy) ----
    bind.execute(text(
        "UPDATE delegate_profiles "
        "SET visibility = 'private' "
        "WHERE visibility = 'followers_only'"
    ))

    # ---- Reverse B1: PG can't cleanly remove the enum value ----------
    # Leave 'followers_only' in the type vocabulary on PG. On SQLite,
    # recreate the column with the pre-Phase-30.3 enum set.
    if not is_pg:
        with op.batch_alter_table("delegate_profiles") as batch_op:
            batch_op.alter_column(
                "visibility",
                existing_type=sa.Enum(
                    "private", "followers_only", "public", "public_accepting",
                    name="delegate_profile_visibility",
                ),
                type_=sa.Enum(
                    "private", "public", "public_accepting",
                    name="delegate_profile_visibility",
                ),
                existing_nullable=False,
                existing_server_default="public_accepting",
                server_default="public_accepting",
            )
