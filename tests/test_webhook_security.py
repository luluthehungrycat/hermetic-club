import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from hermetic_club.services import webhooks
from hermetic_club.services.relevance import relevant_posts_for_agent
from hermetic_club.services.test_posts import NOREPLY_TEST_TAG, is_noreply_test


def test_noreply_test_tag_is_detected_exactly():
    assert is_noreply_test([NOREPLY_TEST_TAG]) is True
    assert is_noreply_test(["test", NOREPLY_TEST_TAG]) is True
    assert is_noreply_test(["noreply_testing"]) is False


def test_dispatch_skips_noreply_test_posts(monkeypatch):
    called = False

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            nonlocal called
            called = True
            return httpx.Response(200, request=httpx.Request("POST", args[0]))

    monkeypatch.setattr(webhooks.httpx, "Client", Client)
    monkeypatch.setattr(webhooks, "WEBHOOK_ALLOWED_HOSTS", {"100.64.0.2"})

    webhooks.fire_post_webhooks(
        "post-1", "Title", "Body", "general", [NOREPLY_TEST_TAG], [], "author",
        [{"url": "http://100.64.0.2:8766/hc-webhook/default", "agent_name": "a", "roles": []}],
    )

    assert called is False


def test_relevance_excludes_noreply_test_posts_unless_opted_in():
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    normal = SimpleNamespace(
        tags="[]", category="general", is_pinned=False, is_solved=False, created_at=now,
    )
    test_post = SimpleNamespace(
        tags=json.dumps([NOREPLY_TEST_TAG]), category="general", is_pinned=False,
        is_solved=False, created_at=now,
    )
    session = SimpleNamespace(
        get=AsyncMock(return_value=SimpleNamespace(categories='["general"]')),
        execute=AsyncMock(
            return_value=SimpleNamespace(
                scalars=lambda: SimpleNamespace(all=lambda: [normal, test_post]),
            ),
        ),
    )

    result = asyncio.run(relevant_posts_for_agent(session, "agent-1"))
    assert result == [normal]

    result = asyncio.run(
        relevant_posts_for_agent(session, "agent-1", include_noreply_test=True)
    )
    assert result == [normal, test_post]


def test_dispatch_adds_configured_bearer_header(monkeypatch):
    seen = {}

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, **kwargs):
            seen.update(kwargs)
            return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(webhooks.httpx, "Client", Client)
    monkeypatch.setattr(webhooks, "WEBHOOK_SECRET", "test-secret")
    monkeypatch.setattr(webhooks, "WEBHOOK_ALLOWED_HOSTS", {"100.64.0.2"})

    webhooks.fire_post_webhooks(
        "post-1", "Title", "Body", "general", [], [], "author",
        [{"url": "http://100.64.0.2:8766/hc-webhook/default", "agent_name": "a", "roles": []}],
    )

    assert seen["headers"] == {"Authorization": "Bearer test-secret"}


def test_dispatch_rejects_non_allowlisted_webhook_url(monkeypatch):
    called = False

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            nonlocal called
            called = True
            return httpx.Response(200, request=httpx.Request("POST", args[0]))

    monkeypatch.setattr(webhooks.httpx, "Client", Client)
    monkeypatch.setattr(webhooks, "WEBHOOK_ALLOWED_HOSTS", {"100.64.0.2"})

    webhooks.fire_post_webhooks(
        "post-1", "Title", "Body", "general", [], [], "author",
        [{"url": "http://127.0.0.1:8765/admin", "agent_name": "a", "roles": []}],
    )

    assert called is False


def test_knowledge_fact_query_is_newest_first(monkeypatch):
    # This is asserted through the source query contract rather than a live DB.
    source = Path(__file__).parents[1] / "src/hermetic_club/routes/knowledge.py"
    text = source.read_text()
    assert "KnowledgeFact.created_at.desc()" in text
