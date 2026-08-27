"""Admin routes — User-authenticated agent management."""
from __future__ import annotations

import hmac
import json
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Config
from ..database import get_session
from ..models import Agent, ArtifactRecord, PendingEnrollment
from ..services.security import digest, seal, valid_forgejo_origin

router = APIRouter(prefix="/api/admin", tags=["admin"])


async def verify_user(authorization: str = Header("")) -> None:
    cfg = Config.load()
    if not cfg.secret_key or cfg.secret_key == "generate-a-strong-random-secret-here":
        raise HTTPException(status_code=503, detail="Server secret is required")
    if not authorization.startswith("Bearer ") or not hmac.compare_digest(
        authorization.removeprefix("Bearer "), cfg.secret_key
    ):
        raise HTTPException(status_code=401, detail="Invalid user secret")


@router.patch("/agents/{name}/settings")
async def update_agent_settings_admin(
    name: str, min_body_length: int | None = Body(None),
    body_preview_length: int | None = Body(None), verbosity_instructions: str | None = Body(None),
    _=Depends(verify_user), session: AsyncSession = Depends(get_session),
):
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
    return {"name": agent.name, "min_body_length": agent.min_body_length,
            "body_preview_length": agent.body_preview_length,
            "verbosity_instructions": agent.verbosity_instructions}


@router.patch("/agents/{name}/roles")
async def update_agent_roles_admin(
    name: str, roles: str = Body("[]"), categories: str = Body("[]"),
    _=Depends(verify_user), session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Agent).where(Agent.name == name))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    try:
        parsed_roles = json.loads(roles)
        parsed_categories = json.loads(categories)
        if not isinstance(parsed_roles, list) or not isinstance(parsed_categories, list):
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="roles and categories must be JSON arrays")
    agent.roles = json.dumps(parsed_roles)
    agent.categories = json.dumps(parsed_categories)
    await session.commit()
    return {"name": agent.name, "roles": parsed_roles, "categories": parsed_categories}


@router.get("/enrollments")
async def list_pending_enrollments(_=Depends(verify_user), session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(PendingEnrollment).where(PendingEnrollment.status == "pending").order_by(PendingEnrollment.created_at))
    now = datetime.now(timezone.utc)
    rows = []
    for item in result.scalars().all():
        expires = item.expires_at.replace(tzinfo=timezone.utc) if item.expires_at.tzinfo is None else item.expires_at
        if expires <= now:
            item.status = "expired"
        rows.append({"id": item.id, "name": item.name, "display_name": item.display_name,
                     "device": item.device, "profile": item.profile,
                     "categories": json.loads(item.categories or "[]"), "roles": json.loads(item.roles or "[]"),
                     "expires_at": item.expires_at.isoformat(), "status": item.status})
    await session.commit()
    return rows


@router.post("/enrollments/{enrollment_id}/approve")
async def approve_enrollment(
    enrollment_id: str, enrollment_token: str = Body(..., embed=True),
    _=Depends(verify_user), session: AsyncSession = Depends(get_session),
):
    cfg = Config.load()
    if not cfg.secret_key:
        raise HTTPException(status_code=503, detail="Server secret is required")
    enrollment = await session.get(PendingEnrollment, enrollment_id)
    if not enrollment or not hmac.compare_digest(
        enrollment.token_hash, digest(enrollment_token)
    ):
        raise HTTPException(status_code=404, detail="Enrollment not found")
    claim = await session.execute(
        update(PendingEnrollment)
        .where(
            PendingEnrollment.id == enrollment_id,
            PendingEnrollment.status == "pending",
        )
        .values(status="approving")
    )
    if claim.rowcount != 1:
        raise HTTPException(status_code=409, detail="Enrollment is not pending")
    enrollment.status = "approving"
    expires = enrollment.expires_at.replace(tzinfo=timezone.utc) if enrollment.expires_at.tzinfo is None else enrollment.expires_at
    if expires <= datetime.now(timezone.utc):
        enrollment.status = "expired"
        await session.commit()
        raise HTTPException(status_code=409, detail="Enrollment has expired")
    duplicate = await session.execute(select(Agent).where(Agent.name == enrollment.name))
    if duplicate.scalar_one_or_none():
        enrollment.status = "rejected"
        enrollment.rejected_at = datetime.now(timezone.utc)
        await session.commit()
        raise HTTPException(status_code=409, detail="Agent name already exists")
    api_key = f"hc_{secrets.token_urlsafe(32)}"
    agent = Agent(name=enrollment.name, display_name=enrollment.display_name, device=enrollment.device,
                  profile=enrollment.profile, categories=enrollment.categories, roles=enrollment.roles,
                  webhook_url=enrollment.webhook_url, api_key_hash=digest(api_key))
    session.add(agent)
    await session.flush()
    enrollment.status = "approved"
    enrollment.approved_agent_id = agent.id
    enrollment.approved_at = datetime.now(timezone.utc)
    enrollment.credential_ciphertext = seal(api_key, cfg.secret_key, enrollment_token)
    await session.commit()
    return {"id": enrollment.id, "agent_id": agent.id, "name": agent.name, "status": "approved"}


@router.post("/enrollments/{enrollment_id}/reject")
async def reject_enrollment(enrollment_id: str, _=Depends(verify_user), session: AsyncSession = Depends(get_session)):
    claim = await session.execute(
        update(PendingEnrollment)
        .where(
            PendingEnrollment.id == enrollment_id,
            PendingEnrollment.status == "pending",
        )
        .values(status="rejected", rejected_at=datetime.now(timezone.utc))
    )
    if claim.rowcount != 1:
        raise HTTPException(status_code=409, detail="Enrollment is not pending")
    await session.commit()
    return {"id": enrollment_id, "status": "rejected"}


@router.post("/agents/{name}/revoke")
async def revoke_agent(name: str, _=Depends(verify_user), session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Agent).where(Agent.name == name))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    agent.is_active = False
    await session.commit()
    return {"name": name, "is_active": False}


@router.post("/agents/{name}/rotate-key")
async def rotate_agent_key(name: str, _=Depends(verify_user), session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Agent).where(Agent.name == name))
    agent = result.scalar_one_or_none()
    if not agent or not agent.is_active:
        raise HTTPException(status_code=404, detail="Active agent not found")
    api_key = f"hc_{secrets.token_urlsafe(32)}"
    agent.api_key_hash = digest(api_key)
    await session.commit()
    return {"name": name, "api_key": api_key, "message": "Save this key; it will not be shown again."}


@router.post("/artifacts")
async def record_artifact(
    project: str = Body(...), artifact_type: str = Body(...), manifest: dict = Body(...),
    source_repository: str = Body(""), source_revision: str = Body(""), allowed_agent_ids: list[str] = Body([]),
    _=Depends(verify_user), session: AsyncSession = Depends(get_session),
):
    cfg = Config.load()
    if source_repository and not valid_forgejo_origin(source_repository, cfg.forgejo_allowed_origins):
        raise HTTPException(status_code=400, detail="Repository is not an allowed Forgejo origin")
    item = ArtifactRecord(project=project, artifact_type=artifact_type, manifest=json.dumps(manifest),
                          source_repository=source_repository, source_revision=source_revision,
                          allowed_agent_ids=json.dumps(allowed_agent_ids))
    session.add(item)
    await session.commit()
    return {"id": item.id, "project": project, "status": "preview"}


@router.post("/artifacts/{artifact_id}/activate")
async def activate_artifact(artifact_id: str, _=Depends(verify_user), session: AsyncSession = Depends(get_session)):
    item = await session.get(ArtifactRecord, artifact_id)
    if not item:
        raise HTTPException(status_code=404, detail="Artifact record not found")
    item.approved_by_user = True
    item.approved_by_identity = "user"
    item.approved_at = datetime.now(timezone.utc)
    item.activated = True
    await session.commit()
    return {"id": item.id, "activated": True, "manifest": json.loads(item.manifest)}
