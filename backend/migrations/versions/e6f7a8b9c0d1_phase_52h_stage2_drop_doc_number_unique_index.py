"""phase 52h stage 2 — drop platform-wide doc_number_hash unique index

Removes the partial-unique index that enforced the platform-wide
"one document = one account" hard block. Per the spec's locked
principle (confidence-determines-scope, harm is org-scoped), cross-
org duplicate accounts for the same person are not a harm we
prevent at the platform layer — the org-scoped name-based flag
system (Phase 52e Stage 2 + Phase 52h Stage 1) handles in-org
duplication, biometric is the deferred stronger tier.

What this migration does:
  * Drop ``ix_users_doc_number_hash_unique`` (the partial-unique
    index, PG ``WHERE doc_number_hash IS NOT NULL``).
  * Leave the ``users.doc_number_hash`` COLUMN in place — dropping
    columns on PG is the riskier op; this stage drops only what
    enforces the platform-wide block, and the column is marked
    deprecated in the model. The eventual column drop batches with
    the deprecated ``verification_nullifier`` cleanup in a future
    pass.
  * Leave the non-unique lookup index ``ix_users_doc_number_hash``
    in place — it's harmless (the column is no longer written, so
    the index never grows) and dropping it doesn't affect
    correctness. The future cleanup pass that drops the column
    will drop this too.

Code-side companions (NOT in this migration; in the Stage 2
commit):
  * ``verification_hashing.compute_hashes`` stops computing
    doc_number_hash (returns None for it; existing callers
    unaffected — the key still exists, just always None).
  * ``routes/verification._apply_decision`` removes the collision
    lookup, the ``collision_rejected`` branch, the
    ``verification.duplicate_document`` audit, and the
    ``doc_number_unique=`` argument to the mapper.
  * ``verification_provider.map_decision_to_state`` drops the
    ``doc_number_unique`` parameter and the ``IDENTITY_UNIQUE``
    rung's auto-assignment (Z-locked Option A: post-removal,
    verification proves identity + residency only; platform-wide
    uniqueness is not claimed).
  * The IntegrityError catch for the doc-hash unique-index race
    in the webhook handler is removed.

Hex-prefix revision id. Reversible (re-creates the index on
downgrade).

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-06-06 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DOC_NUMBER_UNIQUE_INDEX = "ix_users_doc_number_hash_unique"


def _existing_indexes(table: str) -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        return {ix["name"] for ix in insp.get_indexes(table)}
    except Exception:
        return set()


def upgrade() -> None:
    indexes = _existing_indexes("users")
    if DOC_NUMBER_UNIQUE_INDEX in indexes:
        op.drop_index(DOC_NUMBER_UNIQUE_INDEX, table_name="users")


def downgrade() -> None:
    indexes = _existing_indexes("users")
    if DOC_NUMBER_UNIQUE_INDEX not in indexes:
        bind = op.get_bind()
        if bind.dialect.name == "postgresql":
            op.create_index(
                DOC_NUMBER_UNIQUE_INDEX, "users", ["doc_number_hash"],
                unique=True,
                postgresql_where=sa.text(
                    "doc_number_hash IS NOT NULL"
                ),
            )
        else:
            op.create_index(
                DOC_NUMBER_UNIQUE_INDEX, "users", ["doc_number_hash"],
                unique=True,
            )
