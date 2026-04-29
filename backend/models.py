import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Organization & Multi-tenancy
# ---------------------------------------------------------------------------

class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    join_policy: Mapped[str] = mapped_column(String, default="approval_required")  # invite_only, approval_required, open
    settings: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)  # org-specific defaults
    # Phase 8.5: nullable self-referential FK. NULL = parent org (top-level);
    # non-NULL = sub-org whose parent has parent_org_id IS NULL. Two-level
    # enforcement is at the API layer, not the schema (Decision 1).
    parent_org_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("organizations.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    # Relationships
    memberships: Mapped[list["OrgMembership"]] = relationship("OrgMembership", back_populates="organization", cascade="all, delete-orphan")
    invitations: Mapped[list["Invitation"]] = relationship("Invitation", back_populates="organization", cascade="all, delete-orphan")
    proposals: Mapped[list["Proposal"]] = relationship(
        "Proposal", back_populates="organization", foreign_keys="Proposal.org_id"
    )
    topics: Mapped[list["Topic"]] = relationship(
        "Topic", back_populates="organization", foreign_keys="Topic.org_id"
    )
    delegate_profiles: Mapped[list["DelegateProfile"]] = relationship(
        "DelegateProfile", back_populates="organization", foreign_keys="DelegateProfile.org_id"
    )
    delegate_applications: Mapped[list["DelegateApplication"]] = relationship("DelegateApplication", back_populates="organization")
    # Phase 8.5: parent ↔ sub-orgs.
    parent_org: Mapped[Optional["Organization"]] = relationship(
        "Organization",
        remote_side="Organization.id",
        back_populates="sub_orgs",
        foreign_keys=[parent_org_id],
    )
    sub_orgs: Mapped[list["Organization"]] = relationship(
        "Organization",
        back_populates="parent_org",
        foreign_keys=[parent_org_id],
        cascade="all, delete-orphan",
    )
    sub_org_memberships: Mapped[list["SubOrgMembership"]] = relationship(
        "SubOrgMembership",
        back_populates="sub_organization",
        cascade="all, delete-orphan",
        foreign_keys="SubOrgMembership.sub_org_id",
    )


class OrgMembership(Base):
    __tablename__ = "org_memberships"
    __table_args__ = (UniqueConstraint("user_id", "org_id", name="uq_org_membership_user_org"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    org_id: Mapped[str] = mapped_column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String, default="member")  # member, moderator, admin, owner
    status: Mapped[str] = mapped_column(String, default="active")  # active, suspended, pending_approval
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    user: Mapped["User"] = relationship("User", back_populates="org_memberships")
    organization: Mapped["Organization"] = relationship("Organization", back_populates="memberships")


class SubOrgMembership(Base):
    """Phase 8.5: a user's membership in a specific sub-org.

    Parallel to OrgMembership for the parent-org membership. A user can belong
    to multiple sub-orgs of the same parent (Decision 2). Sub-org membership is
    OPT-IN — being a parent-org member does not auto-create rows here.
    """
    __tablename__ = "sub_org_memberships"
    __table_args__ = (UniqueConstraint("user_id", "sub_org_id", name="uq_sub_org_membership_user_sub_org"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    sub_org_id: Mapped[str] = mapped_column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String, default="member")  # member, moderator, admin, owner
    status: Mapped[str] = mapped_column(String, default="active")  # active, suspended, pending_approval
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    user: Mapped["User"] = relationship("User", back_populates="sub_org_memberships")
    sub_organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="sub_org_memberships",
        foreign_keys=[sub_org_id],
    )


class Invitation(Base):
    __tablename__ = "invitations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String, nullable=False)
    invited_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(String, default="member")
    token: Mapped[str] = mapped_column(String, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending, accepted, expired, revoked
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    organization: Mapped["Organization"] = relationship("Organization", back_populates="invitations")
    inviter: Mapped["User"] = relationship("User")


class DelegateApplication(Base):
    __tablename__ = "delegate_applications"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    org_id: Mapped[str] = mapped_column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    topic_id: Mapped[str] = mapped_column(String, ForeignKey("topics.id"), nullable=False)
    bio: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending, approved, denied
    feedback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])
    organization: Mapped["Organization"] = relationship("Organization", back_populates="delegate_applications")
    topic: Mapped["Topic"] = relationship("Topic")
    reviewer: Mapped[Optional["User"]] = relationship("User", foreign_keys=[reviewed_by])


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    user_type: Mapped[str] = mapped_column(
        Enum("human", "ai_agent", name="user_type"),
        nullable=False,
        default="human",
    )
    delegation_strategy: Mapped[str] = mapped_column(
        String, nullable=False, default="strict_precedence"
    )
    email: Mapped[Optional[str]] = mapped_column(String, unique=True, nullable=True, index=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    default_follow_policy: Mapped[str] = mapped_column(
        Enum("require_approval", "auto_approve_view", "auto_approve_delegate",
             name="default_follow_policy"),
        nullable=False,
        default="require_approval",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    proposals: Mapped[list["Proposal"]] = relationship("Proposal", back_populates="author")
    delegations_given: Mapped[list["Delegation"]] = relationship(
        "Delegation", foreign_keys="Delegation.delegator_id", back_populates="delegator"
    )
    delegations_received: Mapped[list["Delegation"]] = relationship(
        "Delegation", foreign_keys="Delegation.delegate_id", back_populates="delegate"
    )
    votes: Mapped[list["Vote"]] = relationship("Vote", foreign_keys="Vote.user_id", back_populates="user")
    topic_precedences: Mapped[list["TopicPrecedence"]] = relationship(
        "TopicPrecedence", back_populates="user"
    )
    delegate_profiles: Mapped[list["DelegateProfile"]] = relationship(
        "DelegateProfile", back_populates="user"
    )
    follow_requests_sent: Mapped[list["FollowRequest"]] = relationship(
        "FollowRequest", foreign_keys="FollowRequest.requester_id", back_populates="requester"
    )
    follow_requests_received: Mapped[list["FollowRequest"]] = relationship(
        "FollowRequest", foreign_keys="FollowRequest.target_id", back_populates="target"
    )
    following: Mapped[list["FollowRelationship"]] = relationship(
        "FollowRelationship", foreign_keys="FollowRelationship.follower_id", back_populates="follower"
    )
    followers: Mapped[list["FollowRelationship"]] = relationship(
        "FollowRelationship", foreign_keys="FollowRelationship.followed_id", back_populates="followed"
    )
    org_memberships: Mapped[list["OrgMembership"]] = relationship(
        "OrgMembership", back_populates="user"
    )
    sub_org_memberships: Mapped[list["SubOrgMembership"]] = relationship(
        "SubOrgMembership", back_populates="user"
    )


class Topic(Base):
    __tablename__ = "topics"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(String, nullable=False, default="")
    color: Mapped[str] = mapped_column(String, nullable=False, default="#6366f1")
    org_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("organizations.id"), nullable=True, index=True)
    # Phase 8.5: NULL = parent-org-wide (default); non-NULL = scoped to that sub-org.
    sub_org_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("organizations.id"), nullable=True, index=True
    )

    organization: Mapped[Optional["Organization"]] = relationship(
        "Organization", back_populates="topics", foreign_keys=[org_id]
    )
    sub_organization: Mapped[Optional["Organization"]] = relationship(
        "Organization", foreign_keys=[sub_org_id]
    )
    proposal_topics: Mapped[list["ProposalTopic"]] = relationship(
        "ProposalTopic", back_populates="topic"
    )
    delegations: Mapped[list["Delegation"]] = relationship("Delegation", back_populates="topic")
    topic_precedences: Mapped[list["TopicPrecedence"]] = relationship(
        "TopicPrecedence", back_populates="topic"
    )
    delegate_profiles: Mapped[list["DelegateProfile"]] = relationship(
        "DelegateProfile", back_populates="topic"
    )


class Proposal(Base):
    __tablename__ = "proposals"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    author_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    org_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("organizations.id"), nullable=True, index=True)
    # Phase 8.5: NULL = parent-org-wide (default); non-NULL = scoped to that sub-org.
    sub_org_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("organizations.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(
        Enum(
            "draft", "deliberation", "voting", "passed", "failed",
            "withdrawn", "unresolved",
            name="proposal_status",
        ),
        nullable=False,
        default="draft",
    )
    deliberation_start: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    voting_start: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    voting_end: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    voting_method: Mapped[str] = mapped_column(
        String, nullable=False, default="binary",
    )
    num_winners: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    tie_resolution: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    pass_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.50)
    quorum_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.40)
    # Phase 8: per-proposal sustained-majority override.
    # null = inherit org default; True/False = explicit per-proposal opt-in/out.
    # Authors can only set non-null when org has
    # `sustained_majority_per_proposal_override: true`.
    sustained_majority_enabled: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    # Phase 9: structurally-recorded links to Polis artifacts. List of
    # `polises.id` UUID strings. Null = unset (no structural links); empty
    # list = author explicitly cleared. URL-detected links in the proposal
    # body are NOT stored here — they are rendered by the body parser at
    # read time. This column only carries the structurally-recorded set
    # used by the `require_polis_for_new_proposals` enforcement and the
    # admin "linked deliberations" picker.
    linked_polis_ids: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)

    author: Mapped["User"] = relationship("User", back_populates="proposals")
    organization: Mapped[Optional["Organization"]] = relationship(
        "Organization", back_populates="proposals", foreign_keys=[org_id]
    )
    sub_organization: Mapped[Optional["Organization"]] = relationship(
        "Organization", foreign_keys=[sub_org_id]
    )
    proposal_topics: Mapped[list["ProposalTopic"]] = relationship(
        "ProposalTopic", back_populates="proposal", cascade="all, delete-orphan"
    )
    options: Mapped[list["ProposalOption"]] = relationship(
        "ProposalOption", back_populates="proposal", cascade="all, delete-orphan",
        order_by="ProposalOption.display_order",
    )
    votes: Mapped[list["Vote"]] = relationship("Vote", back_populates="proposal", cascade="all, delete-orphan")
    vote_snapshots: Mapped[list["VoteSnapshot"]] = relationship(
        "VoteSnapshot", back_populates="proposal", cascade="all, delete-orphan"
    )

    @property
    def topic_ids(self) -> list[str]:
        return [pt.topic_id for pt in self.proposal_topics]


class ProposalOption(Base):
    __tablename__ = "proposal_options"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    proposal_id: Mapped[str] = mapped_column(String, ForeignKey("proposals.id"), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    proposal: Mapped["Proposal"] = relationship("Proposal", back_populates="options")


class ProposalTopic(Base):
    __tablename__ = "proposal_topics"

    proposal_id: Mapped[str] = mapped_column(String, ForeignKey("proposals.id"), primary_key=True)
    topic_id: Mapped[str] = mapped_column(String, ForeignKey("topics.id"), primary_key=True)
    relevance: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    proposal: Mapped["Proposal"] = relationship("Proposal", back_populates="proposal_topics")
    topic: Mapped["Topic"] = relationship("Topic", back_populates="proposal_topics")


class Delegation(Base):
    __tablename__ = "delegations"
    __table_args__ = (UniqueConstraint("delegator_id", "topic_id", name="uq_delegation_delegator_topic"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    delegator_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    delegate_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    topic_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("topics.id"), nullable=True, index=True)
    chain_behavior: Mapped[str] = mapped_column(
        Enum("accept_sub", "revert_direct", "abstain", name="chain_behavior"),
        nullable=False,
        default="accept_sub",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)

    delegator: Mapped["User"] = relationship(
        "User", foreign_keys=[delegator_id], back_populates="delegations_given"
    )
    delegate: Mapped["User"] = relationship(
        "User", foreign_keys=[delegate_id], back_populates="delegations_received"
    )
    topic: Mapped[Optional["Topic"]] = relationship("Topic", back_populates="delegations")


class TopicPrecedence(Base):
    __tablename__ = "topic_precedences"
    __table_args__ = (UniqueConstraint("user_id", "topic_id", name="uq_precedence_user_topic"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    topic_id: Mapped[str] = mapped_column(String, ForeignKey("topics.id"), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    user: Mapped["User"] = relationship("User", back_populates="topic_precedences")
    topic: Mapped["Topic"] = relationship("Topic", back_populates="topic_precedences")


class Vote(Base):
    __tablename__ = "votes"
    __table_args__ = (UniqueConstraint("proposal_id", "user_id", name="uq_vote_proposal_user"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    proposal_id: Mapped[str] = mapped_column(String, ForeignKey("proposals.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    vote_value: Mapped[Optional[str]] = mapped_column(
        Enum("yes", "no", "abstain", name="vote_value"),
        nullable=True,
    )
    ballot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    is_direct: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    delegate_chain: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    cast_by_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    cast_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)

    proposal: Mapped["Proposal"] = relationship("Proposal", back_populates="votes")
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id], back_populates="votes")
    cast_by: Mapped["User"] = relationship("User", foreign_keys=[cast_by_id])


class VoteSnapshot(Base):
    """Periodic tally snapshots during the voting window for time-series tracking.

    Phase 8: extended with `multi_option_winners` JSON to record the live
    winner set for approval / ranked_choice proposals at snapshot time, used
    by the sustained-majority worker to detect winner changes across restarts.
    Null for binary proposals.
    """

    __tablename__ = "vote_snapshots"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    proposal_id: Mapped[str] = mapped_column(String, ForeignKey("proposals.id"), nullable=False, index=True)
    simulated_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    yes_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    no_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    abstain_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    not_cast_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_eligible: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    # Phase 8 — multi-option winner snapshot for stable-result evaluation.
    # Shape: {"winners": [option_id, ...], "total_ballots_cast": int}
    multi_option_winners: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    proposal: Mapped["Proposal"] = relationship("Proposal", back_populates="vote_snapshots")


class AuditLog(Base):
    """
    Append-only audit log — records every state-changing action.
    No UPDATE or DELETE operations ever. Write in same transaction as the action.
    """

    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False, index=True)
    actor_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("users.id"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String, nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String, nullable=False)
    target_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    details: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class DelegateProfile(Base):
    """
    A user registered as a public delegate for a specific topic.
    Makes their votes on that topic publicly visible and allows anyone to delegate
    to them on that topic without a prior follow relationship.
    """
    __tablename__ = "delegate_profiles"
    __table_args__ = (UniqueConstraint("user_id", "topic_id", name="uq_delegate_profile_user_topic"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    topic_id: Mapped[str] = mapped_column(String, ForeignKey("topics.id"), nullable=False, index=True)
    org_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("organizations.id"), nullable=True, index=True)
    # Phase 8.5: NULL = parent-org-wide (default); non-NULL = profile scoped to that sub-org.
    # Stored explicitly (rather than derived from topic) for query efficiency per spec.
    sub_org_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("organizations.id"), nullable=True, index=True
    )
    bio: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="delegate_profiles")
    topic: Mapped["Topic"] = relationship("Topic", back_populates="delegate_profiles")
    organization: Mapped[Optional["Organization"]] = relationship(
        "Organization", back_populates="delegate_profiles", foreign_keys=[org_id]
    )
    sub_organization: Mapped[Optional["Organization"]] = relationship(
        "Organization", foreign_keys=[sub_org_id]
    )


class FollowRequest(Base):
    """
    A request from one user to follow another.
    Kept after approval/denial for audit purposes.
    """
    __tablename__ = "follow_requests"
    __table_args__ = (UniqueConstraint("requester_id", "target_id", name="uq_follow_request_requester_target"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    requester_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    target_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        Enum("pending", "approved", "denied", name="follow_request_status"),
        nullable=False,
        default="pending",
    )
    permission_level: Mapped[Optional[str]] = mapped_column(
        Enum("view_only", "delegation_allowed", name="follow_permission_level"),
        nullable=True,
    )
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    responded_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    requester: Mapped["User"] = relationship(
        "User", foreign_keys=[requester_id], back_populates="follow_requests_sent"
    )
    target: Mapped["User"] = relationship(
        "User", foreign_keys=[target_id], back_populates="follow_requests_received"
    )


class FollowRelationship(Base):
    """
    An active follow relationship created when a FollowRequest is approved,
    or automatically when target has auto_approve_* policy.
    """
    __tablename__ = "follow_relationships"
    __table_args__ = (UniqueConstraint("follower_id", "followed_id", name="uq_follow_relationship"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    follower_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    followed_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    permission_level: Mapped[str] = mapped_column(
        Enum("view_only", "delegation_allowed", name="follow_permission_level"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    follower: Mapped["User"] = relationship(
        "User", foreign_keys=[follower_id], back_populates="following"
    )
    followed: Mapped["User"] = relationship(
        "User", foreign_keys=[followed_id], back_populates="followers"
    )


class EmailVerification(Base):
    __tablename__ = "email_verifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String, nullable=False)
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    user: Mapped["User"] = relationship("User")


class PasswordReset(Base):
    __tablename__ = "password_resets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    user: Mapped["User"] = relationship("User")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    user: Mapped["User"] = relationship("User")


class DelegationIntent(Base):
    """
    Queued delegation that auto-activates when the linked follow_request
    is approved with delegation_allowed permission.
    """
    __tablename__ = "delegation_intents"
    __table_args__ = (
        UniqueConstraint("delegator_id", "delegate_id", "topic_id",
                         name="uq_delegation_intent"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    delegator_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False, index=True
    )
    delegate_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False, index=True
    )
    topic_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("topics.id"), nullable=True
    )
    chain_behavior: Mapped[str] = mapped_column(
        Enum("accept_sub", "revert_direct", "abstain", name="chain_behavior"),
        nullable=False,
        default="accept_sub",
    )
    follow_request_id: Mapped[str] = mapped_column(
        String, ForeignKey("follow_requests.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        Enum("pending", "activated", "expired", "cancelled",
             name="delegation_intent_status"),
        nullable=False,
        default="pending",
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    activated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    delegator: Mapped["User"] = relationship("User", foreign_keys=[delegator_id])
    delegate: Mapped["User"] = relationship("User", foreign_keys=[delegate_id])
    topic: Mapped[Optional["Topic"]] = relationship("Topic")
    follow_request: Mapped["FollowRequest"] = relationship("FollowRequest")


# ---------------------------------------------------------------------------
# Phase 9 — Polis (standalone deliberation artifact)
# ---------------------------------------------------------------------------

class Polis(Base):
    """A standalone deliberation artifact, parallel to Topic and Proposal.

    Phase 9 Decision 1: a Polis is a first-class organizational artifact
    with its own lifecycle (`active` -> `archived`), not a phase coupled
    to a proposal. Visibility scope mirrors topics/proposals: org-wide
    when ``sub_org_id`` IS NULL, sub-org-scoped otherwise.

    The platform stores ``polis_conversation_id`` (the opaque slug returned
    by pol.is, 6-300 chars per pol.is API) so we can build embed URLs and
    fetch live participation stats. The column is nullable to support the
    manual-creation fallback flow (admin creates the conversation on pol.is
    first, then pastes the conversation_id into the platform); see
    `phase9_polis_api_findings.md`.
    """
    __tablename__ = "polises"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id"), nullable=False, index=True,
    )
    # Phase 9 Decision 5: NULL = org-wide, non-NULL = sub-org-scoped.
    sub_org_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("organizations.id"), nullable=True, index=True,
    )
    # Opaque slug from pol.is. 6-300 chars per pol.is API; nullable for
    # manual-creation fallback / pending states.
    polis_conversation_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True,
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False, index=True,
    )
    # Phase 9 Decision 8: lifecycle is `active` -> `archived`. Stored as
    # plain String to match Phase 8's pattern (avoids enum-rebuild
    # migration headaches across PG/SQLite).
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False,
    )
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    organization: Mapped["Organization"] = relationship(
        "Organization", foreign_keys=[org_id],
    )
    sub_organization: Mapped[Optional["Organization"]] = relationship(
        "Organization", foreign_keys=[sub_org_id],
    )
    creator: Mapped["User"] = relationship("User", foreign_keys=[created_by])


class PolisXid(Base):
    """Per-user-per-org pseudonymous ID for pol.is participation.

    Phase 9 Decision 4 — identity bridging. The `polis_xid` is an opaque
    random string passed to pol.is via the embed's ``data-xid`` attribute,
    so that:
      - participants get cross-session continuity within a Polis (same xid
        -> same dot in the visualization);
      - pol.is doesn't see platform user identity;
      - the platform can deanonymize for moderation by joining
        ``polis_xid -> user_id``.

    Generated lazily on the user's first Polis interaction in the org via
    `polis_service.get_or_create_polis_xid`. Per-org-isolated: the same
    user gets a different xid in different orgs.
    """
    __tablename__ = "polis_xids"
    __table_args__ = (
        UniqueConstraint("user_id", "org_id", name="uq_polis_xid_user_org"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False, index=True,
    )
    org_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id"), nullable=False, index=True,
    )
    # Opaque random string. Format: secrets.token_urlsafe(16) ~ 22 chars.
    # Pol.is accepts xid 1-999 chars (see phase9_polis_api_findings.md), so
    # this fits comfortably with headroom.
    polis_xid: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])
    organization: Mapped["Organization"] = relationship(
        "Organization", foreign_keys=[org_id],
    )
