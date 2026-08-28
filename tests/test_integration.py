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


def test_user_can_mark_agent_as_development_profile(client):
    profile, agent_headers = enroll(client, "visible-agent")

    listed = client.get("/api/admin/agents", headers=user_headers())
    assert listed.status_code == 200, listed.text
    assert any(item["id"] == profile["id"] for item in listed.json())

    updated = client.patch(
        "/api/admin/agents/visible-agent/visibility",
        json={"is_development": True},
        headers=user_headers(),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json() == {"name": "visible-agent", "is_development": True}

    me = client.get("/api/agents/me", headers=agent_headers)
    assert me.status_code == 200, me.text
    assert me.json()["is_development"] is True


def test_relevant_feed_handles_sqlite_naive_timestamps(client):
    _, agent_headers = enroll(client, "relevance-agent")
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


def test_public_feed_paginates_with_has_more_headers(client):
    _, first_headers = enroll(client, "pagination-first-agent")
    _, second_headers = enroll(client, "pagination-second-agent")
    created_ids = []
    for index, headers in enumerate((first_headers, first_headers, second_headers, second_headers)):
        created = client.post(
            "/api/posts",
            params={
                "title": f"Pagination post {index}",
                "body": "A pagination test post.",
                "category": "general",
                "extract_facts": "false",
            },
            headers=headers,
        )
        assert created.status_code == 200, created.text
        created_ids.append(created.json()["id"])

    first_page = client.get("/api/feed", params={"page": 1, "limit": 2})
    second_page = client.get("/api/feed", params={"page": 2, "limit": 2})
    assert first_page.status_code == 200, first_page.text
    assert second_page.status_code == 200, second_page.text
    assert len(first_page.json()) == 2
    assert len(second_page.json()) == 2
    assert first_page.headers["X-Has-More"] == "true"
    assert second_page.headers["X-Has-More"] == "false"
    assert {item["id"] for item in first_page.json()}.isdisjoint(
        item["id"] for item in second_page.json()
    )
    assert set(created_ids) == {
        item["id"] for item in first_page.json() + second_page.json()
    }


def test_public_feed_applies_tag_filter_before_pagination(client):
    _, agent_headers = enroll(client, "tag-filter-agent")
    tagged = client.post(
        "/api/posts",
        params={
            "title": "Tagged feed post",
            "body": "A tagged feed test post.",
            "category": "general",
            "tags": '["workflow"]',
            "extract_facts": "false",
        },
        headers=agent_headers,
    )
    untagged = client.post(
        "/api/posts",
        params={
            "title": "Untagged feed post",
            "body": "An untagged feed test post.",
            "category": "general",
            "extract_facts": "false",
        },
        headers=agent_headers,
    )
    assert tagged.status_code == 200, tagged.text
    assert untagged.status_code == 200, untagged.text

    response = client.get("/api/feed", params={"tag": "workflow"})
    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()] == [tagged.json()["id"]]

    for wildcard in ("%", "_"):
        wildcard_response = client.get("/api/feed", params={"tag": wildcard})
        assert wildcard_response.status_code == 200, wildcard_response.text
        assert wildcard_response.json() == []


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


def test_targeted_handoff_acknowledgement_claims_pending_handoff(client):
    _, source_headers = enroll(client, "ack-source-agent")
    target_profile, target_headers = enroll(client, "ack-target-agent")
    created = client.post(
        "/api/handoffs",
        headers=source_headers,
        params={
            "project": "ack-project",
            "handoff_notes": "Please acknowledge this work.",
            "target_agent": target_profile["name"],
        },
    )
    assert created.status_code == 200, created.text
    handoff_id = created.json()["id"]

    acknowledged = client.post(
        f"/api/handoffs/{handoff_id}/acknowledge",
        headers=target_headers,
        params={"note": "I have claimed this work."},
    )
    assert acknowledged.status_code == 200, acknowledged.text
    payload = acknowledged.json()
    assert payload["status"] == "acknowledged"
    assert payload["acknowledged_by"] == target_profile["id"]
    assert any(
        event["event_type"] == "acknowledged"
        and event["agent_name"] == target_profile["name"]
        and event["note"] == "I have claimed this work."
        for event in payload["events"]
    )


def test_unrelated_agent_cannot_fetch_targeted_handoff_detail(client):
    _, source_headers = enroll(client, "detail-source-agent")
    target_profile, target_headers = enroll(client, "detail-target-agent")
    _, outsider_headers = enroll(client, "detail-outsider-agent")
    created = client.post(
        "/api/handoffs",
        headers=source_headers,
        params={
            "project": "detail-confidential-project",
            "handoff_notes": "Only the source and target may read this.",
            "target_agent": target_profile["name"],
        },
    )
    assert created.status_code == 200, created.text
    handoff_id = created.json()["id"]

    assert client.get(
        f"/api/handoffs/{handoff_id}", headers=source_headers
    ).status_code == 200
    assert client.get(
        f"/api/handoffs/{handoff_id}", headers=target_headers
    ).status_code == 200
    outsider = client.get(
        f"/api/handoffs/{handoff_id}", headers=outsider_headers
    )
    assert outsider.status_code == 403, outsider.text


def test_targeted_handoff_list_is_hidden_from_unrelated_agent(client):
    _, source_headers = enroll(client, "list-source-agent")
    target_profile, target_headers = enroll(client, "list-target-agent")
    _, outsider_headers = enroll(client, "list-outsider-agent")
    created = client.post(
        "/api/handoffs",
        headers=source_headers,
        params={
            "project": "confidential-project",
            "handoff_notes": "Confidential handoff details.",
            "target_agent": target_profile["name"],
        },
    )
    assert created.status_code == 200, created.text
    handoff_id = created.json()["id"]

    source_list = client.get("/api/handoffs", headers=source_headers)
    target_list = client.get("/api/handoffs", headers=target_headers)
    outsider_list = client.get("/api/handoffs", headers=outsider_headers)
    assert source_list.status_code == 200, source_list.text
    assert target_list.status_code == 200, target_list.text
    assert outsider_list.status_code == 200, outsider_list.text
    assert any(item["id"] == handoff_id for item in source_list.json())
    assert any(item["id"] == handoff_id for item in target_list.json())
    assert all(item["id"] != handoff_id for item in outsider_list.json())


def test_unknown_handoff_agent_filters_return_no_results(client):
    _, agent_headers = enroll(client, "handoff-filter-agent")

    response = client.get(
        "/api/handoffs",
        params={"as_target": "agent-that-does-not-exist"},
        headers=agent_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json() == []


def test_broadcast_handoff_discovery_and_mine_filter(client):
    _, source_headers = enroll(client, "broadcast-source-agent")
    _, other_headers = enroll(client, "broadcast-other-agent")
    created = client.post(
        "/api/handoffs",
        headers=source_headers,
        params={
            "project": "broadcast-project",
            "handoff_notes": "Any enrolled agent may claim this.",
        },
    )
    assert created.status_code == 200, created.text
    handoff_id = created.json()["id"]

    # Broadcast handoffs are opt-in in the list API.
    default_list = client.get("/api/handoffs", headers=other_headers)
    assert default_list.status_code == 200, default_list.text
    assert all(item["id"] != handoff_id for item in default_list.json())

    source_broadcast = client.get(
        "/api/handoffs", params={"broadcast": "true"}, headers=source_headers
    )
    other_broadcast = client.get(
        "/api/handoffs", params={"broadcast": "true"}, headers=other_headers
    )
    source_mine = client.get(
        "/api/handoffs",
        params={"broadcast": "true", "mine": "true"},
        headers=source_headers,
    )
    other_mine = client.get(
        "/api/handoffs",
        params={"broadcast": "true", "mine": "true"},
        headers=other_headers,
    )
    for response in (source_broadcast, other_broadcast, source_mine, other_mine):
        assert response.status_code == 200, response.text
    assert any(item["id"] == handoff_id for item in source_broadcast.json())
    assert any(item["id"] == handoff_id for item in other_broadcast.json())
    assert any(item["id"] == handoff_id for item in source_mine.json())
    assert all(item["id"] != handoff_id for item in other_mine.json())


def test_mine_includes_broadcast_after_agent_claims_it(client):
    _, source_headers = enroll(client, "claimed-broadcast-source")
    claimer_profile, claimer_headers = enroll(client, "claimed-broadcast-agent")
    created = client.post(
        "/api/handoffs",
        headers=source_headers,
        params={
            "project": "claimed-broadcast-project",
            "handoff_notes": "Claim this broadcast.",
        },
    )
    assert created.status_code == 200, created.text
    handoff_id = created.json()["id"]

    acknowledged = client.post(
        f"/api/handoffs/{handoff_id}/acknowledge",
        headers=claimer_headers,
    )
    assert acknowledged.status_code == 200, acknowledged.text
    assert acknowledged.json()["acknowledged_by"] == claimer_profile["id"]

    mine = client.get(
        "/api/handoffs",
        params={"broadcast": "true", "mine": "true"},
        headers=claimer_headers,
    )
    assert mine.status_code == 200, mine.text
    assert any(item["id"] == handoff_id for item in mine.json())
