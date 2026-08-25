"""Route-independent proposal lifecycle mutations (Phase 102).

The service owns lifecycle clocks, voting-deadline resolution, election
option locking, audit rows, and post-commit notification orchestration.  HTTP
routes, background workers, bulk APIs, and reconciliation all call this same
surface; callers retain their own transaction boundaries.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

import models
from audit_utils import log_audit_event
from delegation_engine import eligible_voter_ids_for_proposal
from notification_emit import emit_notification, user_has_any_channel_enabled
from org_config import get_default_proposal_durations


log = logging.getLogger(__name__)
VOTING_DAYS_FLOOR = 0.05


@dataclass(frozen=True)
class LifecycleResult:
    proposal_id: str
    old_status: str
    new_status: str
    occurred_at: datetime
    deliberation_end: Optional[datetime]
    voting_end: Optional[datetime]
    trigger: str
    notifications_suppressed: bool = False


def utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def strip_tz(value: Optional[datetime]) -> Optional[datetime]:
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def effective_deliberation_days(
    proposal: models.Proposal, org: Optional[models.Organization],
) -> float:
    value = getattr(proposal, "deliberation_days", None)
    if value is None:
        value, _ = get_default_proposal_durations(org)
    if value is None or float(value) < 0:
        raise ValueError("proposal has no valid deliberation duration")
    return float(value)


def compute_voting_end(
    *, voting_start: datetime, body_voting_end: Optional[datetime],
    proposal: models.Proposal, org: Optional[models.Organization],
) -> datetime:
    """Resolve the actual voting deadline with absolute-date precedence."""
    explicit = strip_tz(body_voting_end)
    if explicit is not None:
        log.warning(
            "proposal lifecycle: body voting_end is deprecated "
            "(proposal_id=%s)", proposal.id,
        )
        end = explicit
    else:
        absolute = strip_tz(getattr(proposal, "voting_end_date", None))
        if absolute is not None:
            end = absolute
        else:
            days = getattr(proposal, "voting_days", None)
            if days is None:
                _, days = get_default_proposal_durations(org)
            if days is None or float(days) <= 0:
                raise HTTPException(
                    status_code=400,
                    detail=("Cannot advance to voting: proposal has no "
                            "positive voting_days and no positive organization default."),
                )
            end = voting_start + timedelta(days=float(days))

    if end <= voting_start:
        raise HTTPException(
            status_code=400,
            detail="The specified voting end date has already passed or is before voting starts.",
        )
    days = (end - voting_start).total_seconds() / 86400
    if days < VOTING_DAYS_FLOOR:
        raise HTTPException(
            status_code=400,
            detail=("The voting window is below the minimum of 0.05 days "
                    "(~72 minutes)."),
        )
    return end


def lock_election_candidate_options(
    db: Session, proposal: models.Proposal,
) -> None:
    if not getattr(proposal, "is_election", False) or proposal.options:
        return
    from elections import active_candidacies
    for position, candidacy in enumerate(active_candidacies(db, proposal.id)):
        user = db.get(models.User, candidacy.user_id)
        db.add(models.ProposalOption(
            proposal_id=proposal.id,
            label=candidacy.user_id,
            description=user.display_name if user else candidacy.user_id,
            display_order=position,
        ))
    db.flush()


def resolve_tie_if_needed(
    proposal: models.Proposal, tally: Any, voting_method: str,
    db: Session, *, actor_id: Optional[str],
) -> None:
    """Route-independent tie mutation used by manual and worker closes."""
    from org_config import get_org_tie_resolution_method
    from tie_resolution import resolve_tie

    boundary = list(getattr(tally, "boundary_tied", None) or [])
    seats = int(getattr(tally, "seats_remaining", 0) or 0)
    boundary_tie = bool(boundary) and seats > 0
    if not boundary_tie and not (
        getattr(tally, "tied", False)
        and len(getattr(tally, "winners", []) or []) > 1
    ):
        return
    org = db.get(models.Organization, proposal.org_id) if proposal.org_id else None
    method = get_org_tie_resolution_method(org, voting_method)
    try:
        if boundary_tie:
            chosen: list[str] = []
            seed: Optional[str] = None
            rounds: list[Any] = []
            if method == "expand_winners":
                result = resolve_tie(method, boundary, proposal, tally, db)
                chosen = list(result.chosen_winners)
                seed = result.seed
                rounds.append(result.metadata)
            else:
                remaining = sorted(boundary)
                for _ in range(seats):
                    if not remaining:
                        break
                    result = resolve_tie(method, remaining, proposal, tally, db)
                    picks = [item for item in result.chosen_winners if item in remaining]
                    chosen.extend(picks)
                    remaining = [item for item in remaining if item not in picks]
                    seed = result.seed or seed
                    rounds.append(result.metadata)
        else:
            result = resolve_tie(
                method, list(tally.winners), proposal, tally, db,
            )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Tie resolution invariant violated: {exc}",
        ) from exc

    applied_at = datetime.now(timezone.utc).isoformat()
    if boundary_tie:
        proposal.tie_resolution = {
            "method": method, "input_winners": boundary,
            "chosen_winners": chosen, "seed": seed,
            "metadata": {"boundary_tie": True, "seats_remaining": seats, "rounds": rounds},
            "applied_at": applied_at,
        }
        tally.winners = list(tally.winners) + [
            item for item in chosen if item not in tally.winners
        ]
        if hasattr(tally, "winner_seats"):
            for item in chosen:
                tally.winner_seats.setdefault(item, "tie_resolution")
        details = {
            "method": method, "input_winners": boundary,
            "chosen_winners": chosen, "boundary_tie": True,
            "seats_remaining": seats,
        }
    else:
        proposal.tie_resolution = {
            "method": result.method, "input_winners": result.input_winners,
            "chosen_winners": result.chosen_winners, "seed": result.seed,
            "metadata": result.metadata, "applied_at": applied_at,
        }
        tally.winners = result.chosen_winners
        details = {
            "method": result.method, "input_winners": result.input_winners,
            "chosen_winners": result.chosen_winners,
        }
    log_audit_event(
        db, action="proposal.tie_resolved", target_type="proposal",
        target_id=proposal.id, actor_id=actor_id, details=details,
    )


def transition_draft_to_deliberation(
    db: Session, proposal: models.Proposal, *,
    org: Optional[models.Organization] = None,
    actor_id: Optional[str], ip_address: Optional[str],
    now: Optional[datetime] = None,
) -> LifecycleResult:
    if proposal.status != "draft":
        raise ValueError("draft-to-deliberation transition requires draft status")
    when = strip_tz(now) or utcnow_naive()
    days = effective_deliberation_days(proposal, org)
    proposal.deliberation_start = when
    proposal.deliberation_end = when + timedelta(days=days)
    proposal.status = "deliberation"
    result = LifecycleResult(
        proposal.id, "draft", "deliberation", when,
        proposal.deliberation_end, None, "manual",
    )
    log_audit_event(
        db, action="proposal.status_changed", target_type="proposal",
        target_id=proposal.id, actor_id=actor_id,
        details={"proposal_id": proposal.id, "old_status": "draft",
                 "new_status": "deliberation"},
        ip_address=ip_address,
    )
    return result


def transition_deliberation_to_voting(
    db: Session, proposal: models.Proposal, *,
    org: Optional[models.Organization] = None,
    actor_id: Optional[str], ip_address: Optional[str],
    body_voting_end: Optional[datetime] = None,
    trigger: str = "manual", now: Optional[datetime] = None,
    allow_cosign: bool = False,
    notifications_suppressed: bool = False,
) -> LifecycleResult:
    if proposal.status != "deliberation":
        raise ValueError("deliberation-to-voting transition requires deliberation status")
    if getattr(proposal, "is_cosign_gated", False) and not allow_cosign:
        raise ValueError("cosign-gated proposals require the cosign window gate")
    when = strip_tz(now) or utcnow_naive()
    if org is None and proposal.org_id:
        org = db.get(models.Organization, proposal.org_id)
    end = compute_voting_end(
        voting_start=when, body_voting_end=body_voting_end,
        proposal=proposal, org=org,
    )
    old_status = proposal.status
    proposal.voting_start = when
    proposal.voting_end = end
    proposal.status = "voting"
    lock_election_candidate_options(db, proposal)
    log_audit_event(
        db, action="proposal.status_changed", target_type="proposal",
        target_id=proposal.id, actor_id=actor_id,
        details={
            "proposal_id": proposal.id, "old_status": old_status,
            "new_status": "voting", "trigger": trigger,
            "scheduled_deliberation_end": (
                proposal.deliberation_end.isoformat()
                if proposal.deliberation_end else None
            ),
            "actual_voting_start": when.isoformat(),
            "delay_seconds": (
                max(0, int((when - proposal.deliberation_end).total_seconds()))
                if proposal.deliberation_end else None
            ),
            "voting_start": when.isoformat(), "voting_end": end.isoformat(),
            "notifications_suppressed": notifications_suppressed,
        },
        ip_address=ip_address,
    )
    return LifecycleResult(
        proposal.id, old_status, "voting", when,
        getattr(proposal, "deliberation_end", None), end, trigger,
        notifications_suppressed,
    )


def refresh_deliberation_window(
    proposal: models.Proposal, org: Optional[models.Organization], *,
    now: Optional[datetime] = None,
) -> datetime:
    """Give an escalation returned to deliberation a fresh full window."""
    when = strip_tz(now) or utcnow_naive()
    proposal.deliberation_start = when
    proposal.deliberation_end = when + timedelta(
        days=effective_deliberation_days(proposal, org),
    )
    return when


def _has_delegation(
    db: Session, proposal: models.Proposal, user_id: str, *, incoming: bool,
) -> bool:
    topic_ids = [row.topic_id for row in proposal.proposal_topics]
    if not topic_ids:
        return False
    column = models.Delegation.delegate_id if incoming else models.Delegation.delegator_id
    query = db.query(models.Delegation.id).filter(
        column == user_id, models.Delegation.topic_id.in_(topic_ids),
    )
    if proposal.org_id is not None:
        query = query.filter(models.Delegation.org_id == proposal.org_id)
    return bool(db.query(query.exists()).scalar())


def _voting_event(db: Session, proposal: models.Proposal, user_id: str) -> Optional[str]:
    candidates: list[str] = []
    if _has_delegation(db, proposal, user_id, incoming=True):
        candidates.append("proposal.entered_voting.delegated_to_you")
    if not _has_delegation(db, proposal, user_id, incoming=False):
        candidates.append("proposal.entered_voting.you_vote")
    candidates.append("proposal.entered_voting")
    return next(
        (name for name in candidates if user_has_any_channel_enabled(db, user_id, name)),
        None,
    )


def emit_status_notifications(
    db: Session, background_tasks: Any, proposal: models.Proposal, *,
    old_status: str, new_status: str, actor_id: Optional[str],
) -> None:
    """Queue lifecycle notifications after the caller's mutation commit."""
    payload = {
        "proposal_id": proposal.id, "proposal_title": proposal.title,
        "org_id": proposal.org_id, "old_status": old_status,
        "new_status": new_status,
    }
    if old_status != "voting" and new_status == "voting":
        for user_id in eligible_voter_ids_for_proposal(db, proposal):
            event = _voting_event(db, proposal, user_id)
            if event:
                emit_notification(
                    db, background_tasks, event_type=event, user_id=user_id,
                    org_id=proposal.org_id, actor_id=actor_id,
                    target_type="proposal", target_id=proposal.id, payload=payload,
                )
    if old_status == "voting" and new_status in {"passed", "failed"}:
        recipients = {proposal.author_id} if proposal.author_id else set()
        recipients.update(
            user_id for (user_id,) in db.query(models.Vote.user_id).filter(
                models.Vote.proposal_id == proposal.id,
            ).all()
        )
        for user_id in recipients:
            emit_notification(
                db, background_tasks, event_type="proposal.closed", user_id=user_id,
                org_id=proposal.org_id, actor_id=actor_id,
                target_type="proposal", target_id=proposal.id,
                payload={**payload, "outcome": new_status},
            )


def emit_transition_notifications(
    db: Session, background_tasks: Any, proposal: models.Proposal,
    result: LifecycleResult, *, actor_id: Optional[str],
) -> bool:
    """Emit one typed transition result, honoring only internal suppression."""
    if result.notifications_suppressed:
        return False
    emit_status_notifications(
        db, background_tasks, proposal, old_status=result.old_status,
        new_status=result.new_status, actor_id=actor_id,
    )
    return True
