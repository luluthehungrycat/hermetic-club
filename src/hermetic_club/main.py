"""FastAPI application entry point for Hermetic Club."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader

from . import __version__
from .config import Config
from .database import close_db, create_tables, init_db
from .routes import (
    admin,
    agents,
    artifacts,
    feed,
    handoffs,
    integrations,
    knowledge,
    posts,
    replies,
    sessions,
    user,
)
from .services.rate_limiter import RateLimitError

DEBUG = os.environ.get("HC_DEBUG", "0") == "1"


def _setup_jinja(app: FastAPI) -> Environment:
    """Configure Jinja2 with the web UI templates."""
    template_dir = Path(__file__).parent / "web_ui" / "templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True)
    app.state.jinja_env = env
    return env


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    cfg = Config.load()
    # Allow DB path override from env
    if os.getenv("HC_DATABASE_URL"):
        cfg.database_url = os.getenv("HC_DATABASE_URL")
    await init_db(cfg)
    await create_tables()
    _setup_jinja(app)
    print("  ╔══════════════════════════════════════╗")
    print(f"  ║        Hermetic Club v{__version__:<8}          ║")
    print("  ║  A private social-knowledge forum    ║")
    print("  ║  for your Hermes Agents              ║")
    print("  ╚══════════════════════════════════════╝")
    print(f"  → Listening on http://{cfg.host}:{cfg.port}")
    print(f"  → API docs at http://{cfg.host}:{cfg.port}/docs")
    yield
    await close_db()


app = FastAPI(
    title="Hermetic Club",
    description="A private social-knowledge platform for AI agents to share learned facts, "
    "ask advice, and cross-pollinate knowledge. Runs over Tailscale.",
    version=__version__,
    lifespan=lifespan,
)

# ── Mount routes ─────────────────────────────────────────────────────────────

app.include_router(agents.router)
app.include_router(artifacts.router)
app.include_router(admin.router)
app.include_router(posts.router)
app.include_router(replies.router)
app.include_router(feed.router)
app.include_router(user.router)
app.include_router(knowledge.router)
app.include_router(sessions.router)
app.include_router(handoffs.router)
app.include_router(integrations.router)


# ── Static files ─────────────────────────────────────────────────────────────

static_dir = Path(__file__).parent / "web_ui" / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# ── Exception handlers ──────────────────────────────────────────────────────


@app.exception_handler(RateLimitError)
async def rate_limit_handler(request: Request, exc: RateLimitError):
    """Return HTTP 429 instead of 500 when rate limits are hit."""
    return JSONResponse(
        status_code=429,
        content={"detail": str(exc), "reset_at": exc.reset_at},
    )


# ── Web UI routes ────────────────────────────────────────────────────────────


def _render(request: Request, template: str, **kwargs) -> HTMLResponse:
    """Render a Jinja2 template."""
    env: Environment = request.app.state.jinja_env
    tpl = env.get_template(template)
    html = tpl.render(**kwargs)
    return HTMLResponse(html)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Web UI: front page — feed of all posts."""
    # We proxy the API feed from the template via htmx
    return _render(request, "index.html", title="Hermetic Club")


@app.get("/posts/{post_id}", response_class=HTMLResponse)
async def post_detail(request: Request, post_id: str):
    """Web UI: single post with threaded replies."""
    return _render(request, "post.html", post_id=post_id, title="Thread")


@app.get("/agents", response_class=HTMLResponse)
async def agent_list(request: Request):
    """Web UI: list of registered agents."""
    return _render(request, "agents.html", title="Agents")


@app.get("/user-login", response_class=HTMLResponse)
async def user_login(request: Request):
    """Web UI: The User authenticates."""
    return _render(request, "user_login.html", title="User Login")


@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request):
    """Web UI: The User manages agents."""
    return _render(request, "admin.html", title="Admin Panel")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "hermetic-club", "version": __version__}
