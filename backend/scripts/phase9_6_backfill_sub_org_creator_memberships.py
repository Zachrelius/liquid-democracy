"""Phase 9.6 Workstream 2 — backfill SubOrgMembership rows for sub-org creators.

The Phase 9.6 forward fix in ``routes/sub_organizations.py::create_sub_org``
auto-adds the creating parent-org admin as an active sub-org admin. This
script backfills the same row for sub-orgs that were created BEFORE that
fix shipped (notably Z's Gloomhaven sub-org from the friend-pilot dry run).

Logic:
  1. Enumerate all ``Organization`` rows where ``parent_org_id IS NOT NULL``.
  2. For each, find the creator from the audit log: the actor on the most
     recent ``sub_org.created`` event whose ``target_id`` is the sub-org's id.
  3. If that user already has an active SubOrgMembership row for this
     sub-org, skip.
  4. Otherwise create a SubOrgMembership with ``role='admin'``,
     ``status='active'``.
  5. If no ``sub_org.created`` audit row exists (very old sub-orgs created
     before audit logging was wired here), skip with a warning line.

Idempotent — safe to re-run; nothing happens if every sub-org already has
its creator's membership row.

Invocation (from ``backend/`` after ``cd``-ing in or with PYTHONPATH=.``):

    .venv/Scripts/python.exe scripts/phase9_6_backfill_sub_org_creator_memberships.py

Or as a module from the repo root:

    python -m backend.scripts.phase9_6_backfill_sub_org_creator_memberships

Output is a single line per row created (sub-org slug + creator username),
plus warning lines for sub-orgs without a discoverable creator, and a final
total count.
"""
from __future__ import annotations

import os
import sys

# Ensure ``backend/`` is on sys.path so the imports resolve regardless of
# whether the script is run as a module or directly. Mirrors the pattern in
# ``phase8_5_pg_smoke_session2.py``.
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from sqlalchemy.orm import Session  # noqa: E402

import models  # noqa: E402
from database import SessionLocal  # noqa: E402


def _find_creator_id(db: Session, sub_org_id: str) -> str | None:
    """Return the creator user_id for a sub-org, or None if untraceable.

    The creator is the actor on the ``sub_org.created`` audit event whose
    target_id matches this sub-org's id. If multiple exist (shouldn't —
    creation is a single event), take the earliest.
    """
    event = (
        db.query(models.AuditLog)
        .filter(
            models.AuditLog.action == "sub_org.created",
            models.AuditLog.target_id == sub_org_id,
        )
        .order_by(models.AuditLog.timestamp.asc())
        .first()
    )
    if event is None:
        return None
    return event.actor_id


def backfill(db: Session) -> int:
    """Run the backfill. Returns the number of SubOrgMembership rows created."""
    sub_orgs = (
        db.query(models.Organization)
        .filter(models.Organization.parent_org_id.is_not(None))
        .order_by(models.Organization.created_at.asc())
        .all()
    )

    rows_added = 0
    for sub_org in sub_orgs:
        creator_id = _find_creator_id(db, sub_org.id)
        if creator_id is None:
            print(
                f"WARNING: Skipping {sub_org.slug}: no creator audit found "
                f"(no sub_org.created AuditLog row for target_id={sub_org.id})"
            )
            continue

        # Look up the creator user (defensive — audit row could reference a
        # since-deleted user, in which case the FK would already be broken).
        creator = db.get(models.User, creator_id)
        if creator is None:
            print(
                f"WARNING: Skipping {sub_org.slug}: creator user_id={creator_id} "
                f"not found in users table"
            )
            continue

        existing = (
            db.query(models.SubOrgMembership)
            .filter(
                models.SubOrgMembership.user_id == creator_id,
                models.SubOrgMembership.sub_org_id == sub_org.id,
                models.SubOrgMembership.status == "active",
            )
            .first()
        )
        if existing is not None:
            # Idempotency: creator already has an active membership row.
            continue

        # Also skip if there's a non-active row (pending_approval / suspended);
        # the creator's intent there is ambiguous and a backfill shouldn't
        # silently flip its status. Surface as a warning.
        non_active = (
            db.query(models.SubOrgMembership)
            .filter(
                models.SubOrgMembership.user_id == creator_id,
                models.SubOrgMembership.sub_org_id == sub_org.id,
            )
            .first()
        )
        if non_active is not None:
            print(
                f"WARNING: Skipping {sub_org.slug}: creator "
                f"{creator.username} has a non-active SubOrgMembership "
                f"(status={non_active.status}); not auto-promoting"
            )
            continue

        sm = models.SubOrgMembership(
            user_id=creator_id,
            sub_org_id=sub_org.id,
            role="admin",
            status="active",
        )
        db.add(sm)
        db.flush()
        print(f"Added: sub_org={sub_org.slug} creator={creator.username}")
        rows_added += 1

    if rows_added > 0:
        db.commit()
    else:
        # Nothing to commit, but rollback any pending state defensively.
        db.rollback()

    print(f"Total: {rows_added} rows added")
    return rows_added


def main() -> int:
    db = SessionLocal()
    try:
        backfill(db)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
