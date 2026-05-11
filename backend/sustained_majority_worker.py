"""
Stable Result Required background worker (Phase 8 / Phase 20).

A long-running process that wakes every
``SUSTAINED_MAJORITY_CHECK_INTERVAL_SECONDS`` (default 300s; alias
``STABLE_RESULT_CHECK_INTERVAL_SECONDS``), iterates over every proposal that
is in ``voting`` status with Stable Result Required active, captures a
snapshot, and reacts to destabilization:

  - **Original window** (no extensions yet): if any snapshot in the stable
    window (final ``stable_window_fraction`` of the voting period) is
    unstable per the voting method, fire an extension via ``apply_extension``
    (if budget allows) or log ``proposal.destabilization_at_max_extensions``.
  - **Extension window** (>=1 extensions fired): every tick, run a sliding-
    window stability check over the most recent ``stable_window_duration``.
    If stable: close the proposal RIGHT NOW (set voting_end = now). If not
    yet stable: wait for the next tick. If the extension's natural voting_end
    arrives without stability and the budget allows another extension, fire
    one; otherwise log destabilization-at-max-extensions and let close-as-
    usual happen at the next tick.

Each evaluation is one DB transaction:
    snapshot insert + voting_end mutation + audit event
together, or rolled back together.

Deployment:
    Started from ``start.sh`` as a side process. On Railway's single
    Hobby instance, this is fine.

Multi-instance protection:
    If ``SUSTAINED_MAJORITY_WORKER_INSTANCE_ID`` is set in env, the worker
    only runs when this process's ``INSTANCE_ID`` (or ``RAILWAY_REPLICA_ID``)
    matches.

    If ``SUSTAINED_MAJORITY_WORKER_DISABLE=true``, the worker exits
    immediately. Phase 20 also accepts ``STABLE_RESULT_WORKER_INSTANCE_ID``
    and ``STABLE_RESULT_WORKER_DISABLE`` aliases.

Run standalone:
    python -m sustained_majority_worker
or one-shot for tests / local dev:
    python -m sustained_majority_worker --once
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from database import SessionLocal
# Phase 13.2 W-DEPLOY-2 defensive-import pattern: the worker is launched
# as a side-process by start.sh BEFORE uvicorn. If notification_emit's
# transitive imports crash at module load, the worker process dies — which
# by itself is survivable but obscures any downstream signal. Wrapping the
# import here means the worker keeps running even if the emit module is
# broken; notifications silently no-op via the NOTIFICATION_EMIT_AVAILABLE
# guard at each call site. Per phase13_1_notifications_redeploy_spec.md.
try:
    from notification_emit import emit_notification
    NOTIFICATION_EMIT_AVAILABLE = True
except Exception as e:  # noqa: BLE001
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "notification_emit unavailable, stable-result notifications disabled: %s",
        e,
    )
    NOTIFICATION_EMIT_AVAILABLE = False
    emit_notification = None  # type: ignore[assignment]
from settings import settings
from sustained_majority import (
    BinarySnapshotPoint,
    DestabilizationDecision,
    MultiOptionSnapshotPoint,
    StableResultConfig,
    evaluate_extension_stability,
    evaluate_original_window_stability,
    get_stable_result_config,
    is_proposal_stable_result_active,
)
from sustained_majority_service import (
    apply_extension,
    capture_snapshot,
    count_extensions,
    log_destabilization_at_max_extensions,
    reconstruct_original_voting_duration,
    _sum_extension_seconds,
)
import models


# How far back to scan for "recent voters" on the
# proposal.extended_by_stability fan-out. Mirrors the legacy
# floor_approached recipient window (now removed).
EXTENDED_BY_STABILITY_RECENT_VOTER_DAYS: int = 7

log = logging.getLogger("sustained_majority_worker")


# ---------------------------------------------------------------------------
# Multi-instance guard
# ---------------------------------------------------------------------------

def should_run_on_this_instance() -> bool:
    """Apply env-var multi-instance guard. True = this instance does the work."""
    if settings.sustained_majority_worker_disable:
        log.info("Worker disabled via SUSTAINED_MAJORITY_WORKER_DISABLE")
        return False

    expected = settings.sustained_majority_worker_instance_id.strip()
    if not expected:
        return True  # unconditional run

    actual = (
        os.environ.get("INSTANCE_ID")
        or os.environ.get("RAILWAY_REPLICA_ID")
        or ""
    ).strip()
    if expected == actual:
        log.info(f"Worker active (instance_id={actual!r} matches)")
        return True
    log.info(
        f"Worker idle on this instance "
        f"(expected_instance_id={expected!r}, actual={actual!r})"
    )
    return False


# ---------------------------------------------------------------------------
# Single-tick evaluation
# ---------------------------------------------------------------------------

def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _snapshot_points_for(
    db: Session,
    proposal: models.Proposal,
) -> list:
    """Read all VoteSnapshot rows for a proposal and lift them into pure-module
    types. For binary, returns ``BinarySnapshotPoint[]``. For multi-option,
    returns ``MultiOptionSnapshotPoint[]``. Newest last.
    """
    rows = (
        db.query(models.VoteSnapshot)
        .filter(models.VoteSnapshot.proposal_id == proposal.id)
        .order_by(models.VoteSnapshot.simulated_time.asc())
        .all()
    )
    points = []
    if proposal.voting_method == "binary":
        for r in rows:
            points.append(BinarySnapshotPoint(
                simulated_time=r.simulated_time,
                yes=r.yes_count,
                no=r.no_count,
                abstain=r.abstain_count,
                total_eligible=r.total_eligible,
            ))
    else:
        for r in rows:
            payload = r.multi_option_winners or {}
            winners = tuple(payload.get("winners", []) or [])
            total_cast = int(payload.get("total_ballots_cast", 0) or 0)
            points.append(MultiOptionSnapshotPoint(
                simulated_time=r.simulated_time,
                winners=winners,
                total_ballots_cast=total_cast,
                total_eligible=r.total_eligible,
            ))
    return points


def _emit_extended_by_stability(
    db: Session,
    proposal: models.Proposal,
    *,
    new_voting_end: datetime,
    decision: DestabilizationDecision,
) -> None:
    """Phase 20 — emit ``proposal.extended_by_stability`` notification.

    Audience: proposal author + recent voters (last 7 days). Defensive guard
    via NOTIFICATION_EMIT_AVAILABLE per Phase 13.2 W-DEPLOY-2 pattern.
    Always wrapped in try/except — a notification failure must not break
    the worker tick (extension application is the load-bearing piece, and
    has already been committed at this point).
    """
    if not NOTIFICATION_EMIT_AVAILABLE:
        return
    try:
        recipients: set[str] = set()
        if proposal.author_id:
            recipients.add(proposal.author_id)
        voter_cutoff = _now_naive() - timedelta(
            days=EXTENDED_BY_STABILITY_RECENT_VOTER_DAYS,
        )
        recent_votes = (
            db.query(models.Vote.user_id)
            .filter(
                models.Vote.proposal_id == proposal.id,
                models.Vote.cast_at >= voter_cutoff,
            )
            .all()
        )
        for r in recent_votes:
            recipients.add(r.user_id)

        bt = BackgroundTasks()
        for uid in recipients:
            emit_notification(
                db,
                bt,
                event_type="proposal.extended_by_stability",
                user_id=uid,
                org_id=proposal.org_id,
                actor_id=None,  # system event
                target_type="proposal",
                target_id=proposal.id,
                payload={
                    "proposal_id": proposal.id,
                    "proposal_title": proposal.title,
                    "org_id": proposal.org_id,
                    "new_voting_end": new_voting_end.isoformat(),
                    "reason": decision.reason,
                },
            )
    except Exception as e:  # noqa: BLE001 — never break the worker
        log.warning(
            "extended_by_stability emit failed for proposal %s: %s: %s",
            proposal.id, type(e).__name__, e,
        )


def _emit_proposal_closed_for_stability(
    db: Session,
    proposal: models.Proposal,
    *,
    old_status: str,
    new_status: str,
) -> None:
    """Emit ``proposal.closed`` with ``trigger: stable_result_achieved`` when
    the worker closes a proposal early because sliding-window stability
    succeeded during an extension."""
    if not NOTIFICATION_EMIT_AVAILABLE:
        return
    try:
        recipients: set[str] = set()
        if proposal.author_id:
            recipients.add(proposal.author_id)
        vote_rows = (
            db.query(models.Vote.user_id)
            .filter(models.Vote.proposal_id == proposal.id)
            .all()
        )
        for r in vote_rows:
            recipients.add(r.user_id)
        bt = BackgroundTasks()
        for uid in recipients:
            emit_notification(
                db,
                bt,
                event_type="proposal.closed",
                user_id=uid,
                org_id=proposal.org_id,
                actor_id=None,
                target_type="proposal",
                target_id=proposal.id,
                payload={
                    "proposal_id": proposal.id,
                    "proposal_title": proposal.title,
                    "org_id": proposal.org_id,
                    "old_status": old_status,
                    "new_status": new_status,
                    "outcome": new_status,
                    "trigger": "stable_result_achieved",
                },
            )
    except Exception as e:  # noqa: BLE001
        log.warning(
            "proposal.closed (stable_result_achieved) emit failed for %s: %s: %s",
            proposal.id, type(e).__name__, e,
        )


def _close_proposal_now(
    db: Session,
    proposal: models.Proposal,
) -> str:
    """Close the proposal in-place when the sliding-window stability check
    succeeds during an extension. Per spec §B3 "Extension branch":

      - Set ``voting_end = now``.
      - Compute the tally and apply the standard pass/fail logic.
      - Log a ``proposal.status_changed`` audit event.

    Returns the resulting status. Mirrors the close branch in
    ``routes.organizations.advance_proposal`` and ``routes.proposals``.
    Caller commits.
    """
    from delegation_engine import (
        engine as delegation_engine,
        ApprovalTally,
        RCVTally,
    )
    from audit_utils import log_audit_event

    proposal.voting_end = _now_naive()

    old_status = proposal.status
    tally = delegation_engine.compute_tally(proposal, db)

    if proposal.voting_method == "approval":
        if (
            isinstance(tally, ApprovalTally)
            and tally.quorum_met(proposal.quorum_threshold)
            and tally.winners
        ):
            try:
                from routes.proposals import _maybe_resolve_tie
                _maybe_resolve_tie(
                    proposal, tally, "approval", db, current_user_id=None,
                )
            except Exception as e:  # noqa: BLE001
                log.warning("tie-resolution helper failed: %s", e)
            new_status = "passed"
        else:
            new_status = "failed"
    elif proposal.voting_method == "ranked_choice":
        if (
            isinstance(tally, RCVTally)
            and tally.quorum_met(proposal.quorum_threshold)
            and tally.winners
        ):
            try:
                from routes.proposals import _maybe_resolve_tie
                _maybe_resolve_tie(
                    proposal, tally, "ranked_choice", db,
                    current_user_id=None,
                )
            except Exception as e:  # noqa: BLE001
                log.warning("tie-resolution helper failed: %s", e)
            new_status = "passed"
        else:
            new_status = "failed"
    else:
        if (
            tally.threshold_met(proposal.pass_threshold)
            and tally.quorum_met(proposal.quorum_threshold)
        ):
            new_status = "passed"
        else:
            new_status = "failed"

    proposal.status = new_status
    db.flush()

    log_audit_event(
        db,
        action="proposal.status_changed",
        target_type="proposal",
        target_id=proposal.id,
        actor_id=None,  # system actor
        details={
            "proposal_id": proposal.id,
            "old_status": old_status,
            "new_status": new_status,
            "trigger": "stable_result_achieved",
        },
    )
    return new_status


def evaluate_proposal(
    db: Session,
    proposal: models.Proposal,
) -> Optional[str]:
    """One proposal's evaluation tick.

    Captures a fresh snapshot, then branches:

      - If ``extension_count == 0``: original-window check via
        ``evaluate_original_window_stability``.
      - Else: extension branch — sliding-window check via
        ``evaluate_extension_stability``; close early on success; check
        budget for another extension on natural-voting-end-reached.

    Returns a human-readable action string ("extended", "closed_early",
    "destabilized_at_max", or None) or None if no action.

    Caller commits. Errors propagate so the outer loop can roll back.
    """
    if proposal.org_id is None:
        return None  # global proposals don't have org config; skip
    org = db.get(models.Organization, proposal.org_id)
    if org is None:
        return None

    config = get_stable_result_config(org)
    active = is_proposal_stable_result_active(
        proposal.stable_result_required, config.enabled_default,
    )
    if not active:
        return None

    # 1. Take a fresh snapshot.
    capture_snapshot(db, proposal)
    db.flush()

    # 2. Read all snapshots (newest last).
    snapshots = _snapshot_points_for(db, proposal)
    if not snapshots:
        return None

    # 3. Reconstruct the original voting duration (= current span minus all
    # past extensions). Needed for budget calcs and stable-window-duration.
    original_duration = reconstruct_original_voting_duration(db, proposal)
    if original_duration is None or original_duration.total_seconds() <= 0:
        return None

    stable_window_duration = original_duration * config.stable_window_fraction
    extension_budget_total_seconds = int(
        original_duration.total_seconds() * config.max_extension_fraction
    )
    extension_budget_used_seconds = _sum_extension_seconds(db, proposal.id)

    extension_count = count_extensions(db, proposal.id)
    pass_threshold = float(proposal.pass_threshold or 0.5)
    now = _now_naive()

    if extension_count == 0:
        # Original-window branch.
        original_voting_end = proposal.voting_start + original_duration
        decision = evaluate_original_window_stability(
            voting_method=proposal.voting_method,
            snapshots=snapshots,
            pass_threshold=pass_threshold,
            voting_start=proposal.voting_start,
            voting_end=original_voting_end,
            now=now,
            stable_window_fraction=config.stable_window_fraction,
        )
        if not decision.destabilized:
            return None
        return _react_to_destabilization(
            db, proposal,
            decision=decision,
            stable_window_duration=stable_window_duration,
            extension_budget_total_seconds=extension_budget_total_seconds,
            extension_budget_used_seconds=extension_budget_used_seconds,
        )

    # Extension branch.
    is_stable = evaluate_extension_stability(
        voting_method=proposal.voting_method,
        snapshots=snapshots,
        pass_threshold=pass_threshold,
        now=now,
        stable_window_duration=stable_window_duration,
    )
    if is_stable:
        old_status = proposal.status
        new_status = _close_proposal_now(db, proposal)
        _emit_proposal_closed_for_stability(
            db, proposal, old_status=old_status, new_status=new_status,
        )
        return "closed_early"

    # Not yet stable. Check whether the extension's natural voting_end has
    # been reached.
    if proposal.voting_end is None or now < proposal.voting_end:
        return None  # wait for next tick

    # voting_end reached without stability — try another extension if the
    # budget allows.
    decision = DestabilizationDecision(
        destabilized=True,
        reason=(
            f"Extension window reached voting_end without "
            f"sliding-window stability"
        ),
        breach_sample={
            "extension_count_pre": extension_count,
            "voting_end": proposal.voting_end.isoformat(),
        },
    )
    return _react_to_destabilization(
        db, proposal,
        decision=decision,
        stable_window_duration=stable_window_duration,
        extension_budget_total_seconds=extension_budget_total_seconds,
        extension_budget_used_seconds=extension_budget_used_seconds,
    )


def _react_to_destabilization(
    db: Session,
    proposal: models.Proposal,
    *,
    decision: DestabilizationDecision,
    stable_window_duration: timedelta,
    extension_budget_total_seconds: int,
    extension_budget_used_seconds: int,
) -> str:
    """Apply an extension if budget allows; otherwise log destabilization-
    at-max-extensions and let the proposal continue to its natural close.

    Per spec D9 + D11: budget rounds down to whole stable-window-duration
    chunks (no partial extensions). When remaining < stable_window_duration,
    no extension is granted.
    """
    remaining = extension_budget_total_seconds - extension_budget_used_seconds
    swd_seconds = int(stable_window_duration.total_seconds())

    if remaining >= swd_seconds and swd_seconds > 0:
        new_end = apply_extension(
            db, proposal,
            stable_window_duration=stable_window_duration,
            decision=decision,
            actor_id=None,
        )
        _emit_extended_by_stability(
            db, proposal,
            new_voting_end=new_end,
            decision=decision,
        )
        return "extended"

    log_destabilization_at_max_extensions(
        db, proposal,
        decision=decision,
        extension_budget_used_seconds=extension_budget_used_seconds,
        extension_budget_total_seconds=extension_budget_total_seconds,
        actor_id=None,
    )
    return "destabilized_at_max"


def run_one_tick(db: Session) -> int:
    """Iterate every proposal currently in ``voting`` and evaluate each.

    Returns the number of proposals processed. Per-proposal errors are
    caught + logged; the loop keeps going so one bad row doesn't block
    the rest.
    """
    voting_proposals = (
        db.query(models.Proposal)
        .filter(models.Proposal.status == "voting")
        .all()
    )
    processed = 0

    for proposal in voting_proposals:
        try:
            result = evaluate_proposal(db, proposal)
            db.commit()
            processed += 1
            if result is not None:
                log.info(
                    f"stable_result: proposal {proposal.id} -> {result}"
                )
        except Exception:  # noqa: BLE001 — broad on purpose, keep loop alive
            log.exception(
                f"stable_result: error evaluating proposal {proposal.id}; "
                f"rolling back this proposal and continuing"
            )
            db.rollback()
    return processed


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

class _Stop:
    """Bag for SIGINT / SIGTERM flag — kept simple to avoid threading."""
    flag = False


def _install_signal_handlers() -> None:
    def handler(signum, frame):  # noqa: ARG001
        log.info(f"Received signal {signum}; finishing tick and exiting.")
        _Stop.flag = True
    signal.signal(signal.SIGINT, handler)
    try:
        signal.signal(signal.SIGTERM, handler)
    except (AttributeError, ValueError):
        pass


def main(once: bool = False) -> int:
    """Worker entry point. Returns OS exit code."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
    )

    if not should_run_on_this_instance():
        if once:
            return 0
        log.info("Idle on this instance; sleeping forever.")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return 0

    _install_signal_handlers()

    interval = max(10, int(settings.sustained_majority_check_interval_seconds))
    log.info(
        f"Worker starting; check_interval={interval}s, once={once}"
    )

    while not _Stop.flag:
        db = SessionLocal()
        try:
            count = run_one_tick(db)
            log.debug(f"tick processed {count} proposals")
        except Exception:  # noqa: BLE001
            log.exception("Worker tick failed; sleeping and retrying")
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
        finally:
            db.close()

        if once:
            break

        slept = 0
        while slept < interval and not _Stop.flag:
            time.sleep(1)
            slept += 1

    log.info("Worker exited cleanly.")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run the Stable Result Required background worker."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single tick and exit (useful for tests / local dev).",
    )
    args = parser.parse_args()
    sys.exit(main(once=args.once))
