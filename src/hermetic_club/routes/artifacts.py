"""Agent-facing curated artifact access."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..models import Agent, ArtifactRecord
from .agents import verify_agent

router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])


@router.get("/{artifact_id}")
async def get_artifact(
    artifact_id: str,
    agent: Agent = Depends(verify_agent),
    session: AsyncSession = Depends(get_session),
):
    artifact = await session.get(ArtifactRecord, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if not artifact.activated:
        raise HTTPException(status_code=404, detail="Artifact is not active")
    allowed = json.loads(artifact.allowed_agent_ids or "[]")
    if agent.id not in allowed:
        raise HTTPException(status_code=403, detail="Agent is not authorized for this artifact")
    return {
        "id": artifact.id,
        "project": artifact.project,
        "artifact_type": artifact.artifact_type,
        "manifest": json.loads(artifact.manifest),
        "source_repository": artifact.source_repository,
        "source_revision": artifact.source_revision,
        "activated": artifact.activated,
        "approved_by_identity": artifact.approved_by_identity,
        "approved_at": artifact.approved_at.isoformat() if artifact.approved_at else "",
    }
