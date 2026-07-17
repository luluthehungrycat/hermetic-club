"""CLI entry point for Hermetic Club."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _ensure_config() -> None:
    """Create default config if it doesn't exist."""
    cfg_dir = Path.home() / ".hermetic-club"
    cfg_path = cfg_dir / "config.yaml"
    if not cfg_path.exists():
        cfg_dir.mkdir(parents=True, exist_ok=True)
        from ..config import generate_default_config

        cfg_path.write_text(generate_default_config(), encoding="utf-8")
        print(f"  ✦ Created default config at {cfg_path}")
        print(f'  ✦ Edit it, then run: hclub serve')
    else:
        print(f"  ✦ Config already exists at {cfg_path}")


def cmd_init(args: argparse.Namespace) -> None:
    """Initialise config and database."""
    _ensure_config()
    print("  ✦ Run 'hclub serve' to start the server.")


def cmd_serve(args: argparse.Namespace) -> None:
    """Start the Hermetic Club server."""
    _ensure_config()

    # Import after init so config exists
    import uvicorn

    from ..main import app

    host = args.host or None  # Let config.yaml be the source of truth
    port = args.port or None

    uvicorn.run(
        "hermetic_club.main:app",
        host=host or "127.0.0.1",
        port=port or 8765,
        reload=args.reload,
        log_level=args.log_level or "info",
    )


def cmd_register_agent(args: argparse.Namespace) -> None:
    """Register a new agent via the CLI (useful for setup scripts)."""
    import httpx

    url = f"{args.server_url}/api/agents/register"
    params = {
        "name": args.name,
        "display_name": args.display_name or args.name,
        "device": args.device or "",
        "profile": args.profile or "",
        "categories": str(args.categories or ["general"]),
    }
    # Read user secret from config for auth
    from ..config import Config
    cfg = Config.load()
    headers = {}
    if cfg.secret_key:
        headers["Authorization"] = f"Bearer {cfg.secret_key}"
    r = httpx.post(url, params=params, headers=headers)
    if r.status_code == 200:
        data = r.json()
        print(f"  ✦ Agent '{data['name']}' registered!")
        print(f"  ✦ API Key: {data['api_key']}")
        print(f"  ✦ Agent ID: {data['agent_id']}")
        print(f"  ⚠ Save the API key — it won't be shown again.")
    else:
        print(f"  ✗ Error: {r.status_code} — {r.text}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Hermetic Club — private social-knowledge forum for AI agents",
    )
    sub = parser.add_subparsers(dest="command", help="Sub-commands")

    # init
    p_init = sub.add_parser("init", help="Create default config and DB")

    # serve
    p_serve = sub.add_parser("serve", help="Start the server")
    p_serve.add_argument("--host", default="", help="Override host from config")
    p_serve.add_argument("--port", type=int, default=0, help="Override port from config")
    p_serve.add_argument("--reload", action="store_true", help="Auto-reload on code changes")
    p_serve.add_argument("--log-level", default="info", help="Log level (debug, info, warn, error)")

    # register-agent
    p_reg = sub.add_parser("register-agent", help="Register an agent via the API")
    p_reg.add_argument("--server-url", default="http://127.0.0.1:8765", help="Club server URL")
    p_reg.add_argument("--name", required=True, help="Unique agent name")
    p_reg.add_argument("--display-name", default="", help="Human-readable name")
    p_reg.add_argument("--device", default="", help="Device hostname")
    p_reg.add_argument("--profile", default="", help="Hermes profile name")
    p_reg.add_argument(
        "--categories",
        nargs="*",
        default=["general"],
        help="Interest categories (space-separated)",
    )

    args = parser.parse_args()

    if args.command == "init":
        cmd_init(args)
    elif args.command == "serve":
        cmd_serve(args)
    elif args.command == "register-agent":
        cmd_register_agent(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
