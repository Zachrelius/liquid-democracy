"""phase 91 — hash refresh tokens at rest

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-07-12 00:00:00.000000

The upgrade preserves every active client token: it stores SHA-256(token) in
``token_hash`` and clears the plaintext. The downgrade cannot reconstruct a
one-way digest, so it copies the digest into the legacy token column. That
keeps the schema/data constraints reversible while deliberately invalidating
sessions after a downgrade rather than restoring plaintext secrets.
"""
from typing import Sequence, Union
import hashlib

from alembic import op
import sqlalchemy as sa


revision: str = "c5d6e7f8a9b0"
down_revision: Union[str, None] = "b4c5d6e7f8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_map() -> dict[str, dict]:
    return {
        col["name"]: col
        for col in sa.inspect(op.get_bind()).get_columns("refresh_tokens")
    }


def _index_names() -> set[str]:
    return {
        idx["name"]
        for idx in sa.inspect(op.get_bind()).get_indexes("refresh_tokens")
        if idx.get("name")
    }


def upgrade() -> None:
    # Keep ADD COLUMN outside the SQLite batch-recreate operation. Combining
    # a new column with ALTER NULLABILITY triggers an Alembic/SQLAlchemy
    # partial-column-ordering cycle on older, incrementally-migrated SQLite
    # schemas (the Phase 12/13/15 migration-cycle fixtures exercise this).
    cols = _column_map()
    if "token_hash" not in cols:
        op.add_column(
            "refresh_tokens",
            sa.Column("token_hash", sa.String(length=64), nullable=True),
        )
    if "ix_refresh_tokens_token_hash" not in _index_names():
        op.create_index(
            "ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"],
            unique=True,
        )
    if not cols.get("token", {}).get("nullable", False):
        with op.batch_alter_table("refresh_tokens", schema=None) as batch_op:
            batch_op.alter_column(
                "token", existing_type=sa.String(length=64), nullable=True,
            )

    table = sa.table(
        "refresh_tokens",
        sa.column("id", sa.Integer()),
        sa.column("token", sa.String(length=64)),
        sa.column("token_hash", sa.String(length=64)),
    )
    bind = op.get_bind()
    rows = bind.execute(sa.select(table.c.id, table.c.token)).all()
    for row in rows:
        if row.token is None:
            continue
        digest = hashlib.sha256(row.token.encode("utf-8")).hexdigest()
        bind.execute(
            table.update().where(table.c.id == row.id).values(
                token=None, token_hash=digest,
            )
        )


def downgrade() -> None:
    cols = _column_map()
    if "token_hash" not in cols:
        return
    table = sa.table(
        "refresh_tokens",
        sa.column("id", sa.Integer()),
        sa.column("token", sa.String(length=64)),
        sa.column("token_hash", sa.String(length=64)),
    )
    bind = op.get_bind()
    bind.execute(
        table.update()
        .where(table.c.token.is_(None))
        .values(token=table.c.token_hash)
    )

    if "ix_refresh_tokens_token_hash" in _index_names():
        op.drop_index("ix_refresh_tokens_token_hash", table_name="refresh_tokens")
    op.drop_column("refresh_tokens", "token_hash")
    if cols.get("token", {}).get("nullable", True):
        with op.batch_alter_table("refresh_tokens", schema=None) as batch_op:
            batch_op.alter_column(
                "token", existing_type=sa.String(length=64), nullable=False,
            )
