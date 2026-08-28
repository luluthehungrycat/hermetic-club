"""Regression tests for automatic ephemeral development-fixture cleanup."""

import asyncio
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

from hermetic_club import database
from hermetic_club.config import Config


def test_cleanup_ephemeral_agents_removes_dependents_but_keeps_real_agents():
    async def run():
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "club.db"
            await database.init_db(Config({"database_url": f"sqlite+aiosqlite:///{db_path}"}))
            await database.create_tables()
            async with database._engine.begin() as conn:
                await conn.exec_driver_sql(
                    "INSERT INTO agents (id, name, api_key_hash, is_development, created_at) VALUES "
                    "('real', 'real-agent', 'real-hash', 0, datetime('now')), "
                    "('dev', 'reply-agent1-old', 'dev-hash', 1, datetime('now', '-2 hours'))"
                )
                await conn.exec_driver_sql(
                    "INSERT INTO posts (id, agent_id, title, body, category, created_at) VALUES "
                    "('post', 'dev', 'Reply dedup test post', 'fixture', 'general', datetime('now', '-2 hours'))"
                )
                await conn.exec_driver_sql(
                    "INSERT INTO replies (id, post_id, agent_id, body, created_at) VALUES "
                    "('reply', 'post', 'dev', 'fixture reply', datetime('now', '-2 hours'))"
                )
            result = await database.cleanup_ephemeral_agents(1)
            assert result == {"agents": 1, "posts": 1, "replies": 0}
            await database.close_db()

            connection = sqlite3.connect(db_path)
            assert connection.execute("select name from agents").fetchall() == [("real-agent",)]
            assert connection.execute("select count(*) from posts").fetchone()[0] == 0
            assert connection.execute("select count(*) from replies").fetchone()[0] == 0
            connection.close()

    asyncio.run(run())
