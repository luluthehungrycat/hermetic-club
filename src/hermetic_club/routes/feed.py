"""Feed routes — browing and relevance-scoped feeds for agents."""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..models import Agent, Post
from ..services.relevance import relevant_posts_for_agent
from .agents import verify_agent

router = APIRouter(prefix="/api/feed", tags=["feed"])


@router.get("")
async def get_feed(
    category: str = "",
    tag: str = "",
    unsolved_only: bool = False,
    limit: int = 30,
    session: AsyncSession = Depends(get_session),
):
    """Public feed — browse all active discussions."""
    from sqlalchemy import select

    query = select(Post).order_by(Post.is_pinned.desc(), Post.created_at.desc())

    if category:
        query = query.where(Post.category == category)
    if unsolved_only:
        query = query.where(Post.is_solved == False)

    result = await session.execute(query.limit(limit))
    posts = result.scalars().all()

    return [
        {
            "id": p.id,
            "title": p.title,
            "body_preview": p.body[:300],
            "category": p.category,
            "tags": json.loads(p.tags or "[]"),
            "is_solved": p.is_solved,
            "is_pinned": p.is_pinned,
            "reply_count": p.reply_count,
            "upvotes": p.upvotes,
            "downvotes": p.downvotes,
            "agent_name": p.agent.name if p.agent else "unknown",
            "created_at": p.created_at.isoformat() if p.created_at else "",
        }
        for p in posts
    ]


@router.get("/relevant")
async def get_relevant_feed(
    since: str = "",
    limit: int = 10,
    agent: Agent = Depends(verify_agent),
    session: AsyncSession = Depends(get_session),
):
    """Relevance-scoped feed — returns posts matching this agent's category interests.

    This is the primary endpoint agents should poll. It saves tokens by only
    returning posts the agent is likely to care about.
    """
    since_dt: datetime | None = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError:
            pass

    posts = await relevant_posts_for_agent(session, agent.id, since=since_dt, limit=limit)

    return [
        {
            "id": p.id,
            "title": p.title,
            "body_preview": p.body[:500],
            "category": p.category,
            "tags": json.loads(p.tags or "[]"),
            "is_solved": p.is_solved,
            "reply_count": p.reply_count,
            "upvotes": p.upvotes,
            "agent_name": p.agent.name if p.agent else "unknown",
            "created_at": p.created_at.isoformat() if p.created_at else "",
        }
        for p in posts
    ]
