"""Phase 23 (B2 + B4) — demo reset job.

Top-level orchestrator. Called from:
- The Phase 13 digest scheduler tick (``digest_scheduler.run_one_tick``):
  ``run_demo_reset_if_due(db, force=False)``. The schedule check
  short-circuits when not yet due, so the per-tick cost is one
  PlatformSetting / audit-log read.
- The manual-trigger admin endpoint (``POST /api/admin/demo/reset``):
  ``run_demo_reset_if_due(db, force=True, actor_id=admin.id)``.

Sequencing per D2/D3/D7/D10/D19/D20:

1. Compute next-due moment (skip if not due unless ``force=True``).
2. Acquire reset lock (UPDATE ``is_demo_resetting=True`` for is_demo orgs).
3. Wipe phase — explicit deletes for content scoped to each demo org.
   Cascade-aware, no notifications referencing wiped proposals left orphaned.
4. Seed phase — call ``seed_pipeline.seed_org_from_bible`` per bible.
5. Commit (single transaction; partial failure → rollback).
6. Update ``demo_reset_last_completed_at`` PlatformSetting.
7. Release lock (try/finally).
8. Emit ``demo.reset`` audit log.
9. Return ``DemoResetResult``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

import models
from audit_utils import log_audit_event

log = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================


DEMO_RESET_LAST_COMPLETED_KEY = "demo_reset_last_completed_at"


# Slug → seed-config mapping. The bibles' OrgBible.slug values match these
# keys exactly (Amendment E). Bibles iterated in display_order so seeding
# is deterministic.
def _load_demo_bibles() -> list:
    """Lazy-load the three bibles. Returns ordered list of OrgBible instances."""
    from demo_content.hoa_bible import HOA_BIBLE
    from demo_content.union_bible import LOCAL_4021_BIBLE
    from demo_content.activist_bible_part3 import COALITION_BIBLE
    return [HOA_BIBLE, LOCAL_4021_BIBLE, COALITION_BIBLE]


# =============================================================================
# Result dataclass
# =============================================================================


@dataclass
class DemoResetResult:
    """Returned by ``run_demo_reset_if_due``. Mirrors the manual-trigger
    endpoint's response schema."""
    success: bool
    started_at: datetime
    completed_at: datetime
    orgs_reset: list[str] = field(default_factory=list)
    rows_wiped: int = 0
    rows_seeded: int = 0
    error: Optional[str] = None
    skipped: bool = False  # True when not-due short-circuit fired
    reason: Optional[str] = None  # human-readable explanation for skip


# =============================================================================
# Scheduling helpers
# =============================================================================


def _parse_pacific_time(value: str) -> tuple[int, int]:
    """Parse ``"HH:MM"`` → ``(hour, minute)``. Falls back to ``(0, 0)``."""
    try:
        parts = (value or "00:00").split(":")
        return int(parts[0]), int(parts[1])
    except Exception:
        return (0, 0)


def _pacific_now() -> datetime:
    """Current time in Pacific time (DST-aware via zoneinfo)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Los_Angeles"))
    except Exception:
        # Fallback: assume UTC-8 (PST). Lifecycle is "demo daily reset,"
        # so DST drift of one hour is acceptable degraded behavior.
        return datetime.now(timezone.utc) - timedelta(hours=8)


def _compute_next_due(
    last_completed: Optional[datetime], reset_time: str,
) -> datetime:
    """Return the next pacific-time moment the reset should fire.

    If never completed, returns the current Pacific time (= due now).
    Otherwise returns the next H:M occurrence strictly after
    ``last_completed``.
    """
    hour, minute = _parse_pacific_time(reset_time)
    now_pac = _pacific_now()
    if last_completed is None:
        return now_pac
    # Convert last_completed (assumed UTC-ish or naive) to Pacific.
    try:
        from zoneinfo import ZoneInfo
        if last_completed.tzinfo is None:
            last_completed = last_completed.replace(tzinfo=timezone.utc)
        last_pac = last_completed.astimezone(ZoneInfo("America/Los_Angeles"))
    except Exception:
        last_pac = (last_completed or now_pac) - timedelta(hours=8)

    candidate = last_pac.replace(
        hour=hour, minute=minute, second=0, microsecond=0,
    )
    if candidate <= last_pac:
        candidate = candidate + timedelta(days=1)
    return candidate


def _is_due(
    last_completed: Optional[datetime], reset_time: str,
) -> bool:
    """Return True iff a fresh reset should fire now."""
    next_due = _compute_next_due(last_completed, reset_time)
    return _pacific_now() >= next_due


def _read_last_completed(db: Session) -> Optional[datetime]:
    row = db.get(models.PlatformSetting, DEMO_RESET_LAST_COMPLETED_KEY)
    if row is None or row.value is None:
        return None
    try:
        # Stored as ISO-8601 string in JSON value
        return datetime.fromisoformat(row.value)
    except Exception:
        return None


def _write_last_completed(db: Session, when: datetime) -> None:
    row = db.get(models.PlatformSetting, DEMO_RESET_LAST_COMPLETED_KEY)
    if row is None:
        row = models.PlatformSetting(
            key=DEMO_RESET_LAST_COMPLETED_KEY,
            value=when.isoformat(),
        )
        db.add(row)
    else:
        row.value = when.isoformat()


# =============================================================================
# Wipe step (D3)
# =============================================================================


def _wipe_demo_orgs(db: Session, demo_orgs: list[models.Organization]) -> int:
    """Delete all content scoped to ``demo_orgs``. Returns row count."""
    org_ids = [o.id for o in demo_orgs]
    if not org_ids:
        return 0

    rows_wiped = 0

    # Phase 86 (B-4) — content reports scoped to demo orgs. org_id FK has
    # ON DELETE CASCADE, but the org row itself is NOT deleted on reset (only
    # its content is wiped), so reports must be explicitly removed here or
    # they'd dangle pointing at wiped comments/proposals.
    n_reports = (
        db.query(models.ContentReport)
        .filter(models.ContentReport.org_id.in_(org_ids))
        .delete(synchronize_session=False)
    )
    rows_wiped += n_reports or 0

    # Collect proposal IDs first (used for explicit notification cleanup).
    proposals = (
        db.query(models.Proposal)
        .filter(models.Proposal.org_id.in_(org_ids))
        .all()
    )
    proposal_ids = [p.id for p in proposals]

    # Notifications referencing wiped proposals — no FK cascade.
    if proposal_ids:
        n_notifs = (
            db.query(models.Notification)
            .filter(
                models.Notification.target_type == "proposal",
                models.Notification.target_id.in_(proposal_ids),
            )
            .delete(synchronize_session=False)
        )
        rows_wiped += n_notifs or 0
    # Notifications by org_id (covers non-proposal-targeted notifications).
    n_notifs2 = (
        db.query(models.Notification)
        .filter(models.Notification.org_id.in_(org_ids))
        .delete(synchronize_session=False)
    )
    rows_wiped += n_notifs2 or 0

    # Delegate vote rationales (FK to votes); votes cascade later, but
    # rationales need their own delete first to avoid orphan rows on dialects
    # that don't honor ondelete cascade.
    vote_ids = [
        v.id for v in db.query(models.Vote)
        .filter(models.Vote.proposal_id.in_(proposal_ids))
        .all()
    ] if proposal_ids else []
    if vote_ids:
        n_rationales = (
            db.query(models.DelegateVoteRationale)
            .filter(models.DelegateVoteRationale.vote_id.in_(vote_ids))
            .delete(synchronize_session=False)
        )
        rows_wiped += n_rationales or 0

    # Votes (proposal cascade *should* handle, but explicit is safer)
    if proposal_ids:
        n_votes = (
            db.query(models.Vote)
            .filter(models.Vote.proposal_id.in_(proposal_ids))
            .delete(synchronize_session=False)
        )
        rows_wiped += n_votes or 0

    # Vote snapshots
    if proposal_ids:
        n_snaps = (
            db.query(models.VoteSnapshot)
            .filter(models.VoteSnapshot.proposal_id.in_(proposal_ids))
            .delete(synchronize_session=False)
        )
        rows_wiped += n_snaps or 0

    # Comments
    if proposal_ids:
        n_comments = (
            db.query(models.Comment)
            .filter(models.Comment.proposal_id.in_(proposal_ids))
            .delete(synchronize_session=False)
        )
        rows_wiped += n_comments or 0

    # Phase 23.2 B7: explicit delete of ProposalOption + ProposalTopic
    # BEFORE Proposal. The ORM-level `cascade="all, delete-orphan"` on
    # Proposal.options / Proposal.proposal_topics only fires when the
    # session has the relationship loaded and we call `db.delete(proposal)`
    # per row. The bulk `db.query(Proposal).filter(...).delete()` below
    # bypasses the ORM and runs straight SQL — Postgres then raises a
    # ForeignKeyViolation because proposal_options.proposal_id FKs to
    # proposals.id without ON DELETE CASCADE. Same shape applies to
    # ProposalTopic. Wipe these first to keep the bulk delete safe on PG.
    if proposal_ids:
        n_opts = (
            db.query(models.ProposalOption)
            .filter(models.ProposalOption.proposal_id.in_(proposal_ids))
            .delete(synchronize_session=False)
        )
        rows_wiped += n_opts or 0
        n_ptopics = (
            db.query(models.ProposalTopic)
            .filter(models.ProposalTopic.proposal_id.in_(proposal_ids))
            .delete(synchronize_session=False)
        )
        rows_wiped += n_ptopics or 0
        # Phase 49b — cosign signatures FK to Proposal; wipe before Proposal
        # so the bulk delete is safe on Postgres.
        n_csigs = (
            db.query(models.ProposalCosignature)
            .filter(models.ProposalCosignature.proposal_id.in_(proposal_ids))
            .delete(synchronize_session=False)
        )
        rows_wiped += n_csigs or 0

    # Proposals
    if proposal_ids:
        n_props = (
            db.query(models.Proposal)
            .filter(models.Proposal.id.in_(proposal_ids))
            .delete(synchronize_session=False)
        )
        rows_wiped += n_props or 0

    # Delegations + intents + follow_requests + follow_relationships
    n_del = (
        db.query(models.Delegation)
        .filter(models.Delegation.org_id.in_(org_ids))
        .delete(synchronize_session=False)
    )
    rows_wiped += n_del or 0
    n_intent = (
        db.query(models.DelegationIntent)
        .filter(models.DelegationIntent.org_id.in_(org_ids))
        .delete(synchronize_session=False)
    )
    rows_wiped += n_intent or 0
    n_fr = (
        db.query(models.FollowRequest)
        .filter(models.FollowRequest.org_id.in_(org_ids))
        .delete(synchronize_session=False)
    )
    rows_wiped += n_fr or 0
    n_frel = (
        db.query(models.FollowRelationship)
        .filter(models.FollowRelationship.org_id.in_(org_ids))
        .delete(synchronize_session=False)
    )
    rows_wiped += n_frel or 0

    # DelegateProfile + OrgDelegateProfile
    n_dp = (
        db.query(models.DelegateProfile)
        .filter(models.DelegateProfile.org_id.in_(org_ids))
        .delete(synchronize_session=False)
    )
    rows_wiped += n_dp or 0
    n_odp = (
        db.query(models.OrgDelegateProfile)
        .filter(models.OrgDelegateProfile.org_id.in_(org_ids))
        .delete(synchronize_session=False)
    )
    rows_wiped += n_odp or 0

    # Phase 29 C4: explicit delete of TopicPrecedence BEFORE Topic.
    # Same FK-violation shape as Phase 23.2 B7's ProposalOption/Topic
    # fix — TopicPrecedence.topic_id FKs to topics.id without ON DELETE
    # CASCADE, so the bulk Topic delete below would otherwise FK-fail
    # on PG. Filter via join on Topic.org_id since TopicPrecedence has
    # no org_id of its own.
    org_topic_ids = [
        t.id for t in db.query(models.Topic)
        .filter(models.Topic.org_id.in_(org_ids)).all()
    ]
    if org_topic_ids:
        n_tprec = (
            db.query(models.TopicPrecedence)
            .filter(models.TopicPrecedence.topic_id.in_(org_topic_ids))
            .delete(synchronize_session=False)
        )
        rows_wiped += n_tprec or 0

    # Topics (will cascade ProposalTopic; but those rows are gone already
    # with the proposals).
    n_topics = (
        db.query(models.Topic)
        .filter(models.Topic.org_id.in_(org_ids))
        .delete(synchronize_session=False)
    )
    rows_wiped += n_topics or 0

    # Phase 49b — custom (non-system) Phase 47 titles + their
    # assignments. System titles (Steward, Admin) stay because they're
    # backfilled by Phase 47's migration on org creation and are
    # uneditable/undeletable per spec D6 — wiping them would leave the
    # org without the label layer until a new migration run. Custom
    # titles (e.g. Cedar Hollow's President / Secretary / Treasurer)
    # are bible-seeded each reset so the wipe must clear them first.
    custom_title_ids = [
        t.id for t in db.query(models.OrgTitle).filter(
            models.OrgTitle.org_id.in_(org_ids),
            models.OrgTitle.is_system == False,  # noqa: E712
        ).all()
    ]
    if custom_title_ids:
        n_assigns = (
            db.query(models.OrgTitleAssignment)
            .filter(models.OrgTitleAssignment.title_id.in_(custom_title_ids))
            .delete(synchronize_session=False)
        )
        rows_wiped += n_assigns or 0
        n_titles = (
            db.query(models.OrgTitle)
            .filter(models.OrgTitle.id.in_(custom_title_ids))
            .delete(synchronize_session=False)
        )
        rows_wiped += n_titles or 0

    # Org memberships (this wipes BOTH demo users and real users who joined a
    # demo org). Real User rows themselves are NOT deleted.
    n_memb = (
        db.query(models.OrgMembership)
        .filter(models.OrgMembership.org_id.in_(org_ids))
        .delete(synchronize_session=False)
    )
    rows_wiped += n_memb or 0

    # Phase 34.4 hotfix #1: SubOrgMembership rows are scoped by sub_org_id,
    # not org_id — so the OrgMembership wipe above doesn't touch them. Sub-org
    # Organization rows persist across resets (they're in demo_orgs because
    # is_demo=True), and seed_pipeline.seed_sub_orgs upserts new rows but
    # never deletes stale ones. Without this wipe, a bible change that drops
    # a member from sub_orgs_structured leaves their SubOrgMembership row
    # alive across the reset — the next /api/orgs/{slug}/sub-orgs Decision-7
    # filter check finds the stale active row and incorrectly returns the
    # private sub-org to the dropped user. Surfaced by Phase 34.4 D2 (Linda +
    # Brenda dropped from Cedar Court Condos but still saw it in the
    # switcher post-reset).
    n_sub_memb = (
        db.query(models.SubOrgMembership)
        .filter(models.SubOrgMembership.sub_org_id.in_(org_ids))
        .delete(synchronize_session=False)
    )
    rows_wiped += n_sub_memb or 0

    # Filler User rows — identified by username prefix from filler_generator.
    # We *don't* delete by display_name or membership join; we explicitly
    # delete any User whose username matches our filler convention. Named
    # bible characters (marcus_pham, dana_whitfield, hoa_brenda, etc.) do
    # NOT match this pattern and survive.
    # Filler usernames look like "{first_initial}{lastname}_{NN}" but those
    # would collide with normal usernames — we use a stricter marker by
    # tracking a separate cleanup pattern: any User created by the prior
    # seed pipeline whose `username` looks like `[a-z][a-z]+_\d{2}` AND has
    # email `@demo.example`. Use the email suffix as the load-bearing filter.
    fillers = (
        db.query(models.User)
        .filter(
            models.User.email.like("%@demo.example"),
        )
        .all()
    )
    # Only delete fillers without active memberships in non-demo orgs
    # (named bible characters all have @demo.example emails too — we filter
    # by whether they're referenced as a bible character). Defensive: only
    # delete fillers, never marcus_pham/dana_whitfield/janet_reilly etc.
    KEEP_USERNAMES = _named_bible_usernames()
    deleted_filler_count = 0
    for u in fillers:
        if u.username in KEEP_USERNAMES:
            continue
        # Defensive: skip if this user has memberships in non-demo orgs
        non_demo_mem = (
            db.query(models.OrgMembership)
            .join(models.Organization, models.Organization.id == models.OrgMembership.org_id)
            .filter(
                models.OrgMembership.user_id == u.id,
                models.Organization.is_demo == False,  # noqa: E712
            )
            .count()
        )
        if non_demo_mem > 0:
            continue
        db.delete(u)
        deleted_filler_count += 1
    rows_wiped += deleted_filler_count

    db.flush()
    return rows_wiped


def _named_bible_usernames() -> set[str]:
    """Collect underlying usernames for all named characters (post-cross-org-mapping)."""
    from demo_content.seed_pipeline import CROSS_ORG_USER_MAP
    usernames: set[str] = set()
    try:
        bibles = _load_demo_bibles()
    except Exception:
        return usernames
    for b in bibles:
        for m in b.members:
            usernames.add(CROSS_ORG_USER_MAP.get(m.user_id, m.user_id))
    # Also keep underlying cross-org names (they appear once each)
    for v in CROSS_ORG_USER_MAP.values():
        usernames.add(v)
    return usernames


# =============================================================================
# Lock helpers
# =============================================================================


def _acquire_lock(db: Session) -> list[models.Organization]:
    """Set ``is_demo_resetting=True`` for all demo orgs; return the rows.

    If any demo org has ``is_demo_resetting=True`` already, raise to
    prevent concurrent resets (D20).

    Phase 40 B1 (2026-05-27): switched from Python-side advisory check to
    Postgres row-level lock via ``with_for_update()``. Pre-fix, two
    triggers entering ``_acquire_lock`` concurrently could both pass the
    ``any(...)`` check before either's ``flush`` landed; under READ
    COMMITTED on Postgres the second one likely deadlocked rather than
    failing cleanly. Post-fix, the second trigger blocks on the row lock
    until the first commits or rolls back, then either sees
    ``is_demo_resetting=True`` (and raises cleanly) or proceeds normally.
    SQLite is a no-op for ``with_for_update`` (single-writer anyway).
    """
    demo_orgs = (
        db.query(models.Organization)
        .filter(models.Organization.is_demo == True)  # noqa: E712
        .with_for_update()
        .all()
    )
    if any(o.is_demo_resetting for o in demo_orgs):
        raise RuntimeError("demo reset already in progress")
    for o in demo_orgs:
        o.is_demo_resetting = True
    db.flush()
    return demo_orgs


def _release_lock(db: Session) -> None:
    """Always clear ``is_demo_resetting=True`` on all demo orgs."""
    demo_orgs = (
        db.query(models.Organization)
        .filter(models.Organization.is_demo == True)  # noqa: E712
        .all()
    )
    for o in demo_orgs:
        o.is_demo_resetting = False
    db.flush()


# =============================================================================
# Top-level entry point
# =============================================================================


def run_demo_reset_if_due(
    db: Session,
    *,
    force: bool = False,
    actor_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> DemoResetResult:
    """Run a demo reset if due; per D2/D19 entry point.

    Returns a DemoResetResult with success/skipped/error fields.
    On any error, logs to audit and re-raises if force=True (manual path),
    swallows if force=False (scheduled path).
    """
    from settings import settings as _settings

    started_at = now or datetime.now(timezone.utc).replace(tzinfo=None)
    reset_time = getattr(_settings, "demo_reset_time_pacific", "00:00")

    last_completed = _read_last_completed(db)
    if not force and not _is_due(last_completed, reset_time):
        return DemoResetResult(
            success=True,
            started_at=started_at,
            completed_at=started_at,
            skipped=True,
            reason="not due",
        )

    # Acquire lock (D20). If concurrent reset detected, skip.
    try:
        demo_orgs = _acquire_lock(db)
    except RuntimeError as e:
        return DemoResetResult(
            success=False,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc).replace(tzinfo=None),
            error=str(e),
            skipped=True,
            reason="concurrent reset",
        )

    rows_wiped = 0
    rows_seeded = 0
    orgs_reset: list[str] = []
    error: Optional[str] = None
    success = False

    try:
        # ---- Wipe ----
        rows_wiped = _wipe_demo_orgs(db, demo_orgs)

        # ---- Seed (one bible at a time) ----
        from demo_content.seed_pipeline import seed_org_from_bible, ORG_SEED_CONFIG
        bibles = _load_demo_bibles()
        for bible in bibles:
            cfg = ORG_SEED_CONFIG.get(bible.slug, {})
            counts = seed_org_from_bible(db, bible, cfg, now=started_at)
            orgs_reset.append(bible.slug)
            rows_seeded += sum(counts.values())

        # ---- Commit ----
        completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        _write_last_completed(db, completed_at)
        # Release lock as part of the same transaction so audit log + flag
        # state are consistent.
        _release_lock(db)

        # Audit log (single row per reset).
        log_audit_event(
            db,
            action="demo.reset",
            target_type="platform",
            target_id="demo_reset",
            actor_id=actor_id,
            details={
                "started_at": started_at.isoformat(),
                "completed_at": completed_at.isoformat(),
                "success": True,
                "orgs_reset": orgs_reset,
                "rows_wiped": rows_wiped,
                "rows_seeded": rows_seeded,
            },
        )
        db.commit()
        success = True

        # Phase 23.1 B3b: refresh the in-memory delegation graph store so
        # cycle detection + neighborhood queries see the freshly-seeded
        # delegations. rebuild_from_db rebuilds across ALL orgs; we call
        # it once here after the cross-org wipe-then-seed commit (not
        # per-org inside seed_pipeline.seed_org_from_bible). Failures
        # are logged but non-fatal — the next process boot also calls
        # rebuild_from_db during startup.
        try:
            from delegation_engine import graph_store
            graph_store.rebuild_from_db(db)
            log.info("Graph store refreshed after demo reset")
        except Exception:
            log.exception("Failed to refresh graph store after demo reset")

        return DemoResetResult(
            success=True,
            started_at=started_at,
            completed_at=completed_at,
            orgs_reset=orgs_reset,
            rows_wiped=rows_wiped,
            rows_seeded=rows_seeded,
        )
    except Exception as exc:  # noqa: BLE001
        error = repr(exc)
        log.exception("demo_reset_job: reset failed; rolling back")
        try:
            db.rollback()
        except Exception:
            pass
        # Release lock in a separate transaction (rollback discarded the
        # is_demo_resetting=True flips above).
        try:
            _release_lock(db)
            log_audit_event(
                db,
                action="demo.reset",
                target_type="platform",
                target_id="demo_reset",
                actor_id=actor_id,
                details={
                    "started_at": started_at.isoformat(),
                    "completed_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
                    "success": False,
                    "orgs_reset": orgs_reset,
                    "rows_wiped": rows_wiped,
                    "rows_seeded": rows_seeded,
                    "error": error,
                },
            )
            db.commit()
        except Exception:
            log.exception("demo_reset_job: failed to release lock + audit on rollback path")
            try:
                db.rollback()
            except Exception:
                pass
        return DemoResetResult(
            success=False,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc).replace(tzinfo=None),
            orgs_reset=orgs_reset,
            rows_wiped=rows_wiped,
            rows_seeded=rows_seeded,
            error=error,
        )


__all__ = [
    "DemoResetResult",
    "run_demo_reset_if_due",
    "DEMO_RESET_LAST_COMPLETED_KEY",
]
