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
    valid_webhook_url,
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
    assert not valid_forgejo_origin("https://forgejo.example/mo/repo", [])
    assert not valid_forgejo_origin("file:///etc/passwd", ["https://forgejo.example"])
    assert valid_webhook_url("http://100.77.74.22:8766/hc-webhook/pi", ["100.77.74.22"])
    assert not valid_webhook_url("http://attacker.example/hc-webhook/pi", ["100.77.74.22"])
    assert not valid_webhook_url("http://100.77.74.22:8766/hc-webhook/pi", [])
    assert json_array('["skill", "project"]') == '["skill", "project"]'


def test_privileged_auth_fails_closed_without_server_secret(monkeypatch):
    from hermetic_club.config import Config
    from hermetic_club.routes.admin import verify_user
    from hermetic_club.routes.user import _check_user_auth

    monkeypatch.setattr(Config, "load", lambda: Config({"secret_key": ""}))
    with pytest.raises(Exception) as admin_error:
        import asyncio
        asyncio.run(verify_user(""))
    assert getattr(admin_error.value, "status_code", None) == 503

    with pytest.raises(Exception) as user_error:
        _check_user_auth("")
    assert getattr(user_error.value, "status_code", None) == 503


def test_cli_stores_profile_key_with_owner_only_permissions(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    path = store_agent_key("pi400-coder", "hc_first-key")
    assert path.read_text() == "HC_AGENT_PI400_CODER_API_KEY=hc_first-key\n"
    assert stat.S_IMODE(path.stat().st_mode) == stat.S_IRUSR | stat.S_IWUSR

    store_agent_key("pi400-coder", "hc_rotated-key")
    assert path.read_text() == "HC_AGENT_PI400_CODER_API_KEY=hc_rotated-key\n"
