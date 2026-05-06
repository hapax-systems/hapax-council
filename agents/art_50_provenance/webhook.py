"""HMAC/replay helpers for the future Article 50 issue webhook."""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass, field

SIGNATURE_VERSION = "v1"
DEFAULT_REPLAY_WINDOW_S = 300
DEFAULT_IDEMPOTENCY_TTL_S = 86_400


class Art50WebhookError(ValueError):
    """Raised when a webhook request fails authentication or replay checks."""


def render_signature_header(*, secret: str, timestamp_s: int, body: bytes) -> str:
    """Render the canonical timestamped HMAC-SHA256 signature header."""

    signed = f"{timestamp_s}.".encode() + body
    digest = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp_s},{SIGNATURE_VERSION}={digest}"


def _parse_signature_header(header: str) -> tuple[int, str]:
    parts = {}
    for raw_part in header.split(","):
        key, sep, value = raw_part.partition("=")
        if sep:
            parts[key.strip()] = value.strip()
    if "t" not in parts or SIGNATURE_VERSION not in parts:
        raise Art50WebhookError("missing timestamped HMAC signature parts")
    try:
        timestamp_s = int(parts["t"])
    except ValueError as exc:
        raise Art50WebhookError("invalid HMAC timestamp") from exc
    return timestamp_s, parts[SIGNATURE_VERSION]


def verify_signature_header(
    *,
    secret: str,
    header: str,
    body: bytes,
    now_s: int | None = None,
    replay_window_s: int = DEFAULT_REPLAY_WINDOW_S,
) -> int:
    """Verify HMAC-SHA256 and the 300-second default replay window."""

    if not secret:
        raise Art50WebhookError("webhook secret is not configured")
    now = int(time.time()) if now_s is None else now_s
    timestamp_s, candidate = _parse_signature_header(header)
    if abs(now - timestamp_s) > replay_window_s:
        raise Art50WebhookError("webhook timestamp outside replay window")
    expected = render_signature_header(secret=secret, timestamp_s=timestamp_s, body=body)
    _, expected_digest = _parse_signature_header(expected)
    if not hmac.compare_digest(expected_digest, candidate):
        raise Art50WebhookError("HMAC SHA-256 signature mismatch")
    return timestamp_s


@dataclass
class MemoryIdempotencyStore:
    """Small in-memory 24h idempotency helper for tests and single-process MVP."""

    ttl_s: int = DEFAULT_IDEMPOTENCY_TTL_S
    _seen: dict[str, int] = field(default_factory=dict)

    def accept_once(self, delivery_id: str, *, now_s: int | None = None) -> bool:
        now = int(time.time()) if now_s is None else now_s
        expired = [key for key, first_seen in self._seen.items() if now - first_seen > self.ttl_s]
        for key in expired:
            self._seen.pop(key, None)
        if delivery_id in self._seen:
            return False
        self._seen[delivery_id] = now
        return True


__all__ = [
    "DEFAULT_IDEMPOTENCY_TTL_S",
    "DEFAULT_REPLAY_WINDOW_S",
    "SIGNATURE_VERSION",
    "Art50WebhookError",
    "MemoryIdempotencyStore",
    "render_signature_header",
    "verify_signature_header",
]
