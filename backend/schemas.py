from datetime import date, datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, field_validator, Field, model_validator
import re
import nh3
import uuid as _uuid_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sanitize_markdown(text: str) -> str:
    """Strip unsafe HTML from markdown bodies to prevent XSS."""
    # Allow a safe subset of HTML tags that markdown renderers emit.
    return nh3.clean(
        text,
        tags={
            "a", "abbr", "b", "blockquote", "br", "caption", "cite", "code",
            "col", "colgroup", "dd", "del", "details", "dfn", "div", "dl",
            "dt", "em", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i",
            "img", "ins", "kbd", "li", "mark", "ol", "p", "pre", "q", "rp",
            "rt", "ruby", "s", "samp", "small", "span", "strong", "sub",
            "summary", "sup", "table", "tbody", "td", "th", "thead", "time",
            "tr", "ul", "var",
        },
    )


def _validate_uuid(v: str) -> str:
    try:
        _uuid_mod.UUID(v)
    except ValueError:
        raise ValueError(f"Invalid UUID: {v!r}")
    return v


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    display_name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=8, max_length=128)
    # Phase 9.7 W1 — when present, registration consumes the invitation
    # (creates an OrgMembership in the inviting org, marks the invitation
    # accepted, and skips the IS_PUBLIC_DEMO=true demo auto-join). Email on
    # the request body must match the invitation's invited email
    # (case-insensitive).
    invitation_token: Optional[str] = Field(default=None, max_length=200)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)
    # Phase 9.7 W1 — see RegisterRequest. After successful auth, if the
    # invitation token resolves to a pending invitation for the user's
    # email, an OrgMembership is created (or the existing one is left in
    # place idempotently) and the invitation is marked accepted.
    invitation_token: Optional[str] = Field(default=None, max_length=200)


# Phase 9.7 W5 — public invitation metadata response. Surfaced via
# `GET /api/invitations/{token}/meta` so the frontend InviteAccept page can
# render the right state without consuming the token.
class InvitationMetaOut(BaseModel):
    org_name: str
    org_slug: str
    invited_email: str
    role: str
    expires_at: datetime


class DemoLoginRequest(BaseModel):
    """Passwordless login for whitelisted demo personas (Phase 6.5).

    The handler validates the persona against the per-org allowlist
    stored in ``Organization.personas`` JSONB. ``org_slug`` was extended
    as Optional for the Phase 23 transition window; Phase 38 B7 removed
    the legacy ``org_slug=None`` branch from the handler so a missing
    value now returns 400 explicitly. The field remains Optional here so
    request-validation errors stay loud at the route layer rather than
    being swallowed as a 422 schema rejection.
    """
    username: str = Field(min_length=1, max_length=50)
    org_slug: Optional[str] = Field(default=None, max_length=100)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: str
    username: str
    display_name: str
    email: Optional[str] = None
    email_verified: bool = False
    is_admin: bool
    user_type: str
    delegation_strategy: str
    default_follow_policy: str
    # Phase 9.8 — relative path under /uploads when set; null for users
    # who haven't uploaded an avatar (frontend renders an initials fallback).
    avatar_url: Optional[str] = None
    created_at: datetime
    # Phase 51 — verification state, jurisdiction, provenance, and
    # last-updated timestamp. These four fields are safe to surface to
    # the client and drive the read-only "Verification: …" display
    # plus the Phase 52 "verify now" prompts. The internal
    # ``verification_attestation_id`` and ``verification_nullifier``
    # are NOT exposed — they're cross-org correlation primitives that
    # must stay platform-internal.
    verification_state: str = "email_only"
    verification_jurisdiction: Optional[str] = None
    verification_provenance: str = "none"
    verification_updated_at: Optional[datetime] = None
    # Phase 77 — direct-message opt-out (drives the Settings toggle).
    dm_disabled: bool = False

    model_config = {"from_attributes": True}


class DelegationStrategyUpdate(BaseModel):
    """Phase 27 B4 — body for PATCH /api/users/me/delegation-strategy.

    Validation of allowed values lives in the route handler so the
    error message can enumerate them; the schema-level validator would
    only emit a 422 with a less useful detail string.
    """
    strategy: str


class RegisterResponse(BaseModel):
    """Registration response — includes is_first_user flag for first-run setup."""
    id: str
    username: str
    display_name: str
    email: Optional[str] = None
    email_verified: bool = False
    is_admin: bool
    user_type: str
    delegation_strategy: str
    default_follow_policy: str
    # Phase 9.8 — see UserOut.avatar_url.
    avatar_url: Optional[str] = None
    created_at: datetime
    is_first_user: bool = False

    model_config = {"from_attributes": True}


class SetupStatusOut(BaseModel):
    needs_setup: bool
    has_orgs: bool
    has_topics: bool


class UserUpdate(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    default_follow_policy: Optional[str] = None
    # Phase 77 — per-user opt-out of new direct-message conversation
    # initiations from other members.
    dm_disabled: Optional[bool] = None

    @field_validator("default_follow_policy")
    @classmethod
    def validate_policy(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("require_approval", "auto_approve_view", "auto_approve_delegate"):
            raise ValueError("Invalid follow policy")
        return v


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=128)


class VerifyEmailRequest(BaseModel):
    token: str


class ResendVerificationRequest(BaseModel):
    pass


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254)


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class UserSearchResult(BaseModel):
    """Lightweight user info returned by search — no voting records."""
    id: str
    username: str
    display_name: str
    # Phase 9.8 — see UserOut.avatar_url.
    avatar_url: Optional[str] = None

    model_config = {"from_attributes": True}


class UserSearchResultWithContext(BaseModel):
    """Search result enriched with follow/delegate context for the viewer."""
    id: str
    username: str
    display_name: str
    # Phase 9.8 — see UserOut.avatar_url.
    avatar_url: Optional[str] = None
    # Delegate profiles (active)
    delegate_profiles: list["DelegateProfileOut"] = []
    # Relationship with the viewer
    follow_status: Optional[str] = None          # None, "following", "pending"
    follow_permission: Optional[str] = None      # view_only, delegation_allowed
    follow_relationship_id: Optional[str] = None
    pending_request_id: Optional[str] = None
    # Whether there's a pending delegation intent to this user
    has_pending_intent: bool = False


# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------

class TopicCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    # Phase 33 D2 — `description` removed; the field accepted from API requests
    # is preserved on the request schema as ignored-extra so older clients
    # don't 422. Pydantic's default behavior allows unknown fields silently.
    color: str = "#6366f1"
    # Phase 8.5: optional sub-org scope. NULL = parent-org-wide (default).
    sub_org_id: Optional[str] = None
    # Phase 56 — optional purpose (plain text, max 500) and category
    # (free-text label, max 80). Both default to None / NULL on the row.
    # Purpose is NEVER used as a display-name fallback (Phase 33 guard).
    purpose: Optional[str] = Field(default=None, max_length=500)
    category: Optional[str] = Field(default=None, max_length=80)
    # Phase 65 — per-topic delegation disallow flag. True (today's
    # behavior) when the caller omits it; False makes proposals touching
    # this topic direct-vote-only.
    allow_delegation: bool = True

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: str) -> str:
        # Phase 56 B2 — converge on the shared hex-regex validator used by
        # branding so the topic color path rejects var() strings and other
        # malformed shapes (the prior hand-rolled startswith('#') + length
        # check wrongly accepted '#zzz' and rejected legitimate colors
        # only because of the var(--brand-*) presets in the FE).
        # The shared helper accepts None as "leave unchanged" — topic
        # color is non-nullable with a default, so we forward None to it
        # only when the caller explicitly clears the field (it won't,
        # since the FE always sends a hex), and re-raise on None reaching
        # the persistence layer.
        validated = _validate_hex_color(v)
        if validated is None:
            raise ValueError(
                "color must be a hex string in #RRGGBB or #RGB form"
            )
        return validated


class TopicOut(BaseModel):
    id: str
    name: str
    color: str
    # Phase 8.5: NULL for parent-org-wide topics. Tests/clients can rely on
    # this to render scope badges; existing single-org clients receive None
    # everywhere and behave unchanged.
    sub_org_id: Optional[str] = None
    # Phase 56 — optional purpose + category surface on every TopicOut so
    # the FE can render subtitles and category grouping. Both NULL on
    # existing topics; the FE handles None gracefully.
    purpose: Optional[str] = None
    category: Optional[str] = None
    # Phase 65 — surfaced so the FE can render the per-topic "Allow
    # delegation" toggle + inert-delegation labeling. True on every
    # pre-existing topic (server_default).
    allow_delegation: bool = True

    model_config = {"from_attributes": True}


class ProposalTopicOut(BaseModel):
    """Topic with its relevance score for a specific proposal."""
    topic_id: str
    topic: TopicOut
    relevance: float

    model_config = {"from_attributes": True}


class TopicWithRelevance(BaseModel):
    """Input: topic_id plus optional relevance score."""
    topic_id: str = Field(min_length=1)
    relevance: float = Field(default=1.0, ge=0.0, le=1.0)

    @field_validator("topic_id")
    @classmethod
    def validate_topic_id(cls, v: str) -> str:
        return _validate_uuid(v)


# ---------------------------------------------------------------------------
# Proposals
# ---------------------------------------------------------------------------

def _normalise_topics(v: Any) -> list[TopicWithRelevance]:
    """
    Accept either:
      - old format: ["uuid1", "uuid2"]
      - new format: [{"topic_id": "uuid1", "relevance": 0.8}, ...]
      - mixed is fine too
    Always returns list[TopicWithRelevance].
    """
    result = []
    for item in v:
        if isinstance(item, str):
            result.append(TopicWithRelevance(topic_id=item, relevance=1.0))
        elif isinstance(item, dict):
            result.append(TopicWithRelevance(**item))
        elif isinstance(item, TopicWithRelevance):
            result.append(item)
        else:
            raise ValueError(f"Invalid topic entry: {item!r}")
    return result


class TierOptionCreate(BaseModel):
    """Phase 74b — one variant of a tier-parent project item, nested under the
    parent at create time. The server expands each into a child ProposalOption
    row (budget_kind='discrete', budget_tier_parent_id=parent.id,
    budget_floor_amount=cost) so the not-yet-created parent's id doesn't need to
    be referenced client-side."""
    label: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    budget_floor_amount: float = Field(gt=0)


class OptionCreate(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    # Phase 73 — allocation bucket ceiling. NULL = no ceiling (bucket can
    # absorb the whole envelope). Ignored for non-budget proposals.
    budget_max_amount: Optional[float] = Field(default=None, ge=0)
    # Phase 74 — discrete project-item cost metadata. NULL on non-project
    # options. budget_floor_amount is the all-or-nothing cost. budget_kind ∈
    # {discrete, continuous-as-discrete (74a), tier_parent (74b)}.
    # (mandatory-minimum was cut; its column dropped in 74a.)
    budget_floor_amount: Optional[float] = Field(default=None, ge=0)
    budget_kind: Optional[str] = Field(default=None)
    budget_tier_parent_id: Optional[str] = Field(default=None)
    tier_allow_fallback: Optional[bool] = Field(default=None)
    # Phase 74b — for a budget_kind=='tier_parent' option, its variants (nested
    # at create; the server expands them into child option rows).
    tiers: Optional[list[TierOptionCreate]] = Field(default=None)


class OptionOut(BaseModel):
    id: str
    proposal_id: str
    label: str
    description: str
    display_order: int
    created_at: datetime
    # Phase 32 W1 — write-in attribution. NULL/false on original options
    # that were created at proposal-create time.
    added_by_user_id: Optional[str] = None
    added_at: Optional[datetime] = None
    is_write_in: bool = False
    # Phase 73 — allocation bucket ceiling (NULL on non-budget options).
    budget_max_amount: Optional[float] = None
    # Phase 74 — discrete project-item cost metadata (NULL on non-project).
    budget_floor_amount: Optional[float] = None
    budget_kind: Optional[str] = None
    budget_tier_parent_id: Optional[str] = None
    tier_allow_fallback: Optional[bool] = None

    model_config = {"from_attributes": True}


class WriteInOptionCreate(BaseModel):
    """Phase 32 W2 — body for ``POST /api/proposals/{id}/options``."""
    label: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class OptionTextUpdate(BaseModel):
    """Phase 76b — body for ``PATCH /api/proposals/{id}/options/{option_id}``.

    In-place edit of an existing option's display text (label and/or
    description) during draft / deliberation. Distinct from the proposal
    PATCH ``options`` full-replace: this keeps the option row (and its id),
    so any pre-votes cast during deliberation, write-in attribution, and
    budget metadata survive untouched. Both fields are optional; only those
    present in the request are applied (``model_fields_set``)."""
    label: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)


# Phase 66 — multi-winner approval selection config validation. Shared by
# ProposalCreate + ProposalUpdate so both paths enforce identical shape
# rules at the schema layer (422 on violation). Method-compatibility
# (approval only, never elections) is enforced at the route layer (400)
# because it needs the proposal/org context.
_APPROVAL_WINNER_CONFIG_KEYS = {
    "min_winners", "max_winners", "approval_threshold",
}


def _validate_approval_winner_config(v: Optional[dict]) -> Optional[dict]:
    """Validate + normalize an ``approval_winner_config`` object.

    Shape: ``{min_winners: int>=0, max_winners: int>=1|null,
    approval_threshold: float in (0,1]|null}``. ``approval_threshold``
    is a FRACTION of ballots cast (mirrors ``pass_threshold``
    conventions — D2). Cross-field rules: ``max_winners >=
    min_winners`` when both set; at least one of ``min_winners > 0`` /
    ``approval_threshold`` set (a config that can never seat anyone is
    rejected as vacuous).

    Returns the canonical three-key form (missing optional keys
    normalized to their defaults) or None.
    """
    if v is None:
        return None
    if not isinstance(v, dict):
        raise ValueError("approval_winner_config must be an object")
    unknown = set(v.keys()) - _APPROVAL_WINNER_CONFIG_KEYS
    if unknown:
        raise ValueError(
            f"approval_winner_config has unknown keys: {sorted(unknown)}. "
            f"Allowed: {sorted(_APPROVAL_WINNER_CONFIG_KEYS)}."
        )
    min_w = v.get("min_winners", 0)
    if isinstance(min_w, bool) or not isinstance(min_w, int) or min_w < 0:
        raise ValueError(
            "approval_winner_config.min_winners must be an integer >= 0"
        )
    max_w = v.get("max_winners")
    if max_w is not None and (
        isinstance(max_w, bool) or not isinstance(max_w, int) or max_w < 1
    ):
        raise ValueError(
            "approval_winner_config.max_winners must be an integer >= 1 "
            "or null"
        )
    thr = v.get("approval_threshold")
    if thr is not None:
        if isinstance(thr, bool) or not isinstance(thr, (int, float)):
            raise ValueError(
                "approval_winner_config.approval_threshold must be a "
                "number in (0, 1] or null"
            )
        if not (0.0 < float(thr) <= 1.0):
            raise ValueError(
                "approval_winner_config.approval_threshold must be in "
                "(0, 1] (a fraction of ballots cast)"
            )
    if max_w is not None and max_w < min_w:
        raise ValueError(
            "approval_winner_config.max_winners must be >= min_winners"
        )
    if min_w == 0 and thr is None:
        raise ValueError(
            "approval_winner_config is vacuous: set min_winners > 0 "
            "and/or approval_threshold"
        )
    return {
        "min_winners": min_w,
        "max_winners": max_w,
        "approval_threshold": float(thr) if thr is not None else None,
    }


# Phase 73 — budget-voting config validation. Shared by ProposalCreate +
# ProposalUpdate. Phase 73 ships allocation mode; Phase 74 adds project mode.
_BUDGET_ALLOCATION_KEYS = {"mode", "envelope", "currency", "aggregation"}
_BUDGET_PROJECT_KEYS = {"mode", "envelope", "currency", "min_spend", "max_spend"}
_BUDGET_AGGREGATIONS = {"median", "trimmed_mean"}


def _pos_number(v, name: str, *, allow_zero: bool = False) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f"budget_config.{name} must be a number")
    if allow_zero and v < 0:
        raise ValueError(f"budget_config.{name} must be >= 0")
    if not allow_zero and v <= 0:
        raise ValueError(f"budget_config.{name} must be a positive number")
    return v


def _validate_budget_config(v: Optional[dict]) -> Optional[dict]:
    """Validate + normalize a ``budget_config`` object (allocation OR project
    mode). Method-compatibility (mode matching the voting_method) is enforced
    at the route layer; this validator just enforces shape.
    """
    if v is None:
        return None
    if not isinstance(v, dict):
        raise ValueError("budget_config must be an object")
    mode = v.get("mode")
    if mode == "allocation":
        unknown = set(v) - _BUDGET_ALLOCATION_KEYS
        if unknown:
            raise ValueError(
                f"budget_config has unknown keys: {sorted(unknown)}. "
                f"Allowed: {sorted(_BUDGET_ALLOCATION_KEYS)}"
            )
        envelope = _pos_number(v.get("envelope"), "envelope")
        aggregation = v.get("aggregation", "median")
        if aggregation not in _BUDGET_AGGREGATIONS:
            raise ValueError(
                "budget_config.aggregation must be 'median' or 'trimmed_mean'"
            )
        currency = v.get("currency", "USD")
        if not isinstance(currency, str) or not currency:
            raise ValueError("budget_config.currency must be a non-empty string")
        return {
            "mode": "allocation", "envelope": envelope,
            "currency": currency, "aggregation": aggregation,
        }
    if mode == "project":
        # Phase 74 — discrete project budget. envelope is the hard ceiling;
        # [min_spend, max_spend] is the stop-rule spend band.
        unknown = set(v) - _BUDGET_PROJECT_KEYS
        if unknown:
            raise ValueError(
                f"budget_config has unknown keys: {sorted(unknown)}. "
                f"Allowed: {sorted(_BUDGET_PROJECT_KEYS)}"
            )
        envelope = _pos_number(v.get("envelope"), "envelope")
        min_spend = _pos_number(v.get("min_spend", 0), "min_spend", allow_zero=True)
        max_spend = _pos_number(v.get("max_spend", envelope), "max_spend", allow_zero=True)
        if not (min_spend <= max_spend <= envelope):
            raise ValueError(
                "budget_config requires 0 <= min_spend <= max_spend <= envelope"
            )
        currency = v.get("currency", "USD")
        if not isinstance(currency, str) or not currency:
            raise ValueError("budget_config.currency must be a non-empty string")
        return {
            "mode": "project", "envelope": envelope, "currency": currency,
            "min_spend": min_spend, "max_spend": max_spend,
        }
    raise ValueError("budget_config.mode must be 'allocation' or 'project'")


# Phase 73 — the canonical set of accepted voting methods. Centralized so the
# create + update validators stay in lockstep when a method is added. Phase 74
# adds budget_project.
_VOTING_METHODS = {
    "binary", "approval", "ranked_choice", "budget_allocation", "budget_project",
}


class ProposalCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    body: str = Field(default="", max_length=50000)
    # Accepts plain UUID strings (relevance defaults to 1.0) OR dicts with relevance
    topics: list[Any] = Field(default=[])
    pass_threshold: float = Field(default=0.50, ge=0.0, le=1.0)
    quorum_threshold: float = Field(default=0.40, ge=0.0, le=1.0)
    voting_method: str = "binary"
    options: list[OptionCreate] = Field(default=[])
    num_winners: int = Field(default=1, ge=1)
    # Phase 8 / Phase 20 — per-proposal "Stable Result Required" override.
    # null = inherit org default; True/False = explicit. Server rejects
    # non-null when org has `stable_result_per_proposal_override: false`.
    stable_result_required: Optional[bool] = None
    # Phase 8.5: optional sub-org scope. NULL = parent-org-wide (default).
    # If non-null, all referenced topics must be either parent-org-wide or
    # the same sub-org's; eligibility derives via SubOrgMembership.
    sub_org_id: Optional[str] = None
    # Phase 9 Decision 2 / Decision 7: structurally-recorded Polis links.
    # Validated at route layer (each ID must exist, viewer must be in
    # eligible_viewers_for_polis, status must be active). Required when
    # the org's `require_polis_for_new_proposals` config is True.
    linked_polis_ids: Optional[list[str]] = None
    # Phase 16 — per-proposal duration overrides. Setting either to a
    # value differing from the org's default requires the
    # `proposal.set_durations` permission; values matching the default
    # are accepted from any caller. Both default to None so the route
    # can distinguish "omitted" from "explicitly equal to default".
    # Floor validation is enforced in the route handler (NOT via Pydantic
    # ge=) so a below-floor value returns HTTP 400 with a friendly message,
    # not a 422 schema-validation error: voting_days >= 0.05 (72 minutes),
    # deliberation_days >= 0 (zero is valid; negative is rejected).
    deliberation_days: Optional[float] = Field(default=None)
    voting_days: Optional[float] = Field(default=None)
    # Phase 75a — absolute voting deadline (alternative to voting_days). When
    # set, wins over voting_days at advance time. Accepted at create with no
    # staleness check (the proposal may sit in draft); validated at advance.
    voting_end_date: Optional[datetime] = Field(default=None)
    # Phase 32 — per-proposal overrides for the three new deliberation-
    # engagement features. All Optional; null = inherit org default.
    allow_write_in_options: Optional[bool] = None
    allow_write_ins_during_voting: Optional[bool] = None
    max_write_ins: Optional[int] = Field(default=None, ge=1, le=100)
    allow_pre_voting: Optional[bool] = None
    show_votes_during_deliberation: Optional[bool] = None
    edit_lockout_fraction: Optional[float] = Field(
        default=None, ge=0.0, le=1.0,
    )
    # Phase 52 Stage 1 — per-proposal verification gate. NULL =
    # ungated (today's behavior). When set to a valid floor, casting
    # a direct vote requires the user satisfy it; the tally side
    # narrows the eligible set per the org's
    # ``verification_delegation_carries_weight`` setting.
    verification_floor: Optional[str] = None
    verification_jurisdiction: Optional[str] = None
    # Phase 66 — multi-winner approval selection config. NULL = legacy
    # single-winner behavior. Approval voting_method only (route layer
    # 400s on other methods + on elections). Shape validated below.
    approval_winner_config: Optional[dict] = None
    # Phase 73 — budget-voting config. NULL = not a budget proposal. Required
    # (route layer) when voting_method == "budget_allocation". Shape validated
    # below; method/mode coherence enforced at the route layer.
    budget_config: Optional[dict] = None

    @field_validator("voting_method")
    @classmethod
    def validate_voting_method(cls, v: str) -> str:
        if v not in _VOTING_METHODS:
            raise ValueError(
                "voting_method must be binary, approval, ranked_choice, or "
                "budget_allocation"
            )
        return v

    @field_validator("approval_winner_config")
    @classmethod
    def validate_approval_winner_config(
        cls, v: Optional[dict],
    ) -> Optional[dict]:
        return _validate_approval_winner_config(v)

    @field_validator("budget_config")
    @classmethod
    def validate_budget_config(cls, v: Optional[dict]) -> Optional[dict]:
        return _validate_budget_config(v)

    @field_validator("topics", mode="before")
    @classmethod
    def normalise_topics(cls, v: list) -> list[TopicWithRelevance]:
        return _normalise_topics(v)

    @field_validator("body")
    @classmethod
    def sanitize_body(cls, v: str) -> str:
        return _sanitize_markdown(v)


class ProposalUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=500)
    body: Optional[str] = Field(default=None, max_length=50000)
    topics: Optional[list[Any]] = None
    options: Optional[list[OptionCreate]] = None
    # Phase 59 A4 — voting_method + num_winners are editable WHILE STATUS
    # == 'draft' ONLY. The route handler enforces the draft gate and the
    # option-handling fork (binary↔approval/RCV reshape). Outside draft
    # status these fields are rejected (400).
    voting_method: Optional[str] = Field(default=None)
    num_winners: Optional[int] = Field(default=None, ge=1)
    # Phase 8 / Phase 20 — per-proposal "Stable Result Required" override
    # (see ProposalCreate). Use Field with explicit default sentinel so
    # omitted vs. null differ: we only update the column when the field is
    # present in the payload.
    stable_result_required: Optional[bool] = Field(default=None)
    # Phase 9 — replace the linked-Polis set on update (omitted = leave alone).
    # When present, the route diffs old vs. new and emits
    # `polis.linked_to_proposal` / `polis.unlinked_from_proposal` per change.
    linked_polis_ids: Optional[list[str]] = Field(default=None)
    # Phase 12.5 — per-proposal thresholds. Setting either to a value that
    # differs from the org default requires `proposal.set_thresholds`. Both
    # default to None (omitted) so we can distinguish "not patching" from
    # "patching to a value matching the default."
    pass_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    quorum_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    # Phase 16 — per-proposal duration overrides. Same shape as
    # pass_threshold/quorum_threshold: setting to a value differing from
    # the org's default requires `proposal.set_durations`. Floor checks
    # (voting >= 0.05, deliberation >= 0) are enforced in the route so
    # below-floor values return 400 (not 422). Both default to None.
    deliberation_days: Optional[float] = Field(default=None)
    voting_days: Optional[float] = Field(default=None)
    # Phase 75a — absolute voting deadline, editable like voting_days.
    voting_end_date: Optional[datetime] = Field(default=None)
    # Phase 32 — per-proposal overrides; null = inherit org default.
    allow_write_in_options: Optional[bool] = Field(default=None)
    allow_write_ins_during_voting: Optional[bool] = Field(default=None)
    max_write_ins: Optional[int] = Field(default=None, ge=1, le=100)
    allow_pre_voting: Optional[bool] = Field(default=None)
    show_votes_during_deliberation: Optional[bool] = Field(default=None)
    edit_lockout_fraction: Optional[float] = Field(
        default=None, ge=0.0, le=1.0,
    )
    # Phase 62 A2 — per-proposal verification floor + jurisdiction become
    # editable while status='draft' (matching ProposalCreate). The route
    # enforces the draft-only guard + reuses the create-path normalization
    # block (VALID_STATES + jurisdiction-presence + email_only → NULL).
    # Outside draft these are rejected.
    verification_floor: Optional[str] = Field(default=None)
    verification_jurisdiction: Optional[str] = Field(default=None)
    # Phase 66 — multi-winner approval selection config, editable while
    # status='draft' ONLY (mirrors num_winners / voting_method — the
    # winner-selection rule changes outcome semantics, so it's frozen
    # once the proposal has an audience). Explicit null clears the
    # config (back to legacy single-winner). The route enforces the
    # draft gate, the approval-method-only rule, and the
    # election-rejection rule.
    approval_winner_config: Optional[dict] = Field(default=None)
    # Phase 73 — budget config, editable while status='draft' ONLY (mirrors
    # approval_winner_config — it changes outcome semantics). The route
    # enforces the draft gate + method/mode coherence.
    budget_config: Optional[dict] = Field(default=None)

    @field_validator("approval_winner_config")
    @classmethod
    def validate_approval_winner_config(
        cls, v: Optional[dict],
    ) -> Optional[dict]:
        return _validate_approval_winner_config(v)

    @field_validator("budget_config")
    @classmethod
    def validate_budget_config(cls, v: Optional[dict]) -> Optional[dict]:
        return _validate_budget_config(v)

    @field_validator("topics", mode="before")
    @classmethod
    def normalise_topics(cls, v: Optional[list]) -> Optional[list[TopicWithRelevance]]:
        if v is not None:
            return _normalise_topics(v)
        return v

    @field_validator("body")
    @classmethod
    def sanitize_body(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return _sanitize_markdown(v)
        return v

    @field_validator("voting_method")
    @classmethod
    def validate_voting_method(cls, v: Optional[str]) -> Optional[str]:
        # Phase 59 A4 — same value set as ProposalCreate.
        if v is None:
            return v
        if v not in _VOTING_METHODS:
            raise ValueError(
                "voting_method must be binary, approval, ranked_choice, or "
                "budget_allocation"
            )
        return v


class ProposalOut(BaseModel):
    id: str
    title: str
    body: str
    author_id: str
    author: UserOut
    status: str
    voting_method: str = "binary"
    num_winners: int = 1
    tie_resolution: Optional[dict] = None
    deliberation_start: Optional[datetime]
    voting_start: Optional[datetime]
    voting_end: Optional[datetime]
    pass_threshold: float
    quorum_threshold: float
    # Phase 16 — per-proposal duration overrides; null = inherit org default.
    deliberation_days: Optional[float] = None
    voting_days: Optional[float] = None
    # Phase 75a — absolute voting deadline (NULL = use voting_days/org default).
    voting_end_date: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    topics: list[ProposalTopicOut] = []
    options: list[OptionOut] = []
    # Phase 8 / Phase 20 — null = inherit org default; True/False = explicit
    # override. Renamed in Phase 20 from ``sustained_majority_enabled``.
    stable_result_required: Optional[bool] = None
    # Phase 8.5 — null for parent-org-wide proposals.
    sub_org_id: Optional[str] = None
    # Phase 9 — structurally-linked Polises. Stored on Proposal.linked_polis_ids
    # JSON column; resolved into rich objects on detail GET.
    linked_polis_ids: Optional[list[str]] = None
    linked_polises: Optional[list[dict]] = None
    # Phase 32 — per-proposal overrides for deliberation-engagement
    # features. null = inherit org default.
    allow_write_in_options: Optional[bool] = None
    allow_write_ins_during_voting: Optional[bool] = None
    max_write_ins: Optional[int] = None
    allow_pre_voting: Optional[bool] = None
    show_votes_during_deliberation: Optional[bool] = None
    edit_lockout_fraction: Optional[float] = None
    # Phase 32.2 — resolved-effective values from the 4-option resolver.
    # The frontend uses these (not the raw override columns above) to
    # decide whether to show the +Add option button, the pre-vote
    # panel, etc. Each pair includes `_effective` (the resolved
    # boolean) + `_overridable` (whether the org's mode allows a
    # per-proposal override). Numeric flags expose the resolved value
    # directly.
    effective_allow_write_in_options: bool = False
    effective_allow_write_ins_during_voting: bool = True
    write_in_options_overridable: bool = True
    write_ins_during_voting_overridable: bool = True
    effective_allow_pre_voting: bool = False
    effective_show_votes_during_deliberation: bool = False
    pre_voting_overridable: bool = True
    show_votes_during_deliberation_overridable: bool = True
    effective_max_write_ins: int = 10
    effective_edit_lockout_fraction: float = 0.75

    # Phase 46 — cosign-gated proposal fields (B3). All null/false for
    # non-cosign-gated proposals so existing FE code is unaffected.
    is_cosign_gated: bool = False
    cosign_threshold_snapshot: Optional[int] = None
    cosign_expires_at: Optional[datetime] = None
    cosign_signature_count: int = 0
    # Phase 46a Item 1 — weighted accrual. The threshold is measured
    # in weight, not headcount; the FE shows BOTH the signer count
    # (above) and the live resolved weight (below) so members can see
    # how delegation shifts the bar. 0 for non-cosign-gated.
    cosign_weight: int = 0
    # Phase 48 Stage 1 — election subtype (D1). False for normal
    # proposals — non-election callers see byte-identical responses.
    is_election: bool = False
    election_title_id: Optional[str] = None
    election_title_name: Optional[str] = None
    election_candidates: list[str] = []
    # True iff the requesting viewer has signed (FE renders Sign vs
    # Withdraw accordingly). Null when the request is anonymous / has
    # no auth context.
    viewer_has_cosigned: Optional[bool] = None

    # Phase 52 Stage 1 — per-proposal verification gate.
    # ``verification_floor`` is null for ungated proposals (today's
    # behavior). FE keys the "this proposal requires verification"
    # banner + the disabled "Cast vote" button + the "your delegation
    # didn't carry" surface on these two fields.
    verification_floor: Optional[str] = None
    verification_jurisdiction: Optional[str] = None

    # Phase 65 — True when the proposal is direct-vote-only (org master
    # delegation switch off OR any attached topic disallows delegation).
    # FE keys the proposal-detail "direct vote only" indicator on this so
    # voters know their delegate won't cover them.
    delegation_gated: bool = False

    # Phase 66 — multi-winner approval selection config. NULL for
    # legacy single-winner proposals (all pre-66 rows).
    approval_winner_config: Optional[dict] = None

    # Phase 73 — budget-voting config. NULL = not a budget proposal (every
    # non-budget row). The FE reads this to render the allocation ballot +
    # results UI; it must surface here or the FE silently can't tell a budget
    # proposal apart from a binary one.
    budget_config: Optional[dict] = None

    # Phase 68b — whether the requesting viewer may archive this proposal
    # right now (author in draft/deliberation, proposal.archive holder at
    # any phase, or platform admin). False for anonymous / list contexts
    # where no viewer_id was supplied. The FE gates the "Archive" action
    # on this so it never disagrees with what the endpoint will allow.
    can_archive: bool = False

    # Phase 70 — whether the requesting viewer may advance this proposal to
    # its next status (author / platform admin / proposal.advance_phase
    # holder, AND a next status exists). False for anonymous / list contexts
    # without a viewer_id. The FE gates the author "Advance" control on this
    # so it never disagrees with the /advance endpoint. ``next_status`` is
    # the target status (draft→deliberation, deliberation→voting; null when
    # there's nowhere to advance) so the FE can label the button without
    # re-deriving the transition map.
    can_advance: bool = False
    next_status: Optional[str] = None

    model_config = {"from_attributes": True}


class ProposalRevisionOut(BaseModel):
    """Phase 32 E4 — one row in the proposal change log."""
    id: str
    proposal_id: str
    org_id: str
    edited_by_user_id: str
    edited_at: datetime
    snapshot_before: dict
    snapshot_after: dict
    changed_fields: list[str]
    editor: Optional[UserOut] = None

    model_config = {"from_attributes": True}


class StableResultStatus(BaseModel):
    """Phase 20 — Stable Result Required status block surfaced on /results.

    Populated for every proposal; ``active=False`` for proposals where the
    feature is not in effect (in which case the rest of the fields are at
    sensible defaults and the frontend hides the block).

    Fields:
      - ``stable_window_fraction`` / ``max_extension_fraction``: org-level
        config snapshot (frontend uses to render copy / sliders).
      - ``extension_budget_*_seconds``: budget tracking. Total = original
        voting period * max_extension_fraction. Used = sum of all worker-
        fired extension durations. Remaining = max(0, total - used).
      - ``in_stable_window``: true iff the current time is past the
        original voting period's stable-window start.
      - ``in_extension``: true iff the proposal has had at least one
        worker-fired extension.
      - ``stable_window_starts_at``: timestamp when the original voting
        period's stable window begins. Useful for countdown UI.
      - ``last_destabilization_at``: most recent timestamp at which an
        extension fired (or destabilization-at-max-extensions was logged).
      - ``extension_count``: number of worker-fired extensions to date.
    """
    active: bool = False
    stable_window_fraction: float = 0.25
    max_extension_fraction: float = 0.25
    extension_budget_total_seconds: int = 0
    extension_budget_used_seconds: int = 0
    extension_budget_remaining_seconds: int = 0
    in_stable_window: bool = False
    in_extension: bool = False
    stable_window_starts_at: Optional[datetime] = None
    voting_end: Optional[datetime] = None
    last_destabilization_at: Optional[datetime] = None
    extension_count: int = 0


# Backwards-compat alias for any consumer still using the old name.
# Phase 20 (D13): the user-facing rebrand is "Stable Result Required";
# the legacy class name resolved to the new one for one pass before the
# alias is removed in a future cleanup.
SustainedMajorityStatus = StableResultStatus


class EscalationResolveRequest(BaseModel):
    """POST /api/orgs/{slug}/proposals/{id}/resolve_escalation body."""
    action: str  # "extend" | "fail" | "pass" | "back_to_deliberation"
    reason: Optional[str] = Field(default=None, max_length=2000)
    # Required only for `extend` — new voting_end timestamp.
    new_voting_end: Optional[datetime] = None

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        if v not in ("extend", "fail", "pass", "back_to_deliberation"):
            raise ValueError(
                "action must be extend, fail, pass, or back_to_deliberation"
            )
        return v


# ---------------------------------------------------------------------------
# Delegations
# ---------------------------------------------------------------------------

class DelegationUpsert(BaseModel):
    delegate_id: str
    topic_id: Optional[str] = None  # None = global
    # Phase 18 (D4 / B3): optional sub-org scope. When set, the resulting
    # row is "global within this sub-org" — applies to every topic of that
    # sub-org. The route validates that the sub-org belongs to the parent
    # org from the URL prefix.
    sub_org_id: Optional[str] = None
    chain_behavior: str = "accept_sub"

    @field_validator("delegate_id")
    @classmethod
    def validate_delegate_id(cls, v: str) -> str:
        return _validate_uuid(v)

    @field_validator("topic_id")
    @classmethod
    def validate_topic_id(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return _validate_uuid(v)
        return v

    @field_validator("sub_org_id")
    @classmethod
    def validate_sub_org_id(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return _validate_uuid(v)
        return v

    @field_validator("chain_behavior")
    @classmethod
    def validate_chain_behavior(cls, v: str) -> str:
        allowed = {"accept_sub", "revert_direct", "abstain"}
        if v not in allowed:
            raise ValueError(f"chain_behavior must be one of {allowed}")
        return v


class DelegationOut(BaseModel):
    id: str
    delegator_id: str
    delegate_id: str
    delegate: UserOut
    # Phase 18: org_id + sub_org_id surfaced so the FE can render the
    # "scope" label correctly (org-wide vs sub-org-wide vs topic-scoped).
    # Both are nullable in 18a (backfill running) and become non-null on
    # org_id post-18b. sub_org_id stays optional.
    org_id: Optional[str] = None
    sub_org_id: Optional[str] = None
    topic_id: Optional[str]
    topic: Optional[TopicOut]
    chain_behavior: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Delegation Intents
# ---------------------------------------------------------------------------

class DelegationIntentCreate(BaseModel):
    delegate_id: str
    topic_id: Optional[str] = None
    # Phase 18 (D4 / D5 / B3): same sub-org scope shape as DelegationUpsert.
    # The resulting Delegation row created at activate-time inherits both
    # ``org_id`` (from the URL prefix) and ``sub_org_id`` (from this body).
    sub_org_id: Optional[str] = None
    chain_behavior: str = "accept_sub"

    @field_validator("delegate_id")
    @classmethod
    def validate_delegate_id(cls, v: str) -> str:
        return _validate_uuid(v)

    @field_validator("topic_id")
    @classmethod
    def validate_topic_id(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return _validate_uuid(v)
        return v

    @field_validator("sub_org_id")
    @classmethod
    def validate_sub_org_id(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return _validate_uuid(v)
        return v

    @field_validator("chain_behavior")
    @classmethod
    def validate_chain_behavior(cls, v: str) -> str:
        if v not in ("accept_sub", "revert_direct", "abstain"):
            raise ValueError("chain_behavior must be accept_sub, revert_direct, or abstain")
        return v


class DelegationIntentOut(BaseModel):
    id: str
    delegator_id: str
    delegate_id: str
    delegate: UserSearchResult
    # Phase 18: surface org / sub-org scope on the intent so the FE can
    # display "intent for org X" / "intent for sub-org Y" before activation.
    org_id: Optional[str] = None
    sub_org_id: Optional[str] = None
    topic_id: Optional[str]
    topic: Optional[TopicOut]
    chain_behavior: str
    follow_request_id: str
    status: str
    expires_at: datetime
    created_at: datetime
    activated_at: Optional[datetime]

    model_config = {"from_attributes": True}


class DelegationRequestResult(BaseModel):
    """Response from POST /api/delegations/request"""
    status: str   # "delegated" or "requested"
    message: str
    delegation: Optional[DelegationOut] = None
    intent: Optional[DelegationIntentOut] = None


# ---------------------------------------------------------------------------
# Topic Precedence
# ---------------------------------------------------------------------------

class TopicPrecedenceSet(BaseModel):
    """Ordered list of topic_ids from highest to lowest priority."""
    ordered_topic_ids: list[str]

    @field_validator("ordered_topic_ids", mode="before")
    @classmethod
    def validate_topic_ids(cls, v: list) -> list:
        for tid in v:
            _validate_uuid(tid)
        return v


class TopicPrecedenceOut(BaseModel):
    topic_id: str
    topic: TopicOut
    priority: int

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Votes
# ---------------------------------------------------------------------------

class VoteCast(BaseModel):
    vote_value: Optional[str] = None
    approvals: Optional[list[str]] = None
    ranking: Optional[list[str]] = None
    # Phase 73 — budget_allocation ballot: {option_id: amount}. Each value is
    # a non-negative number; per-bucket cap + sum<=envelope enforced at the
    # route layer (needs the proposal's option ceilings + envelope).
    allocations: Optional[dict[str, float]] = None
    # Phase 74 — budget_project ballot: ordered list of {option_id, tier_id?}
    # (highest priority first). tier_id is forward-compat (Stage-74 core
    # ignores it). Route-layer validates option membership + no duplicates.
    ranked: Optional[list[dict]] = None

    @field_validator("vote_value")
    @classmethod
    def validate_vote_value(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            allowed = {"yes", "no", "abstain"}
            if v not in allowed:
                raise ValueError(f"vote_value must be one of {allowed}")
        return v

    @field_validator("approvals")
    @classmethod
    def validate_approvals(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is not None:
            for oid in v:
                _validate_uuid(oid)
            if len(v) != len(set(v)):
                raise ValueError("Duplicate option IDs in approvals")
        return v

    @field_validator("ranking")
    @classmethod
    def validate_ranking(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is not None:
            for oid in v:
                _validate_uuid(oid)
            if len(v) != len(set(v)):
                raise ValueError("Duplicate option IDs in ranking")
        return v

    @field_validator("allocations")
    @classmethod
    def validate_allocations(
        cls, v: Optional[dict[str, float]],
    ) -> Optional[dict[str, float]]:
        if v is not None:
            for oid, amount in v.items():
                _validate_uuid(oid)
                if isinstance(amount, bool) or not isinstance(amount, (int, float)):
                    raise ValueError("allocation amounts must be numbers")
                if amount < 0:
                    raise ValueError("allocation amounts must be non-negative")
        return v

    @field_validator("ranked")
    @classmethod
    def validate_ranked(cls, v: Optional[list[dict]]) -> Optional[list[dict]]:
        if v is not None:
            seen = set()
            for item in v:
                if not isinstance(item, dict) or "option_id" not in item:
                    raise ValueError("each ranked item must be an object with option_id")
                oid = item["option_id"]
                _validate_uuid(oid)
                if oid in seen:
                    raise ValueError("Duplicate option IDs in ranked")
                seen.add(oid)
                if item.get("tier_id") is not None:
                    _validate_uuid(item["tier_id"])
        return v


class VoteOut(BaseModel):
    id: str
    proposal_id: str
    user_id: str
    vote_value: Optional[str] = None
    ballot: Optional[dict] = None
    is_direct: bool
    delegate_chain: Optional[list[str]]
    cast_by_id: str
    cast_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MyVoteStatus(BaseModel):
    """How the current user's vote is being cast on a proposal."""
    vote_value: Optional[str] = None       # None if not cast (binary)
    approvals: Optional[list[str]] = None  # option IDs approved (approval)
    ranking: Optional[list[str]] = None    # option IDs ordered (ranked_choice)
    # Phase 73 — budget_allocation: {option_id: amount}. Phase 89: may be a
    # delegated ballot (the caller's resolved delegate's allocation).
    allocations: Optional[dict[str, float]] = None
    # Phase 74 — budget_project: ordered [{option_id, tier_id?}]. Phase 89: may
    # be a delegated ballot (the resolved delegate's ranking).
    ranked: Optional[list[dict]] = None
    is_direct: Optional[bool] = None
    delegate_chain: Optional[list[str]] = None
    cast_by: Optional[UserOut] = None
    # Phase 88 — the caller's own effective voting weight (shares) on this
    # proposal, so the ballot UI can show "Your vote carries N shares". None in
    # unweighted orgs (weight is a uniform 1 and the chip is hidden).
    my_voting_weight: Optional[int] = None
    message: str                      # Human-readable explanation
    # True when the user's delegation_strategy is not strict_precedence on a
    # multi-option proposal — strategy fell back since approval/ranked_choice
    # only support strict-precedence today. Frontend renders an info note.
    delegation_strategy_fallback: Optional[bool] = None


# ---------------------------------------------------------------------------
# Tally / Results
# ---------------------------------------------------------------------------

class SnapshotPoint(BaseModel):
    simulated_time: datetime
    yes: int
    no: int
    abstain: int
    not_cast: int
    total_eligible: int


class RCVRoundOut(BaseModel):
    round_number: int
    option_counts: dict[str, float]
    eliminated: Optional[str] = None
    elected: list[str] = []
    transferred_from: Optional[str] = None
    transfer_breakdown: dict[str, float] = {}


class ProposalResults(BaseModel):
    proposal_id: str
    voting_method: str = "binary"
    yes: int = 0
    no: int = 0
    abstain: int = 0
    not_cast: int = 0
    total_eligible: int = 0
    # Total ballots cast on the proposal regardless of voting method —
    # populated for binary/approval/ranked_choice so the proposal-list counter
    # works uniformly. (Phase 7B fix: previously the list page showed
    # "0 of N" for ranked_choice because it summed yes+no+abstain.)
    votes_cast: int = 0
    yes_pct: float = 0.0
    no_pct: float = 0.0
    abstain_pct: float = 0.0
    quorum_met: bool = False
    threshold_met: bool = False
    # Phase 88 — weighted-voting labels. ``weighted`` is True when the org has
    # weighted voting enabled (so every counter above is share-denominated,
    # not headcount); ``unit_label`` is the org's unit noun ("shares" /
    # "units" / …) so the FE can render "1,240 shares yes" without a second
    # fetch. False / None in unweighted orgs (counters mean headcount).
    weighted: bool = False
    unit_label: Optional[str] = None
    time_series: list[SnapshotPoint] = []
    # Approval-voting fields (populated only when voting_method == "approval")
    option_approvals: Optional[dict[str, int]] = None
    option_labels: Optional[dict[str, str]] = None
    total_ballots_cast: Optional[int] = None
    total_abstain: Optional[int] = None
    winners: Optional[list[str]] = None
    tied: Optional[bool] = None
    tie_resolution: Optional[dict] = None
    # Phase 66 — multi-winner approval surface (populated only when
    # voting_method == "approval"). ``winner_seats`` maps each winner
    # to how it seated: "floor" (unconditional min_winners seat),
    # "threshold" (cleared approval_threshold), or "tie_resolution"
    # (chosen by the org's tie resolver at a seat boundary).
    # ``boundary_tied`` + ``seats_remaining`` surface an unresolved
    # boundary tie on a live tally (pre-close). ``approval_winner_config``
    # echoes the proposal's config so the results page can render the
    # selection rule. All None for legacy single-winner proposals.
    winner_seats: Optional[dict[str, str]] = None
    boundary_tied: Optional[list[str]] = None
    seats_remaining: Optional[int] = None
    approval_winner_config: Optional[dict] = None
    # Ranked-choice / STV fields (populated only when voting_method == "ranked_choice")
    rounds: Optional[list[RCVRoundOut]] = None
    method: Optional[str] = None      # "irv" or "stv"
    num_winners: Optional[int] = None
    # Phase 73 — allocation-budget surface (populated only when
    # voting_method == "budget_allocation"). ``budget_amounts`` maps each
    # bucket option_id to its final whole-dollar amount; the amounts sum to
    # ``budget_total_allocated`` (== envelope unless ceilings force a
    # shortfall, surfaced in ``budget_unallocated_remainder``).
    # ``budget_degenerate_no_support`` is True when the group allocated
    # nothing anywhere (all-zero result — the group chose to spend nothing).
    budget_amounts: Optional[dict[str, int]] = None
    budget_total_allocated: Optional[float] = None
    budget_unallocated_remainder: Optional[float] = None
    budget_degenerate_no_support: Optional[bool] = None
    budget_envelope: Optional[float] = None
    budget_currency: Optional[str] = None
    budget_aggregation: Optional[str] = None
    # Phase 74 — project-budget surface (voting_method == "budget_project").
    # ``project_funded`` is the funded set in priority order [{option_id,
    # amount}]; ``project_unfunded`` lists everything not funded (incl. any
    # hard-stop-halted high-priority item). ``project_halt_reason`` is one of
    # "stop_point" | "item_did_not_fit" | "queue_exhausted".
    project_funded: Optional[list[dict]] = None
    project_unfunded: Optional[list[str]] = None
    project_priority_order: Optional[list[str]] = None
    project_total_committed: Optional[float] = None
    project_stop_point: Optional[float] = None
    project_group_desired_total: Optional[float] = None
    project_halt_reason: Optional[str] = None
    project_min_spend: Optional[float] = None
    project_max_spend: Optional[float] = None
    # Phase 8 / Phase 20 — Stable Result Required status block. Populated for
    # every proposal; ``active=False`` for proposals where the feature is not
    # in effect, in which case the rest of the fields are at defaults and the
    # frontend hides the block. Field name kept (``sustained_majority``) for
    # one pass to avoid breaking the frontend mid-deploy; rename to
    # ``stable_result`` deferred to a future cleanup.
    sustained_majority: Optional["StableResultStatus"] = None


# ---------------------------------------------------------------------------
# Delegation graph
# ---------------------------------------------------------------------------

class GraphNode(BaseModel):
    id: str
    display_name: str
    username: str
    weight: int  # total voting weight delegated to this node
    # Phase 9.8 — see UserOut.avatar_url.
    avatar_url: Optional[str] = None


class GraphEdge(BaseModel):
    source: str
    target: str
    topic_id: Optional[str]
    topic_name: Optional[str]
    chain_behavior: str


class DelegationGraph(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


# ---------------------------------------------------------------------------
# Vote Flow Graph (Proposal)
# ---------------------------------------------------------------------------

class VoteFlowBallot(BaseModel):
    """Method-aware ballot summary for a single voter.

    Exactly one field is populated based on the proposal's voting_method.
    Visible only for voters whose identity is revealed by privacy rules;
    anonymous voters get ballot=None on their VoteFlowNode.
    """
    vote_value: Optional[str] = None       # binary: "yes" / "no" / "abstain"
    approvals: Optional[list[str]] = None  # approval: option_ids
    ranking: Optional[list[str]] = None    # ranked_choice: option_ids in rank order


class VoteFlowOption(BaseModel):
    """A proposal option, surfaced for the option-attractor visualization.

    Populated for approval and ranked_choice; empty list for binary.
    """
    id: str
    label: str
    display_order: int
    approval_count: int = 0   # approval-only; 0 for RCV
    first_pref_count: int = 0  # RCV-only; 0 for approval


class VoteFlowNode(BaseModel):
    id: str
    label: str
    type: str           # direct_voter, delegator, chain_delegate, non_voter
    vote: Optional[str]
    vote_source: Optional[str] = None  # "direct" or "delegation"
    is_public_delegate: bool = False
    is_current_user: bool = False
    delegator_count: int = 0
    total_vote_weight: int = 1
    # Phase 9.8 — see UserOut.avatar_url. Null when the viewer can't see the
    # node's identity (label gated by privacy rules) or the user has no avatar.
    avatar_url: Optional[str] = None
    # Ballot content is populated for every voter who has a ballot, regardless of
    # identity visibility. Privacy boundary: identity (label) is gated by follow/
    # public-delegate status; ballot content is part of the aggregate population
    # view that all viewers can see. ballot stays None only when the voter has no
    # cast ballot (non_voter).
    ballot: Optional[VoteFlowBallot] = None


class VoteFlowEdge(BaseModel):
    source: str     # from (delegator)
    target: str     # to (delegate)
    topic: Optional[str] = None
    topic_color: str = "#95a5a6"
    is_active: bool = True


class BinaryClusters(BaseModel):
    yes: dict = {}
    no: dict = {}
    abstain: dict = {}
    not_cast: dict = {}


class ApprovalClusters(BaseModel):
    option_counts: dict[str, int] = {}   # option_id -> approval count
    winners: list[str] = []              # top-vote-getters; len > 1 for ties


class RCVClusters(BaseModel):
    winners: list[str] = []              # option_ids; len > 1 for unresolved final-round tie
    total_rounds: int = 0


class VoteFlowClusters(BaseModel):
    # Legacy top-level binary fields — preserved for back-compat with existing
    # frontend code that reads clusters.yes / clusters.no / clusters.not_cast.
    # Populated only when voting_method == "binary"; empty/zero otherwise.
    # NOTE: not_cast is a {count: N} dict here (legacy shape). Phase 7B's spec
    # asks for an additional top-level not_cast int — resolved by exposing the
    # not_cast count via total_eligible - total_cast and keeping the dict shape.
    yes: dict = {}
    no: dict = {}
    abstain: dict = {}
    not_cast: dict = {}
    # Phase 7B additions — method-aware aggregates.
    voting_method: str = "binary"
    total_eligible: int = 0
    total_cast: int = 0
    total_abstain: int = 0
    binary: Optional[BinaryClusters] = None
    approval: Optional[ApprovalClusters] = None
    rcv: Optional[RCVClusters] = None


class VoteFlowGraph(BaseModel):
    proposal_id: str
    proposal_title: str
    voting_method: str = "binary"
    total_eligible: int
    nodes: list[VoteFlowNode]
    edges: list[VoteFlowEdge]
    options: list[VoteFlowOption] = []
    clusters: VoteFlowClusters


# ---------------------------------------------------------------------------
# Personal Delegation Network
# ---------------------------------------------------------------------------

class PersonalNetworkCenter(BaseModel):
    id: str
    label: str
    delegating_to: int
    delegated_from: int
    # Phase 9.8 — see UserOut.avatar_url.
    avatar_url: Optional[str] = None


class PersonalNetworkNode(BaseModel):
    id: str
    label: str
    relationship: str   # "delegate" or "delegator"
    topics: list[str]
    is_public_delegate: bool = False
    total_delegators: int = 0
    # Phase 9.8 — see UserOut.avatar_url.
    avatar_url: Optional[str] = None


class PersonalNetworkEdgeTopic(BaseModel):
    name: str
    color: str
    # Phase 30 B4 — surface the user-visible label (Topic.description)
    # so the frontend's description-fallback rendering can strip the
    # demo-org "slug:" prefix that scoped uniqueness adds to Topic.name.
    # None for the synthesized "Global" placeholder (no Topic row exists).
    description: Optional[str] = None


class PersonalNetworkEdge(BaseModel):
    source: str   # from
    target: str   # to
    topics: list[PersonalNetworkEdgeTopic]
    direction: str  # "outgoing" or "incoming"


class PersonalDelegationNetwork(BaseModel):
    center: PersonalNetworkCenter
    nodes: list[PersonalNetworkNode]
    edges: list[PersonalNetworkEdge]


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

class AdvanceProposalRequest(BaseModel):
    voting_end: Optional[datetime] = None  # Required when advancing to voting


class SeedRequest(BaseModel):
    scenario: str = "healthcare"  # "healthcare" | "environment"


class TimeSimulationRequest(BaseModel):
    proposal_id: str
    simulated_time: datetime

    @field_validator("proposal_id")
    @classmethod
    def validate_proposal_id(cls, v: str) -> str:
        return _validate_uuid(v)


# Phase 9.5 — admin-only platform-settings + per-user org-creation-limit
# patches. `value` and `limit` are intentionally permissive: `value` is JSON
# (str/bool/number/dict are all valid), `limit` is `int | None` (None
# clears the override and restores the platform default of 3).
class PlatformSettingPatch(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    value: Any = None


class OrgCreationLimitPatch(BaseModel):
    limit: Optional[int] = Field(default=None, ge=0)


# ---------------------------------------------------------------------------
# Audit Log
# ---------------------------------------------------------------------------

class AuditLogOut(BaseModel):
    id: str
    timestamp: datetime
    actor_id: Optional[str]
    action: str
    target_type: str
    target_id: str
    details: Optional[dict[str, Any]]
    ip_address: Optional[str]

    model_config = {"from_attributes": True}


class AccessLogEntry(BaseModel):
    """
    User-facing "data access history" entry — surfaces times a privileged
    operator (or another user) accessed something that includes this user's
    data. Built by `routes.users.get_user_access_log` from the audit log.
    """
    timestamp: datetime
    accessor_id: Optional[str]
    accessor_display_name: str
    accessor_role: str       # "Platform admin" | "Org admin of {Name}" | "User"
    action_type: str         # human-readable, e.g. "Viewed your ballot"
    reason: Optional[str]
    ip_address: Optional[str]


# ---------------------------------------------------------------------------
# Delegate Profiles
# ---------------------------------------------------------------------------

class DelegateProfileCreate(BaseModel):
    topic_id: str
    bio: str = Field(default="", max_length=2000)

    @field_validator("topic_id")
    @classmethod
    def validate_topic_id(cls, v: str) -> str:
        return _validate_uuid(v)


class DelegateProfileOut(BaseModel):
    id: str
    user_id: str
    topic_id: str
    topic: "TopicOut"
    bio: str
    # Phase 33 D1 — `is_active` column dropped from the model. The field was
    # always True post-creation for current rows. We could remove it from the
    # schema entirely, but keeping it as a literal True default preserves
    # back-compat with any external API consumer that reads it.
    is_active: bool = True
    created_at: datetime

    model_config = {"from_attributes": True}


class PublicDelegateOut(BaseModel):
    """Public delegate listing entry — user info plus their profiles."""
    user: UserSearchResult
    profiles: list[DelegateProfileOut]
    delegation_counts: dict[str, int] = {}   # topic_id -> count

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Follow System
# ---------------------------------------------------------------------------

class FollowRequestCreate(BaseModel):
    target_id: str
    message: Optional[str] = Field(default=None, max_length=500)

    @field_validator("target_id")
    @classmethod
    def validate_target_id(cls, v: str) -> str:
        return _validate_uuid(v)


class FollowRequestRespond(BaseModel):
    status: str
    permission_level: Optional[str] = "view_only"

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in ("approved", "denied"):
            raise ValueError("status must be 'approved' or 'denied'")
        return v

    @field_validator("permission_level")
    @classmethod
    def validate_permission_level(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("view_only", "delegation_allowed"):
            raise ValueError("permission_level must be 'view_only' or 'delegation_allowed'")
        return v


class FollowRequestOut(BaseModel):
    id: str
    requester_id: str
    requester: UserSearchResult
    target_id: str
    target: UserSearchResult
    # Phase 18 (D2): follow requests carry org context. Nullable in 18a,
    # NOT NULL post-18b.
    org_id: Optional[str] = None
    status: str
    permission_level: Optional[str]
    message: Optional[str]
    requested_at: datetime
    responded_at: Optional[datetime]

    model_config = {"from_attributes": True}


class FollowRelationshipOut(BaseModel):
    id: str
    follower_id: str
    follower: UserSearchResult
    followed_id: str
    followed: UserSearchResult
    # Phase 18 (D2): follow relationships carry org context.
    org_id: Optional[str] = None
    permission_level: str
    created_at: datetime

    model_config = {"from_attributes": True}


class FollowPermissionUpdate(BaseModel):
    permission_level: str

    @field_validator("permission_level")
    @classmethod
    def validate_permission_level(cls, v: str) -> str:
        if v not in ("view_only", "delegation_allowed"):
            raise ValueError("permission_level must be 'view_only' or 'delegation_allowed'")
        return v


# ---------------------------------------------------------------------------
# Vote visibility
# ---------------------------------------------------------------------------

class VoteVisibility(BaseModel):
    """A vote entry that may be redacted if the requester lacks permission."""
    id: str
    proposal_id: str
    proposal_title: Optional[str] = None
    vote_value: Optional[str]        # None means private/hidden
    is_direct: Optional[bool]
    cast_at: Optional[datetime]
    visible: bool                     # False = redacted


class PublicProfileOut(BaseModel):
    user: UserSearchResult
    delegate_profiles: list["DelegateProfileOut"] = []
    votes: list[VoteVisibility] = []


# ---------------------------------------------------------------------------
# Organizations
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$")


# Phase 57 — the new three-axis value vocabulary. The four old Phase 14
# values still accepted for back-compat (FE / in-flight callers may not
# have updated yet) but normalize to the new vocabulary on the way in.
_PHASE_57_JOIN_POLICIES = {"open", "approval", "invite"}
_PHASE_57_DISCOVERABILITIES = {"listed", "unlisted", "hidden"}
_PHASE_57_ACTIVITY_VISIBILITIES = {"public", "members_only"}
# Legacy → (new join_policy, implied discoverability). Mirrors the
# migration b9c0d1e2f3a4 mapping exactly.
_LEGACY_JOIN_POLICY_MAP = {
    "open": ("open", "listed"),
    "approval_required": ("approval", "listed"),
    "invite_only_public": ("invite", "listed"),
    "invite_only_secret": ("invite", "hidden"),
}


def _validate_join_policy_value(v: str) -> str:
    """Accept BOTH the new vocabulary AND the four legacy Phase 14
    values without normalizing the legacy value here — the field-level
    validator returns the raw value through so a downstream model-level
    validator can read both `join_policy` and `discoverability` in the
    same pass and apply the legacy implied-discoverability default.

    Legacy `invite_only` (the Phase-13.3 pre-rename literal) is still
    rejected loudly for symmetry with the prior Phase 14 validator.
    """
    if v == "invite_only":
        raise ValueError(
            "join_policy 'invite_only' is no longer accepted; use one of "
            "'open' / 'approval' / 'invite'."
        )
    if v in _LEGACY_JOIN_POLICY_MAP:
        # Accept-as-is; the model-level normalizer handles the rewrite
        # so it can co-update discoverability when the caller hasn't
        # explicitly set it.
        return v
    if v not in _PHASE_57_JOIN_POLICIES:
        raise ValueError(
            "join_policy must be one of 'open', 'approval', 'invite'."
        )
    return v


def _apply_legacy_join_policy_normalization(data: dict) -> dict:
    """Phase 57 — read join_policy + discoverability together and
    normalize legacy four-value join_policy strings onto the new
    three-value vocabulary, filling in implied discoverability if the
    caller hasn't explicitly set it. Also normalizes the incoherent
    hidden+public combination to hidden+members_only per spec B3.

    Mutates and returns the input dict so it's reusable from both
    OrgCreate and OrgUpdate model_validators.
    """
    jp = data.get("join_policy")
    if jp in _LEGACY_JOIN_POLICY_MAP:
        new_jp, implied_disc = _LEGACY_JOIN_POLICY_MAP[jp]
        data["join_policy"] = new_jp
        if implied_disc is not None and not data.get("discoverability"):
            data["discoverability"] = implied_disc
    if data.get("discoverability") == "hidden":
        # Incoherent combination: nobody can see the org, so activity
        # visibility is moot. Force members_only server-side regardless
        # of caller input.
        data["activity_visibility"] = "members_only"
    return data


def normalize_access_axes_for_create_or_update(
    join_policy: Optional[str],
    discoverability: Optional[str],
    activity_visibility: Optional[str],
    legacy_join_policy_raw: Optional[str],
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Phase 57 — co-validate the three access axes.

    Returns the (possibly-normalized) triple. If ``legacy_join_policy_raw``
    matches one of the four old Phase 14 values AND no explicit
    ``discoverability`` was supplied, the implied discoverability from the
    legacy mapping is filled in (so old in-flight clients still produce
    the byte-for-byte same access posture as before).

    The hidden + public combination is incoherent (nobody can see the
    org at all, so the activity-visibility axis is moot). Per spec D6
    + B3, it normalizes to (hidden, members_only) server-side.
    """
    if legacy_join_policy_raw in _LEGACY_JOIN_POLICY_MAP and not discoverability:
        discoverability = _LEGACY_JOIN_POLICY_MAP[legacy_join_policy_raw][1]
    if discoverability == "hidden":
        activity_visibility = "members_only"
    return join_policy, discoverability, activity_visibility


class OrgCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=3, max_length=50)
    description: str = ""
    # Phase 57 — default to 'approval'. The validator below accepts the
    # four legacy values too and normalizes them onto the new vocabulary.
    join_policy: str = "approval"
    # Phase 57 — new axes; default to today's effective behavior
    # (everything was listed except invite_only_secret; nothing exposed
    # activity to non-members).
    discoverability: Optional[str] = None
    activity_visibility: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_join_policy(cls, data):
        # Phase 57 — co-normalize join_policy + discoverability so a
        # caller that sent a legacy 4-value join_policy literal also
        # gets the implied discoverability filled in (preserving the
        # pre-Phase-57 access posture byte-for-byte).
        if isinstance(data, dict):
            data = _apply_legacy_join_policy_normalization(data)
        return data

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        if not _SLUG_RE.match(v):
            raise ValueError(
                "Slug must be 3-50 characters, lowercase alphanumeric and hyphens only, "
                "cannot start or end with a hyphen"
            )
        return v

    @field_validator("join_policy")
    @classmethod
    def validate_join_policy(cls, v: str) -> str:
        return _validate_join_policy_value(v)

    @field_validator("discoverability")
    @classmethod
    def validate_discoverability(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if v not in _PHASE_57_DISCOVERABILITIES:
            raise ValueError(
                "discoverability must be one of 'listed', 'unlisted', 'hidden'."
            )
        return v

    @field_validator("activity_visibility")
    @classmethod
    def validate_activity_visibility(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if v not in _PHASE_57_ACTIVITY_VISIBILITIES:
            raise ValueError(
                "activity_visibility must be one of 'public', 'members_only'."
            )
        return v


class OrgUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    join_policy: Optional[str] = None
    # Phase 57 — new access axes on update.
    discoverability: Optional[str] = None
    activity_visibility: Optional[str] = None
    settings: Optional[dict] = None
    # Phase 49a Cluster B — `proposal_creation_mode` was replaced
    # by the boolean `settings.allow_cosign_petition`. Admins set
    # the toggle via the standard `settings` PATCH path (it lives
    # inside the JSONB blob rather than as a top-level column).

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_join_policy(cls, data):
        if isinstance(data, dict):
            data = _apply_legacy_join_policy_normalization(data)
        return data

    @field_validator("join_policy")
    @classmethod
    def validate_join_policy(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return _validate_join_policy_value(v)

    @field_validator("discoverability")
    @classmethod
    def validate_discoverability(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if v not in _PHASE_57_DISCOVERABILITIES:
            raise ValueError(
                "discoverability must be one of 'listed', 'unlisted', 'hidden'."
            )
        return v

    @field_validator("activity_visibility")
    @classmethod
    def validate_activity_visibility(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if v not in _PHASE_57_ACTIVITY_VISIBILITIES:
            raise ValueError(
                "activity_visibility must be one of 'public', 'members_only'."
            )
        return v


# Phase 12.7 B3+B4 — branding section of Organization.settings JSON.
# Always present in /api/orgs responses with all-null fields when no
# branding has been configured (frontend uses platform defaults in that
# case). Persisted to ``Organization.settings.branding``; absent on
# fresh org creation, populated as stewards opt in via the UI.

# Hex format: #RRGGBB or #RGB. Backend just validates the shape; the
# auto-derive logic for accent_color is frontend-only (frontend computes
# the lighter shade and submits it explicitly with accent_auto_derived=True).
_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def _validate_hex_color(value: Optional[str]) -> Optional[str]:
    """Hex-color validator shared by BrandingUpdate fields.

    Accepts ``None`` (means "leave unchanged" / "clear" depending on the
    PATCH semantics in the route handler), or a hex string in ``#RRGGBB``
    or ``#RGB`` form. Anything else raises a ValueError that Pydantic
    surfaces as a 422 — the route handler converts to 400 if it wants
    that shape.
    """
    if value is None:
        return None
    if not isinstance(value, str) or not _HEX_COLOR_RE.match(value):
        raise ValueError(
            "color must be a hex string in #RRGGBB or #RGB form"
        )
    return value


class BrandingOut(BaseModel):
    """Always-present branding shape on org responses.

    All fields are nullable; when null, the frontend falls back to
    platform defaults. ``accent_auto_derived`` defaults to False on
    unconfigured orgs (no semantic meaning when accent_color is None,
    but a consistent type makes the frontend's life easier).
    """
    logo_url: Optional[str] = None
    primary_color: Optional[str] = None
    accent_color: Optional[str] = None
    accent_auto_derived: bool = False


class BrandingUpdate(BaseModel):
    """PATCH body for /api/orgs/{slug}/branding.

    Partial-update semantics: keys NOT present in the request body are
    left unchanged; keys present with ``null`` clear the value (frontend
    will then use platform defaults). The route handler distinguishes
    "key absent" from "key present and null" via ``model_dump(exclude_unset=True)``.

    The logo_url is NOT settable here — logos are managed via
    POST/DELETE /api/orgs/{slug}/logo which sets the URL as a side
    effect of file upload.

    Phase 14 B4: ``intro_text`` is a markdown-supported text block shown
    on the org's public landing page. Stored on
    ``Organization.settings.intro_text`` (NOT under the ``branding``
    sub-dict, since intro_text is conceptually independent of color/logo
    branding even though it ships through the same PATCH endpoint).
    Up to 5000 chars; longer rejected.
    """
    primary_color: Optional[str] = None
    accent_color: Optional[str] = None
    accent_auto_derived: Optional[bool] = None
    # Phase 14 B4 — empty string is allowed and treated as "clear" by the
    # endpoint (settings.intro_text set to "" so get_intro_text returns
    # None). Frontend can submit None to leave the field unchanged.
    intro_text: Optional[str] = None

    @field_validator("primary_color")
    @classmethod
    def validate_primary(cls, v: Optional[str]) -> Optional[str]:
        return _validate_hex_color(v)

    @field_validator("accent_color")
    @classmethod
    def validate_accent(cls, v: Optional[str]) -> Optional[str]:
        return _validate_hex_color(v)

    @field_validator("intro_text")
    @classmethod
    def validate_intro_text(cls, v: Optional[str]) -> Optional[str]:
        # Phase 14 B4 — 5000-char cap. None and empty string are both
        # valid (frontend uses None to mean "leave unchanged" and ""
        # to mean "clear the field"; the route handler distinguishes
        # via exclude_unset=True).
        if v is None:
            return v
        if not isinstance(v, str):
            raise ValueError("intro_text must be a string")
        if len(v) > 5000:
            raise ValueError(
                "intro_text exceeds 5000-character maximum length"
            )
        return v


class OrgPublicBrandingOut(BaseModel):
    """Phase 14 B2 — public-shape branding object on the public landing
    page endpoint. Exposes ONLY primary_color and accent_color (no
    accent_auto_derived flag, no logo_url — logo_url is on the parent
    response). Smaller surface than internal BrandingOut.
    """
    primary_color: Optional[str] = None
    accent_color: Optional[str] = None


class OrgPublicOut(BaseModel):
    """Phase 14 B2 — public-facing org data shape returned by
    GET /api/orgs/{slug}/public.

    No auth required; the response is identical for logged-in and
    logged-out callers. Excludes internal fields (id, created_at,
    member_count, user_role, user_permissions, settings) and only
    surfaces fields a prospective member needs to decide whether and
    how to join.
    """
    slug: str
    name: str
    description: str
    logo_url: Optional[str] = None
    branding: OrgPublicBrandingOut = OrgPublicBrandingOut()
    intro_text: Optional[str] = None
    join_policy: str
    # Phase 57 — surface activity_visibility on the public splash so
    # the FE can render a public proposal panel when 'public'. The
    # public endpoint is the SAME source of truth the unauth viewer
    # sees, so including this here keeps the FE from doing a second
    # API call to learn the access posture.
    activity_visibility: str = "members_only"
    # Phase 88c — the org's voting model, declared publicly so a prospective
    # joiner sees weighted-voting orgs up front (anti-stealth). {enabled,
    # unit_label}; absent/unweighted ⇒ enabled False. Individual member weights
    # are NEVER surfaced here (anonymous access).
    weighted_voting: dict = {"enabled": False, "unit_label": "shares"}


class ExploreOrgCard(BaseModel):
    """Phase 55 — one card on the public org discovery page (/explore).

    Minimal, public-safe projection — deliberately distinct from OrgOut and
    NOT subject to the OrgOut _MUST_SURFACE_FIELDS serializer-coverage test
    (this schema intentionally omits settings, user_permissions, governance_mode,
    and all other internal fields). The endpoint is unauthenticated; only the
    fields a card needs to render are exposed. Branding reuses the public-shape
    OrgPublicBrandingOut (primary_color + accent_color only — no logo flag,
    since logo_url surfaces directly on the card).
    """
    slug: str
    name: str
    description: str
    governance_type: Optional[str] = None
    join_policy: str
    member_count: int
    logo_url: Optional[str] = None
    branding: OrgPublicBrandingOut = OrgPublicBrandingOut()
    # Phase 88c — voting model on each discovery card so the badge renders in
    # the /explore listing. {enabled, unit_label}; no per-member weights.
    weighted_voting: dict = {"enabled": False, "unit_label": "shares"}


class ExploreResponse(BaseModel):
    """Phase 55 — response envelope for GET /api/orgs/explore."""
    orgs: list[ExploreOrgCard]
    count: int


class JoinRequestOut(BaseModel):
    """Phase 14 B3 — POST /api/orgs/{slug}/join-request response."""
    status: str  # 'pending' or 'active'
    member_id: str


class OrgOut(BaseModel):
    id: str
    name: str
    slug: str
    description: str
    join_policy: str
    # Phase 57 — three-axis access model. `join_policy` (above) is now
    # repurposed to hold only the join semantics (open / approval /
    # invite); discoverability + activity_visibility carry the orthogonal
    # axes that used to be conflated inside `join_policy`. Both are
    # surfaced on every OrgOut (and asserted via Phase 46a
    # _MUST_SURFACE_FIELDS) so the FE can render the new access controls
    # in OrgSettings + drive the public landing flow.
    discoverability: str = "listed"
    activity_visibility: str = "members_only"
    settings: dict = {}
    # Phase 34 — parent_org_id needs to surface so the FE can distinguish
    # sub-orgs from top-level orgs in the org switcher / Nav.jsx
    # parentOrgs filter. None for top-level orgs.
    parent_org_id: Optional[str] = None
    created_at: datetime
    member_count: Optional[int] = None
    user_role: Optional[str] = None
    # Phase 80.1 hotfix — surface is_demo so the FE can (a) keep the demo
    # disclosure banner rendering on demo orgs and (b) let the Phase 79 demo
    # session fence trust `currentOrg.is_demo`. Its absence here was the
    # root cause of the fence logging demo personas out of their own demo org.
    is_demo: bool = False
    # Phase 12.5 — resolved permission keys the current user holds on this
    # org (computed via the per-request cache; one DB load for all 25 keys).
    # Empty list for non-members. Frontend uses this to drive admin-nav and
    # in-page control gating without an extra round-trip.
    user_permissions: list[str] = []
    # Phase 12.7 B4 — always-present branding object. Centralized via
    # the _org_to_out helper in routes/organizations.py so every org-
    # returning endpoint emits the same shape. All-null fields when the
    # org hasn't configured branding.
    branding: BrandingOut = BrandingOut()
    # Phase 45b — per-org governance mode. Defaults to 'single_steward'
    # so untouched orgs surface the today-behavior value.
    governance_mode: str = "single_steward"
    # Phase 49a Cluster B — replaces the legacy `proposal_creation_
    # mode` 3-way enum. When False (default), members without
    # `proposal.create` get 403; when True, they can initiate via
    # cosign-gathering instead.
    allow_cosign_petition: bool = False
    # Phase 87 (B-10) — platform-moderation state. NULL for normal orgs;
    # 'delisted' / 'suspended' otherwise. Surfaced so an org's own admins see
    # the delist notice in settings; members of a suspended org never receive
    # an OrgOut (the org 404s for them). Read-only from the org's perspective.
    platform_restriction: Optional[str] = None
    # Phase 88 — resolved weighted-voting config {enabled, unit_label}. Always
    # present (defaults {enabled: False, unit_label: "shares"}); populated by
    # _org_to_out via org_config.get_weighted_voting_config so the FE renders
    # the shares column + ballot chips without re-parsing raw settings.
    weighted_voting: dict = {"enabled": False, "unit_label": "shares"}
    # Phase 88c — total outstanding voting weight (sum over active members).
    # Every member may see this (it's already implicit in tally denominators);
    # the FE renders "N of M total <unit>". None when weighted voting is off.
    total_voting_weight: Optional[int] = None
    model_config = ConfigDict(from_attributes=True)


class OrgMemberOut(BaseModel):
    # Phase 47 — list of held titles (D8). Combines system titles
    # derived from role + custom titles from org_title_assignments,
    # sorted by display order. Empty list for members with no titles.
    held_titles: list[str] = []
    user_id: str
    username: str
    display_name: str
    email: Optional[str] = None
    # Phase 9.8 — see UserOut.avatar_url.
    avatar_url: Optional[str] = None
    role: str
    status: str
    joined_at: datetime
    # Phase 52e Stage 2 E3 — derived per-org verified status. Computed
    # on read via ``verification_flags.is_org_verified`` (membership
    # floor satisfied AND not currently the subject of an open high-
    # confidence duplicate flag in this org). NOT a stored field; the
    # value reflects the live derived state at list-render time. The
    # member-list "Verified" badge reads this boolean.
    is_org_verified: bool = False
    # Phase 88 / 88c — per-member voting weight (shares). AMENDED in 88c:
    # surfaced ONLY in the admin-gated view (holders of
    # member.set_voting_weight); None for plain members, because a public
    # per-member register plus the support-trajectory time series would let
    # anyone deanonymize ballots by arithmetic. Members see their OWN weight
    # via the ballot chip + the org total, not other members' weights.
    voting_weight: Optional[int] = None
    # Phase 90a — the member's share anniversary date, admin-gated like
    # voting_weight (None for plain members). Drives anniversary distribution.
    share_start_date: Optional[date] = None
    model_config = ConfigDict(from_attributes=True)


class ShareEventOut(BaseModel):
    """Phase 90 — one share-ledger event, rendered per the org's visibility
    rules. Amounts + authorizer are always present; party ids/names appear only
    when ``show_event_parties`` is on OR the requester is a party; the
    resulting balance appears only on the requester's own events."""
    id: str
    event_type: str            # admin_set | auto_distribution | transfer
    created_at: datetime
    delta: int
    # The authorizer of an admin_set (accountability-critical, ALWAYS named).
    actor_id: Optional[str] = None
    actor_display_name: Optional[str] = None
    # Party fields — populated only when visible to the requester (toggle on,
    # or requester is a party). Otherwise omitted (None).
    user_id: Optional[str] = None
    user_display_name: Optional[str] = None
    from_user_id: Optional[str] = None
    from_display_name: Optional[str] = None
    to_user_id: Optional[str] = None
    to_display_name: Optional[str] = None
    # Only present on the requester's own events (register-grade).
    resulting_balance: Optional[int] = None
    # Phase 90b — the SENDER's balance after a transfer, only present when the
    # requester is the sender.
    from_resulting_balance: Optional[int] = None
    # Reference to the auto-distribution rule (90a); None for admin_set /
    # transfer.
    rule_id: Optional[str] = None


class ShareEventFeedOut(BaseModel):
    """Paginated share-event feed. ``epoch`` states when the ledger began (no
    genesis backfill of pre-ledger balances)."""
    events: list[ShareEventOut]
    has_more: bool = False
    show_parties: bool = False
    unit_label: str = "shares"
    epoch: Optional[datetime] = None


class ShareDistributionRuleOut(BaseModel):
    """Phase 90a — a standing auto-distribution rule (readable by all members)."""
    id: str
    status: str
    amount: int
    interval_months: int
    schedule_mode: str
    anchor_date: Optional[date] = None
    targeting_mode: str
    title_ids: list[str] = []
    created_at: datetime
    last_run_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class ShareDistributionRuleCreate(BaseModel):
    amount: int
    interval_months: int
    schedule_mode: str  # fixed_cadence | anniversary
    targeting_mode: str = "all_members"
    title_ids: list[str] = []
    anchor_date: Optional[date] = None


class ShareDistributionRuleUpdate(BaseModel):
    amount: Optional[int] = None
    interval_months: Optional[int] = None
    schedule_mode: Optional[str] = None
    targeting_mode: Optional[str] = None
    title_ids: Optional[list[str]] = None
    anchor_date: Optional[date] = None


class _ShareStartDateBody(BaseModel):
    share_start_date: Optional[date] = None


class _ShareTransferBody(BaseModel):
    to_user_id: str
    amount: int


class OrgBanOut(BaseModel):
    """Phase 85 (B-8) — one active org rejoin ban, for the admin Members
    "Banned" section. Surfaces the banned user, who banned them, when, and
    the admin-facing reason (never shown to the banned user)."""
    id: str
    user_id: str
    user_display_name: str
    user_username: str
    banned_by_id: Optional[str] = None
    banned_by_display_name: Optional[str] = None
    reason: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AdminOrgOut(BaseModel):
    """Phase 87 (B-10) — one org row for the platform-admin org table."""
    id: str
    name: str
    slug: str
    member_count: int
    discoverability: str
    activity_visibility: str
    platform_restriction: Optional[str] = None
    restriction_reason: Optional[str] = None
    is_demo: bool = False
    parent_org_id: Optional[str] = None
    created_at: datetime


class AdminOrgRestrictionIn(BaseModel):
    """Set/clear an org's platform restriction. ``restriction`` is one of
    'delisted' | 'suspended' | 'none' (or null to clear). ``reason`` is
    REQUIRED when restricting, optional when reverting."""
    restriction: Optional[str] = None
    reason: Optional[str] = None


class InvitationCreate(BaseModel):
    emails: list[str]
    role: str = "member"

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in ("member", "admin"):
            raise ValueError("role must be member or admin")
        return v


class InvitationOut(BaseModel):
    id: str
    email: str
    role: str
    status: str
    expires_at: datetime
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# Phase 30.1 B4 — DelegateApplicationCreate / DelegateApplicationOut /
# DelegateApplicationReview removed alongside the legacy admin-approval
# surface. The Phase 19 DelegateProfile lifecycle replaces them; per-
# profile-id approve/deny endpoints in delegate_profiles.py use
# OrgDelegateProfileOut + DelegateApplicationDeny (preserved below for
# the new flow's deny-comment payload).


class AnalyticsOut(BaseModel):
    participation_rates: list[dict] = []
    delegation_patterns: dict = {}
    proposal_outcomes: dict = {}
    active_members: dict = {}


class MemberRoleUpdate(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in ("member", "moderator", "admin"):
            raise ValueError("role must be member, moderator, or admin")
        return v


# ---------------------------------------------------------------------------
# Phase 8.5 — Sub-organizations
# ---------------------------------------------------------------------------

class SubOrgCreate(BaseModel):
    """Body for `POST /api/orgs/{slug}/sub-orgs`."""
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=3, max_length=50)
    description: str = ""
    settings: Optional[dict] = None

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        if not _SLUG_RE.match(v):
            raise ValueError(
                "Slug must be 3-50 characters, lowercase alphanumeric and hyphens only, "
                "cannot start or end with a hyphen"
            )
        return v


class SubOrgUpdate(BaseModel):
    """Body for `PATCH /api/orgs/{slug}/sub-orgs/{sub_slug}`."""
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    settings: Optional[dict] = None


class SubOrgOut(BaseModel):
    id: str
    name: str
    slug: str
    description: str
    parent_org_id: str
    settings: dict = {}
    member_count: Optional[int] = None
    # Phase 15 Cluster S — sub-org effective role's system_key (the
    # highest-tier role applicable to the user via direct sub-org
    # membership, transferable parent role, or platform-admin grant).
    # None for users with no applicable role on this sub-org.
    user_role: Optional[str] = None
    # Phase 15 Cluster S §S5 — resolved permission keys the current user
    # holds on this sub-org. Computed via has_permission_on_sub_org
    # against the parent's matrix at the resolved role. Empty list when
    # user has no applicable role. Frontend uses this to drive the
    # sub-org admin nav and in-page control gating, parallel to Phase
    # 12.5 B4's addition to OrgOut.
    user_permissions: list[str] = []
    # Phase 34.1 hotfix #1 — branding surfaces on sub-org responses with
    # parent-org fallback (same _inherit logic as OrgOut). FE consumes
    # this when rendering sub-org admin pages.
    branding: BrandingOut = BrandingOut()
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class SubOrgMemberInvite(BaseModel):
    """Body for `POST /api/orgs/{slug}/sub-orgs/{sub_slug}/members/invite`.

    Phase 15 Cluster S — accepts the new ``steward`` role; ``owner`` is
    accepted for one cycle of backwards compatibility and silently
    translated to ``steward`` server-side (per the role-rename policy).
    """
    user_id: str
    role: str = "member"

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, v: str) -> str:
        return _validate_uuid(v)

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in ("member", "moderator", "admin", "owner", "steward"):
            raise ValueError(
                "role must be member, moderator, admin, or steward"
            )
        return v


class SubOrgMemberRoleUpdate(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in ("member", "moderator", "admin", "owner", "steward"):
            raise ValueError(
                "role must be member, moderator, admin, or steward"
            )
        return v


class SubOrgMemberDirectAdd(BaseModel):
    """Phase 9.6 Workstream 2 — body for
    `POST /api/orgs/{slug}/sub-orgs/{sub_slug}/members/add`.

    Used by parent-org admins (or sub-org admins) to add a parent-org member
    to a sub-org directly, skipping the invitation/approval flow. Default
    role is `member`.
    """
    user_id: str
    role: str = "member"

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, v: str) -> str:
        return _validate_uuid(v)

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in ("member", "moderator", "admin"):
            raise ValueError("role must be member, moderator, or admin")
        return v


class SubOrgMemberOut(BaseModel):
    user_id: str
    username: str
    display_name: str
    email: Optional[str] = None
    # Phase 9.8 — see UserOut.avatar_url.
    avatar_url: Optional[str] = None
    role: str
    status: str
    joined_at: datetime
    model_config = ConfigDict(from_attributes=True)


class PromoteTopicToOrgwide(BaseModel):
    """Body for `POST /api/orgs/{slug}/topics/{topic_id}/promote-to-orgwide`.

    Decision 3 — promotion is irreversible. The route requires
    `confirm: true` to ensure clients have shown a confirmation UI.
    """
    confirm: bool = False


# ---------------------------------------------------------------------------
# Phase 9 — Polis schemas
# ---------------------------------------------------------------------------

class PolisCreate(BaseModel):
    """Body for `POST /api/orgs/{slug}/polises`.

    Phase 81 — the frontend now links an EXISTING pol.is conversation:
    `polis_conversation_id` is required and `title` (Discussion topic) +
    `prompt` (Description) are optional (default `""`; the FE falls back to
    a "Linked pol.is conversation <id>" label when topic is empty).

    `seed_statements` is RETAINED for back-compat and the untouched
    programmatic path (settings.polis_auth_token set) + a future Phase 69
    programmatic-wiring pass; the new frontend no longer sends it. When set
    on the manual path it is still preserved as `intended_seed_statements`
    on the platform record.
    """
    title: str = Field(default="", max_length=500)
    prompt: str = Field(default="", max_length=10000)
    sub_org_id: Optional[str] = None
    seed_statements: list[str] = Field(default_factory=list, max_length=200)
    polis_conversation_id: Optional[str] = Field(
        default=None, min_length=1, max_length=300,
    )

    @field_validator("title", "prompt")
    @classmethod
    def _blank_to_empty(cls, v: Optional[str]) -> str:
        # Whitespace-only topic/description collapse to "" so the empty-
        # fallback logic downstream (D4) only has to check for "".
        return (v or "").strip()


class PolisUpdate(BaseModel):
    """Body for `PATCH /api/orgs/{slug}/polises/{polis_id}`.

    Title edits and archival are exposed in v1 (Decision 8 lifecycle:
    active -> archived). `status` may only be `'archived'` — other transitions
    are rejected at the route layer.

    Phase 9 Session 4 gap fix: also accepts `polis_conversation_id` to wire
    the manual-fallback CreatePolis "paste slug" success-panel Save button.
    The route enforces a one-shot connect — the field is only writable when
    the Polis's current `polis_conversation_id` is NULL. Once set, swapping
    it out requires admin tooling (audited as `polis.connected`).
    """
    # Phase 81 — drop min_length so the discussion topic can be cleared back
    # to empty (consistent with topic being optional at create; the FE
    # fallback handles display). None means "leave unchanged" on PATCH.
    title: Optional[str] = Field(default=None, max_length=500)
    status: Optional[str] = Field(default=None)
    polis_conversation_id: Optional[str] = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v != "archived":
            raise ValueError(
                "status may only be set to 'archived' (v1 lifecycle)"
            )
        return v


class PolisOut(BaseModel):
    id: str
    org_id: str
    sub_org_id: Optional[str] = None
    polis_conversation_id: Optional[str] = None
    title: str
    prompt: str
    status: str
    created_by: str
    created_at: datetime
    updated_at: datetime
    archived_at: Optional[datetime] = None
    intended_seed_statements: Optional[list[str]] = None
    embed_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class PolisCreateResponse(BaseModel):
    """Response for `POST /api/orgs/{slug}/polises`.

    `programmatic_path` tells the frontend which dispatch ran:
      - True: pol.is API was called; `polis_conversation_id` is real and
        seeds were inserted server-side. Check `partial_seed_failures` for
        per-seed error info if any seed posts failed.
      - False: manual-fallback. Operator must seed manually via the pol.is
        admin UI; FE should render the `intended_seed_statements` from
        `polis` for "paste these in" UX. `manual_seed_statements_required`
        is True in this case.
    """
    polis: PolisOut
    programmatic_path: bool
    manual_seed_statements_required: Optional[bool] = None
    partial_seed_failures: Optional[list[dict]] = None


class PolisSeedGenerateRequest(BaseModel):
    """Phase 82 C1 — body for the seed-statement generator. The generated
    statements are returned to the client for review + CSV download; nothing
    is persisted."""
    topic: str = Field(default="", max_length=2000)
    description: str = Field(default="", max_length=2000)
    steer: str = Field(default="", max_length=2000)
    include_org_description: bool = False


class PolisSeedGenerateResponse(BaseModel):
    """Phase 82 C1 — generated seed statements + an optional non-blocking
    degradation warning (empty input / AI unreachable / unparseable)."""
    statements: list[str]
    warning: Optional[str] = None


class PolisHasVisibleResponse(BaseModel):
    """Phase 82 C2 — cheap nav presence check: does this member have ≥1
    visible Polis in the org?"""
    has_visible: bool


class PolisXidResponse(BaseModel):
    """Response for `POST /api/orgs/{slug}/polises/{polis_id}/xid`.

    The xid is the Decision-4 pseudonymous bridging ID passed to pol.is's
    embed via `data-xid`. Lazily generated on first call per (user, org).
    """
    polis_xid: str


# ---------------------------------------------------------------------------
# Phase 10 — Comments
# ---------------------------------------------------------------------------

class CommentCreate(BaseModel):
    """Body for `POST /api/proposals/{proposal_id}/comments`.

    `body` is sanitized via the same nh3 pipeline as proposal bodies — see
    ``_sanitize_markdown``. Length is enforced at the route layer because we
    want the post-sanitize, post-trim length (rather than the raw Pydantic
    pre-validator length).
    """
    body: str = Field(min_length=1, max_length=5000)
    parent_comment_id: Optional[str] = None

    @field_validator("body")
    @classmethod
    def sanitize_body(cls, v: str) -> str:
        return _sanitize_markdown(v)

    @field_validator("parent_comment_id")
    @classmethod
    def validate_parent(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return _validate_uuid(v)
        return v


class CommentUpdate(BaseModel):
    """Body for `PATCH /api/comments/{id}`. Only the body is editable."""
    body: str = Field(min_length=1, max_length=5000)

    @field_validator("body")
    @classmethod
    def sanitize_body(cls, v: str) -> str:
        return _sanitize_markdown(v)


class CommentAuthorOut(BaseModel):
    """Nested user shape on CommentOut. Lighter than full UserOut so the
    list payload stays small; mirrors the UserSearchResult fields the
    frontend already knows how to render via the Avatar component."""
    id: str
    username: str
    display_name: str
    avatar_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class CommentOut(BaseModel):
    """Phase 10 — comment representation returned to the frontend.

    Soft-delete handling: when ``deleted_at`` is set, the route blanks
    ``body`` to an empty string and sets ``body_deleted=True`` so the
    frontend can render the ``[deleted]`` placeholder consistently without
    needing to second-guess the field. Keeping the boolean explicit (rather
    than overloading body content) makes the wire format honest and avoids
    the corner case where a real comment legitimately reads "[deleted]".
    """
    id: str
    proposal_id: str
    author_id: str
    author: CommentAuthorOut
    parent_comment_id: Optional[str] = None
    body: str
    body_deleted: bool = False
    # Phase 85 (B-1) — distinguishes an attributed moderator removal from an
    # author self-delete. True iff the row is soft-deleted AND ``removed_by_id``
    # is set. The FE renders "[removed by a moderator]" vs "[deleted]"
    # accordingly. The acting moderator's identity is NOT surfaced here (it
    # lives in the audit log); only the fact of moderation is public.
    moderator_removed: bool = False
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Phase 86 (B-4) — content reports
# ---------------------------------------------------------------------------

_REPORT_TARGET_TYPES = {"comment", "proposal"}
_REPORT_REASONS = {"spam", "harassment", "misleading", "other"}
_REPORT_RESOLUTIONS = {"dismissed", "actioned"}
_REPORT_NOTE_MAX = 500


class ReportCreate(BaseModel):
    """Submit a content report. ``org_id`` is NEVER accepted from the client;
    it is resolved server-side from the target."""
    target_type: str
    target_id: str
    reason: str
    note: Optional[str] = None

    @field_validator("target_type")
    @classmethod
    def _v_target_type(cls, v: str) -> str:
        if v not in _REPORT_TARGET_TYPES:
            raise ValueError(f"target_type must be one of {sorted(_REPORT_TARGET_TYPES)}")
        return v

    @field_validator("reason")
    @classmethod
    def _v_reason(cls, v: str) -> str:
        if v not in _REPORT_REASONS:
            raise ValueError(f"reason must be one of {sorted(_REPORT_REASONS)}")
        return v

    @field_validator("note")
    @classmethod
    def _v_note(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        cleaned = _sanitize_markdown(v).strip()
        if not cleaned:
            return None
        # Length enforced here (post-sanitize) so tag-stripping can't smuggle
        # a longer payload through a pre-sanitize check.
        return cleaned[:_REPORT_NOTE_MAX]


class ReportResolveIn(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def _v_status(cls, v: str) -> str:
        if v not in _REPORT_RESOLUTIONS:
            raise ValueError(f"status must be one of {sorted(_REPORT_RESOLUTIONS)}")
        return v


class ReportItemOut(BaseModel):
    """One report within a target group — moderator-only. Carries the
    reporter's identity (accountability); this schema is NEVER returned to
    non-moderators."""
    id: str
    reporter_id: str
    reporter_display_name: str
    reason: str
    note: Optional[str] = None
    status: str
    created_at: datetime


class ReportGroupOut(BaseModel):
    """Open reports grouped by target, with enough context for a moderator to
    act (excerpt, author, link) plus the per-target open count."""
    target_type: str
    target_id: str
    org_slug: str
    proposal_id: Optional[str] = None
    target_excerpt: str
    target_author_id: Optional[str] = None
    target_author_display: Optional[str] = None
    open_count: int
    reports: list[ReportItemOut]


# ---------------------------------------------------------------------------
# Phase 19 — Public delegate pages
# ---------------------------------------------------------------------------

class _OrgDelegateProfileTopicOut(BaseModel):
    """One ``DelegateProfile`` row (per-topic) embedded in the org-delegate-
    profile GET response. Covers every column the frontend needs to render
    the per-topic editing UI: bio, position_statement, the visibility
    state machine, and the approval-workflow timestamps so the F1 surface
    can show pending / approved / denied per topic.
    """

    id: str
    topic_id: str
    topic_name: Optional[str] = None
    bio: str = ""
    position_statement: Optional[str] = None
    visibility: str  # 'private' | 'public' | 'public_accepting'
    public_accepting_submitted_at: Optional[datetime] = None
    public_accepting_approved_at: Optional[datetime] = None
    public_accepting_approved_by_id: Optional[str] = None
    public_accepting_denied_comment: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class OrgDelegateProfileOut(BaseModel):
    """Response shape for ``GET /api/orgs/{slug}/delegate-profile``
    (caller's own profile in this org).

    Phase 30.3: ``page_visibility`` and ``effective_page_visibility``
    fields were removed when the page-visibility layer was consolidated
    into per-topic ``DelegateProfile.visibility``. The frontend reads
    audience state from the per-topic ``topics[].visibility`` field.
    """

    id: str
    user_id: str
    org_id: str
    org_slug: str
    intro: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    topics: list[_OrgDelegateProfileTopicOut] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class PublicDelegatePageOut(BaseModel):
    """Phase 19 — response shape for ``GET /api/orgs/{slug}/delegates/
    {handle_or_username}`` (public read of any delegate's per-org page).

    Combines user identity + OrgDelegateProfile intro + topics that are
    non-``private`` (per D12: page renders both ``public`` and
    ``public_accepting`` topics; ``private`` topics are hidden).

    Auth: caller's view is gated by ``effective_page_visibility`` on the
    target ``OrgDelegateProfile``:
      - ``public``  → anyone may view (anonymous OK)
      - ``private_delegators`` → only approved followers in this org
      - ``private`` → 404 (owner uses ``/delegate-profile`` instead)

    The list endpoint surfaces only ``public_accepting`` users (D11);
    this single-page endpoint surfaces any user with a non-``private``
    page so transparent-only delegates are reachable via direct URL.
    """

    user_id: str
    username: str
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    delegate_handle: Optional[str] = None
    org_id: str
    org_slug: str
    org_name: str
    intro: Optional[str] = None
    topics: list[_OrgDelegateProfileTopicOut] = Field(default_factory=list)


class OrgDelegateProfilePatch(BaseModel):
    """Body for ``PATCH /api/orgs/{slug}/delegate-profile``.

    Phase 30.3: ``page_visibility`` dropped — the column is gone and
    per-topic ``DelegateProfile.visibility`` is the sole audience
    control. The schema preserves backward-compat by accepting the
    field as a no-op (any value validates; the route ignores it). A
    future cleanup pass can drop the field once no clients send it.
    """

    intro: Optional[str] = None
    # Deprecated post-Phase-30.3 — accepted-and-ignored for back-compat.
    page_visibility: Optional[str] = None


class DelegateProfileTopicPatch(BaseModel):
    """Body for ``PATCH /api/orgs/{slug}/delegate-profile/topics/{topic_id}``.

    Phase 30.3: ``visibility`` accepts ``'private'``, ``'followers_only'``,
    or ``'public'``. ``'public_accepting'`` transitions must go through
    the dedicated submit endpoint (approval gate).
    """

    bio: Optional[str] = None
    position_statement: Optional[str] = None
    visibility: Optional[str] = None  # 'private' | 'followers_only' | 'public'

    @field_validator("visibility")
    @classmethod
    def _validate_visibility(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        # NB: 'public_accepting' is intentionally rejected here — it must
        # go through the submit-public-accepting endpoint (approval gate).
        if v not in ("private", "followers_only", "public"):
            raise ValueError(
                "visibility on PATCH must be 'private', 'followers_only', "
                "or 'public'; use POST .../submit-public-accepting for "
                "public_accepting transitions"
            )
        return v


class DelegateApplicationDeny(BaseModel):
    """Body for ``POST /api/orgs/{slug}/delegate-profile/topics/{topic_id}
    /deny`` and the Phase 30.1 B2 per-profile-id deny endpoint. Required
    non-empty comment per spec §B3.
    """

    comment: str = Field(min_length=1, max_length=2000)


class HardRevertBody(BaseModel):
    """Phase 30.3 — optional body for the hard-revert endpoint. The
    endpoint historically only reverted to ``'private'``; post-Phase-30.3
    it also accepts ``'followers_only'`` as a softer destination (public
    delegators still get revoked, but the topic stays visible to
    approved followers).
    """

    target_visibility: Optional[str] = "private"

    @field_validator("target_visibility")
    @classmethod
    def _validate(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return "private"
        if v not in ("private", "followers_only"):
            raise ValueError(
                "target_visibility must be 'private' or 'followers_only'"
            )
        return v


class PendingApplicationOut(BaseModel):
    """Phase 30.1 B2 — one row of GET /delegate-applications-pending.

    Returns enough context (applicant info, intro, bio, position) for the
    approver UI to make a decision without further roundtrips. The
    ``delegate_page_url`` is a frontend route (not an API path).
    """
    profile_id: str
    applicant: dict
    topic_id: str
    topic_name: str
    submitted_at: datetime
    bio: str
    position_statement: Optional[str] = None
    intro: Optional[str] = None
    delegate_page_url: str


class DelegateVoteRationaleOut(BaseModel):
    """Phase 19 B6 — response shape for the rationale GET / PUT endpoints."""

    id: str
    vote_id: str
    content: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DelegateVoteRationaleUpsert(BaseModel):
    """Body for ``PUT /api/votes/{vote_id}/rationale``. Non-empty content."""

    content: str = Field(min_length=1, max_length=10000)


# ===========================================================================
# Phase 77 — Org-scoped direct messaging
# ===========================================================================

class ConversationCreate(BaseModel):
    """Body for ``POST /api/orgs/{slug}/conversations``. First message body
    is required — no empty conversations."""
    conversation_type: str = Field(..., min_length=1)
    recipient_id: Optional[str] = None
    subject: Optional[str] = Field(default=None, max_length=200)
    context_proposal_id: Optional[str] = None
    body: str = Field(..., min_length=1, max_length=5000)

    @field_validator("body")
    @classmethod
    def sanitize_body(cls, v: str) -> str:
        return _sanitize_markdown(v)


class MessageCreate(BaseModel):
    """Body for ``POST /api/orgs/{slug}/conversations/{id}/messages``."""
    body: str = Field(..., min_length=1, max_length=5000)

    @field_validator("body")
    @classmethod
    def sanitize_body(cls, v: str) -> str:
        return _sanitize_markdown(v)


class MessageBlockCreate(BaseModel):
    """Body for ``POST /api/orgs/{slug}/message-blocks``."""
    blocked_id: str = Field(..., min_length=1)


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    sender_id: str
    sender_display_name: str
    body: str
    is_system: bool
    created_at: datetime


class ConversationOut(BaseModel):
    id: str
    org_id: str
    conversation_type: str  # direct | delegate | org_inbox
    initiator_id: str
    recipient_id: Optional[str]
    subject: Optional[str]
    context_proposal_id: Optional[str]
    status: str  # active | closed
    last_message_at: Optional[datetime]
    created_at: datetime
    # Denormalized for list views:
    other_party_display_name: str
    other_party_id: Optional[str]
    unread_count: int
    last_message_preview: Optional[str]


class ConversationDetailOut(BaseModel):
    conversation: ConversationOut
    messages: list[MessageOut]
    context_proposal: Optional[dict] = None


class MessageBlockOut(BaseModel):
    id: str
    blocked_id: str
    blocked_display_name: str
    org_id: str
    created_at: datetime
