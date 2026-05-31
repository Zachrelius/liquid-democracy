"""Phase 44 — Action registry: maps wrapped action types to handlers.

Each wrapped action type has FIVE responsibilities tied to a single
``ActionDefinition``:

  1. ``required_permission_key`` — the permission key the actor needs
     to have initiated the action. The eligible-approver set is derived
     from this key (D5) UNLESS the action overrides ``approver_set``
     (used for ``org.delete`` per D5, which is steward-gated, not
     permission-gated).
  2. ``approver_set_resolver`` — given (db, org), return the set of
     User.id strings who can ratify this action. By default, holders
     of ``required_permission_key`` in this org.
  3. ``payload_validator`` — given (payload, db, org, actor), raise
     ``HTTPException`` on bad shape / missing target / unauthorized
     target. Runs at submit time + re-runs at execution.
  4. ``executor`` — given (db, action, actor_user), apply the actual
     mutation. Called from the ratification executor when the threshold
     is met, AND from the direct destruct path when approval is OFF.
     Must be idempotent against partial states only insofar as it
     refuses to execute on invalid state; never partially applies.
  5. ``preview_builder`` — given (action, db), return a structured
     human-readable change description the frontend renders. For
     ``role_permissions.edit`` this is the per-role before→after diff
     of only the changed cells.

Action types live in a private ``_REGISTRY`` dict; callers go through
``get_action_definition(action_type)`` which raises 400 on unknown
types.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

import models
from permission_registry import PERMISSION_REGISTRY


# Type aliases for readability.
ApproverSetResolver = Callable[[Session, models.Organization], set[str]]
PayloadValidator = Callable[[dict, Session, models.Organization, models.User], None]
Executor = Callable[[Session, "models.PendingAdminAction", models.User], None]
PreviewBuilder = Callable[["models.PendingAdminAction", Session], dict[str, Any]]


@dataclass(frozen=True)
class ActionDefinition:
    action_type: str
    required_permission_key: Optional[str]  # None for org.delete (steward-only)
    summary_label: str  # human-readable noun-phrase for the action type
    approver_set_resolver: ApproverSetResolver
    payload_validator: PayloadValidator
    executor: Executor
    preview_builder: PreviewBuilder
    # Steward-only flag: action requires steward role rather than a
    # permission key. Used for org.delete per D5.
    steward_only: bool = False


_REGISTRY: dict[str, ActionDefinition] = {}


def register(definition: ActionDefinition) -> None:
    _REGISTRY[definition.action_type] = definition


def is_known_action_type(action_type: str) -> bool:
    return action_type in _REGISTRY


def get_action_definition(action_type: str) -> ActionDefinition:
    d = _REGISTRY.get(action_type)
    if d is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown action type: {action_type!r}",
        )
    return d


def known_action_types() -> list[str]:
    return list(_REGISTRY.keys())


# ---------------------------------------------------------------------------
# Approver-set resolvers
# ---------------------------------------------------------------------------

def _users_with_permission(
    db: Session, org: models.Organization, permission_key: str,
) -> set[str]:
    """Return active members of ``org`` whose role grants
    ``permission_key`` per ``role_permissions``.

    Used for the default approver-set resolver. Stewards are included
    via the standard ``has_permission`` check; we call into it per-
    membership rather than reimplementing the resolution logic.
    """
    from role_permissions import has_permission

    memberships = (
        db.query(models.OrgMembership)
        .filter(
            models.OrgMembership.org_id == org.id,
            models.OrgMembership.status == "active",
        )
        .all()
    )
    out: set[str] = set()
    for m in memberships:
        if has_permission(db, m.user_id, org.id, permission_key):
            out.add(m.user_id)
    return out


def _stewards_of(db: Session, org: models.Organization) -> set[str]:
    """Return user_ids of active members whose role.system_key=='steward'.

    Used for ``org.delete``'s approver set per D5: org-delete is steward-
    gated, not permission-gated, so the approver set is the steward(s)
    rather than the holders of any permission.
    """
    memberships = (
        db.query(models.OrgMembership)
        .filter(
            models.OrgMembership.org_id == org.id,
            models.OrgMembership.status == "active",
        )
        .all()
    )
    out: set[str] = set()
    for m in memberships:
        if m.role_id is None:
            continue
        role = db.get(models.Role, m.role_id)
        if role is not None and role.system_key == "steward":
            out.add(m.user_id)
    return out


def _default_approver_set(permission_key: str) -> ApproverSetResolver:
    def _resolve(db: Session, org: models.Organization) -> set[str]:
        return _users_with_permission(db, org, permission_key)
    return _resolve


# ---------------------------------------------------------------------------
# Payload validators
# ---------------------------------------------------------------------------

def _require_str(payload: dict, key: str) -> str:
    v = payload.get(key)
    if not isinstance(v, str) or not v.strip():
        raise HTTPException(
            status_code=400,
            detail=f"Missing or invalid field {key!r} in pending-action payload",
        )
    return v


def _validate_member_remove(
    payload: dict, db: Session, org: models.Organization, actor: models.User,
) -> None:
    target_user_id = _require_str(payload, "target_user_id")
    target_user = db.get(models.User, target_user_id)
    if target_user is None:
        raise HTTPException(status_code=404, detail="Target user not found")
    membership = (
        db.query(models.OrgMembership)
        .filter(
            models.OrgMembership.org_id == org.id,
            models.OrgMembership.user_id == target_user_id,
        )
        .first()
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Target is not a member of this org")
    # Steward cannot be removed (mirrors the live direct path).
    if membership.role_id is not None:
        role = db.get(models.Role, membership.role_id)
        if role is not None and role.system_key == "steward":
            raise HTTPException(status_code=400, detail="Cannot remove the Steward")


def _validate_topic_delete(
    payload: dict, db: Session, org: models.Organization, actor: models.User,
) -> None:
    topic_id = _require_str(payload, "topic_id")
    topic = db.get(models.Topic, topic_id)
    if topic is None or topic.org_id != org.id:
        raise HTTPException(status_code=404, detail="Topic not found in this organization")


def _validate_role_permissions_edit(
    payload: dict, db: Session, org: models.Organization, actor: models.User,
) -> None:
    changes = payload.get("changes")
    if not isinstance(changes, list) or len(changes) == 0:
        raise HTTPException(
            status_code=400, detail="role_permissions.edit requires non-empty 'changes' list",
        )
    valid_keys = {p.key for p in PERMISSION_REGISTRY}
    valid_roles = {"steward", "admin", "moderator", "member"}
    for c in changes:
        if not isinstance(c, dict):
            raise HTTPException(status_code=400, detail="Invalid change entry")
        if c.get("permission_key") not in valid_keys:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown permission key: {c.get('permission_key')!r}",
            )
        if c.get("role_system_key") not in valid_roles:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown role: {c.get('role_system_key')!r}",
            )
        if not isinstance(c.get("enabled"), bool):
            raise HTTPException(
                status_code=400, detail="Each change must have a boolean 'enabled'",
            )
    baseline = payload.get("baseline")
    if not isinstance(baseline, dict):
        raise HTTPException(
            status_code=400,
            detail="role_permissions.edit requires a 'baseline' snapshot of the matrix at submit time",
        )


def _validate_org_delete(
    payload: dict, db: Session, org: models.Organization, actor: models.User,
) -> None:
    # Confirmation token is the org slug — the FE asks the user to type
    # the slug, matching the live destructive-delete pattern.
    confirmation = payload.get("confirmation")
    if not isinstance(confirmation, str) or confirmation.strip() != org.slug:
        raise HTTPException(
            status_code=400,
            detail="org.delete requires 'confirmation' to equal the org slug",
        )


# ---------------------------------------------------------------------------
# Executors — shared callables called by both the direct path (approval
# off) and the ratification executor (approval on).
# ---------------------------------------------------------------------------

def execute_member_remove(
    db: Session, org: models.Organization, target_user_id: str,
) -> None:
    """Hard-delete the OrgMembership row. Mirrors the live direct path
    at ``routes/organizations.py::remove_member``. Caller is responsible
    for permission + steward-protection checks BEFORE calling this; this
    function only enforces the not-the-steward guard as a final safety.
    """
    m = (
        db.query(models.OrgMembership)
        .filter(
            models.OrgMembership.org_id == org.id,
            models.OrgMembership.user_id == target_user_id,
        )
        .first()
    )
    if m is None:
        raise HTTPException(status_code=404, detail="Member not found")
    if m.role_id is not None:
        role = db.get(models.Role, m.role_id)
        if role is not None and role.system_key == "steward":
            raise HTTPException(status_code=400, detail="Cannot remove the Steward")
    db.delete(m)


def execute_topic_delete(
    db: Session, org: models.Organization, topic_id: str,
) -> None:
    """Soft-delete a topic by clearing its org_id (mirrors direct path)."""
    topic = (
        db.query(models.Topic)
        .filter(
            models.Topic.id == topic_id,
            models.Topic.org_id == org.id,
        )
        .first()
    )
    if topic is None:
        raise HTTPException(
            status_code=404, detail="Topic not found in this organization",
        )
    topic.org_id = None


def execute_org_delete(db: Session, org: models.Organization) -> None:
    db.delete(org)


def execute_role_permissions_edit(
    db: Session, org: models.Organization, changes: list[dict], actor_id: str,
) -> int:
    """Apply a list of permission-matrix changes. Mirrors
    ``patch_role_permissions``'s apply loop without the HTTP wrapper.

    Returns the number of cells changed (callers may want to log/return).
    Raises HTTPException on invalid changes (e.g. unknown role/key).
    """
    from role_permissions import is_locked

    valid_keys = {p.key for p in PERMISSION_REGISTRY}
    valid_roles = {"steward", "admin", "moderator", "member"}
    roles_by_key: dict[str, models.Role] = {
        r.system_key: r for r in (
            db.query(models.Role)
            .filter(
                models.Role.org_id == org.id,
                models.Role.system_key.in_(valid_roles),
            )
            .all()
        )
    }

    applied = 0
    for c in changes:
        permission_key = c["permission_key"]
        role_system_key = c["role_system_key"]
        new_enabled = bool(c["enabled"])

        if is_locked(role_system_key, permission_key):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Cannot change '{permission_key}' for the Steward "
                    "role: this permission is locked."
                ),
            )
        if permission_key not in valid_keys:
            raise HTTPException(status_code=400, detail=f"Unknown permission key: {permission_key!r}")
        if role_system_key not in valid_roles:
            raise HTTPException(status_code=400, detail=f"Unknown role: {role_system_key!r}")
        role = roles_by_key.get(role_system_key)
        if role is None:
            raise HTTPException(
                status_code=500,
                detail=f"Org is missing the preset role {role_system_key!r}",
            )
        rp_row = (
            db.query(models.RolePermission)
            .filter(
                models.RolePermission.role_id == role.id,
                models.RolePermission.permission_key == permission_key,
            )
            .first()
        )
        if rp_row is None:
            if new_enabled:
                db.add(
                    models.RolePermission(
                        role_id=role.id,
                        permission_key=permission_key,
                        enabled=True,
                    )
                )
                applied += 1
        else:
            if bool(rp_row.enabled) != new_enabled:
                rp_row.enabled = new_enabled
                applied += 1
    db.info.pop("_permission_cache", None)
    return applied


# ---------------------------------------------------------------------------
# Executor wrappers expected by the registry signature
# ---------------------------------------------------------------------------

def _exec_member_remove(
    db: Session, action: "models.PendingAdminAction", actor_user: models.User,
) -> None:
    target_user_id = action.payload["target_user_id"]
    org = db.get(models.Organization, action.org_id)
    execute_member_remove(db, org, target_user_id)


def _exec_topic_delete(
    db: Session, action: "models.PendingAdminAction", actor_user: models.User,
) -> None:
    topic_id = action.payload["topic_id"]
    org = db.get(models.Organization, action.org_id)
    execute_topic_delete(db, org, topic_id)


def _exec_role_permissions_edit(
    db: Session, action: "models.PendingAdminAction", actor_user: models.User,
) -> None:
    """Re-validates against baseline drift (D11b + D7).

    If the current matrix no longer matches the baseline captured at
    submit time, raise — the calling engine resolves status=failed and
    the action's audit trail records the drift.
    """
    org = db.get(models.Organization, action.org_id)
    baseline = action.payload.get("baseline") or {}
    current_matrix = _read_current_matrix(db, org)
    if not _baselines_match(baseline, current_matrix):
        raise HTTPException(
            status_code=409,
            detail=(
                "Permissions have changed since this action was proposed; "
                "re-review."
            ),
        )
    execute_role_permissions_edit(db, org, action.payload["changes"], actor_user.id)


def _exec_org_delete(
    db: Session, action: "models.PendingAdminAction", actor_user: models.User,
) -> None:
    org = db.get(models.Organization, action.org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    execute_org_delete(db, org)


# ---------------------------------------------------------------------------
# Preview builders — structured human-readable change descriptions.
# Frontend uses ``label`` + ``summary`` + (optional) ``diff`` + ``drift``.
# ---------------------------------------------------------------------------

def _preview_member_remove(
    action: "models.PendingAdminAction", db: Session,
) -> dict[str, Any]:
    target = db.get(models.User, action.payload.get("target_user_id"))
    target_name = target.display_name if target else "(unknown user)"
    reason = action.payload.get("reason") or ""
    return {
        "label": "Remove member",
        "summary": f"Remove {target_name} from the organization",
        "target": {
            "type": "user",
            "id": action.payload.get("target_user_id"),
            "display_name": target_name,
        },
        "reason": reason,
    }


def _preview_topic_delete(
    action: "models.PendingAdminAction", db: Session,
) -> dict[str, Any]:
    topic_id = action.payload.get("topic_id")
    topic = db.get(models.Topic, topic_id) if isinstance(topic_id, str) else None
    topic_name = topic.name if topic else "(unknown topic)"
    # Count of proposals tagged with this topic (impact preview).
    impact_count = 0
    if topic is not None:
        impact_count = (
            db.query(models.ProposalTopic)
            .filter(models.ProposalTopic.topic_id == topic.id)
            .count()
        )
    return {
        "label": "Delete topic",
        "summary": f"Delete topic \"{topic_name}\"",
        "target": {"type": "topic", "id": topic_id, "name": topic_name},
        "impact": {"proposals_tagged": impact_count},
    }


def _preview_role_permissions_edit(
    action: "models.PendingAdminAction", db: Session,
) -> dict[str, Any]:
    """Build per-role before→after diff of only changed cells.

    Plus a drift flag: True iff the live matrix no longer matches the
    captured baseline — surfaced in the ratify UI as a warning so
    approvers know the diff may have stale assumptions.
    """
    org = db.get(models.Organization, action.org_id)
    changes = action.payload.get("changes", [])
    baseline = action.payload.get("baseline", {})
    current = _read_current_matrix(db, org) if org else {}

    perm_labels = {p.key: p.label for p in PERMISSION_REGISTRY}

    diff_by_role: dict[str, list[dict]] = {}
    for c in changes:
        role_key = c.get("role_system_key")
        perm_key = c.get("permission_key")
        new_enabled = bool(c.get("enabled"))
        baseline_enabled = (
            baseline.get(role_key, {}).get(perm_key, False)
            if isinstance(baseline.get(role_key), dict) else False
        )
        diff_by_role.setdefault(role_key, []).append({
            "permission_key": perm_key,
            "permission_label": perm_labels.get(perm_key, perm_key),
            "from": bool(baseline_enabled),
            "to": new_enabled,
        })

    drift = not _baselines_match(baseline, current)

    return {
        "label": "Edit role permissions",
        "summary": (
            f"Change {sum(len(v) for v in diff_by_role.values())} "
            "permission cell(s) across "
            f"{len(diff_by_role)} role(s)"
        ),
        "diff_by_role": diff_by_role,
        "drift": drift,
    }


def _preview_org_delete(
    action: "models.PendingAdminAction", db: Session,
) -> dict[str, Any]:
    org = db.get(models.Organization, action.org_id)
    name = org.name if org else "(unknown org)"
    return {
        "label": "Delete organization",
        "summary": (
            f"Permanently delete the entire organization \"{name}\" "
            "and all its data"
        ),
        "destructive": "high",
        "target": {"type": "organization", "id": action.org_id, "name": name},
    }


# ---------------------------------------------------------------------------
# Matrix snapshot + baseline-drift helpers
# ---------------------------------------------------------------------------

def _read_current_matrix(
    db: Session, org: models.Organization,
) -> dict[str, dict[str, bool]]:
    """Snapshot the org's current role_permissions matrix as
    ``{role_system_key: {permission_key: bool}}``.

    Same shape submit-time baselines should be captured in.
    """
    out: dict[str, dict[str, bool]] = {}
    roles = (
        db.query(models.Role)
        .filter(models.Role.org_id == org.id)
        .all()
    )
    for role in roles:
        rows = (
            db.query(models.RolePermission)
            .filter(models.RolePermission.role_id == role.id)
            .all()
        )
        out[role.system_key] = {r.permission_key: bool(r.enabled) for r in rows}
    return out


def _baselines_match(baseline: dict, current: dict) -> bool:
    """Compare two matrix snapshots. Missing role→perm pairs are
    treated as False (the "default-off" representation).
    """
    if not isinstance(baseline, dict) or not isinstance(current, dict):
        return False
    all_roles = set(baseline.keys()) | set(current.keys())
    for role in all_roles:
        b = baseline.get(role, {}) if isinstance(baseline.get(role), dict) else {}
        c = current.get(role, {}) if isinstance(current.get(role), dict) else {}
        all_keys = set(b.keys()) | set(c.keys())
        for k in all_keys:
            if bool(b.get(k, False)) != bool(c.get(k, False)):
                return False
    return True


def capture_baseline(db: Session, org: models.Organization) -> dict[str, dict[str, bool]]:
    """Public helper for callers (submit endpoint) to capture the
    current matrix snapshot to embed in a role_permissions.edit
    payload."""
    return _read_current_matrix(db, org)


# ---------------------------------------------------------------------------
# Register the four wrapped actions
# ---------------------------------------------------------------------------

register(ActionDefinition(
    action_type="member.remove",
    required_permission_key="member.remove",
    summary_label="Remove member",
    approver_set_resolver=_default_approver_set("member.remove"),
    payload_validator=_validate_member_remove,
    executor=_exec_member_remove,
    preview_builder=_preview_member_remove,
))

register(ActionDefinition(
    action_type="topic.delete",
    required_permission_key="topic.delete",
    summary_label="Delete topic",
    approver_set_resolver=_default_approver_set("topic.delete"),
    payload_validator=_validate_topic_delete,
    executor=_exec_topic_delete,
    preview_builder=_preview_topic_delete,
))

register(ActionDefinition(
    action_type="role_permissions.edit",
    required_permission_key="role_permissions.edit",
    summary_label="Edit role permissions",
    approver_set_resolver=_default_approver_set("role_permissions.edit"),
    payload_validator=_validate_role_permissions_edit,
    executor=_exec_role_permissions_edit,
    preview_builder=_preview_role_permissions_edit,
))

register(ActionDefinition(
    action_type="org.delete",
    required_permission_key=None,
    summary_label="Delete organization",
    approver_set_resolver=_stewards_of,
    payload_validator=_validate_org_delete,
    executor=_exec_org_delete,
    preview_builder=_preview_org_delete,
    steward_only=True,
))
