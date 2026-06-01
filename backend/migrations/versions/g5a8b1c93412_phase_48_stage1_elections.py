"""phase 48 stage 1 — elections (proposal subtype + candidacy)

Adds the minimum binding-election surface per D1: a proposal can be
flagged as an election whose target is an ``OrgTitle`` (Phase 47).
Candidacies are recorded in a new ``election_candidacies`` table.

  * ``proposals.is_election`` bool (default False, server_default '0').
  * ``proposals.election_title_id`` nullable FK to ``org_titles.id``.
  * ``election_candidacies`` table — (proposal_id, user_id) unique, plus
    status + declared_at + optional withdrawn_at.

Per D2 the close→assign-title hook is the load-bearing piece — schema
side it's just two columns + a table. Migration is reversible. New
columns default-False/null so non-election proposals are byte-identical
to pre-48 behavior.

Revision ID: g5a8b1c93412
Revises: f4d8a9c52312
Create Date: 2026-06-01 07:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g5a8b1c93412"
down_revision: Union[str, None] = "f4d8a9c52312"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns(table: str) -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        return {c["name"] for c in insp.get_columns(table)}
    except Exception:
        return set()


def _existing_tables() -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return set(insp.get_table_names())


def upgrade() -> None:
    cols = _existing_columns("proposals")
    # SQLite can't ALTER constraints — use batch_alter_table when
    # adding a FK-bearing column so the table is rebuilt. Postgres
    # accepts plain ALTER; using batch on both keeps dialect parity.
    if "is_election" not in cols or "election_title_id" not in cols:
        with op.batch_alter_table("proposals") as batch_op:
            if "is_election" not in cols:
                batch_op.add_column(
                    sa.Column(
                        "is_election", sa.Boolean(),
                        nullable=False, server_default=sa.false(),
                    ),
                )
            if "election_title_id" not in cols:
                batch_op.add_column(
                    sa.Column(
                        "election_title_id", sa.String(),
                        sa.ForeignKey(
                            "org_titles.id",
                            name="fk_proposals_election_title_id",
                        ),
                        nullable=True,
                    ),
                )
        if "election_title_id" not in cols:
            op.create_index(
                "ix_proposals_election_title_id",
                "proposals",
                ["election_title_id"],
            )

    if "election_candidacies" not in _existing_tables():
        op.create_table(
            "election_candidacies",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "proposal_id", sa.String(),
                sa.ForeignKey("proposals.id", ondelete="CASCADE"),
                nullable=False, index=True,
            ),
            sa.Column(
                "user_id", sa.String(),
                sa.ForeignKey("users.id"),
                nullable=False, index=True,
            ),
            sa.Column(
                "status", sa.String(length=16),
                nullable=False, server_default="declared",
            ),
            sa.Column(
                "declared_at", sa.DateTime(),
                nullable=False, server_default=sa.func.now(),
            ),
            sa.Column("withdrawn_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint(
                "proposal_id", "user_id",
                name="uq_election_candidacies_proposal_user",
            ),
        )


def downgrade() -> None:
    if "election_candidacies" in _existing_tables():
        op.drop_table("election_candidacies")
    cols = _existing_columns("proposals")
    # SQLite can't drop FK-bearing columns via plain ALTER TABLE — it
    # rejects with "unknown column in foreign key definition" when
    # re-validating after the rewrite. ``batch_alter_table`` rebuilds
    # the table around the changes which sidesteps the issue. Postgres
    # would accept the plain ALTER; using batch on both keeps the
    # migration identical across dialects.
    with op.batch_alter_table("proposals") as batch_op:
        if "election_title_id" in cols:
            try:
                batch_op.drop_index("ix_proposals_election_title_id")
            except Exception:
                pass
            batch_op.drop_column("election_title_id")
        if "is_election" in cols:
            batch_op.drop_column("is_election")
