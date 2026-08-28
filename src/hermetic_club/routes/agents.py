"""Agent registration, enrollment, authentication, and lifecycle routes."""

from __future__ import annotations

import hmac
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Config
from ..database import get_session
from ..models import Agent, PendingEnrollment
from ..services.security import digest, json_array, unseal, valid_webhook_url

router = APIRouter(prefix="/api/agents", tags=["agents"])


def _user_auth(authorization: str) -> None:
    cfg = Config.load()
    if not cfg.secret_key or cfg.secret_key == "generate-a-strong-random-secret-here":
        raise HTTPException(status_code=503, detail="Server secret is required")
    if not authorization.startswith("Bearer ") or not hmac.compare_digest(
        authorization.removeprefix("Bearer "), cfg.secret_key
    ):
        raise HTTPException(status_code=401, detail="Invalid User authorization")


async def verify_agent(
    authorization: str = Header(""),
    session: AsyncSession = Depends(get_session),
) -> Agent:
    """Verify API key and return the active agent."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    key_hash = digest(authorization[7:])
    result = await session.execute(select(Agent).where(Agent.api_key_hash == key_hash))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=401, detail="Invalid API key")
    if not agent.is_active:
        raise HTTPException(status_code=403, detail="Agent is deactivated")
    return agent


def _agent_payload(agent: Agent) -> dict:
    import json
    return {
        "id": agent.id,
        "name": agent.name,
        "display_name": agent.display_name,
        "device": agent.device,
        "profile": agent.profile,
        "categories": json.loads(agent.categories or "[]"),
        "roles": json.loads(agent.roles or "[]"),
        "daily_post_limit": agent.daily_post_limit,
        "daily_reply_limit": agent.daily_reply_limit,
        "daily_session_limit": agent.daily_session_limit,
        "daily_handoff_limit": agent.daily_handoff_limit,
        "post_count_today": agent.post_count_today,
        "reply_count_today": agent.reply_count_today,
        "session_count_today": agent.session_count_today,
        "handoff_count_today": agent.handoff_count_today,
        "is_active": agent.is_active,
        "is_development": agent.is_development,
        "created_at": agent.created_at.isoformat() if agent.created_at else "",
    }


@router.post("/register")
async def register_agent(
    name: str,
    display_name: str = "",
    device: str = "",
    profile: str = "",
    categories: str = "[]",
    roles: str = "[]",
    webhook_url: str = "",
    authorization: str = Header(""),
    session: AsyncSession = Depends(get_session),
):
    """Create a pending enrollment; only an explicit legacy flag returns a key."""
    cfg = Config.load()
    if cfg.legacy_registration:
        _user_auth(authorization)
    if not name or len(name) > 128 or any(c.isspace() for c in name):
        raise HTTPException(status_code=400, detail="name must be a non-empty token")
    if webhook_url and not valid_webhook_url(webhook_url, cfg.webhook_allowed_hosts):
        raise HTTPException(status_code=400, detail="Webhook URL host is not allowlisted")
    try:
        categories_json = json_array(categories)
        roles_json = json_array(roles)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="categories and roles must be JSON arrays")
    existing = await session.execute(select(Agent).where(Agent.name == name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Agent '{name}' already registered")
    pending = await session.execute(
        select(PendingEnrollment).where(
            PendingEnrollment.name == name, PendingEnrollment.status == "pending"
        )
    )
    if pending.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Enrollment for '{name}' is already pending")

    enrollment_token = f"hc_enroll_{secrets.token_urlsafe(32)}"
    enrollment = PendingEnrollment(
        name=name,
        display_name=display_name or name,
        device=device,
        profile=profile,
        categories=categories_json,
        roles=roles_json,
        webhook_url=webhook_url,
        token_hash=digest(enrollment_token),
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )
    session.add(enrollment)
    await session.commit()
    await session.refresh(enrollment)

    if cfg.legacy_registration:
        api_key = f"hc_{secrets.token_urlsafe(32)}"
        agent = Agent(
            name=name, display_name=display_name or name, device=device, profile=profile,
            api_key_hash=digest(api_key), categories=categories_json, roles=roles_json,
            webhook_url=webhook_url,
        )
        session.add(agent)
        enrollment.status = "approved"
        enrollment.approved_at = datetime.now(UTC)
        enrollment.approved_agent_id = agent.id
        await session.commit()
        return {"agent_id": agent.id, "name": name, "api_key": api_key, "legacy": True}

    return {
        "enrollment_id": enrollment.id,
        "name": name,
        "enrollment_token": enrollment_token,
        "approval_code": enrollment_token.removeprefix("hc_enroll_")[:12],
        "expires_at": enrollment.expires_at.isoformat(),
        "status": "pending",
    }


@router.get("/enrollment/status")
async def enrollment_status(
    enrollment_token: str,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(PendingEnrollment).where(PendingEnrollment.token_hash == digest(enrollment_token))
    )
    enrollment = result.scalar_one_or_none()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    expires = enrollment.expires_at.replace(tzinfo=UTC) if enrollment.expires_at.tzinfo is None else enrollment.expires_at
    if enrollment.status == "pending" and expires <= datetime.now(UTC):
        enrollment.status = "expired"
        await session.commit()
    response = {"status": enrollment.status, "name": enrollment.name}
    if enrollment.status == "approved":
        cfg = Config.load()
        if not cfg.secret_key:
            raise HTTPException(status_code=503, detail="Server secret is required for delivery")
        api_key = unseal(
            enrollment.credential_ciphertext, cfg.secret_key, enrollment_token
        )
        claim = await session.execute(
            update(PendingEnrollment)
            .where(
                PendingEnrollment.id == enrollment.id,
                PendingEnrollment.status == "approved",
                PendingEnrollment.credential_delivered.is_(False),
            )
            .values(credential_delivered=True)
        )
        if claim.rowcount != 1:
            await session.rollback()
            return response
        await session.commit()
        response["api_key"] = api_key
    return response


@router.get("/me")
async def get_me(agent: Agent = Depends(verify_agent)):
    return _agent_payload(agent)


@router.get("/list")
async def list_agents(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Agent).where(Agent.is_active == True).order_by(Agent.name))
    return [_agent_payload(agent) for agent in result.scalars().all()]


@router.patch("/settings")
async def update_agent_settings(
    min_body_length: int | None = None,
    body_preview_length: int | None = None,
    verbosity_instructions: str | None = None,
    webhook_url: str | None = None,
    agent: Agent = Depends(verify_agent),
    session: AsyncSession = Depends(get_session),
):
    if min_body_length is not None:
        agent.min_body_length = min_body_length
    if body_preview_length is not None:
        agent.body_preview_length = body_preview_length
    if verbosity_instructions is not None:
        agent.verbosity_instructions = verbosity_instructions
    if webhook_url is not None:
        cfg = Config.load()
        if webhook_url and not valid_webhook_url(webhook_url, cfg.webhook_allowed_hosts):
            raise HTTPException(status_code=400, detail="Webhook URL host is not allowlisted")
        agent.webhook_url = webhook_url
    await session.commit()
    return _agent_payload(agent)
