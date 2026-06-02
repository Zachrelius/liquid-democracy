"""phase 49a cluster B — proposal_creation_mode → allow_cosign_petition remap

Replaces the legacy three-way ``Organization.proposal_creation_mode``
(``open``/``cosign_required``/``admin_only``) with a single per-org
boolean ``settings.allow_cosign_petition``. The new model:

  * If a user holds ``proposal.create``: they create proposals
    directly (subject to the existing deliberation flow).
  * Else if ``settings.allow_cosign_petition`` is True: their
    proposal enters cosign-gathering and goes live on threshold.
  * Else: 403.

Migration mapping (preserves each existing org's effective behavior):
  * ``open`` → ``allow_cosign_petition = false``. Per-role
    ``proposal.create`` grants preserved verbatim (steward/admin/
    moderator hold it by default; member does not). Effective
    behavior unchanged.
  * ``cosign_required`` → ``allow_cosign_petition = true``. ALSO
    revoke any ``proposal.create`` row on the org's ``member`` role
    so members route through the cosign path (matches the old
    behavior where ``cosign_required`` mode sent member-tier
    creates through cosign regardless of their ``proposal.create``
    grant).
  * ``admin_only`` → ``allow_cosign_petition = false``. ALSO revoke
    any ``proposal.create`` row on the org's ``member`` role so
    members get 403 (matches the old behavior of the explicit
    admin_only block).

After backfill the legacy column is dropped. Down() restores the
column with a best-effort re-derivation (true→cosign_required;
false→open; the ``admin_only``-vs-``open`` distinction is lost on
downgrade, which is acceptable for test reversibility).

Hex-prefix revision ID per the Phase 48 Stage 2 incident lesson.

Revision ID: b9c2e0f43215
Revises: a7c1d8e94521
Create Date: 2026-06-02 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b9c2e0f43215"
down_revision: Union[str, None] = "a7c1d8e94521"
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
    bind = op.get_bind()
    has_mode_col = "proposal_creation_mode" in _existing_columns("organizations")

    # ---- 1. Backfill settings.allow_cosign_petition per org -----------------
    # Read each org's current proposal_creation_mode + settings, write
    # settings.allow_cosign_petition. Done via raw SQL so SQLite + Postgres
    # both work; JSON column round-trips through Python.
    #
    # The pre-check on column existence is load-bearing on Postgres:
    # transactional DDL means a SELECT against a missing column aborts
    # the entire migration transaction. Skip the data-backfill cleanly
    # when the column was never added (the pg_smoke fresh-DB path's
    # ``create_all`` skips it because today's model no longer has the
    # column).
    if has_mode_col:
        rows = list(bind.execute(sa.text(
            "SELECT id, proposal_creation_mode, settings FROM organizations"
        )))
    else:
        rows = []

    import json

    org_modes: dict[str, str] = {}
    for r in rows:
        org_id = r[0]
        mode = (r[1] or "open")
        raw_settings = r[2]
        org_modes[org_id] = mode
        # Normalize the settings to a dict.
        if raw_settings is None:
            settings = {}
        elif isinstance(raw_settings, str):
            try:
                settings = json.loads(raw_settings)
            except Exception:
                settings = {}
        elif isinstance(raw_settings, dict):
            settings = dict(raw_settings)
        else:
            settings = {}

        allow_cosign = (mode == "cosign_required")
        settings["allow_cosign_petition"] = bool(allow_cosign)
        # Write back. JSON serialization handled by Python on the
        # text bind for SQLite; Postgres accepts the JSON string.
        bind.execute(
            sa.text(
                "UPDATE organizations SET settings = :s WHERE id = :id"
            ),
            {"s": json.dumps(settings), "id": org_id},
        )

    # ---- 2. Revoke proposal.create from member role for cosign_required + admin_only orgs ----
    affected_org_ids = [
        org_id for org_id, mode in org_modes.items()
        if mode in ("cosign_required", "admin_only")
    ]
    if affected_org_ids:
        # Delete only the member-role row for proposal.create on each
        # affected org. Steward/admin/moderator rows are left alone.
        for org_id in affected_org_ids:
            bind.execute(
                sa.text(
                    "DELETE FROM role_permissions "
                    "WHERE permission_key = :pk AND role_id IN ("
                    "  SELECT id FROM roles WHERE org_id = :oid AND system_key = 'member'"
                    ")"
                ),
                {"pk": "proposal.create", "oid": org_id},
            )

    # ---- 3. Drop proposal_creation_mode column ------------------------------
    # SQLite's batch_alter_table rebuild copies all existing indexes to
    # the new table — so we must drop the Phase 46 index FIRST or the
    # rebuild tries to recreate it on a non-existent column.
    cols = _existing_columns("organizations")
    if "proposal_creation_mode" in cols:
        try:
            op.drop_index(
                "ix_organizations_proposal_creation_mode",
                table_name="organizations",
            )
        except Exception:
            # Some envs may not have the index (e.g. fresh-DB stamp head);
            # tolerate. batch_alter_table below still handles the drop.
            pass
        with op.batch_alter_table("organizations") as batch_op:
            batch_op.drop_column("proposal_creation_mode")


def downgrade() -> None:
    # Restore the column with default 'open'. Also recreate the
    # original Phase 46 index (``ix_organizations_proposal_creation_
    # mode``) so a subsequent downgrade past Phase 46 finds the
    # index it expects to drop — without this, the Phase 46
    # downgrade fails on "no such index" because SQLite's
    # batch_alter_table rebuild lost it when this migration's
    # upgrade dropped the column.
    cols = _existing_columns("organizations")
    if "proposal_creation_mode" not in cols:
        with op.batch_alter_table("organizations") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "proposal_creation_mode", sa.String(length=20),
                    nullable=False, server_default="open",
                ),
            )
        try:
            op.create_index(
                "ix_organizations_proposal_creation_mode",
                "organizations",
                ["proposal_creation_mode"],
            )
        except Exception:
            pass

    bind = op.get_bind()
    try:
        rows = list(bind.execute(sa.text(
            "SELECT id, settings FROM organizations"
        )))
    except Exception:
        rows = []

    import json

    for r in rows:
        org_id = r[0]
        raw_settings = r[1]
        if raw_settings is None:
            settings = {}
        elif isinstance(raw_settings, str):
            try:
                settings = json.loads(raw_settings)
            except Exception:
                settings = {}
        elif isinstance(raw_settings, dict):
            settings = dict(raw_settings)
        else:
            settings = {}

        allow_cosign = bool(settings.get("allow_cosign_petition", False))
        mode = "cosign_required" if allow_cosign else "open"
        bind.execute(
            sa.text(
                "UPDATE organizations SET proposal_creation_mode = :m WHERE id = :id"
            ),
            {"m": mode, "id": org_id},
        )
        # Strip the toggle key from settings (clean down).
        if "allow_cosign_petition" in settings:
            settings.pop("allow_cosign_petition", None)
            bind.execute(
                sa.text(
                    "UPDATE organizations SET settings = :s WHERE id = :id"
                ),
                {"s": json.dumps(settings), "id": org_id},
            )
