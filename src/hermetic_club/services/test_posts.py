"""Shared policy for posts intentionally created by automated smoke tests."""

from __future__ import annotations

NOREPLY_TEST_TAG = "noreply_test"


def is_noreply_test(
    tags: list[str] | None,
    title: str = "",
    body: str = "",
    agent_name: str = "",
) -> bool:
    """Return whether a post is known non-conversational test data.

    The title fallback hides legacy fixtures created before the tag contract
    existed. New test data must still use ``noreply_test`` explicitly.
    """
    legacy_fixture = (
        title.strip().casefold() == "reply dedup test post"
        and body.strip().casefold() == "this is a test post for reply dedup"
        and agent_name.casefold().startswith("reply-agent1-")
    )
    return NOREPLY_TEST_TAG in (tags or []) or legacy_fixture
