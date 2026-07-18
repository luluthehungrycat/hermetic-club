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


def fire_post_webhooks(
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

    Uses synchronous httpx to avoid event-loop issues. Runs in a background
    thread (called via asyncio.ensure_future / run_in_executor).

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

    import sys as _sys
    _sys.stderr.write(f"[WEBHOOK] Dispatching post {post_id} to {len(webhook_targets)} targets\n")
    _sys.stderr.flush()
    log.info("Dispatching webhooks for post %s to %d target(s)", post_id, len(webhook_targets))

    for target in webhook_targets:
        url = target.get("url", "").strip()
        if not url:
            _sys.stderr.write(f"  [WEBHOOK] Skipping {target.get('agent_name')} — empty URL\n")
            _sys.stderr.flush()
            continue

        target_roles_list = target.get("roles", [])
        if not _roles_match(target_roles, target_roles_list):
            _sys.stderr.write(f"  [WEBHOOK] Skipping {target.get('agent_name')} — role mismatch\n")
            _sys.stderr.flush()
            continue

        _sys.stderr.write(f"  [WEBHOOK] Firing to {target.get('agent_name')} at {url}\n")
        _sys.stderr.flush()
        try:
            with httpx.Client(timeout=httpx.Timeout(5.0, connect=2.0)) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
            _sys.stderr.write(f"  ✓ {url} — {resp.status_code}\n")
            _sys.stderr.flush()
        except httpx.TimeoutException:
            _sys.stderr.write(f"  ✗ {url} — timeout\n")
            _sys.stderr.flush()
        except httpx.HTTPStatusError as e:
            _sys.stderr.write(f"  ✗ {url} — HTTP {e.response.status_code}\n")
            _sys.stderr.flush()
        except Exception as e:
            _sys.stderr.write(f"  ✗ {url} — {type(e).__name__}: {e}\n")
            _sys.stderr.flush()
