"""phase 52h stage 1 — demoted_user_id on org_duplicate_flags

Adds one nullable column to ``org_duplicate_flags``:

  ``demoted_user_id`` (FK users.id, SET NULL on delete, nullable,
  indexed) — records which side of a ``resolved_same`` pair was
  durably demoted by the admin's verdict. NULL until the flag's
  ``status`` becomes ``resolved_same``; populated at that time with
  the newer-of-pair (by ``User.created_at``).

Why this column: the derived ``is_org_verified`` predicate needs a
durable signal that survives the flag transitioning out of
``open`` status. Pre-Phase-52h, ``resolved_same`` was records-only
and the predicate's open-flag check would have RE-VERIFIED the
duplicate as a side effect (a backward outcome). 52h H4 fixes this
by keying the predicate on EITHER an open flag (any tier) OR a
``resolved_same`` flag where the user is the ``demoted_user_id``.

No data migration — existing rows (none with ``resolved_same`` yet,
by inspection — the v1 ``resolved_same`` path never demoted anyone)
have ``demoted_user_id`` NULL by default.

Hex-prefix revision id. Reversible via batch_alter_table.drop_column.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-06-06 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DEMOTED_USER_INDEX = "ix_org_duplicate_flags_demoted_user_id"


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
    cols = _existing_columns("org_duplicate_flags")
    if "demoted_user_id" not in cols:
        with op.batch_alter_table("org_duplicate_flags") as batch_op:
            batch_op.add_column(sa.Column(
                "demoted_user_id", sa.String(length=36),
                sa.ForeignKey(
                    "users.id", ondelete="SET NULL",
                    name="fk_org_duplicate_flags_demoted_user",
                ),
                nullable=True,
            ))

    indexes = _existing_indexes("org_duplicate_flags")
    if DEMOTED_USER_INDEX not in indexes:
        op.create_index(
            DEMOTED_USER_INDEX, "org_duplicate_flags",
            ["demoted_user_id"],
        )


def downgrade() -> None:
    indexes = _existing_indexes("org_duplicate_flags")
    if DEMOTED_USER_INDEX in indexes:
        op.drop_index(
            DEMOTED_USER_INDEX, table_name="org_duplicate_flags",
        )
    cols = _existing_columns("org_duplicate_flags")
    if "demoted_user_id" in cols:
        with op.batch_alter_table("org_duplicate_flags") as batch_op:
            batch_op.drop_column("demoted_user_id")
