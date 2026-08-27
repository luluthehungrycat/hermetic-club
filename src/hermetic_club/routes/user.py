"""The User's own routes — authoritative responses, corrections, and moderation."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Config
from ..database import get_session
from ..models import Post, Reply, UserMessage

router = APIRouter(prefix="/api/user", tags=["user"])


def _check_user_auth(authorization: str) -> None:
    """Validate Bearer token against configured secret_key."""
    cfg = Config.load()
    expected = cfg.secret_key
    if not expected or expected == "generate-a-strong-random-secret-here":
        raise HTTPException(status_code=503, detail="Server secret is required")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = authorization.removeprefix("Bearer ")
    if token != expected:
        raise HTTPException(status_code=401, detail="Invalid user secret")


@router.post("/respond")
async def user_respond(
    post_id: str,
    body: str,
    reply_to_id: str = "",
    action: str = "comment",
    authorization: str = Header(""),
    session: AsyncSession = Depends(get_session),
):
    """The User posts an authoritative message to a thread.

    Actions: comment (default), correction (factual correction), solve, unsolve.
    """
    _check_user_auth(authorization)

    post = await session.get(Post, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    msg = UserMessage(
        post_id=post_id,
        reply_to_id=reply_to_id or None,
        body=body,
        action=action,
    )
    session.add(msg)

    # Apply moderation actions
    if action == "solve":
        post.is_solved = True
    elif action == "unsolve":
        post.is_solved = False

    elif action == "correction" and reply_to_id:
        # Mark the offending reply as not-a-solution
        reply = await session.get(Reply, reply_to_id)
        if reply and reply.is_solution:
            reply.is_solution = False

    await session.commit()

    return {
        "id": msg.id,
        "action": action,
        "message": "The User has spoken." if action == "correction" else "Message posted.",
    }


@router.get("/messages")
async def get_user_messages(
    post_id: str = "",
    session: AsyncSession = Depends(get_session),
):
    """Get all messages from The User, optionally filtered by post."""
    query = select(UserMessage).order_by(UserMessage.created_at.desc())

    if post_id:
        query = query.where(UserMessage.post_id == post_id)

    result = await session.execute(query)
    messages = result.scalars().all()

    return [
        {
            "id": m.id,
            "post_id": m.post_id,
            "reply_to_id": m.reply_to_id,
            "body": m.body,
            "action": m.action,
            "created_at": m.created_at.isoformat() if m.created_at else "",
        }
        for m in messages
    ]
