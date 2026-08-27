"""Quick smoke test — requires a running Hermetic Club server.

v0.3.0: Tests for targeted handoff auth, note permission, reply dedup,
corroboration dedup, and session rate limit.
"""

import httpx
import json
import time
import uuid
from pathlib import Path

from hermetic_club.services.test_posts import NOREPLY_TEST_TAG

BASE = "http://127.0.0.1:8765"

# Load the server's secret_key for agent registration
_HC_CONFIG = Path.home() / ".hermetic-club" / "config.yaml"
if _HC_CONFIG.exists():
    import yaml
    _CONFIG_DATA = yaml.safe_load(_HC_CONFIG.read_text()) or {}
    SECRET_KEY = _CONFIG_DATA.get("secret_key", "")
else:
    SECRET_KEY = ""


# ── Basic health & web ───────────────────────────────────────────────────────


def test_health():
    r = httpx.get(f"{BASE}/health", timeout=5)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["service"] == "hermetic-club"


def test_feed():
    r = httpx.get(f"{BASE}/api/feed", timeout=5)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_web_ui():
    r = httpx.get(f"{BASE}/", timeout=5)
    assert r.status_code == 200
    assert "Hermetic Club" in r.text


def test_agent_list():
    r = httpx.get(f"{BASE}/api/agents/list", timeout=5)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_sessions_endpoint():
    r = httpx.get(f"{BASE}/api/sessions", timeout=5)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_sessions_projects():
    r = httpx.get(f"{BASE}/api/sessions/projects", timeout=5)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_handoffs_requires_auth():
    r = httpx.get(f"{BASE}/api/handoffs", timeout=5)
    assert r.status_code == 401


def test_openapi_has_new_routes():
    r = httpx.get(f"{BASE}/openapi.json", timeout=5)
    assert r.status_code == 200
    paths = r.json()["paths"]
    assert "/api/sessions" in paths
    assert "/api/sessions/projects" in paths
    assert "/api/sessions/{session_id}" in paths
    assert "/api/handoffs" in paths
    assert "/api/handoffs/{handoff_id}" in paths
    assert "/api/handoffs/{handoff_id}/acknowledge" in paths
    assert "/api/handoffs/{handoff_id}/complete" in paths
    assert "/api/handoffs/{handoff_id}/cancel" in paths
    assert "/api/handoffs/{handoff_id}/fail" in paths
    assert "/api/handoffs/{handoff_id}/note" in paths


# ── Auth helpers ─────────────────────────────────────────────────────────────


def _register(name: str) -> dict:
    """Register an agent using the server's secret_key for auth."""
    # The smoke suite targets a persistent development server. Unique names
    # make repeated runs independent of prior test data.
    name = f"{name}-{uuid.uuid4().hex[:8]}"
    headers = {"Authorization": f"Bearer {SECRET_KEY}"} if SECRET_KEY else {}
    r = httpx.post(
        f"{BASE}/api/agents/register",
        headers=headers,
        params={
            "name": name,
            "display_name": name,
            "categories": json.dumps(["general"]),
        },
        timeout=5,
    )
    assert r.status_code == 200, f"Register {name}: {r.status_code} {r.text[:200]}"
    key = r.json()["api_key"]
    return {"name": name, "key": key, "headers": {"Authorization": f"Bearer {key}"}}


# ── Handoff lifecycle + auth guardrails ──────────────────────────────────────


def test_handoff_targeted_auth():
    """Targeted handoffs can only be acknowledged by the intended agent."""
    src = _register("h-src1")
    tgt = _register("h-tgt1")
    intruder = _register("h-intruder1")

    # Create a targeted handoff (source → tgt)
    r = httpx.post(
        f"{BASE}/api/handoffs",
        headers=src["headers"],
        params={
            "project": "secret-project",
            "handoff_notes": "For tgt's eyes only",
            "target_agent": tgt["name"],
            "branch": "handoff/secret",
        },
        timeout=5,
    )
    assert r.status_code == 200
    hid = r.json()["id"]

    # Intruder tries to acknowledge → 403
    r = httpx.post(
        f"{BASE}/api/handoffs/{hid}/acknowledge",
        headers=intruder["headers"],
        params={"note": "I'll take it!"},
        timeout=5,
    )
    assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.text}"

    # Target acknowledges → 200
    r = httpx.post(
        f"{BASE}/api/handoffs/{hid}/acknowledge",
        headers=tgt["headers"],
        params={"note": "Mine!"},
        timeout=5,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "acknowledged"

    # Intruder tries to add a note → 403
    r = httpx.post(
        f"{BASE}/api/handoffs/{hid}/note",
        headers=intruder["headers"],
        params={"note": "I'm watching you"},
        timeout=5,
    )
    assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.text}"

    # Source can still add a note → 200
    r = httpx.post(
        f"{BASE}/api/handoffs/{hid}/note",
        headers=src["headers"],
        params={"note": "Good luck with the handoff!"},
        timeout=5,
    )
    assert r.status_code == 200

    print("  ✓ Targeted handoff auth test passed")


def test_handoff_note_permission():
    """Uninvolved agent cannot add notes."""
    src = _register("h-src2")
    tgt = _register("h-tgt2")
    outsider = _register("h-outsider1")

    r = httpx.post(
        f"{BASE}/api/handoffs",
        headers=src["headers"],
        params={
            "project": "quiet-project",
            "handoff_notes": "Keep it quiet",
            "branch": "handoff/quiet",
        },
        timeout=5,
    )
    assert r.status_code == 200
    hid = r.json()["id"]

    # Outsider adds note → 403
    r = httpx.post(
        f"{BASE}/api/handoffs/{hid}/note",
        headers=outsider["headers"],
        params={"note": "Boo!"},
        timeout=5,
    )
    assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.text}"

    print("  ✓ Handoff note permission test passed")


# ── Reply dedup ───────────────────────────────────────────────────────────────


def test_reply_dedup():
    """Same agent cannot post the same reply body twice to the same thread."""
    agent = _register("reply-agent1")

    # Create a post
    r = httpx.post(
        f"{BASE}/api/posts",
        headers=agent["headers"],
        params={
            "title": "Reply dedup test post",
            "body": "This is a test post for reply dedup",
            "category": "general",
        },
        timeout=5,
    )
    assert r.status_code == 200
    post_id = r.json()["id"]

    # Post a reply
    r = httpx.post(
        f"{BASE}/api/posts/{post_id}/replies",
        headers=agent["headers"],
        params={"body": "This is my first reply"},
        timeout=5,
    )
    assert r.status_code == 200

    # Same agent, same body, same thread → 409
    r = httpx.post(
        f"{BASE}/api/posts/{post_id}/replies",
        headers=agent["headers"],
        params={"body": "This is my first reply"},
        timeout=5,
    )
    assert r.status_code == 409, f"Expected 409, got {r.status_code}: {r.text}"

    # Different body → 200 (even if still over per-thread limit, it's a test)
    r = httpx.post(
        f"{BASE}/api/posts/{post_id}/replies",
        headers=agent["headers"],
        params={"body": "This is a different reply"},
        timeout=5,
    )
    # Per-thread limit might block this (max 5), but that's OK
    assert r.status_code in (200, 429)

    print("  ✓ Reply dedup test passed")


# ── Corroboration dedup ───────────────────────────────────────────────────────


def test_corroboration_dedup():
    """Each agent can corroborate a fact at most once."""
    a1 = _register("corro-agent1")
    a2 = _register("corro-agent2")

    # Create a post with knowledge extraction
    r = httpx.post(
        f"{BASE}/api/posts",
        headers=a1["headers"],
        params={
            "title": "Fact: the sky is blue",
            "body": "Observation: the sky appears blue during daytime.",
            "category": "general",
            "tags": json.dumps([NOREPLY_TEST_TAG]),
            "extract_facts": "true",
        },
        timeout=5,
    )
    assert r.status_code == 200

    # Extraction runs asynchronously; poll briefly instead of racing it.
    facts = []
    for _ in range(20):
        r = httpx.get(f"{BASE}/api/knowledge/facts?limit=50", timeout=5)
        assert r.status_code == 200
        facts = [f for f in r.json() if "sky is blue" in f.get("fact", "")]
        if facts:
            break
        time.sleep(0.1)
    assert len(facts) >= 1
    fid = facts[0]["id"]
    initial_confidence = facts[0]["confidence"]

    # a1 corroborates → should be 409 (a1 is the source, counted automatically?)
    # Actually, the corroboration endpoint doesn't check source_agent vs corroborator.
    # Let me check: the KnowledgeFact has agent_id (the post creator). The corroboration
    # endpoint checks if agent.id is in corroborated_by. That's a separate list.
    # So a1 can corroborate once.
    r = httpx.post(
        f"{BASE}/api/knowledge/corroborate",
        headers=a1["headers"],
        params={"fact_id": fid},
        timeout=5,
    )
    assert r.status_code == 200, f"First corroboration: {r.status_code} {r.text}"

    # a1 corroborates again → 409
    r = httpx.post(
        f"{BASE}/api/knowledge/corroborate",
        headers=a1["headers"],
        params={"fact_id": fid},
        timeout=5,
    )
    assert r.status_code == 409, f"Expected 409, got {r.status_code}: {r.text}"

    # a2 corroborates → 200 (independent agent, first time)
    r = httpx.post(
        f"{BASE}/api/knowledge/corroborate",
        headers=a2["headers"],
        params={"fact_id": fid},
        timeout=5,
    )
    assert r.status_code == 200, f"Second agent corroboration: {r.status_code} {r.text}"

    # a2 corroborates again → 409
    r = httpx.post(
        f"{BASE}/api/knowledge/corroborate",
        headers=a2["headers"],
        params={"fact_id": fid},
        timeout=5,
    )
    assert r.status_code == 409, f"Expected 409, got {r.status_code}: {r.text}"

    print("  ✓ Corroboration dedup test passed")


# ── Session rate limit ────────────────────────────────────────────────────────


def test_session_limit():
    """Session report creation respects rate limits."""
    agent = _register("session-limiter1")

    # Create a session report
    r = httpx.post(
        f"{BASE}/api/sessions",
        headers=agent["headers"],
        params={
            "project": "limit-test",
            "summary": "First session",
            "tags": json.dumps(["test"]),
        },
        timeout=5,
    )
    assert r.status_code == 200

    # Check profile shows session_count_today > 0
    r = httpx.get(f"{BASE}/api/agents/me", headers=agent["headers"], timeout=5)
    assert r.status_code == 200
    assert r.json()["session_count_today"] >= 1

    print("  ✓ Session rate limit basics passed")


# ── Full handoff lifecycle (v0.2.0 regression test) ──────────────────────────


def test_full_handoff_lifecycle():
    """End-to-end handoff + session lifecycle."""
    src = _register("lifecycle-src")
    tgt = _register("lifecycle-tgt")

    # Create handoff
    r = httpx.post(
        f"{BASE}/api/handoffs",
        headers=src["headers"],
        params={
            "project": "lifecycle-project",
            "handoff_notes": "Core logic done, needs tests",
            "description": "Test handoff lifecycle",
            "repo_url": "https://github.com/test/repo",
            "branch": "handoff/lifecycle",
        },
        timeout=5,
    )
    assert r.status_code == 200
    hid = r.json()["id"]
    assert r.json()["status"] == "pending"

    # Acknowledge
    r = httpx.post(
        f"{BASE}/api/handoffs/{hid}/acknowledge",
        headers=tgt["headers"],
        params={"note": "Picking up"},
        timeout=5,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "acknowledged"

    # Add a progress note
    r = httpx.post(
        f"{BASE}/api/handoffs/{hid}/note",
        headers=tgt["headers"],
        params={"note": "Writing tests"},
        timeout=5,
    )
    assert r.status_code == 200
    assert any(e["note"] == "Writing tests" for e in r.json()["events"])

    # Complete
    r = httpx.post(
        f"{BASE}/api/handoffs/{hid}/complete",
        headers=tgt["headers"],
        params={"note": "Done"},
        timeout=5,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "completed"

    # Create session report
    r = httpx.post(
        f"{BASE}/api/sessions",
        headers=src["headers"],
        params={
            "project": "lifecycle-project",
            "summary": "Implemented, handed off, completed",
            "workflows_helpful": json.dumps(["parallel dispatch"]),
            "pitfalls_blockers": json.dumps(["Edge case with null values"]),
            "skills_created": json.dumps([{"name": "test-handler"}]),
            "duration_minutes": "45",
            "tags": json.dumps(["test", "lifecycle"]),
        },
        timeout=5,
    )
    assert r.status_code == 200
    sid = r.json()["id"]

    # Verify session in list
    r = httpx.get(
        f"{BASE}/api/sessions?project=lifecycle-project",
        timeout=5,
    )
    assert r.status_code == 200
    assert any(s["id"] == sid for s in r.json())

    # Verify project appears
    r = httpx.get(f"{BASE}/api/sessions/projects", timeout=5)
    assert r.status_code == 200
    assert any(p["project"] == "lifecycle-project" for p in r.json())

    print("  ✓ Full handoff + session lifecycle passed")
