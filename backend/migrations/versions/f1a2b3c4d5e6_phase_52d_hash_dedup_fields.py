"""phase 52d — hash-dedup fields on users

Adds four nullable columns to ``users`` for the document-hash dedup
model (replacing the dead Didit-1:N nullifier approach):

  * ``doc_number_hash`` (String(128), nullable, indexed) —
    PLATFORM-WIDE uniqueness invariant lives here. A partial unique
    index ``ix_users_doc_number_hash_unique`` is emitted; on
    PostgreSQL the WHERE clause is honored so the many NULL rows do
    not collide. On SQLite a plain unique index already treats NULLs
    as distinct, so the same logical guarantee holds without WHERE.
  * ``name_dob_address_hash`` (String(128), nullable, indexed) —
    org-scoped soft-flag input. NOT unique (matching is a lookup, not
    a constraint).
  * ``name_dob_hash`` (String(128), nullable, indexed) — org-scoped
    soft-flag input. NOT unique.
  * ``uniqueness_strength`` (String(16), nullable) — two-tier;
    ``document_hash`` (v1) or ``biometric`` (architected, deferred).

The pre-existing ``verification_nullifier`` column is DEPRECATED but
intentionally NOT dropped here. Dropping a partial-unique-indexed
column on PG is riskier than leaving it; nothing reads it as of
Phase 52d (``doc_number_hash`` is the live invariant), and a future
cleanup pass can drop both the column and
``ix_users_verification_nullifier_unique``.

Hex-prefix revision id (Phase 48 Stage 2 lesson). Reversible via
``batch_alter_table`` + ``drop_index``.

Revision ID: f1a2b3c4d5e6
Revises: e0a1b2c3d4f5
Create Date: 2026-06-04 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "e0a1b2c3d4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DOC_NUMBER_UNIQUE_INDEX = "ix_users_doc_number_hash_unique"
DOC_NUMBER_LOOKUP_INDEX = "ix_users_doc_number_hash"
NAME_DOB_ADDRESS_LOOKUP_INDEX = "ix_users_name_dob_address_hash"
NAME_DOB_LOOKUP_INDEX = "ix_users_name_dob_hash"


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
    cols = _existing_columns("users")
    to_add = []
    if "doc_number_hash" not in cols:
        to_add.append("doc_number_hash")
    if "name_dob_address_hash" not in cols:
        to_add.append("name_dob_address_hash")
    if "name_dob_hash" not in cols:
        to_add.append("name_dob_hash")
    if "uniqueness_strength" not in cols:
        to_add.append("uniqueness_strength")
    if to_add:
        with op.batch_alter_table("users") as batch_op:
            if "doc_number_hash" in to_add:
                batch_op.add_column(sa.Column(
                    "doc_number_hash", sa.String(length=128), nullable=True,
                ))
            if "name_dob_address_hash" in to_add:
                batch_op.add_column(sa.Column(
                    "name_dob_address_hash", sa.String(length=128), nullable=True,
                ))
            if "name_dob_hash" in to_add:
                batch_op.add_column(sa.Column(
                    "name_dob_hash", sa.String(length=128), nullable=True,
                ))
            if "uniqueness_strength" in to_add:
                batch_op.add_column(sa.Column(
                    "uniqueness_strength", sa.String(length=16), nullable=True,
                ))

    bind = op.get_bind()
    dialect = bind.dialect.name
    indexes = _existing_indexes("users")

    # Lookup-only indexes for the two name-based hashes.
    if NAME_DOB_ADDRESS_LOOKUP_INDEX not in indexes:
        op.create_index(
            NAME_DOB_ADDRESS_LOOKUP_INDEX, "users", ["name_dob_address_hash"],
        )
    if NAME_DOB_LOOKUP_INDEX not in indexes:
        op.create_index(
            NAME_DOB_LOOKUP_INDEX, "users", ["name_dob_hash"],
        )
    if DOC_NUMBER_LOOKUP_INDEX not in indexes:
        op.create_index(
            DOC_NUMBER_LOOKUP_INDEX, "users", ["doc_number_hash"],
        )

    # Partial-unique index on the document-number hash — the
    # platform-wide invariant. Repurposes the Phase 52a nullifier
    # partial-unique pattern (PG honors WHERE; SQLite treats NULLs
    # as distinct so the same DDL with no WHERE is fine).
    if DOC_NUMBER_UNIQUE_INDEX not in indexes:
        if dialect == "postgresql":
            op.create_index(
                DOC_NUMBER_UNIQUE_INDEX, "users", ["doc_number_hash"],
                unique=True,
                postgresql_where=sa.text("doc_number_hash IS NOT NULL"),
            )
        else:
            op.create_index(
                DOC_NUMBER_UNIQUE_INDEX, "users", ["doc_number_hash"],
                unique=True,
            )


def downgrade() -> None:
    indexes = _existing_indexes("users")
    if DOC_NUMBER_UNIQUE_INDEX in indexes:
        op.drop_index(DOC_NUMBER_UNIQUE_INDEX, table_name="users")
    if DOC_NUMBER_LOOKUP_INDEX in indexes:
        op.drop_index(DOC_NUMBER_LOOKUP_INDEX, table_name="users")
    if NAME_DOB_LOOKUP_INDEX in indexes:
        op.drop_index(NAME_DOB_LOOKUP_INDEX, table_name="users")
    if NAME_DOB_ADDRESS_LOOKUP_INDEX in indexes:
        op.drop_index(NAME_DOB_ADDRESS_LOOKUP_INDEX, table_name="users")

    cols = _existing_columns("users")
    to_drop = []
    for c in ("uniqueness_strength", "name_dob_hash",
              "name_dob_address_hash", "doc_number_hash"):
        if c in cols:
            to_drop.append(c)
    if to_drop:
        with op.batch_alter_table("users") as batch_op:
            for c in to_drop:
                batch_op.drop_column(c)
