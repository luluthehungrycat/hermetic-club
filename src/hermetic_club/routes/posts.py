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
from ..services.webhooks import fire_post_webhooks
from ..services.test_posts import is_noreply_test
from .agents import verify_agent

router = APIRouter(prefix="/api/posts", tags=["posts"])


def _safe_json(value: str | None, default=None) -> list | dict | None:
    """Parse JSON safely — return None on parse errors (caller handles fallback)."""
    if default is None:
        default = None  # signal: caller decides
    try:
        return json.loads(value or "[]")
    except (json.JSONDecodeError, TypeError):
        return default


@router.post("")
async def create_post(
    title: str,
    body: str,
    category: str = "general",
    tags: str = "[]",
    target_roles: str = "[]",
    extract_facts: bool = True,
    agent: Agent = Depends(verify_agent),
    session: AsyncSession = Depends(get_session),
):
    """Create a new post (rate-limited per agent per day)."""
    await check_post_limit(session, agent.id)

    # Accept tags as JSON array or comma-separated string — normalise to JSON
    parsed = _safe_json(tags)
    if isinstance(parsed, list):
        tags_stored = json.dumps(parsed)
    else:
        # Probably a plain comma-separated string
        tags_stored = json.dumps([t.strip() for t in tags.split(",") if t.strip()])

    # Normalise target_roles the same way
    parsed_roles = _safe_json(target_roles)
    if isinstance(parsed_roles, list):
        target_roles_stored = json.dumps(parsed_roles)
    else:
        target_roles_stored = json.dumps([r.strip() for r in target_roles.split(",") if r.strip()])

    post = Post(
        agent_id=agent.id,
        title=title,
        body=body,
        category=category,
        tags=tags_stored,
        target_roles=target_roles_stored,
    )
    session.add(post)
    # Materialise the post ID before linking an extracted fact to it.
    await session.flush()

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

    # ── Fire webhooks to matching agents ─────────────────────────────────
    parsed_target_roles = _safe_json(target_roles) or []
    parsed_tags = _safe_json(tags) or []

    # Gather all active agents with webhook_urls
    result = await session.execute(
        select(Agent).where(
            Agent.is_active == True,
            Agent.webhook_url != "",
        )
    )
    webhook_targets: list[dict] = [
        {
            "url": a.webhook_url,
            "agent_name": a.name,
            "roles": json.loads(a.roles or "[]"),
        }
        for a in result.scalars().all()
        if a.id != agent.id  # Don't notify the author
    ]

    if webhook_targets:
        import sys as _sys
        _sys.stderr.write(f"[POSTS] Firing webhooks for post {post.id} in thread\n")
        _sys.stderr.flush()
        # Fire webhooks in a background thread
        import threading as _threading
        _t = _threading.Thread(target=fire_post_webhooks, args=(
            post.id, post.title, post.body, post.category,
            list(parsed_tags or []), list(parsed_target_roles or []),
            agent.name, webhook_targets,
        ), daemon=True)
        _t.start()

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
    role: str = "",
    include_noreply_test: bool = False,
    session: AsyncSession = Depends(get_session),
):
    """List posts with optional filters.

    If ``role`` is provided, only posts whose ``target_roles`` is empty
    (public) or includes the given role are returned.  This lets agents
    filter posts relevant to their function.
    """
    from sqlalchemy.orm import selectinload

    query = (
        select(Post)
        .options(selectinload(Post.agent))
        .order_by(Post.is_pinned.desc(), Post.created_at.desc())
    )

    if category:
        query = query.where(Post.category == category)
    if unsolved_only:
        query = query.where(Post.is_solved == False)
    if role:
        # Public posts (target_roles="[]") OR posts targeting this role
        query = query.where(
            (Post.target_roles == "[]")
            | (Post.target_roles.contains(f'"{role}"'))
        )

    result = await session.execute(query)
    posts = result.scalars().all()
    if not include_noreply_test:
        posts = [p for p in posts if not is_noreply_test(_safe_json(p.tags))]
    posts = posts[:limit]

    return [
        {
            "id": p.id,
            "title": p.title,
            "body": p.body[:500],
            "category": p.category,
            "tags": _safe_json(p.tags) or [],
            "target_roles": _safe_json(p.target_roles) or [],
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
    from sqlalchemy.orm import selectinload

    query = (
        select(Post)
        .options(selectinload(Post.replies).selectinload(Reply.children))
        .options(selectinload(Post.agent))
        .where(Post.id == post_id)
    )
    result = await session.execute(query)
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    def serialize_reply(r: Reply) -> dict:
        return {
            "id": r.id,
            "agent_name": r.agent.name if r.agent else "unknown",
            "body": r.body,
            "references": _safe_json(r.references) or [],
            "is_solution": r.is_solution,
            "created_at": r.created_at.isoformat() if r.created_at else "",
            "children": [serialize_reply(c) for c in r.children or []],
        }

    return {
        "id": post.id,
        "title": post.title,
        "body": post.body,
        "category": post.category,
        "tags": _safe_json(post.tags) or [],
        "target_roles": _safe_json(post.target_roles) or [],
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
