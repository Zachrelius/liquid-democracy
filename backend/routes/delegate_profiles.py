"""Phase 19 (B3) — Public-delegate-page lifecycle endpoints.

Mounted under ``/api/orgs/{org_slug}/delegate-profile/*``. Routes manage:

  * The caller's own ``OrgDelegateProfile`` row in this org (idempotent
    get-or-create on first access; PATCH for intro + page_visibility).
  * Per-topic ``DelegateProfile`` rows: bio + position_statement edits +
    visibility transitions (``private`` <-> ``public`` toggleable; the
    ``public -> public_accepting`` transition goes through the dedicated
    submit endpoint and may require approval per the org's
    ``delegate_application.approve`` matrix).
  * The approve / deny side of the workflow (gated on
    ``delegate_application.approve``). Deny requires a non-empty comment;
    user re-submits as a fresh application.
  * User-initiated reverts:
    - ``revert-to-public`` is a soft revert — existing delegations on the
      topic remain (D7).
    - ``revert-to-private`` is a hard revert per D7 / D15 — auto-revoke
      delegations on this topic where ``delegation_intent_id IS NULL``
      (public origin only). Private-origin delegations are preserved.

Design notes
------------

The Wave-1 schema was specced to use a ``Delegation.delegation_intent_id``
column to distinguish "public origin" from "private (follow-flow)
origin." That column was NOT shipped in the Wave-1 migration; the only
durable signal we have is the ``DelegationIntent`` table itself —
``status='activated'`` rows record which delegations were materialized
through the follow-approval path. The hard-revert helper below
(``_revoke_public_origin_delegations_on_topic``) leverages that: a
delegation is considered private-origin iff there's an activated
``DelegationIntent`` matching its (delegator, delegate, org, sub_org,
topic) shape. This matches D15 semantics ("delegations originated via
the private follow + delegation_allowed flow") and is the centralized
filter spec line 327 calls out.

If a future pass adds the ``delegation_intent_id`` FK column, the helper
should be updated to filter on the column directly (one query, not a
join + python set membership).

Visibility centralization
-------------------------

Every render boundary calls
``OrgDelegateProfile.effective_page_visibility(db)`` from the model
layer. Routes do NOT re-derive ``'public'`` from topic state — the
helper is the single source of truth (spec line 326).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import (
    APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response,
    status,
)
from sqlalchemy.orm import Session

import auth as auth_utils
import models
import schemas
from audit_utils import log_audit_event
from database import get_db
from delegation_engine import graph_store
from notification_emit import emit_notification
from org_middleware import require_org_membership
from role_permissions import has_permission


log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/orgs", tags=["delegate-profiles"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    """Naive UTC — matches the rest of the codebase's DateTime columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _get_or_create_org_delegate_profile(
    db: Session, user_id: str, org_id: str,
) -> models.OrgDelegateProfile:
    """Return the caller's OrgDelegateProfile for this org, creating one
    with ``page_visibility='private'`` (D9 default) on first access. The
    GET endpoint is idempotent — no error on re-call.
    """
    odp = (
        db.query(models.OrgDelegateProfile)
        .filter(
            models.OrgDelegateProfile.user_id == user_id,
            models.OrgDelegateProfile.org_id == org_id,
        )
        .first()
    )
    if odp is not None:
        return odp

    odp = models.OrgDelegateProfile(
        user_id=user_id,
        org_id=org_id,
        intro=None,
        page_visibility="private",
    )
    db.add(odp)
    db.flush()
    log_audit_event(
        db,
        action="org_delegate_profile.created",
        target_type="org_delegate_profile",
        target_id=odp.id,
        actor_id=user_id,
        details={
            "user_id": user_id,
            "org_id": org_id,
            "page_visibility": "private",
            "via": "get_or_create",
        },
    )
    return odp


def _serialize_topic_row(
    dp: models.DelegateProfile,
    topic: Optional[models.Topic],
) -> schemas._OrgDelegateProfileTopicOut:
    return schemas._OrgDelegateProfileTopicOut(
        id=dp.id,
        topic_id=dp.topic_id,
        topic_name=topic.name if topic is not None else None,
        bio=dp.bio or "",
        position_statement=dp.position_statement,
        visibility=dp.visibility,
        public_accepting_submitted_at=dp.public_accepting_submitted_at,
        public_accepting_approved_at=dp.public_accepting_approved_at,
        public_accepting_approved_by_id=dp.public_accepting_approved_by_id,
        public_accepting_denied_comment=dp.public_accepting_denied_comment,
    )


def _serialize_org_delegate_profile(
    db: Session,
    odp: models.OrgDelegateProfile,
    org: models.Organization,
) -> schemas.OrgDelegateProfileOut:
    """Build the GET response shape, including all per-topic DelegateProfile
    rows for (user_id, org_id) joined with topic names. Calls the
    centralized ``effective_page_visibility`` helper (spec line 326).
    """
    topic_rows = (
        db.query(models.DelegateProfile)
        .filter(
            models.DelegateProfile.user_id == odp.user_id,
            models.DelegateProfile.org_id == odp.org_id,
        )
        .all()
    )
    topic_ids = [dp.topic_id for dp in topic_rows]
    topics_by_id: dict[str, models.Topic] = {}
    if topic_ids:
        topics_by_id = {
            t.id: t for t in db.query(models.Topic)
            .filter(models.Topic.id.in_(topic_ids))
            .all()
        }
    serialized_topics = [
        _serialize_topic_row(dp, topics_by_id.get(dp.topic_id))
        for dp in topic_rows
    ]
    # Centralized derivation — per spec line 326 do NOT re-implement.
    eff = odp.effective_page_visibility(db)
    return schemas.OrgDelegateProfileOut(
        id=odp.id,
        user_id=odp.user_id,
        org_id=odp.org_id,
        org_slug=org.slug,
        intro=odp.intro,
        page_visibility=odp.page_visibility,
        effective_page_visibility=eff,
        created_at=odp.created_at,
        updated_at=odp.updated_at,
        topics=serialized_topics,
    )


def _topic_in_org_or_404(
    db: Session, topic_id: str, org_id: str,
) -> models.Topic:
    """Resolve ``topic_id`` and verify it belongs to ``org_id``. 404
    rather than 400 to avoid leaking topic existence across orgs."""
    topic = db.get(models.Topic, topic_id)
    if topic is None or topic.org_id != org_id:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic


def _get_or_create_delegate_profile(
    db: Session, user_id: str, org_id: str, topic_id: str,
) -> models.DelegateProfile:
    """Get-or-create a DelegateProfile row for (user, org, topic). New
    rows default to ``visibility='private'`` (the user is implicitly
    drafting; nothing about the topic is publicly visible until they
    raise visibility).

    The Phase 19 enum default on the column itself is
    ``'public_accepting'`` (D8 backwards-compat for legacy rows) but
    NEW rows created from this route default to ``'private'`` because
    a Phase-19-aware caller should explicitly opt into a non-private
    state via the lifecycle transitions.
    """
    dp = (
        db.query(models.DelegateProfile)
        .filter(
            models.DelegateProfile.user_id == user_id,
            models.DelegateProfile.topic_id == topic_id,
            models.DelegateProfile.org_id == org_id,
        )
        .first()
    )
    if dp is not None:
        return dp

    dp = models.DelegateProfile(
        user_id=user_id,
        topic_id=topic_id,
        org_id=org_id,
        bio="",
        is_active=True,
        visibility="private",
    )
    db.add(dp)
    db.flush()
    log_audit_event(
        db,
        action="delegate_profile.created",
        target_type="delegate_profile",
        target_id=dp.id,
        actor_id=user_id,
        details={
            "user_id": user_id,
            "org_id": org_id,
            "topic_id": topic_id,
            "visibility": "private",
            "via": "get_or_create",
        },
    )
    return dp


def _is_private_origin_delegation(
    db: Session, delegation: models.Delegation,
) -> bool:
    """Phase 19 D15 — return True iff this delegation was originated via
    the private follow-flow (i.e., an activated DelegationIntent exists
    matching its shape).

    See module docstring: the spec assumed a ``delegation_intent_id``
    column; Wave 1 didn't ship one, so we infer origin from the
    ``DelegationIntent`` table. Activated intents persist in the DB
    (``status='activated'``), so this query is stable across time —
    a delegation that was originally activated through a follow stays
    classified as private-origin until it's deleted.
    """
    has_activated_intent = (
        db.query(models.DelegationIntent.id)
        .filter(
            models.DelegationIntent.delegator_id == delegation.delegator_id,
            models.DelegationIntent.delegate_id == delegation.delegate_id,
            models.DelegationIntent.org_id == delegation.org_id,
            models.DelegationIntent.sub_org_id == delegation.sub_org_id,
            models.DelegationIntent.topic_id == delegation.topic_id,
            models.DelegationIntent.status == "activated",
        )
        .first()
        is not None
    )
    return has_activated_intent


def _revoke_public_origin_delegations_on_topic(
    db: Session,
    background_tasks: BackgroundTasks,
    delegate_id: str,
    topic_id: str,
    org_id: str,
    org_slug: str,
    org_name: str,
    topic_name: str,
    delegate_display_name: str,
    actor_id: Optional[str] = None,
) -> int:
    """Phase 19 hard-revert helper — centralized per spec line 327.

    Revokes delegations to ``delegate_id`` on ``topic_id`` in ``org_id``
    where the origin is the public-delegate flow (i.e., NOT linked to an
    activated DelegationIntent — see ``_is_private_origin_delegation``).
    Emits a ``delegation_revoked_by_delegate`` notification per revoked
    delegation and writes one ``delegation.revoked_by_delegate`` audit
    log row. Returns the count of revoked rows.

    Notifications fire only for public-origin delegations per D15 —
    private-origin delegators are NOT notified (nothing changed for them
    from their delegation's perspective; the delegate's separate private
    follow trust is untouched).
    """
    candidates = (
        db.query(models.Delegation)
        .filter(
            models.Delegation.delegate_id == delegate_id,
            models.Delegation.org_id == org_id,
            models.Delegation.topic_id == topic_id,
        )
        .all()
    )
    revoked_count = 0
    for d in candidates:
        if _is_private_origin_delegation(db, d):
            # D15: leave private-origin delegations untouched, no notify.
            continue

        delegator_id = d.delegator_id
        delegation_id = d.id
        log_audit_event(
            db,
            action="delegation.revoked_by_delegate",
            target_type="delegation",
            target_id=delegation_id,
            actor_id=actor_id,
            details={
                "delegator_id": delegator_id,
                "delegate_id": delegate_id,
                "topic_id": topic_id,
                "org_id": org_id,
                "reason": "delegate_topic_hard_revert_to_private",
            },
        )
        db.delete(d)
        db.flush()
        # Update the in-memory delegation graph so subsequent tally /
        # eligibility computations see the revocation immediately.
        graph_store.remove_delegation(
            delegator_id, topic_id, org_id=org_id,
        )

        # Per-delegator notification. Wrapped per-row to avoid one
        # malformed recipient sinking the rest.
        try:
            emit_notification(
                db,
                background_tasks,
                event_type="delegation_revoked_by_delegate",
                user_id=delegator_id,
                org_id=org_id,
                actor_id=actor_id,
                target_type="delegation",
                target_id=delegation_id,
                payload={
                    "org_id": org_id,
                    "org_slug": org_slug,
                    "org_name": org_name,
                    "topic_id": topic_id,
                    "topic_name": topic_name,
                    "delegate_display_name": delegate_display_name,
                    "actor_display_name": delegate_display_name,
                },
            )
        except Exception as e:  # noqa: BLE001
            log.warning(
                "delegation_revoked_by_delegate emit failed for "
                "delegator=%s delegation=%s: %s: %s",
                delegator_id, delegation_id, type(e).__name__, e,
            )

        revoked_count += 1

    return revoked_count


def _has_org_approvers(db: Session, org_id: str) -> bool:
    """Auto-approval gate — per spec §B3 endpoint (4): if the org has no
    approvers (no users hold ``delegate_application.approve``), submit
    auto-approves immediately.

    We resolve approvers by walking active memberships and consulting
    ``has_permission`` per user. This matches the
    ``_users_with_permission_in_org`` shape used by the legacy delegate-
    application surface in routes/organizations.py — keeping the two in
    lockstep so an org's approver set is consistent across both flows.
    """
    member_rows = (
        db.query(models.OrgMembership.user_id)
        .filter(
            models.OrgMembership.org_id == org_id,
            models.OrgMembership.status == "active",
        )
        .all()
    )
    for r in member_rows:
        if has_permission(db, r.user_id, org_id, "delegate_application.approve"):
            return True
    return False


def _users_with_approve_permission(db: Session, org_id: str) -> list[str]:
    """Return user_ids of all active org members holding
    ``delegate_application.approve`` — for the submit notification fan-out.
    """
    member_rows = (
        db.query(models.OrgMembership.user_id)
        .filter(
            models.OrgMembership.org_id == org_id,
            models.OrgMembership.status == "active",
        )
        .all()
    )
    return [
        r.user_id for r in member_rows
        if has_permission(db, r.user_id, org_id, "delegate_application.approve")
    ]


# ---------------------------------------------------------------------------
# Routes — caller's own OrgDelegateProfile
# ---------------------------------------------------------------------------


@router.get(
    "/{org_slug}/delegate-profile",
    response_model=schemas.OrgDelegateProfileOut,
)
def get_my_org_delegate_profile(
    org_slug: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """Return the caller's OrgDelegateProfile for this org. Idempotent
    get-or-create: if no row exists, one is created with
    ``page_visibility='private'`` and the (now-existing) row is returned.
    """
    org = db.get(models.Organization, membership.org_id)
    if org is None:
        # Defensive — require_org_membership already resolved org context.
        raise HTTPException(status_code=404, detail="Organization not found")

    odp = _get_or_create_org_delegate_profile(
        db, current_user.id, membership.org_id,
    )
    db.commit()
    db.refresh(odp)
    return _serialize_org_delegate_profile(db, odp, org)


@router.patch(
    "/{org_slug}/delegate-profile",
    response_model=schemas.OrgDelegateProfileOut,
)
def patch_my_org_delegate_profile(
    org_slug: str,
    body: schemas.OrgDelegateProfilePatch,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """Update the caller's OrgDelegateProfile (intro, page_visibility).
    User-only — implicitly enforced by always operating on the caller's
    own row (idempotent get-or-create then mutate).
    """
    org = db.get(models.Organization, membership.org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    odp = _get_or_create_org_delegate_profile(
        db, current_user.id, membership.org_id,
    )

    changes: dict[str, object] = {}
    if body.intro is not None:
        changes["intro"] = body.intro
        odp.intro = body.intro
    if body.page_visibility is not None:
        changes["page_visibility"] = body.page_visibility
        odp.page_visibility = body.page_visibility

    if changes:
        db.flush()
        log_audit_event(
            db,
            action="org_delegate_profile.updated",
            target_type="org_delegate_profile",
            target_id=odp.id,
            actor_id=current_user.id,
            details={
                "user_id": current_user.id,
                "org_id": membership.org_id,
                "changes": changes,
            },
            ip_address=request.client.host if request.client else None,
        )

    db.commit()
    db.refresh(odp)
    return _serialize_org_delegate_profile(db, odp, org)


# ---------------------------------------------------------------------------
# Routes — per-topic DelegateProfile editing
# ---------------------------------------------------------------------------


@router.patch(
    "/{org_slug}/delegate-profile/topics/{topic_id}",
    response_model=schemas.OrgDelegateProfileOut,
)
def patch_my_topic_profile(
    org_slug: str,
    topic_id: str,
    body: schemas.DelegateProfileTopicPatch,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """Update a per-topic ``DelegateProfile`` row: bio, position_statement,
    or transition visibility ``private <-> public``.

    Direct ``public_accepting`` transitions are REJECTED — the schema
    validator catches them with a 422; this is the dedicated submit
    endpoint's territory (``submit-public-accepting``).

    Hard-revert (``public -> private``) is also REJECTED here — clients
    must use the dedicated ``revert-to-private`` endpoint so the cascade
    runs inside an explicit confirmation flow (F1 dialog, per spec).
    """
    org = db.get(models.Organization, membership.org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    topic = _topic_in_org_or_404(db, topic_id, membership.org_id)
    dp = _get_or_create_delegate_profile(
        db, current_user.id, membership.org_id, topic.id,
    )

    changes: dict[str, object] = {}
    if body.bio is not None:
        changes["bio"] = body.bio
        dp.bio = body.bio
    if body.position_statement is not None:
        changes["position_statement"] = body.position_statement
        dp.position_statement = body.position_statement
    if body.visibility is not None:
        new_v = body.visibility
        old_v = dp.visibility
        if new_v == "public" and old_v == "public_accepting":
            # public_accepting -> public is the SOFT revert; route caller
            # through the dedicated endpoint so the audit trail captures
            # the user's explicit intent.
            raise HTTPException(
                status_code=400,
                detail=(
                    "Use POST .../revert-to-public to transition from "
                    "public_accepting to public."
                ),
            )
        if new_v == "private" and old_v in ("public", "public_accepting"):
            # Hard revert path — needs the cascade-runner endpoint.
            raise HTTPException(
                status_code=400,
                detail=(
                    "Use POST .../revert-to-private to transition from "
                    "public/public_accepting to private — this is a "
                    "hard revert that auto-revokes public-origin "
                    "delegations."
                ),
            )
        changes["visibility"] = {"old": old_v, "new": new_v}
        dp.visibility = new_v

    if changes:
        db.flush()
        log_audit_event(
            db,
            action="delegate_profile.updated",
            target_type="delegate_profile",
            target_id=dp.id,
            actor_id=current_user.id,
            details={
                "user_id": current_user.id,
                "org_id": membership.org_id,
                "topic_id": topic.id,
                "changes": changes,
            },
            ip_address=request.client.host if request.client else None,
        )

    db.commit()

    # Re-serialize the parent OrgDelegateProfile so callers can update
    # the whole edit surface from one response.
    odp = _get_or_create_org_delegate_profile(
        db, current_user.id, membership.org_id,
    )
    db.commit()
    db.refresh(odp)
    return _serialize_org_delegate_profile(db, odp, org)


# ---------------------------------------------------------------------------
# Routes — approval workflow (submit / approve / deny)
# ---------------------------------------------------------------------------


@router.post(
    "/{org_slug}/delegate-profile/topics/{topic_id}/submit-public-accepting",
    response_model=schemas.OrgDelegateProfileOut,
)
def submit_public_accepting(
    org_slug: str,
    topic_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """Request approval to transition the topic from ``public`` to
    ``public_accepting``. If the org has no approvers (the matrix grants
    ``delegate_application.approve`` to no one), auto-approve immediately
    AND transition the topic. Otherwise: set ``submitted_at`` and emit
    ``delegate_application_submitted`` notifications to approvers.

    The current state must be ``public`` — submitting from ``private``
    or from an already-pending state returns 400.
    """
    org = db.get(models.Organization, membership.org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    topic = _topic_in_org_or_404(db, topic_id, membership.org_id)
    dp = _get_or_create_delegate_profile(
        db, current_user.id, membership.org_id, topic.id,
    )

    if dp.visibility == "public_accepting":
        raise HTTPException(
            status_code=400,
            detail="Topic is already in public_accepting state",
        )
    if dp.visibility != "public":
        raise HTTPException(
            status_code=400,
            detail=(
                "Topic must be in 'public' state before submitting for "
                "public_accepting; currently '" + dp.visibility + "'"
            ),
        )
    if dp.public_accepting_submitted_at is not None and \
            dp.public_accepting_approved_at is None and \
            dp.public_accepting_denied_comment is None:
        # Already pending; reject duplicate submit per spec D6.
        raise HTTPException(
            status_code=409,
            detail="A submission for this topic is already pending review",
        )

    # Clear any prior denial state so the new submission is clean.
    dp.public_accepting_denied_comment = None
    dp.public_accepting_submitted_at = _now()
    db.flush()

    actor_display = current_user.display_name or current_user.username
    has_approvers = _has_org_approvers(db, membership.org_id)

    if not has_approvers:
        # Auto-approve path per spec §B3 endpoint (4).
        dp.visibility = "public_accepting"
        dp.public_accepting_approved_at = _now()
        # Auto-approval has no human approver — leave approved_by_id NULL
        # so the audit log can distinguish auto-approve vs. human-approve.
        log_audit_event(
            db,
            action="delegate_profile.public_accepting_auto_approved",
            target_type="delegate_profile",
            target_id=dp.id,
            actor_id=current_user.id,
            details={
                "user_id": current_user.id,
                "org_id": membership.org_id,
                "topic_id": topic.id,
                "reason": "no_approvers_in_org",
            },
            ip_address=request.client.host if request.client else None,
        )
        db.commit()

        # Emit approved notification to the applicant (single recipient
        # pattern matching the human-approve path).
        try:
            emit_notification(
                db,
                background_tasks,
                event_type="delegate_application_approved",
                user_id=current_user.id,
                org_id=membership.org_id,
                actor_id=current_user.id,
                target_type="delegate_profile",
                target_id=dp.id,
                payload={
                    "org_id": membership.org_id,
                    "org_slug": org.slug,
                    "org_name": org.name,
                    "topic_id": topic.id,
                    "topic_name": topic.name,
                    "actor_display_name": actor_display,
                    "auto_approved": True,
                },
            )
            db.commit()
        except Exception as e:  # noqa: BLE001
            log.warning(
                "delegate_application_approved (auto) emit failed: %s: %s",
                type(e).__name__, e,
            )
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
    else:
        log_audit_event(
            db,
            action="delegate_profile.public_accepting_submitted",
            target_type="delegate_profile",
            target_id=dp.id,
            actor_id=current_user.id,
            details={
                "user_id": current_user.id,
                "org_id": membership.org_id,
                "topic_id": topic.id,
            },
            ip_address=request.client.host if request.client else None,
        )
        db.commit()

        # Notify approvers.
        try:
            approver_ids = _users_with_approve_permission(
                db, membership.org_id,
            )
            for approver_id in approver_ids:
                if approver_id == current_user.id:
                    continue
                emit_notification(
                    db,
                    background_tasks,
                    event_type="delegate_application_submitted",
                    user_id=approver_id,
                    org_id=membership.org_id,
                    actor_id=current_user.id,
                    target_type="delegate_profile",
                    target_id=dp.id,
                    payload={
                        "org_id": membership.org_id,
                        "org_slug": org.slug,
                        "org_name": org.name,
                        "topic_id": topic.id,
                        "topic_name": topic.name,
                        "applicant_id": current_user.id,
                        "actor_display_name": actor_display,
                    },
                )
            db.commit()
        except Exception as e:  # noqa: BLE001
            log.warning(
                "delegate_application_submitted emit failed: %s: %s",
                type(e).__name__, e,
            )
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass

    odp = _get_or_create_org_delegate_profile(
        db, current_user.id, membership.org_id,
    )
    db.commit()
    db.refresh(odp)
    return _serialize_org_delegate_profile(db, odp, org)


@router.post(
    "/{org_slug}/delegate-profile/topics/{topic_id}/approve",
    response_model=schemas.OrgDelegateProfileOut,
)
def approve_topic(
    org_slug: str,
    topic_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """Approver-only — gated on ``delegate_application.approve``. Approves
    a topic's pending public_accepting submission. Sets
    ``approved_at`` + ``approved_by_id``, transitions the topic to
    ``public_accepting``, and emits an approved notification to the
    applicant.

    Note: the approver acts on behalf of the org; we do NOT require they
    are the user whose page is being approved (in fact they must NOT
    be — see permission gate below; admins approving their own pages
    is allowed by the matrix but unusual).
    """
    if not has_permission(
        db, current_user.id, membership.org_id, "delegate_application.approve",
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "You do not have the delegate_application.approve "
                "permission in this organization."
            ),
        )

    org = db.get(models.Organization, membership.org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    topic = _topic_in_org_or_404(db, topic_id, membership.org_id)

    # The DelegateProfile we approve is the one waiting on review — we
    # need to know whose application this is. Per spec the approver page
    # lists pending applications; we expect the URL to encode the
    # applicant's identity through the profile lookup. The route uses
    # the application's pending state per (org, topic) to disambiguate
    # — there must be exactly one pending row per (org, topic, user)
    # because submit rejects duplicates. To keep the URL simple we use
    # a query on the pending profile keyed by topic + the matrix says
    # there shouldn't be multiple pending users on the SAME topic from
    # the same approver pass; if there are, we approve the oldest.
    #
    # TODO: a future revision could make this URL ``.../topics/{topic_id}
    # /applications/{user_id}/approve`` for explicit targeting. For
    # Phase 19 the implicit "oldest pending" is sufficient given
    # approver UX surfaces them one at a time.
    dp = (
        db.query(models.DelegateProfile)
        .filter(
            models.DelegateProfile.topic_id == topic.id,
            models.DelegateProfile.org_id == membership.org_id,
            models.DelegateProfile.public_accepting_submitted_at.is_not(None),
            models.DelegateProfile.public_accepting_approved_at.is_(None),
        )
        .order_by(models.DelegateProfile.public_accepting_submitted_at.asc())
        .first()
    )
    if dp is None:
        raise HTTPException(
            status_code=404,
            detail="No pending public_accepting submission for this topic",
        )

    applicant_id = dp.user_id
    dp.visibility = "public_accepting"
    dp.public_accepting_approved_at = _now()
    dp.public_accepting_approved_by_id = current_user.id
    dp.public_accepting_denied_comment = None
    db.flush()

    log_audit_event(
        db,
        action="delegate_profile.public_accepting_approved",
        target_type="delegate_profile",
        target_id=dp.id,
        actor_id=current_user.id,
        details={
            "applicant_user_id": applicant_id,
            "org_id": membership.org_id,
            "topic_id": topic.id,
        },
        ip_address=request.client.host if request.client else None,
    )
    db.commit()

    actor_display = current_user.display_name or current_user.username
    try:
        emit_notification(
            db,
            background_tasks,
            event_type="delegate_application_approved",
            user_id=applicant_id,
            org_id=membership.org_id,
            actor_id=current_user.id,
            target_type="delegate_profile",
            target_id=dp.id,
            payload={
                "org_id": membership.org_id,
                "org_slug": org.slug,
                "org_name": org.name,
                "topic_id": topic.id,
                "topic_name": topic.name,
                "actor_display_name": actor_display,
            },
        )
        db.commit()
    except Exception as e:  # noqa: BLE001
        log.warning(
            "delegate_application_approved emit failed: %s: %s",
            type(e).__name__, e,
        )
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass

    # Return the applicant's view of their OrgDelegateProfile (the one
    # we just approved a topic on). This is the most useful response
    # shape for QA harnesses / approver UIs that want to confirm the
    # transition; the approver isn't editing their own profile here.
    applicant_odp = _get_or_create_org_delegate_profile(
        db, applicant_id, membership.org_id,
    )
    db.commit()
    db.refresh(applicant_odp)
    return _serialize_org_delegate_profile(db, applicant_odp, org)


@router.post(
    "/{org_slug}/delegate-profile/topics/{topic_id}/deny",
    response_model=schemas.OrgDelegateProfileOut,
)
def deny_topic(
    org_slug: str,
    topic_id: str,
    body: schemas.DelegateApplicationDeny,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """Approver-only — deny a pending public_accepting submission with a
    required non-empty comment. Topic stays at ``public`` state; the
    submitted_at marker is cleared so the row no longer reads as
    pending. Applicant must re-submit as a fresh application per D6.
    """
    if not has_permission(
        db, current_user.id, membership.org_id, "delegate_application.approve",
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "You do not have the delegate_application.approve "
                "permission in this organization."
            ),
        )

    org = db.get(models.Organization, membership.org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    topic = _topic_in_org_or_404(db, topic_id, membership.org_id)

    dp = (
        db.query(models.DelegateProfile)
        .filter(
            models.DelegateProfile.topic_id == topic.id,
            models.DelegateProfile.org_id == membership.org_id,
            models.DelegateProfile.public_accepting_submitted_at.is_not(None),
            models.DelegateProfile.public_accepting_approved_at.is_(None),
        )
        .order_by(models.DelegateProfile.public_accepting_submitted_at.asc())
        .first()
    )
    if dp is None:
        raise HTTPException(
            status_code=404,
            detail="No pending public_accepting submission for this topic",
        )

    applicant_id = dp.user_id
    # Topic stays at 'public' (or wherever it was — typically 'public').
    # Clear the pending marker; record the denial comment.
    dp.public_accepting_submitted_at = None
    dp.public_accepting_denied_comment = body.comment
    db.flush()

    log_audit_event(
        db,
        action="delegate_profile.public_accepting_denied",
        target_type="delegate_profile",
        target_id=dp.id,
        actor_id=current_user.id,
        details={
            "applicant_user_id": applicant_id,
            "org_id": membership.org_id,
            "topic_id": topic.id,
            "comment": body.comment,
        },
        ip_address=request.client.host if request.client else None,
    )
    db.commit()

    actor_display = current_user.display_name or current_user.username
    try:
        emit_notification(
            db,
            background_tasks,
            event_type="delegate_application_denied",
            user_id=applicant_id,
            org_id=membership.org_id,
            actor_id=current_user.id,
            target_type="delegate_profile",
            target_id=dp.id,
            payload={
                "org_id": membership.org_id,
                "org_slug": org.slug,
                "org_name": org.name,
                "topic_id": topic.id,
                "topic_name": topic.name,
                "actor_display_name": actor_display,
                "denial_comment": body.comment,
            },
        )
        db.commit()
    except Exception as e:  # noqa: BLE001
        log.warning(
            "delegate_application_denied emit failed: %s: %s",
            type(e).__name__, e,
        )
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass

    applicant_odp = _get_or_create_org_delegate_profile(
        db, applicant_id, membership.org_id,
    )
    db.commit()
    db.refresh(applicant_odp)
    return _serialize_org_delegate_profile(db, applicant_odp, org)


# ---------------------------------------------------------------------------
# Routes — user-initiated reverts
# ---------------------------------------------------------------------------


@router.post(
    "/{org_slug}/delegate-profile/topics/{topic_id}/revert-to-public",
    response_model=schemas.OrgDelegateProfileOut,
)
def revert_to_public(
    org_slug: str,
    topic_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """Soft revert per D7: ``public_accepting -> public``. Existing
    delegations on the topic remain (the user has stopped accepting NEW
    delegations but kept their current delegators). No notifications.
    """
    org = db.get(models.Organization, membership.org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    topic = _topic_in_org_or_404(db, topic_id, membership.org_id)
    dp = (
        db.query(models.DelegateProfile)
        .filter(
            models.DelegateProfile.user_id == current_user.id,
            models.DelegateProfile.topic_id == topic.id,
            models.DelegateProfile.org_id == membership.org_id,
        )
        .first()
    )
    if dp is None:
        # User-only enforcement: 404 (not 403) per spec line on user-only
        # endpoints — don't leak existence.
        raise HTTPException(status_code=404, detail="Delegate profile not found")

    if dp.visibility != "public_accepting":
        raise HTTPException(
            status_code=400,
            detail=(
                "Topic must be in 'public_accepting' state to revert to "
                "'public'; currently '" + dp.visibility + "'"
            ),
        )

    dp.visibility = "public"
    # Clear pending markers — the topic isn't accepting anymore so any
    # in-flight pending state is moot.
    dp.public_accepting_submitted_at = None
    db.flush()

    log_audit_event(
        db,
        action="delegate_profile.reverted_to_public",
        target_type="delegate_profile",
        target_id=dp.id,
        actor_id=current_user.id,
        details={
            "user_id": current_user.id,
            "org_id": membership.org_id,
            "topic_id": topic.id,
            "soft_revert": True,
        },
        ip_address=request.client.host if request.client else None,
    )
    db.commit()

    odp = _get_or_create_org_delegate_profile(
        db, current_user.id, membership.org_id,
    )
    db.commit()
    db.refresh(odp)
    return _serialize_org_delegate_profile(db, odp, org)


@router.post(
    "/{org_slug}/delegate-profile/topics/{topic_id}/revert-to-private",
    response_model=schemas.OrgDelegateProfileOut,
)
def revert_to_private(
    org_slug: str,
    topic_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
    membership: models.OrgMembership = Depends(require_org_membership),
):
    """Hard revert per D7 / D15: ``public`` or ``public_accepting`` ->
    ``private``. Auto-revokes public-origin delegations on this topic
    via the centralized
    ``_revoke_public_origin_delegations_on_topic`` helper. Private-origin
    delegations (those with an activated ``DelegationIntent`` matching
    their shape) are preserved unchanged. Per-revoked-delegation
    notifications are emitted by the helper.
    """
    org = db.get(models.Organization, membership.org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    topic = _topic_in_org_or_404(db, topic_id, membership.org_id)
    dp = (
        db.query(models.DelegateProfile)
        .filter(
            models.DelegateProfile.user_id == current_user.id,
            models.DelegateProfile.topic_id == topic.id,
            models.DelegateProfile.org_id == membership.org_id,
        )
        .first()
    )
    if dp is None:
        raise HTTPException(status_code=404, detail="Delegate profile not found")

    if dp.visibility not in ("public", "public_accepting"):
        raise HTTPException(
            status_code=400,
            detail=(
                "Topic must be in 'public' or 'public_accepting' state to "
                "hard-revert to 'private'; currently '" + dp.visibility + "'"
            ),
        )

    old_visibility = dp.visibility
    dp.visibility = "private"
    # Clear pending markers — topic is fully private now.
    dp.public_accepting_submitted_at = None
    db.flush()

    delegate_display = current_user.display_name or current_user.username
    revoked_count = _revoke_public_origin_delegations_on_topic(
        db,
        background_tasks,
        delegate_id=current_user.id,
        topic_id=topic.id,
        org_id=membership.org_id,
        org_slug=org.slug,
        org_name=org.name,
        topic_name=topic.name,
        delegate_display_name=delegate_display,
        actor_id=current_user.id,
    )

    log_audit_event(
        db,
        action="delegate_profile.reverted_to_private",
        target_type="delegate_profile",
        target_id=dp.id,
        actor_id=current_user.id,
        details={
            "user_id": current_user.id,
            "org_id": membership.org_id,
            "topic_id": topic.id,
            "previous_visibility": old_visibility,
            "hard_revert": True,
            "public_origin_delegations_revoked": revoked_count,
        },
        ip_address=request.client.host if request.client else None,
    )
    db.commit()

    odp = _get_or_create_org_delegate_profile(
        db, current_user.id, membership.org_id,
    )
    db.commit()
    db.refresh(odp)
    return _serialize_org_delegate_profile(db, odp, org)
