"""Security helpers for enrollment and repository integration."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from urllib.parse import urlparse


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def seal(value: str, secret: str, context: str) -> str:
    """Encrypt and authenticate a short-lived value.

    The ciphertext is useless without both the server secret and the pending
    enrollment token. The HMAC also makes wrong-context attempts fail closed.
    """
    key = hmac.new(secret.encode(), context.encode(), hashlib.sha256).digest()
    raw = value.encode()
    stream = hashlib.sha512(key + context.encode()).digest()
    encrypted = bytes(b ^ stream[i % len(stream)] for i, b in enumerate(raw))
    tag = hmac.new(secret.encode(), context.encode() + encrypted, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(encrypted + tag).decode()


def unseal(ciphertext: str, secret: str, context: str) -> str:
    key = hmac.new(secret.encode(), context.encode(), hashlib.sha256).digest()
    stream = hashlib.sha512(key + context.encode()).digest()
    packed = base64.urlsafe_b64decode(ciphertext.encode())
    if len(packed) < hashlib.sha256().digest_size:
        raise ValueError("invalid sealed credential")
    encrypted, tag = packed[:-hashlib.sha256().digest_size], packed[-hashlib.sha256().digest_size:]
    expected = hmac.new(secret.encode(), context.encode() + encrypted, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        raise ValueError("invalid sealed credential context")
    raw = bytes(b ^ stream[i % len(stream)] for i, b in enumerate(encrypted))
    return raw.decode()


def valid_webhook_url(value: str, allowed_hosts: list[str] | set[str]) -> bool:
    """Accept only HTTP(S) callback URLs on explicitly allowed hosts."""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    hosts = {host.strip().lower() for host in allowed_hosts if host.strip()}
    return bool(hosts) and parsed.hostname.lower() in hosts


def valid_forgejo_origin(value: str, allowed_origins: list[str]) -> bool:
    """Accept only configured HTTP(S) Forgejo origins, never arbitrary URLs."""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    return bool(allowed_origins) and any(
        origin == item.rstrip("/") for item in allowed_origins
    )


def forgejo_signature_valid(body: bytes, signature: str, secret: str) -> bool:
    if not secret or not signature.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature.removeprefix("sha256="), expected)


def json_array(value: str | list[str] | None) -> str:
    if value is None:
        return "[]"
    if isinstance(value, list):
        return json.dumps(value)
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        raise TypeError("expected JSON array")
    return json.dumps(parsed)
