"""Phase 102 production schedule inventory and gated reconciliation.

Dry-run is the default. ``--apply`` performs only the two locked mutations:
future ordinary legacy schedule initialization outside Reform Table, and
overdue ordinary Reform Table deliberation-to-voting reconciliation.  It
never accepts IDs, slugs, SQL, or notification controls from the command line.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import models
from audit_utils import log_audit_event
from database import SessionLocal
from proposal_lifecycle import transition_deliberation_to_voting


REFORM_TABLE_SLUG = "reform-table"
_LIFECYCLE_MUTATION_COLUMNS = {
    "status", "deliberation_end", "voting_start", "voting_end", "updated_at",
}


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


def _content_state(rows: list[models.Proposal]) -> dict:
    """Return private proposal content/configuration comparison state."""
    columns = [
        column.name for column in models.Proposal.__table__.columns
        if column.name not in _LIFECYCLE_MUTATION_COLUMNS
    ]
    return {
        proposal.id: {name: getattr(proposal, name) for name in columns}
        for proposal in sorted(rows, key=lambda row: row.id)
    }


def _stable_hash(state: dict) -> str:
    """Hash private comparison state without exposing proposal content."""
    encoded = json.dumps(state, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def capture_verification_baseline(db, now: datetime) -> dict:
    """Capture private comparison state; only booleans/counts are printed."""
    reform = db.query(models.Organization).filter(
        models.Organization.slug == REFORM_TABLE_SLUG,
    ).one_or_none()
    reform_rows = (
        db.query(models.Proposal).filter(models.Proposal.org_id == reform.id).all()
        if reform else []
    )
    protected = {
        row.id: (
            row.status, row.deliberation_start, row.deliberation_end,
            row.voting_start, row.voting_end,
        )
        for row in reform_rows if row.status in {"voting", "withdrawn"}
    }
    unrelated_overdue = {}
    for proposal, org in db.query(models.Proposal, models.Organization).join(
        models.Organization, models.Organization.id == models.Proposal.org_id,
    ).filter(
        models.Proposal.status == "deliberation",
        models.Proposal.is_cosign_gated.is_(False),
        models.Proposal.deliberation_end.is_(None),
        models.Organization.slug != REFORM_TABLE_SLUG,
    ).all():
        derived = _derived_end(proposal)
        if derived is not None and derived <= now:
            unrelated_overdue[proposal.id] = (
                proposal.status, proposal.deliberation_end,
                proposal.deliberation_start, proposal.deliberation_days,
            )
    return {
        "started_at": now,
        "reform_content_state": _content_state(reform_rows),
        "protected": protected,
        "unrelated_overdue": unrelated_overdue,
    }


def verify_reconciliation(db, baseline: dict, changes: dict, now: datetime) -> dict:
    advanced_ids = [row["id"] for row in changes["reform_table_advanced"]]
    future_ids = [row["id"] for row in changes["future_initialized"]]
    reform = db.query(models.Organization).filter(
        models.Organization.slug == REFORM_TABLE_SLUG,
    ).one_or_none()
    reform_rows = (
        db.query(models.Proposal).filter(models.Proposal.org_id == reform.id).all()
        if reform else []
    )
    protected_after = {
        row.id: (
            row.status, row.deliberation_start, row.deliberation_end,
            row.voting_start, row.voting_end,
        )
        for row in reform_rows if row.id in baseline["protected"]
    }
    unrelated_after = {}
    if baseline["unrelated_overdue"]:
        for proposal in db.query(models.Proposal).filter(
            models.Proposal.id.in_(baseline["unrelated_overdue"]),
        ).all():
            unrelated_after[proposal.id] = (
                proposal.status, proposal.deliberation_end,
                proposal.deliberation_start, proposal.deliberation_days,
            )

    reconciliation_audits = []
    if advanced_ids:
        candidates = db.query(models.AuditLog).filter(
            models.AuditLog.action == "proposal.status_changed",
            models.AuditLog.target_id.in_(advanced_ids),
            models.AuditLog.timestamp >= baseline["started_at"],
        ).all()
        reconciliation_audits = [
            row for row in candidates
            if (row.details or {}).get("trigger") == "phase102_reform_table_reconciliation"
            and (row.details or {}).get("notifications_suppressed") is True
        ]
    audit_counts = Counter(row.target_id for row in reconciliation_audits)

    entered_voting_notifications = 0
    if advanced_ids:
        entered_voting_notifications = db.query(models.Notification).filter(
            models.Notification.target_id.in_(advanced_ids),
            models.Notification.created_at >= baseline["started_at"],
            models.Notification.event_type.like("proposal.entered_voting%"),
        ).count()

    future_audit_count = 0
    if future_ids:
        candidates = db.query(models.AuditLog).filter(
            models.AuditLog.action == "proposal.schedule_initialized",
            models.AuditLog.target_id.in_(future_ids),
            models.AuditLog.timestamp >= baseline["started_at"],
        ).all()
        future_audit_count = sum(
            1 for row in candidates
            if (row.details or {}).get("trigger") == "phase102_future_schedule_initialization"
        )

    post_inventory = inventory(db, now)
    reform_counts = post_inventory["organizations"].get(REFORM_TABLE_SLUG, {})
    content_after = _content_state(reform_rows)
    changed_content_columns = sorted({
        column
        for proposal_id, before_values in baseline["reform_content_state"].items()
        for column, before_value in before_values.items()
        if content_after.get(proposal_id, {}).get(column) != before_value
    })
    return {
        "advanced_count": len(advanced_ids),
        "reconciliation_audit_count": len(reconciliation_audits),
        "one_reconciliation_audit_per_advanced": (
            len(audit_counts) == len(advanced_ids)
            and all(audit_counts[proposal_id] == 1 for proposal_id in advanced_ids)
        ),
        "entered_voting_notification_count": entered_voting_notifications,
        "future_initialized_count": len(future_ids),
        "future_initialization_audit_count": future_audit_count,
        "reform_qualifying_overdue_count": reform_counts.get("overdue_ordinary", 0),
        "preexisting_voting_withdrawn_unchanged": protected_after == baseline["protected"],
        "content_configuration_unchanged": not changed_content_columns,
        "content_configuration_changed_columns": changed_content_columns,
        "content_configuration_hash": _stable_hash(content_after),
        "unrelated_overdue_unchanged": unrelated_after == baseline["unrelated_overdue"],
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
            baseline = capture_verification_baseline(db, now)
            output["changes"] = apply_reconciliation(db, now)
            verified_at = _now()
            output["after"] = inventory(db, verified_at)
            output["verification"] = verify_reconciliation(
                db, baseline, output["changes"], verified_at,
            )
        else:
            db.rollback()
        print(json.dumps(output, indent=2, sort_keys=True))
        if before["overdue_budget_voting_total"]:
            print("BLOCK: overdue budget voting proposals require owner disposition before enabling automation.", file=sys.stderr)
            return 2
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
