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


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)


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

    model_config = {"from_attributes": True}


class UserSearchResultWithContext(BaseModel):
    """Search result enriched with follow/delegate context for the viewer."""
    id: str
    username: str
    display_name: str
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

    model_config = {"from_attributes": True}


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
    is_direct: Optional[bool] = None
    delegate_chain: Optional[list[str]] = None
    cast_by: Optional[UserOut] = None
    message: str                      # Human-readable explanation


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


class ProposalResults(BaseModel):
    proposal_id: str
    voting_method: str = "binary"
    yes: int = 0
    no: int = 0
    abstain: int = 0
    not_cast: int = 0
    total_eligible: int = 0
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


class VoteFlowEdge(BaseModel):
    source: str     # from (delegator)
    target: str     # to (delegate)
    topic: Optional[str] = None
    topic_color: str = "#95a5a6"
    is_active: bool = True


class VoteFlowClusters(BaseModel):
    yes: dict = {}
    no: dict = {}
    abstain: dict = {}
    not_cast: dict = {}


class VoteFlowGraph(BaseModel):
    proposal_id: str
    proposal_title: str
    total_eligible: int
    nodes: list[VoteFlowNode]
    edges: list[VoteFlowEdge]
    clusters: VoteFlowClusters


# ---------------------------------------------------------------------------
# Personal Delegation Network
# ---------------------------------------------------------------------------

class PersonalNetworkCenter(BaseModel):
    id: str
    label: str
    delegating_to: int
    delegated_from: int


class PersonalNetworkNode(BaseModel):
    id: str
    label: str
    relationship: str   # "delegate" or "delegator"
    topics: list[str]
    is_public_delegate: bool = False
    total_delegators: int = 0


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
