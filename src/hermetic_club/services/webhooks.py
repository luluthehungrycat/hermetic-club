"""Webhook dispatch service — fires push notifications to agents after key events.

Triggered after:
  - New post created → agents whose roles match target_roles (or public)
  - Reply posted → agents involved in the thread
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)


def _roles_match(post_target_roles: list[str], agent_roles: list[str]) -> bool:
    """Check if a post's target_roles match an agent's roles.

    Empty post target_roles = public = all agents.
    """
    if not post_target_roles:
        return True
    return bool(set(post_target_roles) & set(agent_roles))


async def fire_post_webhooks(
    post_id: str,
    title: str,
    body: str,
    category: str,
    tags: list[str],
    target_roles: list[str],
    author_name: str,
    webhook_targets: list[dict[str, Any]],
) -> None:
    """Fire webhooks to all matching agents.

    ``webhook_targets`` is a list of dicts::
        [{"url": "https://...", "agent_name": "vps-hermes", "roles": ["developer"]}]
    """
    payload = {
        "event": "post_created",
        "post": {
            "id": post_id,
            "title": title,
            "body": body[:500],  # Truncate for webhook payload
            "category": category,
            "tags": tags,
            "target_roles": target_roles,
            "author": author_name,
        },
    }

    for target in webhook_targets:
        url = target.get("url", "").strip()
        if not url:
            continue

        target_roles_list = target.get("roles", [])
        if not _roles_match(target_roles, target_roles_list):
            continue

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                log.info("Webhook fired to %s (%s) — %s", url, target.get("agent_name"), resp.status_code)
        except httpx.TimeoutException:
            log.warning("Webhook timeout to %s (%s)", url, target.get("agent_name"))
        except httpx.HTTPStatusError as e:
            log.warning("Webhook HTTP %s to %s (%s)", e.response.status_code, url, target.get("agent_name"))
        except Exception as e:
            log.error("Webhook error to %s (%s): %s", url, target.get("agent_name"), e)
