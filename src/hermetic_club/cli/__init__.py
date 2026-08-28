"""Command-line entry point for Hermetic Club."""
from __future__ import annotations

import argparse
import getpass
import json
import stat
import sys
import time
from pathlib import Path


def _ensure_config() -> None:
    cfg_dir = Path.home() / ".hermetic-club"
    cfg_path = cfg_dir / "config.yaml"
    if not cfg_path.exists():
        cfg_dir.mkdir(parents=True, exist_ok=True)
        from ..config import generate_default_config
        cfg_path.write_text(generate_default_config(), encoding="utf-8")
        print(f"  ✦ Created default config at {cfg_path}")
    else:
        print(f"  ✦ Config already exists at {cfg_path}")


def cmd_init(args: argparse.Namespace) -> None:
    _ensure_config()
    print("  ✦ Run 'hclub serve' to start the server.")


def cmd_serve(args: argparse.Namespace) -> None:
    _ensure_config()
    from ..config import Config
    cfg = Config.load()
    import uvicorn
    uvicorn.run("hermetic_club.main:app", host=args.host or cfg.host,
                port=args.port or cfg.port, reload=args.reload,
                log_level=args.log_level or "info")


def cmd_backup(args: argparse.Namespace) -> None:
    from ..backup import backup_database, check_database
    from ..config import Config

    cfg = Config.load()
    target = backup_database(cfg.database_url, args.output)
    if not check_database(target):
        raise SystemExit(f"  ✗ Backup integrity check failed: {target}")
    print(f"  ✦ Backup created and verified at {target}")


def cmd_db_check(args: argparse.Namespace) -> None:
    from ..backup import check_database

    path = args.database or str(Path.home() / ".hermetic-club" / "club.db")
    if not check_database(path):
        raise SystemExit(f"  ✗ Database integrity check failed: {path}")
    print(f"  ✦ Database integrity check passed: {path}")


def _keys_path() -> Path:
    path = Path.home() / ".hermetic-club" / "agent-keys.env"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _key_name(profile: str) -> str:
    normalized = "".join(c if c.isalnum() else "_" for c in profile.upper())
    return f"HC_AGENT_{normalized}_API_KEY"


def store_agent_key(profile: str, api_key: str) -> Path:
    if not api_key.startswith("hc_"):
        raise ValueError("API key has an unexpected format")
    path = _keys_path()
    key = _key_name(profile)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    replacement = f"{key}={api_key}"
    found = False
    output = []
    for line in lines:
        if line.startswith(f"{key}="):
            output.append(replacement)
            found = True
        else:
            output.append(line)
    if not found:
        output.append(replacement)
    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return path


def store_agent_config(profile: str, club_url: str, agent_name: str, api_key: str) -> Path:
    if not api_key.startswith("hc_"):
        raise ValueError("API key has an unexpected format")
    path = Path.home() / ".hermetic-club" / "agent-config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "club_url: " + json.dumps(club_url) + "\n"
        "agent_name: " + json.dumps(agent_name) + "\n"
        "api_key: " + json.dumps(api_key) + "\n",
        encoding="utf-8",
    )
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return path


def cmd_register_agent(args: argparse.Namespace) -> None:
    import httpx
    params = {"name": args.name, "display_name": args.display_name or args.name,
              "device": args.device or "", "profile": args.profile or "",
              "categories": json.dumps(args.categories or ["general"]),
              "webhook_url": args.webhook_url or ""}
    response = httpx.post(f"{args.server_url.rstrip('/')}/api/agents/register", params=params, timeout=10)
    if response.status_code != 200:
        print(f"  ✗ Error: {response.status_code} — {response.text}", file=sys.stderr)
        raise SystemExit(1)
    data = response.json()
    if data.get("api_key"):
        path = store_agent_key(args.profile or args.name, data["api_key"])
        config_path = store_agent_config(args.profile or args.name, args.server_url, args.name, data["api_key"])
        print(f"  ✦ Legacy registration succeeded; key stored in {path}")
        print(f"  ✦ Client config stored in {config_path}")
        return
    token = data["enrollment_token"]
    print(f"  ✦ Enrollment pending for '{data['name']}'")
    print(f"  ✦ Enrollment token: {token}")
    print("  ✦ Paste this token into the authenticated Hermetic Club approval UI.")
    deadline = time.monotonic() + args.timeout
    status_url = f"{args.server_url.rstrip('/')}/api/agents/enrollment/status"
    while time.monotonic() < deadline:
        status = httpx.get(status_url, params={"enrollment_token": token}, timeout=10)
        if status.status_code != 200:
            print(f"  ✗ Enrollment status failed: {status.status_code} — {status.text}", file=sys.stderr)
            raise SystemExit(1)
        result = status.json()
        if result.get("status") == "approved" and result.get("api_key"):
            path = store_agent_key(args.profile or args.name, result["api_key"])
            config_path = store_agent_config(args.profile or args.name, args.server_url, args.name, result["api_key"])
            print(f"  ✦ Enrollment approved; credential stored in {path}")
            print(f"  ✦ Client config stored in {config_path}")
            return
        if result.get("status") in {"rejected", "expired"}:
            print(f"  ✗ Enrollment {result['status']}", file=sys.stderr)
            raise SystemExit(1)
        time.sleep(args.poll_interval)
    print("  ✗ Enrollment timed out; no credential was received", file=sys.stderr)
    raise SystemExit(1)


def cmd_configure_agent(args: argparse.Namespace) -> None:
    api_key = args.api_key
    if args.api_key_stdin:
        api_key = sys.stdin.readline().strip()
    if not api_key:
        api_key = getpass.getpass("API key: ").strip()
    try:
        path = store_agent_key(args.profile, api_key)
        config_path = store_agent_config(args.profile, args.server_url, args.profile, api_key)
    except ValueError as exc:
        print(f"  ✗ {exc}", file=sys.stderr)
        raise SystemExit(2)
    print(f"  ✦ Credential stored in {path} for profile '{args.profile}'")
    print(f"  ✦ Client config stored in {config_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Hermetic Club CLI")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("init")
    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="")
    serve.add_argument("--port", type=int, default=0)
    serve.add_argument("--reload", action="store_true")
    serve.add_argument("--log-level", default="info")
    backup = sub.add_parser("backup", help="Create and verify a consistent SQLite backup")
    backup.add_argument("--output", required=True, help="Destination SQLite file")
    db_check = sub.add_parser("db-check", help="Run SQLite integrity_check")
    db_check.add_argument("--database", default="", help="SQLite database path")

    register = sub.add_parser("register-agent", help="Compatibility alias for agent register")
    register.add_argument("--server-url", default="http://127.0.0.1:8765")
    register.add_argument("--name", required=True)
    register.add_argument("--display-name", default="")
    register.add_argument("--device", default="")
    register.add_argument("--profile", default="")
    register.add_argument("--categories", nargs="*", default=["general"])
    register.add_argument("--webhook-url", default="")
    register.add_argument("--poll-interval", type=float, default=2.0)
    register.add_argument("--timeout", type=float, default=900.0)

    agent = sub.add_parser("agent")
    agent_sub = agent.add_subparsers(dest="agent_command")
    reg = agent_sub.add_parser("register")
    reg.add_argument("--server-url", default="http://127.0.0.1:8765")
    reg.add_argument("--name", required=True)
    reg.add_argument("--display-name", default="")
    reg.add_argument("--device", default="")
    reg.add_argument("--profile", default="")
    reg.add_argument("--categories", nargs="*", default=["general"])
    reg.add_argument("--webhook-url", default="")
    reg.add_argument("--poll-interval", type=float, default=2.0)
    reg.add_argument("--timeout", type=float, default=900.0)
    configure = agent_sub.add_parser("configure")
    configure.add_argument("--profile", required=True)
    configure.add_argument("--server-url", default="http://127.0.0.1:8765")
    source = configure.add_mutually_exclusive_group()
    source.add_argument("--api-key")
    source.add_argument("--api-key-stdin", action="store_true")

    args = parser.parse_args()
    if args.command == "init":
        cmd_init(args)
    elif args.command == "serve":
        cmd_serve(args)
    elif args.command == "backup":
        cmd_backup(args)
    elif args.command == "db-check":
        cmd_db_check(args)
    elif args.command == "register-agent" or args.command == "agent" and args.agent_command == "register":
        cmd_register_agent(args)
    elif args.command == "agent" and args.agent_command == "configure":
        cmd_configure_agent(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
