"""phase 52f+52g — legal name + age bands + per-org display name

Combined migration shipping Phase 52f (per-org display names +
display-name-match) and Phase 52g (derived age band, never raw DOB)
in one pass. Both touch the same ``_apply_decision`` extraction
site, both add nullable User columns, and the "verify once, light up
everything" principle in both specs argues for shipping them
together so a single re-verify populates the legal name AND the age
band.

Added columns:

  ``users.legal_first_name`` (String 128, nullable)
  ``users.legal_last_name`` (String 128, nullable)
  ``users.legal_full_name`` (String 256, nullable)
    Phase 52f — readable legal name from Didit's OCR
    (``id_verifications[0].{first_name, last_name, full_name}``).
    Locked PII keep-list per the arc backlog: storing readable
    enables display-name-match (org gates whose purpose is to
    enforce against the legal name; a hash can't support partial /
    first-only matching). Privacy disclosure on the consent path
    + the Settings copy.

  ``users.verification_age_bands`` (Text, nullable, stores JSON list)
    Phase 52g — derived set of met age thresholds (e.g. [13, 16, 18]
    means "≥13, ≥16, ≥18 all true; <21"). Format A from the spec
    (sorted list of met thresholds) — compact, supports any
    threshold an org configures from the supported set. NEVER the
    raw DOB.

  ``users.verification_age_promotes_at`` (DateTime, nullable)
    Phase 52g — month-aligned date when the user crosses the NEXT
    supported threshold. Month granularity (always the 1st of the
    month) so the value can't reconstruct the exact birth day. NULL
    when the user already meets every supported threshold.

  ``org_memberships.display_name`` (String 80, nullable)
    Phase 52f — per-org display name override. NULL = fall through
    to ``User.display_name``. The resolver helper
    ``verification.display_name_for(user, org)`` returns the
    override or fallback; every name-rendering surface in an org
    context reads through this.

  ``proposals.min_age`` (Integer, nullable)
    Phase 52g — per-proposal minimum age. NULL = no age gate (the
    default; matches the ``verification_floor`` column's nullable
    pattern from Phase 52 Stage 1).

Hex-prefix revision id. Reversible via batch_alter_table.

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-06-06 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, None] = "e6f7a8b9c0d1"
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
    # --- users: legal name + age band columns ---
    user_cols = _existing_columns("users")
    user_to_add = []
    if "legal_first_name" not in user_cols:
        user_to_add.append("legal_first_name")
    if "legal_last_name" not in user_cols:
        user_to_add.append("legal_last_name")
    if "legal_full_name" not in user_cols:
        user_to_add.append("legal_full_name")
    if "verification_age_bands" not in user_cols:
        user_to_add.append("verification_age_bands")
    if "verification_age_promotes_at" not in user_cols:
        user_to_add.append("verification_age_promotes_at")
    if user_to_add:
        with op.batch_alter_table("users") as batch_op:
            if "legal_first_name" in user_to_add:
                batch_op.add_column(sa.Column(
                    "legal_first_name", sa.String(length=128), nullable=True,
                ))
            if "legal_last_name" in user_to_add:
                batch_op.add_column(sa.Column(
                    "legal_last_name", sa.String(length=128), nullable=True,
                ))
            if "legal_full_name" in user_to_add:
                batch_op.add_column(sa.Column(
                    "legal_full_name", sa.String(length=256), nullable=True,
                ))
            if "verification_age_bands" in user_to_add:
                batch_op.add_column(sa.Column(
                    "verification_age_bands", sa.Text, nullable=True,
                ))
            if "verification_age_promotes_at" in user_to_add:
                batch_op.add_column(sa.Column(
                    "verification_age_promotes_at", sa.DateTime, nullable=True,
                ))

    # --- org_memberships: per-org display name override ---
    mem_cols = _existing_columns("org_memberships")
    if "display_name" not in mem_cols:
        with op.batch_alter_table("org_memberships") as batch_op:
            batch_op.add_column(sa.Column(
                "display_name", sa.String(length=80), nullable=True,
            ))

    # --- proposals: per-proposal min_age gate ---
    prop_cols = _existing_columns("proposals")
    if "min_age" not in prop_cols:
        with op.batch_alter_table("proposals") as batch_op:
            batch_op.add_column(sa.Column(
                "min_age", sa.Integer, nullable=True,
            ))


def downgrade() -> None:
    prop_cols = _existing_columns("proposals")
    if "min_age" in prop_cols:
        with op.batch_alter_table("proposals") as batch_op:
            batch_op.drop_column("min_age")

    mem_cols = _existing_columns("org_memberships")
    if "display_name" in mem_cols:
        with op.batch_alter_table("org_memberships") as batch_op:
            batch_op.drop_column("display_name")

    user_cols = _existing_columns("users")
    user_to_drop = [
        c for c in (
            "verification_age_promotes_at",
            "verification_age_bands",
            "legal_full_name",
            "legal_last_name",
            "legal_first_name",
        ) if c in user_cols
    ]
    if user_to_drop:
        with op.batch_alter_table("users") as batch_op:
            for c in user_to_drop:
                batch_op.drop_column(c)
