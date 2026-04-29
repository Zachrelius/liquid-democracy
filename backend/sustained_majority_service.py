"""
Sustained-majority service — DB-touching glue between routes / worker and the
pure `sustained_majority` module.

The pure module (`sustained_majority.py`) takes data and returns decisions.
The service module reads snapshots, queries audit-log extension counts,
builds status payloads for the API, and applies failure-mode actions in a
single atomic transaction. Routes and the background job both live here.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

import models
import schemas
from audit_utils import log_audit_event
from sustained_majority import (
    BinarySnapshotPoint,
    FailureDecision,
    FLOOR_APPROACH_DELTA,
    MultiOptionSnapshotPoint,
    STABLE_RESULT_FRACTION,
    SustainedMajorityConfig,
    evaluate_binary,
    evaluate_multi_option,
    extension_window_for,
    get_sustained_majority_config,
    in_stable_result_window,
    is_approaching_floor,
    is_proposal_sustained_majority_active,
    should_trigger_failure,
)


def _naive_utc(dt: datetime) -> datetime:
    """SQLite stores naive UTC; comparisons need both sides naive."""
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Per-proposal validation
# ---------------------------------------------------------------------------

def validate_per_proposal_override(
    proposal_override: Optional[bool],
    org: Optional[models.Organization],
) -> None:
    """
    Reject a non-null per-proposal `sustained_majority_enabled` value when the
    org has `sustained_majority_per_proposal_override: false`. Raises HTTP 403.

    Routes call this before persisting the override on a proposal.
    """
    if proposal_override is None or org is None:
        return
    config = get_sustained_majority_config(org)
    if not config.per_proposal_override:
        # 403 (matches the existing voting-method gate pattern in
        # `_validate_proposal_creation`).
        from fastapi import HTTPException
        raise HTTPException(
            status_code=403,
            detail=(
                "This organization does not allow per-proposal sustained-"
                "majority overrides. Ask an admin to enable it in org settings."
            ),
        )


def is_active_for_proposal(
    proposal: models.Proposal,
    org: Optional[models.Organization],
) -> bool:
    """Resolve whether sustained-majority is in effect for this proposal."""
    if org is None:
        return False
    config = get_sustained_majority_config(org)
    return is_proposal_sustained_majority_active(
        proposal.sustained_majority_enabled, config.enabled_default,
    )


# ---------------------------------------------------------------------------
# Extension count via audit log
# ---------------------------------------------------------------------------

def count_extensions(db: Session, proposal_id: str) -> int:
    """How many times has this proposal's voting window been extended
    by the worker? Admin-driven extensions via resolve_escalation are
    excluded — they have actor_id set, and the worker's "extension
    already used" guard rail should only count system-fired extensions.
    """
    return (
        db.query(models.AuditLog)
        .filter(
            models.AuditLog.action == "proposal.window_extended",
            models.AuditLog.target_id == proposal_id,
            models.AuditLog.actor_id.is_(None),
        )
        .count()
    )


# ---------------------------------------------------------------------------
# Status block (read path)
# ---------------------------------------------------------------------------

def build_status(
    db: Session,
    proposal: models.Proposal,
    org: Optional[models.Organization],
) -> schemas.SustainedMajorityStatus:
    """Build the SustainedMajorityStatus payload for /results."""
    if org is None:
        return schemas.SustainedMajorityStatus(active=False)

    config = get_sustained_majority_config(org)
    active = is_proposal_sustained_majority_active(
        proposal.sustained_majority_enabled, config.enabled_default,
    )
    if not active:
        return schemas.SustainedMajorityStatus(
            active=False,
            threshold=config.threshold,
            floor=config.floor,
            failure_mode=config.failure_mode,
            voting_end=proposal.voting_end,
        )

    extension_count = count_extensions(db, proposal.id)

    # Pull the latest snapshot (if any).
    latest_snap = (
        db.query(models.VoteSnapshot)
        .filter(models.VoteSnapshot.proposal_id == proposal.id)
        .order_by(models.VoteSnapshot.simulated_time.desc())
        .first()
    )

    if proposal.voting_method == "binary":
        if latest_snap is None:
            return schemas.SustainedMajorityStatus(
                active=True,
                threshold=config.threshold,
                floor=config.floor,
                failure_mode=config.failure_mode,
                extension_count=extension_count,
                voting_end=proposal.voting_end,
            )
        sample = BinarySnapshotPoint(
            simulated_time=latest_snap.simulated_time,
            yes=latest_snap.yes_count,
            no=latest_snap.no_count,
            abstain=latest_snap.abstain_count,
            total_eligible=latest_snap.total_eligible,
        )
        support = sample.support_fraction
        breached = (
            sample.votes_cast > 0 and support < config.floor
        )
        approaching = is_approaching_floor(sample, config)
        return schemas.SustainedMajorityStatus(
            active=True,
            threshold=config.threshold,
            floor=config.floor,
            failure_mode=config.failure_mode,
            current_support=round(support, 4),
            distance_to_floor=round(support - config.floor, 4),
            floor_breached=breached,
            approaching_floor=approaching,
            extension_count=extension_count,
            voting_end=proposal.voting_end,
        )

    # Multi-option (approval / ranked_choice)
    now = _now_naive()
    in_window = False
    if proposal.voting_start and proposal.voting_end:
        in_window = in_stable_result_window(
            now, proposal.voting_start, proposal.voting_end,
        )

    current_winners: list[str] = []
    if latest_snap and latest_snap.multi_option_winners:
        current_winners = list(
            latest_snap.multi_option_winners.get("winners", []) or []
        )

    # `stable_result_locked` = we are in the final-X% window and at least one
    # snapshot was taken inside it (so future winner-changes are watched).
    stable_locked = bool(in_window and latest_snap is not None)

    return schemas.SustainedMajorityStatus(
        active=True,
        threshold=config.threshold,
        floor=config.floor,
        failure_mode=config.failure_mode,
        in_stable_result_window=in_window,
        stable_result_locked=stable_locked,
        current_winners=current_winners,
        extension_count=extension_count,
        voting_end=proposal.voting_end,
    )


# ---------------------------------------------------------------------------
# Snapshot capture (write path — used by worker + time-simulation)
# ---------------------------------------------------------------------------

def capture_snapshot(
    db: Session,
    proposal: models.Proposal,
    *,
    simulated_time: Optional[datetime] = None,
) -> models.VoteSnapshot:
    """Compute the live tally and persist it as a VoteSnapshot row.

    For approval / ranked_choice proposals, also fills `multi_option_winners`
    so the worker can detect winner changes across snapshots.

    Caller owns the transaction — this only adds + flushes; it does not commit.
    """
    from delegation_engine import (
        engine as delegation_engine,
        ApprovalTally,
        RCVTally,
    )

    when = _naive_utc(simulated_time) if simulated_time else _now_naive()
    tally = delegation_engine.compute_tally(proposal, db)

    if proposal.voting_method == "binary":
        snap = models.VoteSnapshot(
            proposal_id=proposal.id,
            simulated_time=when,
            yes_count=tally.yes,
            no_count=tally.no,
            abstain_count=tally.abstain,
            not_cast_count=tally.not_cast,
            total_eligible=tally.total_eligible,
            multi_option_winners=None,
        )
    else:
        winners: list[str]
        total_cast: int
        if isinstance(tally, ApprovalTally):
            winners = sorted(tally.winners or [])
            total_cast = tally.total_ballots_cast
            total_abstain = tally.total_abstain
            not_cast = tally.not_cast
        elif isinstance(tally, RCVTally):
            winners = sorted(tally.winners or [])
            total_cast = tally.total_ballots_cast
            total_abstain = tally.total_abstain
            not_cast = tally.not_cast
        else:
            winners = []
            total_cast = 0
            total_abstain = 0
            not_cast = 0
        snap = models.VoteSnapshot(
            proposal_id=proposal.id,
            simulated_time=when,
            yes_count=0,
            no_count=0,
            abstain_count=total_abstain,
            not_cast_count=not_cast,
            total_eligible=tally.total_eligible,
            multi_option_winners={
                "winners": winners,
                "total_ballots_cast": total_cast,
            },
        )
    db.add(snap)
    db.flush()
    return snap


# ---------------------------------------------------------------------------
# Failure-mode application
# ---------------------------------------------------------------------------

def apply_failure_mode(
    db: Session,
    proposal: models.Proposal,
    *,
    decision: FailureDecision,
    actor_id: Optional[str] = None,
    extension_length: Optional[timedelta] = None,
) -> str:
    """
    Mutate `proposal.status` (or voting_end) per the decision and write the
    matching audit event. Returns the resulting status.

    Caller owns the surrounding transaction; this only stages writes.
    """
    mode = decision.mode or "fail"
    details_base = {
        "proposal_id": proposal.id,
        "voting_method": proposal.voting_method,
        "reason": decision.reason,
        "breach_sample": decision.breach_sample,
    }

    if mode == "fail":
        proposal.status = "failed"
        log_audit_event(
            db,
            action="proposal.failed_sustained_majority",
            target_type="proposal",
            target_id=proposal.id,
            actor_id=actor_id,
            details=details_base,
        )
        return "failed"

    if mode == "extend":
        # Push voting_end forward by the original window length (or a caller-
        # provided custom length).
        if proposal.voting_start and proposal.voting_end:
            ext = extension_length or extension_window_for(
                proposal.voting_start, proposal.voting_end,
            )
        else:
            ext = extension_length or timedelta(days=7)
        old_end = proposal.voting_end
        new_end = (proposal.voting_end or _now_naive()) + ext
        proposal.voting_end = _naive_utc(new_end)
        log_audit_event(
            db,
            action="proposal.window_extended",
            target_type="proposal",
            target_id=proposal.id,
            actor_id=actor_id,
            details={
                **details_base,
                "old_voting_end": old_end.isoformat() if old_end else None,
                "new_voting_end": proposal.voting_end.isoformat(),
                "extension_seconds": int(ext.total_seconds()),
            },
        )
        return proposal.status  # unchanged (still "voting")

    if mode == "escalate":
        proposal.status = "unresolved"
        log_audit_event(
            db,
            action="proposal.escalated",
            target_type="proposal",
            target_id=proposal.id,
            actor_id=actor_id,
            details=details_base,
        )
        return "unresolved"

    # Defensive fallback — corrupt mode treated as fail.
    proposal.status = "failed"
    log_audit_event(
        db,
        action="proposal.failed_sustained_majority",
        target_type="proposal",
        target_id=proposal.id,
        actor_id=actor_id,
        details={**details_base, "fallback": "unrecognised mode"},
    )
    return "failed"


# ---------------------------------------------------------------------------
# Org-settings audit
# ---------------------------------------------------------------------------

SUSTAINED_MAJORITY_KEYS = (
    "sustained_majority_enabled_default",
    "sustained_majority_per_proposal_override",
    "sustained_majority_threshold",
    "sustained_majority_floor",
    "sustained_majority_failure_mode",
)


def diff_sustained_majority_settings(
    old_settings: Optional[dict],
    new_settings: dict,
) -> dict:
    """Return only the SM keys that changed (post-merge), with old + new values.

    Used by the org-update route to emit a focused
    `org.sustained_majority_config_changed` audit event when (and only when)
    one of the five SM keys actually moved.
    """
    old = old_settings or {}
    changed: dict = {}
    for key in SUSTAINED_MAJORITY_KEYS:
        if key not in new_settings:
            continue
        if old.get(key) != new_settings.get(key):
            changed[key] = {
                "old": old.get(key),
                "new": new_settings.get(key),
            }
    return changed
