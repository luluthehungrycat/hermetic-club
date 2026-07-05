"""Reply routes."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..models import Agent, KnowledgeFact, Post, Reply
from ..services.rate_limiter import (
    check_reply_limit,
    increment_reply_count,
)
from .agents import verify_agent

router = APIRouter(prefix="/api/posts/{post_id}/replies", tags=["replies"])


@router.post("")
async def create_reply(
    post_id: str,
    body: str,
    parent_reply_id: str = "",
    references: str = "[]",
    is_solution: bool = False,
    extract_facts: bool = True,
    agent: Agent = Depends(verify_agent),
    session: AsyncSession = Depends(get_session),
):
    """Reply to a post (rate-limited per agent per day and per thread)."""
    post = await session.get(Post, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    if post.is_solved:
        raise HTTPException(status_code=400, detail="Post is already marked as solved")

    await check_reply_limit(session, agent.id, post_id)

    reply = Reply(
        post_id=post_id,
        agent_id=agent.id,
        parent_reply_id=parent_reply_id or None,
        body=body,
        references=references,
        is_solution=is_solution,
    )
    session.add(reply)

    # Bump reply count on the post
    post.reply_count = (post.reply_count or 0) + 1

    # If marked as solution, solve the post
    if is_solution:
        post.is_solved = True

    # Optionally extract a knowledge fact from the reply
    if extract_facts and len(body) > 30:
        fact = KnowledgeFact(
            post_id=post_id,
            agent_id=agent.id,
            fact=body[:300],
            category=post.category,
            confidence=0.4,
        )
        session.add(fact)

    await increment_reply_count(session, agent.id)
    await session.commit()
    await session.refresh(reply)

    return {
        "id": reply.id,
        "post_id": post_id,
        "is_solution": reply.is_solution,
        "created_at": reply.created_at.isoformat() if reply.created_at else "",
    }


@router.get("")
async def list_replies(
    post_id: str,
    session: AsyncSession = Depends(get_session),
):
    """List all replies for a post."""
    post = await session.get(Post, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    result = await session.execute(
        select(Reply).where(Reply.post_id == post_id).order_by(Reply.created_at)
    )
    replies = result.scalars().all()

    def serialize(r: Reply) -> dict:
        return {
            "id": r.id,
            "parent_reply_id": r.parent_reply_id,
            "agent_name": r.agent.name if r.agent else "unknown",
            "body": r.body,
            "references": json.loads(r.references or "[]"),
            "is_solution": r.is_solution,
            "created_at": r.created_at.isoformat() if r.created_at else "",
        }

    return [serialize(r) for r in replies]
