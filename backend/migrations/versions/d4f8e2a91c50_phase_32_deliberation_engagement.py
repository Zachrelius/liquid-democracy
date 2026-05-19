"""Phase 32 — deliberation engagement: write-ins + pre-voting + author edits.

Revision ID: d4f8e2a91c50
Revises: c7d4e0a91f23
Create Date: 2026-05-19 12:00:00.000000

Single migration covering Phase 32's three coupled sub-features:

1. **Write-in attribution** on ``proposal_options``: ``added_by_user_id``
   (FK to ``users.id``), ``added_at`` (timestamp), ``is_write_in``
   (boolean). Existing rows backfill to ``is_write_in=False``,
   ``added_by_user_id=NULL``, ``added_at=NULL`` — Phase 32 D22 says
   pre-existing proposals are unaffected.

2. **Per-proposal override flags** on ``proposals``:
     - ``allow_write_in_options`` (bool, nullable; null = inherit org)
     - ``allow_write_ins_during_voting`` (bool, nullable)
     - ``max_write_ins`` (int, nullable; null = inherit org default)
     - ``allow_pre_voting`` (bool, nullable)
     - ``show_votes_during_deliberation`` (bool, nullable)
     - ``edit_lockout_fraction`` (float, nullable; null = inherit org)
   All nullable so existing rows default to "behavior unchanged" per D22.

3. **``proposal_revisions`` table** for the author-edit change log. New
   relationship table follows the Phase 18 multi-tenancy convention:
   ``org_id`` is on the row from day one (NOT NULL). ``changed_fields``
   is stored as JSON for SQLite/PG dialect parity (SQLite has no native
   ARRAY type).

Org-level settings (``write_ins.*``, ``pre_voting.*``,
``proposal_edits.*``) live inside the existing ``organizations.settings``
JSONB column — no schema migration needed for JSONB additions; defaults
are provided at app level.

Reversible. Downgrade drops the table + columns. Subprocess test
exercises upgrade → downgrade → upgrade on SQLite.

Spec: phase32_deliberation_engagement_spec.md
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d4f8e2a91c50"
down_revision = "c7d4e0a91f23"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    inspector = sa.inspect(bind)

    def _has_col(table: str, col: str) -> bool:
        return col in {c["name"] for c in inspector.get_columns(table)}

    def _has_table(table: str) -> bool:
        return table in set(inspector.get_table_names())

    # Idempotent guards. The migration_cycle test pattern (Phase 12.5,
    # 15, 12, 12-stage2) builds schema via ``create_tables()`` then stamps
    # at the prior revision, so when we walk forward to head, the
    # Phase 32 columns/table may already exist. Skip individual operations
    # whose target already matches the desired state.

    # ---- 1. proposal_options: write-in attribution columns ----------------
    # SQLite batch_alter_table can hit a CircularDependencyError when
    # multiple columns are added in a single batch — the dependency
    # graph of the rebuild cycles through sibling column adds. One
    # batch per column avoids the issue. Order: plain columns first,
    # FK column last (the FK adds an extra constraint participant).
    if not _has_col("proposal_options", "is_write_in"):
        with op.batch_alter_table("proposal_options") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "is_write_in",
                    sa.Boolean(),
                    nullable=False,
                    server_default=(
                        sa.text("0") if not is_pg else sa.text("false")
                    ),
                )
            )
    if not _has_col("proposal_options", "added_at"):
        with op.batch_alter_table("proposal_options") as batch_op:
            batch_op.add_column(
                sa.Column("added_at", sa.DateTime(), nullable=True)
            )
    if not _has_col("proposal_options", "added_by_user_id"):
        with op.batch_alter_table("proposal_options") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "added_by_user_id",
                    sa.String(),
                    sa.ForeignKey(
                        "users.id",
                        name="fk_proposal_options_added_by_user_id_users",
                    ),
                    nullable=True,
                )
            )

    # ---- 2. proposals: per-proposal override flags ------------------------
    # One batch per column for the same reason as section 1.
    _proposal_cols = [
        ("allow_write_in_options", sa.Boolean()),
        ("allow_write_ins_during_voting", sa.Boolean()),
        ("max_write_ins", sa.Integer()),
        ("allow_pre_voting", sa.Boolean()),
        ("show_votes_during_deliberation", sa.Boolean()),
        ("edit_lockout_fraction", sa.Float()),
    ]
    for col_name, col_type in _proposal_cols:
        if not _has_col("proposals", col_name):
            with op.batch_alter_table("proposals") as batch_op:
                batch_op.add_column(
                    sa.Column(col_name, col_type, nullable=True)
                )

    # ---- 3. proposal_revisions table --------------------------------------
    if _has_table("proposal_revisions"):
        return
    op.create_table(
        "proposal_revisions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "proposal_id",
            sa.String(),
            sa.ForeignKey("proposals.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "org_id",
            sa.String(),
            sa.ForeignKey("organizations.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "edited_by_user_id",
            sa.String(),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("edited_at", sa.DateTime(), nullable=False),
        sa.Column("snapshot_before", sa.JSON(), nullable=False),
        sa.Column("snapshot_after", sa.JSON(), nullable=False),
        sa.Column("changed_fields", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("proposal_revisions")

    with op.batch_alter_table("proposals") as batch_op:
        batch_op.drop_column("edit_lockout_fraction")
        batch_op.drop_column("show_votes_during_deliberation")
        batch_op.drop_column("allow_pre_voting")
        batch_op.drop_column("max_write_ins")
        batch_op.drop_column("allow_write_ins_during_voting")
        batch_op.drop_column("allow_write_in_options")

    # SQLite batch_alter_table can hit a CircularDependencyError when
    # dropping an FK column in the same batch as its plain-column
    # siblings; the FK metadata participates in the rebuild's
    # dependency graph. Drop the FK constraint explicitly first, then
    # drop the columns in a separate batch.
    with op.batch_alter_table("proposal_options") as batch_op:
        batch_op.drop_constraint(
            "fk_proposal_options_added_by_user_id_users",
            type_="foreignkey",
        )
    with op.batch_alter_table("proposal_options") as batch_op:
        batch_op.drop_column("is_write_in")
        batch_op.drop_column("added_at")
        batch_op.drop_column("added_by_user_id")
