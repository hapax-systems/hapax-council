"""LRR Phase 9 §3.5 — async-first chat queue.

Chat messages land in two places:

1. **Real-time path** (``agents.studio_compositor.chat_reactor``): existing
   keyword-match + cooldown pipeline. Unchanged. A preset switch fires
   the moment a viewer says a preset name, independent of this queue.
2. **Async queue** (this module): a FIFO-20 buffer that Hapax inspects
   *only when the director-loop selects `chat`* as the active activity.
   Messages older than 20 pending are evicted oldest-first.

This protects the ``executive_function`` axiom: Hapax does not
context-switch to every chat message individually. Instead it reviews
the last 20 messages holistically when it has decided chat is what
should be happening right now.

Consent-safe: no author names stored, no persistence to disk, no
log-line with message contents beyond debug. The queue is in-process
only; a daimonion restart loses whatever was unread.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from threading import Lock

log = logging.getLogger(__name__)

DEFAULT_MAX_SIZE: int = 20


@dataclass(frozen=True)
class QueuedMessage:
    """A single queued chat message — author_id is hashed / stripped by caller."""

    text: str
    ts: float  # epoch seconds
    author_id: str = ""  # optional, for dedup only; never logged


class ChatQueue:
    """FIFO queue of up to ``max_size`` chat messages.

    Thread-safe via an internal ``Lock`` — chat-monitor threads push,
    director-loop reads during ``chat`` activity selection.
    """

    def __init__(self, max_size: int = DEFAULT_MAX_SIZE) -> None:
        if max_size <= 0:
            raise ValueError("chat queue max_size must be positive")
        self._max_size = max_size
        self._queue: deque[QueuedMessage] = deque(maxlen=max_size)
        self._lock = Lock()
        self._total_seen: int = 0  # diagnostic

    @property
    def max_size(self) -> int:
        return self._max_size

    def push(self, message: QueuedMessage) -> None:
        """Append a message; oldest is evicted when full (deque semantics)."""
        with self._lock:
            self._queue.append(message)
            self._total_seen += 1

    def __len__(self) -> int:
        with self._lock:
            return len(self._queue)

    def snapshot(self) -> list[QueuedMessage]:
        """Return the current queue contents (oldest → newest) without draining."""
        with self._lock:
            return list(self._queue)

    def drain(self) -> list[QueuedMessage]:
        """Return the current messages AND clear the queue atomically.

        Director-loop calls this when ``chat`` activity is selected and a
        response batch is about to be composed; the drained messages are
        the batch's input.
        """
        with self._lock:
            messages = list(self._queue)
            self._queue.clear()
            return messages

    def peek_oldest(self) -> QueuedMessage | None:
        with self._lock:
            return self._queue[0] if self._queue else None

    def peek_newest(self) -> QueuedMessage | None:
        with self._lock:
            return self._queue[-1] if self._queue else None

    @property
    def total_seen(self) -> int:
        """Lifetime count of pushes — diagnostic, never gated on."""
        with self._lock:
            return self._total_seen


__all__ = ["ChatQueue", "QueuedMessage", "DEFAULT_MAX_SIZE"]
