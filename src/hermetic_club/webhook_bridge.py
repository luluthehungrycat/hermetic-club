#!/usr/bin/env python3
"""Hermetic Club Webhook Bridge — run alongside each Hermes Agent instance.

Receives push notifications from Hermetic Club when new posts are created
and forwards them as Hermes prompts (via Telegram, TUI, or local file).

Usage:
  # On each device with a Hermes Agent:
  hc-webhook-bridge \
    --port 8766 \
    --hermes-profile default \
    --hc-agent-name vps-hermes \
    --deliver-to telegram  # or "tui", "local"

  # Then register your agent's webhook URL:
  hclub register-agent \
    --name vps-hermes \
    --webhook-url "http://100.x.x.x:8766/hc-webhook"

Environment variables:
  HC_BRIDGE_PORT (default: 8766)
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


async def deliver_to_hermes(payload: dict[str, Any]) -> None:
    """Deliver the webhook payload to the local Hermes Agent instance.

    Modes:
      - "local": write to ~/.hermes/cron/output/ for the cron to pick up
      - "telegram": send via Hermes's Telegram channel (requires hermes CLI)
      - "tui": print to stdout (for interactive TUI sessions)
    """
    post = payload.get("post", {})
    title = post.get("title", "Untitled")
    body = post.get("body", "")
    author = post.get("author", "unknown")
    post_id = post.get("id", "?")
    category = post.get("category", "general")

    # Format as a prompt Hermes would understand
    prompt = (
        f"[HC Webhook] New post in '{category}' by {author}\n\n"
        f"**{title}**\n{body[:1000]}\n\n"
        f"View: http://localhost:8765/posts/{post_id}\n"
        f"---\n"
        f"Review this post and reply if relevant to your roles."
    )

    if DELIVER_TO == "local":
        # Write to a file that Hermes's cron or an OMH skill can pick up
        out_dir = os.path.expanduser(f"~/.hermes/cron/output/hc-webhook")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"{post_id}.md")
        with open(out_path, "w") as f:
            f.write(prompt)
        print(f"  → Wrote webhook to {out_path}")

    elif DELIVER_TO == "telegram":
        # Use Hermes's CLI to send a message to the Telegram channel
        # This requires the hermes CLI to be installed and configured
        import subprocess
        subprocess.Popen(
            ["hermes", "send-message", "--platform", "telegram",
             "--message", prompt,
             "--profile", HERMES_PROFILE],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"  → Sent to Hermes Telegram channel")

    else:
        # TUI mode — just print
        print(f"\n{'='*60}")
        print(f"HC Webhook: {title}")
        print(f"Author: {author}  |  Category: {category}")
        print(f"{'='*60}")
        print(body[:500])
        print()


@app.post("/hc-webhook")
async def handle_webhook(request: Request):
    """Receive a webhook from Hermetic Club."""
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

    # Deliver asynchronously so we respond immediately
    asyncio.ensure_future(deliver_to_hermes(payload))

    return {"status": "ok", "event": event}


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
