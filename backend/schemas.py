from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, field_validator, Field
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
    """Passwordless login for whitelisted demo personas (Phase 6.5)."""
    username: str = Field(min_length=1, max_length=50)


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

    model_config = {"from_attributes": True}


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
    description: str = Field(default="", max_length=500)
    color: str = "#6366f1"
    # Phase 8.5: optional sub-org scope. NULL = parent-org-wide (default).
    sub_org_id: Optional[str] = None

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: str) -> str:
        if not v.startswith("#") or len(v) not in (4, 7):
            raise ValueError("color must be a hex string like #abc or #aabbcc")
        return v


class TopicOut(BaseModel):
    id: str
    name: str
    description: str
    color: str
    # Phase 8.5: NULL for parent-org-wide topics. Tests/clients can rely on
    # this to render scope badges; existing single-org clients receive None
    # everywhere and behave unchanged.
    sub_org_id: Optional[str] = None

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


class OptionCreate(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class OptionOut(BaseModel):
    id: str
    proposal_id: str
    label: str
    description: str
    display_order: int
    created_at: datetime

    model_config = {"from_attributes": True}


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
    # Phase 8 — per-proposal sustained-majority override.
    # null = inherit org default; True/False = explicit. Server rejects
    # non-null when org has `sustained_majority_per_proposal_override: false`.
    sustained_majority_enabled: Optional[bool] = None
    # Phase 8.5: optional sub-org scope. NULL = parent-org-wide (default).
    # If non-null, all referenced topics must be either parent-org-wide or
    # the same sub-org's; eligibility derives via SubOrgMembership.
    sub_org_id: Optional[str] = None
    # Phase 9 Decision 2 / Decision 7: structurally-recorded Polis links.
    # Validated at route layer (each ID must exist, viewer must be in
    # eligible_viewers_for_polis, status must be active). Required when
    # the org's `require_polis_for_new_proposals` config is True.
    linked_polis_ids: Optional[list[str]] = None

    @field_validator("voting_method")
    @classmethod
    def validate_voting_method(cls, v: str) -> str:
        if v not in ("binary", "approval", "ranked_choice"):
            raise ValueError("voting_method must be binary, approval, or ranked_choice")
        return v

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
    # Phase 8 — per-proposal sustained-majority override (see ProposalCreate).
    # Use Field with explicit default sentinel so omitted vs. null differ:
    # we only update the column when the field is present in the payload.
    sustained_majority_enabled: Optional[bool] = Field(default=None)
    # Phase 9 — replace the linked-Polis set on update (omitted = leave alone).
    # When present, the route diffs old vs. new and emits
    # `polis.linked_to_proposal` / `polis.unlinked_from_proposal` per change.
    linked_polis_ids: Optional[list[str]] = Field(default=None)

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
    created_at: datetime
    updated_at: datetime
    topics: list[ProposalTopicOut] = []
    options: list[OptionOut] = []
    # Phase 8 — null = inherit org default; True/False = explicit override.
    sustained_majority_enabled: Optional[bool] = None
    # Phase 8.5 — null for parent-org-wide proposals.
    sub_org_id: Optional[str] = None
    # Phase 9 — structurally-linked Polises. Stored on Proposal.linked_polis_ids
    # JSON column; resolved into rich objects on detail GET.
    linked_polis_ids: Optional[list[str]] = None
    linked_polises: Optional[list[dict]] = None

    model_config = {"from_attributes": True}


class SustainedMajorityStatus(BaseModel):
    """Phase 8 — sustained-majority status block surfaced on /results.

    Populated only for proposals where sustained-majority is active. `active`
    is the fully-resolved boolean (per-proposal override applied to org default).
    `current_support` is the latest snapshot's yes-fraction; `distance_to_floor`
    is `current_support - floor` (negative means breached).
    """
    active: bool = False
    threshold: float = 0.5
    floor: float = 0.45
    failure_mode: str = "fail"
    # Latest sample stats (binary). Multi-option uses winners_history below.
    current_support: Optional[float] = None
    distance_to_floor: Optional[float] = None
    floor_breached: bool = False
    approaching_floor: bool = False  # within FLOOR_APPROACH_DELTA (5pp default)
    # Multi-option only — set when in stable-result window
    in_stable_result_window: bool = False
    stable_result_locked: bool = False
    current_winners: list[str] = []
    # Bookkeeping
    extension_count: int = 0
    voting_end: Optional[datetime] = None


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
    is_direct: Optional[bool] = None
    delegate_chain: Optional[list[str]] = None
    cast_by: Optional[UserOut] = None
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
    time_series: list[SnapshotPoint] = []
    # Approval-voting fields (populated only when voting_method == "approval")
    option_approvals: Optional[dict[str, int]] = None
    option_labels: Optional[dict[str, str]] = None
    total_ballots_cast: Optional[int] = None
    total_abstain: Optional[int] = None
    winners: Optional[list[str]] = None
    tied: Optional[bool] = None
    tie_resolution: Optional[dict] = None
    # Ranked-choice / STV fields (populated only when voting_method == "ranked_choice")
    rounds: Optional[list[RCVRoundOut]] = None
    method: Optional[str] = None      # "irv" or "stv"
    num_winners: Optional[int] = None
    # Phase 8 — sustained-majority status block. Populated for every proposal;
    # `active=False` for proposals where sustained-majority is not in effect,
    # in which case the rest of the fields are at defaults and the frontend
    # hides the block.
    sustained_majority: Optional["SustainedMajorityStatus"] = None


class TieResolutionRequest(BaseModel):
    selected_option_id: str

    @field_validator("selected_option_id")
    @classmethod
    def validate_option_id(cls, v: str) -> str:
        return _validate_uuid(v)


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
    is_active: bool
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


class OrgCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=3, max_length=50)
    description: str = ""
    join_policy: str = "approval_required"

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
        if v not in ("invite_only", "approval_required", "open"):
            raise ValueError("join_policy must be invite_only, approval_required, or open")
        return v


class OrgUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    join_policy: Optional[str] = None
    settings: Optional[dict] = None

    @field_validator("join_policy")
    @classmethod
    def validate_join_policy(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("invite_only", "approval_required", "open"):
            raise ValueError("join_policy must be invite_only, approval_required, or open")
        return v


class OrgOut(BaseModel):
    id: str
    name: str
    slug: str
    description: str
    join_policy: str
    settings: dict = {}
    created_at: datetime
    member_count: Optional[int] = None
    user_role: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class OrgMemberOut(BaseModel):
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


class DelegateApplicationCreate(BaseModel):
    topic_id: str
    bio: str = Field(min_length=1, max_length=2000)

    @field_validator("topic_id")
    @classmethod
    def validate_topic_id(cls, v: str) -> str:
        return _validate_uuid(v)


class DelegateApplicationOut(BaseModel):
    id: str
    user_id: str
    username: str = ""
    display_name: str = ""
    # Phase 9.8 — see UserOut.avatar_url.
    avatar_url: Optional[str] = None
    topic_id: str
    topic_name: str = ""
    bio: str
    status: str
    feedback: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class DelegateApplicationReview(BaseModel):
    feedback: Optional[str] = None


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
    user_role: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class SubOrgMemberInvite(BaseModel):
    """Body for `POST /api/orgs/{slug}/sub-orgs/{sub_slug}/members/invite`."""
    user_id: str
    role: str = "member"

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, v: str) -> str:
        return _validate_uuid(v)

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in ("member", "moderator", "admin", "owner"):
            raise ValueError("role must be member, moderator, admin, or owner")
        return v


class SubOrgMemberRoleUpdate(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in ("member", "moderator", "admin", "owner"):
            raise ValueError("role must be member, moderator, admin, or owner")
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

    Dual-path create per `phase9_polis_api_findings.md`:
      - Programmatic path (settings.polis_auth_token set): the route calls
        pol.is to create the conversation and seed it; `polis_conversation_id`
        in the body is ignored (the route computes it from the API response).
      - Manual-fallback (no auth token): the operator created the conversation
        on pol.is themselves and pastes the slug in `polis_conversation_id`.
        The seed_statements list is preserved as `intended_seed_statements`
        on the platform record so the FE can render "paste these into pol.is
        admin UI" UX.
    """
    title: str = Field(min_length=1, max_length=500)
    prompt: str = Field(min_length=1, max_length=10000)
    sub_org_id: Optional[str] = None
    seed_statements: list[str] = Field(default_factory=list, max_length=200)
    polis_conversation_id: Optional[str] = Field(
        default=None, min_length=1, max_length=300,
    )


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
    title: Optional[str] = Field(default=None, min_length=1, max_length=500)
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
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
