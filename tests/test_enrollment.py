"""Isolated tests for the User-approved enrollment lifecycle."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from hermetic_club.config import Config
from hermetic_club.main import app


def test_enrollment_approval_delivers_key_once():
    with TemporaryDirectory() as temp_dir:
        cfg = Config({
            "secret_key": "test-user-secret",
            "database_url": f"sqlite+aiosqlite:///{Path(temp_dir) / 'club.db'}",
        })
        with patch.object(Config, "load", return_value=cfg), TestClient(app) as client:
            user_headers = {"Authorization": "Bearer test-user-secret"}
            pending = client.post(
                "/api/agents/register",
                params={"name": "test-enrollment", "profile": "default"},
            )
            assert pending.status_code == 200
            data = pending.json()
            assert data["status"] == "pending"
            assert "api_key" not in data

            approved = client.post(
                f"/api/admin/enrollments/{data['enrollment_id']}/approve",
                json={"enrollment_token": data["enrollment_token"]},
                headers=user_headers,
            )
            assert approved.status_code == 200

            delivered = client.get(
                "/api/agents/enrollment/status",
                params={"enrollment_token": data["enrollment_token"]},
            )
            assert delivered.status_code == 200
            api_key = delivered.json()["api_key"]
            assert api_key.startswith("hc_")

            replay = client.get(
                "/api/agents/enrollment/status",
                params={"enrollment_token": data["enrollment_token"]},
            )
            assert "api_key" not in replay.json()
            assert client.get(
                "/api/agents/me",
                headers={"Authorization": f"Bearer {api_key}"},
            ).status_code == 200


def test_enrollment_rejection_and_admin_auth():
    with TemporaryDirectory() as temp_dir:
        cfg = Config({
            "secret_key": "test-user-secret",
            "database_url": f"sqlite+aiosqlite:///{Path(temp_dir) / 'club.db'}",
        })
        with patch.object(Config, "load", return_value=cfg), TestClient(app) as client:
            pending = client.post("/api/agents/register", params={"name": "reject-me"}).json()
            assert client.get("/api/admin/enrollments").status_code == 401
            rejected = client.post(
                f"/api/admin/enrollments/{pending['enrollment_id']}/reject",
                headers={"Authorization": "Bearer test-user-secret"},
            )
            assert rejected.status_code == 200
            status = client.get(
                "/api/agents/enrollment/status",
                params={"enrollment_token": pending["enrollment_token"]},
            )
            assert status.json()["status"] == "rejected"
