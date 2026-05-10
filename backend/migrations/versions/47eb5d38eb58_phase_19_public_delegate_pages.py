"""Phase 19: Public Delegate Pages — schema foundation.

Revision ID: 47eb5d38eb58
Revises: e9419ee5906f
Create Date: 2026-05-10 12:00:00.000000

What this does
--------------

The Phase 19 spec (``phase19_public_delegate_pages_spec.md`` §B1) ships
the schema foundation for the public delegate identity surface. Per-org
delegate identity (``OrgDelegateProfile``) plus per-topic visibility
states + position statements + lifecycle metadata on ``DelegateProfile``
plus an account-level ``delegate_handle`` plus per-vote rationale
(``DelegateVoteRationale``).

Migration order:

1. Create ``org_delegate_profiles`` table (per-user-per-org parent
   profile holding intro markdown + ``page_visibility`` enum).
2. Add columns to ``delegate_profiles``:
   - ``visibility`` enum('private','public','public_accepting'),
     server_default='public_accepting' for D8 backwards-compat — every
     existing row "is" already a public-accepting delegate (the old
     binary "having a profile = accepting" model).
   - ``position_statement`` Text nullable.
   - ``public_accepting_submitted_at`` DateTime nullable.
   - ``public_accepting_approved_at`` DateTime nullable.
   - ``public_accepting_approved_by_id`` String FK users.id nullable.
   - ``public_accepting_denied_comment`` Text nullable.
3. Add ``users.delegate_handle`` String unique nullable indexed —
   account-level handle resolved by the ``/{slug}/delegates/{handle}``
   URL pattern. Handles are reserved-slugs validated at write time
   (route layer; not enforced in DB).
4. Create ``delegate_vote_rationales`` table — one rationale per vote
   (vote_id is unique).
5. Backfill: for every existing ``delegate_profiles`` row's
   ``(user_id, org_id)`` pair that doesn't already have a parent
   ``org_delegate_profiles`` row, create one with
   ``page_visibility='private'`` (D9 default; effective visibility on
   the page is derived to ``public`` because the user has at least one
   non-private topic per the D8 default of ``public_accepting``).
6. Audit log per backfilled row: ``delegate_profile.visibility_backfilled``
   per ``DelegateProfile`` row; ``org_delegate_profile.created_via_backfill``
   per ``OrgDelegateProfile`` row.

SQLite portability
~~~~~~~~~~~~~~~~~~

All ALTER TABLE goes through ``op.batch_alter_table`` so SQLite (which
can't ALTER FK columns in place) gets the table-rebuild treatment. The
Phase 18 downgrade gotcha — ``try/except`` cannot catch deferred batch
flush errors — is avoided by pre-inspecting FK + index existence before
queueing drops in ``downgrade()``.

Backwards compat
~~~~~~~~~~~~~~~~

D8: existing ``DelegateProfile`` rows get ``visibility='public_accepting'``
via the column ``server_default``. No additional UPDATE needed in
``upgrade()`` for that — the server_default fires on existing rows when
the column lands NOT NULL with a default.

Downgrade
~~~~~~~~~

Drops the new columns + tables. Backfilled ``OrgDelegateProfile`` rows
are LOST on downgrade (no way to reverse the per-row inference). The
new ``DelegateProfile`` columns are dropped — any approval-workflow
state recorded post-deploy is also lost. Document any divergence in
the closeout if a downgrade is ever exercised in production.
"""

from datetime import datetime, timezone
from typing import Sequence, Union
import json
import logging
import uuid

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '47eb5d38eb58'
down_revision: Union[str, None] = 'e9419ee5906f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_LOG = logging.getLogger("alembic.phase19")


# ---------------------------------------------------------------------------
# Helpers (mirroring the Phase 18a shape)
# ---------------------------------------------------------------------------


def _now_naive() -> datetime:
    """UTC timestamp without tzinfo (matches the DB column shape)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _audit(bind, action: str, target_type: str, target_id: str,
           details: dict) -> None:
    """Append a row to ``audit_log``. Skips silently if the table is
    missing (defensive — shouldn't happen post-Phase-4c)."""
    inspector = sa.inspect(bind)
    if "audit_log" not in inspector.get_table_names():
        return
    bind.execute(
        sa.text(
            "INSERT INTO audit_log "
            "(id, timestamp, actor_id, action, target_type, target_id, "
            " details, ip_address) "
            "VALUES (:id, :ts, NULL, :action, :ttype, :tid, "
            "        :details, NULL)"
        ),
        {
            "id": str(uuid.uuid4()),
            "ts": _now_naive(),
            "action": action,
            "ttype": target_type,
            "tid": target_id,
            "details": json.dumps(details),
        },
    )


# ---------------------------------------------------------------------------
# upgrade / downgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # ----- 1. Create org_delegate_profiles. -----
    if "org_delegate_profiles" not in existing_tables:
        op.create_table(
            "org_delegate_profiles",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("org_id", sa.String(), nullable=False),
            sa.Column("intro", sa.Text(), nullable=True),
            sa.Column(
                "page_visibility",
                sa.Enum(
                    "private", "private_delegators",
                    name="org_delegate_page_visibility",
                ),
                nullable=False,
                server_default="private",
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["user_id"], ["users.id"],
                name="fk_org_delegate_profiles_user_id",
            ),
            sa.ForeignKeyConstraint(
                ["org_id"], ["organizations.id"],
                name="fk_org_delegate_profiles_org_id",
            ),
            sa.UniqueConstraint(
                "user_id", "org_id",
                name="uq_org_delegate_profile_user_org",
            ),
        )
        op.create_index(
            "ix_org_delegate_profiles_user_id",
            "org_delegate_profiles", ["user_id"], unique=False,
        )
        op.create_index(
            "ix_org_delegate_profiles_org_id",
            "org_delegate_profiles", ["org_id"], unique=False,
        )

    # Re-inspect after table create.
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # ----- 2. Add columns to delegate_profiles. -----
    if "delegate_profiles" in existing_tables:
        existing_cols = {c["name"] for c in inspector.get_columns(
            "delegate_profiles"
        )}

        with op.batch_alter_table("delegate_profiles", schema=None) as batch_op:
            if "visibility" not in existing_cols:
                batch_op.add_column(
                    sa.Column(
                        "visibility",
                        sa.Enum(
                            "private", "public", "public_accepting",
                            name="delegate_profile_visibility",
                        ),
                        nullable=False,
                        server_default="public_accepting",  # D8
                    )
                )
            if "position_statement" not in existing_cols:
                batch_op.add_column(
                    sa.Column("position_statement", sa.Text(), nullable=True)
                )
            if "public_accepting_submitted_at" not in existing_cols:
                batch_op.add_column(
                    sa.Column(
                        "public_accepting_submitted_at",
                        sa.DateTime(), nullable=True,
                    )
                )
            if "public_accepting_approved_at" not in existing_cols:
                batch_op.add_column(
                    sa.Column(
                        "public_accepting_approved_at",
                        sa.DateTime(), nullable=True,
                    )
                )
            if "public_accepting_approved_by_id" not in existing_cols:
                batch_op.add_column(
                    sa.Column(
                        "public_accepting_approved_by_id",
                        sa.String(), nullable=True,
                    )
                )
                batch_op.create_foreign_key(
                    "fk_delegate_profiles_public_accepting_approved_by_id",
                    "users", ["public_accepting_approved_by_id"], ["id"],
                )
            if "public_accepting_denied_comment" not in existing_cols:
                batch_op.add_column(
                    sa.Column(
                        "public_accepting_denied_comment",
                        sa.Text(), nullable=True,
                    )
                )

    # ----- 3. Add users.delegate_handle. -----
    inspector = sa.inspect(bind)
    if "users" in inspector.get_table_names():
        existing_cols = {c["name"] for c in inspector.get_columns("users")}
        if "delegate_handle" not in existing_cols:
            with op.batch_alter_table("users", schema=None) as batch_op:
                batch_op.add_column(
                    sa.Column(
                        "delegate_handle", sa.String(),
                        nullable=True,
                    )
                )
                batch_op.create_unique_constraint(
                    "uq_users_delegate_handle",
                    ["delegate_handle"],
                )
                batch_op.create_index(
                    "ix_users_delegate_handle",
                    ["delegate_handle"], unique=False,
                )

    # ----- 4. Create delegate_vote_rationales. -----
    inspector = sa.inspect(bind)
    if "delegate_vote_rationales" not in inspector.get_table_names():
        op.create_table(
            "delegate_vote_rationales",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("vote_id", sa.String(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["vote_id"], ["votes.id"],
                name="fk_delegate_vote_rationales_vote_id",
            ),
            sa.UniqueConstraint(
                "vote_id",
                name="uq_delegate_vote_rationale_vote_id",
            ),
        )
        op.create_index(
            "ix_delegate_vote_rationales_vote_id",
            "delegate_vote_rationales", ["vote_id"], unique=False,
        )

    # ----- 5. Backfill OrgDelegateProfile rows. -----
    inspector = sa.inspect(bind)
    if (
        "delegate_profiles" in inspector.get_table_names()
        and "org_delegate_profiles" in inspector.get_table_names()
    ):
        # Distinct (user_id, org_id) pairs from delegate_profiles where
        # org_id is set. Skip pairs that already have an OrgDelegateProfile
        # row (defensive: makes re-running idempotent).
        rows = bind.execute(
            sa.text(
                "SELECT DISTINCT dp.user_id, dp.org_id "
                "FROM delegate_profiles dp "
                "WHERE dp.org_id IS NOT NULL "
                "  AND NOT EXISTS ( "
                "    SELECT 1 FROM org_delegate_profiles odp "
                "    WHERE odp.user_id = dp.user_id "
                "      AND odp.org_id = dp.org_id "
                "  )"
            )
        ).fetchall()
        backfill_count = 0
        for user_id, org_id in rows:
            new_id = str(uuid.uuid4())
            now = _now_naive()
            bind.execute(
                sa.text(
                    "INSERT INTO org_delegate_profiles "
                    "(id, user_id, org_id, intro, page_visibility, "
                    " created_at, updated_at) "
                    "VALUES (:id, :uid, :oid, NULL, 'private', "
                    "        :ts, :ts)"
                ),
                {"id": new_id, "uid": user_id, "oid": org_id, "ts": now},
            )
            _audit(
                bind,
                action="org_delegate_profile.created_via_backfill",
                target_type="org_delegate_profile",
                target_id=new_id,
                details={
                    "user_id": user_id,
                    "org_id": org_id,
                    "page_visibility": "private",
                    "note": (
                        "Backfilled from existing DelegateProfile rows; "
                        "effective visibility derives to 'public' because "
                        "the user has at least one non-private topic "
                        "(D8 default)."
                    ),
                },
            )
            backfill_count += 1

        # Audit log per existing DelegateProfile row that was implicitly
        # set to 'public_accepting' via column server_default.
        dp_rows = bind.execute(
            sa.text("SELECT id FROM delegate_profiles")
        ).fetchall()
        for (dp_id,) in dp_rows:
            _audit(
                bind,
                action="delegate_profile.visibility_backfilled",
                target_type="delegate_profile",
                target_id=dp_id,
                details={
                    "old_state": {"visibility": None},
                    "new_state": {"visibility": "public_accepting"},
                    "note": "D8 backwards-compat default applied.",
                },
            )

        _LOG.info(
            "Phase 19 backfill: created %d OrgDelegateProfile row(s); "
            "audited %d DelegateProfile row(s) at default 'public_accepting'.",
            backfill_count, len(dp_rows),
        )


def downgrade() -> None:
    """Reverse the schema additions. Backfilled OrgDelegateProfile rows
    + any approval-workflow state on DelegateProfile rows are LOST."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # ----- 4 (reverse). Drop delegate_vote_rationales. -----
    if "delegate_vote_rationales" in existing_tables:
        existing_indexes = {
            ix.get("name")
            for ix in inspector.get_indexes("delegate_vote_rationales")
        }
        if "ix_delegate_vote_rationales_vote_id" in existing_indexes:
            op.drop_index(
                "ix_delegate_vote_rationales_vote_id",
                table_name="delegate_vote_rationales",
            )
        op.drop_table("delegate_vote_rationales")

    # ----- 3 (reverse). Drop users.delegate_handle. -----
    inspector = sa.inspect(bind)
    if "users" in inspector.get_table_names():
        existing_cols = {c["name"] for c in inspector.get_columns("users")}
        if "delegate_handle" in existing_cols:
            existing_uniques = {
                uq.get("name")
                for uq in inspector.get_unique_constraints("users")
            }
            existing_indexes = {
                ix.get("name") for ix in inspector.get_indexes("users")
            }
            with op.batch_alter_table("users", schema=None) as batch_op:
                if "ix_users_delegate_handle" in existing_indexes:
                    batch_op.drop_index("ix_users_delegate_handle")
                if "uq_users_delegate_handle" in existing_uniques:
                    batch_op.drop_constraint(
                        "uq_users_delegate_handle", type_="unique"
                    )
                batch_op.drop_column("delegate_handle")

    # ----- 2 (reverse). Drop new delegate_profiles columns. -----
    inspector = sa.inspect(bind)
    if "delegate_profiles" in inspector.get_table_names():
        existing_cols = {
            c["name"] for c in inspector.get_columns("delegate_profiles")
        }
        existing_fks = {
            fk.get("name")
            for fk in inspector.get_foreign_keys("delegate_profiles")
        }
        with op.batch_alter_table("delegate_profiles", schema=None) as batch_op:
            if "public_accepting_approved_by_id" in existing_cols:
                if (
                    "fk_delegate_profiles_public_accepting_approved_by_id"
                    in existing_fks
                ):
                    batch_op.drop_constraint(
                        "fk_delegate_profiles_public_accepting_approved_by_id",
                        type_="foreignkey",
                    )
                batch_op.drop_column("public_accepting_approved_by_id")
            if "public_accepting_denied_comment" in existing_cols:
                batch_op.drop_column("public_accepting_denied_comment")
            if "public_accepting_approved_at" in existing_cols:
                batch_op.drop_column("public_accepting_approved_at")
            if "public_accepting_submitted_at" in existing_cols:
                batch_op.drop_column("public_accepting_submitted_at")
            if "position_statement" in existing_cols:
                batch_op.drop_column("position_statement")
            if "visibility" in existing_cols:
                batch_op.drop_column("visibility")

    # ----- 1 (reverse). Drop org_delegate_profiles. -----
    inspector = sa.inspect(bind)
    if "org_delegate_profiles" in inspector.get_table_names():
        existing_indexes = {
            ix.get("name")
            for ix in inspector.get_indexes("org_delegate_profiles")
        }
        if "ix_org_delegate_profiles_user_id" in existing_indexes:
            op.drop_index(
                "ix_org_delegate_profiles_user_id",
                table_name="org_delegate_profiles",
            )
        if "ix_org_delegate_profiles_org_id" in existing_indexes:
            op.drop_index(
                "ix_org_delegate_profiles_org_id",
                table_name="org_delegate_profiles",
            )
        op.drop_table("org_delegate_profiles")

    # Drop the named ENUM types (PG only — SQLite ignores them).
    # On PG, these would otherwise leak across downgrade/upgrade cycles.
    if bind.dialect.name == "postgresql":
        sa.Enum(name="org_delegate_page_visibility").drop(bind, checkfirst=True)
        sa.Enum(name="delegate_profile_visibility").drop(bind, checkfirst=True)
