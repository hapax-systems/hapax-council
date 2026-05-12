"""Are.na Publisher subclass for public-event and artifact fanout."""

from __future__ import annotations

import logging
from typing import ClassVar

from agents.publication_bus.publisher_kit import (
    Publisher,
    PublisherPayload,
    PublisherResult,
)
from agents.publication_bus.publisher_kit.allowlist import (
    AllowlistGate,
    load_allowlist,
)

log = logging.getLogger(__name__)

ARENA_SURFACE = "arena-post"

DEFAULT_ARENA_ALLOWLIST: AllowlistGate = load_allowlist(
    ARENA_SURFACE,
    permitted=["hapax"],
)


class ArenaPublisher(Publisher):
    """Publish a single block to an operator-owned Are.na channel."""

    surface_name: ClassVar[str] = ARENA_SURFACE
    allowlist: ClassVar[AllowlistGate] = DEFAULT_ARENA_ALLOWLIST
    requires_legal_name: ClassVar[bool] = False

    def __init__(
        self,
        *,
        token: str | None,
        channel_slug: str | None,
        client_factory=None,
    ) -> None:
        self.token = token or ""
        self.channel_slug = channel_slug or ""
        self._client_factory = client_factory or _default_client_factory
        self._client = None

    def _emit(self, payload: PublisherPayload) -> PublisherResult:
        if not (self.token and self.channel_slug):
            return PublisherResult(refused=True, detail="missing Are.na credentials")

        source_url = payload.metadata.get("source_url")
        source = source_url if isinstance(source_url, str) and source_url else None
        try:
            self._ensure_client().add_block(
                self.channel_slug,
                content=payload.text,
                source=source,
            )
        except Exception:  # noqa: BLE001
            log.warning("Are.na add_block raised", exc_info=True)
            return PublisherResult(error=True, detail="add_block_error")

        return PublisherResult(ok=True, detail=f"channel:{self.channel_slug}")

    def _ensure_client(self):
        if self._client is None:
            self._client = self._client_factory(self.token)
        return self._client


class _ArenaAdapter:
    """Minimal Are.na adapter wrapping the ``arena`` Python client."""

    def __init__(self, token: str) -> None:
        from arena import Arena

        self._arena = Arena(access_token=token)

    def add_block(
        self,
        channel_slug: str,
        *,
        content: str,
        source: str | None = None,
    ) -> None:
        channel = self._arena.channels.channel(channel_slug)
        if source:
            channel.add_block(source=source, content=content)
        else:
            channel.add_block(content=content)


def _default_client_factory(token: str) -> _ArenaAdapter:
    """Lazy-build an Are.na adapter."""
    return _ArenaAdapter(token)


__all__ = [
    "ARENA_SURFACE",
    "ArenaPublisher",
    "DEFAULT_ARENA_ALLOWLIST",
]
