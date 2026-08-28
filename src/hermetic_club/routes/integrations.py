"""Forgejo webhook integration."""
from __future__ import annotations

import json

from fastapi import APIRouter, Header, HTTPException, Request

from ..config import Config
from ..database import get_session
from ..models import RepositoryActivity
from ..services.security import forgejo_signature_valid, valid_forgejo_origin

router = APIRouter(prefix="/api/integrations/forgejo", tags=["forgejo"])


@router.post("/webhook")
async def forgejo_webhook(
    request: Request,
    x_forgejo_signature: str = Header(""),
    x_forgejo_event: str = Header("push"),
):
    body = await request.body()
    cfg = Config.load()
    if not forgejo_signature_valid(body, x_forgejo_signature, cfg.forgejo_webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid Forgejo webhook signature")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Webhook body must be JSON")
    repository = payload.get("repository", {}).get("html_url", "")
    if not valid_forgejo_origin(repository, cfg.forgejo_allowed_origins):
        raise HTTPException(status_code=400, detail="Webhook repository is not allowed")
    async for session in get_session():
        activity = RepositoryActivity(
            repository=repository,
            event_type=x_forgejo_event,
            reference=str(payload.get("ref", payload.get("number", ""))),
            payload_summary=json.dumps({
                "repository": repository,
                "sender": payload.get("sender", {}).get("login", ""),
                "action": payload.get("action", ""),
                "ref": payload.get("ref", ""),
                "number": payload.get("number", ""),
            }),
        )
        session.add(activity)
        await session.commit()
        return {"accepted": True, "activity_id": activity.id, "event": x_forgejo_event}
    raise HTTPException(status_code=503, detail="Database unavailable")
