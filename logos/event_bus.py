"""logos/event_bus.py — Ring-buffer event bus with async subscriptions.

FlowEvent is a lightweight dataclass emitted whenever data flows between
nodes in the hapax system (SHM writes, engine rule firings, LLM calls,
Qdrant ops, Pi fleet events, etc.).  Subscribers receive events via async
generator; the ring buffer keeps recent events for late-joining consumers.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class FlowEvent:
    """A single observable event in the hapax data flow graph."""

    kind: str  # e.g. "shm.write", "engine.rule", "llm.call", "qdrant.op"
    source: str  # originating node / agent name
    target: str  # destination node / agent name (may equal source)
    label: str = ""  # human-readable description
    ts: float = field(default_factory=time.time)
    meta: dict = field(default_factory=dict)


class _AsyncSubscription:
    """Async generator that yields FlowEvents from a bounded queue."""

    def __init__(self, bus: EventBus, maxsize: int) -> None:
        self._bus = bus
        self._queue: asyncio.Queue[FlowEvent] = asyncio.Queue(maxsize=maxsize)
        self._closed = False

    def _put_nowait(self, event: FlowEvent) -> None:
        """Called by EventBus.emit — non-blocking, drops on full."""
        if self._closed:
            return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            pass  # drop silently

    def __aiter__(self) -> _AsyncSubscription:
        return self

    async def __anext__(self) -> FlowEvent:
        if self._closed:
            raise StopAsyncIteration
        return await self._queue.get()

    async def aclose(self) -> None:
        if not self._closed:
            self._closed = True
            self._bus._remove_subscriber(self)


class EventBus:
    """Central pub-sub bus for hapax flow events.

    Parameters
    ----------
    maxlen:
        Ring buffer capacity.  Oldest events are dropped when full.
    """

    def __init__(self, maxlen: int = 1000) -> None:
        self._buffer: deque[FlowEvent] = deque(maxlen=maxlen)
        self._subscribers: list[_AsyncSubscription] = []

    def emit(self, event: FlowEvent) -> None:
        """Publish an event to all subscribers and append to ring buffer."""
        self._buffer.append(event)
        for sub in list(self._subscribers):
            sub._put_nowait(event)

    def recent(self, since: float | None = None) -> list[FlowEvent]:
        """Return buffered events, optionally filtered by timestamp."""
        events = list(self._buffer)
        if since is None:
            return events
        return [e for e in events if e.ts > since]

    def subscribe(self, maxsize: int = 256) -> _AsyncSubscription:
        """Create and register a new async subscription."""
        sub = _AsyncSubscription(self, maxsize=maxsize)
        self._subscribers.append(sub)
        return sub

    def _remove_subscriber(self, sub: _AsyncSubscription) -> None:
        try:
            self._subscribers.remove(sub)
        except ValueError:
            pass
