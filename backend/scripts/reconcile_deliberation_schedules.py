"""Phase 102 production schedule inventory and gated reconciliation.

Dry-run is the default. ``--apply`` performs only the two locked mutations:
future ordinary legacy schedule initialization outside Reform Table, and
overdue ordinary Reform Table deliberation-to-voting reconciliation.  It
never accepts IDs, slugs, SQL, or notification controls from the command line.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import models
from audit_utils import log_audit_event
from database import SessionLocal
from proposal_lifecycle import transition_deliberation_to_voting


REFORM_TABLE_SLUG = "reform-table"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _derived_end(proposal: models.Proposal):
    if proposal.deliberation_start is None or proposal.deliberation_days is None:
        return None
    try:
        days = float(proposal.deliberation_days)
    except (TypeError, ValueError):
        return None
    if days < 0:
        return None
    return proposal.deliberation_start + timedelta(days=days)


def inventory(db, now: datetime) -> dict:
    orgs = {row.id: row.slug for row in db.query(models.Organization).all()}
    grouped = defaultdict(lambda: defaultdict(int))
    active = db.query(models.Proposal).filter(
        models.Proposal.status == "deliberation",
    ).all()
    for proposal in active:
        slug = orgs.get(proposal.org_id, "unscoped")
        if proposal.is_cosign_gated:
            category = "cosign_gated"
        elif proposal.deliberation_end is not None:
            category = "already_scheduled"
        else:
            derived = _derived_end(proposal)
            if derived is None:
                category = "invalid_or_missing_inputs"
            elif derived <= now:
                category = "overdue_ordinary"
            else:
                category = "future_ordinary"
        grouped[slug][category] += 1
    overdue_budget = db.query(models.Proposal).filter(
        models.Proposal.status == "voting",
        models.Proposal.voting_method.in_(["budget_allocation", "budget_project"]),
        models.Proposal.voting_end.is_not(None),
        models.Proposal.voting_end <= now,
    ).all()
    for proposal in overdue_budget:
        grouped[orgs.get(proposal.org_id, "unscoped")]["overdue_budget_voting"] += 1
    return {
        "checked_at": now.isoformat(),
        "organizations": {slug: dict(sorted(counts.items())) for slug, counts in sorted(grouped.items())},
        "overdue_budget_voting_total": len(overdue_budget),
    }


def apply_reconciliation(db, now: datetime) -> dict:
    changed = {"future_initialized": [], "reform_table_advanced": [], "failures": []}
    rows = db.query(models.Proposal, models.Organization).join(
        models.Organization, models.Organization.id == models.Proposal.org_id,
    ).filter(
        models.Proposal.status == "deliberation",
        models.Proposal.is_cosign_gated.is_(False),
        models.Proposal.deliberation_end.is_(None),
    ).order_by(models.Organization.slug, models.Proposal.id).all()
    for proposal, org in rows:
        derived = _derived_end(proposal)
        if derived is None:
            continue
        try:
            if org.slug != REFORM_TABLE_SLUG and derived > now:
                proposal.deliberation_end = derived
                log_audit_event(
                    db, action="proposal.schedule_initialized",
                    target_type="proposal", target_id=proposal.id,
                    actor_id=None,
                    details={
                        "proposal_id": proposal.id,
                        "trigger": "phase102_future_schedule_initialization",
                        "deliberation_end": derived.isoformat(),
                    },
                )
                db.commit()
                changed["future_initialized"].append({
                    "id": proposal.id, "title": proposal.title,
                    "org": org.slug, "deliberation_end": derived.isoformat(),
                })
            elif org.slug == REFORM_TABLE_SLUG and derived <= now:
                proposal.deliberation_end = derived
                result = transition_deliberation_to_voting(
                    db, proposal, org=org, actor_id=None, ip_address=None,
                    trigger="phase102_reform_table_reconciliation", now=now,
                    notifications_suppressed=True,
                )
                db.commit()
                # Deliberately no emit_status_notifications call: this is the
                # one server-internal, audited historical suppression mode.
                changed["reform_table_advanced"].append({
                    "id": proposal.id, "title": proposal.title,
                    "voting_start": result.occurred_at.isoformat(),
                    "voting_end": result.voting_end.isoformat(),
                })
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            changed["failures"].append({
                "id": proposal.id, "org": org.slug,
                "error_type": type(exc).__name__,
            })
    return changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="perform the locked reconciliation")
    args = parser.parse_args()
    now = _now()
    with SessionLocal() as db:
        before = inventory(db, now)
        output = {"mode": "apply" if args.apply else "dry_run", "before": before}
        if args.apply:
            output["changes"] = apply_reconciliation(db, now)
            output["after"] = inventory(db, _now())
        else:
            db.rollback()
        print(json.dumps(output, indent=2, sort_keys=True))
        if before["overdue_budget_voting_total"]:
            print("BLOCK: overdue budget voting proposals require owner disposition before enabling automation.", file=sys.stderr)
            return 2
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
