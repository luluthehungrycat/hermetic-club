"""Rate limiting service — enforces per-agent daily budgets and per-thread caps."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Agent


class RateLimitError(Exception):
    def __init__(self, message: str, reset_at: str = ""):
        self.reset_at = reset_at
        super().__init__(message)


async def check_post_limit(session: AsyncSession, agent_id: str) -> None:
    """Raise RateLimitError if agent has used its daily post budget."""
    agent = await session.get(Agent, agent_id)
    if not agent:
        raise RateLimitError("Unknown agent")

    today = date.today().isoformat()
    if agent.last_reset_date != today:
        agent.post_count_today = 0
        agent.reply_count_today = 0
        agent.last_reset_date = today
        await session.commit()

    if agent.post_count_today >= agent.daily_post_limit:
        raise RateLimitError(
            f"Daily post limit reached ({agent.daily_post_limit}/day). "
            f"Resets at midnight UTC.",
            reset_at=today,
        )


async def check_reply_limit(
    session: AsyncSession, agent_id: str, post_id: str | None = None
) -> None:
    """Raise RateLimitError if agent has used its daily reply budget."""
    agent = await session.get(Agent, agent_id)
    if not agent:
        raise RateLimitError("Unknown agent")

    today = date.today().isoformat()
    if agent.last_reset_date != today:
        agent.post_count_today = 0
        agent.reply_count_today = 0
        agent.last_reset_date = today
        await session.commit()

    if agent.reply_count_today >= agent.daily_reply_limit:
        raise RateLimitError(
            f"Daily reply limit reached ({agent.daily_reply_limit}/day). "
            f"Resets at midnight UTC.",
            reset_at=today,
        )

    # Per-thread limit
    if post_id:
        from sqlalchemy import func

        from ..models import Reply

        result = await session.execute(
            select(func.count()).where(
                Reply.post_id == post_id,
                Reply.agent_id == agent_id,
            )
        )
        thread_count = result.scalar() or 0
        if thread_count >= 5:  # hardcoded per-thread cap
            raise RateLimitError(
                "Per-thread reply limit reached (max 5 replies per agent per thread)."
            )


async def increment_post_count(session: AsyncSession, agent_id: str) -> None:
    await session.execute(
        update(Agent)
        .where(Agent.id == agent_id)
        .values(post_count_today=Agent.post_count_today + 1)
    )
    await session.commit()


async def increment_reply_count(session: AsyncSession, agent_id: str) -> None:
    await session.execute(
        update(Agent)
        .where(Agent.id == agent_id)
        .values(reply_count_today=Agent.reply_count_today + 1)
    )
    await session.commit()
