"""phase 52a — Didit verification sessions + nullifier uniqueness

Two additions, both supporting the Phase 52a real-provider path:

  1. ``verification_sessions`` bookkeeping table. One row per
     initiated Didit session, keyed by ``provider_session_id``.
     Tracks the lifecycle (initiated → approved / declined /
     superseded) and supports webhook idempotency: a replayed
     ``(provider_session_id, webhook_type_last)`` lookup either
     finds the prior row (no-op 200) or writes a new processed
     status. No raw PII is stored — only the session id, the user
     it was opened for, and high-level status.

  2. Partial unique index on ``users.verification_nullifier`` —
     the constraint deferred from Phase 51. On PostgreSQL the
     index is partial (``WHERE verification_nullifier IS NOT
     NULL``) so the many users with NULL nullifier do not collide.
     On SQLite a plain unique index already tolerates many NULLs
     by spec (NULLs treated as distinct in a UNIQUE index), so the
     same DDL works in both backends with the partial-WHERE
     clause emitted only on Postgres.

CAPABILITY-FORK CAVEAT (recorded in the spec): if the configured
Didit workspace does NOT expose true 1:N face-search / biometric
duplicate detection, ``map_decision_to_state`` will not populate the
nullifier and the uniqueness invariant is effectively dormant. The
column + index plumbing still lands here so Stage 52b / future passes
do not require another migration to turn it on.

Hex-prefix revision id. Reversible via ``batch_alter_table`` +
``drop_index``.

Revision ID: e0a1b2c3d4f5
Revises: d9e4f2a78543
Create Date: 2026-06-03 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e0a1b2c3d4f5"
down_revision: Union[str, None] = "d9e4f2a78543"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_tables() -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        return set(insp.get_table_names())
    except Exception:
        return set()


def _existing_indexes(table: str) -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        return {ix["name"] for ix in insp.get_indexes(table)}
    except Exception:
        return set()


NULLIFIER_UNIQUE_INDEX = "ix_users_verification_nullifier_unique"


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    tables = _existing_tables()

    if "verification_sessions" not in tables:
        op.create_table(
            "verification_sessions",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "user_id", sa.String(length=36),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False, index=True,
            ),
            sa.Column(
                "provider_session_id", sa.String(length=128),
                nullable=False, unique=True,
            ),
            sa.Column(
                "status", sa.String(length=32),
                nullable=False, server_default="initiated",
            ),
            sa.Column(
                "webhook_type_last", sa.String(length=64),
                nullable=True,
            ),
            sa.Column(
                "created_at", sa.DateTime,
                nullable=False, server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at", sa.DateTime,
                nullable=False, server_default=sa.func.now(),
            ),
        )

    # Partial unique index on the nullifier. On PG, the WHERE clause
    # is honored — many NULL rows do not collide. On SQLite, the
    # unique index already tolerates many NULLs (NULLs are distinct
    # in a UNIQUE index); we emit it without the WHERE for SQLite.
    user_indexes = _existing_indexes("users")
    if NULLIFIER_UNIQUE_INDEX not in user_indexes:
        if dialect == "postgresql":
            op.create_index(
                NULLIFIER_UNIQUE_INDEX,
                "users",
                ["verification_nullifier"],
                unique=True,
                postgresql_where=sa.text(
                    "verification_nullifier IS NOT NULL"
                ),
            )
        else:
            op.create_index(
                NULLIFIER_UNIQUE_INDEX,
                "users",
                ["verification_nullifier"],
                unique=True,
            )


def downgrade() -> None:
    tables = _existing_tables()
    user_indexes = _existing_indexes("users")
    if NULLIFIER_UNIQUE_INDEX in user_indexes:
        op.drop_index(NULLIFIER_UNIQUE_INDEX, table_name="users")
    if "verification_sessions" in tables:
        op.drop_table("verification_sessions")
