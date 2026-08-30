"""Phase 9 Session 2 — Polis CRUD + xid + export endpoints.

Mirrors `routes/sub_organizations.py` style: APIRouter prefixed
``/api/orgs``, scope helpers from ``polis_engine``, permission helpers from
``permissions``, and the dual-path create dispatch documented in
``phase9_polis_api_findings.md``.

Why a new module: ``routes/organizations.py`` is already ~1600 lines and
mixes a lot of concerns. Polis CRUD is its own artifact family (parallel
to topics and proposals); putting it in its own router keeps Decision
6/7 enforcement and dual-path-create dispatch discoverable in one place.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from sqlalchemy import cast, exists, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session, load_only

import auth as auth_utils
import models
import polis_service
import schemas
from audit_utils import log_audit_event
from database import get_db
from notification_emit import emit_notification
from org_middleware import require_org_membership
from permissions import is_polis_admin, is_sub_org_admin
from polis_engine import eligible_viewers_for_polis
from role_permissions import has_permission
from settings import settings as app_settings


log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/orgs", tags=["polises"])


def _now() -> datetime:
    """Naive UTC — same convention as routes/sub_organizations.py."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parent_or_404(db: Session, org_slug: str) -> models.Organization:
    org = db.query(models.Organization).filter(
        models.Organization.slug == org_slug,
    ).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


def _polis_or_404(
    db: Session, org: models.Organization, polis_id: str,
) -> models.Polis:
    polis = db.query(models.Polis).filter(
        models.Polis.id == polis_id,
        models.Polis.org_id == org.id,
    ).first()
    if polis is None:
        raise HTTPException(status_code=404, detail="Polis not found")
    return polis


def _embed_url_for(polis: models.Polis) -> Optional[str]:
    """Compute the pol.is embed URL from the conversation_id.

    Returns None when the conversation_id isn't set yet (manual-fallback
    state where the operator hasn't pasted the slug). The frontend can
    treat None as "embed unavailable; conversation not yet linked".
    """
    if not polis.polis_conversation_id:
        return None
    base = (app_settings.polis_api_base_url or "").rstrip("/")
    return f"{base}/{polis.polis_conversation_id}"


def _polis_to_out(polis: models.Polis) -> schemas.PolisOut:
    return schemas.PolisOut(
        id=polis.id,
        org_id=polis.org_id,
        sub_org_id=polis.sub_org_id,
        polis_conversation_id=polis.polis_conversation_id,
        title=polis.title,
        prompt=polis.prompt,
        status=polis.status,
        created_by=polis.created_by,
        created_at=polis.created_at,
        updated_at=polis.updated_at,
        archived_at=polis.archived_at,
        intended_seed_statements=polis.intended_seed_statements,
        embed_url=_embed_url_for(polis),
    )


def _is_org_moderator_plus(membership: models.OrgMembership) -> bool:
    """Phase 12 — moderator+ tier check on the resolved Role.system_key.

    The function is kept as a pre-existing call-site convenience; the
    canonical permission gate for Polis creation is the
    'polis.create' permission key (use ``has_permission`` at the call
    site for new code).
    """
    if membership is None or membership.role is None:
        return False
    return membership.role.system_key in ("moderator", "admin", "steward")


def _can_manage_polis(db: Session, user_id: str, polis: models.Polis) -> bool:
    """Phase 71b — config-authoritative polis-manage check that PRESERVES the
    creator-ownership axis (Z decision: don't let config-authoritative
    silently strip a creator's ability to manage their own Polis).

    True iff the viewer:
      * created the Polis (ownership — always, regardless of role/config), OR
      * passes the role-tier FLOOR (``is_polis_admin``: org-wide moderator+,
        or sub-org admin / parent-admin implicit power) AND holds
        ``polis.manage`` in the matrix for the Polis's scope (the sub-org for
        sub-org Polises — ``has_permission`` auto-resolves the effective role;
        the parent org for org-wide Polises).

    The floor keeps a below-tier member from gaining manage via a stray config
    grant (escalation invariant); the config cell lets an org revoke manage
    from moderators and have it actually enforced. Replaces the bare
    ``is_polis_admin`` gate at the manage/mutate call sites.
    """
    user = db.get(models.User, user_id)
    if user is not None and user.is_admin:
        return True
    # Ownership is meaningful only while the creator remains an eligible
    # viewer. A removed or suspended member must not retain mutation or
    # deanonymized-export access through a stale creator_id.
    if user_id not in eligible_viewers_for_polis(db, polis):
        return False
    if polis.created_by == user_id:
        return True
    if not is_polis_admin(db, user_id, polis):
        return False  # below the role-tier floor
    scope_org_id = polis.sub_org_id or polis.org_id
    return has_permission(db, user_id, scope_org_id, "polis.manage")


def _resolve_sub_org(
    db: Session, parent: models.Organization, sub_org_id: str,
) -> models.Organization:
    """Validate sub-org belongs to parent; 400 if it doesn't."""
    sub = db.query(models.Organization).filter(
        models.Organization.id == sub_org_id,
        models.Organization.parent_org_id == parent.id,
    ).first()
    if sub is None:
        raise HTTPException(
            status_code=400,
            detail="sub_org_id is not a sub-org of this parent",
        )
    return sub


def _exact_polis_link_predicate(db: Session, polis_id: str):
    """Exact JSON-array membership for PostgreSQL JSON and SQLite JSON1."""
    column = models.Proposal.linked_polis_ids
    if db.get_bind().dialect.name == "postgresql":
        return cast(column, JSONB).contains([polis_id])
    values = func.json_each(column).table_valued("value").alias("polis_link")
    return exists(
        select(1).select_from(values).where(values.c.value == polis_id)
    )


# ============================================================================
# CREATE — dual-path (programmatic vs. manual-fallback)
# ============================================================================

@router.post(
    "/{org_slug}/polises",
    response_model=schemas.PolisCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_polis(
    org_slug: str,
    body: schemas.PolisCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """Create a Polis (org-wide or sub-org-scoped).

    Dispatch (`phase9_polis_api_findings.md` Decision 4):

    * If ``settings.polis_auth_token`` is set (programmatic path): call
      pol.is to create the conversation + insert seed statements; the
      `polis_conversation_id` field on the body is IGNORED with a
      response-side flag (`programmatic_path: true`). If the pol.is
      API call raises ``PolisAPIError`` we do NOT create a platform-side
      row — atomicity is the spec contract (no orphaned platform rows).

    * If not (manual-fallback): the operator must supply
      `polis_conversation_id` themselves (they created the conversation
      on pol.is by hand and are pasting the slug). Seed statements are
      stored on the platform record as `intended_seed_statements` for
      the FE's "paste these into pol.is admin UI" reference UX. Response
      flag `manual_seed_statements_required: true`.
    """
    parent = _parent_or_404(db, org_slug)

    # Permission dispatch by scope (Decision 6).
    target_sub_org: Optional[models.Organization] = None
    if body.sub_org_id is not None:
        target_sub_org = _resolve_sub_org(db, parent, body.sub_org_id)
        if not is_sub_org_admin(db, current_user.id, target_sub_org):
            raise HTTPException(
                status_code=403,
                detail=(
                    "Sub-org admin (or parent-org admin) access required "
                    "to create a sub-org-scoped Polis."
                ),
            )
        # Phase 71b — config-authoritative; sub-org-admin tier is the floor.
        if not has_permission(db, current_user.id, target_sub_org.id, "polis.create"):
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to create Polis conversations in this sub-organization.",
            )
    else:
        # Org-wide: moderator+ on the parent org.
        if not _is_org_moderator_plus(membership):
            raise HTTPException(
                status_code=403,
                detail="Moderator access required to create an org-wide Polis",
            )
        # Phase 71b — config-authoritative; moderator+ tier is the floor.
        if not has_permission(db, current_user.id, parent.id, "polis.create"):
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to create Polis conversations in this organization.",
            )

    # Determine which path to run. The env-var check is the ONLY signal —
    # if a token is configured the platform always tries programmatic
    # (the operator's `polis_conversation_id` field is ignored to keep
    # the platform-side conversation_id aligned with the pol.is API call's
    # return value; mismatched IDs would silently break embed URLs).
    use_programmatic_path = bool((app_settings.polis_auth_token or "").strip())
    seed_statements = list(body.seed_statements or [])

    polis_conversation_id: Optional[str] = None
    partial_seed_failures: Optional[list] = None

    if use_programmatic_path:
        try:
            api_result = polis_service.create_conversation(
                title=body.title,
                prompt=body.prompt,
                seed_statements=seed_statements,
            )
        except polis_service.PolisAPIError as exc:
            # No platform-side row created — atomic per spec.
            raise HTTPException(
                status_code=502,
                detail=f"pol.is API failure: {exc}",
            )
        polis_conversation_id = api_result["conversation_id"]
        seed_results = api_result.get("seed_statement_results") or []
        # Surface only the failures so the FE can render a "9/10 inserted"
        # warning. Empty list when everything posted clean.
        failures = [r for r in seed_results if not r.get("ok")]
        partial_seed_failures = failures or None
    else:
        # Link-existing path: operator must supply the conversation_id.
        if not body.polis_conversation_id:
            raise HTTPException(
                status_code=400,
                detail=(
                    "polis_conversation_id is required. Create the "
                    "conversation on pol.is first, then paste its "
                    "conversation_id."
                ),
            )
        polis_conversation_id = body.polis_conversation_id

    polis = models.Polis(
        org_id=parent.id,
        sub_org_id=target_sub_org.id if target_sub_org else None,
        polis_conversation_id=polis_conversation_id,
        title=body.title,
        prompt=body.prompt,
        created_by=current_user.id,
        status="active",
        # Phase 81 — the new link-existing frontend no longer sends
        # seed_statements, so this stores None for FE-created polises. The
        # column is INTENTIONALLY RETAINED (not dead code): the untouched
        # programmatic path still writes it, and Phase 69 programmatic
        # wiring will use it for replay/repair + server-side seed insertion.
        # Do not "clean up" its absence from the UI as unused.
        intended_seed_statements=seed_statements or None,
    )
    db.add(polis)
    db.flush()

    log_audit_event(
        db,
        action="polis.created",
        target_type="polis",
        target_id=polis.id,
        actor_id=current_user.id,
        details={
            "polis_id": polis.id,
            "org_id": parent.id,
            "sub_org_id": target_sub_org.id if target_sub_org else None,
            "title": polis.title,
            "programmatic_path": use_programmatic_path,
            "polis_conversation_id": polis_conversation_id,
        },
        ip_address=request.client.host if request.client else None,
    )

    db.commit()
    db.refresh(polis)

    # Phase 13 B-emit — polis.created -> all org members in scope. For
    # org-wide Polises this is every parent-org member; for sub-org-scoped
    # Polises the eligible_viewers_for_polis helper handles parent-admin
    # implicit power + Decision-7 default visibility. Wrapped per spec §B3.
    try:
        viewer_ids = eligible_viewers_for_polis(db, polis)
        actor_display = current_user.display_name or current_user.username
        for uid in viewer_ids:
            if uid == current_user.id:
                continue  # don't notify the creator
            emit_notification(
                db,
                background_tasks,
                event_type="polis.created",
                user_id=uid,
                org_id=parent.id,
                actor_id=current_user.id,
                target_type="polis",
                target_id=polis.id,
                payload={
                    "polis_id": polis.id,
                    "org_id": parent.id,
                    "org_slug": parent.slug,
                    "sub_org_id": polis.sub_org_id,
                    "title": polis.title,
                    "actor_display_name": actor_display,
                },
            )
        db.commit()
    except Exception as e:  # noqa: BLE001
        log.warning(
            "polis.created emit failed: %s: %s", type(e).__name__, e,
        )
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass

    return schemas.PolisCreateResponse(
        polis=_polis_to_out(polis),
        programmatic_path=use_programmatic_path,
        manual_seed_statements_required=(
            True if (not use_programmatic_path and seed_statements) else None
        ),
        partial_seed_failures=partial_seed_failures,
    )


# ============================================================================
# LIST — scope filtering via eligible_viewers_for_polis
# ============================================================================

@router.get(
    "/{org_slug}/polises",
    response_model=list[schemas.PolisOut],
)
def list_polises(
    org_slug: str,
    status_filter: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """List Polises in viewer's scope.

    Reuses Phase 8.5 list-filter pattern: query all org Polises, then
    filter via `eligible_viewers_for_polis` per row. For org-wide Polises
    the viewer set is "all org members"; for sub-org Polises Decision 7
    (default-visible-with-opt-out) governs whether parent-org members
    not in the sub-org see them.

    Optional `?status=active|archived` query param (matches the
    proposal-list filter shape).
    """
    parent = _parent_or_404(db, org_slug)
    q = db.query(models.Polis).filter(models.Polis.org_id == parent.id)
    if status_filter:
        q = q.filter(models.Polis.status == status_filter)
    polises = q.order_by(models.Polis.created_at.desc()).all()

    visible: list[models.Polis] = []
    for polis in polises:
        # Cheap optimization: org-wide Polises are visible to every active
        # member, so any active membership suffices — skip the heavier
        # eligible_viewers_for_polis query for this common case.
        if polis.sub_org_id is None:
            visible.append(polis)
            continue
        viewers = eligible_viewers_for_polis(db, polis)
        if current_user.id in viewers:
            visible.append(polis)
    return [_polis_to_out(p) for p in visible]


# ============================================================================
# Phase 82 C2 — cheap nav presence check (has ≥1 visible Polis?)
# ============================================================================

@router.get(
    "/{org_slug}/polises/has-visible",
    response_model=schemas.PolisHasVisibleResponse,
)
def has_visible_polises(
    org_slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """Phase 82 C2 — boolean used by the member nav to decide whether to show
    the "Deliberations" link. Short-circuits on the first visible Polis so the
    nav poll stays cheap. Declared BEFORE the `/{polis_id}` detail route so
    "has-visible" isn't captured as a polis_id.
    """
    parent = _parent_or_404(db, org_slug)
    polises = db.query(models.Polis).filter(
        models.Polis.org_id == parent.id,
    ).all()
    for polis in polises:
        # Org-wide Polises are visible to every active member (matches the
        # list_polises fast path).
        if polis.sub_org_id is None:
            return schemas.PolisHasVisibleResponse(has_visible=True)
        if current_user.id in eligible_viewers_for_polis(db, polis):
            return schemas.PolisHasVisibleResponse(has_visible=True)
    return schemas.PolisHasVisibleResponse(has_visible=False)


# ============================================================================
# Phase 82 C1 — AI seed-statement generator (stateless; CSV built client-side)
# ============================================================================

@router.post(
    "/{org_slug}/polises/seed-statements/generate",
    response_model=schemas.PolisSeedGenerateResponse,
)
def generate_seed_statements(
    org_slug: str,
    body: schemas.PolisSeedGenerateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """Phase 82 C1 — draft pol.is seed statements via Sonnet. Stateless: the
    statements are returned for client-side review + CSV download and are NOT
    persisted (no `intended_seed_statements` write). Degradation is carried in
    the `warning` field (200), except the not-configured case (503).

    Permission: `polis.create` OR `polis.manage` on the parent org (whoever
    can create or manage a Polis can generate seeds). Declared before the
    `/{polis_id}` POST routes so "seed-statements" isn't captured as a
    polis_id.
    """
    import polis_seed_generator

    parent = _parent_or_404(db, org_slug)

    # Permission: create OR manage on the parent org.
    can_generate = (
        has_permission(db, current_user.id, parent.id, "polis.create")
        or has_permission(db, current_user.id, parent.id, "polis.manage")
    )
    if not can_generate:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to generate seed statements.",
        )

    if not polis_seed_generator.is_configured():
        raise HTTPException(
            status_code=503,
            detail="AI seed generation isn't configured on this platform.",
        )

    # Resolve org description server-side only when opted in (never trust a
    # client-passed description).
    org_description = ""
    if body.include_org_description:
        org_description = parent.description or ""

    statements, warning = polis_seed_generator.generate_statements(
        topic=body.topic,
        description=body.description,
        steer=body.steer,
        org_description=org_description,
    )

    # Light audit — aggregate only, NEVER the statement text.
    log_audit_event(
        db,
        action="polis.seed_statements_generated",
        target_type="organization",
        target_id=parent.id,
        actor_id=current_user.id,
        details={
            "count": len(statements),
            "include_org_description": bool(body.include_org_description),
            "had_warning": bool(warning),
        },
    )
    db.commit()

    return schemas.PolisSeedGenerateResponse(statements=statements, warning=warning)


# ============================================================================
# GET — detail with optional live participation stats
# ============================================================================

@router.get(
    "/{org_slug}/polises/{polis_id}",
    response_model=dict,
)
def get_polis(
    org_slug: str,
    polis_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """Polis detail + live participation stats (fail-soft).

    Returns the PolisOut payload plus a `participation_stats` block from
    `polis_service.get_participation_stats`. Stats fetch is auth-optional
    on pol.is (works even without POLIS_AUTH_TOKEN); polis_service
    fail-softs to `live_stats_unavailable: true` if the API is down so
    the detail page never blows up.

    Visibility scope: viewer must be in `eligible_viewers_for_polis(polis)`.
    """
    parent = _parent_or_404(db, org_slug)
    polis = _polis_or_404(db, parent, polis_id)

    if polis.sub_org_id is not None:
        viewers = eligible_viewers_for_polis(db, polis)
        if current_user.id not in viewers:
            raise HTTPException(status_code=404, detail="Polis not found")

    stats: dict
    if polis.polis_conversation_id:
        try:
            stats = polis_service.get_participation_stats(
                polis.polis_conversation_id,
            )
        except Exception:
            # polis_service already fail-softs internally, but defensive
            # second try here keeps the route from ever 500'ing on an
            # unexpected polis_service exception type.
            stats = {
                "participant_count": 0,
                "statement_count": 0,
                "vote_count": 0,
                "live_stats_unavailable": True,
            }
    else:
        # No conversation_id yet (manual-fallback pre-paste state).
        stats = {
            "participant_count": 0,
            "statement_count": 0,
            "vote_count": 0,
            "live_stats_unavailable": True,
            "error": "polis_conversation_id not set",
        }

    out = _polis_to_out(polis)
    return {**out.model_dump(), "participation_stats": stats}


@router.get(
    "/{org_slug}/polises/{polis_id}/proposal-links",
    response_model=schemas.PolisProposalLinksOut,
)
def get_polis_proposal_links(
    org_slug: str,
    polis_id: str,
    cursor: Optional[str] = Query(None),
    limit: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """Return an exact, visibility-filtered reverse proposal-link page."""
    parent = _parent_or_404(db, org_slug)
    polis = _polis_or_404(db, parent, polis_id)
    # The membership dependency is the canonical complete access proof for an
    # org-wide Polis. Sub-org Polises retain their narrower scope resolver.
    if (
        polis.sub_org_id is not None
        and current_user.id not in eligible_viewers_for_polis(db, polis)
    ):
        raise HTTPException(status_code=404, detail="Polis not found")

    from org_middleware import membership_role_system_key
    from proposal_feed import member_visibility
    from proposal_pagination import (
        created_after_cursor,
        decode_created_cursor,
        encode_created_cursor,
    )
    is_parent_admin = membership_role_system_key(membership) in ("admin", "steward")
    query = db.query(models.Proposal).options(load_only(
        models.Proposal.id,
        models.Proposal.title,
        models.Proposal.status,
        models.Proposal.created_at,
    )).filter(
        member_visibility(
            db, parent, current_user, is_admin=is_parent_admin,
        ),
        _exact_polis_link_predicate(db, polis.id),
    )
    if cursor:
        decoded = decode_created_cursor(
            cursor,
            error_code="invalid_polis_proposal_cursor",
            error_message="Malformed Polis proposal-link cursor",
        )
        query = query.filter(created_after_cursor(decoded))
    rows = query.order_by(
        models.Proposal.created_at.desc(), models.Proposal.id.asc(),
    ).limit(limit + 1).all()
    has_more = len(rows) > limit
    page = rows[:limit]
    return schemas.PolisProposalLinksOut(
        items=[
            schemas.PolisProposalLinkItemOut(
                id=proposal.id,
                title=proposal.title,
                status=proposal.status,
                created_at=proposal.created_at,
            )
            for proposal in page
        ],
        next_cursor=(encode_created_cursor(page[-1]) if has_more and page else None),
        has_more=has_more,
    )


# ============================================================================
# PATCH — title edit + archive (admin only)
# ============================================================================

@router.patch(
    "/{org_slug}/polises/{polis_id}",
    response_model=schemas.PolisOut,
)
def update_polis(
    org_slug: str,
    polis_id: str,
    body: schemas.PolisUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Update title and/or archive a Polis (admin only).

    `body.status` may only be `'archived'` (validated in PolisUpdate
    field_validator). Title edits emit `polis.config_changed` with the
    Phase 8 sustained-majority diff shape `{changes: {title: {old, new}}}`.
    Archival emits `polis.archived` and ALSO calls
    `polis_service.archive_conversation` to close the conversation on
    pol.is — but we capture failure into the audit payload as
    `polis_api_call_result: 'failed' | 'no_token' | 'success'` so we
    can audit the manual-fallback "platform archived but pol.is is
    still live" case (admin must close on pol.is manually).

    Phase 9 Session 4 gap fix: also accepts `polis_conversation_id` for
    the manual-fallback "paste slug" Save flow. One-shot connect — only
    valid when the Polis currently has no conversation_id. Emits
    `polis.connected` on success. If multiple fields are sent in one
    PATCH, all updates apply atomically; events fire alongside each other.
    """
    parent = _parent_or_404(db, org_slug)
    polis = _polis_or_404(db, parent, polis_id)

    if not _can_manage_polis(db, current_user.id, polis):
        raise HTTPException(status_code=403, detail="Polis admin access required")

    # Conversation_id connect (one-shot, manual-fallback wire-up). Done
    # before title/archive so a same-request connect-and-rename emits
    # `polis.connected` first, in dispatch order. Validate the value is
    # non-empty after stripping; reject if already set (irreversible).
    if body.polis_conversation_id is not None:
        cid = body.polis_conversation_id.strip()
        if not cid:
            raise HTTPException(
                status_code=400,
                detail=(
                    "polis_conversation_id must be a non-empty string"
                ),
            )
        if polis.polis_conversation_id:
            raise HTTPException(
                status_code=400,
                detail=(
                    "polis_conversation_id is already set on this Polis "
                    "and cannot be changed (one-shot connect — "
                    "irreversible without admin tooling)."
                ),
            )
        polis.polis_conversation_id = cid
        log_audit_event(
            db,
            action="polis.connected",
            target_type="polis",
            target_id=polis.id,
            actor_id=current_user.id,
            details={
                "polis_id": polis.id,
                "polis_conversation_id": cid,
            },
            ip_address=request.client.host if request.client else None,
        )

    # Title update next (so a same-request title-change-and-archive emits
    # both events in their natural order).
    if body.title is not None and body.title != polis.title:
        old_title = polis.title
        polis.title = body.title
        log_audit_event(
            db,
            action="polis.config_changed",
            target_type="polis",
            target_id=polis.id,
            actor_id=current_user.id,
            details={
                "polis_id": polis.id,
                "changes": {"title": {"old": old_title, "new": body.title}},
            },
            ip_address=request.client.host if request.client else None,
        )

    # Archive (only valid `status` transition in v1).
    if body.status == "archived" and polis.status != "archived":
        polis.status = "archived"
        polis.archived_at = _now()

        # Close on pol.is too. Three outcomes for the audit trail:
        #   - 'success' — API call succeeded; conversation is closed.
        #   - 'failed'  — API call raised; platform marks archived but
        #     the pol.is conversation may still accept participation.
        #     Admin must close it manually on the pol.is admin UI.
        #   - 'no_token' — no POLIS_AUTH_TOKEN configured; platform
        #     archives but never tried to call pol.is. Manual-fallback
        #     case; admin must close on pol.is by hand.
        polis_api_call_result: str
        if polis.polis_conversation_id and (
            (app_settings.polis_auth_token or "").strip()
        ):
            try:
                polis_service.archive_conversation(polis.polis_conversation_id)
                polis_api_call_result = "success"
            except polis_service.PolisAPIError:
                polis_api_call_result = "failed"
        else:
            polis_api_call_result = "no_token"

        log_audit_event(
            db,
            action="polis.archived",
            target_type="polis",
            target_id=polis.id,
            actor_id=current_user.id,
            details={
                "polis_id": polis.id,
                "polis_api_call_result": polis_api_call_result,
            },
            ip_address=request.client.host if request.client else None,
        )

    db.commit()
    db.refresh(polis)
    return _polis_to_out(polis)


# ============================================================================
# XID — get-or-create the user's pseudonymous bridge ID
# ============================================================================

@router.post(
    "/{org_slug}/polises/{polis_id}/xid",
    response_model=schemas.PolisXidResponse,
)
def get_or_create_xid_for_polis(
    org_slug: str,
    polis_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """Return the requesting user's `polis_xid` for this org.

    Idempotent on repeat calls (per Phase 9 Session 1's
    `get_or_create_polis_xid` semantics). Audit `polis.xid_generated`
    is emitted ONLY on first generation, wired in the helper.

    Visibility scope: viewer must be in `eligible_viewers_for_polis(polis)`.
    """
    parent = _parent_or_404(db, org_slug)
    polis = _polis_or_404(db, parent, polis_id)

    viewers = eligible_viewers_for_polis(db, polis)
    if current_user.id not in viewers:
        raise HTTPException(status_code=403, detail="Not eligible to view this Polis")

    xid = polis_service.get_or_create_polis_xid(
        db,
        user_id=current_user.id,
        org_id=parent.id,
        actor_id=current_user.id,
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return schemas.PolisXidResponse(polis_xid=xid)


# ============================================================================
# EXPORT — admin-only data export with optional deanonymization
# ============================================================================

@router.get(
    "/{org_slug}/polises/{polis_id}/export",
    response_class=Response,
)
def export_polis(
    org_slug: str,
    polis_id: str,
    request: Request,
    deanonymize: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Admin-only Polis data export (CSV bytes from pol.is).

    When `?deanonymize=true`, joins against `polis_xids` to map xids back
    to platform user IDs (incl. display names) and prepends a
    `xid_user_mapping` JSON block above the export payload as a multi-part
    response. The export bytes themselves stay unmodified; the mapping
    metadata is platform-side context the admin needs to deanonymize.

    Audit (`polis.export_requested`) records THAT exported and whether
    deanonymization was requested — NOT the export contents (Phase 7.5
    redaction principles).

    Returns 503 with a clear "manual export required" message when no
    POLIS_AUTH_TOKEN is configured (the export endpoint is admin-auth on
    pol.is so we cannot proxy without one).
    """
    parent = _parent_or_404(db, org_slug)
    polis = _polis_or_404(db, parent, polis_id)

    if not _can_manage_polis(db, current_user.id, polis):
        raise HTTPException(status_code=403, detail="Polis admin access required")

    if not (app_settings.polis_auth_token or "").strip():
        raise HTTPException(
            status_code=503,
            detail=(
                "Polis API export requires POLIS_AUTH_TOKEN. Manual export "
                "available from the pol.is admin UI."
            ),
        )

    # Audit BEFORE the API call so we record the intent even if the
    # downstream call fails. Aggregate-only payload per Phase 7.5.
    log_audit_event(
        db,
        action="polis.export_requested",
        target_type="polis",
        target_id=polis.id,
        actor_id=current_user.id,
        details={
            "polis_id": polis.id,
            "deanonymized": bool(deanonymize),
        },
        ip_address=request.client.host if request.client else None,
    )
    db.commit()

    if not polis.polis_conversation_id:
        raise HTTPException(
            status_code=409,
            detail="Polis has no conversation_id; nothing to export",
        )

    try:
        raw = polis_service.fetch_export(polis.polis_conversation_id)
    except polis_service.PolisAPIError as exc:
        raise HTTPException(status_code=502, detail=f"pol.is export failed: {exc}")

    if not deanonymize:
        return Response(
            content=raw,
            media_type="text/csv",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="polis_{polis.id}.csv"'
                ),
            },
        )

    # Deanonymized response: prepend an xid -> user mapping section as a
    # multi-part-ish text payload. This is a v1 simplification — the
    # admin gets one file with both the mapping and the raw CSV. Frontend
    # can split at the marker if needed.
    xids = db.query(models.PolisXid).filter(
        models.PolisXid.org_id == parent.id,
    ).all()
    user_ids = [x.user_id for x in xids]
    users = (
        db.query(models.User).filter(models.User.id.in_(user_ids)).all()
        if user_ids else []
    )
    user_map = {u.id: u for u in users}
    mapping_lines = ["xid,user_id,display_name,username"]
    for x in xids:
        u = user_map.get(x.user_id)
        if u is None:
            continue
        # Quote display_name defensively for commas.
        dn = (u.display_name or "").replace('"', '""')
        un = (u.username or "").replace('"', '""')
        mapping_lines.append(f'{x.polis_xid},{x.user_id},"{dn}","{un}"')
    mapping_csv = "\n".join(mapping_lines).encode()

    sep = b"\n--- POLIS EXPORT ---\n"
    return Response(
        content=mapping_csv + sep + raw,
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f'attachment; filename="polis_{polis.id}_deanon.csv"'
            ),
            "X-Polis-Deanonymized": "true",
        },
    )
