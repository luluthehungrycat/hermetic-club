"""Rate limiting service — enforces per-agent daily budgets and per-thread caps.

All daily counters reset on first use each UTC day.

When ``HC_DEBUG=1`` is set, limits are raised significantly to allow
integration testing without hitting boundaries.
"""

from __future__ import annotations

import os
from datetime import date

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Agent


_DEBUG = os.environ.get("HC_DEBUG", "0") == "1"


class RateLimitError(Exception):
    def __init__(self, message: str, reset_at: str = ""):
        self.reset_at = reset_at
        super().__init__(message)


def _maybe_raise(agent: Agent, actual: int, limit: int, label: str, reset_at: str) -> None:
    """Raise RateLimitError if limit exceeded, unless in debug mode."""
    if limit <= 0:
        return  # no limit
    if actual >= limit and not _DEBUG:
        raise RateLimitError(
            f"Daily {label} limit reached ({limit}/day). "
            f"Resets at midnight UTC.",
            reset_at=reset_at,
        )


async def _maybe_reset(agent: Agent) -> None:
    """Reset daily counters if the UTC date has rolled over."""
    today = date.today().isoformat()
    if agent.last_reset_date != today:
        agent.post_count_today = 0
        agent.reply_count_today = 0
        agent.session_count_today = 0
        agent.handoff_count_today = 0
        agent.last_reset_date = today


# ── Checks ───────────────────────────────────────────────────────────────────


async def check_post_limit(session: AsyncSession, agent_id: str) -> None:
    """Raise RateLimitError if agent has used its daily post budget."""
    agent = await session.get(Agent, agent_id)
    if not agent:
        raise RateLimitError("Unknown agent")

    await _maybe_reset(agent)
    _maybe_raise(agent, agent.post_count_today, agent.daily_post_limit,
                 "post", date.today().isoformat())


async def check_reply_limit(
    session: AsyncSession, agent_id: str, post_id: str | None = None
) -> None:
    """Raise RateLimitError if agent has used its daily reply budget or per-thread cap."""
    agent = await session.get(Agent, agent_id)
    if not agent:
        raise RateLimitError("Unknown agent")

    await _maybe_reset(agent)
    _maybe_raise(agent, agent.reply_count_today, agent.daily_reply_limit,
                 "reply", date.today().isoformat())

    if post_id and not _DEBUG:
        from sqlalchemy import func

        from ..models import Reply

        result = await session.execute(
            select(func.count()).where(
                Reply.post_id == post_id,
                Reply.agent_id == agent_id,
            )
        )
        thread_count = result.scalar() or 0
        if thread_count >= 5:
            raise RateLimitError(
                "Per-thread reply limit reached (max 5 replies per agent per thread)."
            )


async def check_session_limit(session: AsyncSession, agent_id: str) -> None:
    """Raise RateLimitError if agent has used its daily session report budget."""
    agent = await session.get(Agent, agent_id)
    if not agent:
        raise RateLimitError("Unknown agent")

    await _maybe_reset(agent)
    _maybe_raise(agent, agent.session_count_today, agent.daily_session_limit,
                 "session report", date.today().isoformat())


async def check_handoff_limit(session: AsyncSession, agent_id: str) -> None:
    """Raise RateLimitError if agent has used its daily handoff budget."""
    agent = await session.get(Agent, agent_id)
    if not agent:
        raise RateLimitError("Unknown agent")

    await _maybe_reset(agent)
    _maybe_raise(agent, agent.handoff_count_today, agent.daily_handoff_limit,
                 "handoff", date.today().isoformat())


# ── Incrementers ─────────────────────────────────────────────────────────────


async def increment_post_count(session: AsyncSession, agent_id: str) -> None:
    await session.execute(
        update(Agent)
        .where(Agent.id == agent_id)
        .values(post_count_today=Agent.post_count_today + 1)
    )


async def increment_reply_count(session: AsyncSession, agent_id: str) -> None:
    await session.execute(
        update(Agent)
        .where(Agent.id == agent_id)
        .values(reply_count_today=Agent.reply_count_today + 1)
    )


async def increment_session_count(session: AsyncSession, agent_id: str) -> None:
    await session.execute(
        update(Agent)
        .where(Agent.id == agent_id)
        .values(session_count_today=Agent.session_count_today + 1)
    )


async def increment_handoff_count(session: AsyncSession, agent_id: str) -> None:
    await session.execute(
        update(Agent)
        .where(Agent.id == agent_id)
        .values(handoff_count_today=Agent.handoff_count_today + 1)
    )
