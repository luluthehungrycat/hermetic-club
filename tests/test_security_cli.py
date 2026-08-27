"""Unit tests for enrollment security and local CLI credential handling."""
import hashlib
import hmac
import stat

import pytest

from hermetic_club.cli import store_agent_key
from hermetic_club.services.security import (
    digest,
    forgejo_signature_valid,
    json_array,
    seal,
    unseal,
    valid_forgejo_origin,
)


def test_digest_is_stable_and_not_plaintext():
    value = "hc_enroll_test-token"
    assert digest(value) == hashlib.sha256(value.encode()).hexdigest()
    assert value not in digest(value)


def test_sealed_credential_requires_context():
    ciphertext = seal("hc_secret", "server-secret", "enrollment-token")
    assert ciphertext != "hc_secret"
    assert unseal(ciphertext, "server-secret", "enrollment-token") == "hc_secret"
    with pytest.raises(ValueError, match="invalid sealed credential"):
        unseal(ciphertext, "server-secret", "different-token")


def test_forgejo_signature_uses_constant_time_comparable_value():
    body = b'{"action":"opened"}'
    secret = "webhook-secret"
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert forgejo_signature_valid(body, f"sha256={signature}", secret)
    assert not forgejo_signature_valid(body, "sha256=bad", secret)
    assert not forgejo_signature_valid(body, signature, secret)


def test_forgejo_origin_allowlist_and_json_array():
    assert valid_forgejo_origin("https://forgejo.example/mo/repo", ["https://forgejo.example"])
    assert not valid_forgejo_origin("https://evil.example/mo/repo", ["https://forgejo.example"])
    assert not valid_forgejo_origin("file:///etc/passwd", ["https://forgejo.example"])
    assert json_array('["skill", "project"]') == '["skill", "project"]'


def test_cli_stores_profile_key_with_owner_only_permissions(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    path = store_agent_key("pi400-coder", "hc_first-key")
    assert path.read_text() == "HC_AGENT_PI400_CODER_API_KEY=hc_first-key\n"
    assert stat.S_IMODE(path.stat().st_mode) == stat.S_IRUSR | stat.S_IWUSR

    store_agent_key("pi400-coder", "hc_rotated-key")
    assert path.read_text() == "HC_AGENT_PI400_CODER_API_KEY=hc_rotated-key\n"
