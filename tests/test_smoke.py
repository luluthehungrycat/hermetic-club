"""Quick smoke test — requires a running Hermetic Club server."""

import httpx


def test_health():
    r = httpx.get("http://127.0.0.1:8765/health", timeout=5)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["service"] == "hermetic-club"


def test_feed():
    r = httpx.get("http://127.0.0.1:8765/api/feed", timeout=5)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_web_ui():
    r = httpx.get("http://127.0.0.1:8765/", timeout=5)
    assert r.status_code == 200
    assert "Hermetic Club" in r.text


def test_agent_list():
    r = httpx.get("http://127.0.0.1:8765/api/agents/list", timeout=5)
    assert r.status_code == 200
    assert isinstance(r.json(), list)
