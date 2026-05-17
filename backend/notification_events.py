"""Phase 13 — notification event registry.

The 12 notification event definitions shipped in Phase 13. Parallel to the
permission registry (``backend/permission_registry.py``) — a single source
of truth for event metadata that the backend, the API (via
``GET /api/notifications/registry``), and the frontend's preferences-matrix
UI all read.

Phase 21 (2026-05) extended each ``EventDefinition`` with a
``signal_level`` field ("critical" | "standard" | "ambient" | "always_on")
so the preferences-page preset selector can stamp curated defaults
data-driven from the registry. Five new events were also added covering
delegate-action and voting-deadline gaps in the Phase 13 set.

Adding a new event type
-----------------------

1. Add a new ``EventDefinition`` row below in the appropriate category.
   Choose a ``signal_level`` per D19:
     - ``critical``: high-signal, target-specific, low-volume; nearly
       everyone wants this. In-app on at all presets.
     - ``standard``: meaningful events most users want.
     - ``ambient``: high-volume / low-target-specificity; opt-in for
       most users.
     - ``always_on``: user-initiated-action responses; presets don't
       touch these.
2. Wire emission at the relevant route handler with
   ``emit_notification(..., event_type=<new key>, ...)``.
3. Add a per-event email template (Cluster E) keyed by the same
   ``event_type``.

No schema change is required to add events — ``Notification.event_type``
and ``NotificationPreference.event_type`` are plain string columns.
"""
from __future__ import annotations

from typing import NamedTuple, Optional


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

    ``signal_level`` (Phase 21) is one of ``"critical"``, ``"standard"``,
    ``"ambient"``, ``"always_on"`` and drives the preference-preset
    selector. ``always_on`` events are exempt from preset stamping.
    """
    key: str
    label: str
    description: str
    category: str
    signal_level: str


CATEGORIES: tuple[str, ...] = (
    "Comments",
    "Proposals",
    "Membership",
    "Delegation",
    "Polis",
)


# Valid values for ``EventDefinition.signal_level``. Asserted at module load
# time below; the preset selector (``PRESET_STAMP_RULES`` /
# ``apply_preset_to_preferences``) keys off these.
SIGNAL_LEVELS: tuple[str, ...] = (
    "critical", "standard", "ambient", "always_on",
)


EVENT_REGISTRY: list[EventDefinition] = [
    # ---- Comments -------------------------------------------------------
    EventDefinition(
        key="comment.replied",
        label="Reply to your comment",
        description="Someone replied to a comment you posted on a proposal.",
        category="Comments",
        signal_level="standard",
    ),
    EventDefinition(
        key="comment.posted_on_your_proposal",
        label="Comment on your proposal",
        description="Someone posted a top-level comment on a proposal you authored.",
        category="Comments",
        signal_level="ambient",
    ),
    # ---- Proposals ------------------------------------------------------
    EventDefinition(
        key="proposal.entered_voting",
        label="Proposal entered voting",
        description="A proposal in your organization moved from deliberation into voting.",
        category="Proposals",
        signal_level="standard",
    ),
    EventDefinition(
        key="proposal.entered_voting.you_vote",
        label="Voting opened (you vote)",
        description=(
            "A proposal in your organization moved into voting and you "
            "haven't delegated your vote on its topic. You need to vote "
            "yourself."
        ),
        category="Proposals",
        signal_level="critical",
    ),
    EventDefinition(
        key="proposal.entered_voting.delegated_to_you",
        label="Voting opened (you vote on others' behalf)",
        description=(
            "A proposal moved into voting and someone has delegated their "
            "vote to you on its topic. You're voting on their behalf."
        ),
        category="Proposals",
        signal_level="critical",
    ),
    EventDefinition(
        key="proposal.closed",
        label="Proposal closed",
        description="A proposal you voted on or authored has reached its outcome.",
        category="Proposals",
        signal_level="critical",
    ),
    # Phase 20 — Stable Result Required: voting is extended when the result
    # destabilizes near the closing portion of the voting period. Audience:
    # proposal author + recent voters (last 7 days). Default channel set:
    # in-app + email (matches the floor_approached pattern that this event
    # supersedes).
    EventDefinition(
        key="proposal.extended_by_stability",
        label="Voting extended (Stable Result Required)",
        description=(
            "A proposal you voted on or authored had its voting window "
            "extended because the result destabilized in the closing portion "
            "of the voting period."
        ),
        category="Proposals",
        signal_level="critical",
    ),
    # ---- Membership -----------------------------------------------------
    EventDefinition(
        key="member.join_request",
        label="New member request to join",
        description="Someone requested to join an organization where you can approve members.",
        category="Membership",
        signal_level="standard",
    ),
    EventDefinition(
        key="invitation.accepted",
        label="Invitation accepted",
        description="An invitation you sent was accepted.",
        category="Membership",
        signal_level="always_on",
    ),
    # ---- Delegation -----------------------------------------------------
    # Phase 30.1 B4 — delegate.applied / delegate.application_decided
    # event definitions removed alongside the legacy
    # DelegateApplication surface. The Phase 19 events
    # (delegate_application_submitted / delegate_application_approved /
    # delegate_application_denied) below cover the new lifecycle.
    EventDefinition(
        key="follow.requested",
        label="Follow request",
        description="Someone requested to follow you.",
        category="Delegation",
        signal_level="standard",
    ),
    EventDefinition(
        key="follow.approved",
        label="Follow approved",
        description="Your request to follow another user was approved.",
        category="Delegation",
        signal_level="always_on",
    ),
    # Phase 19 — public-delegate-page approval workflow + hard-revert.
    # The legacy single-step ``delegate.applied`` /
    # ``delegate.application_decided`` events that these supplanted were
    # removed in Phase 30.1 B4 (alongside the DelegateApplication model).
    # These events fire on the per-topic ``DelegateProfile.visibility``
    # lifecycle.
    EventDefinition(
        key="delegate_application_submitted",
        label="New public-delegate application (Phase 19)",
        description="Someone submitted a topic for public-accepting delegate approval in an organization where you can review applications.",
        category="Delegation",
        signal_level="standard",
    ),
    EventDefinition(
        key="delegate_application_approved",
        label="Your public-delegate application was approved",
        description="An approver accepted your request to become a public-accepting delegate on a topic.",
        category="Delegation",
        signal_level="always_on",
    ),
    EventDefinition(
        key="delegate_application_denied",
        label="Your public-delegate application was denied",
        description="An approver denied your request to become a public-accepting delegate on a topic; the denial includes a comment.",
        category="Delegation",
        signal_level="critical",
    ),
    EventDefinition(
        key="delegation_revoked_by_delegate",
        label="A delegate stopped publicly accepting delegation",
        description="Your public-origin delegation on a topic was revoked because the delegate stopped publicly accepting delegation on it.",
        category="Delegation",
        signal_level="critical",
    ),
    # ---- Delegation (Phase 21) ------------------------------------------
    EventDefinition(
        key="delegate.voted",
        label="Your delegate cast a vote",
        description="Your delegate on this proposal's topic has cast their vote.",
        category="Delegation",
        signal_level="standard",
    ),
    EventDefinition(
        key="delegate.vote_changed",
        label="Your delegate changed their vote",
        description="Your delegate on this proposal's topic changed their existing vote.",
        category="Delegation",
        signal_level="critical",
    ),
    EventDefinition(
        key="delegate.posted_rationale",
        label="Your delegate posted a vote rationale",
        description="Your delegate published their reasoning on a proposal where the topic is in public state.",
        category="Delegation",
        signal_level="standard",
    ),
    EventDefinition(
        key="voting.halfway_delegate_silent",
        label="Voting half-elapsed; your delegate hasn't voted",
        description="A proposal is halfway through its voting period and your delegate on the topic hasn't cast a vote yet.",
        category="Delegation",
        signal_level="critical",
    ),
    # ---- Proposals (Phase 21) -------------------------------------------
    EventDefinition(
        key="voting.halfway_you_havent_voted",
        label="Voting half-elapsed; you haven't voted",
        description="A proposal is halfway through its voting period and you haven't cast a vote (you're not delegated on its topic).",
        category="Proposals",
        signal_level="critical",
    ),
    # ---- Polis ----------------------------------------------------------
    EventDefinition(
        key="polis.created",
        label="New deliberation",
        description="A new Polis deliberation was created in an organization you belong to.",
        category="Polis",
        signal_level="ambient",
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

# Sanity check: every signal_level is one of the four valid values
# (Phase 21). Mirrors the category check above so a typo at registry-edit
# time fails loudly at import.
for _ev in EVENT_REGISTRY:
    assert _ev.signal_level in SIGNAL_LEVELS, (
        f"EventDefinition {_ev.key!r} has unknown signal_level "
        f"{_ev.signal_level!r}; expected one of {SIGNAL_LEVELS}"
    )
del _ev


# ---------------------------------------------------------------------------
# Phase 21 — preset stamping rules
# ---------------------------------------------------------------------------
#
# Three preset levels (High / Medium / Low engagement) stamp curated channel
# defaults across all non-``always_on`` events. Each preset is a
# ``{signal_level -> {channel -> bool}}`` mapping; ``apply_preset_to_preferences``
# walks ``EVENT_REGISTRY`` and writes the corresponding sub-dict to each
# non-``always_on`` event.
#
# The 4-channel structure (``in_app``, ``email_immediate``, ``email_daily``,
# ``email_weekly``) is Phase 13.3's; presets always stamp at-most-one email
# channel per event (redundancy isn't typical), but the underlying schema
# permits multiple email channels per event and the per-event UI continues
# to render the three email channels as independent toggles. Presets are
# starting points, not enforced shapes.
#
# Always-on events keep their current values regardless of preset chosen.

PRESET_STAMP_RULES: dict[str, dict[str, dict[str, bool]]] = {
    "high": {
        "critical": {"in_app": True, "email_immediate": True,  "email_daily": False, "email_weekly": False},
        "standard": {"in_app": True, "email_immediate": False, "email_daily": True,  "email_weekly": False},
        "ambient":  {"in_app": True, "email_immediate": False, "email_daily": False, "email_weekly": True},
        # ``always_on`` intentionally absent — preset doesn't touch it.
    },
    "medium": {
        "critical": {"in_app": True,  "email_immediate": False, "email_daily": True,  "email_weekly": False},
        "standard": {"in_app": True,  "email_immediate": False, "email_daily": False, "email_weekly": True},
        "ambient":  {"in_app": False, "email_immediate": False, "email_daily": False, "email_weekly": False},
    },
    "low": {
        "critical": {"in_app": True,  "email_immediate": False, "email_daily": False, "email_weekly": True},
        "standard": {"in_app": False, "email_immediate": False, "email_daily": False, "email_weekly": False},
        "ambient":  {"in_app": False, "email_immediate": False, "email_daily": False, "email_weekly": False},
    },
}


def apply_preset_to_preferences(
    preset: str,
    current_prefs: dict,
) -> dict:
    """Return an updated preference dict with the preset applied to every
    non-``always_on`` event in ``EVENT_REGISTRY``.

    ``current_prefs`` is a ``{event_key: {channel: bool}}`` dict; the
    returned dict is a shallow copy with the preset's stamped values
    overwriting each non-``always_on`` event's sub-dict. ``always_on``
    events are passed through unchanged (preset selector is a curated-set
    shortcut, not a destructive wipe — user-initiated-response events
    stay as the user has configured them).

    Raises ``ValueError`` on an unknown preset name.
    """
    if preset not in PRESET_STAMP_RULES:
        raise ValueError(f"Unknown preset: {preset}")
    rules = PRESET_STAMP_RULES[preset]
    updated = dict(current_prefs)
    for ev in EVENT_REGISTRY:
        if ev.signal_level == "always_on":
            continue
        if ev.signal_level in rules:
            # Fresh dict per event so callers can't mutate the rule
            # table through an aliased reference.
            updated[ev.key] = dict(rules[ev.signal_level])
    return updated


def detect_matching_preset(prefs: dict) -> Optional[str]:
    """Return the preset name (``"high"``, ``"medium"``, ``"low"``) whose
    stamped output exactly matches the given prefs, or ``None`` if no
    preset matches.

    Compares only the keys produced by ``apply_preset_to_preferences(preset, {})``
    — i.e. ignores ``always_on`` events (presets don't stamp them) and
    any extra keys in ``prefs``. The match is exact on the four channel
    booleans per event.

    Used by the frontend preferences page's "matching preset" indicator
    so it can highlight which preset the user's current settings reflect
    (or surface "Custom" when none match).
    """
    for preset_name in ("high", "medium", "low"):
        expected = apply_preset_to_preferences(preset_name, {})
        if all(
            prefs.get(key) == expected.get(key)
            for key in expected.keys()
        ):
            return preset_name
    return None
