"""phase 52 stage 1 — proposal verification floor fields

Adds two nullable columns to ``proposals`` so a per-proposal
verification gate can be set at proposal-creation:

  * ``verification_floor`` (String(32), nullable). NULL = inherit
    "no gate" (today's behavior). Non-null = the floor required to
    cast a direct vote on this proposal. Validated against
    ``verification.VALID_STATES`` at the route layer.
  * ``verification_jurisdiction`` (String(16), nullable). Optional
    jurisdiction scoping. Validated for presence consistency via
    ``verification.jurisdiction_required_for(floor)`` at the route
    layer (route-side, not DB-side, so existing rows don't trip the
    check).

Existing proposals are byte-for-byte unaffected — both columns
default NULL. The additive-layer invariant: delete the gate in your
head, every existing tally / vote-cast / chain-resolution path
behaves identically.

Hex-prefix revision ID per the Phase 48 Stage 2 incident lesson.
Reversible via ``batch_alter_table`` for SQLite parity.

Revision ID: d9e4f2a78543
Revises: c8d3e1f56432
Create Date: 2026-06-03 09:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d9e4f2a78543"
down_revision: Union[str, None] = "c8d3e1f56432"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns(table: str) -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        return {c["name"] for c in insp.get_columns(table)}
    except Exception:
        return set()


def upgrade() -> None:
    cols = _existing_columns("proposals")
    add_floor = "verification_floor" not in cols
    add_jur = "verification_jurisdiction" not in cols
    if add_floor or add_jur:
        with op.batch_alter_table("proposals") as batch_op:
            if add_floor:
                batch_op.add_column(
                    sa.Column(
                        "verification_floor", sa.String(length=32),
                        nullable=True,
                    ),
                )
            if add_jur:
                batch_op.add_column(
                    sa.Column(
                        "verification_jurisdiction", sa.String(length=16),
                        nullable=True,
                    ),
                )


def downgrade() -> None:
    cols = _existing_columns("proposals")
    drop_floor = "verification_floor" in cols
    drop_jur = "verification_jurisdiction" in cols
    if drop_floor or drop_jur:
        with op.batch_alter_table("proposals") as batch_op:
            if drop_jur:
                batch_op.drop_column("verification_jurisdiction")
            if drop_floor:
                batch_op.drop_column("verification_floor")
