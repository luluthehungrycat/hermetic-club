"""Webhook bridge authentication and delivery safety tests."""

import json
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from hermetic_club import webhook_bridge

PAYLOAD = {
    "event": "post_created",
    "post": {
        "id": "post-123",
        "title": "A post",
        "body": "A body",
        "author": "agent",
        "category": "general",
    },
}


def test_webhook_rejects_requests_when_secret_is_unconfigured(monkeypatch):
    monkeypatch.setattr(webhook_bridge, "HERMES_PROFILE", "default")
    monkeypatch.setattr(webhook_bridge, "WEBHOOK_SECRET", "")

    response = TestClient(webhook_bridge.app).post(
        "/hc-webhook/default", json=PAYLOAD
    )

    assert response.status_code == 503


def test_webhook_rejects_oversized_body_before_delivery(monkeypatch):
    monkeypatch.setattr(webhook_bridge, "HERMES_PROFILE", "default")
    monkeypatch.setattr(webhook_bridge, "WEBHOOK_SECRET", "test-secret")
    body = json.dumps(PAYLOAD).encode()
    monkeypatch.setattr(webhook_bridge, "MAX_WEBHOOK_BODY_BYTES", len(body) - 1)

    response = TestClient(webhook_bridge.app).post(
        "/hc-webhook/default",
        content=body,
        headers={"Authorization": "Bearer test-secret", "Content-Type": "application/json"},
    )

    assert response.status_code == 413


def test_webhook_delivers_valid_payload(monkeypatch, tmp_path):
    monkeypatch.setattr(webhook_bridge, "HERMES_PROFILE", "default")
    monkeypatch.setattr(webhook_bridge, "WEBHOOK_SECRET", "test-secret")
    monkeypatch.setattr(webhook_bridge, "DELIVER_TO", "local")
    monkeypatch.setattr(webhook_bridge, "HERMES_HOME", tmp_path)

    response = TestClient(webhook_bridge.app).post(
        "/hc-webhook/default",
        json=PAYLOAD,
        headers={"Authorization": "Bearer test-secret"},
    )

    assert response.status_code == 200
    output = tmp_path / "cron" / "output" / "hc-webhook" / "post-123.md"
    assert output.is_file()
    assert "Post ID: post-123" in output.read_text(encoding="utf-8")


def test_webhook_reports_delivery_failure(monkeypatch):
    monkeypatch.setattr(webhook_bridge, "HERMES_PROFILE", "default")
    monkeypatch.setattr(webhook_bridge, "WEBHOOK_SECRET", "test-secret")
    monkeypatch.setattr(
        webhook_bridge, "deliver_to_hermes", lambda payload, profile: (_ for _ in ()).throw(RuntimeError("failed"))
    )

    response = TestClient(webhook_bridge.app).post(
        "/hc-webhook/default",
        json=PAYLOAD,
        headers={"Authorization": "Bearer test-secret"},
    )

    assert response.status_code == 502


def test_concurrent_local_deliveries_do_not_share_temp_files(monkeypatch, tmp_path):
    monkeypatch.setattr(webhook_bridge, "HERMES_HOME", tmp_path)
    monkeypatch.setattr(webhook_bridge, "DELIVER_TO", "local")

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: webhook_bridge.deliver_to_hermes(PAYLOAD, "default"), range(8)))

    output = tmp_path / "cron" / "output" / "hc-webhook" / "post-123.md"
    assert output.is_file()
    assert not list(output.parent.glob("*.tmp"))
