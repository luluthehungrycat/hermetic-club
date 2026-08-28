"""Database engine and session management."""

from __future__ import annotations

from pathlib import Path

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


async def close_db() -> None:
    """Dispose the engine."""
    global _engine, _SessionLocal
    if _engine:
        await _engine.dispose()
    _engine = None
    _SessionLocal = None
