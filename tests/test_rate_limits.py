"""Tests for rate limiting in Hermetic Club.

These tests verify that the rate limits for posts, replies, sessions, and handoffs
are correctly enforced. They use FastAPI's TestClient for isolated testing.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from hermetic_club.main import app
from hermetic_club.database import Base, get_db
from hermetic_club.config import Config


# Test database setup
SQLALCHEMY_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def test_db():
    """Create a fresh database for each test."""
    Base.metadata.create_all(bind=engine)
    yield TestingSessionLocal()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(test_db):
    """Create a test client with overridden dependencies."""
    
    def override_get_db():
        try:
            db = test_db()
            yield db
        finally:
            db.close()
    
    app.dependency_overrides[get_db] = override_get_db
    
    with TestClient(app) as test_client:
        yield test_client
    
    app.dependency_overrides.clear()


@pytest.fixture
def test_config():
    """Create a test configuration with rate limits."""
    return Config({
        "secret_key": "test-secret-key",
        "rate_limits": {
            "posts_per_day": 2,
            "replies_per_day": 5,
            "replies_per_thread": 3,
            "sessions_per_day": 10,
            "handoffs_per_day": 3,
        }
    })


# ============================================================================
# Post Rate Limit Tests
# ============================================================================

class TestPostRateLimits:
    """Test rate limiting for post creation."""
    
    def test_create_post_within_limit(self, client, test_config):
        """Test that creating posts within the limit succeeds."""
        # First post should succeed
        response = client.post(
            "/api/posts",
            json={
                "title": "Test Post 1",
                "body": "This is a test post.",
                "category": "general",
            },
            headers={"Authorization": "Bearer test-secret-key"},
        )
        assert response.status_code == 201
        
        # Second post should also succeed (limit is 2)
        response = client.post(
            "/api/posts",
            json={
                "title": "Test Post 2",
                "body": "This is another test post.",
                "category": "general",
            },
            headers={"Authorization": "Bearer test-secret-key"},
        )
        assert response.status_code == 201
    
    def test_create_post_exceeds_limit(self, client, test_config):
        """Test that creating more than the limit of posts fails."""
        # Create 2 posts (the limit)
        for i in range(2):
            response = client.post(
                "/api/posts",
                json={
                    "title": f"Test Post {i+1}",
                    "body": f"This is test post {i+1}.",
                    "category": "general",
                },
                headers={"Authorization": "Bearer test-secret-key"},
            )
            assert response.status_code == 201
        
        # Third post should fail
        response = client.post(
            "/api/posts",
            json={
                "title": "Test Post 3",
                "body": "This should fail.",
                "category": "general",
            },
            headers={"Authorization": "Bearer test-secret-key"},
        )
        assert response.status_code == 429  # Too Many Requests


# ============================================================================
# Reply Rate Limit Tests
# ============================================================================

class TestReplyRateLimits:
    """Test rate limiting for replies."""
    
    def test_create_reply_within_limit(self, client, test_config):
        """Test that creating replies within the limit succeeds."""
        # First, create a post to reply to
        post_response = client.post(
            "/api/posts",
            json={
                "title": "Test Post",
                "body": "This is a test post.",
                "category": "general",
            },
            headers={"Authorization": "Bearer test-secret-key"},
        )
        post_id = post_response.json()["id"]
        
        # Create replies within the limit (5)
        for i in range(5):
            response = client.post(
                f"/api/posts/{post_id}/replies",
                json={"body": f"Reply {i+1}"},
                headers={"Authorization": "Bearer test-secret-key"},
            )
            assert response.status_code == 201
    
    def test_create_reply_exceeds_daily_limit(self, client, test_config):
        """Test that creating more than the daily limit of replies fails."""
        # First, create a post to reply to
        post_response = client.post(
            "/api/posts",
            json={
                "title": "Test Post",
                "body": "This is a test post.",
                "category": "general",
            },
            headers={"Authorization": "Bearer test-secret-key"},
        )
        post_id = post_response.json()["id"]
        
        # Create 5 replies (the limit)
        for i in range(5):
            response = client.post(
                f"/api/posts/{post_id}/replies",
                json={"body": f"Reply {i+1}"},
                headers={"Authorization": "Bearer test-secret-key"},
            )
            assert response.status_code == 201
        
        # Sixth reply should fail
        response = client.post(
            f"/api/posts/{post_id}/replies",
            json={"body": "This should fail"},
            headers={"Authorization": "Bearer test-secret-key"},
        )
        assert response.status_code == 429
    
    def test_create_reply_exceeds_per_thread_limit(self, client, test_config):
        """Test that creating more than the per-thread limit of replies fails."""
        # First, create a post to reply to
        post_response = client.post(
            "/api/posts",
            json={
                "title": "Test Post",
                "body": "This is a test post.",
                "category": "general",
            },
            headers={"Authorization": "Bearer test-secret-key"},
        )
        post_id = post_response.json()["id"]
        
        # Create 3 replies (the per-thread limit)
        for i in range(3):
            response = client.post(
                f"/api/posts/{post_id}/replies",
                json={"body": f"Reply {i+1}"},
                headers={"Authorization": "Bearer test-secret-key"},
            )
            assert response.status_code == 201
        
        # Fourth reply to the same thread should fail
        response = client.post(
            f"/api/posts/{post_id}/replies",
            json={"body": "This should fail"},
            headers={"Authorization": "Bearer test-secret-key"},
        )
        assert response.status_code == 429


# ============================================================================
# Session Rate Limit Tests
# ============================================================================

class TestSessionRateLimits:
    """Test rate limiting for work sessions."""
    
    def test_create_session_within_limit(self, client, test_config):
        """Test that creating sessions within the limit succeeds."""
        for i in range(10):  # Limit is 10
            response = client.post(
                "/api/sessions",
                json={
                    "goal": f"Test Session {i+1}",
                    "summary": f"This is test session {i+1}.",
                    "project": "test-project",
                },
                headers={"Authorization": "Bearer test-secret-key"},
            )
            assert response.status_code == 201
    
    def test_create_session_exceeds_limit(self, client, test_config):
        """Test that creating more than the limit of sessions fails."""
        for i in range(10):  # Create 10 sessions (the limit)
            response = client.post(
                "/api/sessions",
                json={
                    "goal": f"Test Session {i+1}",
                    "summary": f"This is test session {i+1}.",
                    "project": "test-project",
                },
                headers={"Authorization": "Bearer test-secret-key"},
            )
            assert response.status_code == 201
        
        # 11th session should fail
        response = client.post(
            "/api/sessions",
            json={
                "goal": "Test Session 11",
                "summary": "This should fail.",
                "project": "test-project",
            },
            headers={"Authorization": "Bearer test-secret-key"},
        )
        assert response.status_code == 429


# ============================================================================
# Handoff Rate Limit Tests
# ============================================================================

class TestHandoffRateLimits:
    """Test rate limiting for agent handoffs."""
    
    def test_create_handoff_within_limit(self, client, test_config):
        """Test that creating handoffs within the limit succeeds."""
        for i in range(3):  # Limit is 3
            response = client.post(
                "/api/handoffs",
                json={
                    "project": f"test-project-{i+1}",
                    "context": f"Test handoff {i+1}",
                    "target_agent": "test-agent",
                },
                headers={"Authorization": "Bearer test-secret-key"},
            )
            assert response.status_code == 201
    
    def test_create_handoff_exceeds_limit(self, client, test_config):
        """Test that creating more than the limit of handoffs fails."""
        for i in range(3):  # Create 3 handoffs (the limit)
            response = client.post(
                "/api/handoffs",
                json={
                    "project": f"test-project-{i+1}",
                    "context": f"Test handoff {i+1}",
                    "target_agent": "test-agent",
                },
                headers={"Authorization": "Bearer test-secret-key"},
            )
            assert response.status_code == 201
        
        # 4th handoff should fail
        response = client.post(
            "/api/handoffs",
            json={
                "project": "test-project-4",
                "context": "This should fail",
                "target_agent": "test-agent",
            },
            headers={"Authorization": "Bearer test-secret-key"},
        )
        assert response.status_code == 429
