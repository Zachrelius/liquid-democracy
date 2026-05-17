"""Phase 30.1 B5 — Topic.name org-scoped uniqueness + prefix backfill.

Revision ID: a8c2d51e9f10
Revises: f3a8b25e90c7
Create Date: 2026-05-16 18:30:00.000000

Drops the global ``UNIQUE`` constraint on ``topics.name`` and replaces
it with a scoped ``UNIQUE (org_id, name)`` constraint. Backfills by
stripping the ``{org_slug}:`` prefix that the demo seed pipeline used
to add for global-uniqueness purposes.

Background: ``Topic.name`` had a global ``unique=True`` constraint
since the schema's pre-Alembic origins. Demo orgs needed multiple
topics with the same intent across orgs (``Budget`` in Cedar Hollow
and in Local 4021), so ``seed_pipeline.py`` worked around the
constraint by prefixing names with ``{bible.slug}:``. The prefix then
had to be stripped at the display layer, leading to a recurring
"prefix leaks into user-visible text" bug patched at the surface
five times (Phases 23.1, 25, 26, 28, 30 B4). Phase 30.1 fixes the
constraint instead so the prefix is never needed.

Idempotent: rerun finds zero prefixed names + the new constraint
already in place.

Spec: phase30_1_delegate_approval_and_topic_name_rootcause_dispatch_2026-05-16.md
cluster B5.
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = "a8c2d51e9f10"
down_revision = "f3a8b25e90c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # ---- Step 1 — backfill prefix-strip BEFORE the constraint change.
    # Doing this first means the new (org_id, name) constraint is
    # added against already-deduplicated data and can't violate.
    orgs = {
        row[0]: row[1]
        for row in bind.execute(text(
            "SELECT id, slug FROM organizations"
        )).fetchall()
    }
    topics = bind.execute(text(
        "SELECT id, name, org_id FROM topics WHERE name LIKE '%:%'"
    )).fetchall()
    for tid, tname, org_id in topics:
        if not org_id or org_id not in orgs:
            continue
        prefix = f"{orgs[org_id]}:"
        if tname.startswith(prefix):
            bind.execute(
                text("UPDATE topics SET name = :new WHERE id = :id"),
                {"new": tname[len(prefix):], "id": tid},
            )

    # ---- Step 2 — constraint swap. Wrapped in batch_alter_table so
    # SQLite can use the table-recreate path; PG operates in place.
    # Drop attempts are best-effort because the legacy constraint
    # name differs across deployments and dialects:
    #   - PG auto-generated `topics_name_key` (the typical pattern).
    #   - SQLite has no named constraint — the column-level UNIQUE
    #     is part of the table schema. batch_alter_table recreates
    #     the table without the column-level UNIQUE if the column
    #     definition is updated, but here we instead drop_constraint
    #     by name and tolerate failure.
    # Idempotency check: in test stacks where the schema was built via
    # ``Base.metadata.create_all`` AFTER Phase 30.1 updated models.py,
    # the new constraint is already in place. Skip the swap then.
    import sqlalchemy as _sa
    inspector = _sa.inspect(bind)
    existing_constraints = inspector.get_unique_constraints("topics")
    has_new_constraint = any(
        c.get("name") == "uq_topics_org_id_name"
        and set(c.get("column_names") or []) == {"org_id", "name"}
        for c in existing_constraints
    )
    if has_new_constraint:
        return

    if bind.dialect.name == "postgresql":
        # On PG, prefer explicit drop_constraint outside batch mode
        # so the constraint truly goes away.
        bind.execute(text(
            "ALTER TABLE topics DROP CONSTRAINT IF EXISTS topics_name_key"
        ))
        op.create_unique_constraint(
            "uq_topics_org_id_name",
            "topics",
            ["org_id", "name"],
        )
    else:
        # SQLite — recreate the table with the new constraint shape.
        # batch_alter_table copies columns from the current schema; we
        # pass the new UniqueConstraint via table_args so the recreated
        # table has it. The column-level UNIQUE on `name` from earlier
        # model defs is part of the column's introspected type and
        # carries over by default — we explicitly redeclare `name`
        # without a UNIQUE clause via alter_column.
        import sqlalchemy as _sa
        with op.batch_alter_table(
            "topics",
            recreate="always",
            table_args=[
                _sa.UniqueConstraint(
                    "org_id", "name", name="uq_topics_org_id_name",
                ),
            ],
        ) as batch_op:
            batch_op.alter_column(
                "name",
                existing_type=_sa.String(),
                existing_nullable=False,
            )


def downgrade() -> None:
    bind = op.get_bind()

    # Reverse step 2: drop the scoped unique, restore the global one.
    if bind.dialect.name == "postgresql":
        bind.execute(text(
            "ALTER TABLE topics DROP CONSTRAINT IF EXISTS uq_topics_org_id_name"
        ))
        op.create_unique_constraint(
            "topics_name_key",
            "topics",
            ["name"],
        )
    else:
        with op.batch_alter_table("topics") as batch_op:
            try:
                batch_op.drop_constraint(
                    "uq_topics_org_id_name", type_="unique",
                )
            except Exception:
                pass
            batch_op.create_unique_constraint(
                "topics_name_key", ["name"],
            )

    # Reverse step 1: re-prefix names. Only do this if names are
    # currently un-prefixed (idempotent — a re-run after a rolled-back
    # upgrade shouldn't double-prefix).
    orgs = {
        row[0]: row[1]
        for row in bind.execute(text(
            "SELECT id, slug FROM organizations"
        )).fetchall()
    }
    topics = bind.execute(text(
        "SELECT id, name, org_id FROM topics"
    )).fetchall()
    for tid, tname, org_id in topics:
        if not org_id or org_id not in orgs:
            continue
        slug = orgs[org_id]
        if not tname.startswith(f"{slug}:"):
            bind.execute(
                text("UPDATE topics SET name = :new WHERE id = :id"),
                {"new": f"{slug}:{tname}", "id": tid},
            )
