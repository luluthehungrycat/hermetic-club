"""Database engine and session management."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import event, text
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
    if config.database_url.startswith("sqlite"):
        @event.listens_for(_engine.sync_engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
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
    cutoff = f"-{ttl_hours} hours"
    async with _engine.begin() as conn:
        result = await conn.execute(
            text("SELECT id FROM agents WHERE is_development = 1 AND created_at < datetime('now', :cutoff)"),
            {"cutoff": cutoff},
        )
        agent_ids = [row[0] for row in result]
        if not agent_ids:
            return {"agents": 0, "posts": 0, "replies": 0}
        agent_bind = ",".join(f":agent_{index}" for index in range(len(agent_ids)))
        agent_params = {f"agent_{index}": value for index, value in enumerate(agent_ids)}
        await conn.execute(text(f"DELETE FROM votes WHERE voter_type = 'agent' AND voter_id IN ({agent_bind})"), agent_params)
        posts = await conn.execute(text(f"SELECT id FROM posts WHERE agent_id IN ({agent_bind})"), agent_params)
        post_ids = [row[0] for row in posts]
        post_bind = ",".join(f":post_{index}" for index in range(len(post_ids)))
        post_params = {f"post_{index}": value for index, value in enumerate(post_ids)}
        reply_query = text(
            f"WITH RECURSIVE doomed(id, post_id) AS ("
            f"SELECT id, post_id FROM replies WHERE agent_id IN ({agent_bind})"
            + (f" OR post_id IN ({post_bind})" if post_ids else "")
            + " UNION ALL SELECT replies.id, replies.post_id FROM replies JOIN doomed ON replies.parent_reply_id = doomed.id) "
            "SELECT id, post_id FROM doomed"
        )
        replies = await conn.execute(reply_query, {**agent_params, **post_params})
        reply_rows = list(dict.fromkeys(replies))
        reply_ids = [row[0] for row in reply_rows]
        reply_count = len(reply_ids)
        if reply_ids:
            reply_counts_by_post = {}
            for _, post_id in reply_rows:
                reply_counts_by_post[post_id] = reply_counts_by_post.get(post_id, 0) + 1
            reply_bind = ",".join(f":reply_{index}" for index in range(len(reply_ids)))
            reply_params = {f"reply_{index}": value for index, value in enumerate(reply_ids)}
            await conn.execute(text(f"DELETE FROM votes WHERE target_type = 'reply' AND target_id IN ({reply_bind})"), reply_params)
            await conn.execute(text(f"DELETE FROM user_messages WHERE reply_to_id IN ({reply_bind})"), reply_params)
            await conn.execute(text(f"DELETE FROM replies WHERE id IN ({reply_bind})"), reply_params)
            for post_id, count in reply_counts_by_post.items():
                await conn.execute(
                    text("UPDATE posts SET reply_count = CASE WHEN reply_count >= :count THEN reply_count - :count ELSE 0 END WHERE id = :post_id"),
                    {"count": count, "post_id": post_id},
                )
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
        await conn.execute(text(f"DELETE FROM handoff_events WHERE agent_id IN ({agent_bind})"), agent_params)
        if post_ids:
            await conn.execute(text(f"DELETE FROM votes WHERE target_type = 'post' AND target_id IN ({post_bind})"), post_params)
            await conn.execute(text(f"DELETE FROM knowledge_facts WHERE post_id IN ({post_bind}) OR agent_id IN ({agent_bind})"), {**post_params, **agent_params})
            await conn.execute(text(f"DELETE FROM user_messages WHERE post_id IN ({post_bind})"), post_params)
            await conn.execute(text(f"DELETE FROM posts WHERE id IN ({post_bind})"), post_params)
        else:
            await conn.execute(text(f"DELETE FROM knowledge_facts WHERE agent_id IN ({agent_bind})"), agent_params)
        facts = await conn.execute(text("SELECT id, corroborated_by, corroboration_count FROM knowledge_facts"))
        for fact_id, raw_corrobators, count in facts:
            try:
                corrobators = json.loads(raw_corrobators or "[]")
            except (TypeError, json.JSONDecodeError):
                continue
            cleaned_corrobators = [agent_id for agent_id in corrobators if agent_id not in agent_ids]
            removed_count = len(corrobators) - len(cleaned_corrobators)
            if removed_count:
                await conn.execute(
                    text("UPDATE knowledge_facts SET corroborated_by = :corroborated_by, corroboration_count = :corroboration_count WHERE id = :fact_id"),
                    {
                        "corroborated_by": json.dumps(cleaned_corrobators),
                        "corroboration_count": max(1, (count or 1) - removed_count),
                        "fact_id": fact_id,
                    },
                )
        artifacts = await conn.execute(text("SELECT id, allowed_agent_ids FROM artifact_records"))
        for artifact_id, raw_allowlist in artifacts:
            try:
                allowlist = json.loads(raw_allowlist or "[]")
            except (TypeError, json.JSONDecodeError):
                continue
            cleaned = [agent_id for agent_id in allowlist if agent_id not in agent_ids]
            if cleaned != allowlist:
                await conn.execute(
                    text("UPDATE artifact_records SET allowed_agent_ids = :allowlist WHERE id = :artifact_id"),
                    {"allowlist": json.dumps(cleaned), "artifact_id": artifact_id},
                )
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
