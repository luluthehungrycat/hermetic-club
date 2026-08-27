"""Shared policy for posts intentionally created by automated smoke tests."""

from __future__ import annotations

NOREPLY_TEST_TAG = "noreply_test"


def is_noreply_test(tags: list[str] | None) -> bool:
    """Return whether a post is explicitly marked as non-conversational test data."""
    return NOREPLY_TEST_TAG in (tags or [])
