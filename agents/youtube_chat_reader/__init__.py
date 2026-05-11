"""YouTube live-chat reader.

Owner: epsilon (cc-task ``youtube-chat-ingestion-impingement``). Ships
the concrete poller (``ChatReader``) plus the reverse-channel contract
(``YoutubeChatReader`` Protocol + module-level registry) that the
chat-poster lane (cc-task ``chat-response-verbal-and-text``) consumes.

The Protocol-only surface here was designed to let the poster lane
wire to the reader before the implementation existed; the reader now
ships and ``register_reader()`` is wired in ``__main__.py`` at daemon
startup, so the poster's ``get_active_reader()`` lookup resolves once
the daemon is up.

Integration contract (read by ``response_dispatch.py``):

* The reader's ``live_chat_id()`` is the YouTube Data API
  ``liveChatId`` (the ID returned by ``liveBroadcasts.list`` under
  ``snippet.liveChatId``, or ``videos.list`` with
  ``part=liveStreamingDetails`` -> ``activeLiveChatId``). The
  poster needs this ID for the ``liveChatMessages.insert`` POST
  target — it is the only routing identifier the YouTube API
  exposes for posting into a stream's chat.
* ``recent_messages()`` is for the chat-state surface and is not
  consumed by the poster.

Invariants of the concrete implementation:

* **Consent-first.** Author identifiers never land on disk in
  plaintext. ``anonymize.AuthorAnonymizer`` derives a per-process
  HMAC key fresh on daemon start so accumulation across livestream
  sessions is impossible without an explicit consent contract
  (axiom ``interpersonal_transparency``).
* **Quota-disciplined.** Honours the response's
  ``pollingIntervalMillis`` and uses
  :class:`shared.youtube_rate_limiter.QuotaBucket` for daily budget.
  When no broadcast is live the daemon idles at 60s checks (no
  ``liveChatMessages.list`` call), so quota is only consumed during
  active streams.
* **Sanitized.** Message text is length-capped, control-stripped,
  URL-stripped, and Unicode-normalised before any downstream
  consumer (impingement bus, chat-state surface, LLM) sees it.

Shared OAuth credential path: this reader and the poster both use
``shared.google_auth.get_google_credentials()``. The reader uses the
readonly scope; the poster uses ``youtube.force-ssl``.
``google-auth`` handles refresh transparently across both lanes when
a single token covers both scopes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from agents.youtube_chat_reader.reader import ChatReader


class YoutubeChatReaderUnavailable(RuntimeError):
    """Raised when a registered reader cannot satisfy a query.

    Concrete reader (epsilon) raises this when no broadcast is active
    and ``live_chat_id()`` cannot be resolved.
    """


@dataclass(frozen=True)
class ChatMessageSnapshot:
    """One chat message — author hash, text, sentiment, length, timestamp.

    Mirrors the impingement adapter's per-message metadata
    (``youtube-chat-ingestion-impingement`` cc-task §2). Author IDs
    arrive hashed per the interpersonal_transparency axiom.
    """

    author_hash: str
    text: str
    sentiment: float
    length: int
    posted_at_unix: float


class YoutubeChatReader(Protocol):
    """Reverse-channel reader contract.

    Implemented by epsilon's concrete agent at module-load time. The
    poster lane reads ``live_chat_id()`` for the POST target.
    """

    def live_chat_id(self) -> str:
        """The active stream's YouTube ``liveChatId``.

        Raises ``YoutubeChatReaderUnavailable`` when no broadcast is
        active. Concrete reader caches per-broadcast.
        """

    def recent_messages(self, *, limit: int = 50) -> list[ChatMessageSnapshot]:
        """Last ``limit`` chat messages — for compositor + dashboards."""


def get_active_reader() -> YoutubeChatReader | None:
    """Return the currently-registered reader, or ``None`` if none.

    Concrete reader (epsilon) calls ``register_reader()`` at daemon
    startup; until then this returns ``None`` and the poster lane
    silently skips chat-post emission. The verbal modality is
    unaffected.
    """
    return _ACTIVE_READER


def register_reader(reader: YoutubeChatReader) -> None:
    """Register the active reader. Idempotent; last-write wins."""
    global _ACTIVE_READER
    _ACTIVE_READER = reader


def clear_reader() -> None:
    """Clear the registry. Used by tests."""
    global _ACTIVE_READER
    _ACTIVE_READER = None


_ACTIVE_READER: YoutubeChatReader | None = None


def __getattr__(name: str) -> object:
    """Lazy optional-dependency boundary for the concrete reader.

    Lightweight submodules such as ``anonymize`` are imported by
    compositor code that does not need the YouTube Data API client.
    Import ``reader`` only when callers explicitly request
    ``ChatReader``.
    """
    if name == "ChatReader":
        from agents.youtube_chat_reader.reader import ChatReader

        return ChatReader
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ChatMessageSnapshot",
    "ChatReader",
    "YoutubeChatReader",
    "YoutubeChatReaderUnavailable",
    "clear_reader",
    "get_active_reader",
    "register_reader",
]
