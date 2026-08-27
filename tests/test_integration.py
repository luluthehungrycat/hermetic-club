"""In-process integration tests for enrollment, Forgejo, artifacts, and handoffs."""
import hashlib
import hmac
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from hermetic_club.config import Config
from hermetic_club.main import app


@pytest.fixture
def client():
    with TemporaryDirectory() as temp_dir:
        config = Config({
            "secret_key": "integration-user-secret",
            "forgejo_webhook_secret": "integration-forgejo-secret",
            "forgejo_allowed_origins": ["http://forgejo.test"],
            "database_url": f"sqlite+aiosqlite:///{Path(temp_dir) / 'club.db'}",
        })
        with patch.object(Config, "load", return_value=config), TestClient(app) as test_client:
            yield test_client


def user_headers():
    return {"Authorization": "Bearer integration-user-secret"}


def enroll(client, name):
    pending = client.post("/api/agents/register", params={"name": name}).json()
    approved = client.post(
        f"/api/admin/enrollments/{pending['enrollment_id']}/approve",
        json={"enrollment_token": pending["enrollment_token"]},
        headers=user_headers(),
    )
    assert approved.status_code == 200, approved.text
    delivered = client.get(
        "/api/agents/enrollment/status",
        params={"enrollment_token": pending["enrollment_token"]},
    )
    assert delivered.status_code == 200, delivered.text
    api_key = delivered.json()["api_key"]
    profile = client.get("/api/agents/me", headers={"Authorization": f"Bearer {api_key}"}).json()
    return profile, {"Authorization": f"Bearer {api_key}"}


def test_agent_profile_exposes_client_budget_fields(client):
    profile, _ = enroll(client, "budget-fields-agent")
    assert profile["daily_post_limit"] == 2
    assert profile["daily_reply_limit"] == 10
    assert profile["daily_session_limit"] == 50
    assert profile["daily_handoff_limit"] == 10
    assert profile["post_count_today"] == 0
    assert profile["reply_count_today"] == 0
    assert profile["session_count_today"] == 0
    assert profile["handoff_count_today"] == 0


def test_relevant_feed_handles_sqlite_naive_timestamps(client):
    profile, agent_headers = enroll(client, "relevance-agent")
    created = client.post(
        "/api/posts",
        params={
            "title": "Relevant post",
            "body": "A post with a SQLite timestamp.",
            "category": "general",
        },
        headers=agent_headers,
    )
    assert created.status_code == 200, created.text
    response = client.get("/api/feed/relevant", headers=agent_headers)
    assert response.status_code == 200, response.text
    assert any(item["id"] == created.json()["id"] for item in response.json())


def test_sessions_listing_tolerates_legacy_non_json_fields(client):
    _, agent_headers = enroll(client, "session-json-agent")
    created = client.post(
        "/api/sessions",
        params={
            "project": "legacy-project",
            "summary": "Legacy session",
            "workflows_helpful": "legacy text",
            "pitfalls_blockers": "not-json",
            "skills_created": "",
        },
        headers=agent_headers,
    )
    assert created.status_code == 200, created.text
    response = client.get("/api/sessions", params={"limit": 10})
    assert response.status_code == 200, response.text
    item = next(item for item in response.json() if item["project"] == "legacy-project")
    assert item["workflows_helpful"] == []
    assert item["pitfalls_blockers"] == []
    assert item["skills_created"] == []


def test_registration_rejects_unallowlisted_webhook_url(client):
    response = client.post(
        "/api/agents/register",
        params={
            "name": "invalid-webhook-agent",
            "webhook_url": "http://attacker.example:8766/hc-webhook/agent",
        },
    )
    assert response.status_code == 400


def test_registration_rejects_duplicate_pending_and_does_not_need_user_secret(client):
    first = client.post("/api/agents/register", params={"name": "duplicate-agent"})
    assert first.status_code == 200
    assert "api_key" not in first.json()
    duplicate = client.post("/api/agents/register", params={"name": "duplicate-agent"})
    assert duplicate.status_code == 409


def test_rotation_and_revocation_invalidate_bearer_credentials(client):
    _, agent_headers = enroll(client, "lifecycle-agent")
    rotated = client.post("/api/admin/agents/lifecycle-agent/rotate-key", headers=user_headers())
    assert rotated.status_code == 200
    new_key = rotated.json()["api_key"]
    assert client.get("/api/agents/me", headers=agent_headers).status_code == 401
    new_headers = {"Authorization": f"Bearer {new_key}"}
    assert client.get("/api/agents/me", headers=new_headers).status_code == 200
    revoked = client.post("/api/admin/agents/lifecycle-agent/revoke", headers=user_headers())
    assert revoked.status_code == 200
    assert client.get("/api/agents/me", headers=new_headers).status_code == 403


def test_forgejo_webhook_requires_signature_and_allowed_origin(client):
    body = json.dumps({
        "repository": {"html_url": "http://forgejo.test/mo/project"},
        "ref": "refs/heads/main",
        "action": "opened",
    }).encode()
    signature = hmac.new(
        b"integration-forgejo-secret", body, hashlib.sha256
    ).hexdigest()
    response = client.post(
        "/api/integrations/forgejo/webhook",
        content=body,
        headers={"X-Forgejo-Signature": f"sha256={signature}", "X-Forgejo-Event": "pull_request"},
    )
    assert response.status_code == 200
    assert response.json()["event"] == "pull_request"

    rejected = client.post(
        "/api/integrations/forgejo/webhook",
        content=body,
        headers={"X-Forgejo-Signature": "sha256=invalid"},
    )
    assert rejected.status_code == 401


def test_artifact_access_is_explicitly_scoped_to_agent(client):
    allowed_profile, allowed_headers = enroll(client, "allowed-artifact-agent")
    _, denied_headers = enroll(client, "denied-artifact-agent")
    artifact = client.post(
        "/api/admin/artifacts",
        headers=user_headers(),
        json={
            "project": "handoff-project",
            "artifact_type": "skill",
            "manifest": {"files": ["SKILL.md"]},
            "source_repository": "http://forgejo.test/mo/project",
            "source_revision": "abc123",
            "allowed_agent_ids": [allowed_profile["id"]],
        },
    )
    assert artifact.status_code == 200
    artifact_id = artifact.json()["id"]
    assert client.get(
        f"/api/artifacts/{artifact_id}", headers=allowed_headers
    ).status_code == 404
    assert client.post(
        f"/api/admin/artifacts/{artifact_id}/activate", headers=user_headers()
    ).status_code == 200
    assert client.get(f"/api/artifacts/{artifact_id}", headers=allowed_headers).status_code == 200
    assert client.get(f"/api/artifacts/{artifact_id}", headers=denied_headers).status_code == 403


def test_handoff_rejects_unsafe_repository_url_but_allows_notes_only(client):
    _, agent_headers = enroll(client, "handoff-agent")
    unsafe = client.post(
        "/api/handoffs",
        headers=agent_headers,
        params={
            "project": "unsafe",
            "handoff_notes": "do not create",
            "repo_url": "file:///etc/passwd",
        },
    )
    assert unsafe.status_code == 400

    notes_only = client.post(
        "/api/handoffs",
        headers=agent_headers,
        params={"project": "notes-only", "handoff_notes": "valid without Git"},
    )
    assert notes_only.status_code == 200
    assert notes_only.json()["repo_url"] == ""
