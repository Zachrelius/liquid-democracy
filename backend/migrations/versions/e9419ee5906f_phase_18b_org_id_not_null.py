"""Phase 18b: flip org_id to NOT NULL on the four relationship tables.

Revision ID: e9419ee5906f
Revises: 1cc8f3f27717
Create Date: 2026-05-10 00:00:00.000000

What this does
--------------

Phase 18a (`219205801d2c`) added nullable ``org_id`` columns to
``delegations``, ``delegation_intents``, ``follow_relationships``, and
``follow_requests``, then ran a three-sweep backfill. Phase 18a follow-up
(`1cc8f3f27717`) updated the follow tables' unique constraints to
include ``org_id``.

This migration completes the two-phase upgrade: it asserts zero
remaining ``org_id IS NULL`` rows across all four tables, then flips
the column to ``NOT NULL``. ``sub_org_id`` (on delegations + intents)
stays nullable — sub-orgs are an optional scope.

Pre-flight gate
---------------

Before any ALTER, ``upgrade()`` runs SELECT COUNT(*) on each table for
``org_id IS NULL`` rows. If any are non-zero, the migration aborts
LOUDLY with the row IDs in the error message — Z's manual intervention
is required before re-running. This is the failure mode the spec calls
out at line 88-90: "deploy fails loudly here rather than silently
dropping data."

Why this matters: Phase 18a's backfill is best-effort — if a row's
backfill is ambiguous beyond the heuristic (e.g., parties share zero
orgs, which shouldn't happen in prod but could in pathological data),
18a logs a WARNING and leaves ``org_id`` NULL. 18b is the gate that
catches those edge cases at constraint-application time.

Downgrade
---------

``ALTER COLUMN org_id SET NULL``. Rows backfilled in 18a are not
"unbackfilled" — that data is durable. Downgrade only loosens the
constraint, doesn't reverse the data backfill.
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = 'e9419ee5906f'
down_revision: Union[str, None] = '1cc8f3f27717'
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


_TABLES = (
    "delegations",
    "delegation_intents",
    "follow_relationships",
    "follow_requests",
)


def _assert_no_null_org_ids(bind) -> None:
    """Pre-flight: every relationship table must have zero ``org_id IS NULL``
    rows before we can flip the column to NOT NULL. Aborts with row IDs if
    any are found."""
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    bad_rows: dict[str, list[str]] = {}
    for table in _TABLES:
        if table not in existing_tables:
            # Defensive: shouldn't happen in normal flow but skip gracefully.
            continue
        result = bind.execute(
            sa.text(f"SELECT id FROM {table} WHERE org_id IS NULL LIMIT 20")
        ).fetchall()
        if result:
            bad_rows[table] = [row[0] for row in result]

    if bad_rows:
        # Build a clear error message naming each row so Z can investigate.
        msg_parts = ["Phase 18b aborted: rows with org_id IS NULL detected."]
        for table, ids in bad_rows.items():
            msg_parts.append(
                f"  {table}: {len(ids)} row(s) shown (limit 20): "
                f"{', '.join(ids[:20])}"
            )
        msg_parts.append(
            "Resolve manually (assign org_id via SELECT/UPDATE) before "
            "re-running this migration. The Phase 18a backfill should have "
            "covered all rows; if any are still NULL, that's a bug in the "
            "heuristic or pathological pre-existing data."
        )
        raise RuntimeError("\n".join(msg_parts))


def upgrade() -> None:
    bind = op.get_bind()

    # Pre-flight: zero NULLs across all four tables. Aborts loudly if any.
    _assert_no_null_org_ids(bind)

    # Flip org_id to NOT NULL on each table. Use batch_alter_table so SQLite
    # gets the table-rebuild treatment; Postgres handles in-place ALTER.
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    for table in _TABLES:
        if table not in existing_tables:
            continue
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.alter_column(
                "org_id", existing_type=sa.String(), nullable=False,
            )


def downgrade() -> None:
    """Loosen the constraint back to nullable. The backfilled data is
    durable — downgrade does NOT reverse the org_id assignments."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    for table in _TABLES:
        if table not in existing_tables:
            continue
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.alter_column(
                "org_id", existing_type=sa.String(), nullable=True,
            )
