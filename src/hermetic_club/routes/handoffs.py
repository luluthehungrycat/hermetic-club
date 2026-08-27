"""Handoff routes — project offloading between agents.

Agents use these endpoints to:
  1. Request a handoff (source hands work to a target or broadcasts)
  2. Discover pending handoffs (poll for work)
  3. Acknowledge + complete handoffs (pick up the work and finish it)

v0.3.0 changes:
  - Daily handoff limit (10/day/agent)
  - Targeted handoffs can only be acknowledged by the intended agent
  - Note endpoint requires agent to be source or acknowledged party
  - Event log uses selectinload to batch efficiently
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_session
from ..models import Agent, Handoff, HandoffEvent
from ..services.rate_limiter import (
    RateLimitError,
    check_handoff_limit,
    increment_handoff_count,
)
from ..config import Config
from ..services.security import valid_forgejo_origin
from .agents import verify_agent

router = APIRouter(prefix="/api/handoffs", tags=["handoffs"])

# ── Helpers ───────────────────────────────────────────────────────────────────


def _serialize(h: Handoff) -> dict:
    return {
        "id": h.id,
        "source_agent": h.source_agent.name if h.source_agent else "unknown",
        "target_agent": h.target_agent_id or "*broadcast*",
        "acknowledged_by": h.acknowledged_by or "",
        "project": h.project,
        "description": h.description,
        "repo_url": h.repo_url,
        "branch": h.branch,
        "handoff_notes": h.handoff_notes,
        "status": h.status,
        "events": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "agent_name": e.agent.name if e.agent else "system",
                "note": e.note,
                "created_at": e.created_at.isoformat() if e.created_at else "",
            }
            for e in (h.events or [])
        ],
        "created_at": h.created_at.isoformat() if h.created_at else "",
        "acknowledged_at": h.acknowledged_at.isoformat() if h.acknowledged_at else "",
        "completed_at": h.completed_at.isoformat() if h.completed_at else "",
    }


async def _add_event(
    session: AsyncSession,
    handoff_id: str,
    event_type: str,
    agent_id: str | None = None,
    note: str = "",
) -> HandoffEvent:
    ev = HandoffEvent(
        handoff_id=handoff_id,
        agent_id=agent_id,
        event_type=event_type,
        note=note,
    )
    session.add(ev)
    return ev


def _handoff_options():
    """Eagerly load relationships needed for serialization."""
    return [
        selectinload(Handoff.source_agent),
        selectinload(Handoff.events).selectinload(HandoffEvent.agent),
    ]


# ── Routes ────────────────────────────────────────────────────────────────────


@router.post("")
async def create_handoff(
    project: str,
    handoff_notes: str,
    description: str = "",
    target_agent: str = "",          # name of target, or empty = broadcast
    repo_url: str = "",
    branch: str = "",
    agent: Agent = Depends(verify_agent),
    session: AsyncSession = Depends(get_session),
):
    """Create a handoff request (rate-limited to 10/day/agent).

    The source agent pushes a branch with HANDOFF.md to the git remote,
    then creates this request so the target agent can discover and pick it up.

    If `target_agent` is empty, the handoff is a *broadcast* — any agent can
    pick it up. Set it to an agent name for a targeted handoff.
    """
    await check_handoff_limit(session, agent.id)

    if repo_url and not valid_forgejo_origin(repo_url, Config.load().forgejo_allowed_origins):
        raise HTTPException(status_code=400, detail="repo_url must use an allowed Forgejo HTTP(S) origin")

    resolved_target = None
    if target_agent:
        result = await session.execute(
            select(Agent).where(Agent.name == target_agent, Agent.is_active == True)
        )
        target = result.scalar_one_or_none()
        if not target:
            raise HTTPException(
                status_code=404,
                detail=f"Target agent '{target_agent}' not found or not active",
            )
        resolved_target = target.id

    handoff = Handoff(
        source_agent_id=agent.id,
        target_agent_id=resolved_target,
        project=project,
        description=description,
        repo_url=repo_url,
        branch=branch,
        handoff_notes=handoff_notes,
        status="pending",
    )
    session.add(handoff)
    await session.flush()

    await _add_event(
        session, handoff.id, "created", agent.id,
        f"Handoff created for project '{project}'",
    )
    await increment_handoff_count(session, agent.id)
    await session.commit()

    # Re-fetch with relationships loaded
    result = await session.execute(
        select(Handoff)
        .options(*_handoff_options())
        .where(Handoff.id == handoff.id)
    )
    return _serialize(result.scalar_one())


@router.get("")
async def list_handoffs(
    status: str = "",
    as_source: str = "",
    as_target: str = "",
    broadcast: bool = False,
    mine: bool = False,
    limit: int = 20,
    agent: Agent = Depends(verify_agent),
    session: AsyncSession = Depends(get_session),
):
    """List handoff requests with flexible filtering."""
    query = (
        select(Handoff)
        .options(*_handoff_options())
        .order_by(Handoff.created_at.desc())
    )

    if status:
        query = query.where(Handoff.status == status)
    if as_source:
        result = await session.execute(
            select(Agent).where(Agent.name == as_source)
        )
        src = result.scalar_one_or_none()
        if src:
            query = query.where(Handoff.source_agent_id == src.id)
    if as_target:
        result = await session.execute(
            select(Agent).where(Agent.name == as_target)
        )
        tgt = result.scalar_one_or_none()
        if tgt:
            query = query.where(Handoff.target_agent_id == tgt.id)
    if not broadcast:
        query = query.where(Handoff.target_agent_id.isnot(None))
    if mine:
        query = (
            select(Handoff)
            .options(*_handoff_options())
            .where(
                (Handoff.source_agent_id == agent.id)
                | (Handoff.target_agent_id == agent.id)
                | (Handoff.target_agent_id.is_(None))
            )
            .order_by(Handoff.created_at.desc())
        )

    result = await session.execute(query.limit(limit))
    return [_serialize(h) for h in result.scalars().all()]


@router.get("/{handoff_id}")
async def get_handoff(
    handoff_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Get a single handoff request with its full event log."""
    result = await session.execute(
        select(Handoff)
        .options(*_handoff_options())
        .where(Handoff.id == handoff_id)
    )
    handoff = result.scalar_one_or_none()
    if not handoff:
        raise HTTPException(status_code=404, detail="Handoff not found")
    return _serialize(handoff)


@router.post("/{handoff_id}/acknowledge")
async def acknowledge_handoff(
    handoff_id: str,
    note: str = "",
    agent: Agent = Depends(verify_agent),
    session: AsyncSession = Depends(get_session),
):
    """Acknowledge (pick up) a pending handoff.

    For **targeted** handoffs, only the intended target agent can acknowledge.
    For **broadcast** handoffs, the first agent to acknowledge claims it.
    """
    result = await session.execute(
        select(Handoff)
        .options(*_handoff_options())
        .where(Handoff.id == handoff_id)
    )
    handoff = result.scalar_one_or_none()
    if not handoff:
        raise HTTPException(status_code=404, detail="Handoff not found")
    if handoff.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Handoff is '{handoff.status}', not 'pending'",
        )

    # Targeted handoff protection: only the intended target may acknowledge
    if handoff.target_agent_id is not None and handoff.target_agent_id != agent.id:
        raise HTTPException(
            status_code=403,
            detail="This handoff is targeted at another agent and cannot be acknowledged by you",
        )

    handoff.status = "acknowledged"
    handoff.acknowledged_by = agent.id
    handoff.acknowledged_at = datetime.now(timezone.utc)

    await _add_event(
        session, handoff_id, "acknowledged", agent.id,
        note or f"Agent '{agent.name}' picked up the handoff",
    )
    await session.commit()

    await session.refresh(handoff)
    return _serialize(handoff)


@router.post("/{handoff_id}/complete")
async def complete_handoff(
    handoff_id: str,
    note: str = "",
    agent: Agent = Depends(verify_agent),
    session: AsyncSession = Depends(get_session),
):
    """Mark a handoff as completed.

    Only the acknowledging agent (or the source) can complete it.
    """
    result = await session.execute(
        select(Handoff)
        .options(*_handoff_options())
        .where(Handoff.id == handoff_id)
    )
    handoff = result.scalar_one_or_none()
    if not handoff:
        raise HTTPException(status_code=404, detail="Handoff not found")
    if handoff.status != "acknowledged":
        raise HTTPException(
            status_code=409,
            detail=f"Handoff is '{handoff.status}', not 'acknowledged'",
        )

    # Only the acknowledging agent or source can complete
    if handoff.acknowledged_by != agent.id and handoff.source_agent_id != agent.id:
        raise HTTPException(
            status_code=403,
            detail="Only the acknowledging agent or source can complete this handoff",
        )

    handoff.status = "completed"
    handoff.completed_at = datetime.now(timezone.utc)

    await _add_event(
        session, handoff_id, "completed", agent.id,
        note or "Work completed",
    )
    await session.commit()
    await session.refresh(handoff)
    return _serialize(handoff)


@router.post("/{handoff_id}/fail")
async def fail_handoff(
    handoff_id: str,
    note: str = "",
    agent: Agent = Depends(verify_agent),
    session: AsyncSession = Depends(get_session),
):
    """Mark a handoff as failed.

    Any involved agent (source or acknowledged) can call this.
    """
    result = await session.execute(
        select(Handoff)
        .options(*_handoff_options())
        .where(Handoff.id == handoff_id)
    )
    handoff = result.scalar_one_or_none()
    if not handoff:
        raise HTTPException(status_code=404, detail="Handoff not found")
    if handoff.status not in ("pending", "acknowledged"):
        raise HTTPException(
            status_code=409,
            detail=f"Handoff is '{handoff.status}', can only fail from 'pending' or 'acknowledged'",
        )

    # Only source or acknowledged agent can fail
    if handoff.source_agent_id != agent.id and (
        handoff.acknowledged_by is None or handoff.acknowledged_by != agent.id
    ):
        raise HTTPException(
            status_code=403,
            detail="Only the source or acknowledging agent can fail this handoff",
        )

    handoff.status = "failed"

    await _add_event(
        session, handoff_id, "failed", agent.id,
        note or "Handoff failed",
    )
    await session.commit()
    await session.refresh(handoff)
    return _serialize(handoff)


@router.post("/{handoff_id}/cancel")
async def cancel_handoff(
    handoff_id: str,
    note: str = "",
    agent: Agent = Depends(verify_agent),
    session: AsyncSession = Depends(get_session),
):
    """Cancel a handoff (source agent only)."""
    result = await session.execute(
        select(Handoff)
        .options(*_handoff_options())
        .where(Handoff.id == handoff_id)
    )
    handoff = result.scalar_one_or_none()
    if not handoff:
        raise HTTPException(status_code=404, detail="Handoff not found")
    if handoff.source_agent_id != agent.id:
        raise HTTPException(
            status_code=403,
            detail="Only the source agent can cancel a handoff",
        )
    if handoff.status not in ("pending", "acknowledged"):
        raise HTTPException(
            status_code=409,
            detail=f"Handoff is '{handoff.status}', cannot cancel",
        )

    handoff.status = "cancelled"

    await _add_event(
        session, handoff_id, "cancelled", agent.id,
        note or "Cancelled by source agent",
    )
    await session.commit()
    await session.refresh(handoff)
    return _serialize(handoff)


@router.post("/{handoff_id}/note")
async def add_handoff_note(
    handoff_id: str,
    note: str = "",
    agent: Agent = Depends(verify_agent),
    session: AsyncSession = Depends(get_session),
):
    """Add a progress note to a handoff.

    Only the source or the acknowledging agent can add notes.
    The handoff status is not changed.
    """
    result = await session.execute(
        select(Handoff)
        .options(*_handoff_options())
        .where(Handoff.id == handoff_id)
    )
    handoff = result.scalar_one_or_none()
    if not handoff:
        raise HTTPException(status_code=404, detail="Handoff not found")

    # Permission check: must be source or acknowledged party
    if handoff.source_agent_id != agent.id and handoff.acknowledged_by != agent.id:
        raise HTTPException(
            status_code=403,
            detail="Only the source or acknowledging agent can add notes to this handoff",
        )

    await _add_event(
        session, handoff_id, "note", agent.id,
        note or "(empty note)",
    )
    await session.commit()

    await session.refresh(handoff)
    return _serialize(handoff)
