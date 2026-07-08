"""issuance.py — Phase 90e vote-gated share issuance.

An issuance proposal is a binary approve/reject of a share action snapshotted in
``Proposal.issuance_payload`` = ``{"action": <key>, "params": {...}}``. It exists
only in orgs whose ``weighted_voting.issuance_mode == 'member_vote'``. On a passed
close the payload executes via the SAME 90d executors the multi_admin ratification
path uses (do not fork validation or execution); the resulting ShareEvent carries
``authorization_ref = 'proposal:<id>'``. On fail/expiry nothing executes.

Mirrors ``elections.run_election_close_hook``: one shared hook called from all
three close sites (routes/proposals.py advance, routes/organizations.py advance,
the sustained-majority worker) so they can't drift. Drift at close (e.g. the
target member left the org between creation and close) resolves the proposal
``passed`` but ``issuance_executed=False`` with a ``share.issuance_execution_failed``
audit + author notification — the elections ``not_finalized`` honesty pattern.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

import models

log = logging.getLogger(__name__)


# Issuance-payload action key -> registered pending-action type. One channel,
# shared validators + executors.
ISSUANCE_ACTION_TYPES = {
    "set_weight": "share.set_weight",
    "rule_create": "share.rule_create",
    "rule_edit": "share.rule_edit",
    "rule_resume": "share.rule_resume",
    "cap_raise": "share.cap_raise",
    "issuance_mode_weaken": "share.issuance_mode_weaken",
}


def _action_type_for(action_key: str) -> str:
    at = ISSUANCE_ACTION_TYPES.get(action_key)
    if at is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "issuance action must be one of "
                + ", ".join(ISSUANCE_ACTION_TYPES.keys())
            ),
        )
    return at


def validate_issuance_payload(
    db: Session, org: models.Organization, payload: dict, actor: models.User,
) -> None:
    """Validate an issuance payload at CREATION using the same validator the
    corresponding pending-action type uses. Also enforces the authorized cap up
    front for weight increases (spec §3.2: creation 400 if it would breach)."""
    from pending_actions import registry
    from org_config import get_weighted_voting_config, outstanding_total

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="issuance_payload must be an object")
    action_key = payload.get("action")
    params = payload.get("params")
    if not isinstance(params, dict):
        raise HTTPException(status_code=400, detail="issuance_payload.params must be an object")
    at = _action_type_for(action_key)
    defn = registry.get_action_definition(at)
    defn.payload_validator(params, db, org, actor)

    # Up-front cap check for a weight SET that increases (mirrors the direct
    # path's set_member_weight cap; validated now so the ballot never promises
    # an issuance that can't execute).
    cfg = get_weighted_voting_config(org)
    cap = cfg["authorized_total"]
    if cap is not None and action_key == "set_weight":
        m = db.query(models.OrgMembership).filter(
            models.OrgMembership.org_id == org.id,
            models.OrgMembership.user_id == params.get("target_user_id"),
            models.OrgMembership.status == "active",
        ).first()
        old = (m.voting_weight or 0) if m else 0
        new = int(params.get("new_weight", old))
        if new > old:
            projected = outstanding_total(db, org) + (new - old)
            if projected > cap:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"This issuance would raise the outstanding total to "
                        f"{projected}, above the authorized cap of {cap}."
                    ),
                )


def _stub_action(proposal: models.Proposal, org: models.Organization):
    """A transient PendingAdminAction-shaped object the 90d executors accept.
    Carries the proposal authorization ref so the ledger records 'proposal:<id>'.
    """
    params = (proposal.issuance_payload or {}).get("params", {})
    return SimpleNamespace(
        id=proposal.id,
        org_id=org.id,
        initiator_id=proposal.author_id,
        payload=params,
        _issuance_authz_ref=f"proposal:{proposal.id}",
    )


def _notify_author_failed(db: Session, proposal: models.Proposal) -> None:
    try:
        from notification_emit import _is_channel_enabled
        if not _is_channel_enabled(db, proposal.author_id, "shares.issuance_failed", "in_app"):
            return
        org = db.get(models.Organization, proposal.org_id)
        db.add(models.Notification(
            user_id=proposal.author_id,
            event_type="shares.issuance_failed",
            org_id=proposal.org_id,
            actor_id=None,
            target_type="proposal",
            target_id=proposal.id,
            payload={
                "org_id": proposal.org_id,
                "org_slug": org.slug if org else None,
                "org_name": org.name if org else None,
                "proposal_id": proposal.id,
                "proposal_title": proposal.title,
            },
        ))
    except Exception as e:  # noqa: BLE001
        log.debug("issuance_failed notify failed for %s: %s", proposal.author_id, e)


def run_issuance_close_hook(
    db: Session,
    proposal: models.Proposal,
    closed_status: str,
    *,
    actor_id: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> str:
    """Shared close hook for issuance proposals. On a passed close, re-validate
    then execute the payload via the shared executor inside the close txn. Drift
    → passed but ``issuance_executed=False`` + audit + author notification. On
    fail/expiry nothing executes. Non-issuance proposals return immediately.

    Failure is contained: a hook error never rolls back the status transition
    (mirrors ``run_election_close_hook``)."""
    if not getattr(proposal, "is_issuance", False):
        return closed_status
    if closed_status != "passed":
        # Failed / expired vote — nothing executes; record the non-execution
        # so the proposal page can say so honestly.
        proposal.issuance_executed = False
        return closed_status

    from pending_actions import registry
    from audit_utils import log_audit_event

    org = db.get(models.Organization, proposal.org_id)
    payload = proposal.issuance_payload or {}
    action_key = payload.get("action")
    author = db.get(models.User, proposal.author_id)
    actor = db.get(models.User, actor_id) if actor_id else author
    try:
        at = _action_type_for(action_key)
        defn = registry.get_action_definition(at)
        params = payload.get("params") or {}
        # Re-validate against drift (target left org, cap changed, etc.).
        defn.payload_validator(params, db, org, author)
        defn.executor(db, _stub_action(proposal, org), actor)
        proposal.issuance_executed = True
        log_audit_event(
            db, action="share.issuance_executed",
            target_type="proposal", target_id=proposal.id,
            actor_id=actor_id,
            details={"proposal_id": proposal.id, "action": action_key,
                     "org_id": proposal.org_id},
            ip_address=ip_address,
        )
    except Exception as exc:  # noqa: BLE001
        proposal.issuance_executed = False
        detail = getattr(exc, "detail", None) or str(exc)
        log_audit_event(
            db, action="share.issuance_execution_failed",
            target_type="proposal", target_id=proposal.id,
            actor_id=actor_id,
            details={"proposal_id": proposal.id, "action": action_key,
                     "reason": str(detail), "org_id": proposal.org_id},
            ip_address=ip_address,
        )
        _notify_author_failed(db, proposal)
        log.warning("issuance close hook execution failed for proposal %s: %s",
                    proposal.id, detail)
    return closed_status


def issuance_preview(db: Session, proposal: models.Proposal) -> Optional[dict]:
    """Reuse the 90d preview builders (one source of truth for both the
    ratification UI and the issuance-proposal page) to describe what the vote
    would do, including the dilution line."""
    if not getattr(proposal, "is_issuance", False):
        return None
    from pending_actions import registry
    payload = proposal.issuance_payload or {}
    try:
        at = _action_type_for(payload.get("action"))
    except HTTPException:
        return None
    defn = registry.get_action_definition(at)
    org = db.get(models.Organization, proposal.org_id)
    stub = _stub_action(proposal, org)
    try:
        return defn.preview_builder(stub, db)
    except Exception as e:  # noqa: BLE001
        log.debug("issuance preview failed for %s: %s", proposal.id, e)
        return None
