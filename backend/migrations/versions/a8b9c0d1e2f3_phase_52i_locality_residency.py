"""phase 52i — city/locality residency gating (hashed)

Adds one nullable column to ``users``:

  ``verification_locality_hash`` (String 128, nullable)
    HMAC-SHA256 hash of ``(normalized_city, normalized_state)``
    under the same ``VERIFICATION_HASH_PEPPER`` as the dedup hashes.
    The state is included in the hash so "Springfield, MA" ≠
    "Springfield, IL" (load-bearing — city names collide across
    ~30 states). Populated in ``routes/verification._apply_decision``
    from ``decision.id_verifications[0].parsed_address.{city,
    region}``; the readable city is consumed transiently + discarded
    (same flow as today's address-hash inputs).

No index — unlike the dedup hashes (searched across users to find
matches), the locality hash is only ever compared to the org's
computed gate-hash for the SINGLE user being gated. No cross-user
lookup. A future feature that wants per-locality cohorts could add
an index then.

Hex-prefix revision id. Reversible via batch_alter_table.drop_column.

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-06-06 19:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, None] = "f7a8b9c0d1e2"
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
    cols = _existing_columns("users")
    if "verification_locality_hash" not in cols:
        with op.batch_alter_table("users") as batch_op:
            batch_op.add_column(sa.Column(
                "verification_locality_hash", sa.String(length=128),
                nullable=True,
            ))


def downgrade() -> None:
    cols = _existing_columns("users")
    if "verification_locality_hash" in cols:
        with op.batch_alter_table("users") as batch_op:
            batch_op.drop_column("verification_locality_hash")
