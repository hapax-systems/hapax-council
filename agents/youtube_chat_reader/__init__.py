"""YouTube live-chat reader — interface stub.

Owner: epsilon (cc-task ``youtube-chat-ingestion-impingement``).
This module ships a Protocol-only stub so the chat-poster lane
(cc-task ``chat-response-verbal-and-text``) can wire to it without
blocking on epsilon's implementation. When epsilon lands the real
reader, the Protocol below is the contract their concrete class
must satisfy; no further integration changes are required on the
poster side.

Integration contract (read by ``response_dispatch.py``):

* The reader's ``live_chat_id()`` is the YouTube Data API
  ``liveChatId`` (the ID returned by ``liveBroadcasts.list`` under
  ``snippet.liveChatId``, or ``videos.list`` with
  ``part=liveStreamingDetails`` -> ``activeLiveChatId``). The
  poster needs this ID for the ``liveChatMessages.insert`` POST
  target — it is the only routing identifier the YouTube API
  exposes for posting into a stream's chat.
* ``recent_messages()`` is for the chat-state surface and is not
  consumed by this PR.

The stub leaves no concrete instance registered. The poster lane
uses ``get_active_reader()`` and treats a ``None`` return as "no
reader available — chat post path inactive".

Shared OAuth credential path: epsilon's reader and this poster both
use ``shared.google_auth.get_google_credentials()``. The reader
typically requests the readonly scope; the poster requests
``youtube.force-ssl``. ``google-auth`` handles refresh transparently
across both lanes when a single token covers both scopes (operator
can mint once with both scopes).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


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

    Concrete reader (epsilon) calls ``register_reader()`` at startup;
    until then this returns ``None`` and the poster lane silently
    skips chat-post emission. The verbal modality is unaffected.
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


__all__ = [
    "ChatMessageSnapshot",
    "YoutubeChatReader",
    "YoutubeChatReaderUnavailable",
    "clear_reader",
    "get_active_reader",
    "register_reader",
]
