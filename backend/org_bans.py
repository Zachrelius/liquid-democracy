"""Phase 85 (B-8 fix) — org-scoped rejoin ban helpers.

An active ban (``OrgBan`` row with ``revoked_at IS NULL``) blocks EVERY
join / membership-creation path for a ``(org_id, user_id)`` pair until an
admin revokes it. Centralizing the query + the 403 here keeps the several
join entry points (two join endpoints, approve-join, invitation acceptance,
and the register/login invite-consume path) consistent and greppable.

Bans are org-scoped only; there is no platform-level ban in this pass.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

import models
from audit_utils import log_audit_event


# Single user-facing message for every blocked join path (the spec requires
# the same error everywhere so a banned user can't distinguish which path
# they hit).
BAN_REJOIN_MESSAGE = (
    "You have been removed from this organization and cannot rejoin."
)


def _now_naive() -> datetime:
    """Naive UTC to match the DateTime columns (stored without tz)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def active_ban(
    db: Session, org_id: str, user_id: str
) -> Optional[models.OrgBan]:
    """Return the active (un-revoked) ban for (org_id, user_id), or None."""
    return (
        db.query(models.OrgBan)
        .filter(
            models.OrgBan.org_id == org_id,
            models.OrgBan.user_id == user_id,
            models.OrgBan.revoked_at.is_(None),
        )
        .first()
    )


def is_user_banned(db: Session, org_id: str, user_id: str) -> bool:
    return active_ban(db, org_id, user_id) is not None


def raise_if_banned(db: Session, org_id: str, user_id: str) -> None:
    """Raise 403 with the canonical message if an active ban exists.

    Load-bearing invariant: called at every membership-creation entry point
    BEFORE a row is written / reactivated, so a banned user never obtains an
    active or pending membership.
    """
    if is_user_banned(db, org_id, user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=BAN_REJOIN_MESSAGE,
        )


def create_ban(
    db: Session,
    *,
    org_id: str,
    user_id: str,
    banned_by_id: Optional[str],
    reason: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> models.OrgBan:
    """Write an ``OrgBan`` row + ``member.banned`` audit event.

    Idempotent against the active-ban partial unique index: if an active ban
    already exists for the pair, returns it without inserting a duplicate.
    Does NOT commit — the caller's transaction encompasses this (so a
    remove+ban lands atomically).
    """
    existing = active_ban(db, org_id, user_id)
    if existing is not None:
        return existing
    ban = models.OrgBan(
        org_id=org_id,
        user_id=user_id,
        banned_by_id=banned_by_id,
        reason=reason,
    )
    db.add(ban)
    db.flush()
    log_audit_event(
        db,
        action="member.banned",
        target_type="user",
        target_id=user_id,
        actor_id=banned_by_id,
        details={"org_id": org_id, "ban_id": ban.id, "reason": reason},
        ip_address=ip_address,
    )
    return ban


def revoke_ban(
    db: Session,
    *,
    ban: models.OrgBan,
    revoked_by_id: Optional[str],
    ip_address: Optional[str] = None,
) -> models.OrgBan:
    """Revoke a ban (set ``revoked_at`` / ``revoked_by_id``). Never deletes
    the row — the ban history is an audit surface. Idempotent: revoking an
    already-revoked ban is a no-op. Does NOT commit.
    """
    if ban.revoked_at is None:
        ban.revoked_at = _now_naive()
        ban.revoked_by_id = revoked_by_id
        log_audit_event(
            db,
            action="member.ban_revoked",
            target_type="user",
            target_id=ban.user_id,
            actor_id=revoked_by_id,
            details={"org_id": ban.org_id, "ban_id": ban.id},
            ip_address=ip_address,
        )
    return ban
