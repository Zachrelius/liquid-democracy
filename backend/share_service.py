"""share_service.py — Phase 90 shared callables for voting-weight ("share")
movements.

Deliberately route-free so the SAME logic backs the direct endpoints, the
Phase 44 ratification executors (Phase 90d), and the vote-close hook (Phase
90e). Callers own the transaction: these functions add + flush but never
commit, mirroring the ``execute_member_remove`` extraction pattern.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

import models


class ShareServiceError(Exception):
    """Domain violation (zero delta, out-of-range weight, insufficient
    balance). Route callers map ``status_code`` to an HTTP error; ratification
    executors map it to a failed-action status."""

    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def set_member_weight(
    db: Session,
    *,
    membership: models.OrgMembership,
    new_weight: int,
    actor_id: Optional[str],
) -> models.ShareEvent:
    """Set ``membership.voting_weight`` to ``new_weight`` AND record an
    ``admin_set`` ShareEvent, in the caller's transaction. A zero delta is
    rejected (nothing changes, nothing is logged). Returns the ShareEvent.
    """
    from org_config import VOTING_WEIGHT_MIN, VOTING_WEIGHT_MAX

    if not isinstance(new_weight, int) or isinstance(new_weight, bool):
        raise ShareServiceError("voting_weight must be an integer.")
    if new_weight < VOTING_WEIGHT_MIN or new_weight > VOTING_WEIGHT_MAX:
        raise ShareServiceError(
            f"voting_weight must be an integer between "
            f"{VOTING_WEIGHT_MIN} and {VOTING_WEIGHT_MAX}."
        )
    old = membership.voting_weight or 0
    delta = new_weight - old
    if delta == 0:
        raise ShareServiceError(
            "voting_weight is unchanged; no share event recorded."
        )
    membership.voting_weight = new_weight
    event = models.ShareEvent(
        org_id=membership.org_id,
        event_type="admin_set",
        user_id=membership.user_id,
        delta=delta,
        resulting_balance=new_weight,
        actor_id=actor_id,
    )
    db.add(event)
    db.flush()
    return event
