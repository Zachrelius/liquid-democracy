"""Phase 17: chain-only no-op for tie-resolution wiring.

Revision ID: d2a17cb3e45c
Revises: 9a8910210205
Create Date: 2026-05-09 00:00:00.000000

What this does
--------------

Nothing schema-side. Phase 17 wires the missing closure layer for tied
proposals (org-configurable tie resolution: ``broader_approval_base`` /
``expand_winners`` / ``earliest_decisive_vote`` / ``random_seed``) but
needs no new columns, no new tables, and no settings JSON updates:

  - The ``Proposal.tie_resolution`` JSON nullable column already exists
    on the model from earlier; Phase 17 is the first pass that actually
    *writes* to it. No DDL is required to start writing.
  - Org-level tie-resolution config lives in the existing
    ``Organization.settings`` JSON under the
    ``settings['tie_resolution']`` key; defaults-if-absent semantics in
    ``backend/org_config.py::get_org_tie_resolution_method`` cover every
    existing org transparently (D6: no settings backfill).
  - No new permission key (D2: existing ``org.edit_settings`` gates the
    tie-resolution config UI just like the threshold/duration knobs).

The migration file exists for two reasons:

  1. Maintaining the unbroken alembic chain so the next migration has a
     clean parent revision.
  2. Running the actual-upgrade-path verification script (``pg_smoke.py
     --mode actual-upgrade --prior-revision 9a8910210205``) gates the
     deploy.

Both ``upgrade()`` and ``downgrade()`` are ``pass`` by design.

Idempotency
-----------

Trivially idempotent: a no-op upgrade is safe to re-run, and a no-op
downgrade is safe to re-run.

Downgrade
---------

Nothing to undo.
"""
from typing import Sequence, Union


revision: str = 'd2a17cb3e45c'
down_revision: Union[str, None] = '9a8910210205'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Chain-only no-op. See module docstring for rationale.
    pass


def downgrade() -> None:
    # Chain-only no-op. See module docstring for rationale.
    pass
