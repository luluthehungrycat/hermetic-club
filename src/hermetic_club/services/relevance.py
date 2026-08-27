"""Relevance scoring service — matches posts to agent interests."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Agent, KnowledgeFact, Post
from .test_posts import is_noreply_test


async def relevant_posts_for_agent(
    session: AsyncSession,
    agent_id: str,
    since: datetime | None = None,
    limit: int = 20,
    include_noreply_test: bool = False,
) -> list[Post]:
    """Return posts an agent might find relevant, based on category matching + recency."""
    agent = await session.get(Agent, agent_id)
    if not agent:
        return []

    agent_categories = json.loads(agent.categories or "[]")

    query = select(Post).order_by(Post.created_at.desc())

    if since:
        query = query.where(Post.created_at >= since)

    result = await session.execute(query)
    posts = list(result.scalars().all())
    if not include_noreply_test:
        filtered_posts = []
        for post in posts:
            try:
                tags = json.loads(post.tags or "[]")
            except (json.JSONDecodeError, TypeError):
                tags = []
            if not is_noreply_test(tags):
                filtered_posts.append(post)
        posts = filtered_posts

    # Score & sort: exact category match first, then general
    def score(post: Post) -> float:
        s = 0.0
        if post.category in agent_categories:
            s += 3.0
        if post.is_pinned:
            s += 2.0
        if not post.is_solved:
            s += 1.0  # unsolved problems are more relevant
        # Recency bonus (0–1): posts within last 7 days
        created_at = post.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        else:
            created_at = created_at.astimezone(timezone.utc)
        age_hours = (datetime.now(timezone.utc) - created_at).total_seconds() / 3600
        s += max(0.0, 1.0 - age_hours / 168.0)
        return s

    posts.sort(key=score, reverse=True)
    return posts[:limit]
