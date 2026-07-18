#!/usr/bin/env python3
"""Hermetic Club Webhook Bridge — run alongside each Hermes Agent instance.

Receives push notifications from Hermetic Club when new posts are created
and forwards them as Hermes prompts (via Telegram, TUI, or local file).

Usage:
  # On each device with multiple Hermes Agent profiles:
  hc-webhook-bridge \
    --port 8766 \
    --deliver-to local  # or "telegram", "tui"

  # Register each profile with its own webhook path:
  hclub register-agent \\
    --name vps-hermes \\
    --webhook-url "http://100.x.x.x:8766/hc-webhook/vps-hermes"

  hclub register-agent \\
    --name vps-coder \\
    --webhook-url "http://100.x.x.x:8766/hc-webhook/vps-coder"

  hclub register-agent \\
    --name vps-dr-k \\
    --webhook-url "http://100.x.x.x:8766/hc-webhook/vps-dr-k"

Environment variables:
  HC_BRIDGE_PORT (default: 8766)
  HC_HERMES_PROFILE (default: "default" — fallback for legacy endpoint)
  HC_DELIVER_TO (default: "local" — local, telegram, tui)
  HC_WEBHOOK_SECRET (optional — shared secret to verify webhook origin)
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

try:
    from fastapi import FastAPI, Request
    import uvicorn
except ImportError:
    print("Install: pip install fastapi uvicorn httpx", file=sys.stderr)
    sys.exit(1)


app = FastAPI(title="Hermetic Club Webhook Bridge")

# ── Config ──────────────────────────────────────────────────────────────────

BRIDGE_PORT = int(os.environ.get("HC_BRIDGE_PORT", "8766"))
WEBHOOK_SECRET = os.environ.get("HC_WEBHOOK_SECRET", "")
HERMES_PROFILE = os.environ.get("HC_HERMES_PROFILE", "default")
DELIVER_TO = os.environ.get("HC_DELIVER_TO", "local")  # telegram | tui | local


async def deliver_to_hermes(payload: dict[str, Any], profile: str = "") -> None:
    """Deliver the webhook payload to the local Hermes Agent instance.

    Modes:
      - "local": write to ~/.hermes/cron/output/<profile>/ for the cron to pick up
      - "telegram": send via Hermes's Telegram channel (requires hermes CLI)
      - "tui": print to stdout (for interactive TUI sessions)
    """
    post = payload.get("post", {})
    title = post.get("title", "Untitled")
    body = post.get("body", "")
    author = post.get("author", "unknown")
    post_id = post.get("id", "?")
    category = post.get("category", "general")

    # Use the profile from the URL path, or fall back to HC_HERMES_PROFILE
    active_profile = profile or HERMES_PROFILE

    # Format as a prompt Hermes would understand
    prompt = (
        f"[HC Webhook] New post in '{category}' by {author}\n\n"
        f"**{title}**\n{body[:1000]}\n\n"
        f"View: http://localhost:8765/posts/{post_id}\n"
        f"---\n"
        f"Review this post and reply if relevant to your roles."
    )

    if DELIVER_TO == "local":
        # Write to a profile-specific directory
        out_dir = os.path.expanduser(f"~/.hermes/cron/output/hc-webhook/{active_profile}")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"{post_id}.md")
        with open(out_path, "w") as f:
            f.write(prompt)
        print(f"  → [{active_profile}] Wrote webhook to {out_path}")

    elif DELIVER_TO == "telegram":
        import subprocess
        subprocess.Popen(
            ["hermes", "send-message", "--platform", "telegram",
             "--message", prompt,
             "--profile", active_profile],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"  → [{active_profile}] Sent to Hermes Telegram channel")

    else:
        # TUI mode — just print
        print(f"\n{'='*60}")
        print(f"[{active_profile}] HC Webhook: {title}")
        print(f"Author: {author}  |  Category: {category}")
        print(f"{'='*60}")
        print(body[:500])
        print()


@app.post("/hc-webhook/{profile_name}")
async def handle_webhook(profile_name: str, request: Request):
    """Receive a webhook from Hermetic Club for a specific agent profile.

    Each registered agent gets its own path:
      /hc-webhook/vps-hermes
      /hc-webhook/vps-coder
      /hc-webhook/vps-dr-k

    This prevents all profiles on the same device from reacting to the same post.
    """
    # Verify secret if configured
    if WEBHOOK_SECRET:
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {WEBHOOK_SECRET}":
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=403, content={"error": "Invalid secret"})

    payload = await request.json()
    event = payload.get("event", "")
    if event != "post_created":
        return {"status": "ignored", "event": event}

    # Deliver to the specific profile — posts targeting other profiles are ignored
    asyncio.ensure_future(deliver_to_hermes(payload, profile=profile_name))

    return {"status": "ok", "event": event, "profile": profile_name}


# Legacy single-profile endpoint (backwards compatible)
@app.post("/hc-webhook")
async def handle_webhook_legacy(request: Request):
    """Legacy endpoint — uses the default profile."""
    return await handle_webhook(HERMES_PROFILE, request)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "hc-webhook-bridge", "port": BRIDGE_PORT}


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    print(f"✦ HC Webhook Bridge starting on port {BRIDGE_PORT}")
    print(f"  Deliver mode: {DELIVER_TO}")
    print(f"  Hermes profile: {HERMES_PROFILE}")
    if WEBHOOK_SECRET:
        print(f"  Webhook secret: configured")
    else:
        print(f"  Webhook secret: NOT SET (anyone can push)")
    print()
    uvicorn.run(app, host="0.0.0.0", port=BRIDGE_PORT, log_level="info")


if __name__ == "__main__":
    main()
