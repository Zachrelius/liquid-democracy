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

from pydantic import BaseModel

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
# Phase 51 — Guarded verification-state backdoor (platform-admin only)
# ---------------------------------------------------------------------------
#
# So the state model + (Phase 52) enforcement can be tested before a
# real Persona integration exists, this endpoint sets a user's
# verification record. It is platform-admin only — verification is a
# platform-level trust primitive, not an org-delegable one. The
# provenance is stamped as ``backdoor`` so any future-phase code that
# distinguishes real-from-stub verifications (enforcement, billing,
# audit surfaces) treats this record as the ops override path the
# spec calls out as "not throwaway."

class _VerificationStateBody(BaseModel):
    state: str
    jurisdiction: Optional[str] = None


@router.post(
    "/users/{user_id}/verification-state",
    response_model=schemas.UserOut,
)
def set_user_verification_state(
    user_id: str,
    body: _VerificationStateBody,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_admin),
):
    """Phase 51 §6 — set ``users.verification_state`` (and optionally
    ``verification_jurisdiction``) for a target user with provenance
    ``backdoor``.

    Validates:
      * ``state`` is one of ``verification.ORDER``.
      * Jurisdiction-presence consistency: a state at
        ``address_on_id`` or higher requires a non-empty
        ``jurisdiction``; lower states must NOT carry one (we ignore +
        clear any leftover jurisdiction so the row stays consistent
        with the state's claim).

    Sets ``verification_updated_at = now`` and audits via the standard
    ``AuditLog`` pattern (action ``user.verification_state_set``).
    Phase 52's Persona integration will share this endpoint's
    response-shape + audit semantics; the backdoor itself persists
    as the platform-admin / ops override path.
    """
    from verification import (
        VALID_STATES, ORDER, jurisdiction_required_for,
        ADDRESS_ON_ID,
    )
    from datetime import datetime, timezone

    if body.state not in VALID_STATES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown verification state {body.state!r}. "
                f"Allowed: {list(ORDER)}."
            ),
        )
    jurisdiction = body.jurisdiction.strip() if isinstance(body.jurisdiction, str) else None
    if jurisdiction == "":
        jurisdiction = None
    if jurisdiction_required_for(body.state) and not jurisdiction:
        raise HTTPException(
            status_code=400,
            detail=(
                f"State {body.state!r} requires a non-empty "
                "jurisdiction (e.g. a US state code)."
            ),
        )
    if not jurisdiction_required_for(body.state) and jurisdiction:
        # A lower-tier state doesn't carry a jurisdiction claim. Drop
        # the input so the persisted row stays consistent (instead
        # of silently storing a misleading value).
        jurisdiction = None

    user = db.get(models.User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    old_state = user.verification_state
    old_provenance = user.verification_provenance
    old_jurisdiction = user.verification_jurisdiction

    user.verification_state = body.state
    user.verification_jurisdiction = jurisdiction
    # Phase 52a — the backdoor stamps ``backdoor`` provenance, not
    # ``demo_stub``. The C-DEMO tightening (verification.
    # ensure_demo_stub_writable) gates only ``demo_stub`` writes and
    # is enforced at the seed-pipeline + any demo_stub setter; the
    # platform-admin backdoor is unaffected.
    user.verification_provenance = "backdoor"
    user.verification_updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

    log_audit_event(
        db,
        action="user.verification_state_set",
        target_type="user",
        target_id=user.id,
        actor_id=current_user.id,
        details={
            "username": user.username,
            "old_state": old_state,
            "new_state": body.state,
            "old_provenance": old_provenance,
            "new_provenance": "backdoor",
            "old_jurisdiction": old_jurisdiction,
            "new_jurisdiction": jurisdiction,
        },
        ip_address=request.client.host if request.client else None,
    )

    db.commit()
    db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Phase 9.5 — Platform settings + per-user org-creation-limit override
# ---------------------------------------------------------------------------

@router.post("/monitoring/test-alert")
async def send_monitoring_test_alert(
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_admin),
) -> dict:
    """Send one safe operational test message to alert recipients.

    No incident state is opened and recipient addresses are not returned.
    The audit row records only the recipient count and delivery outcome.
    """
    from ops_monitoring import send_test_alert

    delivered, recipient_count = await send_test_alert(db)
    log_audit_event(
        db,
        action="ops.monitoring_test_alert",
        target_type="platform",
        target_id="production-monitoring",
        actor_id=current_user.id,
        details={
            "recipient_count": recipient_count,
            "delivered": delivered,
        },
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    if recipient_count == 0:
        raise HTTPException(
            status_code=409,
            detail="No active verified platform-admin alert recipient is configured.",
        )
    if not delivered:
        raise HTTPException(
            status_code=502,
            detail="Monitoring test alert delivery failed. Check the email provider logs.",
        )
    return {"delivered": True, "recipient_count": recipient_count}

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

    # Phase 60 Bucket 4 — REAL BUG fix. The endpoint declared
    # response_model=AuditLogOut but had no return statement, so it
    # implicitly returned None, failing Pydantic validation and 500'ing
    # in production for every admin that hit this elevated-audit
    # surface. The fix returns the UNREDACTED entry (this is the
    # elevated endpoint — its whole point is to bypass the
    # `_redact_audit_entry` applied on the list view). The elevation
    # itself was already audited above; this return makes the surface
    # actually usable.
    return schemas.AuditLogOut(
        id=entry.id,
        timestamp=entry.timestamp,
        actor_id=entry.actor_id,
        action=entry.action,
        target_type=entry.target_type,
        target_id=entry.target_id,
        details=entry.details,  # NOT redacted — elevated view
        ip_address=entry.ip_address,
    )


# ---------------------------------------------------------------------------
# Phase 45b B4 — Platform-admin backstop for needs_rebootstrap orgs
# ---------------------------------------------------------------------------

from pydantic import BaseModel as _BaseModel


class _RebootstrapBody(_BaseModel):
    """Phase 45b B4 — body for POST /api/admin/orgs/{slug}/rebootstrap.

    ``target_user_id`` must be a user (need not currently be a member of
    the org). ``target_role`` is the governance-tier role to assign:
    'steward' for single_steward mode, 'admin' for council mode. The
    target user gets an active OrgMembership at that role if they don't
    have one; if they do, their role is upgraded.
    """
    target_user_id: str
    target_role: str  # 'steward' or 'admin'


@router.post("/orgs/{org_slug}/rebootstrap")
def rebootstrap_org(
    org_slug: str,
    body: _RebootstrapBody,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_admin),
):
    """Phase 45b B4 — platform-admin backstop for orgs that have lost
    their last active governor (``count_active_governors == 0``). Seats
    the named user as Steward or Admin so the org can resume self-
    governance.

    Restricted to platform admins (``User.is_admin``). The org must
    actually be in the ``needs_rebootstrap`` condition — this endpoint
    rejects with 400 if there's already at least one active governor,
    to prevent a platform admin from bypassing in-org governance under
    the guise of recovery.
    """
    from governance import (
        at_risk_of_needs_rebootstrap, mode_of,
        SINGLE_STEWARD, ADMIN_COUNCIL,
    )

    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug,
    ).first()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    if not at_risk_of_needs_rebootstrap(db, org):
        raise HTTPException(
            status_code=400,
            detail=(
                "Org is not in the needs_rebootstrap condition; "
                "platform-admin re-seat is not authorized."
            ),
        )

    valid_roles = {"steward", "admin"}
    if body.target_role not in valid_roles:
        raise HTTPException(
            status_code=400,
            detail=f"target_role must be one of {sorted(valid_roles)}",
        )
    expected_role_for_mode = "admin" if mode_of(org) == ADMIN_COUNCIL else "steward"
    if body.target_role != expected_role_for_mode:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Org is in {mode_of(org)!r} mode; target_role must be "
                f"{expected_role_for_mode!r}"
            ),
        )

    target_user = db.get(models.User, body.target_user_id)
    if target_user is None:
        raise HTTPException(status_code=404, detail="Target user not found")
    if not target_user.is_active:
        raise HTTPException(
            status_code=400,
            detail="Target user's account must be active.",
        )

    role_row = db.query(models.Role).filter(
        models.Role.org_id == org.id,
        models.Role.system_key == body.target_role,
    ).first()
    if role_row is None:
        raise HTTPException(
            status_code=500,
            detail=f"Org is missing the preset {body.target_role!r} role",
        )

    membership = db.query(models.OrgMembership).filter(
        models.OrgMembership.org_id == org.id,
        models.OrgMembership.user_id == body.target_user_id,
    ).first()
    if membership is None:
        membership = models.OrgMembership(
            user_id=body.target_user_id,
            org_id=org.id,
            role_id=role_row.id,
            status="active",
        )
        db.add(membership)
    else:
        membership.status = "active"
        membership.role_id = role_row.id

    log_audit_event(
        db,
        action="org.rebootstrapped",
        target_type="organization",
        target_id=org.id,
        actor_id=current_user.id,
        details={
            "target_user_id": body.target_user_id,
            "target_role": body.target_role,
            "governance_mode": mode_of(org),
            "platform_admin_override": True,
        },
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return {
        "status": "ok",
        "target_user_id": body.target_user_id,
        "target_role": body.target_role,
        "mode": mode_of(org),
    }

    return schemas.AuditLogOut.model_validate(entry, from_attributes=True)


# ---------------------------------------------------------------------------
# Phase 87 (B-10) — platform-admin org takedown
# ---------------------------------------------------------------------------

@router.get("/orgs", response_model=list[schemas.AdminOrgOut])
def list_all_orgs(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_admin),
):
    """Platform-admin org list for the takedown toolbench. All orgs
    (including restricted + demo), top-level and sub-orgs."""
    from sqlalchemy import func as _func
    counts = dict(
        db.query(
            models.OrgMembership.org_id,
            _func.count(models.OrgMembership.id),
        )
        .filter(models.OrgMembership.status == "active")
        .group_by(models.OrgMembership.org_id)
        .all()
    )
    orgs = db.query(models.Organization).order_by(models.Organization.name).all()
    return [
        schemas.AdminOrgOut(
            id=o.id,
            name=o.name,
            slug=o.slug,
            member_count=int(counts.get(o.id, 0)),
            discoverability=o.discoverability or "listed",
            activity_visibility=o.activity_visibility or "members_only",
            platform_restriction=o.platform_restriction,
            restriction_reason=o.restriction_reason,
            is_demo=bool(o.is_demo),
            parent_org_id=o.parent_org_id,
            created_at=o.created_at,
        )
        for o in orgs
    ]


@router.patch("/orgs/{org_id}/restriction", response_model=schemas.AdminOrgOut)
def set_org_restriction(
    org_id: str,
    body: schemas.AdminOrgRestrictionIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_admin),
):
    """Set or clear an org's platform restriction (delisted / suspended /
    none). ``reason`` is REQUIRED when restricting. Demo orgs cannot be
    restricted (422). Enforcement is read-time (org settings untouched);
    reverting restores the prior public posture. Audited."""
    from org_restriction import VALID_RESTRICTIONS
    from datetime import timezone

    org = db.get(models.Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    # Normalize: 'none'/'' → clear.
    new_restriction = body.restriction
    if new_restriction in (None, "", "none"):
        new_restriction = None
    elif new_restriction not in VALID_RESTRICTIONS:
        raise HTTPException(
            status_code=422,
            detail=f"restriction must be one of {sorted(VALID_RESTRICTIONS)}, 'none', or null",
        )

    # Demo orgs are never restrictable — the nightly reset + demo login paths
    # aren't built to handle it.
    if bool(org.is_demo):
        raise HTTPException(
            status_code=422,
            detail="Demo organizations cannot be restricted.",
        )

    reason = (body.reason or "").strip() or None
    if new_restriction is not None and not reason:
        raise HTTPException(
            status_code=422,
            detail="A reason is required when restricting an organization.",
        )

    prior = org.platform_restriction
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    if new_restriction is None:
        # Revert — clear all restriction fields; audit trail is the history.
        org.platform_restriction = None
        org.restricted_at = None
        org.restricted_by_id = None
        org.restriction_reason = None
        log_audit_event(
            db,
            action="org.restriction_reverted",
            target_type="organization",
            target_id=org.id,
            actor_id=current_user.id,
            details={"prior_restriction": prior, "reason": reason},
            ip_address=request.client.host if request.client else None,
        )
    else:
        org.platform_restriction = new_restriction
        org.restricted_at = now
        org.restricted_by_id = current_user.id
        org.restriction_reason = reason
        log_audit_event(
            db,
            action="org.restriction_set",
            target_type="organization",
            target_id=org.id,
            actor_id=current_user.id,
            details={
                "restriction": new_restriction,
                "prior_restriction": prior,
                "reason": reason,
            },
            ip_address=request.client.host if request.client else None,
        )

    db.commit()
    db.refresh(org)

    member_count = (
        db.query(models.OrgMembership)
        .filter(
            models.OrgMembership.org_id == org.id,
            models.OrgMembership.status == "active",
        )
        .count()
    )
    return schemas.AdminOrgOut(
        id=org.id,
        name=org.name,
        slug=org.slug,
        member_count=member_count,
        discoverability=org.discoverability or "listed",
        activity_visibility=org.activity_visibility or "members_only",
        platform_restriction=org.platform_restriction,
        restriction_reason=org.restriction_reason,
        is_demo=bool(org.is_demo),
        parent_org_id=org.parent_org_id,
        created_at=org.created_at,
    )
