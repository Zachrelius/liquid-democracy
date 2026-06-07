"""Phase 59 Cluster E — one-shot, idempotent removal of the orphaned
`slug='demo'` Organization row.

Background: an "ORG with slug=demo" was seeded by the legacy
`_seed_demo` pipeline (backend/seed_data.py) when IS_PUBLIC_DEMO=true
on first boot. That seed predates the Phase 23 three-bible demo
system (HOA / Local 4021 / Coalition) which manages today's demo
content. The legacy demo-org row is no longer reachable because the
`/demo` ROUTE was repurposed as the demo-login/marketing page, so the
slug `demo` no longer resolves to that org row in the FE. It just
clutters org-level queries.

This script:
  1. Looks up an Organization with slug='demo'.
  2. If absent → no-op, exit 0.
  3. If present → reports what will be deleted (rows + dependents),
     and (when --confirm is passed) hard-deletes the org + its
     cascaded dependents.

USAGE:
  # Dry run (default) — reports counts but deletes nothing.
  DATABASE_URL=... python backend/scripts/phase59_remove_orphaned_demo_org.py

  # Actually delete.
  DATABASE_URL=... python backend/scripts/phase59_remove_orphaned_demo_org.py --confirm

Safety:
  * Idempotent: subsequent runs after a successful delete report
    "no orphan found" + exit 0.
  * Aborts if the row is not what we expect (slug='demo' but
    in the 3-bible system somehow — `is_demo=True` AND a sub-org of a
    bible-managed parent, or having personas). The 3-bible orgs have
    slugs like `demo-cedar-hollow`, NOT bare `demo` — but the check
    is defensive.
  * Hard-deletes via ORM (relies on the
    `cascade='all, delete-orphan'` on Organization.memberships /
    invitations / sub_orgs / sub_org_memberships / delegate_profiles_org).
  * For relationships WITHOUT cascade (Proposal, Topic, DelegateProfile
    — those have `nullable=True` FKs without ON DELETE), the script
    explicitly deletes the dependent rows first so the org-delete
    doesn't FK-violate.

Audit trail: the script writes an audit log entry
`org.deleted` BEFORE the delete fires.
"""
from __future__ import annotations

import argparse
import os
import sys

# Add the backend dir to sys.path so we can import the project modules
# when invoked as `python backend/scripts/phase59_...py`.
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import models  # noqa: E402
from database import SessionLocal  # noqa: E402
from audit_utils import log_audit_event  # noqa: E402


ORPHAN_SLUG = "demo"


def _gather_counts(db, org: "models.Organization") -> dict:
    """Count what would be deleted alongside the org."""
    counts: dict[str, int] = {}
    counts["memberships"] = db.query(models.OrgMembership).filter_by(
        org_id=org.id,
    ).count()
    counts["invitations"] = db.query(models.Invitation).filter_by(
        org_id=org.id,
    ).count()
    counts["proposals"] = db.query(models.Proposal).filter_by(
        org_id=org.id,
    ).count()
    counts["topics"] = db.query(models.Topic).filter_by(
        org_id=org.id,
    ).count()
    counts["delegate_profiles"] = db.query(models.DelegateProfile).filter_by(
        org_id=org.id,
    ).count()
    counts["roles"] = db.query(models.Role).filter_by(
        org_id=org.id,
    ).count()
    counts["sub_orgs"] = db.query(models.Organization).filter_by(
        parent_org_id=org.id,
    ).count()
    return counts


def _is_managed_demo_bible(org: "models.Organization") -> bool:
    """Heuristic: is this row one of the three managed demo bibles?

    The bibles have slugs like `demo-cedar-hollow`, `demo-local-4021`,
    `demo-westgate-coalition`. The bare slug `demo` is NOT one of them
    (this is the orphan we're removing). The heuristic also flags any
    org with bible-style personas / display_order / governance_type
    set, which the 3-bible seed populates.
    """
    if org.slug in (
        "demo-cedar-hollow",
        "demo-local-4021",
        "demo-westgate-coalition",
    ):
        return True
    # The orphan should NOT have personas; if it does, something's
    # off and we abort.
    if org.personas:
        return True
    if org.governance_type:
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 59 Cluster E — remove the orphaned slug='demo' org."
        ),
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help=(
            "Actually delete the row. Without this flag the script "
            "runs in dry-run mode and reports counts only."
        ),
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        org = db.query(models.Organization).filter_by(
            slug=ORPHAN_SLUG,
        ).first()
        if org is None:
            print(
                f"[phase59-remove-orphan] No Organization with "
                f"slug={ORPHAN_SLUG!r} found. Nothing to do. (idempotent)"
            )
            return 0

        print(
            f"[phase59-remove-orphan] Found Organization "
            f"id={org.id!r}, slug={org.slug!r}, name={org.name!r}, "
            f"is_demo={org.is_demo!r}, parent_org_id={org.parent_org_id!r}, "
            f"personas={'present' if org.personas else 'absent'}"
        )

        if _is_managed_demo_bible(org):
            print(
                f"[phase59-remove-orphan] ABORT: org {org.slug!r} "
                f"looks like a managed 3-bible demo org (personas set, "
                f"or governance_type set, or known bible slug). Refusing "
                f"to delete a managed bible. If this is wrong, "
                f"investigate before proceeding."
            )
            return 2

        counts = _gather_counts(db, org)
        print("[phase59-remove-orphan] Will delete the org plus:")
        for k, v in counts.items():
            print(f"    {k}: {v}")

        if not args.confirm:
            print(
                "\n[phase59-remove-orphan] DRY RUN — pass --confirm to "
                "actually delete."
            )
            return 0

        print(
            "[phase59-remove-orphan] --confirm given. Deleting org + "
            "dependents..."
        )

        # Audit log entry BEFORE delete so it survives the cascade.
        log_audit_event(
            db,
            action="org.deleted",
            target_type="organization",
            target_id=org.id,
            actor_id=None,
            details={
                "phase": "59-cluster-e",
                "reason": (
                    "Orphaned legacy demo org cleanup; "
                    "predates Phase 23 three-bible system."
                ),
                "slug": org.slug,
                "counts": counts,
            },
        )

        # Pre-delete dependents that lack ORM cascade. The Organization
        # cascade covers memberships + invitations + sub_orgs +
        # sub_org_memberships + delegate_profiles_org (per back_populates
        # cascade), but Proposal / Topic / DelegateProfile have nullable
        # org_id FKs without cascade — delete those first.
        db.query(models.DelegateProfile).filter_by(org_id=org.id).delete(
            synchronize_session=False,
        )
        # Proposal cascade-deletes votes / proposal_topics / options /
        # snapshots via its own relationships.
        db.query(models.Proposal).filter_by(org_id=org.id).delete(
            synchronize_session=False,
        )
        db.query(models.Topic).filter_by(org_id=org.id).delete(
            synchronize_session=False,
        )
        # The role-permissions cascade is handled by Role's own
        # cascade='all, delete-orphan' on RolePermission; Role itself
        # is cleared by Organization's cascade list... actually Role
        # is NOT in Organization.cascade. Pre-delete Role rows too.
        db.query(models.Role).filter_by(org_id=org.id).delete(
            synchronize_session=False,
        )

        db.delete(org)
        db.commit()

        # Verify post-state.
        survivor = db.query(models.Organization).filter_by(
            slug=ORPHAN_SLUG,
        ).first()
        assert survivor is None, "delete didn't take effect"
        print(
            f"[phase59-remove-orphan] DONE. Organization {ORPHAN_SLUG!r} "
            f"deleted. Re-running this script will report no-op."
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
