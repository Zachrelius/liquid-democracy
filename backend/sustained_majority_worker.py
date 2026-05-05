"""
Sustained-Majority background worker (Phase 8).

A long-running process that wakes every
`SUSTAINED_MAJORITY_CHECK_INTERVAL_SECONDS` (default 300s), iterates over every
proposal that is in `voting` status with sustained-majority active, captures a
snapshot, and applies the configured failure mode if the floor was breached
(binary) or the winner changed in the stable-result window (multi-option).

Each evaluation is one DB transaction:
    snapshot insert + status mutation + audit log entry
together, or rolled back together. Restart-safe: a proposal that's already
moved to `failed` / `unresolved` is skipped on the next tick, and `extend`
mode counts past `proposal.window_extended` audit events to enforce the
"only-once" guard rail.

Deployment:
    Started from `start.sh` as a side process when `IS_PUBLIC_DEMO` is true
    (or any time the operator wants the worker active). On Railway's single
    Hobby instance, this is fine. For future multi-instance deploys, set
    `SUSTAINED_MAJORITY_WORKER_INSTANCE_ID` to one specific instance's
    `INSTANCE_ID` / `RAILWAY_REPLICA_ID` to gate the worker.

Multi-instance protection:
    If `SUSTAINED_MAJORITY_WORKER_INSTANCE_ID` is set in env, the worker only
    runs when this process's `INSTANCE_ID` (or `RAILWAY_REPLICA_ID`) matches.
    Mismatch = log + sleep forever (process stays up so the supervisor doesn't
    restart-loop, but does no work).

    If `SUSTAINED_MAJORITY_WORKER_DISABLE=true`, the worker exits immediately.

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
# as a side-process by start.sh BEFORE uvicorn (`python -m
# sustained_majority_worker &`). If notification_emit's transitive imports
# crash at module load, the worker process dies — which by itself is
# survivable (the `&` decouples it from start.sh) but obscures any
# downstream signal. Wrapping the import here means the worker keeps
# running even if the emit module is broken; floor-approached
# notifications silently no-op via the NOTIFICATION_EMIT_AVAILABLE guard
# at each call site. Per phase13_1_notifications_redeploy_spec.md.
try:
    from notification_emit import emit_notification
    NOTIFICATION_EMIT_AVAILABLE = True
except Exception as e:  # noqa: BLE001
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "notification_emit unavailable, sustained-majority notifications disabled: %s",
        e,
    )
    NOTIFICATION_EMIT_AVAILABLE = False
    emit_notification = None  # type: ignore[assignment]
from settings import settings
from sustained_majority import (
    BinarySnapshotPoint,
    MultiOptionSnapshotPoint,
    get_sustained_majority_config,
    is_approaching_floor,
    is_proposal_sustained_majority_active,
    should_trigger_failure,
)
from sustained_majority_service import (
    apply_failure_mode,
    capture_snapshot,
    count_extensions,
)
import models


# Phase 13 B7 — dedup window for sustained_majority.floor_approached.
# We don't want to spam recent voters with one notification per worker tick
# while a proposal sits near the floor. Suppress further floor_approached
# notifications for the same proposal within this window.
FLOOR_APPROACHED_DEDUP_HOURS: int = 24

# How far back to scan for "recent voters" on the floor_approached fan-out.
FLOOR_APPROACHED_RECENT_VOTER_DAYS: int = 7

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
    """Read the last few VoteSnapshot rows and lift them into pure-module types.

    For binary, returns BinarySnapshotPoint[]. For multi-option, returns
    MultiOptionSnapshotPoint[] (winners drawn from the JSON column). Newest
    last.
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


def _maybe_emit_floor_approached(
    db: Session,
    proposal: models.Proposal,
    snapshots: list,
    config,
) -> None:
    """Phase 13 B-emit (#7) — emit sustained_majority.floor_approached.

    Idempotency: suppress further notifications for this proposal if any
    floor_approached notification fired within the past
    ``FLOOR_APPROACHED_DEDUP_HOURS``. Audience: the proposal author + all
    users who cast a direct vote within the last
    ``FLOOR_APPROACHED_RECENT_VOTER_DAYS``.

    Always wrapped in try/except — a notification failure must not break
    the worker tick (the failure-mode application is the load-bearing piece).
    """
    try:
        if proposal.voting_method != "binary" or not snapshots:
            return
        latest = snapshots[-1]
        if not isinstance(latest, BinarySnapshotPoint):
            return
        if not is_approaching_floor(latest, config):
            return

        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            hours=FLOOR_APPROACHED_DEDUP_HOURS,
        )
        recent = (
            db.query(models.Notification)
            .filter(
                models.Notification.event_type == "sustained_majority.floor_approached",
                models.Notification.target_type == "proposal",
                models.Notification.target_id == proposal.id,
                models.Notification.created_at >= cutoff,
            )
            .first()
        )
        if recent is not None:
            return  # already emitted in the dedup window; nothing to do.

        # Audience: author + recent voters (last 7 days).
        recipients: set[str] = set()
        if proposal.author_id:
            recipients.add(proposal.author_id)
        voter_cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            days=FLOOR_APPROACHED_RECENT_VOTER_DAYS,
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

        # The emit_notification helper expects a BackgroundTasks for the
        # real-time email path. Worker context isn't a request, so we
        # construct an empty BackgroundTasks; the digest scheduler will
        # pick up email delivery for recipients with email-channel enabled.
        # Phase 13.2 W-DEPLOY-2 defensive guard: skip the emit if the
        # import failed (NOTIFICATION_EMIT_AVAILABLE=False); the worker
        # keeps running and the floor-approached signal silently no-ops.
        if NOTIFICATION_EMIT_AVAILABLE:
            bt = BackgroundTasks()
            for uid in recipients:
                emit_notification(
                    db,
                    bt,
                    event_type="sustained_majority.floor_approached",
                    user_id=uid,
                    org_id=proposal.org_id,
                    actor_id=None,  # system event
                    target_type="proposal",
                    target_id=proposal.id,
                    payload={
                        "proposal_id": proposal.id,
                        "proposal_title": proposal.title,
                        "org_id": proposal.org_id,
                        "support_fraction": float(latest.support_fraction),
                        "floor": float(config.floor),
                    },
                )
    except Exception as e:  # noqa: BLE001 — never break the worker
        log.warning(
            "floor_approached emit failed for proposal %s: %s: %s",
            proposal.id, type(e).__name__, e,
        )


def evaluate_proposal(
    db: Session,
    proposal: models.Proposal,
) -> Optional[str]:
    """One proposal's evaluation tick.

    Captures a fresh snapshot, then runs `should_trigger_failure` against the
    full snapshot history. If it triggers, applies the failure mode in the
    same transaction and returns the resulting status string. Returns None
    when no action was needed.

    Caller commits. Errors propagate so the outer loop can roll back.
    """
    if proposal.org_id is None:
        return None  # global proposals don't have org config; skip
    org = db.get(models.Organization, proposal.org_id)
    if org is None:
        return None

    config = get_sustained_majority_config(org)
    active = is_proposal_sustained_majority_active(
        proposal.sustained_majority_enabled, config.enabled_default,
    )
    if not active:
        return None

    # 1. Take a fresh snapshot. capture_snapshot stores the live tally and the
    # multi-option winners for this tick.
    capture_snapshot(db, proposal)
    db.flush()

    # 2. Read all snapshots (newest last).
    snapshots = _snapshot_points_for(db, proposal)
    if not snapshots:
        return None

    # 3. Decide.
    extension_count = count_extensions(db, proposal.id)
    decision = should_trigger_failure(
        voting_method=proposal.voting_method,
        snapshots=snapshots,
        config=config,
        voting_start=proposal.voting_start,
        voting_end=proposal.voting_end,
        now=_now_naive(),
        extension_count=extension_count,
    )

    if not decision.should_fire:
        # No failure mode triggered — but if support is hovering near the
        # floor, emit the floor_approached warning notification. Idempotent
        # via the 24h dedup window inside the helper.
        _maybe_emit_floor_approached(db, proposal, snapshots, config)
        return None

    # 4. Apply (status mutation + audit event in the same transaction).
    old_status = proposal.status
    new_status = apply_failure_mode(
        db, proposal, decision=decision, actor_id=None,  # system actor
    )

    # 5. Phase 13 B-emit — proposal.closed when the failure-mode flips
    # voting -> failed. Author + everyone who voted (deduped). Wrapped per
    # spec §B3.
    if old_status == "voting" and new_status == "failed" and NOTIFICATION_EMIT_AVAILABLE:
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
                        "trigger": "sustained_majority",
                    },
                )
        except Exception as e:  # noqa: BLE001
            log.warning(
                "proposal.closed emit (sustained_majority) failed for %s: %s: %s",
                proposal.id, type(e).__name__, e,
            )

    return new_status


def run_one_tick(db: Session) -> int:
    """Iterate every proposal currently in `voting` and evaluate each.

    Returns the number of proposals processed (snapshot taken). Per-proposal
    errors are caught + logged; the loop keeps going so one bad row doesn't
    block the rest.
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
                    f"sustained_majority: proposal {proposal.id} "
                    f"-> {result} (mode applied)"
                )
        except Exception:  # noqa: BLE001 — broad on purpose, keep loop alive
            log.exception(
                f"sustained_majority: error evaluating proposal {proposal.id}; "
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
        # SIGTERM unavailable on Windows; SIGINT is enough for local dev.
        pass


def main(once: bool = False) -> int:
    """Worker entry point. Returns OS exit code."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
    )

    if not should_run_on_this_instance():
        # Process stays up but sleeps forever so the supervisor doesn't
        # restart-loop. `once` mode just exits cleanly.
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

        # Sleep in 1-second chunks so SIGINT / SIGTERM exit promptly.
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
        description="Run the sustained-majority background worker."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single tick and exit (useful for tests / local dev).",
    )
    args = parser.parse_args()
    sys.exit(main(once=args.once))
