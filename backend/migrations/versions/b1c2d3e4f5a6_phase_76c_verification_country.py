"""phase 76c — residency country capture + country-level residency gating

Adds one nullable column to ``users``:

  ``verification_country`` (String 2, nullable)
    ISO 3166-1 alpha-2 residency country code (e.g. "US", "CA"),
    captured in ``routes/verification._apply_decision`` from
    ``decision.id_verifications[0].parsed_address.country``,
    independent of the (US-centric) ``verification_jurisdiction`` /
    state ladder so non-US members can be gated by country. Readable
    (low-sensitivity, same as jurisdiction); never serialized to
    non-admin clients. No index — only ever compared to the org's
    configured country for the single user being gated.

Backfill: any existing member with a US state already on file
(``verification_jurisdiction`` non-null, excluding the ``DEMO``
sentinel) implies US residency, so we set ``verification_country =
'US'`` for them. This keeps already-verified US members satisfying a
newly-added US country gate without re-verifying. Other countries
can't be inferred (we don't store raw ID payloads) → those members
re-verify to populate the column. The backfill is the only direction
we can safely infer; the downgrade drops the column outright.

Hex-prefix revision id. Reversible via batch_alter_table.drop_column.

Revision ID: b1c2d3e4f5a6
Revises: a5b6c7d8e9f0
Create Date: 2026-06-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "a5b6c7d8e9f0"
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
    if "verification_country" not in cols:
        with op.batch_alter_table("users") as batch_op:
            batch_op.add_column(sa.Column(
                "verification_country", sa.String(length=2),
                nullable=True,
            ))
    # Backfill: a US state on file implies US residency. Exclude the
    # 'DEMO' sentinel and any rows already populated. Idempotent.
    op.execute(
        sa.text(
            "UPDATE users SET verification_country = 'US' "
            "WHERE verification_country IS NULL "
            "AND verification_jurisdiction IS NOT NULL "
            "AND verification_jurisdiction <> 'DEMO'"
        )
    )


def downgrade() -> None:
    cols = _existing_columns("users")
    if "verification_country" in cols:
        with op.batch_alter_table("users") as batch_op:
            batch_op.drop_column("verification_country")
