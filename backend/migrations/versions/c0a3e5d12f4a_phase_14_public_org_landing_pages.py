"""Phase 14 — Public org landing pages: rename ``join_policy='invite_only'``
to ``'invite_only_secret'`` and reserve the new ``invite_only_public`` value.

Revision ID: c0a3e5d12f4a
Revises: b9e2f4a17c83
Create Date: 2026-05-04 22:00:00.000000

What this does
--------------

One coordinated change:

* **Data migration:** ``UPDATE organizations SET join_policy =
  'invite_only_secret' WHERE join_policy = 'invite_only';``  Idempotent
  (re-running upgrade is a no-op once the rename is done).

The ``join_policy`` column is a plain ``String`` in models.py, not a
PG-side ENUM type — so no ``ALTER TYPE ... ADD VALUE`` is required. The
new value ``invite_only_public`` is enforced at the application layer
via ``backend/schemas.py``'s ``OrgCreate``/``OrgUpdate`` validators
(updated in B5 of this pass). ``approval_required`` and ``open`` rows
are left untouched.

The ``intro_text`` field lives in the existing ``Organization.settings``
JSON column (Phase 12.7's branding lives there too), so no schema
column change is needed; ``backend/org_config.get_intro_text`` reads it
defensively.

Downgrade
---------

Best-effort reversal:

1. Rename ``invite_only_secret`` rows back to ``invite_only`` so the
   value set under the prior revision (``invite_only`` / ``approval_required``
   / ``open``) is coherent.
2. Rename ``invite_only_public`` rows ALSO to ``invite_only``. This is
   lossy: the public-landing-page distinction the Phase 14 deploy added
   is collapsed back to invite-only-with-no-public-surface. The
   downgrade docstring and DEPLOYMENT.md both call this out — operators
   doing a downgrade after stewards opted into ``invite_only_public``
   should be aware their orgs lose the public-splash exposure on revert.

No schema-side type change to undo (the column is plain String).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c0a3e5d12f4a'
down_revision: Union[str, None] = 'b9e2f4a17c83'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_tables(inspector) -> set[str]:
    try:
        return set(inspector.get_table_names())
    except Exception:
        return set()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = _existing_tables(inspector)

    if "organizations" not in tables:
        return

    # Idempotent value rename. Repeated upgrade is a no-op once no rows
    # match the WHERE clause.
    bind.execute(sa.text(
        "UPDATE organizations "
        "SET join_policy = 'invite_only_secret' "
        "WHERE join_policy = 'invite_only'"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = _existing_tables(inspector)

    if "organizations" not in tables:
        return

    # Reverse the value rename. invite_only_public collapses to invite_only
    # too — lossy but coherent under the prior revision's value set.
    bind.execute(sa.text(
        "UPDATE organizations "
        "SET join_policy = 'invite_only' "
        "WHERE join_policy IN ('invite_only_secret', 'invite_only_public')"
    ))
