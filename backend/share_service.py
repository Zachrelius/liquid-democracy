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


def transfer_shares(
    db: Session,
    *,
    org: models.Organization,
    sender_membership: models.OrgMembership,
    recipient_membership: models.OrgMembership,
    amount: int,
    actor_id: Optional[str],
) -> models.ShareEvent:
    """Move ``amount`` shares from sender to recipient AND write a single
    ``transfer`` ShareEvent, in the caller's transaction. Conserves the org
    total. Balances can reach 0, never negative. Returns the ShareEvent.

    The caller is responsible for locking the sender row (SELECT ... FOR UPDATE
    on Postgres) before calling, so two simultaneous transfers can't overdraw.
    """
    if not isinstance(amount, int) or isinstance(amount, bool) or amount < 1:
        raise ShareServiceError("amount must be an integer >= 1.")
    if sender_membership.user_id == recipient_membership.user_id:
        raise ShareServiceError("You cannot transfer shares to yourself.")
    sender_bal = sender_membership.voting_weight or 0
    if sender_bal < amount:
        raise ShareServiceError("Insufficient balance for this transfer.")
    new_sender = sender_bal - amount
    new_recipient = (recipient_membership.voting_weight or 0) + amount
    sender_membership.voting_weight = new_sender
    recipient_membership.voting_weight = new_recipient
    event = models.ShareEvent(
        org_id=org.id,
        event_type="transfer",
        user_id=None,
        from_user_id=sender_membership.user_id,
        to_user_id=recipient_membership.user_id,
        delta=amount,
        resulting_balance=new_recipient,
        from_resulting_balance=new_sender,
        actor_id=actor_id,
    )
    db.add(event)
    db.flush()
    return event
