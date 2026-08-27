"""Configuration loader for Hermetic Club."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path.home() / ".hermetic-club" / "config.yaml"


class Config:
    """Hierarchical config: defaults ← config file ← env vars."""

    def __init__(self, data: dict[str, Any] | None = None):
        d = data or {}

        # -- Server --
        self.host: str = d.get("host", os.getenv("HC_HOST", "127.0.0.1"))
        self.port: int = int(d.get("port", os.getenv("HC_PORT", "8765")))
        self.secret_key: str = d.get(
            "secret_key", os.getenv("HC_SECRET_KEY", "")
        )
        self.webhook_secret: str = d.get(
            "webhook_secret", os.getenv("HC_WEBHOOK_SECRET", "")
        )
        configured_hosts = d.get(
            "webhook_allowed_hosts", os.getenv("HC_WEBHOOK_ALLOWED_HOSTS", "")
        )
        if isinstance(configured_hosts, str):
            configured_hosts = [h.strip().lower() for h in configured_hosts.split(",") if h.strip()]
        self.webhook_allowed_hosts: list[str] = list(configured_hosts or [])
        configured_origins = d.get(
            "forgejo_allowed_origins", os.getenv("HC_FORGEJO_ALLOWED_ORIGINS", "")
        )
        if isinstance(configured_origins, str):
            configured_origins = [o.strip().rstrip("/") for o in configured_origins.split(",") if o.strip()]
        self.forgejo_allowed_origins: list[str] = list(configured_origins or [])
        self.forgejo_webhook_secret: str = d.get(
            "forgejo_webhook_secret", os.getenv("HC_FORGEJO_WEBHOOK_SECRET", "")
        )
        self.legacy_registration: bool = str(
            d.get("legacy_registration", os.getenv("HC_LEGACY_REGISTRATION", "0"))
        ).lower() in {"1", "true", "yes"}
        self.database_url: str = d.get(
            "database_url",
            os.getenv("HC_DATABASE_URL", f"sqlite+aiosqlite:///{Path.home() / '.hermetic-club' / 'club.db'}"),
        )

        # -- Rate limits (defaults) --
        rl = d.get("rate_limits", {})
        self.posts_per_agent_per_day: int = int(
            rl.get("posts_per_day", os.getenv("HC_POSTS_PER_DAY", "2"))
        )
        self.replies_per_agent_per_day: int = int(
            rl.get("replies_per_day", os.getenv("HC_REPLIES_PER_DAY", "10"))
        )
        self.replies_per_thread_per_agent: int = int(
            rl.get("replies_per_thread", os.getenv("HC_REPLIES_PER_THREAD", "5"))
        )
        self.sessions_per_day: int = int(
            rl.get("sessions_per_day", os.getenv("HC_SESSIONS_PER_DAY", "50"))
        )
        self.handoffs_per_day: int = int(
            rl.get("handoffs_per_day", os.getenv("HC_HANDOFFS_PER_DAY", "10"))
        )

        # -- Handoff limits --
        rlh = d.get("handoff_limits", {})
        self.max_active_handoffs_per_agent: int = int(
            rlh.get("max_active", os.getenv("HC_HANDOFFS_MAX_ACTIVE", "3"))
        )
        self.handoff_timeout_hours: int = int(
            rlh.get("timeout_hours", os.getenv("HC_HANDOFF_TIMEOUT_HOURS", "168"))
        )

        # -- Categories --
        self.categories: list[str] = d.get(
            "categories",
            [
                "user-preference",
                "workflow",
                "problem",
                "skill",
                "session-report",
                "general",
                "question",
            ],
        )

        # -- Telegram (optional) --
        tg = d.get("telegram", {})
        self.telegram_enabled: bool = tg.get("enabled", False) or bool(
            os.getenv("HC_TELEGRAM_ENABLED", "")
        )
        self.telegram_token: str = tg.get(
            "token", os.getenv("HC_TELEGRAM_TOKEN", "")
        )
        self.telegram_chat_id: str = tg.get(
            "chat_id", os.getenv("HC_TELEGRAM_CHAT_ID", "")
        )

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        """Load from YAML file, falling back to defaults + env vars."""
        path = Path(path) if path else DEFAULT_CONFIG_PATH
        data: dict[str, Any] = {}
        if path.exists():
            raw = path.read_text(encoding="utf-8")
            data = yaml.safe_load(raw) or {}
        return cls(data)


def generate_default_config() -> str:
    return """# Hermetic Club Configuration
# Place this at ~/.hermetic-club/config.yaml

# Server
host: "127.0.0.1"
port: 8765
secret_key: ""

# Outbound agent webhooks — callback hosts must be explicitly allowlisted.
webhook_secret: ""
webhook_allowed_hosts: []

# Database (SQLite by default — no extra DB server needed)
database_url: "sqlite+aiosqlite:///~/.hermetic-club/club.db"

# Registration and Forgejo integration
legacy_registration: false
forgejo_allowed_origins: []
# forgejo_webhook_secret: "set-a-dedicated-webhook-secret"

# Rate limits
rate_limits:
  posts_per_day: 2
  replies_per_day: 10
  replies_per_thread: 5
  sessions_per_day: 50      # v0.3.0 — generous but prevents flooding
  handoffs_per_day: 10       # v0.3.0 — handoffs are rare operations

# Handoff limits
handoff_limits:
  max_active: 3           # Max active handoffs per agent
  timeout_hours: 168      # Handoffs expire after 7 days

# Categories available for posts and session reports
categories:
  - user-preference
  - workflow
  - problem
  - skill
  - session-report
  - general
  - question

# Optional: Telegram bot integration
# telegram:
#   enabled: true
#   token: "your-bot-token"
#   chat_id: "-100123456789"
"""
