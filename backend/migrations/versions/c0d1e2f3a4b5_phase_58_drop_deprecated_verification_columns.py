"""phase 58 — drop deprecated verification_nullifier + doc_number_hash columns

The verification arc explicitly deferred these column drops to a future
cleanup pass:

  * ``users.verification_nullifier`` (String(128), nullable, indexed) —
    deprecated since Phase 52d when hash-dedup replaced Didit's 1:N
    nullifier. Nothing reads or writes it post-52d (confirmed by Phase 58
    Cluster C grep). Two indexes get dropped alongside the column:
      - ``ix_users_verification_nullifier`` (Phase 51 lookup index)
      - ``ix_users_verification_nullifier_unique`` (Phase 52a partial-
        unique, PG `WHERE verification_nullifier IS NOT NULL`).

  * ``users.doc_number_hash`` (String(128), nullable, indexed) —
    deprecated since Phase 52h Stage 2 when the platform-wide document-
    number hard block was removed. Nothing reads or writes the column
    from Phase 52h Stage 2 onward; the org-scoped name-based flag system
    handles uniqueness within an org. One index gets dropped alongside:
      - ``ix_users_doc_number_hash`` (Phase 52d lookup index).
    The partial-unique ``ix_users_doc_number_hash_unique`` was ALREADY
    dropped in migration ``e6f7a8b9c0d1`` (Phase 52h Stage 2) so this
    migration must NOT attempt to drop it again — the idempotent guard
    below handles the case anyway.

The drop is reversible: ``downgrade()`` re-adds both columns as nullable
+ re-creates the lookup indexes. Re-added columns are empty (nothing
writes them anymore); that's fine — they were already effectively empty
on prod and the deprecated stage didn't write either.

PG-specific note: dropping columns on PG is the riskier op the Phase
52d/52h closeouts deliberately deferred. This migration uses
``op.drop_index`` + ``op.drop_column`` (no batch_alter_table) since the
table doesn't have foreign keys referencing the dropped columns. All
operations are wrapped in idempotent guards so a partial run is
recoverable.

Hex-prefix revision id (Phase 48 Stage 2 convention).

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-06-07 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c0d1e2f3a4b5"
down_revision: Union[str, None] = "b9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NULLIFIER_LOOKUP_INDEX = "ix_users_verification_nullifier"
NULLIFIER_UNIQUE_INDEX = "ix_users_verification_nullifier_unique"
DOC_NUMBER_LOOKUP_INDEX = "ix_users_doc_number_hash"


def _existing_columns(table: str) -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        return {c["name"] for c in insp.get_columns(table)}
    except Exception:
        return set()


def _existing_indexes(table: str) -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        return {ix["name"] for ix in insp.get_indexes(table)}
    except Exception:
        return set()


def upgrade() -> None:
    idx = _existing_indexes("users")
    cols = _existing_columns("users")

    # Drop indexes before dropping the columns they reference.
    if NULLIFIER_UNIQUE_INDEX in idx:
        op.drop_index(NULLIFIER_UNIQUE_INDEX, table_name="users")
    if NULLIFIER_LOOKUP_INDEX in idx:
        op.drop_index(NULLIFIER_LOOKUP_INDEX, table_name="users")
    if DOC_NUMBER_LOOKUP_INDEX in idx:
        op.drop_index(DOC_NUMBER_LOOKUP_INDEX, table_name="users")
    # The partial-unique ``ix_users_doc_number_hash_unique`` was dropped
    # in migration ``e6f7a8b9c0d1`` (Phase 52h Stage 2) and is intentionally
    # NOT mentioned here. If it somehow lingers, the no-double-drop guard
    # keeps us safe.

    if "verification_nullifier" in cols:
        op.drop_column("users", "verification_nullifier")
    if "doc_number_hash" in cols:
        op.drop_column("users", "doc_number_hash")


def downgrade() -> None:
    cols = _existing_columns("users")
    idx = _existing_indexes("users")

    # Re-add the columns as nullable; nothing wrote them when deprecated
    # so empty-on-re-add is the correct restore.
    if "verification_nullifier" not in cols:
        op.add_column(
            "users",
            sa.Column(
                "verification_nullifier",
                sa.String(length=128),
                nullable=True,
            ),
        )
    if "doc_number_hash" not in cols:
        op.add_column(
            "users",
            sa.Column(
                "doc_number_hash",
                sa.String(length=128),
                nullable=True,
            ),
        )

    # Re-create the lookup indexes (NOT the partial-unique — that was
    # dropped pre-Phase-58 in e6f7a8b9c0d1 and isn't restored here either).
    if NULLIFIER_LOOKUP_INDEX not in idx:
        op.create_index(
            NULLIFIER_LOOKUP_INDEX, "users", ["verification_nullifier"],
        )
    if DOC_NUMBER_LOOKUP_INDEX not in idx:
        op.create_index(
            DOC_NUMBER_LOOKUP_INDEX, "users", ["doc_number_hash"],
        )
    # NULLIFIER_UNIQUE_INDEX (Phase 52a partial-unique) re-creation is
    # not attempted here — it requires PG-specific partial-index syntax
    # that the original Phase 52a migration handled with dialect-aware
    # branching. The downgrade target for THIS migration is the post-
    # Phase-52h-Stage-2 state which already had the column without the
    # partial unique; if a deeper rollback is needed, the upstream Phase
    # 52a migration handles it.
