"""Phase 11 B2 — slug-collision lint (read-only).

Phase 11 introduces path-based org URLs (/{org-slug}/...). Slugs at the
top-level position cannot collide with the frontend's reserved top-level
routes (marketing, auth, onboarding, user-scoped pages). The reserved
allowlist lives in `backend/reserved_slugs.py`.

The reserved-words check on slug CREATION (B1) prevents NEW collisions.
This script answers: do any EXISTING Organization rows in the database
have a slug that collides with the reserved set? If so, the lead surfaces
the findings to Z for manual rename via direct DB update before the
Phase 11 deploy lands.

The script is **read-only**. It performs only `db.query(...)` calls and
prints findings to stdout. Output format matches the spec (one line per
collision plus a header summary).

Iterates:
  - `Organization` rows where `parent_org_id IS NULL` -> top-level orgs
  - `Organization` rows where `parent_org_id IS NOT NULL` -> sub-orgs

For each, checks `slug.lower() in RESERVED_SLUGS`. Printed line per row
on collision:

    slug=<value> org_id=<id> name=<name> created_at=<timestamp> created_by=<user_id> kind=<org|sub-org>

`created_by` is resolved via the audit log (`org.created` /
`sub_org.created` events), since `Organization` itself doesn't carry a
creator FK. If no audit row exists (rare; pre-Phase-9.5 orgs) prints
`<unknown>`.

Invocation (from repo root with the venv):

    backend/.venv/Scripts/python backend/scripts/phase11_check_slug_collisions.py

For prod, the lead runs via Railway after merge:

    railway run python backend/scripts/phase11_check_slug_collisions.py

The script picks up DATABASE_URL from the environment via `database.py` /
`settings.py`, same pattern as the other scripts in this directory.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Optional

# Ensure backend/ is on sys.path so the imports resolve regardless of
# whether the script is run as a module or directly.
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from sqlalchemy.orm import Session  # noqa: E402

import models  # noqa: E402
from database import SessionLocal  # noqa: E402
from reserved_slugs import RESERVED_SLUGS  # noqa: E402


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _format_timestamp(ts: Optional[datetime]) -> str:
    if ts is None:
        return "<none>"
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_created_by(
    db: Session, org: models.Organization, kind: str,
) -> str:
    """Resolve the creating user via the audit log.

    `org.created` for top-level orgs, `sub_org.created` for sub-orgs.
    Returns the actor_id of the matching audit row, or `<unknown>` if
    no row exists (pre-Phase-9.5 orgs may have been seeded without
    audit emission, depending on origin).
    """
    action = "org.created" if kind == "org" else "sub_org.created"
    row = db.query(models.AuditLog).filter(
        models.AuditLog.action == action,
        models.AuditLog.target_id == org.id,
    ).order_by(models.AuditLog.timestamp.asc()).first()
    if row is None or row.actor_id is None:
        return "<unknown>"
    return row.actor_id


def scan(db: Session) -> dict:
    """Iterate all orgs + sub-orgs, return a dict suitable for rendering.

    Read-only: only db.query(...) calls; no mutation.
    """
    top_level = db.query(models.Organization).filter(
        models.Organization.parent_org_id.is_(None)
    ).order_by(models.Organization.created_at.asc()).all()
    sub_orgs = db.query(models.Organization).filter(
        models.Organization.parent_org_id.isnot(None)
    ).order_by(models.Organization.created_at.asc()).all()

    collisions: list[dict] = []

    for org in top_level:
        if org.slug and org.slug.lower() in RESERVED_SLUGS:
            collisions.append({
                "slug": org.slug,
                "org_id": org.id,
                "name": org.name,
                "created_at": org.created_at,
                "created_by": _resolve_created_by(db, org, "org"),
                "kind": "org",
            })

    for sub in sub_orgs:
        if sub.slug and sub.slug.lower() in RESERVED_SLUGS:
            collisions.append({
                "slug": sub.slug,
                "org_id": sub.id,
                "name": sub.name,
                "created_at": sub.created_at,
                "created_by": _resolve_created_by(db, sub, "sub-org"),
                "kind": "sub-org",
            })

    return {
        "total_orgs_scanned": len(top_level),
        "total_sub_orgs_scanned": len(sub_orgs),
        "collisions": collisions,
    }


def render_report(result: dict, run_timestamp_iso: str) -> str:
    lines: list[str] = []
    lines.append("Phase 11 slug-collision lint")
    lines.append(f"Run timestamp: {run_timestamp_iso}")
    lines.append(f"Total orgs scanned: {result['total_orgs_scanned']}")
    lines.append(f"Total sub-orgs scanned: {result['total_sub_orgs_scanned']}")
    lines.append(f"Colliding slugs found: {len(result['collisions'])}")
    lines.append("")
    if result["collisions"]:
        for c in result["collisions"]:
            lines.append(
                f"slug={c['slug']} "
                f"org_id={c['org_id']} "
                f"name={c['name']} "
                f"created_at={_format_timestamp(c['created_at'])} "
                f"created_by={c['created_by']} "
                f"kind={c['kind']}"
            )
    else:
        lines.append("(no collisions)")

    return "\n".join(lines) + "\n"


def main() -> int:
    run_ts_iso = _now_utc_iso()
    db = SessionLocal()
    try:
        result = scan(db)
    finally:
        db.close()

    report = render_report(result, run_ts_iso)
    print(report, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
