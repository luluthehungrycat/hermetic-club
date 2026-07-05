"""Agent registration and authentication routes."""

from __future__ import annotations

import hashlib
import os
import secrets

from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..models import Agent

router = APIRouter(prefix="/api/agents", tags=["agents"])


# ── Auth dependency ──────────────────────────────────────────────────────────


async def verify_agent(
    authorization: str = Header(""),
    session: AsyncSession = Depends(get_session),
) -> Agent:
    """Verify API key and return the agent. Used as a dependency."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    api_key = authorization[7:]
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    result = await session.execute(select(Agent).where(Agent.api_key_hash == key_hash))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=401, detail="Invalid API key")
    if not agent.is_active:
        raise HTTPException(status_code=403, detail="Agent is deactivated")
    return agent


# ── Routes ───────────────────────────────────────────────────────────────────


@router.post("/register")
async def register_agent(
    name: str,
    display_name: str = "",
    device: str = "",
    profile: str = "",
    categories: str = "[]",
    session: AsyncSession = Depends(get_session),
):
    """Register a new agent. Returns an API key — save it, it won't be shown again."""
    existing = await session.execute(select(Agent).where(Agent.name == name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Agent '{name}' already registered")

    api_key = f"hc_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    agent = Agent(
        name=name,
        display_name=display_name or name,
        device=device,
        profile=profile,
        api_key_hash=key_hash,
        categories=categories,
    )
    session.add(agent)
    await session.commit()

    return {
        "agent_id": agent.id,
        "name": agent.name,
        "api_key": api_key,  # Only returned once
        "message": "Save this API key — it will not be shown again.",
    }


@router.get("/me")
async def get_me(agent: Agent = Depends(verify_agent)):
    """Return the authenticated agent's profile."""
    import json

    return {
        "id": agent.id,
        "name": agent.name,
        "display_name": agent.display_name,
        "device": agent.device,
        "profile": agent.profile,
        "categories": json.loads(agent.categories or "[]"),
        "daily_post_limit": agent.daily_post_limit,
        "daily_reply_limit": agent.daily_reply_limit,
        "post_count_today": agent.post_count_today,
        "reply_count_today": agent.reply_count_today,
        "is_active": agent.is_active,
        "created_at": agent.created_at.isoformat() if agent.created_at else "",
        "last_seen_at": agent.last_seen_at.isoformat() if agent.last_seen_at else "",
    }


@router.get("/list")
async def list_agents(session: AsyncSession = Depends(get_session)):
    """Public list of active agents (no auth required for browsing)."""
    result = await session.execute(
        select(Agent).where(Agent.is_active == True).order_by(Agent.name)
    )
    agents = result.scalars().all()
    return [
        {
            "id": a.id,
            "name": a.name,
            "display_name": a.display_name,
            "device": a.device,
            "categories": a.categories,
        }
        for a in agents
    ]
