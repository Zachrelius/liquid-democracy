"""Phase 23: demo reset infrastructure — Organization demo flag + persona +
branding columns, plus users.headshot_url.

Revision ID: c7e8a3d419f5
Revises: 9a8920b1f3c7
Create Date: 2026-05-12 09:00:00.000000

What this does
--------------

Adds the schema foundation Phase 23's demo daily reset depends on:

1. **`organizations.is_demo`** (Boolean, NOT NULL, default False).
   The load-bearing safety flag — the reset job only touches rows where
   ``is_demo = True``. Real orgs are immune.

2. **`organizations.is_demo_resetting`** (Boolean, NOT NULL, default False).
   Per-org reset-in-progress lock (D20). Frontend reads this to show a
   "Demo refreshing..." overlay; cleared once the reset transaction
   commits.

3. **`organizations.governance_type`** (String(50), nullable).
   Directory-card label ("Homeowners' Association", "Labor Union Local",
   "Civic Advocacy Group" — see Amendment E). Seeded from per-org config,
   not the bible. Real orgs leave NULL.

4. **`organizations.display_order`** (Integer, nullable).
   Bible-curated card ordering on `/demo` (D23). Real orgs leave NULL,
   sort as NULLS LAST.

5. **`organizations.personas`** (JSON, nullable).
   Per-org demo persona allowlist (D25). Each entry has shape
   ``{"username": str, "display_name": str, "role": str, "description": str}``.
   Drives the directory cards and the `/api/auth/demo-login` per-org
   validation. We use ``sa.JSON`` (not JSONB) — SQLAlchemy adapts to
   the right native type per dialect: PG gets JSONB-friendly storage,
   SQLite stores as TEXT with the JSON1 helpers. Phase 4c uses the same
   pattern on ``organizations.settings`` and ``proposals.options``.

6. **`organizations.brand_color`** (String(7), nullable).
   Hex color like ``#3A7CA5`` for governance-type label tinting on the
   directory cards and per-org banner accent on ``OrgPublicLanding``.
   Phase 24 prep — Phase 23 leaves NULL (Amendment F).

7. **`organizations.brand_secondary_color`** (String(7), nullable).
   Optional secondary hex color. Phase 24 prep, NULL in Phase 23.

8. **`organizations.logo_url`** (String(500), nullable).
   Path to a static asset under ``frontend/public/demo_assets/`` (e.g.
   ``/demo_assets/cedar-hollow-logo.svg``). Phase 24 prep, NULL in
   Phase 23.

9. **Index `ix_organizations_is_demo`** on ``(is_demo,)`` for the load-bearing
   reset-job filter (D1). The dispatch suggested ``idx_organizations_is_demo``
   but the codebase uses the ``ix_`` prefix consistently (alembic's default
   index naming convention); keeping the convention so future downgrades
   that rely on naming continue to work uniformly.

10. **`users.headshot_url`** (String(500), nullable).
    Per-person headshot asset path (e.g. ``/demo_assets/janet_reilly.jpg``).
    Placed on ``users`` rather than ``DelegateProfile`` because the Stage 8
    example is a single image per person — not per-org-per-topic. This
    mirrors the Phase 9.8 ``avatar_url`` pattern (one image per user) and
    keeps the demo branding asset surface profile-agnostic. Phase 24 prep,
    NULL in Phase 23.

Notes / risks
-------------

- **SQLite + PG compatible.** ``batch_alter_table`` is used for every
  column add on ``organizations`` so the SQLite path works (table-rebuild).
  PG sees a sequence of native ``ALTER TABLE ADD COLUMN`` statements
  via batch's auto-detection. Pattern matches Phase 8.5
  (``d41a8c92f3b1``) and Phase 13.3 (``b9e2f4a17c83``).

- **JSON column dialect:** ``sa.JSON()`` adapts to PG's native ``jsonb``
  column at the driver layer when available; on SQLite it's stored as
  ``TEXT`` with JSON1 helpers. No data migration required. SQLAlchemy
  serializes/deserializes via ``json.dumps`` / ``json.loads`` on both
  dialects.

- **Idempotent introspect-and-skip pattern** — re-running upgrade is a
  no-op once columns exist (Phase 8.6 / Phase 9.5 / Phase 9.8 pattern).
  Important for the ``start.sh`` flow that runs ``create_tables`` before
  ``alembic upgrade head``.

- **No data migration required.** All new columns are either nullable or
  have a default; existing rows take the default automatically.

Downgrade
---------

Drops the index, then drops each column. SQLite path uses
``batch_alter_table``; PG path uses ``ALTER TABLE ... DROP COLUMN``
directly because PG handles drops natively without table rebuild.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c7e8a3d419f5'
down_revision: Union[str, None] = '9a8920b1f3c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_tables(inspector) -> set[str]:
    try:
        return set(inspector.get_table_names())
    except Exception:
        return set()


def _existing_columns(inspector, table: str) -> set[str]:
    try:
        return {c["name"] for c in inspector.get_columns(table)}
    except Exception:
        return set()


def _existing_indexes(inspector, table: str) -> set[str]:
    try:
        return {ix["name"] for ix in inspector.get_indexes(table)}
    except Exception:
        return set()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = _existing_tables(inspector)

    # ----- 1. organizations: 8 new columns -------------------------------
    if "organizations" in tables:
        org_cols = _existing_columns(inspector, "organizations")

        with op.batch_alter_table("organizations", schema=None) as batch_op:
            if "is_demo" not in org_cols:
                batch_op.add_column(
                    sa.Column(
                        "is_demo",
                        sa.Boolean(),
                        nullable=False,
                        server_default=sa.false(),
                    ),
                )
            if "is_demo_resetting" not in org_cols:
                batch_op.add_column(
                    sa.Column(
                        "is_demo_resetting",
                        sa.Boolean(),
                        nullable=False,
                        server_default=sa.false(),
                    ),
                )
            if "governance_type" not in org_cols:
                batch_op.add_column(
                    sa.Column(
                        "governance_type",
                        sa.String(length=50),
                        nullable=True,
                    ),
                )
            if "display_order" not in org_cols:
                batch_op.add_column(
                    sa.Column(
                        "display_order",
                        sa.Integer(),
                        nullable=True,
                    ),
                )
            if "personas" not in org_cols:
                batch_op.add_column(
                    sa.Column(
                        "personas",
                        sa.JSON(),
                        nullable=True,
                    ),
                )
            if "brand_color" not in org_cols:
                batch_op.add_column(
                    sa.Column(
                        "brand_color",
                        sa.String(length=7),
                        nullable=True,
                    ),
                )
            if "brand_secondary_color" not in org_cols:
                batch_op.add_column(
                    sa.Column(
                        "brand_secondary_color",
                        sa.String(length=7),
                        nullable=True,
                    ),
                )
            if "logo_url" not in org_cols:
                batch_op.add_column(
                    sa.Column(
                        "logo_url",
                        sa.String(length=500),
                        nullable=True,
                    ),
                )

        # ----- 2. ix_organizations_is_demo index -------------------------
        # Re-inspect after batch (batch_alter_table on SQLite rebuilds the
        # table, which can drop+recreate the index list).
        org_indexes = _existing_indexes(sa.inspect(bind), "organizations")
        if "ix_organizations_is_demo" not in org_indexes:
            op.create_index(
                "ix_organizations_is_demo",
                "organizations",
                ["is_demo"],
                unique=False,
            )

    # ----- 3. users.headshot_url -----------------------------------------
    if "users" in tables:
        user_cols = _existing_columns(sa.inspect(bind), "users")
        if "headshot_url" not in user_cols:
            with op.batch_alter_table("users", schema=None) as batch_op:
                batch_op.add_column(
                    sa.Column(
                        "headshot_url",
                        sa.String(length=500),
                        nullable=True,
                    ),
                )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    inspector = sa.inspect(bind)
    tables = _existing_tables(inspector)

    # ----- 3 (reverse). users.headshot_url -------------------------------
    if "users" in tables:
        user_cols = _existing_columns(inspector, "users")
        if "headshot_url" in user_cols:
            if dialect == "postgresql":
                op.execute(
                    "ALTER TABLE users DROP COLUMN IF EXISTS headshot_url CASCADE"
                )
            else:
                with op.batch_alter_table("users", schema=None) as batch_op:
                    batch_op.drop_column("headshot_url")

    # ----- 2 (reverse). Drop index first ---------------------------------
    if "organizations" in tables:
        org_indexes = _existing_indexes(sa.inspect(bind), "organizations")
        if "ix_organizations_is_demo" in org_indexes:
            if dialect == "postgresql":
                op.execute("DROP INDEX IF EXISTS ix_organizations_is_demo")
            else:
                # SQLite: drop index outside of batch (op.drop_index works
                # directly; batch's drop_index is only needed when dropping
                # the indexed column simultaneously).
                op.drop_index(
                    "ix_organizations_is_demo",
                    table_name="organizations",
                )

    # ----- 1 (reverse). organizations: drop 8 columns --------------------
    if "organizations" in tables:
        org_cols = _existing_columns(sa.inspect(bind), "organizations")
        new_cols = (
            "logo_url",
            "brand_secondary_color",
            "brand_color",
            "personas",
            "display_order",
            "governance_type",
            "is_demo_resetting",
            "is_demo",
        )
        if dialect == "postgresql":
            for col in new_cols:
                if col in org_cols:
                    op.execute(
                        f"ALTER TABLE organizations DROP COLUMN IF EXISTS {col} CASCADE"
                    )
        else:
            with op.batch_alter_table("organizations", schema=None) as batch_op:
                for col in new_cols:
                    if col in org_cols:
                        batch_op.drop_column(col)
