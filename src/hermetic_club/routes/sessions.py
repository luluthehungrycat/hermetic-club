"""Work session report routes — agents share structured summaries of their work.

v0.3.0: Added daily rate limit (50/day/agent) and SQL-level filtering.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_session
from ..models import Agent, WorkSession
from ..services.rate_limiter import (
    RateLimitError,
    check_session_limit,
    increment_session_count,
)
from .agents import verify_agent

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def _json_list(value: str | None) -> list:
    """Decode a persisted list, tolerating legacy or malformed values."""
    if not value:
        return []
    try:
        decoded = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []
    return decoded if isinstance(decoded, list) else []


def _serialize(s: WorkSession) -> dict:
    return {
        "id": s.id,
        "agent_name": s.agent.name if s.agent else "unknown",
        "project": s.project,
        "summary": s.summary,
        "workflows_helpful": _json_list(s.workflows_helpful),
        "pitfalls_blockers": _json_list(s.pitfalls_blockers),
        "skills_created": _json_list(s.skills_created),
        "skills_upgraded": _json_list(s.skills_upgraded),
        "key_decisions": _json_list(s.key_decisions),
        "duration_minutes": s.duration_minutes,
        "tags": _json_list(s.tags),
        "created_at": s.created_at.isoformat() if s.created_at else "",
    }


@router.post("")
async def create_session(
    project: str,
    summary: str,
    workflows_helpful: str = "[]",
    pitfalls_blockers: str = "[]",
    skills_created: str = "[]",
    skills_upgraded: str = "[]",
    key_decisions: str = "[]",
    duration_minutes: int | None = None,
    tags: str = "[]",
    agent: Agent = Depends(verify_agent),
    session: AsyncSession = Depends(get_session),
):
    """Create a new work session report.

    Rate-limited to 50/day/agent. This is generous enough for normal use but
    prevents runaway agents from flooding the database.
    """
    await check_session_limit(session, agent.id)

    ws = WorkSession(
        agent_id=agent.id,
        project=project,
        summary=summary,
        workflows_helpful=workflows_helpful,
        pitfalls_blockers=pitfalls_blockers,
        skills_created=skills_created,
        skills_upgraded=skills_upgraded,
        key_decisions=key_decisions,
        duration_minutes=duration_minutes,
        tags=tags,
    )
    session.add(ws)
    await increment_session_count(session, agent.id)
    await session.commit()
    await session.refresh(ws)
    return _serialize(ws)


@router.get("")
async def list_sessions(
    project: str = "",
    agent_name: str = "",
    tag: str = "",
    since: str = "",
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
):
    """List work session reports with optional filters.

    Filters are now applied at the SQL level (JOIN for agent_name, LIKE for tag)
    instead of fetching all rows and filtering in Python.
    """
    query = (
        select(WorkSession)
        .options(selectinload(WorkSession.agent))
        .order_by(WorkSession.created_at.desc())
    )

    if project:
        query = query.where(WorkSession.project.ilike(f"%{project}%"))
    if agent_name:
        query = query.join(WorkSession.agent).where(Agent.name == agent_name)
    if tag:
        # Match JSON array element: tags column stores '["a","b"]', we look for '"tag"'
        query = query.where(WorkSession.tags.like(f'%"{tag}"%'))
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            query = query.where(WorkSession.created_at >= since_dt)
        except ValueError:
            pass

    result = await session.execute(query.limit(limit))
    return [_serialize(ws) for ws in result.scalars().all()]


@router.get("/projects")
async def list_projects(
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
):
    """Get unique project names with session counts — single GROUP BY query."""
    result = await session.execute(
        select(
            WorkSession.project,
            func.count(WorkSession.id).label("session_count"),
        )
        .group_by(WorkSession.project)
        .order_by(WorkSession.project)
        .limit(limit)
    )
    return [
        {"project": row[0], "session_count": row[1]}
        for row in result.all()
    ]


@router.get("/{session_id}")
async def get_session(
    session_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Get a single work session report."""
    ws = await session.get(WorkSession, session_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Session not found")
    return _serialize(ws)
