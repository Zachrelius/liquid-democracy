from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, field_validator


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    username: str
    display_name: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: str
    username: str
    display_name: str
    is_admin: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------

class TopicCreate(BaseModel):
    name: str
    description: str = ""
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


# ---------------------------------------------------------------------------
# Proposals
# ---------------------------------------------------------------------------

class ProposalCreate(BaseModel):
    title: str
    body: str = ""
    topic_ids: list[str] = []
    pass_threshold: float = 0.50
    quorum_threshold: float = 0.40


class ProposalUpdate(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    topic_ids: Optional[list[str]] = None


class ProposalOut(BaseModel):
    id: str
    title: str
    body: str
    author_id: str
    author: UserOut
    status: str
    deliberation_start: Optional[datetime]
    voting_start: Optional[datetime]
    voting_end: Optional[datetime]
    pass_threshold: float
    quorum_threshold: float
    created_at: datetime
    updated_at: datetime
    topics: list[TopicOut] = []

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Delegations
# ---------------------------------------------------------------------------

class DelegationUpsert(BaseModel):
    delegate_id: str
    topic_id: Optional[str] = None  # None = global
    chain_behavior: str = "accept_sub"

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
# Topic Precedence
# ---------------------------------------------------------------------------

class TopicPrecedenceSet(BaseModel):
    """Ordered list of topic_ids from highest to lowest priority."""
    ordered_topic_ids: list[str]


class TopicPrecedenceOut(BaseModel):
    topic_id: str
    topic: TopicOut
    priority: int

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Votes
# ---------------------------------------------------------------------------

class VoteCast(BaseModel):
    vote_value: str

    @field_validator("vote_value")
    @classmethod
    def validate_vote_value(cls, v: str) -> str:
        allowed = {"yes", "no", "abstain"}
        if v not in allowed:
            raise ValueError(f"vote_value must be one of {allowed}")
        return v


class VoteOut(BaseModel):
    id: str
    proposal_id: str
    user_id: str
    vote_value: str
    is_direct: bool
    delegate_chain: Optional[list[str]]
    cast_by_id: str
    cast_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MyVoteStatus(BaseModel):
    """How the current user's vote is being cast on a proposal."""
    vote_value: Optional[str]        # None if not cast
    is_direct: Optional[bool]
    delegate_chain: Optional[list[str]]
    cast_by: Optional[UserOut]
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
    yes: int
    no: int
    abstain: int
    not_cast: int
    total_eligible: int
    yes_pct: float
    no_pct: float
    abstain_pct: float
    quorum_met: bool
    threshold_met: bool
    time_series: list[SnapshotPoint] = []


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
# Admin
# ---------------------------------------------------------------------------

class AdvanceProposalRequest(BaseModel):
    voting_end: Optional[datetime] = None  # Required when advancing to voting


class SeedRequest(BaseModel):
    scenario: str = "healthcare"  # "healthcare" | "environment"


class TimeSimulationRequest(BaseModel):
    proposal_id: str
    simulated_time: datetime
