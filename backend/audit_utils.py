"""
Audit log utility.

Call log_audit_event() inside the same database transaction as the action it
records — the write is committed atomically with the action or rolled back
together if anything fails.

Phase 15 Cluster S §S5 — when the action was authorized via the
platform-admin override path on a sub-org (i.e., the actor has no direct
or transferable membership-based permission on the sub-org and the
effective role came from User.is_admin), pass
``platform_admin_override=True`` and the flag will be merged into the
details payload as ``"platform_admin_override": true``. This makes
"platform admin operating on behalf" explicit in the audit trail.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

import models


def log_audit_event(
    db: Session,
    *,
    action: str,
    target_type: str,
    target_id: str,
    actor_id: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    platform_admin_override: bool = False,
) -> models.AuditLog:
    """
    Append one entry to the audit log within the caller's transaction.

    Parameters
    ----------
    db          : active SQLAlchemy session (same transaction as the action)
    action      : dot-namespaced string, e.g. "vote.cast", "delegation.created"
    target_type : table/entity name, e.g. "proposal", "delegation", "vote", "user"
    target_id   : UUID of the affected entity
    actor_id    : ID of the user performing the action (None for system events)
    details     : action-specific JSON payload
    ip_address  : client IP (optional, for future abuse detection)
    platform_admin_override : Phase 15 Cluster S — when True, merge
        ``"platform_admin_override": true`` into the details payload so
        downstream audit consumers can distinguish actions taken via
        the platform-admin sub-org override from regular membership-
        based actions. Callers obtain the flag from
        ``role_permissions.effective_role_on_sub_org`` or
        ``has_permission_on_sub_org``.
    """
    payload: dict[str, Any] = dict(details or {})
    if platform_admin_override:
        payload["platform_admin_override"] = True
    entry = models.AuditLog(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=payload,
        ip_address=ip_address,
    )
    db.add(entry)
    return entry
