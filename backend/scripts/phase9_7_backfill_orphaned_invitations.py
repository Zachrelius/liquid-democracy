"""Phase 9.7 Workstream 2 — backfill orphaned pending invitations.

Phase 9.7 W1 makes the register/login endpoints invitation-aware so that
new users invited to a non-demo org actually land in that org instead of
silently joining demo via the IS_PUBLIC_DEMO=true auto-join. This script
rescues the prior victims: ``Invitation`` rows still in ``pending`` whose
target email matches an existing user account that registered between the
shipping of Phase 6.5's auto-join and the shipping of Phase 9.7's
register-with-invitation handling.

Logic (per ``Invitation`` row in ``pending`` status):

  1. Look up the user account by email (case-insensitive). If no user
     exists, skip silently — the invitation is just waiting for the user
     to register, which is the normal pending state.
  2. If the user is already an active member of the inviting org, mark
     the invitation accepted (with ``accepted_at = now``) and increment
     the ``already_member`` counter. No membership row is changed.
  3. Otherwise create an active ``OrgMembership`` with the invitation's
     role, mark the invitation accepted, and increment ``rescued``.
  4. Bonus: if the user has an ``OrgMembership`` in ``demo`` AND the
     inviting org is NOT ``demo``, log "Auto-join victim" — informational
     only. The demo membership is NOT removed (users can be in multiple
     orgs; the friendlier behavior is to leave demo alone). Increment
     ``auto_join_victims``.

Idempotent — safe to re-run; on a second invocation only newly-arrived
pending invitations get processed (the previously-rescued ones are now
``accepted``).

Invocation (from ``backend/`` after activating the venv):

    .venv/Scripts/python.exe scripts/phase9_7_backfill_orphaned_invitations.py

Or as a module from the repo root:

    python -m backend.scripts.phase9_7_backfill_orphaned_invitations

Output is a single line per row mutated, plus a final summary of the form:

    Rescued: N. Already members: M. Auto-join victims observed: K.
    Total invitations processed: N+M.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from dataclasses import dataclass

# Ensure ``backend/`` is on sys.path so the imports resolve regardless of
# whether the script is run as a module or directly. Mirrors the pattern in
# ``phase9_6_backfill_sub_org_creator_memberships.py``.
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from sqlalchemy import func  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

import models  # noqa: E402
from database import SessionLocal  # noqa: E402

DEMO_ORG_SLUG = "demo"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class BackfillResult:
    rescued: int = 0
    already_member: int = 0
    auto_join_victims: int = 0

    @property
    def total_processed(self) -> int:
        return self.rescued + self.already_member


def backfill(db: Session) -> BackfillResult:
    """Run the backfill. Returns counters across the three branches."""
    result = BackfillResult()

    # Resolve the demo org once for the auto-join-victim signal lookup; it's
    # acceptable for it to be missing (non-public deployments).
    demo_org = db.query(models.Organization).filter(
        models.Organization.slug == DEMO_ORG_SLUG
    ).first()

    pending = (
        db.query(models.Invitation)
        .filter(models.Invitation.status == "pending")
        .order_by(models.Invitation.created_at.asc())
        .all()
    )

    now = _now()

    for inv in pending:
        # Case-insensitive user lookup by email. Invitation emails are stored
        # lower-cased on create (see routes/organizations.py::send_invitation),
        # but defensive lower() here means manually-inserted rows still match.
        user = (
            db.query(models.User)
            .filter(func.lower(models.User.email) == inv.email.lower())
            .first()
        )
        if user is None:
            continue

        org = db.get(models.Organization, inv.org_id)
        org_slug = org.slug if org else f"<missing org id={inv.org_id}>"

        existing = (
            db.query(models.OrgMembership)
            .filter(
                models.OrgMembership.user_id == user.id,
                models.OrgMembership.org_id == inv.org_id,
                models.OrgMembership.status == "active",
            )
            .first()
        )

        if existing is not None:
            inv.status = "accepted"
            inv.accepted_at = now
            print(
                f"Already member: {user.username} in {org_slug} — marked accepted."
            )
            result.already_member += 1
        else:
            db.add(
                models.OrgMembership(
                    user_id=user.id,
                    org_id=inv.org_id,
                    role=inv.role,
                    status="active",
                )
            )
            inv.status = "accepted"
            inv.accepted_at = now
            print(f"Rescued: added {user.username} to {org_slug}.")
            result.rescued += 1

        # Auto-join-victim signal. Demo membership is left in place (users
        # can be in multiple orgs; harmless to leave); we only log it so
        # operators have a count of how often the bug bit before the fix.
        if (
            demo_org is not None
            and inv.org_id != demo_org.id
        ):
            demo_membership = (
                db.query(models.OrgMembership)
                .filter(
                    models.OrgMembership.user_id == user.id,
                    models.OrgMembership.org_id == demo_org.id,
                    models.OrgMembership.status == "active",
                )
                .first()
            )
            if demo_membership is not None:
                print(
                    f"Auto-join victim: {user.username} got auto-joined to "
                    f"demo before invitation was processed"
                )
                result.auto_join_victims += 1

        db.flush()

    if result.total_processed > 0:
        db.commit()
    else:
        db.rollback()

    print(
        f"Rescued: {result.rescued}. "
        f"Already members: {result.already_member}. "
        f"Auto-join victims observed: {result.auto_join_victims}. "
        f"Total invitations processed: {result.total_processed}."
    )
    return result


def main() -> int:
    db = SessionLocal()
    try:
        backfill(db)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
