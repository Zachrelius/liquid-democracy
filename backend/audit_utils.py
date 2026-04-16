"""
Audit log utility.

Call log_audit_event() inside the same database transaction as the action it
records — the write is committed atomically with the action or rolled back
together if anything fails.
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
    """
    entry = models.AuditLog(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details or {},
        ip_address=ip_address,
    )
    db.add(entry)
    return entry
