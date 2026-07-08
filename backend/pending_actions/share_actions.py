"""Phase 90d — issuance-class pending-action definitions.

Registers the six share.* action types that route through the Phase 44
ratification engine when an org's ``weighted_voting.issuance_mode == 'multi_admin'``.
Executors call the SAME route-free service callables the direct path uses
(``share_service`` / ``share_distribution``), stamping each resulting ShareEvent
with ``authorization_ref = 'pending_action:<id>'`` so the ledger records what
authorized the movement.

All six use ``member.set_voting_weight`` as the required key + default
approver set, EXCEPT ``share.issuance_mode_weaken``, which follows the 49a
pattern (``_admins_of`` + ``admin_or_steward_only``) so the constrained party
can't shrink its own approver set via the permission matrix first.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

import models
from org_config import (
    VOTING_WEIGHT_MIN, VOTING_WEIGHT_MAX, WEIGHTED_ISSUANCE_MODES,
    get_weighted_voting_config, outstanding_total, issuance_mode_is_weakening,
)

from .registry import (
    ActionDefinition, register, _default_approver_set, _admins_of, _require_str,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _active_membership(db: Session, org: models.Organization, user_id: str):
    return db.query(models.OrgMembership).filter(
        models.OrgMembership.org_id == org.id,
        models.OrgMembership.user_id == user_id,
        models.OrgMembership.status == "active",
    ).first()


def _rule_in_org(db: Session, org: models.Organization, rule_id: str):
    r = db.get(models.ShareDistributionRule, rule_id)
    if r is None or r.org_id != org.id:
        return None
    return r


def _authz_ref(action: "models.PendingAdminAction") -> str:
    return f"pending_action:{action.id}"


def _pct(old: int, new: int) -> str:
    if old <= 0:
        return "+∞%" if new > 0 else "0%"
    return f"{(new - old) / old * 100:+.1f}%"


# ---------------------------------------------------------------------------
# share.set_weight
# ---------------------------------------------------------------------------

def _validate_set_weight(payload, db, org, actor) -> None:
    target_user_id = _require_str(payload, "target_user_id")
    if _active_membership(db, org, target_user_id) is None:
        raise HTTPException(status_code=404, detail="Target is not an active member of this org")
    nw = payload.get("new_weight")
    if isinstance(nw, bool) or not isinstance(nw, int):
        raise HTTPException(status_code=400, detail="new_weight must be an integer")
    if nw < VOTING_WEIGHT_MIN or nw > VOTING_WEIGHT_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"new_weight must be between {VOTING_WEIGHT_MIN} and {VOTING_WEIGHT_MAX}",
        )


def _exec_set_weight(db, action, actor_user) -> None:
    import share_service
    org = db.get(models.Organization, action.org_id)
    m = _active_membership(db, org, action.payload["target_user_id"])
    if m is None:
        raise HTTPException(status_code=404, detail="Target is not an active member of this org")
    cfg = get_weighted_voting_config(org)
    try:
        share_service.set_member_weight(
            db, membership=m, new_weight=int(action.payload["new_weight"]),
            actor_id=actor_user.id if actor_user else None,
            authorization_ref=_authz_ref(action),
            authorized_total=cfg["authorized_total"],
        )
    except share_service.ShareServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


def _preview_set_weight(action, db) -> dict[str, Any]:
    org = db.get(models.Organization, action.org_id)
    cfg = get_weighted_voting_config(org)
    unit = cfg["unit_label"]
    target = db.get(models.User, action.payload.get("target_user_id"))
    target_name = target.display_name if target else "(unknown member)"
    m = _active_membership(db, org, action.payload.get("target_user_id", "")) if org else None
    old_w = (m.voting_weight or 0) if m else 0
    new_w = int(action.payload.get("new_weight", old_w))
    out: dict[str, Any] = {
        "label": "Set member shares",
        "summary": f"Set {target_name}'s {unit} to {new_w} (was {old_w})",
        "target": {"type": "user", "id": action.payload.get("target_user_id"),
                   "display_name": target_name},
        "unit_label": unit,
    }
    if org is not None:
        cur_total = outstanding_total(db, org)
        new_total = cur_total + (new_w - old_w)
        out["dilution"] = {
            "outstanding_before": cur_total,
            "outstanding_after": new_total,
            "change_pct": _pct(cur_total, new_total),
            "authorized_total": cfg["authorized_total"],
        }
    return out


# ---------------------------------------------------------------------------
# share.rule_create
# ---------------------------------------------------------------------------

def _rule_config_from_payload(payload: dict) -> dict:
    return {
        "amount": payload.get("amount"),
        "interval_months": payload.get("interval_months"),
        "schedule_mode": payload.get("schedule_mode"),
        "targeting_mode": payload.get("targeting_mode"),
        "title_ids": payload.get("title_ids") or [],
    }


def _validate_rule_create(payload, db, org, actor) -> None:
    import share_distribution
    from share_service import ShareServiceError
    cfg = _rule_config_from_payload(payload)
    try:
        share_distribution.validate_rule_config(**cfg)
    except ShareServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    for tid in cfg["title_ids"]:
        t = db.get(models.OrgTitle, tid)
        if t is None or t.org_id != org.id:
            raise HTTPException(status_code=400,
                                detail=f"title {tid} does not belong to this organization.")


def _exec_rule_create(db, action, actor_user) -> None:
    import share_distribution
    from share_service import ShareServiceError
    org = db.get(models.Organization, action.org_id)
    p = action.payload
    try:
        share_distribution.create_rule(
            db, org=org, created_by_id=action.initiator_id,
            amount=p["amount"], interval_months=p["interval_months"],
            schedule_mode=p["schedule_mode"], targeting_mode=p["targeting_mode"],
            title_ids=p.get("title_ids") or [], anchor_date=None,
        )
    except ShareServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


def _rule_estimate(db, org, payload) -> dict:
    """First-period dilution estimate for a create/edit preview."""
    import share_distribution
    cfg = get_weighted_voting_config(org)
    amount = payload.get("amount") or 0
    # Estimate recipient count from a synthetic rule (targeting resolved now).
    synth = models.ShareDistributionRule(
        org_id=org.id, targeting_mode=payload.get("targeting_mode") or "all_members",
        title_ids=payload.get("title_ids") or [],
    )
    try:
        n = len(share_distribution.resolve_targeted_members(db, org.id, synth))
    except Exception:
        n = 0
    cur_total = outstanding_total(db, org)
    first_period = amount * n
    new_total = cur_total + first_period
    return {
        "recipients_estimate": n,
        "amount_per_member": amount,
        "outstanding_before": cur_total,
        "outstanding_after_first_period": new_total,
        "change_pct": _pct(cur_total, new_total),
        "authorized_total": cfg["authorized_total"],
        "unit_label": cfg["unit_label"],
    }


def _preview_rule_create(action, db) -> dict[str, Any]:
    org = db.get(models.Organization, action.org_id)
    p = action.payload
    est = _rule_estimate(db, org, p) if org else {}
    return {
        "label": "Create distribution rule",
        "summary": (
            f"Grant {p.get('amount')} {est.get('unit_label', 'shares')} every "
            f"{p.get('interval_months')} month(s) to "
            f"~{est.get('recipients_estimate', '?')} member(s)"
        ),
        "rule": _rule_config_from_payload(p),
        "dilution": est,
    }


# ---------------------------------------------------------------------------
# share.rule_edit
# ---------------------------------------------------------------------------

def _merged_rule_config(rule, payload) -> dict:
    return {
        "amount": payload["amount"] if payload.get("amount") is not None else rule.amount,
        "interval_months": (payload["interval_months"]
                            if payload.get("interval_months") is not None
                            else rule.interval_months),
        "schedule_mode": payload.get("schedule_mode") or rule.schedule_mode,
        "targeting_mode": payload.get("targeting_mode") or rule.targeting_mode,
        "title_ids": (payload["title_ids"] if payload.get("title_ids") is not None
                      else (rule.title_ids or [])),
    }


def _validate_rule_edit(payload, db, org, actor) -> None:
    import share_distribution
    from share_service import ShareServiceError
    rule_id = _require_str(payload, "rule_id")
    rule = _rule_in_org(db, org, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found in this organization")
    merged = _merged_rule_config(rule, payload)
    try:
        share_distribution.validate_rule_config(**merged)
    except ShareServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    for tid in merged["title_ids"]:
        t = db.get(models.OrgTitle, tid)
        if t is None or t.org_id != org.id:
            raise HTTPException(status_code=400,
                                detail=f"title {tid} does not belong to this organization.")


def _exec_rule_edit(db, action, actor_user) -> None:
    org = db.get(models.Organization, action.org_id)
    rule = _rule_in_org(db, org, action.payload["rule_id"])
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found in this organization")
    merged = _merged_rule_config(rule, action.payload)
    rule.amount = merged["amount"]
    rule.interval_months = merged["interval_months"]
    rule.schedule_mode = merged["schedule_mode"]
    rule.targeting_mode = merged["targeting_mode"]
    rule.title_ids = merged["title_ids"] if merged["targeting_mode"] != "all_members" else []


def _preview_rule_edit(action, db) -> dict[str, Any]:
    org = db.get(models.Organization, action.org_id)
    rule = _rule_in_org(db, org, action.payload.get("rule_id", "")) if org else None
    merged = _merged_rule_config(rule, action.payload) if rule else {}
    est = _rule_estimate(db, org, merged) if org and rule else {}
    return {
        "label": "Edit distribution rule",
        "summary": (
            f"Change distribution rule to grant {merged.get('amount')} "
            f"{est.get('unit_label', 'shares')} every "
            f"{merged.get('interval_months')} month(s)"
        ),
        "rule": merged,
        "dilution": est,
    }


# ---------------------------------------------------------------------------
# share.rule_resume
# ---------------------------------------------------------------------------

def _validate_rule_resume(payload, db, org, actor) -> None:
    rule_id = _require_str(payload, "rule_id")
    if _rule_in_org(db, org, rule_id) is None:
        raise HTTPException(status_code=404, detail="Rule not found in this organization")


def _exec_rule_resume(db, action, actor_user) -> None:
    org = db.get(models.Organization, action.org_id)
    rule = _rule_in_org(db, org, action.payload["rule_id"])
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found in this organization")
    rule.status = "active"


def _preview_rule_resume(action, db) -> dict[str, Any]:
    org = db.get(models.Organization, action.org_id)
    rule = _rule_in_org(db, org, action.payload.get("rule_id", "")) if org else None
    rule_cfg = {} if rule is None else {
        "amount": rule.amount,
        "interval_months": rule.interval_months,
        "schedule_mode": rule.schedule_mode,
        "targeting_mode": rule.targeting_mode,
        "title_ids": rule.title_ids or [],
    }
    return {
        "label": "Resume distribution rule",
        "summary": "Resume a paused distribution rule (it will begin granting shares again)",
        "rule": rule_cfg,
    }


# ---------------------------------------------------------------------------
# share.cap_raise
# ---------------------------------------------------------------------------

def _validate_cap_raise(payload, db, org, actor) -> None:
    at = payload.get("authorized_total")
    if at is not None and (isinstance(at, bool) or not isinstance(at, int) or at < 0):
        raise HTTPException(status_code=400,
                            detail="authorized_total must be a non-negative integer or null")
    # Raising means the new cap must be >= current outstanding (a cap below
    # outstanding is a LOWERING, which is unilateral, not this action).
    if at is not None:
        cur = outstanding_total(db, org)
        if at < cur:
            raise HTTPException(
                status_code=400,
                detail=f"authorized_total ({at}) cannot be below the current outstanding total ({cur}).",
            )


def _exec_cap_raise(db, action, actor_user) -> None:
    from audit_utils import log_audit_event
    org = db.get(models.Organization, action.org_id)
    settings = dict(org.settings or {})
    wv = dict(settings.get("weighted_voting") or {})
    old = wv.get("authorized_total")
    wv["authorized_total"] = action.payload.get("authorized_total")
    settings["weighted_voting"] = wv
    org.settings = settings
    log_audit_event(
        db, action="share.authorized_total_changed",
        target_type="organization", target_id=org.id,
        actor_id=actor_user.id if actor_user else None,
        details={"old": old, "new": wv["authorized_total"], "via": "multi_admin"},
    )


def _preview_cap_raise(action, db) -> dict[str, Any]:
    org = db.get(models.Organization, action.org_id)
    cfg = get_weighted_voting_config(org) if org else {}
    return {
        "label": "Raise authorized share cap",
        "summary": (
            f"Raise the authorized total to {action.payload.get('authorized_total')} "
            f"(currently {cfg.get('authorized_total')})"
        ),
        "current_authorized_total": cfg.get("authorized_total"),
        "proposed_authorized_total": action.payload.get("authorized_total"),
        "outstanding": outstanding_total(db, org) if org else 0,
        "unit_label": cfg.get("unit_label", "shares"),
    }


# ---------------------------------------------------------------------------
# share.issuance_mode_weaken  (49a pattern: admin/steward-ratified)
# ---------------------------------------------------------------------------

def _validate_issuance_mode_weaken(payload, db, org, actor) -> None:
    new_mode = payload.get("new_mode")
    if new_mode not in WEIGHTED_ISSUANCE_MODES:
        raise HTTPException(
            status_code=400,
            detail="new_mode must be one of " + ", ".join(WEIGHTED_ISSUANCE_MODES),
        )
    current = get_weighted_voting_config(org)["issuance_mode"]
    if not issuance_mode_is_weakening(current, new_mode):
        raise HTTPException(
            status_code=400,
            detail=(
                "Proposed issuance_mode does not weaken the current mode; "
                "apply it directly via settings rather than the approval workflow."
            ),
        )


def _exec_issuance_mode_weaken(db, action, actor_user) -> None:
    from audit_utils import log_audit_event
    org = db.get(models.Organization, action.org_id)
    settings = dict(org.settings or {})
    wv = dict(settings.get("weighted_voting") or {})
    old = wv.get("issuance_mode", "direct")
    wv["issuance_mode"] = action.payload["new_mode"]
    settings["weighted_voting"] = wv
    org.settings = settings
    log_audit_event(
        db, action="share.issuance_mode_changed",
        target_type="organization", target_id=org.id,
        actor_id=actor_user.id if actor_user else None,
        details={"old": old, "new": wv["issuance_mode"], "via": "multi_admin"},
    )


def _preview_issuance_mode_weaken(action, db) -> dict[str, Any]:
    org = db.get(models.Organization, action.org_id)
    cfg = get_weighted_voting_config(org) if org else {}
    return {
        "label": "Weaken issuance authorization",
        "summary": (
            f"Change how share issuance is authorized from "
            f"'{cfg.get('issuance_mode')}' to '{action.payload.get('new_mode')}'"
        ),
        "destructive": "high",
        "current_mode": cfg.get("issuance_mode"),
        "proposed_mode": action.payload.get("new_mode"),
    }


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_KEY = "member.set_voting_weight"

register(ActionDefinition(
    action_type="share.set_weight",
    required_permission_key=_KEY,
    summary_label="Set member shares",
    approver_set_resolver=_default_approver_set(_KEY),
    payload_validator=_validate_set_weight,
    executor=_exec_set_weight,
    preview_builder=_preview_set_weight,
))

register(ActionDefinition(
    action_type="share.rule_create",
    required_permission_key=_KEY,
    summary_label="Create distribution rule",
    approver_set_resolver=_default_approver_set(_KEY),
    payload_validator=_validate_rule_create,
    executor=_exec_rule_create,
    preview_builder=_preview_rule_create,
))

register(ActionDefinition(
    action_type="share.rule_edit",
    required_permission_key=_KEY,
    summary_label="Edit distribution rule",
    approver_set_resolver=_default_approver_set(_KEY),
    payload_validator=_validate_rule_edit,
    executor=_exec_rule_edit,
    preview_builder=_preview_rule_edit,
))

register(ActionDefinition(
    action_type="share.rule_resume",
    required_permission_key=_KEY,
    summary_label="Resume distribution rule",
    approver_set_resolver=_default_approver_set(_KEY),
    payload_validator=_validate_rule_resume,
    executor=_exec_rule_resume,
    preview_builder=_preview_rule_resume,
))

register(ActionDefinition(
    action_type="share.cap_raise",
    required_permission_key=_KEY,
    summary_label="Raise authorized share cap",
    approver_set_resolver=_default_approver_set(_KEY),
    payload_validator=_validate_cap_raise,
    executor=_exec_cap_raise,
    preview_builder=_preview_cap_raise,
))

# 49a pattern — weakening the issuance mode routes through the mode being
# weakened; approver set is any admin/steward so the constrained party can't
# shrink its own ratifier set via the permission matrix first.
register(ActionDefinition(
    action_type="share.issuance_mode_weaken",
    required_permission_key=None,
    summary_label="Weaken issuance authorization",
    approver_set_resolver=_admins_of,
    payload_validator=_validate_issuance_mode_weaken,
    executor=_exec_issuance_mode_weaken,
    preview_builder=_preview_issuance_mode_weaken,
    admin_or_steward_only=True,
))
