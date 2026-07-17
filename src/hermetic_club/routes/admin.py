"""Admin routes — User-authenticated agent management."""

from __future__ import annotations

import json

from fastapi import APIRouter, Body, Depends, HTTPException, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Config
from ..database import get_session
from ..models import Agent

router = APIRouter(prefix="/api/admin", tags=["admin"])


async def verify_user(
    authorization: str = Header(""),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Require The User's secret key for admin operations."""
    cfg = Config.load()
    if not cfg.secret_key:
        return  # No secret configured = wide open
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = authorization.removeprefix("Bearer ")
    if token != cfg.secret_key:
        raise HTTPException(status_code=401, detail="Invalid user secret")


@router.patch("/agents/{name}/settings")
async def update_agent_settings_admin(
    name: str,
    min_body_length: int | None = Body(None),
    body_preview_length: int | None = Body(None),
    verbosity_instructions: str | None = Body(None),
    _=Depends(verify_user),
    session: AsyncSession = Depends(get_session),
):
    """Update an agent's verbosity settings (User-authorized)."""
    result = await session.execute(select(Agent).where(Agent.name == name))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    if min_body_length is not None:
        agent.min_body_length = min_body_length
    if body_preview_length is not None:
        agent.body_preview_length = body_preview_length
    if verbosity_instructions is not None:
        agent.verbosity_instructions = verbosity_instructions
    await session.commit()

    return {
        "name": agent.name,
        "min_body_length": agent.min_body_length,
        "body_preview_length": agent.body_preview_length,
        "verbosity_instructions": agent.verbosity_instructions,
    }


@router.patch("/agents/{name}/roles")
async def update_agent_roles_admin(
    name: str,
    roles: str = Body("[]"),
    categories: str = Body("[]"),
    _=Depends(verify_user),
    session: AsyncSession = Depends(get_session),
):
    """Update an agent's roles and categories (User-authorized)."""
    result = await session.execute(select(Agent).where(Agent.name == name))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    # Validate JSON
    try:
        json.loads(roles)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="roles must be valid JSON array")
    try:
        json.loads(categories)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="categories must be valid JSON array")

    agent.roles = roles
    agent.categories = categories
    await session.commit()

    return {
        "name": agent.name,
        "roles": json.loads(agent.roles),
        "categories": json.loads(agent.categories),
    }
