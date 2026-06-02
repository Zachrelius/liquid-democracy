"""phase 49 — scheduled / fixed-term elections (D1 + D6 + B4 plumbing)

Adds the minimum surface for scheduled re-election per the locked
hold-over-if-uncontested model (Phase 49 Decision A):

  * ``org_titles.term_length_days`` (Integer, nullable). NULL =
    no-term = Phase 48 "elected-until-challenged" behavior preserved.
    Setting it opts the title into the ``scheduled`` trigger path.
  * ``org_titles.election_lead_time_days`` (Integer, NOT NULL,
    default 7). How far before ``next_election_due_at`` the tick
    opens the election so the vote concludes around term-end (D4).
  * ``org_titles.next_election_due_at`` (DateTime, nullable). The
    D6 bookkeeping the tick reads. NULL = nothing scheduled.
  * ``proposals.election_trigger`` (String(16), nullable). Records
    which trigger source opened a given election so the close hook
    (``finalize_election``) can decide whether to advance the title's
    ``next_election_due_at`` (B4 — scheduled elections advance the
    schedule; off-cycle admin/cosign elections leave it fixed).

Existing-title parity (Phase 48 B0 discipline carried forward):
``term_length_days`` + ``next_election_due_at`` default to NULL, so
existing electable titles are byte-identical to pre-49 behavior — no
auto-scheduling for orgs that haven't opted in.

Hex-prefix revision ID (``a7c1d8e94521``) per the Phase 48 Stage 2
incident lesson. Reversible via batch_alter_table for dialect parity
across SQLite + Postgres.

Revision ID: a7c1d8e94521
Revises: h6b9c2d04523
Create Date: 2026-06-01 20:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7c1d8e94521"
down_revision: Union[str, None] = "h6b9c2d04523"
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
    title_cols = _existing_columns("org_titles")
    add_term_length = "term_length_days" not in title_cols
    add_lead_time = "election_lead_time_days" not in title_cols
    add_next_due = "next_election_due_at" not in title_cols
    if add_term_length or add_lead_time or add_next_due:
        with op.batch_alter_table("org_titles") as batch_op:
            if add_term_length:
                batch_op.add_column(
                    sa.Column(
                        "term_length_days", sa.Integer(), nullable=True,
                    ),
                )
            if add_lead_time:
                batch_op.add_column(
                    sa.Column(
                        "election_lead_time_days", sa.Integer(),
                        nullable=False, server_default="7",
                    ),
                )
            if add_next_due:
                batch_op.add_column(
                    sa.Column(
                        "next_election_due_at", sa.DateTime(),
                        nullable=True,
                    ),
                )

    proposal_cols = _existing_columns("proposals")
    if "election_trigger" not in proposal_cols:
        with op.batch_alter_table("proposals") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "election_trigger", sa.String(length=16),
                    nullable=True,
                ),
            )


def downgrade() -> None:
    proposal_cols = _existing_columns("proposals")
    if "election_trigger" in proposal_cols:
        with op.batch_alter_table("proposals") as batch_op:
            batch_op.drop_column("election_trigger")

    title_cols = _existing_columns("org_titles")
    drop_term_length = "term_length_days" in title_cols
    drop_lead_time = "election_lead_time_days" in title_cols
    drop_next_due = "next_election_due_at" in title_cols
    if drop_term_length or drop_lead_time or drop_next_due:
        with op.batch_alter_table("org_titles") as batch_op:
            if drop_next_due:
                batch_op.drop_column("next_election_due_at")
            if drop_lead_time:
                batch_op.drop_column("election_lead_time_days")
            if drop_term_length:
                batch_op.drop_column("term_length_days")
