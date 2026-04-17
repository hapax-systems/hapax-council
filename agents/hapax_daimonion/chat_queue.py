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

Consent-safe: no author names stored (snapshot IPC strips ``author_id``
before write), no persistence to disk beyond an ephemeral snapshot
that is deleted on drain, no log-line with message contents beyond
debug. The queue is in-process only in each service; cross-service
handoff (chat-monitor → daimonion) uses the ``snapshot`` / ``drain``
file IPC (Continuous-Loop Research Cadence §3.3).
"""

from __future__ import annotations

import json
import logging
import os
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock

log = logging.getLogger(__name__)

DEFAULT_MAX_SIZE: int = 20

# Continuous-Loop Research Cadence §3.3 — cross-service IPC path.
# Producer (chat-monitor process) writes the snapshot on push; consumer
# (daimonion director-loop during `chat` activity) atomically reads +
# unlinks. The file holds up to DEFAULT_MAX_SIZE messages (FIFO-20).
SNAPSHOT_PATH = Path("/dev/shm/hapax-chat-queue-snapshot.json")


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


def snapshot_to_file(
    queue: ChatQueue,
    *,
    path: Path | None = None,
) -> None:
    """Atomically write the current queue contents to ``path`` for IPC.

    Strips ``author_id`` (consent-safe) and keeps only ``text`` + ``ts``.
    Atomic via tmp + ``os.replace`` so a reader never sees a torn JSON.
    Called by the producer (chat-monitor) after every push.
    """
    out_path = path or SNAPSHOT_PATH
    messages = queue.snapshot()
    payload = {
        "messages": [
            {"text": m.text, "ts": m.ts}
            for m in messages  # author_id stripped
        ],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, out_path)


def drain_from_file(
    *,
    path: Path | None = None,
) -> list[QueuedMessage]:
    """Atomically read + unlink the snapshot; return the messages.

    Consumer-side of the cross-service handoff. Unlink-on-read ensures
    the same batch is never consumed twice — a subsequent drain before
    the producer writes again returns ``[]``. Missing / malformed file
    also returns ``[]``.

    Called by the daimonion director-loop when ``chat`` activity is
    selected.
    """
    in_path = path or SNAPSHOT_PATH
    if not in_path.exists():
        return []
    try:
        text = in_path.read_text(encoding="utf-8")
    except OSError:
        log.debug("chat-queue snapshot read failed", exc_info=True)
        return []
    try:
        in_path.unlink()
    except OSError:
        log.debug("chat-queue snapshot unlink failed", exc_info=True)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        log.debug("chat-queue snapshot parse failed", exc_info=True)
        return []
    if not isinstance(data, dict):
        return []
    raw_messages = data.get("messages", [])
    if not isinstance(raw_messages, list):
        return []
    out: list[QueuedMessage] = []
    for entry in raw_messages:
        if not isinstance(entry, dict):
            continue
        text_v = entry.get("text")
        ts_v = entry.get("ts")
        if not isinstance(text_v, str):
            continue
        try:
            ts_f = float(ts_v) if ts_v is not None else 0.0
        except (TypeError, ValueError):
            ts_f = 0.0
        out.append(QueuedMessage(text=text_v, ts=ts_f))
    return out


# Alias — keeps asdict handy for callers who want a dict form.
_ = asdict

__all__ = [
    "ChatQueue",
    "DEFAULT_MAX_SIZE",
    "QueuedMessage",
    "SNAPSHOT_PATH",
    "drain_from_file",
    "snapshot_to_file",
]
