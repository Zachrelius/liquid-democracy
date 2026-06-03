"""phase 51 — verification state model foundation

Adds the six user-level verification columns the ID-verification arc
builds on. No enforcement is wired in this phase — that's Phase 52.
The columns are additive and carry ``server_default`` values so
existing user rows are byte-for-byte unaffected (the no-backfill
guarantee, asserted by the parity test in
``test_phase_51_verification_state_model.py``).

Columns added to ``users``:

  * ``verification_state`` (String(32), NOT NULL, default ``email_only``,
    indexed). The five-state lifecycle string. ``verification.py`` is
    the source of truth for valid values; no DB enum (consistent with
    ``proposal.status``-era reasoning).
  * ``verification_jurisdiction`` (String(16), nullable). Coarse
    jurisdiction claim (US state code, sentinel ``DEMO``, etc.).
    NULL for states below ``address_on_id``.
  * ``verification_attestation_id`` (String(128), nullable). Opaque
    provider-side verification reference. NULL until verified.
  * ``verification_nullifier`` (String(128), nullable, indexed). The
    per-user uniqueness primitive (mirrors ``PolisXid.polis_xid``).
    **NO UniqueConstraint in this phase** — uniqueness semantics +
    re-verification flow live in Phase 52. Index only.
  * ``verification_provenance`` (String(16), NOT NULL,
    default ``none``). Distinguishes real-from-stub verifications
    so demo + audit surfaces stay honest. Values: ``none`` /
    ``persona`` / ``demo_stub`` / ``backdoor``.
  * ``verification_updated_at`` (DateTime, nullable). When the state
    last changed. NULL until first set.

Hex-prefix revision ID per the Phase 48 Stage 2 incident lesson.
Reversible via batch_alter_table for SQLite dialect parity.

Revision ID: c8d3e1f56432
Revises: b9c2e0f43215
Create Date: 2026-06-03 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c8d3e1f56432"
down_revision: Union[str, None] = "b9c2e0f43215"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns(table: str) -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        return {c["name"] for c in insp.get_columns(table)}
    except Exception:
        return set()


def _existing_index_names(table: str) -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        return {i["name"] for i in insp.get_indexes(table)}
    except Exception:
        return set()


def upgrade() -> None:
    cols = _existing_columns("users")
    add_state = "verification_state" not in cols
    add_jur = "verification_jurisdiction" not in cols
    add_att = "verification_attestation_id" not in cols
    add_null = "verification_nullifier" not in cols
    add_prov = "verification_provenance" not in cols
    add_upd = "verification_updated_at" not in cols

    if any([add_state, add_jur, add_att, add_null, add_prov, add_upd]):
        with op.batch_alter_table("users") as batch_op:
            if add_state:
                batch_op.add_column(
                    sa.Column(
                        "verification_state", sa.String(length=32),
                        nullable=False, server_default="email_only",
                    ),
                )
            if add_jur:
                batch_op.add_column(
                    sa.Column(
                        "verification_jurisdiction", sa.String(length=16),
                        nullable=True,
                    ),
                )
            if add_att:
                batch_op.add_column(
                    sa.Column(
                        "verification_attestation_id", sa.String(length=128),
                        nullable=True,
                    ),
                )
            if add_null:
                batch_op.add_column(
                    sa.Column(
                        "verification_nullifier", sa.String(length=128),
                        nullable=True,
                    ),
                )
            if add_prov:
                batch_op.add_column(
                    sa.Column(
                        "verification_provenance", sa.String(length=16),
                        nullable=False, server_default="none",
                    ),
                )
            if add_upd:
                batch_op.add_column(
                    sa.Column(
                        "verification_updated_at", sa.DateTime(),
                        nullable=True,
                    ),
                )

    idx_names = _existing_index_names("users")
    if "ix_users_verification_state" not in idx_names:
        try:
            op.create_index(
                "ix_users_verification_state",
                "users",
                ["verification_state"],
            )
        except Exception:
            pass
    if "ix_users_verification_nullifier" not in idx_names:
        try:
            op.create_index(
                "ix_users_verification_nullifier",
                "users",
                ["verification_nullifier"],
            )
        except Exception:
            pass


def downgrade() -> None:
    idx_names = _existing_index_names("users")
    if "ix_users_verification_state" in idx_names:
        try:
            op.drop_index("ix_users_verification_state", table_name="users")
        except Exception:
            pass
    if "ix_users_verification_nullifier" in idx_names:
        try:
            op.drop_index("ix_users_verification_nullifier", table_name="users")
        except Exception:
            pass

    cols = _existing_columns("users")
    drop_state = "verification_state" in cols
    drop_jur = "verification_jurisdiction" in cols
    drop_att = "verification_attestation_id" in cols
    drop_null = "verification_nullifier" in cols
    drop_prov = "verification_provenance" in cols
    drop_upd = "verification_updated_at" in cols
    if any([drop_state, drop_jur, drop_att, drop_null, drop_prov, drop_upd]):
        with op.batch_alter_table("users") as batch_op:
            if drop_upd:
                batch_op.drop_column("verification_updated_at")
            if drop_prov:
                batch_op.drop_column("verification_provenance")
            if drop_null:
                batch_op.drop_column("verification_nullifier")
            if drop_att:
                batch_op.drop_column("verification_attestation_id")
            if drop_jur:
                batch_op.drop_column("verification_jurisdiction")
            if drop_state:
                batch_op.drop_column("verification_state")
