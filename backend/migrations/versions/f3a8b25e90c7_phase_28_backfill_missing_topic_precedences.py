"""Phase 28 backfill missing TopicPrecedence rows

Revision ID: f3a8b25e90c7
Revises: d4e3a91c5f0b
Create Date: 2026-05-14 00:00:00.000000

Phase 27 F2 + Phase 28 B1 ensure NEW delegations create a corresponding
TopicPrecedence row at the bottom of the user's priority order. Pre-
Phase-27 delegations (seed data + anything created before the auto-
precedence wiring landed) lack precedence rows, leaving users with
priority lists that don't match their actual delegations.

This migration backfills: for every (user_id, topic_id) Delegation
pair where topic_id IS NOT NULL and no corresponding TopicPrecedence
row exists, INSERT one at the bottom of that user's current ordering.

Python-loop implementation (SQLite-compatible). Data volume on prod is
small (a few hundred rows), so the loop's per-row cost is negligible.

Idempotent: re-running finds zero missing rows (the WHERE NOT EXISTS
filter matches nothing the second time through).

Downgrade is a no-op — backfilled rows are indistinguishable from
user-created ones after the fact. If a rollback is needed, snapshot
the table before running the migration.

Spec: phase28_delegation_table_consolidation_dispatch_2026-05-13.md
cluster B3.
"""
from __future__ import annotations

import uuid
from itertools import groupby

from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = "f3a8b25e90c7"
down_revision = "d4e3a91c5f0b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Backfill TopicPrecedence rows for every topic-scoped Delegation
    that doesn't already have one. Priorities assigned at user's max+1."""
    bind = op.get_bind()

    # Find (user_id, topic_id, created_at) triples for delegations lacking
    # a precedence row. Ordered by user_id then created_at so the loop
    # below can group by user and assign deterministic priorities.
    missing_rows = bind.execute(text("""
        SELECT d.delegator_id, d.topic_id, d.created_at
        FROM delegations d
        WHERE d.topic_id IS NOT NULL
        AND NOT EXISTS (
            SELECT 1 FROM topic_precedences tp
            WHERE tp.user_id = d.delegator_id
            AND tp.topic_id = d.topic_id
        )
        ORDER BY d.delegator_id, d.created_at
    """)).fetchall()

    if not missing_rows:
        return  # idempotent — nothing to do

    for user_id, group in groupby(missing_rows, key=lambda r: r[0]):
        rows = list(group)
        max_prio = bind.execute(text(
            "SELECT COALESCE(MAX(priority), -1) FROM topic_precedences "
            "WHERE user_id = :uid"
        ), {"uid": user_id}).scalar()
        next_prio = (max_prio if max_prio is not None else -1) + 1
        for row in rows:
            bind.execute(text("""
                INSERT INTO topic_precedences (id, user_id, topic_id, priority)
                VALUES (:id, :uid, :tid, :prio)
            """), {
                "id": str(uuid.uuid4()),
                "uid": user_id,
                "tid": row[1],
                "prio": next_prio,
            })
            next_prio += 1


def downgrade() -> None:
    """No-op: backfill is purely additive. Backfilled rows are not
    distinguishable from user-created precedence rows after insert. If
    you need to roll back, restore TopicPrecedence from a pre-migration
    snapshot."""
    pass
