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
                    "('post', 'dev', 'Reply dedup test post', 'fixture', 'general', datetime('now', '-2 hours')), "
                    "('real-post', 'real', 'Real post', 'real content', 'general', datetime('now', '-2 hours'))"
                )
                await conn.exec_driver_sql(
                    "INSERT INTO replies (id, post_id, agent_id, body, created_at) VALUES "
                    "('reply', 'post', 'dev', 'fixture reply', datetime('now', '-2 hours'))"
                )
                await conn.exec_driver_sql(
                    "INSERT INTO artifact_records (id, project, artifact_type, manifest, allowed_agent_ids) VALUES "
                    "('artifact', 'fixture', 'test', '{}', '[\"dev\", \"real\"]')"
                )
                await conn.exec_driver_sql(
                    "INSERT INTO votes (id, target_type, target_id, voter_type, voter_id, vote) VALUES "
                    "('agent-vote', 'post', 'post', 'agent', 'dev', 1), "
                    "('user-vote', 'post', 'real-post', 'user', 'dev', 1)"
                )
            result = await database.cleanup_ephemeral_agents(1)
            assert result == {"agents": 1, "posts": 1, "replies": 1}
            await database.close_db()

            connection = sqlite3.connect(db_path)
            assert connection.execute("select name from agents").fetchall() == [("real-agent",)]
            assert connection.execute("select count(*) from posts").fetchone()[0] == 1
            assert connection.execute("select count(*) from replies").fetchone()[0] == 0
            assert connection.execute("select count(*) from votes where id = 'agent-vote'").fetchone()[0] == 0
            assert connection.execute("select count(*) from votes where id = 'user-vote'").fetchone()[0] == 1
            assert connection.execute("select allowed_agent_ids from artifact_records where id = 'artifact'").fetchone()[0] == '["real"]'
            connection.close()

    asyncio.run(run())
