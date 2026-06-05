"""Phase 52b — free-pool metering + capacity predicate.

Pure helper module for the verification consumption counter. The
counter is the workspace-level monthly tally of real Didit
verifications against the shared free pool (Didit's 500/month free
tier).

Design points (per the spec + the backlog's locked decisions):

  * **Shared pool, FCFS for v1.** One workspace-level monthly cap
    (``VERIFICATION_FREE_POOL_MONTHLY``); no per-org enforcement.
  * **Per-org recorded, not enforced.** Each consumption row carries
    an optional ``org_id`` (the triggering org, if known) so a future
    sub-allocation policy can be picked from real data. The shared
    total is the SUM across all org_ids for the current
    ``year_month``.
  * **Implicit monthly reset.** Rows are keyed by ``year_month``
    (a YYYY-MM string). A new month → new rows, no cron, no worker.
    Mirrors Didit's calendar-month reset semantics.
  * **demo_stub and backdoor NEVER increment.** Phase 51 forward-
    constraint #2. ``record_consumption`` rejects those provenances.
  * **A blocked verification creates no Didit session** — the
    capacity check fires at the session-creation route BEFORE the
    provider call. ``has_capacity`` is the single predicate; reads
    the same row count both the gate-display and session-create
    sites use.

This module has NO direct DB / HTTP / session-scope wiring — it
takes a SQLAlchemy ``Session`` and a ``year_month`` (defaulting to
"now"), so it tests cleanly with a fixture month-injector.
"""
from __future__ import annotations

import calendar
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

import models


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Workspace-level monthly cap for Didit's free tier. Single source of
# truth — call sites read this constant, never a literal 500.
VERIFICATION_FREE_POOL_MONTHLY: int = 500

# Provenances that count against the pool. demo_stub + backdoor are
# explicitly EXCLUDED (Phase 51 forward-constraint).
COUNTING_PROVENANCES: frozenset[str] = frozenset({"didit"})


# ---------------------------------------------------------------------------
# Time helpers (mock-friendly)
# ---------------------------------------------------------------------------


def current_year_month(now: Optional[datetime] = None) -> str:
    """Return the current ``YYYY-MM`` string. ``now`` defaults to
    ``datetime.now(UTC)``; tests can inject a fixed point."""
    n = now or datetime.now(timezone.utc)
    return f"{n.year:04d}-{n.month:02d}"


def next_reset_iso_date(now: Optional[datetime] = None) -> str:
    """Return the ISO date (``YYYY-MM-DD``) when the next free-pool
    reset will happen — i.e., the first of next month. Used by the
    empty-pool message so users see the real reset date."""
    n = now or datetime.now(timezone.utc)
    year, month = n.year, n.month
    if month == 12:
        year += 1
        month = 1
    else:
        month += 1
    return f"{year:04d}-{month:02d}-01"


def days_until_reset(now: Optional[datetime] = None) -> int:
    """Number of whole days until the next reset. ``0`` if today IS
    the first of a month; the next reset is the 1st of the FOLLOWING
    month."""
    n = now or datetime.now(timezone.utc)
    _, last_day = calendar.monthrange(n.year, n.month)
    return max(0, last_day - n.day + 1)


# ---------------------------------------------------------------------------
# Read predicates
# ---------------------------------------------------------------------------


def current_month_consumption(
    db: Session,
    *,
    year_month: Optional[str] = None,
) -> int:
    """Total verifications recorded this month (shared, all orgs)."""
    ym = year_month or current_year_month()
    row = db.execute(
        select(func.count(models.VerificationConsumption.id)).where(
            models.VerificationConsumption.year_month == ym,
        ),
    ).scalar()
    return int(row or 0)


def remaining_capacity(
    db: Session,
    *,
    year_month: Optional[str] = None,
) -> int:
    """How many verifications the shared pool can still serve this
    month. Never negative; floors at 0."""
    used = current_month_consumption(db, year_month=year_month)
    return max(0, VERIFICATION_FREE_POOL_MONTHLY - used)


def has_capacity(
    db: Session,
    *,
    year_month: Optional[str] = None,
) -> bool:
    """The single capacity predicate read by both gate-display and
    session-create. Below the cap → True; at-or-above → False."""
    return remaining_capacity(db, year_month=year_month) > 0


def capacity_status(
    db: Session,
    *,
    now: Optional[datetime] = None,
) -> dict:
    """Bundled status for the FE empty-pool message + the admin
    visibility surface. Pure read; no side effects."""
    ym = current_year_month(now)
    used = current_month_consumption(db, year_month=ym)
    cap = VERIFICATION_FREE_POOL_MONTHLY
    return {
        "year_month": ym,
        "cap": cap,
        "used": used,
        "remaining": max(0, cap - used),
        "has_capacity": used < cap,
        "reset_date": next_reset_iso_date(now),
        "days_until_reset": days_until_reset(now),
    }


# ---------------------------------------------------------------------------
# Per-org breakdown (B4 admin visibility)
# ---------------------------------------------------------------------------


def per_org_breakdown(
    db: Session,
    *,
    year_month: Optional[str] = None,
) -> list[dict]:
    """Per-org consumption rows for the given month, sorted by count
    descending. ``org_id=None`` (verifications without a triggering
    org) appears as one bucket. Used by the admin visibility
    endpoint (B4)."""
    ym = year_month or current_year_month()
    rows = db.execute(
        select(
            models.VerificationConsumption.org_id,
            func.count(models.VerificationConsumption.id).label("count"),
        ).where(
            models.VerificationConsumption.year_month == ym,
        ).group_by(
            models.VerificationConsumption.org_id,
        ),
    ).all()
    org_id_to_name: dict[Optional[str], Optional[str]] = {}
    org_ids = [r.org_id for r in rows if r.org_id is not None]
    if org_ids:
        for o in db.execute(
            select(models.Organization.id, models.Organization.name).where(
                models.Organization.id.in_(org_ids),
            ),
        ).all():
            org_id_to_name[o.id] = o.name
    out = [
        {
            "org_id": r.org_id,
            "org_name": org_id_to_name.get(r.org_id),
            "count": int(r.count),
        }
        for r in rows
    ]
    out.sort(key=lambda r: r["count"], reverse=True)
    return out


# ---------------------------------------------------------------------------
# Increment (write side)
# ---------------------------------------------------------------------------


def record_consumption(
    db: Session,
    *,
    user_id: str,
    provenance: str,
    provider_session_id: Optional[str] = None,
    org_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Optional[models.VerificationConsumption]:
    """Record a single real Didit verification against the pool.

    Returns the new row, or ``None`` if the provenance is not on the
    counting allow-list (``demo_stub`` / ``backdoor`` → no-op, no
    row).

    Idempotency: callers SHOULD only invoke this once per real
    completion (the receiver dedupes replays via the bookkeeping
    row's status check, so this never runs twice for the same
    webhook). For belt-and-suspenders, the receiver passes the
    ``provider_session_id`` so an accidental double-call is visible
    in the audit query (you can look for two rows with the same
    provider_session_id).
    """
    if provenance not in COUNTING_PROVENANCES:
        return None
    ym = current_year_month(now)
    row = models.VerificationConsumption(
        year_month=ym,
        org_id=org_id,
        user_id=user_id,
        provider_session_id=provider_session_id,
        provenance=provenance,
    )
    db.add(row)
    # Don't commit here — the caller is the webhook receiver, which
    # commits the whole state-write + audit together. Letting the
    # consumption row ride that same commit keeps the "verification
    # written + pool incremented" pair atomic.
    return row
