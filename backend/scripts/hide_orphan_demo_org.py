"""One-shot, idempotent: hide the orphaned ``slug='demo'`` Organization
from /explore by flipping its discoverability to ``hidden``.

Background: "Demo Organization" (slug='demo') was the very first demo
org. The ``/demo`` FE route was later repurposed as the demo-login /
marketing page, so the org's splash is unreachable, but the row still
carries discoverability='listed' + is_demo=False, so it lingers on
/explore. Phase 59 shipped a hard-delete script for this same row
(phase59_remove_orphaned_demo_org.py) but it was never run against prod.

Z chose the reversible fix: hide it (don't delete). /explore filters on
``discoverability == 'listed'`` (routes/organizations.py get_explore_orgs),
so flipping to 'hidden' removes it from the index while preserving the
37 memberships + any proposals. Fully reversible (set it back to 'listed').

USAGE (prod env injected by Railway):
  # Dry run (default) — reports current state, changes nothing.
  railway run -- python backend/scripts/hide_orphan_demo_org.py
  # Actually flip.
  railway run -- python backend/scripts/hide_orphan_demo_org.py --confirm

Safety:
  * Aborts unless the row looks like the orphan: slug='demo',
    name='Demo Organization', is_demo=False, no parent. Refuses to
    touch a managed 3-bible demo org.
  * Idempotent: re-running after a successful flip reports already-hidden.
  * Audits ``org.discoverability_changed`` before commit.
"""
from __future__ import annotations

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import models  # noqa: E402
from database import SessionLocal  # noqa: E402
from audit_utils import log_audit_event  # noqa: E402

ORPHAN_SLUG = "demo"
EXPECTED_NAME = "Demo Organization"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Hide the orphaned slug='demo' org from /explore.",
    )
    parser.add_argument(
        "--confirm", action="store_true",
        help="Actually flip discoverability to 'hidden'. Default: dry run.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        org = db.query(models.Organization).filter_by(slug=ORPHAN_SLUG).first()
        if org is None:
            print(f"[hide-orphan] No org with slug={ORPHAN_SLUG!r}. No-op.")
            return 0

        print(
            f"[hide-orphan] Found id={org.id!r} slug={org.slug!r} "
            f"name={org.name!r} is_demo={org.is_demo!r} "
            f"parent_org_id={org.parent_org_id!r} "
            f"discoverability={org.discoverability!r}"
        )

        # Safety: only touch the expected orphan.
        if (
            org.name != EXPECTED_NAME
            or bool(org.is_demo)
            or org.parent_org_id is not None
        ):
            print(
                "[hide-orphan] ABORT: row does not match the expected "
                "orphan signature (name='Demo Organization', is_demo=False, "
                "no parent). Refusing to modify."
            )
            return 2

        if org.discoverability == "hidden":
            print("[hide-orphan] Already hidden. No-op. (idempotent)")
            return 0

        if not args.confirm:
            print(
                f"\n[hide-orphan] DRY RUN — would set discoverability "
                f"{org.discoverability!r} -> 'hidden'. Pass --confirm to apply."
            )
            return 0

        old = org.discoverability
        log_audit_event(
            db,
            action="org.discoverability_changed",
            target_type="organization",
            target_id=org.id,
            actor_id=None,
            details={
                "reason": "Hide orphaned legacy demo org from /explore",
                "slug": org.slug,
                "old": old,
                "new": "hidden",
            },
        )
        org.discoverability = "hidden"
        db.commit()

        fresh = db.query(models.Organization).filter_by(slug=ORPHAN_SLUG).first()
        assert fresh is not None and fresh.discoverability == "hidden", (
            "discoverability flip did not take effect"
        )
        print(
            f"[hide-orphan] DONE. discoverability {old!r} -> 'hidden'. "
            f"Org is now off /explore (reversible: set back to 'listed')."
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
