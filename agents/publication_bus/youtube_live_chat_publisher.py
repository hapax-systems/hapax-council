"""YouTube Live Chat poster (V5 publication-bus publisher).

POSTs ``liveChatMessages.insert`` to publish a textMessageEvent into
the operator's active livestream chat. Subclass of the V5
:class:`Publisher` ABC, so the three load-bearing invariants are
inherited from the base ``publish()`` method:

1. AllowlistGate — only operator-curated ``liveChatId``s permitted
2. Legal-name-leak guard — ``requires_legal_name = False``; chat
   replies are signed via the operator-referent picker
3. Prometheus counter — per-result outcome under
   ``hapax_publication_bus_publishes_total{surface="youtube-live-chat-message"}``

A per-chat-id :class:`LiveChatRateLimiter` is the fourth guard,
specific to this surface (not part of the V5 invariants because
allowlist alone does not constrain emission cadence).

Auth: ``shared.google_auth.get_google_credentials([youtube.force-ssl])``
matches the existing youtube_telemetry pattern. The operator must
mint a token with the ``youtube.force-ssl`` scope (write access to
their own channel) — ``google-auth`` handles refresh transparently
once the refresh token is in place.

Error semantics (per Gemini Jr packet
``youtube-live-api-chat-ingestion-and-post-2026``):

* HTTP 429 — generic too-many-requests; classified as ``error=True``.
* HTTP 403 with ``rateLimitExceeded`` reason — YouTube-specific
  rapid-insert rate limit; classified as ``error=True`` (NOT
  ``refused=True`` because we expect to retry next window).
* Other 4xx/5xx — ``error=True``; transport-level failures bubble up
  here too. The publish path never raises.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

import yaml

from agents.publication_bus.publisher_kit.allowlist import (
    AllowlistGate,
    load_allowlist,
)
from agents.publication_bus.publisher_kit.base import (
    Publisher,
    PublisherPayload,
    PublisherResult,
)

log = logging.getLogger(__name__)

YOUTUBE_LIVE_CHAT_SURFACE: str = "youtube-live-chat-message"
"""Stable surface name for AllowlistGate + Prometheus labels."""

YOUTUBE_FORCE_SSL_SCOPE: str = "https://www.googleapis.com/auth/youtube.force-ssl"
"""OAuth scope required for liveChatMessages.insert."""

DEFAULT_MIN_INTERVAL_S: float = 5.0
"""Default rate-limit window per liveChatId."""

DEFAULT_ALLOWLIST_ENV: str = "HAPAX_YOUTUBE_LIVE_CHAT_ALLOWLIST"
"""Env var pointing at a YAML allowlist file with a ``permitted``
list of liveChatIds. Empty allowlist = chat path inactive."""

DEFAULT_ALLOWLIST_PATH: Path = Path("config/publication-bus/youtube-live-chat.yaml")
"""Repo-checked allowlist fallback when the env override is unset."""


@dataclass
class LiveChatRateLimiter:
    """Per-liveChatId minimum-interval rate limiter.

    Default 5s window per chat thread (operator-tunable via
    constructor). Thread-safe via a single ``threading.Lock``; the
    last-permitted timestamp per chat id is stored in a small dict
    that grows with the number of distinct chat threads (in practice
    one per active broadcast).
    """

    min_interval_s: float = DEFAULT_MIN_INTERVAL_S
    clock: Callable[[], float] = field(default_factory=lambda: time.monotonic)
    _last_permitted: dict[str, float] = field(default_factory=dict, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def acquire(self, chat_id: str) -> bool:
        """Return ``True`` iff a post is permitted now for ``chat_id``."""
        if self.min_interval_s <= 0.0:
            return True
        now = self.clock()
        with self._lock:
            last = self._last_permitted.get(chat_id)
            if last is not None and now - last < self.min_interval_s:
                return False
            self._last_permitted[chat_id] = now
            return True


def load_default_allowlist() -> AllowlistGate:
    """Load the YouTube live-chat allowlist from env or repo config.

    Empty allowlist (file missing or empty list) yields a gate that
    permits nothing — the chat path is inactive until the operator
    populates the file with their broadcast's liveChatId.
    """
    env_path = os.environ.get(DEFAULT_ALLOWLIST_ENV)
    candidate = Path(env_path) if env_path else DEFAULT_ALLOWLIST_PATH
    permitted: list[str] = []
    if candidate.is_file():
        try:
            data = yaml.safe_load(candidate.read_text()) or {}
            if isinstance(data, dict):
                raw = data.get("permitted") or []
                if isinstance(raw, list):
                    permitted = [str(x) for x in raw if isinstance(x, str)]
        except (yaml.YAMLError, OSError) as exc:
            log.warning("youtube-live-chat allowlist load failed (%s): %s", candidate, exc)
    return load_allowlist(YOUTUBE_LIVE_CHAT_SURFACE, permitted)


class YoutubeLiveChatPublisher(Publisher):
    """Publishes a chat message into a YouTube live broadcast.

    ``payload.target`` is the ``liveChatId`` (allowlist match key).
    ``payload.text`` is the message body (max 200 chars per YouTube
    API; the chat-task's <140 char short-response window stays well
    under that ceiling).
    """

    surface_name: ClassVar[str] = YOUTUBE_LIVE_CHAT_SURFACE
    allowlist: ClassVar[AllowlistGate] = load_allowlist(YOUTUBE_LIVE_CHAT_SURFACE, [])
    requires_legal_name: ClassVar[bool] = False

    def __init__(
        self,
        *,
        service_factory: Callable[[], Any] | None = None,
        allowlist: AllowlistGate | None = None,
        rate_limiter: LiveChatRateLimiter | None = None,
    ) -> None:
        if allowlist is not None:
            self.allowlist = allowlist  # type: ignore[misc]
        self._service_factory = service_factory or self._build_service
        self._service: Any | None = None
        self._rate_limiter = rate_limiter or LiveChatRateLimiter()

    @staticmethod
    def _build_service() -> Any:
        from googleapiclient.discovery import build

        from shared.google_auth import get_google_credentials

        creds = get_google_credentials([YOUTUBE_FORCE_SSL_SCOPE])
        if creds is None:
            raise RuntimeError(
                "no google credentials available for youtube.force-ssl — operator must mint "
                "a token with that scope before chat posting can work"
            )
        return build("youtube", "v3", credentials=creds, cache_discovery=False)

    def _ensure_service(self) -> Any:
        if self._service is None:
            self._service = self._service_factory()
        return self._service

    def _emit(self, payload: PublisherPayload) -> PublisherResult:
        if not self._rate_limiter.acquire(payload.target):
            return PublisherResult(
                error=True,
                detail=f"rate-limit window not elapsed for {payload.target}",
            )
        try:
            service = self._ensure_service()
        except RuntimeError as exc:
            return PublisherResult(error=True, detail=f"service init failed: {exc}")

        body = {
            "snippet": {
                "liveChatId": payload.target,
                "type": "textMessageEvent",
                "textMessageDetails": {"messageText": payload.text},
            }
        }
        try:
            request = service.liveChatMessages().insert(part="snippet", body=body)
            request.execute()
        except Exception as exc:  # noqa: BLE001 — googleapiclient.errors.HttpError + transport
            status = getattr(getattr(exc, "resp", None), "status", None)
            log.warning("youtube live-chat insert failed (status=%s): %s", status, exc)
            detail = f"insert failed: status={status} {exc.__class__.__name__}"
            return PublisherResult(error=True, detail=detail)
        return PublisherResult(ok=True, detail="liveChatMessages.insert ok")


__all__ = [
    "DEFAULT_ALLOWLIST_ENV",
    "DEFAULT_ALLOWLIST_PATH",
    "DEFAULT_MIN_INTERVAL_S",
    "LiveChatRateLimiter",
    "YOUTUBE_FORCE_SSL_SCOPE",
    "YOUTUBE_LIVE_CHAT_SURFACE",
    "YoutubeLiveChatPublisher",
    "load_default_allowlist",
]
