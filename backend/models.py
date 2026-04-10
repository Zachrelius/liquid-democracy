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


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
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


class Topic(Base):
    __tablename__ = "topics"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(String, nullable=False, default="")
    color: Mapped[str] = mapped_column(String, nullable=False, default="#6366f1")

    proposal_topics: Mapped[list["ProposalTopic"]] = relationship(
        "ProposalTopic", back_populates="topic"
    )
    delegations: Mapped[list["Delegation"]] = relationship("Delegation", back_populates="topic")
    topic_precedences: Mapped[list["TopicPrecedence"]] = relationship(
        "TopicPrecedence", back_populates="topic"
    )


class Proposal(Base):
    __tablename__ = "proposals"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    author_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum("draft", "deliberation", "voting", "passed", "failed", "withdrawn", name="proposal_status"),
        nullable=False,
        default="draft",
    )
    deliberation_start: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    voting_start: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    voting_end: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    pass_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.50)
    quorum_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.40)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)

    author: Mapped["User"] = relationship("User", back_populates="proposals")
    proposal_topics: Mapped[list["ProposalTopic"]] = relationship(
        "ProposalTopic", back_populates="proposal", cascade="all, delete-orphan"
    )
    votes: Mapped[list["Vote"]] = relationship("Vote", back_populates="proposal", cascade="all, delete-orphan")
    vote_snapshots: Mapped[list["VoteSnapshot"]] = relationship(
        "VoteSnapshot", back_populates="proposal", cascade="all, delete-orphan"
    )

    @property
    def topic_ids(self) -> list[str]:
        return [pt.topic_id for pt in self.proposal_topics]


class ProposalTopic(Base):
    __tablename__ = "proposal_topics"

    proposal_id: Mapped[str] = mapped_column(String, ForeignKey("proposals.id"), primary_key=True)
    topic_id: Mapped[str] = mapped_column(String, ForeignKey("topics.id"), primary_key=True)

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
    vote_value: Mapped[str] = mapped_column(
        Enum("yes", "no", "abstain", name="vote_value"),
        nullable=False,
    )
    is_direct: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    delegate_chain: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    cast_by_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    cast_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)

    proposal: Mapped["Proposal"] = relationship("Proposal", back_populates="votes")
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id], back_populates="votes")
    cast_by: Mapped["User"] = relationship("User", foreign_keys=[cast_by_id])


class VoteSnapshot(Base):
    """Periodic tally snapshots during the voting window for time-series tracking."""

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

    proposal: Mapped["Proposal"] = relationship("Proposal", back_populates="vote_snapshots")
