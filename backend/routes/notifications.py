"""Phase 13 — notification feed + preferences API.

Endpoints
---------

GET    /api/notifications
POST   /api/notifications/{id}/read
POST   /api/notifications/mark-all-read
GET    /api/notifications/preferences
PATCH  /api/notifications/preferences
GET    /api/notifications/registry

All endpoints are account-scoped — the caller can only see / mutate their
own rows. Per spec Item 30 audit guidance: NO role-tier gates anywhere
in this module; every authenticated user has access to their own
notifications and preferences.

Pagination shape
----------------

GET /api/notifications uses simple offset-based pagination
(``?limit=20&offset=N``). Cursor-based was an option per spec but offset
suffices for the v1 use case (small per-user feeds, monotonically
decreasing-by-time ordering); switching to cursors later is a
backwards-compatible additive change (introduce ``?cursor=`` and ignore
``?offset=`` when ``cursor`` is set).

Item 22 routing
---------------

Each row in the feed response includes ``org_slug`` resolved from
``org_id`` (left join on organizations) so the frontend can route
click-throughs correctly without a separate lookup. Account-level
notifications carry ``org_id=None`` and ``org_slug=None``; the frontend
falls back to the account-level full feed in that case.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import auth as auth_utils
import models
from audit_utils import log_audit_event
from database import get_db
from notification_events import (
    EVENT_REGISTRY,
    is_known_event_type,
)


log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


# Allowed values mirrored from User.digest_cadence semantics.
_VALID_DIGEST_CADENCES: frozenset[str] = frozenset(
    {"real_time", "daily", "weekly", "off"}
)
_VALID_CHANNELS: frozenset[str] = frozenset({"in_app", "email"})


def _now_naive() -> datetime:
    """UTC timestamp without tzinfo. Matches the rest of the codebase."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _client_ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


# ---------------------------------------------------------------------------
# Response shapes
# ---------------------------------------------------------------------------

class NotificationOut(BaseModel):
    """One notification row in the feed response.

    ``org_slug`` is resolved server-side from ``org_id`` so the frontend
    doesn't need a separate lookup for click-through routing (Item 22).
    Account-level notifications carry ``org_id=None`` and ``org_slug=None``.
    """
    id: str
    event_type: str
    org_id: Optional[str]
    org_slug: Optional[str]
    actor_id: Optional[str]
    target_type: Optional[str]
    target_id: Optional[str]
    payload: Optional[dict[str, Any]]
    read_at: Optional[datetime]
    created_at: datetime


class NotificationListOut(BaseModel):
    """Paginated feed response. ``has_more`` is computed by asking for one
    extra row past ``limit`` and trimming."""
    items: list[NotificationOut]
    has_more: bool
    next_offset: Optional[int]


class ChannelPrefsOut(BaseModel):
    """Per-event preference flags."""
    in_app: bool = False
    email: bool = False


class PreferencesOut(BaseModel):
    """Top-level preferences shape returned by GET /preferences.

    ``preferences`` is a dict keyed by event_type with a
    ``{in_app, email}`` sub-dict. All 12 event keys are always present
    (absent rows = default-False, surfaced explicitly so the frontend
    doesn't have to merge defaults itself).
    """
    preferences: dict[str, ChannelPrefsOut]
    digest_cadence: str
    quiet_hours_enabled: bool
    timezone: Optional[str]
    notification_intro_dismissed: bool


class ChannelPrefsPatch(BaseModel):
    """Per-event partial update. Either field may be omitted."""
    in_app: Optional[bool] = None
    email: Optional[bool] = None


class PreferencesPatch(BaseModel):
    """Body shape for PATCH /preferences. All fields optional; unspecified
    fields are unchanged. ``preferences`` is a partial dict — only the
    listed event types are updated."""
    preferences: Optional[dict[str, ChannelPrefsPatch]] = None
    digest_cadence: Optional[str] = None
    quiet_hours_enabled: Optional[bool] = None
    timezone: Optional[str] = Field(default=None)
    notification_intro_dismissed: Optional[bool] = None


class EventDefinitionOut(BaseModel):
    """One event-registry entry."""
    key: str
    label: str
    description: str
    category: str


class EventRegistryOut(BaseModel):
    events: list[EventDefinitionOut]
    categories: list[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_out(
    row: models.Notification, org_slug: Optional[str],
) -> NotificationOut:
    return NotificationOut(
        id=row.id,
        event_type=row.event_type,
        org_id=row.org_id,
        org_slug=org_slug,
        actor_id=row.actor_id,
        target_type=row.target_type,
        target_id=row.target_id,
        payload=row.payload,
        read_at=row.read_at,
        created_at=row.created_at,
    )


def _bulk_org_slug_lookup(
    db: Session, org_ids: list[str],
) -> dict[str, str]:
    """Single SELECT to resolve org_id -> slug for the rows in this page.

    Avoids N+1 queries when rendering a paginated feed where many rows
    point at the same org. Account-level notifications (org_id=None) are
    skipped — caller passes only non-None ids.
    """
    if not org_ids:
        return {}
    rows = (
        db.query(models.Organization.id, models.Organization.slug)
        .filter(models.Organization.id.in_(org_ids))
        .all()
    )
    return {oid: slug for oid, slug in rows}


# ---------------------------------------------------------------------------
# GET /api/notifications
# ---------------------------------------------------------------------------

@router.get("", response_model=NotificationListOut)
def list_notifications(
    unread: bool = Query(False, description="If True, only unread rows."),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Return the caller's notifications, newest first.

    Pagination is offset-based: ``?limit=20&offset=N``. The response's
    ``has_more`` field is True when more rows exist beyond this page; the
    frontend can either pass ``next_offset`` as the next ``offset`` or
    bump its own counter.
    """
    q = (
        db.query(models.Notification)
        .filter(models.Notification.user_id == current_user.id)
    )
    if unread:
        q = q.filter(models.Notification.read_at.is_(None))

    # Fetch one extra row to determine has_more without a separate count.
    rows = (
        q.order_by(models.Notification.created_at.desc())
        .offset(offset)
        .limit(limit + 1)
        .all()
    )
    has_more = len(rows) > limit
    page = rows[:limit]

    # Bulk-resolve org slugs in one SELECT (Item 22 routing).
    org_ids = sorted({r.org_id for r in page if r.org_id is not None})
    slug_by_id = _bulk_org_slug_lookup(db, org_ids)

    items = [_row_to_out(r, slug_by_id.get(r.org_id) if r.org_id else None) for r in page]
    return NotificationListOut(
        items=items,
        has_more=has_more,
        next_offset=(offset + limit) if has_more else None,
    )


# ---------------------------------------------------------------------------
# POST /api/notifications/{id}/read
# ---------------------------------------------------------------------------

@router.post(
    "/{notification_id}/read",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def mark_read(
    notification_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Mark a single notification read. Idempotent.

    404 if the notification doesn't exist OR belongs to another user (we
    intentionally don't distinguish — leaking "this id exists but isn't
    yours" would be a small information leak).
    """
    row = db.get(models.Notification, notification_id)
    if row is None or row.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found.",
        )

    if row.read_at is None:
        row.read_at = _now_naive()
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# POST /api/notifications/mark-all-read
# ---------------------------------------------------------------------------

class MarkAllReadOut(BaseModel):
    marked: int


@router.post("/mark-all-read", response_model=MarkAllReadOut)
def mark_all_read(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Bulk-mark every unread notification for the caller as read.

    Returns ``{marked: N}`` so the frontend can surface a confirmation
    count.
    """
    now = _now_naive()
    n = (
        db.query(models.Notification)
        .filter(
            models.Notification.user_id == current_user.id,
            models.Notification.read_at.is_(None),
        )
        .update({"read_at": now}, synchronize_session=False)
    )
    db.commit()
    return MarkAllReadOut(marked=int(n))


# ---------------------------------------------------------------------------
# GET /api/notifications/preferences
# ---------------------------------------------------------------------------

@router.get("/preferences", response_model=PreferencesOut)
def get_preferences(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Return the caller's full preferences shape.

    Every event_type from EVENT_REGISTRY is included (all 12). Absent
    rows surface as ``{in_app: False, email: False}`` so the frontend
    doesn't have to merge defaults itself.
    """
    rows = (
        db.query(models.NotificationPreference)
        .filter(models.NotificationPreference.user_id == current_user.id)
        .all()
    )
    by_event: dict[str, ChannelPrefsOut] = {
        ev.key: ChannelPrefsOut() for ev in EVENT_REGISTRY
    }
    for r in rows:
        if r.event_type not in by_event:
            # Stale row (event removed from registry); skip rather than
            # surface a key the frontend can't render.
            continue
        if r.channel == "in_app":
            by_event[r.event_type].in_app = bool(r.enabled)
        elif r.channel == "email":
            by_event[r.event_type].email = bool(r.enabled)

    return PreferencesOut(
        preferences=by_event,
        digest_cadence=current_user.digest_cadence,
        quiet_hours_enabled=bool(current_user.quiet_hours_enabled),
        timezone=current_user.timezone,
        notification_intro_dismissed=bool(current_user.notification_intro_dismissed),
    )


# ---------------------------------------------------------------------------
# PATCH /api/notifications/preferences
# ---------------------------------------------------------------------------

@router.patch("/preferences", response_model=PreferencesOut)
def update_preferences(
    body: PreferencesPatch,
    request: Request,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Partial update of the caller's notification preferences.

    Body shape::

        {
          "preferences": {
              "comment.replied": {"in_app": true, "email": false},
              "follow.requested": {"in_app": true}
          },
          "digest_cadence": "daily",
          "quiet_hours_enabled": true,
          "timezone": "America/Los_Angeles",
          "notification_intro_dismissed": true
        }

    All top-level fields are optional. Inside ``preferences`` only listed
    event types are touched; unspecified events are unchanged. Inside each
    per-event sub-dict, omitting ``in_app`` or ``email`` leaves that
    channel unchanged.

    Audited as ``notifications.preferences_updated`` with the change-set.
    """
    diff: dict[str, Any] = {}

    # Validate top-level enum-like fields up front so we 400 cleanly
    # before mutating anything.
    if body.digest_cadence is not None:
        if body.digest_cadence not in _VALID_DIGEST_CADENCES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"digest_cadence must be one of "
                    f"{sorted(_VALID_DIGEST_CADENCES)}; got "
                    f"{body.digest_cadence!r}"
                ),
            )

    if body.preferences:
        for ev_key in body.preferences.keys():
            if not is_known_event_type(ev_key):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Unknown event_type {ev_key!r}; not in "
                        f"EVENT_REGISTRY"
                    ),
                )

    # Top-level user columns.
    if body.digest_cadence is not None and body.digest_cadence != current_user.digest_cadence:
        diff["digest_cadence"] = {
            "old": current_user.digest_cadence,
            "new": body.digest_cadence,
        }
        current_user.digest_cadence = body.digest_cadence

    if body.quiet_hours_enabled is not None and bool(body.quiet_hours_enabled) != bool(current_user.quiet_hours_enabled):
        diff["quiet_hours_enabled"] = {
            "old": bool(current_user.quiet_hours_enabled),
            "new": bool(body.quiet_hours_enabled),
        }
        current_user.quiet_hours_enabled = bool(body.quiet_hours_enabled)

    if body.timezone is not None and body.timezone != current_user.timezone:
        diff["timezone"] = {
            "old": current_user.timezone,
            "new": body.timezone,
        }
        current_user.timezone = body.timezone or None

    if (
        body.notification_intro_dismissed is not None
        and bool(body.notification_intro_dismissed) != bool(current_user.notification_intro_dismissed)
    ):
        diff["notification_intro_dismissed"] = {
            "old": bool(current_user.notification_intro_dismissed),
            "new": bool(body.notification_intro_dismissed),
        }
        current_user.notification_intro_dismissed = bool(body.notification_intro_dismissed)

    # Per-event channel toggles. Upsert one row per (event_type, channel)
    # touched.
    pref_changes: dict[str, dict[str, dict[str, bool]]] = {}
    if body.preferences:
        for ev_key, sub in body.preferences.items():
            for channel, new_val in (("in_app", sub.in_app), ("email", sub.email)):
                if new_val is None:
                    continue
                row = (
                    db.query(models.NotificationPreference)
                    .filter(
                        models.NotificationPreference.user_id == current_user.id,
                        models.NotificationPreference.event_type == ev_key,
                        models.NotificationPreference.channel == channel,
                    )
                    .first()
                )
                old_val = bool(row.enabled) if row is not None else False
                if old_val == bool(new_val):
                    continue
                if row is None:
                    row = models.NotificationPreference(
                        user_id=current_user.id,
                        event_type=ev_key,
                        channel=channel,
                        enabled=bool(new_val),
                    )
                    db.add(row)
                else:
                    row.enabled = bool(new_val)
                pref_changes.setdefault(ev_key, {})[channel] = {
                    "old": old_val, "new": bool(new_val),
                }
    if pref_changes:
        diff["preferences"] = pref_changes

    if diff:
        log_audit_event(
            db,
            action="notifications.preferences_updated",
            target_type="user",
            target_id=current_user.id,
            actor_id=current_user.id,
            details={"changes": diff},
            ip_address=_client_ip(request),
        )

    db.commit()
    db.refresh(current_user)

    # Reuse the GET shape for the response.
    return get_preferences(db=db, current_user=current_user)


# ---------------------------------------------------------------------------
# GET /api/notifications/registry
# ---------------------------------------------------------------------------

@router.get("/registry", response_model=EventRegistryOut)
def get_registry(
    current_user: models.User = Depends(auth_utils.get_current_user),
):
    """Return the EVENT_REGISTRY contents for the preferences UI to render.

    Static data; the caller is welcome to cache aggressively. Auth gate
    is purely to keep the endpoint behind the same shell as the rest of
    the notifications surface — content here is not sensitive.
    """
    from notification_events import CATEGORIES
    return EventRegistryOut(
        events=[
            EventDefinitionOut(
                key=ev.key,
                label=ev.label,
                description=ev.description,
                category=ev.category,
            )
            for ev in EVENT_REGISTRY
        ],
        categories=list(CATEGORIES),
    )


# ---------------------------------------------------------------------------
# GET /api/notifications/unsubscribe/{token}  (PUBLIC — no auth)
# ---------------------------------------------------------------------------
#
# Phase 13 E2 — one-click unsubscribe links in event emails. The link's
# signed token encodes (user_id, event_type) so we can flip the email
# channel preference to False without forcing the recipient to log in.
# Token TTL is 30 days (see ``email_service.UNSUBSCRIBE_TOKEN_TTL_DAYS``).

class UnsubscribeOut(BaseModel):
    success: bool
    event_type: Optional[str] = None
    message: str


@router.get("/unsubscribe/{token}", response_model=UnsubscribeOut)
def unsubscribe_via_token(
    token: str,
    db: Session = Depends(get_db),
):
    """Public unsubscribe endpoint — flips ``(user_id, event_type, "email")``
    preference to False after verifying the signed token.

    Returns a JSON body for v1; the frontend can render a polished page
    in a follow-up pass. Idempotent: repeat calls succeed silently.
    """
    from email_service import decode_unsubscribe_token

    decoded = decode_unsubscribe_token(token)
    if decoded is None:
        # Don't 401 — return a body the user-friendly redirect page can
        # render. The token may simply be expired (30-day TTL).
        return UnsubscribeOut(
            success=False,
            event_type=None,
            message=(
                "This unsubscribe link is invalid or has expired. Please "
                "manage your preferences at /settings/notifications."
            ),
        )
    user_id, event_type = decoded
    if not is_known_event_type(event_type):
        return UnsubscribeOut(
            success=False,
            event_type=event_type,
            message=(
                f"Unknown event type {event_type!r}. The notification system "
                "may have changed since this email was sent."
            ),
        )

    # Upsert the (user, event_type, email) preference to enabled=False.
    pref = (
        db.query(models.NotificationPreference)
        .filter(
            models.NotificationPreference.user_id == user_id,
            models.NotificationPreference.event_type == event_type,
            models.NotificationPreference.channel == "email",
        )
        .first()
    )
    if pref is None:
        pref = models.NotificationPreference(
            user_id=user_id, event_type=event_type, channel="email",
            enabled=False,
        )
        db.add(pref)
    else:
        pref.enabled = False
    db.commit()
    return UnsubscribeOut(
        success=True,
        event_type=event_type,
        message=f"You have been unsubscribed from {event_type} emails.",
    )
