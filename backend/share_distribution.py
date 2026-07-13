"""share_distribution.py — Phase 90a auto-distribution rules.

Standalone (route-free) so both the CRUD endpoints and the scheduler sweep,
and later the 90d ratification executor, drive the same logic. Anniversary
month arithmetic is pure-Python (``dateutil`` is NOT a dependency, contrary to
the spec's assumption) with calendar day-clamping (Jan 31 + 1 month -> Feb
28/29; Feb 29 + 12 months -> Feb 28 in a non-leap year).
"""
from __future__ import annotations

import calendar
import logging
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

import models

log = logging.getLogger(__name__)

# Bound a pathological catch-up backlog: at most this many periods fire per
# rule (fixed) or per rule+member (anniversary) in one sweep.
CATCHUP_CAP = 12

_VALID_SCHEDULE_MODES = ("fixed_cadence", "anniversary")
_VALID_TARGETING_MODES = ("all_members", "titles_include", "titles_exclude")


def add_months(d: date, n: int) -> date:
    """Add ``n`` months to ``d`` with calendar day-clamping."""
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


def _today() -> date:
    return datetime.now(timezone.utc).date()


# ---------------------------------------------------------------------------
# Share-start-date resolver (not backfill)
# ---------------------------------------------------------------------------

def share_start_date_for(membership: models.OrgMembership) -> date:
    """The member's share anniversary date: the explicit column when set, else
    the membership join date."""
    if getattr(membership, "share_start_date", None):
        return membership.share_start_date
    joined = getattr(membership, "joined_at", None)
    if isinstance(joined, datetime):
        return joined.date()
    return _today()


# ---------------------------------------------------------------------------
# Targeting resolution (fire time)
# ---------------------------------------------------------------------------

def _active_members(db: Session, org_id: str) -> list[models.OrgMembership]:
    return db.query(models.OrgMembership).filter(
        models.OrgMembership.org_id == org_id,
        models.OrgMembership.status == "active",
    ).populate_existing().all()


def _title_holder_ids(db: Session, org_id: str, title_ids: list) -> set:
    """User ids of active members holding any of ``title_ids``. Handles both
    custom titles (assignment rows) and system titles (role-derived). A missing
    / wrong-org title id is inert (contributes no holders)."""
    holders: set = set()
    for tid in title_ids or []:
        title = db.get(models.OrgTitle, tid)
        if title is None or title.org_id != org_id:
            continue
        if getattr(title, "is_system", False) and getattr(title, "bound_role", None):
            rows = db.query(models.OrgMembership).join(
                models.Role, models.OrgMembership.role_id == models.Role.id,
            ).filter(
                models.OrgMembership.org_id == org_id,
                models.OrgMembership.status == "active",
                models.Role.system_key == title.bound_role,
            ).all()
            holders.update(m.user_id for m in rows)
        else:
            rows = db.query(models.OrgTitleAssignment).filter(
                models.OrgTitleAssignment.title_id == tid,
            ).all()
            holders.update(a.user_id for a in rows)
    return holders


def resolve_targeted_members(
    db: Session, org_id: str, rule: models.ShareDistributionRule,
) -> list[models.OrgMembership]:
    """Active members the rule targets, resolved at FIRE time."""
    members = _active_members(db, org_id)
    if rule.targeting_mode == "all_members":
        return members
    holders = _title_holder_ids(db, org_id, rule.title_ids or [])
    if rule.targeting_mode == "titles_include":
        return [m for m in members if m.user_id in holders]
    if rule.targeting_mode == "titles_exclude":
        return [m for m in members if m.user_id not in holders]
    return members


# ---------------------------------------------------------------------------
# Rule create (route-free callable — reused by 90d ratification executor)
# ---------------------------------------------------------------------------

def validate_rule_config(
    *,
    amount: int,
    interval_months: int,
    schedule_mode: str,
    targeting_mode: str,
    title_ids: Optional[list],
) -> None:
    """Raise ShareServiceError on an invalid rule config."""
    from share_service import ShareServiceError

    if not isinstance(amount, int) or isinstance(amount, bool) or amount < 1:
        raise ShareServiceError("amount must be an integer >= 1.")
    if (not isinstance(interval_months, int) or isinstance(interval_months, bool)
            or interval_months < 1):
        raise ShareServiceError("interval_months must be an integer >= 1.")
    if schedule_mode not in _VALID_SCHEDULE_MODES:
        raise ShareServiceError(
            f"schedule_mode must be one of {_VALID_SCHEDULE_MODES}."
        )
    if targeting_mode not in _VALID_TARGETING_MODES:
        raise ShareServiceError(
            f"targeting_mode must be one of {_VALID_TARGETING_MODES}."
        )
    if targeting_mode != "all_members" and not title_ids:
        raise ShareServiceError(
            "title_ids is required for titles_include / titles_exclude."
        )


def create_rule(
    db: Session,
    *,
    org: models.Organization,
    created_by_id: Optional[str],
    amount: int,
    interval_months: int,
    schedule_mode: str,
    targeting_mode: str,
    title_ids: Optional[list] = None,
    anchor_date: Optional[date] = None,
) -> models.ShareDistributionRule:
    """Validate + insert a ShareDistributionRule (caller commits). Title ids
    are validated to belong to the org."""
    from share_service import ShareServiceError

    validate_rule_config(
        amount=amount, interval_months=interval_months,
        schedule_mode=schedule_mode, targeting_mode=targeting_mode,
        title_ids=title_ids,
    )
    tids = list(title_ids or [])
    for tid in tids:
        t = db.get(models.OrgTitle, tid)
        if t is None or t.org_id != org.id:
            raise ShareServiceError(f"title {tid} does not belong to this organization.")
    rule = models.ShareDistributionRule(
        org_id=org.id,
        created_by_id=created_by_id,
        status="active",
        amount=amount,
        interval_months=interval_months,
        schedule_mode=schedule_mode,
        targeting_mode=targeting_mode,
        title_ids=tids if targeting_mode != "all_members" else [],
        anchor_date=(anchor_date if schedule_mode == "fixed_cadence"
                     else None),
    )
    db.add(rule)
    db.flush()
    return rule


# ---------------------------------------------------------------------------
# Execution engine (sweep)
# ---------------------------------------------------------------------------

def _period_exists(db: Session, org_id: str, period_key: str) -> bool:
    return db.query(models.ShareEvent.id).filter(
        models.ShareEvent.org_id == org_id,
        models.ShareEvent.period_key == period_key,
    ).first() is not None


def _grant(
    db: Session,
    *,
    org_id: str,
    membership: models.OrgMembership,
    amount: int,
    rule_id: str,
    period_key: str,
) -> models.ShareEvent:
    """Increment weight + write an auto_distribution ShareEvent (idempotency
    key ``period_key``) in the caller's transaction. Returns the event."""
    new_balance = (membership.voting_weight or 0) + amount
    membership.voting_weight = new_balance
    ev = models.ShareEvent(
        org_id=org_id,
        event_type="auto_distribution",
        user_id=membership.user_id,
        delta=amount,
        resulting_balance=new_balance,
        actor_id=None,
        rule_id=rule_id,
        period_key=period_key,
    )
    db.add(ev)
    db.flush()
    return ev


def _elapsed_k(anchor: date, interval_months: int, today: date) -> int:
    """Largest k >= 0 such that anchor + k*interval_months <= today."""
    k = 0
    while add_months(anchor, (k + 1) * interval_months) <= today:
        k += 1
    return k


def _notify_recipient(db: Session, user_id: str, org: models.Organization,
                      rule: models.ShareDistributionRule, amount: int) -> None:
    """Best-effort in-app shares.received notification (respecting the user's
    in_app preference). No email from the scheduler context."""
    try:
        from notification_emit import _is_channel_enabled
        if not _is_channel_enabled(db, user_id, "shares.received", "in_app"):
            return
        db.add(models.Notification(
            user_id=user_id,
            event_type="shares.received",
            org_id=org.id,
            actor_id=None,
            target_type="organization",
            target_id=org.id,
            payload={
                "org_id": org.id, "org_slug": org.slug, "org_name": org.name,
                "amount": amount, "rule_id": rule.id,
            },
        ))
    except Exception as e:  # noqa: BLE001
        log.debug("shares.received notify failed for %s: %s", user_id, e)


def _notify_cap_blocked(db: Session, org: models.Organization,
                        rule: models.ShareDistributionRule, skipped: int) -> None:
    """Phase 90d — best-effort in-app notification to the rule's creator that
    the sweep skipped grants because they'd breach the authorized cap. Batched:
    one per sweep-per-rule, not per member."""
    if not rule.created_by_id:
        return
    try:
        from notification_emit import _is_channel_enabled
        if not _is_channel_enabled(db, rule.created_by_id, "shares.cap_blocked", "in_app"):
            return
        db.add(models.Notification(
            user_id=rule.created_by_id,
            event_type="shares.cap_blocked",
            org_id=org.id,
            actor_id=None,
            target_type="organization",
            target_id=org.id,
            payload={
                "org_id": org.id, "org_slug": org.slug, "org_name": org.name,
                "rule_id": rule.id, "skipped_grants": skipped,
            },
        ))
    except Exception as e:  # noqa: BLE001
        log.debug("shares.cap_blocked notify failed for %s: %s", rule.created_by_id, e)


def run_rule(db: Session, org: models.Organization,
             rule: models.ShareDistributionRule, *, today: Optional[date] = None) -> int:
    """Fire all due, not-yet-granted periods for one rule. Returns the number
    of grants made. Idempotent (period_key guard). Caller owns the transaction
    per rule.

    Phase 90d — respects the authorized cap: a grant that would push the org's
    outstanding total above ``weighted_voting.authorized_total`` is SKIPPED (no
    ShareEvent, period_key NOT consumed, so it retries next sweep if headroom
    appears). One batched ``share.cap_blocked_distribution`` audit + creator
    notification per affected sweep.
    """
    from org_config import get_weighted_voting_config, outstanding_total
    from audit_utils import log_audit_event

    today = today or _today()
    if rule.status != "active":
        return 0

    # Participate in the same per-org serialization protocol as direct and
    # ratified issuance. Refresh the settings under the lock so a cap change
    # committed while this sweep waited is honored. Resolve target membership
    # rows only AFTER acquiring the lock: pre-lock ORM rows could retain stale
    # balances and overwrite an issuance that committed while this sweep waited.
    org = (
        db.query(models.Organization)
        .filter(models.Organization.id == org.id)
        .populate_existing()
        .with_for_update()
        .one()
    )
    targeted = resolve_targeted_members(db, org.id, rule)
    grants = 0
    cap = get_weighted_voting_config(org)["authorized_total"]
    # Track projected outstanding across grants in THIS sweep (weights mutate in
    # the session as we go). None cap = uncapped fast path.
    running = outstanding_total(db, org) if cap is not None else 0
    skipped_for_cap = 0

    def _try_grant(m, pk) -> bool:
        nonlocal grants, running, skipped_for_cap
        if _period_exists(db, org.id, pk):
            return False
        if cap is not None and running + rule.amount > cap:
            # Skip WITHOUT consuming period_key so it retries when headroom opens.
            skipped_for_cap += 1
            return False
        _grant(db, org_id=org.id, membership=m, amount=rule.amount,
               rule_id=rule.id, period_key=pk)
        _notify_recipient(db, m.user_id, org, rule, rule.amount)
        if cap is not None:
            running += rule.amount
        grants += 1
        return True

    if rule.schedule_mode == "fixed_cadence":
        anchor = rule.anchor_date or rule.created_at.date()
        max_k = _elapsed_k(anchor, rule.interval_months, today)
        if max_k < 1:
            return 0
        k_start = max(1, max_k - CATCHUP_CAP + 1)
        if max_k - k_start + 1 >= CATCHUP_CAP:
            log.warning("distribution rule %s hit the %d-period catch-up cap "
                        "(fixed)", rule.id, CATCHUP_CAP)
        for k in range(k_start, max_k + 1):
            for m in targeted:
                _try_grant(m, f"{rule.id}:{m.user_id}:{k}")
    else:  # anniversary
        for m in targeted:
            anchor = share_start_date_for(m)
            max_k = _elapsed_k(anchor, rule.interval_months, today)
            if max_k < 1:
                continue
            k_start = max(1, max_k - CATCHUP_CAP + 1)
            if max_k - k_start + 1 >= CATCHUP_CAP:
                log.warning("distribution rule %s hit the %d-period catch-up "
                            "cap (anniversary, member %s)", rule.id, CATCHUP_CAP,
                            m.user_id)
            for k in range(k_start, max_k + 1):
                _try_grant(m, f"{rule.id}:{m.user_id}:{k}")

    if skipped_for_cap:
        log_audit_event(
            db, action="share.cap_blocked_distribution",
            target_type="share_distribution_rule", target_id=rule.id,
            actor_id=None,
            details={"org_id": org.id, "rule_id": rule.id,
                     "skipped_grants": skipped_for_cap, "authorized_total": cap},
        )
        _notify_cap_blocked(db, org, rule, skipped_for_cap)

    rule.last_run_at = datetime.now(timezone.utc).replace(tzinfo=None)
    return grants


def run_distribution_sweep(db: Session, *, today: Optional[date] = None) -> dict:
    """Run one distribution sweep across all orgs. Skips orgs where weighted
    voting is disabled (rules lie dormant). One transaction per rule so a
    failure in one rule doesn't lose others. Returns per-run counts."""
    from org_config import get_weighted_voting_config

    today = today or _today()
    total_grants = 0
    rules_fired = 0
    rules = db.query(models.ShareDistributionRule).filter(
        models.ShareDistributionRule.status == "active",
    ).all()
    for rule in rules:
        org = db.get(models.Organization, rule.org_id)
        if org is None or not get_weighted_voting_config(org)["enabled"]:
            continue  # dormant
        try:
            g = run_rule(db, org, rule, today=today)
            db.commit()
            total_grants += g
            if g > 0:
                rules_fired += 1
        except Exception as e:  # noqa: BLE001
            log.warning("distribution rule %s sweep failed: %s: %s",
                        rule.id, type(e).__name__, e)
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
    return {"grants": total_grants, "rules_fired": rules_fired,
            "rules_considered": len(rules)}
