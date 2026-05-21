"""Phase 33 D1 + D2: legacy column drops.

Drops two columns that have become vestigial as the schema evolved:

- ``delegate_profiles.is_active`` (Phase 33 D1). The column used to gate
  the legacy /api/delegates/register lifecycle (register sets True, the
  parallel deactivate endpoint sets False). Phase 19 introduced the
  per-topic ``visibility`` enum (private / followers_only / public /
  public_accepting) and Phase 30 retired the legacy register flow from
  the frontend. The column has been ``True`` for every row created via
  the current public-delegate flow since Phase 19; Phase 33 removes the
  legacy endpoints + drops the column.

- ``topics.description`` (Phase 33 D2). Phase 30.1's root-cause fix made
  ``topics.name`` the canonical display name (uniquely scoped per org via
  ``UniqueConstraint("org_id", "name")``). ``description`` was a
  same-value clone preserved for back-compat; new code reads ``name``
  exclusively. Phase 33 drops it.

Reversible: down() re-adds both columns with their original defaults so
a downgrade from Phase 33 → Phase 32.2 produces a working schema (the
re-added columns will be empty for newly-inserted rows but that's
matches the column's original behavior at creation time).

Spec: phase33_tech_debt_audit_refresh_spec.md §D1, §D2, §M
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "b6d8e2f1a350"
down_revision = "e7a3d1c84920"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ---- D1: delegate_profiles.is_active ----
    dp_cols = {c["name"] for c in inspector.get_columns("delegate_profiles")}
    if "is_active" in dp_cols:
        with op.batch_alter_table("delegate_profiles") as batch:
            batch.drop_column("is_active")

    # ---- D2: topics.description ----
    topic_cols = {c["name"] for c in inspector.get_columns("topics")}
    if "description" in topic_cols:
        with op.batch_alter_table("topics") as batch:
            batch.drop_column("description")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ---- D2 down: topics.description re-added ----
    topic_cols = {c["name"] for c in inspector.get_columns("topics")}
    if "description" not in topic_cols:
        with op.batch_alter_table("topics") as batch:
            batch.add_column(
                sa.Column(
                    "description",
                    sa.String(),
                    nullable=False,
                    server_default="",
                )
            )

    # ---- D1 down: delegate_profiles.is_active re-added (default True) ----
    dp_cols = {c["name"] for c in inspector.get_columns("delegate_profiles")}
    if "is_active" not in dp_cols:
        with op.batch_alter_table("delegate_profiles") as batch:
            batch.add_column(
                sa.Column(
                    "is_active",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.true(),
                )
            )
