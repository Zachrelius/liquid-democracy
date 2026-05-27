"""
Platform-admin endpoints. Every route in this module is gated by
`Depends(auth_utils.get_current_admin)` (or stricter in debug-only cases).

Endpoints:
  POST /api/admin/seed                - debug only, public seed loader
  POST /api/admin/time-simulation     - debug only, snapshot tool
  GET  /api/admin/delegation-graph    - system-wide delegation graph (audited)
  GET  /api/admin/users               - system user list (audited)
  PATCH /api/admin/users/{id}/make-admin - grant the role to a user
  GET  /api/admin/audit               - audit log viewer (ballots redacted)
  GET  /api/admin/audit/ballots/{id}  - elevated single-entry view
                                        (self-logs with required reason)

See `backend/auth.py:get_current_admin` for the role definition and
`SECURITY_REVIEW.md` (Privileged Access Tiers) for the full boundary.
"""
from copy import deepcopy
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

import auth as auth_utils
import models
import schemas
from audit_utils import log_audit_event
from database import get_db
from delegation_engine import engine as delegation_engine
from settings import settings

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Audit log redaction
# ---------------------------------------------------------------------------
#
# Per-action allowlist of fields whose values should be replaced with the
# string "<redacted>" when serializing audit log entries via the default
# `GET /api/admin/audit` endpoint. The unredacted values remain in the
# database; the redaction happens at response time.
#
# Extending: add a new action key with a list of detail-field names.
REDACTED_DETAIL_FIELDS: dict[str, list[str]] = {
    "vote.cast": ["vote_value", "ballot", "previous_value"],
    "vote.retracted": ["previous_value", "ballot", "previous_ballot"],
}


def _redact_audit_entry(entry: models.AuditLog) -> Optional[dict[str, Any]]:
    """
    Return a redacted copy of `entry.details` per `REDACTED_DETAIL_FIELDS`.

    - If the action has no redaction rules, returns a deep copy of the
      original details (or None if details is None/empty).
    - For each field in the allowlist that appears in details, replaces its
      value with "<redacted>" and adds the field name to the
      `_redacted_fields` array.
    - The `_redacted_fields` key is only set when at least one field was
      actually redacted, so unredacted entries don't grow a noisy empty key.
    - Never mutates the underlying ORM row.
    """
    raw = entry.details
    if raw is None:
        return None
    details = deepcopy(raw)

    allowlist = REDACTED_DETAIL_FIELDS.get(entry.action)
    if not allowlist:
        return details

    redacted: list[str] = []
    for field in allowlist:
        if field in details:
            details[field] = "<redacted>"
            redacted.append(field)

    if redacted:
        details["_redacted_fields"] = redacted

    return details


@router.post("/seed", status_code=200)
def seed_demo(
    body: schemas.SeedRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_admin),
):
    """Admin-only endpoint — seeds demo data. Only available in debug mode.

    Phase 37 B4 (2026-05-27): added Depends(get_current_admin) to match the
    /time-simulation pattern. Prior to this, only `settings.debug` gated the
    endpoint, so in any environment where DEBUG=true (including staging
    misconfig) an unauthenticated caller could trigger arbitrary seed
    scenarios that wipe or massively alter DB state.
    """
    if not settings.debug:
        raise HTTPException(
            status_code=403,
            detail="Seed endpoint is only available in debug mode.",
        )
    from seed_data import run_seed
    result = run_seed(db, scenario=body.scenario)
    return result or {"message": f"Scenario '{body.scenario}' loaded. Log in as alice / demo1234."}


@router.post("/time-simulation", status_code=200)
def simulate_time(
    body: schemas.TimeSimulationRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_admin),
):
    """Take a tally snapshot for a proposal at the given simulated time. Debug only."""
    if not settings.debug:
        raise HTTPException(
            status_code=403,
            detail="Time simulation endpoint is only available in debug mode.",
        )
    proposal = db.get(models.Proposal, body.proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    tally = delegation_engine.compute_tally(proposal, db)
    snapshot = models.VoteSnapshot(
        proposal_id=proposal.id,
        simulated_time=body.simulated_time,
        yes_count=tally.yes,
        no_count=tally.no,
        abstain_count=tally.abstain,
        not_cast_count=tally.not_cast,
        total_eligible=tally.total_eligible,
    )
    db.add(snapshot)
    db.commit()
    return {"detail": "Snapshot recorded", "yes": tally.yes, "no": tally.no}


@router.get("/delegation-graph", response_model=schemas.DelegationGraph)
def system_delegation_graph_all_orgs(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_admin),
):
    """System-wide delegation graph (cross-org union) for the admin panel.

    Phase 18: renamed from ``system_delegation_graph`` to make the
    cross-org behavior explicit. Admins see the union of every org's
    delegations for forensic work; for org-focused admin work use the
    sibling :func:`org_scoped_delegation_graph` endpoint at
    ``/api/admin/orgs/{slug}/delegation_graph`` which scopes to one org.

    The HTTP path stays at ``/api/admin/delegation-graph`` to avoid
    breaking the existing admin frontend; only the Python function name
    changes. Access is audited.

    Voting weights here are computed via
    ``graph_store.compute_voting_weight_all_orgs`` so the rendered weight
    reflects the cross-org union the admin is looking at, matching the
    cross-org edges in the same payload.
    """
    from delegation_engine import graph_store

    all_delegations: list[models.Delegation] = db.query(models.Delegation).all()

    node_ids: set[str] = set()
    edges = []
    for d in all_delegations:
        node_ids.add(d.delegator_id)
        node_ids.add(d.delegate_id)
        topic_name = d.topic.name if d.topic else None
        edges.append(
            schemas.GraphEdge(
                source=d.delegator_id,
                target=d.delegate_id,
                topic_id=d.topic_id,
                topic_name=topic_name,
                chain_behavior=d.chain_behavior,
            )
        )

    nodes = []
    for uid in node_ids:
        user = db.get(models.User, uid)
        if user:
            nodes.append(
                schemas.GraphNode(
                    id=uid,
                    display_name=user.display_name,
                    username=user.username,
                    weight=graph_store.compute_voting_weight_all_orgs(uid),
                    avatar_url=user.avatar_url,
                )
            )

    log_audit_event(
        db,
        action="admin.delegation_graph_viewed",
        target_type="system",
        target_id="system_delegation_graph_all_orgs",
        actor_id=current_user.id,
        details={"node_count": len(nodes), "edge_count": len(edges)},
        ip_address=request.client.host if request.client else None,
    )
    db.commit()

    return schemas.DelegationGraph(nodes=nodes, edges=edges)


@router.get(
    "/orgs/{org_slug}/delegation_graph",
    response_model=schemas.DelegationGraph,
)
def org_scoped_delegation_graph(
    org_slug: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_admin),
):
    """Org-scoped delegation graph for admin work focused on a single org.

    Phase 18 (B2.2 / spec line 118): companion to
    ``system_delegation_graph_all_orgs``. Returns only delegations whose
    ``org_id`` matches the named org. Voting weights are computed within
    that org's partition so they're consistent with the rendered edges.
    Access is audited.
    """
    from delegation_engine import graph_store

    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug
    ).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    org_delegations: list[models.Delegation] = db.query(models.Delegation).filter(
        models.Delegation.org_id == org.id,
    ).all()

    node_ids: set[str] = set()
    edges = []
    for d in org_delegations:
        node_ids.add(d.delegator_id)
        node_ids.add(d.delegate_id)
        topic_name = d.topic.name if d.topic else None
        edges.append(
            schemas.GraphEdge(
                source=d.delegator_id,
                target=d.delegate_id,
                topic_id=d.topic_id,
                topic_name=topic_name,
                chain_behavior=d.chain_behavior,
            )
        )

    nodes = []
    for uid in node_ids:
        user = db.get(models.User, uid)
        if user:
            nodes.append(
                schemas.GraphNode(
                    id=uid,
                    display_name=user.display_name,
                    username=user.username,
                    weight=graph_store.compute_voting_weight(uid, org_id=org.id),
                    avatar_url=user.avatar_url,
                )
            )

    log_audit_event(
        db,
        action="admin.delegation_graph_viewed",
        target_type="organization",
        target_id=org.id,
        actor_id=current_user.id,
        details={
            "scope": "org",
            "org_slug": org_slug,
            "node_count": len(nodes),
            "edge_count": len(edges),
        },
        ip_address=request.client.host if request.client else None,
    )
    db.commit()

    return schemas.DelegationGraph(nodes=nodes, edges=edges)


@router.get("/users", response_model=list[schemas.UserOut])
def list_users(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_admin),
):
    """System-wide user list for the admin panel. Access is audited.

    Phase 40 B6.3 (2026-05-27) — added pagination via ``limit`` / ``offset``
    query params matching the ``/api/admin/audit`` shape. Default 50,
    max 500. Pre-fix this endpoint returned ALL users in one response —
    fine at v1 scale but unbounded. Total user count goes to the audit
    log (and an `X-Total-Count` response header would be a future
    addition if the admin UI needs it for "showing N of M" UX).
    """
    total = db.query(models.User).count()
    users = (
        db.query(models.User)
        .order_by(models.User.username)
        .offset(offset)
        .limit(limit)
        .all()
    )
    log_audit_event(
        db,
        action="admin.user_list_viewed",
        target_type="system",
        target_id="system_user_list",
        actor_id=current_user.id,
        details={
            "user_count": len(users),
            "total_user_count": total,
            "limit": limit,
            "offset": offset,
        },
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return users


@router.patch("/users/{user_id}/make-admin", response_model=schemas.UserOut)
def make_admin(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_admin),
):
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    was_admin = user.is_admin
    user.is_admin = True
    # Phase 40 B6.2 (2026-05-27) — audit-log the promotion. Pre-fix this
    # endpoint mutated a high-privilege flag with no record. Matches the
    # patch_user_org_creation_limit pattern below.
    log_audit_event(
        db,
        action="user.made_admin",
        target_type="user",
        target_id=user.id,
        actor_id=current_user.id,
        details={
            "username": user.username,
            "promoted_by": current_user.username,
            "was_already_admin": was_admin,
        },
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Phase 9.5 — Platform settings + per-user org-creation-limit override
# ---------------------------------------------------------------------------

@router.get("/platform-settings")
def get_platform_settings(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_admin),
) -> dict:
    """Return all platform_settings rows as a `{key: value}` dict.

    Phase 9.5 — used by the future monitoring dashboard. Today the only
    seeded key is `org_creation_mode` (`'open'` by default; flippable to
    `'approval_required'` for the manual kill switch).
    """
    rows = db.query(models.PlatformSetting).all()
    return {r.key: r.value for r in rows}


@router.patch("/platform-settings")
def patch_platform_settings(
    body: schemas.PlatformSettingPatch,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_admin),
) -> dict:
    """Upsert one platform_settings row by key.

    Phase 9.5 — body shape `{key, value}`. Audited as
    `platform_settings.changed` with `{key, old_value, new_value}`.
    """
    row = db.get(models.PlatformSetting, body.key)
    old_value = row.value if row else None
    if row is None:
        row = models.PlatformSetting(key=body.key, value=body.value)
        db.add(row)
    else:
        row.value = body.value

    log_audit_event(
        db,
        action="platform_settings.changed",
        target_type="platform_setting",
        target_id=body.key,
        actor_id=current_user.id,
        details={
            "key": body.key,
            "old_value": old_value,
            "new_value": body.value,
        },
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return {"key": body.key, "value": body.value}


@router.patch("/users/{user_id}/org-creation-limit", response_model=schemas.UserOut)
def patch_user_org_creation_limit(
    user_id: str,
    body: schemas.OrgCreationLimitPatch,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_admin),
):
    """Set (or clear) a user's org_creation_limit override.

    Phase 9.5 — `limit: int | null`. Null restores the platform default of
    3. Audited as `user.org_creation_limit_changed` with the target user
    plus the old/new values for forensic context.
    """
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    old_value = user.org_creation_limit
    user.org_creation_limit = body.limit

    log_audit_event(
        db,
        action="user.org_creation_limit_changed",
        target_type="user",
        target_id=user.id,
        actor_id=current_user.id,
        details={
            "target_user_id": user.id,
            "old_value": old_value,
            "new_value": body.limit,
        },
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Phase 23 (D19) — demo reset manual trigger
# ---------------------------------------------------------------------------


@router.post("/demo/reset")
def trigger_demo_reset(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_admin),
) -> dict:
    """Phase 23 (D19) — admin-triggered immediate demo reset.

    Bypasses the schedule check (``force=True``) and runs the wipe+seed
    pipeline now. Returns the ``DemoResetResult`` shape as JSON. Audit log
    is emitted by ``run_demo_reset_if_due`` itself; no extra entry here.
    """
    from demo_reset_job import run_demo_reset_if_due

    result = run_demo_reset_if_due(db, force=True, actor_id=current_user.id)
    return {
        "success": result.success,
        "started_at": result.started_at.isoformat(),
        "completed_at": result.completed_at.isoformat(),
        "orgs_reset": result.orgs_reset,
        "rows_wiped": result.rows_wiped,
        "rows_seeded": result.rows_seeded,
        "error": result.error,
        "skipped": result.skipped,
        "reason": result.reason,
    }


@router.get("/audit", response_model=list[schemas.AuditLogOut])
def get_audit_log(
    action: Optional[str] = Query(None, description="Filter by action type, e.g. 'vote.cast'"),
    actor_id: Optional[str] = Query(None, description="Filter by actor user ID"),
    target_id: Optional[str] = Query(None, description="Filter by target entity ID"),
    since: Optional[datetime] = Query(None, description="Filter entries at or after this datetime (ISO 8601)"),
    until: Optional[datetime] = Query(None, description="Filter entries at or before this datetime (ISO 8601)"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_admin),
):
    """
    Paginated, filterable audit log viewer (admin only).
    Results are ordered newest-first. Ballot-content fields are redacted at
    response time per `REDACTED_DETAIL_FIELDS`. Use the elevated
    `/audit/ballots/{id}` endpoint with a reason to view unredacted content.
    """
    q = db.query(models.AuditLog)

    if action:
        q = q.filter(models.AuditLog.action == action)
    if actor_id:
        q = q.filter(models.AuditLog.actor_id == actor_id)
    if target_id:
        q = q.filter(models.AuditLog.target_id == target_id)
    if since:
        q = q.filter(models.AuditLog.timestamp >= since)
    if until:
        q = q.filter(models.AuditLog.timestamp <= until)

    rows = (
        q.order_by(models.AuditLog.timestamp.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return [
        schemas.AuditLogOut(
            id=r.id,
            timestamp=r.timestamp,
            actor_id=r.actor_id,
            action=r.action,
            target_type=r.target_type,
            target_id=r.target_id,
            details=_redact_audit_entry(r),
            ip_address=r.ip_address,
        )
        for r in rows
    ]


@router.get("/audit/ballots/{audit_log_id}", response_model=schemas.AuditLogOut)
def get_audit_ballot(
    audit_log_id: str,
    request: Request,
    reason: str = Query(..., min_length=1, max_length=500, description="Required justification for elevated access"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_admin),
):
    """
    Elevated single-entry audit viewer. Returns the unredacted entry for the
    given audit_log_id and self-logs the elevation as
    `admin.audit_ballot_viewed` with the requesting admin's id, IP, the
    target audit entry's action and original actor, and the supplied reason.
    """
    cleaned_reason = reason.strip()
    if not cleaned_reason:
        raise HTTPException(status_code=400, detail="reason cannot be empty")

    entry = db.get(models.AuditLog, audit_log_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Audit log entry not found")

    log_audit_event(
        db,
        action="admin.audit_ballot_viewed",
        target_type="audit_log",
        target_id=audit_log_id,
        actor_id=current_user.id,
        details={
            "reason": cleaned_reason,
            "viewed_action": entry.action,
            "viewed_actor_id": entry.actor_id,
        },
        ip_address=request.client.host if request.client else None,
    )
    db.commit()

    return schemas.AuditLogOut.model_validate(entry, from_attributes=True)
