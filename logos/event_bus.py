"""logos/event_bus.py — In-process async event bus for flow visualization."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field

__all__ = ["EventBus", "FlowEvent", "emit_llm_call", "set_global_bus"]


@dataclass
class FlowEvent:
    """A single observable system event for flow visualization."""

    kind: str  # shm.write | engine.rule | engine.action | llm.call | qdrant.op | pi.detection
    source: str
    target: str
    label: str
    duration_ms: float | None = None
    ts: float = field(default_factory=time.time)


class EventBus:
    """Bounded ring buffer with async fan-out to SSE subscribers."""

    def __init__(self, maxlen: int = 500) -> None:
        self._ring: deque[FlowEvent] = deque(maxlen=maxlen)
        self._subscribers: list[asyncio.Queue[FlowEvent]] = []

    def emit(self, event: FlowEvent) -> None:
        self._ring.append(event)
        for q in self._subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def recent(self, since: float | None = None) -> list[FlowEvent]:
        if since is None:
            return list(self._ring)
        return [e for e in self._ring if e.ts >= since]

    def subscribe(self) -> _Subscription:
        q: asyncio.Queue[FlowEvent] = asyncio.Queue(maxsize=50)
        self._subscribers.append(q)
        return _Subscription(q, self._subscribers)


class _Subscription:
    def __init__(
        self,
        queue: asyncio.Queue[FlowEvent],
        subscribers: list[asyncio.Queue[FlowEvent]],
    ) -> None:
        self._queue = queue
        self._subscribers = subscribers

    def __aiter__(self):
        return self

    async def __anext__(self) -> FlowEvent:
        try:
            return await self._queue.get()
        except asyncio.CancelledError:
            self._cleanup()
            raise

    def _cleanup(self) -> None:
        try:
            self._subscribers.remove(self._queue)
        except ValueError:
            pass

    async def aclose(self) -> None:
        self._cleanup()


# Global bus for non-request code paths (LLM calls, etc.)
_global_bus: EventBus | None = None


def set_global_bus(bus: EventBus) -> None:
    global _global_bus
    _global_bus = bus


def emit_llm_call(agent_name: str, model: str, duration_ms: float | None = None) -> None:
    if _global_bus is not None:
        _global_bus.emit(
            FlowEvent(
                kind="llm.call",
                source=agent_name,
                target="llm",
                label=model,
                duration_ms=duration_ms,
            )
        )
