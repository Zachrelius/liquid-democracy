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

    # Idempotency check: when ``Base.metadata.create_all`` already built
    # the post-Phase-30.1 schema (e.g. test stacks), the new constraint
    # is in place and there's nothing to do. Skip everything.
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

    # ---- Step 1 — drop the legacy uniqueness BEFORE the backfill.
    # PG enforces the global unique on every UPDATE row by row, so
    # stripping a prefix on one topic can collide with another topic
    # in a different org that already had the un-prefixed name. The
    # constraint MUST be gone before we start renaming.
    #
    # The model carried both ``unique=True`` (auto-named constraint
    # ``topics_name_key``) AND ``index=True`` (auto-named index
    # ``ix_topics_name``) on the column; the index is ALSO unique by
    # virtue of the column-level unique, so both must go.
    if bind.dialect.name == "postgresql":
        bind.execute(text(
            "ALTER TABLE topics DROP CONSTRAINT IF EXISTS topics_name_key"
        ))
        # Drop the (now-unique) index too. Re-create it as a NON-unique
        # index for query performance — model still has ``index=True``.
        bind.execute(text("DROP INDEX IF EXISTS ix_topics_name"))
        bind.execute(text("CREATE INDEX ix_topics_name ON topics (name)"))

    # ---- Step 2 — backfill prefix-strip. Now safe because the global
    # unique is gone; the new scoped unique hasn't been added yet so
    # transient duplicates across orgs are allowed during the loop.
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

    # ---- Step 3 — add the new (org_id, name) scoped unique constraint.
    if bind.dialect.name == "postgresql":
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
