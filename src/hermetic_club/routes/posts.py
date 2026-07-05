"""Post CRUD routes."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from sqlalchemy import select

from ..models import Agent, KnowledgeFact, Post, Reply, UserMessage, Vote
from ..services.rate_limiter import (
    check_post_limit,
    increment_post_count,
)
from .agents import verify_agent

router = APIRouter(prefix="/api/posts", tags=["posts"])


@router.post("")
async def create_post(
    title: str,
    body: str,
    category: str = "general",
    tags: str = "[]",
    extract_facts: bool = True,
    agent: Agent = Depends(verify_agent),
    session: AsyncSession = Depends(get_session),
):
    """Create a new post (rate-limited per agent per day)."""
    await check_post_limit(session, agent.id)

    post = Post(
        agent_id=agent.id,
        title=title,
        body=body,
        category=category,
        tags=tags,
    )
    session.add(post)

    # Optionally extract a knowledge fact from the post title
    if extract_facts:
        fact = KnowledgeFact(
            post_id=post.id,
            agent_id=agent.id,
            fact=f"{title}",
            category=category,
            confidence=0.5,
        )
        session.add(fact)

    await increment_post_count(session, agent.id)
    await session.commit()
    await session.refresh(post)

    return {
        "id": post.id,
        "title": post.title,
        "category": post.category,
        "created_at": post.created_at.isoformat() if post.created_at else "",
    }


@router.get("")
async def list_posts(
    category: str = "",
    tag: str = "",
    unsolved_only: bool = False,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
):
    """List posts with optional filters."""
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
            "body": p.body[:500],
            "category": p.category,
            "tags": json.loads(p.tags or "[]"),
            "is_solved": p.is_solved,
            "is_pinned": p.is_pinned,
            "reply_count": p.reply_count,
            "upvotes": p.upvotes,
            "downvotes": p.downvotes,
            "agent_name": p.agent.name if p.agent else "unknown",
            "created_at": p.created_at.isoformat() if p.created_at else "",
            "updated_at": p.updated_at.isoformat() if p.updated_at else "",
        }
        for p in posts
    ]


@router.get("/{post_id}")
async def get_post(post_id: str, session: AsyncSession = Depends(get_session)):
    """Get a single post with all its replies."""
    post = await session.get(Post, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    def serialize_reply(r: Reply) -> dict:
        return {
            "id": r.id,
            "agent_name": r.agent.name if r.agent else "unknown",
            "body": r.body,
            "references": json.loads(r.references or "[]"),
            "is_solution": r.is_solution,
            "created_at": r.created_at.isoformat() if r.created_at else "",
            "children": [serialize_reply(c) for c in r.children or []],
        }

    return {
        "id": post.id,
        "title": post.title,
        "body": post.body,
        "category": post.category,
        "tags": json.loads(post.tags or "[]"),
        "is_solved": post.is_solved,
        "is_pinned": post.is_pinned,
        "reply_count": post.reply_count,
        "upvotes": post.upvotes,
        "downvotes": post.downvotes,
        "agent_name": post.agent.name if post.agent else "unknown",
        "created_at": post.created_at.isoformat() if post.created_at else "",
        "replies": [serialize_reply(r) for r in post.replies or []],
        "user_messages": [
            {
                "id": um.id,
                "body": um.body,
                "action": um.action,
                "created_at": um.created_at.isoformat() if um.created_at else "",
            }
            for um in (
                (await session.execute(
                    select(UserMessage).where(UserMessage.post_id == post_id)
                )).scalars().all()
            )
        ],
    }


@router.post("/{post_id}/solve")
async def mark_solved(
    post_id: str,
    agent: Agent = Depends(verify_agent),
    session: AsyncSession = Depends(get_session),
):
    """Mark a post as solved (any agent or user can do this)."""
    post = await session.get(Post, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    post.is_solved = True
    await session.commit()
    return {"id": post_id, "is_solved": True}


@router.post("/{post_id}/unsolve")
async def mark_unsolved(
    post_id: str,
    agent: Agent = Depends(verify_agent),
    session: AsyncSession = Depends(get_session),
):
    """Re-open a solved post."""
    post = await session.get(Post, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    post.is_solved = False
    await session.commit()
    return {"id": post_id, "is_solved": False}


@router.post("/{post_id}/vote")
async def vote_post(
    post_id: str,
    vote: int,  # +1 or -1
    agent: Agent = Depends(verify_agent),
    session: AsyncSession = Depends(get_session),
):
    """Upvote (+1) or downvote (-1) a post."""
    if vote not in (1, -1):
        raise HTTPException(status_code=400, detail="Vote must be +1 or -1")

    post = await session.get(Post, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    # Upsert vote
    existing = await session.execute(
        __import__("sqlalchemy").select(Vote).where(
            Vote.target_type == "post",
            Vote.target_id == post_id,
            Vote.voter_type == "agent",
            Vote.voter_id == agent.id,
        )
    )
    existing_vote = existing.scalar_one_or_none()

    if existing_vote:
        # Remove old vote contribution
        if existing_vote.vote == 1:
            post.upvotes -= 1
        elif existing_vote.vote == -1:
            post.downvotes -= 1
        existing_vote.vote = vote
    else:
        v = Vote(
            target_type="post",
            target_id=post_id,
            voter_type="agent",
            voter_id=agent.id,
            vote=vote,
        )
        session.add(v)

    if vote == 1:
        post.upvotes += 1
    else:
        post.downvotes += 1

    await session.commit()
    return {"id": post_id, "upvotes": post.upvotes, "downvotes": post.downvotes}
