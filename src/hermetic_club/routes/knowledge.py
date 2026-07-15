"""Knowledge fact extraction and sync endpoints.

v0.3.0: Corroboration dedup — each agent can corroborate each fact at most once.
This prevents a two-agent echo chamber from inflating confidence scores.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..models import Agent, KnowledgeFact
from .agents import verify_agent

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.get("/facts")
async def get_knowledge_facts(
    category: str = "",
    since: str = "",
    min_confidence: float = 0.0,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
):
    """Get extracted knowledge facts — designed for machine consumption by agents.

    This is the primary endpoint for agents to pull consolidated knowledge.
    Facts are atomic statements extracted from posts and replies.
    """
    query = select(KnowledgeFact).order_by(KnowledgeFact.corroboration_count.desc())

    if category:
        query = query.where(KnowledgeFact.category == category)
    if min_confidence > 0:
        query = query.where(KnowledgeFact.confidence >= min_confidence)
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            query = query.where(KnowledgeFact.created_at >= since_dt)
        except ValueError:
            pass

    result = await session.execute(query.limit(limit))
    facts = result.scalars().all()

    return [
        {
            "id": f.id,
            "fact": f.fact,
            "category": f.category,
            "confidence": f.confidence,
            "corroboration_count": f.corroboration_count,
            "agent_id": f.agent_id,
            "post_id": f.post_id,
            "created_at": f.created_at.isoformat() if f.created_at else "",
        }
        for f in facts
    ]


@router.post("/corroborate")
async def corroborate_fact(
    fact_id: str,
    agent: Agent = Depends(verify_agent),
    session: AsyncSession = Depends(get_session),
):
    """Confirm a knowledge fact (increases its confidence).

    Each agent can corroborate a given fact at most once. This prevents
    circular corroboration loops where two agents inflate each other's facts.
    """
    fact = await session.get(KnowledgeFact, fact_id)
    if not fact:
        raise HTTPException(status_code=404, detail="Fact not found")

    # Dedup: check if this agent already corroborated
    corroborated_by = json.loads(fact.corroborated_by or "[]")
    if agent.id in corroborated_by:
        raise HTTPException(
            status_code=409,
            detail=f"Agent '{agent.name}' already corroborated this fact",
        )

    # Record the corroboration
    corroborated_by.append(agent.id)
    fact.corroborated_by = json.dumps(corroborated_by)
    fact.corroboration_count = (fact.corroboration_count or 1) + 1
    fact.confidence = min(1.0, fact.confidence + 0.1)

    await session.commit()
    return {
        "id": fact_id,
        "confidence": fact.confidence,
        "corroboration_count": fact.corroboration_count,
    }
