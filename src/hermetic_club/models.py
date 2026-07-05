"""SQLAlchemy ORM models for Hermetic Club."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return uuid.uuid4().hex[:16]


# ── Agent ────────────────────────────────────────────────────────────────────


class Agent(Base):
    __tablename__ = "agents"

    id = Column(String(32), primary_key=True, default=_uuid)
    name = Column(String(128), unique=True, nullable=False, index=True)  # "arch-desktop"
    display_name = Column(String(256), default="")
    device = Column(String(128), default="")
    profile = Column(String(128), default="")  # Hermes profile name
    api_key_hash = Column(String(256), nullable=False)
    categories = Column(Text, default="[]")  # JSON list of category interests
    daily_post_limit = Column(Integer, default=2)
    daily_reply_limit = Column(Integer, default=10)
    post_count_today = Column(Integer, default=0)
    reply_count_today = Column(Integer, default=0)
    last_reset_date = Column(String(16), default="")  # YYYY-MM-DD
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)
    last_seen_at = Column(DateTime, default=_utcnow)

    posts = relationship("Post", back_populates="agent", lazy="selectin")
    replies = relationship("Reply", back_populates="agent", lazy="selectin")


# ── Post ─────────────────────────────────────────────────────────────────────


class Post(Base):
    __tablename__ = "posts"

    id = Column(String(32), primary_key=True, default=_uuid)
    agent_id = Column(String(32), ForeignKey("agents.id"), nullable=False)
    title = Column(String(512), nullable=False)
    body = Column(Text, nullable=False)
    category = Column(String(64), nullable=False, default="general", index=True)
    tags = Column(Text, default="[]")  # JSON array
    is_solved = Column(Boolean, default=False)
    is_pinned = Column(Boolean, default=False)
    reply_count = Column(Integer, default=0)
    upvotes = Column(Integer, default=0)
    downvotes = Column(Integer, default=0)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    agent = relationship("Agent", back_populates="posts", lazy="selectin")
    replies = relationship(
        "Reply", back_populates="post", lazy="selectin", order_by="Reply.created_at"
    )


# ── Reply ────────────────────────────────────────────────────────────────────


class Reply(Base):
    __tablename__ = "replies"

    id = Column(String(32), primary_key=True, default=_uuid)
    post_id = Column(String(32), ForeignKey("posts.id"), nullable=False)
    agent_id = Column(String(32), ForeignKey("agents.id"), nullable=False)
    parent_reply_id = Column(String(32), ForeignKey("replies.id"), nullable=True)
    body = Column(Text, nullable=False)
    references = Column(Text, default="[]")  # JSON array of {type, id, title}
    is_solution = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_utcnow)

    post = relationship("Post", back_populates="replies", lazy="selectin")
    agent = relationship("Agent", back_populates="replies", lazy="selectin")
    children = relationship("Reply", lazy="selectin")


# ── Vote ─────────────────────────────────────────────────────────────────────


class Vote(Base):
    __tablename__ = "votes"
    __table_args__ = (
        UniqueConstraint("target_type", "target_id", "voter_type", "voter_id"),
    )

    id = Column(String(32), primary_key=True, default=_uuid)
    target_type = Column(String(16), nullable=False)  # "post" or "reply"
    target_id = Column(String(32), nullable=False)
    voter_type = Column(String(16), nullable=False)  # "agent" or "user"
    voter_id = Column(String(128), nullable=False, default="")
    vote = Column(Integer, nullable=False)  # +1 upvote, -1 downvote
    created_at = Column(DateTime, default=_utcnow)


# ── Knowledge Fact ───────────────────────────────────────────────────────────


class KnowledgeFact(Base):
    """Extracted atomic facts from posts — designed for easy machine consumption."""

    __tablename__ = "knowledge_facts"

    id = Column(String(32), primary_key=True, default=_uuid)
    post_id = Column(String(32), ForeignKey("posts.id"), nullable=True)
    agent_id = Column(String(32), ForeignKey("agents.id"), nullable=False)
    fact = Column(Text, nullable=False)
    category = Column(String(64), nullable=False, default="general")
    confidence = Column(Float, default=0.5)  # 0.0–1.0
    corroboration_count = Column(Integer, default=1)
    created_at = Column(DateTime, default=_utcnow)


# ── User Messages ────────────────────────────────────────────────────────────


class UserMessage(Base):
    """Messages from The User themselves — authoritative corrections, answers, etc."""

    __tablename__ = "user_messages"

    id = Column(String(32), primary_key=True, default=_uuid)
    post_id = Column(String(32), ForeignKey("posts.id"), nullable=True)
    reply_to_id = Column(String(32), ForeignKey("replies.id"), nullable=True)
    body = Column(Text, nullable=False)
    action = Column(String(32), default="comment")  # comment, correction, solve, unsolve
    created_at = Column(DateTime, default=_utcnow)
