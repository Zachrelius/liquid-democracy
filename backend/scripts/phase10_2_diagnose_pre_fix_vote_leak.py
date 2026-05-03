"""Phase 10.2 W-DIAG — pre-fix vote leak diagnostic (read-only).

Phase 10.1 fixed three places where ineligible votes could enter the
system (``compute_tally``'s else branch, ``get_vote_graph``'s
``all_users``, and ``cast_vote``'s missing eligibility check). The fix
prevents NEW ineligible votes from being recorded; it says nothing about
historical rows that landed BEFORE the fix shipped. Z's wife's
miscounted ballot is the one we know about. There may be others —
possibly many, going back to whenever the leak first opened.

This script answers: how many ``Vote`` rows currently in the DB have a
``user_id`` for a user who is NOT eligible to vote on the corresponding
``proposal_id`` per the current ``eligible_voter_ids_for_proposal``
definition? It produces a per-org / per-proposal / per-user breakdown
plus oldest/newest leaked-vote timestamps.

The script is **read-only**. It does NOT modify, delete, or insert any
rows. It is safe to re-run; output is deterministic against the same
DB state.

Defensive branches (per spec lines 153-158):

  - **Orphan votes** — proposal or user no longer exists in the DB
    (FK should prevent this in PG, but SQLite may have laxer behavior;
    counted separately and excluded from the leak count).
  - **Suspect-scope votes** — proposal references a sub_org_id or org_id
    whose Organization row no longer exists (the eligibility helper
    returns the empty set, which would cause every vote on the proposal
    to read as "leaked"). Surfaced as a separate category so it isn't
    conflated with real cross-scope leak.
  - All other rows are scanned through the same
    ``eligible_voter_ids_for_proposal`` helper used at runtime; a vote
    is flagged "leaked" when its ``user_id`` is not in the eligible set.

Output is printed to stdout AND written to a timestamped report file in
the script's own directory (``phase10_2_diagnostic_report_<UTC ISO>.txt``)
for archival.

Invocation (from ``backend/`` with the venv active):

    .venv/Scripts/python.exe scripts/phase10_2_diagnose_pre_fix_vote_leak.py

Or from the repo root with the venv:

    backend/.venv/Scripts/python backend/scripts/phase10_2_diagnose_pre_fix_vote_leak.py

Or as a module:

    python -m backend.scripts.phase10_2_diagnose_pre_fix_vote_leak

For the actual prod-DB W-DIAG numbers, Z must run via Railway:

    railway run python backend/scripts/phase10_2_diagnose_pre_fix_vote_leak.py

The script picks up ``DATABASE_URL`` from the environment via the
existing ``database.py`` / ``settings.py`` Pydantic pattern.
"""
from __future__ import annotations

import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

# Ensure ``backend/`` is on sys.path so the imports resolve regardless of
# whether the script is run as a module or directly. Mirrors the pattern
# in the other backend/scripts/ files.
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from sqlalchemy.orm import Session  # noqa: E402

import models  # noqa: E402
from database import SessionLocal  # noqa: E402
from delegation_engine import eligible_voter_ids_for_proposal  # noqa: E402


# ---------------------------------------------------------------------------
# Categorisation result containers
# ---------------------------------------------------------------------------


@dataclass
class LeakedVoteRecord:
    """A single Vote row whose user is NOT in the proposal's eligible set."""

    vote_id: str
    proposal_id: str
    proposal_title: str
    user_id: str
    username: str
    display_name: str
    org_id: Optional[str]
    org_slug: str
    sub_org_id: Optional[str]
    sub_org_slug: Optional[str]
    cast_at: datetime


@dataclass
class OrphanVoteRecord:
    """Vote whose proposal or user row is missing."""

    vote_id: str
    proposal_id: str
    user_id: str
    missing: str  # "proposal", "user", or "both"
    cast_at: datetime


@dataclass
class SuspectScopeVoteRecord:
    """Vote whose proposal references a missing org or sub-org.

    Eligibility helper returns the empty set in this case, which would
    otherwise inflate the "leaked" count with rows that are really
    casualties of an org/sub-org delete rather than the cross-scope
    leak we are trying to measure.
    """

    vote_id: str
    proposal_id: str
    proposal_title: str
    user_id: str
    username: str
    missing_scope: str  # "org" or "sub_org"
    missing_id: str
    cast_at: datetime


@dataclass
class DiagnosticResult:
    total_votes_scanned: int = 0
    leaked: list[LeakedVoteRecord] = field(default_factory=list)
    orphan: list[OrphanVoteRecord] = field(default_factory=list)
    suspect_scope: list[SuspectScopeVoteRecord] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core scan
# ---------------------------------------------------------------------------


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _filename_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def scan(db: Session) -> DiagnosticResult:
    """Iterate every Vote row and categorise it. Returns a DiagnosticResult.

    Read-only: this function performs only ``db.query(...)`` calls plus
    in-memory bookkeeping. It does not call ``db.add``, ``db.flush``,
    ``db.delete``, ``db.commit``, or any other mutating method.
    """
    result = DiagnosticResult()

    # Per-proposal cache for the eligibility set so a proposal with N
    # votes triggers one helper call rather than N. Cache spans the
    # whole scan; safe because we never mutate any input.
    eligible_cache: dict[str, set[str]] = {}
    proposal_cache: dict[str, Optional[models.Proposal]] = {}
    user_cache: dict[str, Optional[models.User]] = {}
    org_cache: dict[str, Optional[models.Organization]] = {}

    def _get_proposal(pid: str) -> Optional[models.Proposal]:
        if pid not in proposal_cache:
            proposal_cache[pid] = db.get(models.Proposal, pid)
        return proposal_cache[pid]

    def _get_user(uid: str) -> Optional[models.User]:
        if uid not in user_cache:
            user_cache[uid] = db.get(models.User, uid)
        return user_cache[uid]

    def _get_org(oid: Optional[str]) -> Optional[models.Organization]:
        if oid is None:
            return None
        if oid not in org_cache:
            org_cache[oid] = db.get(models.Organization, oid)
        return org_cache[oid]

    votes = db.query(models.Vote).order_by(models.Vote.cast_at.asc()).all()
    result.total_votes_scanned = len(votes)

    for vote in votes:
        proposal = _get_proposal(vote.proposal_id)
        user = _get_user(vote.user_id)

        # Defensive: orphan votes (proposal and/or user row missing).
        if proposal is None or user is None:
            missing_parts = []
            if proposal is None:
                missing_parts.append("proposal")
            if user is None:
                missing_parts.append("user")
            missing = "+".join(missing_parts)
            result.orphan.append(
                OrphanVoteRecord(
                    vote_id=vote.id,
                    proposal_id=vote.proposal_id,
                    user_id=vote.user_id,
                    missing=missing,
                    cast_at=vote.cast_at,
                )
            )
            continue

        # Defensive: proposal references a missing org/sub-org. The
        # eligibility helper returns the empty set in this case, which
        # would otherwise count every vote on the proposal as "leaked"
        # — surface separately.
        sub_org_id = getattr(proposal, "sub_org_id", None)
        org_id = getattr(proposal, "org_id", None)

        missing_scope: Optional[str] = None
        missing_scope_id: Optional[str] = None
        if sub_org_id is not None and _get_org(sub_org_id) is None:
            missing_scope = "sub_org"
            missing_scope_id = sub_org_id
        elif (
            sub_org_id is None
            and org_id is not None
            and _get_org(org_id) is None
        ):
            missing_scope = "org"
            missing_scope_id = org_id

        if missing_scope is not None and missing_scope_id is not None:
            result.suspect_scope.append(
                SuspectScopeVoteRecord(
                    vote_id=vote.id,
                    proposal_id=proposal.id,
                    proposal_title=proposal.title,
                    user_id=vote.user_id,
                    username=user.username,
                    missing_scope=missing_scope,
                    missing_id=missing_scope_id,
                    cast_at=vote.cast_at,
                )
            )
            continue

        # Compute (or reuse cached) eligible voter set for this proposal.
        if proposal.id not in eligible_cache:
            eligible_cache[proposal.id] = eligible_voter_ids_for_proposal(
                db, proposal
            )
        eligible_ids = eligible_cache[proposal.id]

        if vote.user_id in eligible_ids:
            continue  # Eligible — the common case, nothing to record.

        # Leaked: user not in the eligible set.
        scope_org = _get_org(org_id)
        scope_sub_org = _get_org(sub_org_id) if sub_org_id else None
        result.leaked.append(
            LeakedVoteRecord(
                vote_id=vote.id,
                proposal_id=proposal.id,
                proposal_title=proposal.title,
                user_id=vote.user_id,
                username=user.username,
                display_name=user.display_name,
                org_id=org_id,
                org_slug=scope_org.slug if scope_org else "<no-org>",
                sub_org_id=sub_org_id,
                sub_org_slug=scope_sub_org.slug if scope_sub_org else None,
                cast_at=vote.cast_at,
            )
        )

    return result


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _format_timestamp(ts: Optional[datetime]) -> str:
    if ts is None:
        return "<none>"
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def render_report(result: DiagnosticResult, run_timestamp_iso: str) -> str:
    """Render the diagnostic report as a single string (matches spec format)."""
    lines: list[str] = []

    lines.append("Phase 10.2 pre-fix vote leak diagnostic")
    lines.append(f"Run timestamp: {run_timestamp_iso}")
    lines.append("")

    leaked = result.leaked
    affected_users = {r.user_id for r in leaked}
    affected_proposals = {r.proposal_id for r in leaked}

    oldest_leaked = min((r.cast_at for r in leaked), default=None)
    newest_leaked = max((r.cast_at for r in leaked), default=None)

    lines.append(f"Total Vote rows scanned: {result.total_votes_scanned}")
    lines.append(f"Leaked vote rows found: {len(leaked)}")
    lines.append(f"Affected users (distinct): {len(affected_users)}")
    lines.append(f"Affected proposals (distinct): {len(affected_proposals)}")
    lines.append(
        f"Orphan votes (proposal/user deleted): {len(result.orphan)} "
        f"(excluded from leak count)"
    )
    lines.append(
        f"Suspect-scope votes (sub-org or org deleted but proposal lingers): "
        f"{len(result.suspect_scope)} (surfaced separately, not counted as leak)"
    )
    lines.append(f"Oldest leaked vote: {_format_timestamp(oldest_leaked)}")
    lines.append(f"Newest leaked vote: {_format_timestamp(newest_leaked)}")
    lines.append("")

    # ---- Per-org breakdown -----------------------------------------
    lines.append("Per-org breakdown:")
    if not leaked:
        lines.append("  (no leaked votes)")
    else:
        # Group leaked records by org_slug.
        by_org: dict[str, list[LeakedVoteRecord]] = defaultdict(list)
        for r in leaked:
            by_org[r.org_slug].append(r)
        # Sort by descending leak count for a stable, useful ordering.
        for org_slug in sorted(
            by_org.keys(), key=lambda s: (-len(by_org[s]), s)
        ):
            recs = by_org[org_slug]
            n_proposals = len({r.proposal_id for r in recs})
            n_users = len({r.user_id for r in recs})
            lines.append(
                f"  {org_slug}: {len(recs)} leaked vote"
                f"{'s' if len(recs) != 1 else ''} across "
                f"{n_proposals} proposal{'s' if n_proposals != 1 else ''} "
                f"({n_users} user{'s' if n_users != 1 else ''})"
            )
    lines.append("")

    # ---- Per-proposal breakdown (top 10 by leak count) -------------
    lines.append("Per-proposal breakdown (top 10 by leaked vote count):")
    if not leaked:
        lines.append("  (no leaked votes)")
    else:
        per_prop_counter: Counter[str] = Counter(r.proposal_id for r in leaked)
        prop_meta: dict[str, LeakedVoteRecord] = {}
        for r in leaked:
            prop_meta.setdefault(r.proposal_id, r)
        for proposal_id, count in per_prop_counter.most_common(10):
            meta = prop_meta[proposal_id]
            lines.append(
                f"  proposal_id={proposal_id} title={meta.proposal_title!r} "
                f"org_slug={meta.org_slug} leaked={count}"
            )
    lines.append("")

    # ---- Per-affected-user breakdown -------------------------------
    lines.append("Per-affected-user breakdown:")
    if not leaked:
        lines.append("  (no leaked votes)")
    else:
        per_user_counter: Counter[str] = Counter(r.user_id for r in leaked)
        user_meta: dict[str, LeakedVoteRecord] = {}
        for r in leaked:
            user_meta.setdefault(r.user_id, r)
        # Stable order: descending count, then username for tiebreak.
        for user_id, count in sorted(
            per_user_counter.items(),
            key=lambda kv: (-kv[1], user_meta[kv[0]].username),
        ):
            meta = user_meta[user_id]
            lines.append(
                f"  user_id={user_id} username={meta.username} "
                f"display_name={meta.display_name!r} leaked_count={count}"
            )

    # ---- Suspect-scope detail (if any) -----------------------------
    if result.suspect_scope:
        lines.append("")
        lines.append("Suspect-scope vote detail (proposals with deleted org/sub-org):")
        # Group by (proposal_id, missing_scope, missing_id) for readability.
        by_prop: dict[tuple[str, str, str], list[SuspectScopeVoteRecord]] = (
            defaultdict(list)
        )
        for r in result.suspect_scope:
            by_prop[(r.proposal_id, r.missing_scope, r.missing_id)].append(r)
        for (proposal_id, scope, missing_id), recs in sorted(
            by_prop.items(), key=lambda kv: (-len(kv[1]), kv[0][0])
        ):
            sample = recs[0]
            lines.append(
                f"  proposal_id={proposal_id} title={sample.proposal_title!r} "
                f"missing_{scope}_id={missing_id} affected_votes={len(recs)}"
            )

    # ---- Orphan detail (if any) ------------------------------------
    if result.orphan:
        lines.append("")
        lines.append("Orphan vote detail (proposal or user row missing):")
        # Summarise rather than dump every row; a per-vote line if small.
        if len(result.orphan) <= 25:
            for r in result.orphan:
                lines.append(
                    f"  vote_id={r.vote_id} proposal_id={r.proposal_id} "
                    f"user_id={r.user_id} missing={r.missing} "
                    f"cast_at={_format_timestamp(r.cast_at)}"
                )
        else:
            by_missing: Counter[str] = Counter(r.missing for r in result.orphan)
            for missing, count in by_missing.most_common():
                lines.append(f"  missing={missing}: {count} rows")

    return "\n".join(lines) + "\n"


def write_report_file(report_text: str, filename_ts: str) -> str:
    """Write the report to ``backend/scripts/phase10_2_diagnostic_report_<ts>.txt``.

    Returns the absolute path of the written file. Idempotent for a given
    ``filename_ts``; re-running with the same timestamp would overwrite,
    but in practice we always pass a fresh timestamp per run.
    """
    out_dir = os.path.dirname(os.path.abspath(__file__))
    out_path = os.path.join(
        out_dir, f"phase10_2_diagnostic_report_{filename_ts}.txt"
    )
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report_text)
    return out_path


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    run_ts_iso = _now_utc_iso()
    file_ts = _filename_timestamp()

    db = SessionLocal()
    try:
        result = scan(db)
    finally:
        db.close()

    report = render_report(result, run_ts_iso)
    print(report, end="")

    out_path = write_report_file(report, file_ts)
    print(f"\nReport written to: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
