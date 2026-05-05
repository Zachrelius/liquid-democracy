"""Phase 13 — notification event registry.

The 12 notification event definitions shipped in Phase 13. Parallel to the
permission registry (``backend/permission_registry.py``) — a single source
of truth for event metadata that the backend, the API (via
``GET /api/notifications/registry``), and the frontend's preferences-matrix
UI all read.

Adding a new event type
-----------------------

1. Add a new ``EventDefinition`` row below in the appropriate category.
2. Wire emission at the relevant route handler with
   ``emit_notification(..., event_type=<new key>, ...)``.
3. Add a per-event email template (Cluster E) keyed by the same
   ``event_type``.

No schema change is required to add events — ``Notification.event_type``
and ``NotificationPreference.event_type`` are plain string columns.
"""
from __future__ import annotations

from typing import NamedTuple


class EventDefinition(NamedTuple):
    """Metadata for one notification event type.

    ``key`` is the dot-namespaced identifier stored in
    ``Notification.event_type`` (e.g. ``"comment.replied"``).

    ``label`` is a short human-readable label for the preferences matrix
    (e.g. ``"Reply to your comment"``).

    ``description`` is a one-sentence explanation surfaced under the label
    in the preferences UI.

    ``category`` groups events in the matrix; one of the five categories
    listed in ``CATEGORIES``. The frontend renders one section per
    category in display order.
    """
    key: str
    label: str
    description: str
    category: str


CATEGORIES: tuple[str, ...] = (
    "Comments",
    "Proposals",
    "Membership",
    "Delegation",
    "Polis",
)


EVENT_REGISTRY: list[EventDefinition] = [
    # ---- Comments -------------------------------------------------------
    EventDefinition(
        key="comment.replied",
        label="Reply to your comment",
        description="Someone replied to a comment you posted on a proposal.",
        category="Comments",
    ),
    EventDefinition(
        key="comment.posted_on_your_proposal",
        label="Comment on your proposal",
        description="Someone posted a top-level comment on a proposal you authored.",
        category="Comments",
    ),
    # ---- Proposals ------------------------------------------------------
    EventDefinition(
        key="proposal.entered_voting",
        label="Proposal entered voting",
        description="A proposal in your organization moved from deliberation into voting.",
        category="Proposals",
    ),
    EventDefinition(
        key="proposal.closed",
        label="Proposal closed",
        description="A proposal you voted on or authored has reached its outcome.",
        category="Proposals",
    ),
    EventDefinition(
        key="sustained_majority.floor_approached",
        label="Vote support nearing floor",
        description="A proposal's support is approaching the sustained-majority floor.",
        category="Proposals",
    ),
    # ---- Membership -----------------------------------------------------
    EventDefinition(
        key="member.join_request",
        label="New member request to join",
        description="Someone requested to join an organization where you can approve members.",
        category="Membership",
    ),
    EventDefinition(
        key="invitation.accepted",
        label="Invitation accepted",
        description="An invitation you sent was accepted.",
        category="Membership",
    ),
    # ---- Delegation -----------------------------------------------------
    EventDefinition(
        key="delegate.applied",
        label="New delegate application",
        description="Someone applied to become a public delegate in an organization where you can review applications.",
        category="Delegation",
    ),
    EventDefinition(
        key="delegate.application_decided",
        label="Your delegate application",
        description="Your delegate application was approved or denied.",
        category="Delegation",
    ),
    EventDefinition(
        key="follow.requested",
        label="Follow request",
        description="Someone requested to follow you.",
        category="Delegation",
    ),
    EventDefinition(
        key="follow.approved",
        label="Follow approved",
        description="Your request to follow another user was approved.",
        category="Delegation",
    ),
    # ---- Polis ----------------------------------------------------------
    EventDefinition(
        key="polis.created",
        label="New deliberation",
        description="A new Polis deliberation was created in an organization you belong to.",
        category="Polis",
    ),
]


# Convenience: index by key for O(1) lookup.
EVENT_REGISTRY_BY_KEY: dict[str, EventDefinition] = {
    ev.key: ev for ev in EVENT_REGISTRY
}


def is_known_event_type(event_type: str) -> bool:
    """Return True iff ``event_type`` is a key in ``EVENT_REGISTRY``."""
    return event_type in EVENT_REGISTRY_BY_KEY


# Sanity check: every category referenced is in CATEGORIES.
for _ev in EVENT_REGISTRY:
    assert _ev.category in CATEGORIES, (
        f"EventDefinition {_ev.key!r} has unknown category {_ev.category!r}; "
        f"expected one of {CATEGORIES}"
    )
del _ev
