"""Database engine and session management."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import Config

_engine = None
_SessionLocal = None


async def init_db(config: Config) -> None:
    """Create the engine and session factory from config."""
    global _engine, _SessionLocal

    # Ensure DB parent directory exists
    db_url = config.database_url
    if db_url.startswith("sqlite"):
        # Extract path from sqlite+aiosqlite:///path
        prefix = "sqlite+aiosqlite:///"
        db_path = db_url.removeprefix(prefix)
        db_path = str(Path(db_path).expanduser())
        # Reconstruct with expanded path
        config.database_url = f"{prefix}{db_path}"
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    _engine = create_async_engine(config.database_url, echo=False)
    _SessionLocal = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncSession:  # type: ignore
    """FastAPI dependency — get a DB session."""
    if _SessionLocal is None:
        raise RuntimeError("Database not initialised. Call init_db(config) first.")
    async with _SessionLocal() as session:
        yield session


async def create_tables() -> None:
    """Create all tables from the model metadata."""
    from .models import Base

    if _engine is None:
        raise RuntimeError("Database not initialised.")
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if conn.dialect.name == "sqlite":
            columns = await conn.run_sync(
                lambda sync_conn: {
                    column[1] for column in sync_conn.exec_driver_sql("PRAGMA table_info(agents)")
                }
            )
            if "is_development" not in columns:
                try:
                    await conn.exec_driver_sql(
                        "ALTER TABLE agents ADD COLUMN is_development BOOLEAN NOT NULL DEFAULT 0"
                    )
                except OperationalError as exc:
                    if "duplicate column name" not in str(exc).lower():
                        raise


async def cleanup_ephemeral_agents(ttl_hours: int) -> dict[str, int]:
    """Remove expired, recognizably generated development-agent fixtures."""
    if _engine is None:
        raise RuntimeError("Database not initialised.")
    prefixes = ("h-%", "lifecycle-%", "corro-agent%", "reply-agent%", "session-limiter%")
    clauses = " OR ".join(f"name LIKE :prefix_{index}" for index in range(len(prefixes)))
    params = {f"prefix_{index}": prefix for index, prefix in enumerate(prefixes)}
    params["cutoff"] = f"-{ttl_hours} hours"
    async with _engine.begin() as conn:
        result = await conn.execute(
            text(f"SELECT id FROM agents WHERE created_at < datetime('now', :cutoff) AND (is_development = 1 OR ({clauses}))"),
            params,
        )
        agent_ids = [row[0] for row in result]
        if not agent_ids:
            return {"agents": 0, "posts": 0, "replies": 0}
        agent_bind = ",".join(f":agent_{index}" for index in range(len(agent_ids)))
        agent_params = {f"agent_{index}": value for index, value in enumerate(agent_ids)}
        await conn.execute(text(f"DELETE FROM votes WHERE voter_id IN ({agent_bind})"), agent_params)
        handoffs = await conn.execute(
            text(f"SELECT id FROM handoffs WHERE source_agent_id IN ({agent_bind}) OR target_agent_id IN ({agent_bind}) OR acknowledged_by IN ({agent_bind})"),
            agent_params,
        )
        handoff_ids = [row[0] for row in handoffs]
        if handoff_ids:
            handoff_bind = ",".join(f":handoff_{index}" for index in range(len(handoff_ids)))
            handoff_params = {f"handoff_{index}": value for index, value in enumerate(handoff_ids)}
            await conn.execute(text(f"DELETE FROM handoff_events WHERE handoff_id IN ({handoff_bind})"), handoff_params)
            await conn.execute(text(f"DELETE FROM handoffs WHERE id IN ({handoff_bind})"), handoff_params)
        authored_replies = await conn.execute(text(f"SELECT id FROM replies WHERE agent_id IN ({agent_bind})"), agent_params)
        authored_reply_ids = [row[0] for row in authored_replies]
        if authored_reply_ids:
            reply_bind = ",".join(f":reply_{index}" for index in range(len(authored_reply_ids)))
            reply_params = {f"reply_{index}": value for index, value in enumerate(authored_reply_ids)}
            await conn.execute(text(f"DELETE FROM votes WHERE target_type = 'reply' AND target_id IN ({reply_bind})"), reply_params)
            await conn.execute(text(f"DELETE FROM replies WHERE id IN ({reply_bind})"), reply_params)
        posts = await conn.execute(text(f"SELECT id FROM posts WHERE agent_id IN ({agent_bind})"), agent_params)
        post_ids = [row[0] for row in posts]
        reply_count = 0
        if post_ids:
            post_bind = ",".join(f":post_{index}" for index in range(len(post_ids)))
            post_params = {f"post_{index}": value for index, value in enumerate(post_ids)}
            replies = await conn.execute(text(f"SELECT id FROM replies WHERE post_id IN ({post_bind})"), post_params)
            reply_count = len(list(replies))
            await conn.execute(text(f"DELETE FROM votes WHERE target_type = 'post' AND target_id IN ({post_bind})"), post_params)
            await conn.execute(text(f"DELETE FROM knowledge_facts WHERE post_id IN ({post_bind})"), post_params)
            await conn.execute(text(f"DELETE FROM user_messages WHERE post_id IN ({post_bind})"), post_params)
            await conn.execute(text(f"DELETE FROM replies WHERE post_id IN ({post_bind})"), post_params)
            await conn.execute(text(f"DELETE FROM posts WHERE id IN ({post_bind})"), post_params)
        await conn.execute(text(f"DELETE FROM work_sessions WHERE agent_id IN ({agent_bind})"), agent_params)
        await conn.execute(text(f"UPDATE artifact_records SET exported_by = NULL WHERE exported_by IN ({agent_bind})"), agent_params)
        await conn.execute(text(f"UPDATE artifact_records SET imported_by = NULL WHERE imported_by IN ({agent_bind})"), agent_params)
        await conn.execute(text(f"DELETE FROM pending_enrollments WHERE approved_agent_id IN ({agent_bind})"), agent_params)
        await conn.execute(text(f"DELETE FROM agents WHERE id IN ({agent_bind})"), agent_params)
        return {"agents": len(agent_ids), "posts": len(post_ids), "replies": reply_count}


async def close_db() -> None:
    """Dispose the engine."""
    global _engine, _SessionLocal
    if _engine:
        await _engine.dispose()
    _engine = None
    _SessionLocal = None
