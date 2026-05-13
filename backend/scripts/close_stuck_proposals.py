"""Phase 24 — backfill: close proposals stuck past voting_end.

The pre-Phase-24 codebase had no scheduled time-based close path for
non-SRR proposals — the worker only closed proposals via the
sliding-window-stable branch inside an SRR extension. Real-org proposals
whose authors set a ``voting_end`` and walked away accumulated in
``status='voting'`` indefinitely. This script closes those leftovers
in one pass.

Selection criteria:
  - ``status = 'voting'``
  - ``voting_end IS NOT NULL`` AND ``voting_end < NOW() - INTERVAL '24h'``
    The 24h grace period prevents an accidental close of a proposal that
    just hit its deadline between the deploy and this script — those will
    be picked up by the next worker tick with normal notifications.
  - org is not ``is_demo=True`` (those are wiped by the daily reset job).
    Legacy ``is_demo=False`` "demo" org IS included if it has stuck
    proposals (Z's decision per the dispatch).

For each match:
  - Close via ``_close_proposal_now`` with ``trigger="voting_end_backfill"``
    and ``update_voting_end=False`` (preserve original deadline).
  - No notification is emitted — these proposals are 11-21 days past
    deadline; notifying users that an old vote "just closed" is noise.

Invocation (from ``backend/`` with venv active):

    .venv/Scripts/python.exe scripts/close_stuck_proposals.py --dry-run
    .venv/Scripts/python.exe scripts/close_stuck_proposals.py

``--dry-run`` prints the list of matches and exits without mutating.

Output is one line per closed proposal plus a final summary tally.

Idempotent — safe to re-run; the second run finds no matches because the
first closed everything.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

# Ensure ``backend/`` is on sys.path so the imports resolve regardless of
# whether the script is run as a module or directly.
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import models  # noqa: E402
from database import SessionLocal  # noqa: E402
from sustained_majority_worker import (  # noqa: E402
    _close_proposal_now,
    TRIGGER_VOTING_END_BACKFILL,
)


GRACE_HOURS: int = 24


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def find_stuck_proposals(db, *, grace_hours: int = GRACE_HOURS):
    """Return the list of (proposal, org_slug, org_name) tuples to close."""
    cutoff = _now_naive() - timedelta(hours=grace_hours)
    rows = (
        db.query(models.Proposal, models.Organization)
        .join(models.Organization, models.Proposal.org_id == models.Organization.id)
        .filter(
            models.Proposal.status == "voting",
            models.Proposal.voting_end.isnot(None),
            models.Proposal.voting_end < cutoff,
            # Exclude is_demo=True orgs (auto-reset). Legacy
            # is_demo=False "demo" org IS included per dispatch
            # decision — those proposals also need closure.
            (models.Organization.is_demo.is_(None) | (models.Organization.is_demo == False)),  # noqa: E712
        )
        .order_by(models.Proposal.voting_end.asc())
        .all()
    )
    return rows


def close_one(db, proposal: models.Proposal) -> str:
    """Close a single proposal via the worker's helper. Returns the new
    status. Caller commits."""
    return _close_proposal_now(
        db, proposal,
        trigger=TRIGGER_VOTING_END_BACKFILL,
        update_voting_end=False,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Backfill: close proposals stuck past voting_end.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would close without mutating the database.",
    )
    parser.add_argument(
        "--grace-hours", type=int, default=GRACE_HOURS,
        help=f"Minimum hours past voting_end before close (default {GRACE_HOURS}).",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        matches = find_stuck_proposals(db, grace_hours=args.grace_hours)
        print(
            f"Found {len(matches)} proposal(s) stuck past voting_end "
            f"(grace={args.grace_hours}h, dry_run={args.dry_run})"
        )
        if not matches:
            print("Nothing to close.")
            return 0

        closed_by_status: dict[str, int] = {}
        rows_for_summary: list[tuple[str, str, str, str]] = []

        for proposal, org in matches:
            if args.dry_run:
                print(
                    f"  [dry-run] {org.slug!r}: '{proposal.title}' "
                    f"(method={proposal.voting_method}, "
                    f"voting_end={proposal.voting_end.isoformat()})"
                )
                continue
            try:
                new_status = close_one(db, proposal)
                db.commit()
                closed_by_status[new_status] = closed_by_status.get(new_status, 0) + 1
                rows_for_summary.append((org.slug, proposal.title, new_status, proposal.voting_method))
                print(
                    f"  CLOSED {org.slug!r}: '{proposal.title}' -> {new_status} "
                    f"(method={proposal.voting_method})"
                )
            except Exception as e:  # noqa: BLE001
                db.rollback()
                print(
                    f"  ERROR closing {org.slug!r} '{proposal.title}': "
                    f"{type(e).__name__}: {e}"
                )

        if args.dry_run:
            print(f"\nDry-run complete. {len(matches)} proposal(s) would close.")
        else:
            total = sum(closed_by_status.values())
            breakdown = ", ".join(
                f"{s}={n}" for s, n in sorted(closed_by_status.items())
            )
            print(f"\nDone. Closed {total} proposal(s): {breakdown}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
