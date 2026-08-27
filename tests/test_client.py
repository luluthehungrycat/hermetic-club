from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

_CLIENT_PATH = Path(__file__).parents[1] / "hermes-skill" / "scripts" / "client.py"
_CLIENT_SPEC = spec_from_file_location("hermetic_club_client", _CLIENT_PATH)
assert _CLIENT_SPEC and _CLIENT_SPEC.loader
client_module = module_from_spec(_CLIENT_SPEC)
_CLIENT_SPEC.loader.exec_module(client_module)


class TestClient:
    def _make_client(self) -> client_module.HermeticClubClient:
        with patch.object(
            client_module.HermeticClubClient,
            "_load_config",
            return_value={
                "club_url": "https://club.example:8443",
                "api_key": "hc_test",
                "agent_name": "test-agent",
            },
        ):
            return client_module.HermeticClubClient()

    def test_vote_post_sends_explicit_vote(self):
        client = self._make_client()
        response = Mock(status_code=200)
        response.json.return_value = {"id": "post-1", "upvotes": 1, "downvotes": 0}

        with patch.object(client_module.httpx, "post", return_value=response) as post:
            result = client.vote_post("post-1", 1)

        post.assert_called_once_with(
            "https://club.example:8443/api/posts/post-1/vote",
            headers={"Authorization": "Bearer hc_test"},
            params={"vote": 1},
            timeout=30,
        )
        assert result == {"id": "post-1", "upvotes": 1, "downvotes": 0}

    def test_vote_post_rejects_values_other_than_plus_or_minus_one(self):
        client = self._make_client()

        with pytest.raises(ValueError, match="vote must be 1 or -1"):
            client.vote_post("post-1", 0)

    def test_vote_post_does_not_create_a_replayable_draft_on_rate_limit(self, tmp_path: Path):
        client = self._make_client()
        response = Mock(status_code=429, text="rate limited")

        with (
            patch.object(client_module.httpx, "post", return_value=response),
            patch.object(client_module, "_DRAFTS_DIR", tmp_path),
            patch.object(client_module, "_set_sentinel") as set_sentinel,
        ):
            with pytest.raises(client_module.HermeticClubBudgetExhausted):
                client.vote_post("post-1", 1)

        set_sentinel.assert_called_once()
        assert list(tmp_path.iterdir()) == []
