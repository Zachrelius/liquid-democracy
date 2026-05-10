"""Phase 18a follow-up: include org_id in FollowRelationship + FollowRequest unique constraints.

Revision ID: 1cc8f3f27717
Revises: 219205801d2c
Create Date: 2026-05-09 00:00:00.000000

What this does
--------------

Wave 1 (migration 219205801d2c) added ``org_id`` to ``follow_relationships``
and ``follow_requests`` but did NOT update their unique constraints — both
were still keyed on the account-level pair ``(follower_id, followed_id)``
and ``(requester_id, target_id)`` respectively. The Wave 1 closeout flagged
this for the Wave 2 (B3) write-side pass to fix.

This is that fix. The unique constraints are widened to include ``org_id``
so the same pair of users can have separate per-org follow rows / requests:

- ``uq_follow_relationship`` (``(follower_id, followed_id)``) →
  ``uq_follow_relationship_org`` (``(follower_id, followed_id, org_id)``)
- ``uq_follow_request_requester_target`` (``(requester_id, target_id)``) →
  ``uq_follow_request_requester_target_org`` (``(requester_id, target_id, org_id)``)

Per Postgres / SQLite distinct-NULL semantics, rows whose ``org_id`` is
still NULL during the 18a backfill window are automatically considered
distinct under the new constraint — they don't conflict with each other
or with new explicitly-org-scoped rows. Once 18b lands and ``org_id``
flips to NOT NULL, the constraint is fully meaningful.

Idempotency
-----------

Constraint drops/creates are guarded via ``inspector.get_unique_constraints``.
Re-running on a partially-applied DB is a no-op.

Downgrade
---------

Reinstates the original ``(follower_id, followed_id)`` /
``(requester_id, target_id)`` constraints. WARNING: if the prod DB has
multiple per-org follow rows for the same pair when the downgrade runs,
this will fail with a unique-constraint violation. The expected sequence
is "downgrade only on a fresh-from-18a-or-earlier DB" — same as the parent
18a migration's downgrade caveat.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "1cc8f3f27717"
down_revision: Union[str, None] = "219205801d2c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _maybe_drop_unique(inspector, table: str, name: str) -> None:
    existing = {
        uq["name"] for uq in inspector.get_unique_constraints(table)
        if uq.get("name")
    }
    if name not in existing:
        return
    with op.batch_alter_table(table, schema=None) as batch_op:
        batch_op.drop_constraint(name, type_="unique")


def _maybe_create_unique(
    inspector, table: str, name: str, columns: list[str]
) -> None:
    existing = {
        uq["name"] for uq in inspector.get_unique_constraints(table)
        if uq.get("name")
    }
    if name in existing:
        return
    with op.batch_alter_table(table, schema=None) as batch_op:
        batch_op.create_unique_constraint(name, columns)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # --- follow_relationships ----------------------------------------------
    _maybe_drop_unique(inspector, "follow_relationships", "uq_follow_relationship")
    # Re-inspect after the drop so the next call sees the current state.
    inspector = sa.inspect(bind)
    _maybe_create_unique(
        inspector,
        "follow_relationships",
        "uq_follow_relationship_org",
        ["follower_id", "followed_id", "org_id"],
    )

    # --- follow_requests ---------------------------------------------------
    inspector = sa.inspect(bind)
    _maybe_drop_unique(
        inspector, "follow_requests", "uq_follow_request_requester_target"
    )
    inspector = sa.inspect(bind)
    _maybe_create_unique(
        inspector,
        "follow_requests",
        "uq_follow_request_requester_target_org",
        ["requester_id", "target_id", "org_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    _maybe_drop_unique(
        inspector, "follow_requests", "uq_follow_request_requester_target_org"
    )
    inspector = sa.inspect(bind)
    _maybe_create_unique(
        inspector,
        "follow_requests",
        "uq_follow_request_requester_target",
        ["requester_id", "target_id"],
    )

    inspector = sa.inspect(bind)
    _maybe_drop_unique(
        inspector, "follow_relationships", "uq_follow_relationship_org"
    )
    inspector = sa.inspect(bind)
    _maybe_create_unique(
        inspector,
        "follow_relationships",
        "uq_follow_relationship",
        ["follower_id", "followed_id"],
    )
