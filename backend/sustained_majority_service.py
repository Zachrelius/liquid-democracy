"""
Stable Result Required service — DB-touching glue between routes / worker and
the pure ``sustained_majority`` module.

The pure module (``sustained_majority.py``) takes data and returns decisions.
This service module reads snapshots, queries audit-log extension data, builds
status payloads for the API, and applies extensions in a single atomic
transaction. Routes and the background worker both live here.

Phase 20 redesign (from `sustained_majority_service`):

  - ``apply_failure_mode`` renamed to ``apply_extension`` (only the extension
    path remains; ``fail`` and ``escalate`` modes are gone).
  - ``build_status`` rewritten to emit the ``StableResultStatus`` shape
    (extension budget tracking; in_stable_window / in_extension flags).
  - ``SUSTAINED_MAJORITY_KEYS`` -> ``STABLE_RESULT_KEYS``.
  - ``diff_sustained_majority_settings`` -> ``diff_stable_result_settings``.
  - ``validate_per_proposal_override`` updated to read
    ``stable_result_per_proposal_override``.
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
    DestabilizationDecision,
    MultiOptionSnapshotPoint,
    StableResultConfig,
    get_stable_result_config,
    in_stable_result_window,
    is_proposal_stable_result_active,
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
    Reject a non-null per-proposal ``stable_result_required`` value when the
    org has ``stable_result_per_proposal_override: false``. Raises HTTP 403.

    Routes call this before persisting the override on a proposal.
    """
    if proposal_override is None or org is None:
        return
    config = get_stable_result_config(org)
    if not config.per_proposal_override:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=403,
            detail=(
                "This organization does not allow per-proposal "
                "Stable-Result-Required overrides. Ask an admin to enable "
                "it in org settings."
            ),
        )


def is_active_for_proposal(
    proposal: models.Proposal,
    org: Optional[models.Organization],
) -> bool:
    """Resolve whether Stable Result Required is in effect for this proposal."""
    if org is None:
        return False
    config = get_stable_result_config(org)
    return is_proposal_stable_result_active(
        proposal.stable_result_required, config.enabled_default,
    )


# ---------------------------------------------------------------------------
# Extension bookkeeping via audit log
# ---------------------------------------------------------------------------

def count_extensions(db: Session, proposal_id: str) -> int:
    """How many times has this proposal's voting window been extended by the
    worker (Stable Result Required)?

    Admin-driven extensions via resolve_escalation are excluded — they have
    actor_id set, and the worker's "is in extension?" question only counts
    system-fired extensions.
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


def _sum_extension_seconds(db: Session, proposal_id: str) -> int:
    """Sum the ``extension_seconds`` field from all worker-fired
    ``proposal.window_extended`` audit events on this proposal.

    Returns 0 when no extensions have fired (or when the audit details JSON
    is missing the field, which would be a bug — defensive fallback).

    This is the ground-truth for ``extension_budget_used``. Per spec line 308
    the alternative would be storing ``original_voting_end`` on the proposal
    column. We chose the audit-log path: avoids another migration, keeps the
    proposal model unchanged, and the audit events already record
    ``extension_seconds`` per the legacy ``apply_failure_mode`` extension
    branch.
    """
    rows = (
        db.query(models.AuditLog.details)
        .filter(
            models.AuditLog.action == "proposal.window_extended",
            models.AuditLog.target_id == proposal_id,
            models.AuditLog.actor_id.is_(None),
        )
        .all()
    )
    total = 0
    for (details,) in rows:
        if not details:
            continue
        seconds = details.get("extension_seconds") if isinstance(details, dict) else None
        if isinstance(seconds, (int, float)):
            total += int(seconds)
    return total


def _last_destabilization_at(
    db: Session,
    proposal_id: str,
) -> Optional[datetime]:
    """Most recent timestamp at which this proposal destabilized (granted an
    extension OR logged a force-close-on-exhausted-budget)."""
    row = (
        db.query(models.AuditLog.timestamp)
        .filter(
            models.AuditLog.target_id == proposal_id,
            models.AuditLog.action.in_((
                "proposal.window_extended",
                "proposal.destabilization_at_max_extensions",
            )),
            models.AuditLog.actor_id.is_(None),
        )
        .order_by(models.AuditLog.timestamp.desc())
        .first()
    )
    return row[0] if row else None


def reconstruct_original_voting_duration(
    db: Session,
    proposal: models.Proposal,
) -> Optional[timedelta]:
    """Compute the ORIGINAL voting period duration (pre-extensions).

    ``proposal.voting_end`` reflects the CURRENT deadline, after any extensions
    have been applied. To get the original duration we subtract the cumulative
    extension time from the current voting_end - voting_start span.
    """
    if not proposal.voting_start or not proposal.voting_end:
        return None
    current_span = proposal.voting_end - proposal.voting_start
    extended = timedelta(seconds=_sum_extension_seconds(db, proposal.id))
    original = current_span - extended
    if original.total_seconds() <= 0:
        return None
    return original


# ---------------------------------------------------------------------------
# Status block (read path)
# ---------------------------------------------------------------------------

def build_status(
    db: Session,
    proposal: models.Proposal,
    org: Optional[models.Organization],
) -> schemas.StableResultStatus:
    """Build the StableResultStatus payload for /results."""
    if org is None:
        return schemas.StableResultStatus(active=False)

    config = get_stable_result_config(org)
    active = is_proposal_stable_result_active(
        proposal.stable_result_required, config.enabled_default,
    )
    if not active:
        return schemas.StableResultStatus(
            active=False,
            stable_window_fraction=config.stable_window_fraction,
            max_extension_fraction=config.max_extension_fraction,
            voting_end=proposal.voting_end,
        )

    extension_count = count_extensions(db, proposal.id)
    in_extension = extension_count > 0

    original_duration = reconstruct_original_voting_duration(db, proposal)
    if original_duration is not None:
        extension_budget_total = int(
            original_duration.total_seconds() * config.max_extension_fraction
        )
    else:
        extension_budget_total = 0
    extension_budget_used = _sum_extension_seconds(db, proposal.id)
    extension_budget_remaining = max(
        0, extension_budget_total - extension_budget_used
    )

    in_window = False
    stable_window_starts_at: Optional[datetime] = None
    if proposal.voting_start and proposal.voting_end and original_duration is not None:
        # The stable window is anchored to the ORIGINAL voting period (the
        # "final 25% of the original 7-day vote"), not the current extended
        # span. While in an extension, the in_window flag should reflect "are
        # we past the stable_window_starts_at point of the original window?"
        original_voting_end = proposal.voting_start + original_duration
        in_window = in_stable_result_window(
            _now_naive(),
            proposal.voting_start,
            original_voting_end,
            config.stable_window_fraction,
        )
        stable_window_starts_at = (
            proposal.voting_start
            + original_duration * (1.0 - config.stable_window_fraction)
        )

    last_destab = _last_destabilization_at(db, proposal.id)

    return schemas.StableResultStatus(
        active=True,
        stable_window_fraction=config.stable_window_fraction,
        max_extension_fraction=config.max_extension_fraction,
        extension_budget_total_seconds=extension_budget_total,
        extension_budget_used_seconds=extension_budget_used,
        extension_budget_remaining_seconds=extension_budget_remaining,
        in_stable_window=in_window,
        in_extension=in_extension,
        stable_window_starts_at=stable_window_starts_at,
        voting_end=proposal.voting_end,
        last_destabilization_at=last_destab,
        extension_count=extension_count,
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

    For approval / ranked_choice proposals, also fills ``multi_option_winners``
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
        # Phase 22 D2: option_totals computed in the SAME tally pass as
        # winners + total_ballots_cast, so the chart's per-option line + the
        # winner-over-time bar are guaranteed consistent. For approval:
        # per-option approval count. For RCV/STV: first-choice count from
        # round 0 (deeper elimination rounds are captured separately by the
        # /results endpoint, not the trajectory snapshot).
        option_totals: dict[str, float] = {}
        if isinstance(tally, ApprovalTally):
            winners = sorted(tally.winners or [])
            total_cast = tally.total_ballots_cast
            total_abstain = tally.total_abstain
            not_cast = tally.not_cast
            option_totals = {
                oid: int(count)
                for oid, count in (tally.option_approvals or {}).items()
            }
        elif isinstance(tally, RCVTally):
            winners = sorted(tally.winners or [])
            total_cast = tally.total_ballots_cast
            total_abstain = tally.total_abstain
            not_cast = tally.not_cast
            if tally.rounds:
                option_totals = {
                    oid: float(count)
                    for oid, count in (tally.rounds[0].option_counts or {}).items()
                }
            else:
                option_totals = {}
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
                "option_totals": option_totals,
            },
        )
    db.add(snap)
    db.flush()
    return snap


# ---------------------------------------------------------------------------
# Extension application (worker write path)
# ---------------------------------------------------------------------------

def apply_extension(
    db: Session,
    proposal: models.Proposal,
    *,
    stable_window_duration: timedelta,
    decision: Optional[DestabilizationDecision] = None,
    actor_id: Optional[str] = None,
) -> datetime:
    """Extend voting_end by ``stable_window_duration``; log audit; return the
    new voting_end.

    Caller owns the surrounding transaction; this only stages writes. The
    audit action ``proposal.window_extended`` is preserved from the legacy
    code so existing audit-log readers (and ``count_extensions`` /
    ``_sum_extension_seconds``) continue to work.
    """
    old_end = proposal.voting_end
    new_end = (proposal.voting_end or _now_naive()) + stable_window_duration
    proposal.voting_end = _naive_utc(new_end)

    details = {
        "proposal_id": proposal.id,
        "voting_method": proposal.voting_method,
        "old_voting_end": old_end.isoformat() if old_end else None,
        "new_voting_end": proposal.voting_end.isoformat(),
        "extension_seconds": int(stable_window_duration.total_seconds()),
        "trigger": "stable_result_required",
    }
    if decision is not None:
        details["reason"] = decision.reason
        details["breach_sample"] = decision.breach_sample

    log_audit_event(
        db,
        action="proposal.window_extended",
        target_type="proposal",
        target_id=proposal.id,
        actor_id=actor_id,
        details=details,
    )
    return proposal.voting_end


def log_destabilization_at_max_extensions(
    db: Session,
    proposal: models.Proposal,
    *,
    decision: Optional[DestabilizationDecision] = None,
    extension_budget_used_seconds: int,
    extension_budget_total_seconds: int,
    actor_id: Optional[str] = None,
) -> None:
    """Record an ``proposal.destabilization_at_max_extensions`` audit event
    when destabilization fires but the extension budget is exhausted.

    No status mutation — proposal continues to its current voting_end and
    closes there normally per standard close logic. Per spec D11.
    """
    details = {
        "proposal_id": proposal.id,
        "voting_method": proposal.voting_method,
        "voting_end": proposal.voting_end.isoformat() if proposal.voting_end else None,
        "extension_budget_used_seconds": extension_budget_used_seconds,
        "extension_budget_total_seconds": extension_budget_total_seconds,
        "extension_budget_remaining_seconds": max(
            0, extension_budget_total_seconds - extension_budget_used_seconds
        ),
    }
    if decision is not None:
        details["reason"] = decision.reason
        details["breach_sample"] = decision.breach_sample

    log_audit_event(
        db,
        action="proposal.destabilization_at_max_extensions",
        target_type="proposal",
        target_id=proposal.id,
        actor_id=actor_id,
        details=details,
    )


# ---------------------------------------------------------------------------
# Org-settings audit
# ---------------------------------------------------------------------------

STABLE_RESULT_KEYS = (
    "stable_result_enabled_default",
    "stable_result_per_proposal_override",
    "stable_window_fraction",
    "max_extension_fraction",
)


def diff_stable_result_settings(
    old_settings: Optional[dict],
    new_settings: dict,
) -> dict:
    """Return only the Stable-Result keys that changed (post-merge), with
    old + new values. Used by the org-update route to emit a focused
    ``org.stable_result_config_changed`` audit event.
    """
    old = old_settings or {}
    changed: dict = {}
    for key in STABLE_RESULT_KEYS:
        if key not in new_settings:
            continue
        if old.get(key) != new_settings.get(key):
            changed[key] = {
                "old": old.get(key),
                "new": new_settings.get(key),
            }
    return changed
