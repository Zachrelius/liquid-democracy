"""Phase 27 default users to relevance_weighted strategy

Revision ID: d4e3a91c5f0b
Revises: c7e8a3d419f5
Create Date: 2026-05-13 16:00:00.000000

Pure data migration: flips every existing User.delegation_strategy row
from 'strict_precedence' to 'relevance_weighted', and the model default
is updated in models.py separately so newly-registered users start on
the new strategy.

Backwards-compat by design: proposals without per-topic relevance
scores (or with uniform 1.0 defaults) degrade naturally to strict-
precedence semantics because the new resolver's tiebreaker IS the
strict-precedence ordering. Users keep their TopicPrecedence rows.

Reversible: downgrade flips everyone back to 'strict_precedence'. Same
shape as the migration, just in the other direction. Idempotent under
both upgrade and downgrade — repeated runs are no-ops because the
filtered WHERE clause matches zero rows after the first execution.

Spec: phase27_relevance_weighted_delegation_dispatch_2026-05-13.md
cluster B3.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "d4e3a91c5f0b"
down_revision = "c7e8a3d419f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Flip every 'strict_precedence' user to 'relevance_weighted'."""
    op.execute(
        "UPDATE users SET delegation_strategy = 'relevance_weighted' "
        "WHERE delegation_strategy = 'strict_precedence'"
    )


def downgrade() -> None:
    """Reverse: flip every 'relevance_weighted' user back to
    'strict_precedence'. Idempotent."""
    op.execute(
        "UPDATE users SET delegation_strategy = 'strict_precedence' "
        "WHERE delegation_strategy = 'relevance_weighted'"
    )
