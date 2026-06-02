"""Phase 50 — Self-service leave-org service.

Single arbiter: the existing governance floor
(``governance.count_active_governors``). The leave function is mode-
independent — it asks the floor whether the leaver's departure would
strand the org and gates on transfer-first when the answer is yes.
Reuse, not reimplementation.

The ``leave_org`` function is the reusable core (account-deletion
will loop it across the user's orgs in a future pass — see Phase 50
spec § "What IS NOT in scope" forward-dependency note). The HTTP
route in ``routes/organizations.py`` is a thin wrapper that
translates the structured exceptions into HTTP responses.
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

import models
from audit_utils import log_audit_event


class TransferRequired(Exception):
    """Raised when ``leave_org`` would strand the org without a
    governor. Carries the mode + a structured payload for the HTTP
    layer to surface as a 409 so the FE can render the inline
    transfer-first flow."""

    def __init__(self, mode: str, detail: str):
        self.mode = mode
        self.detail = detail
        super().__init__(detail)

    def to_dict(self) -> dict:
        return {
            "error": "transfer_required",
            "mode": self.mode,
            "detail": self.detail,
        }


def leave_org(
    db: Session,
    org: models.Organization,
    user: models.User,
    *,
    actor_id: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> dict:
    """Self-service leave-org. Returns a result dict for the caller's
    response shape. Raises:

      * ``HTTPException(400)`` if the caller isn't an active member.
      * ``TransferRequired`` (caught by the HTTP route → 409) if the
        leaver is the sole governor (D1). The FE renders the inline
        transfer step from the structured payload.

    On success: revokes the leaver's Phase 47 custom title assignments
    (system titles are role-derived; the role removal handles them),
    deletes outgoing org-scoped delegations (B3 — incoming resolve
    naturally via the eligibility filter in the tally engine), hard-
    deletes the membership, audits ``org.left``. ``actor_id`` defaults
    to ``user.id`` since leaving is a self-action; passed explicitly so
    a future account-deletion path can attribute it to itself when
    looping per-org.
    """
    from governance import (
        count_active_governors, is_top_tier_role, mode_of,
        SINGLE_STEWARD, ADMIN_COUNCIL, check_and_audit_rebootstrap,
    )

    if actor_id is None:
        actor_id = user.id

    membership = (
        db.query(models.OrgMembership)
        .filter(
            models.OrgMembership.org_id == org.id,
            models.OrgMembership.user_id == user.id,
            models.OrgMembership.status == "active",
        )
        .first()
    )
    if membership is None:
        raise HTTPException(
            status_code=400,
            detail="You are not an active member of this organization.",
        )

    role = db.get(models.Role, membership.role_id) if membership.role_id else None
    is_governor = (
        role is not None and is_top_tier_role(org, role.system_key)
    )

    # D1 — floor check via the existing helper.
    if is_governor:
        other_governor_count = count_active_governors(
            db, org, exclude_user_id=user.id,
        )
        if other_governor_count == 0:
            mode = mode_of(org)
            if mode == SINGLE_STEWARD:
                raise TransferRequired(
                    mode=mode,
                    detail=(
                        "You are the only Steward of this organization. "
                        "Transfer stewardship to another member, then "
                        "leave."
                    ),
                )
            raise TransferRequired(
                mode=mode,
                detail=(
                    "You are the only Admin of this organization. "
                    "Promote another member to Admin (or switch back "
                    "to a single-leader setup), then leave."
                ),
            )

    # D3 — revoke the leaver's custom title assignments before the
    # membership is removed. System titles (Steward / Admin) are
    # role-derived and clear when the role is removed via the
    # membership delete; no explicit revoke required for them. The
    # floor check above guarantees that revoking a bound-role title
    # in this path is floor-safe (the leaver isn't the sole governor).
    custom_assignments = (
        db.query(models.OrgTitleAssignment)
        .join(
            models.OrgTitle,
            models.OrgTitle.id == models.OrgTitleAssignment.title_id,
        )
        .filter(
            models.OrgTitle.org_id == org.id,
            models.OrgTitle.is_system == False,  # noqa: E712
            models.OrgTitleAssignment.user_id == user.id,
        )
        .all()
    )
    revoked_title_ids: list[str] = []
    for ta in custom_assignments:
        title_id = ta.title_id
        title = db.get(models.OrgTitle, title_id)
        db.delete(ta)
        revoked_title_ids.append(title_id)
        # Audit the revocation through the same channel
        # ``routes/org_titles.py`` uses, with a leave-specific trigger.
        log_audit_event(
            db,
            action="title.revoked",
            target_type="org_title",
            target_id=title_id,
            actor_id=actor_id,
            details={
                "org_id": org.id,
                "title_name": title.name if title else None,
                "user_id": user.id,
                "trigger": "member_left",
            },
            ip_address=ip_address,
        )

    # B3 — clean the leaver's outgoing org-scoped delegations.
    # Incoming delegations (others delegating TO the leaver) resolve
    # naturally: ``eligible_voter_ids_for_proposal`` filters delegates
    # by active OrgMembership, so a departed delegate's ballot is
    # filtered out of every tally. Documented in the Phase 50 closeout.
    n_outgoing = (
        db.query(models.Delegation)
        .filter(
            models.Delegation.org_id == org.id,
            models.Delegation.delegator_id == user.id,
        )
        .delete(synchronize_session=False)
    )
    # Also clean delegation intents (the pre-vote signal layer).
    n_intents = (
        db.query(models.DelegationIntent)
        .filter(
            models.DelegationIntent.org_id == org.id,
            models.DelegationIntent.delegator_id == user.id,
        )
        .delete(synchronize_session=False)
    )

    # Hard-delete the membership (matches ``execute_member_remove``).
    db.delete(membership)
    db.flush()

    log_audit_event(
        db,
        action="org.left",
        target_type="organization",
        target_id=org.id,
        actor_id=actor_id,
        details={
            "user_id": user.id,
            "role": role.system_key if role else None,
            "revoked_title_ids": revoked_title_ids,
            "outgoing_delegations_deleted": int(n_outgoing or 0),
            "outgoing_delegation_intents_deleted": int(n_intents or 0),
        },
        ip_address=ip_address,
    )

    # Defensive: keep the Phase 45b B4 rebootstrap-check pattern
    # uniform even though the floor was satisfied (this call is a
    # no-op in that case — count_active_governors > 0).
    check_and_audit_rebootstrap(
        db, org, actor_id=actor_id, ip_address=ip_address,
    )

    return {
        "status": "ok",
        "left_at": models._now().isoformat()
        if hasattr(models, "_now") else None,
        "revoked_title_ids": revoked_title_ids,
        "outgoing_delegations_deleted": int(n_outgoing or 0),
    }
