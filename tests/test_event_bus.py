"""Tests for logos.event_bus — EventBus core with ring buffer and async subscriptions."""

from __future__ import annotations

import asyncio
import time

import pytest

from logos.event_bus import EventBus, FlowEvent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _event(
    kind: str = "shm.write",
    source: str = "agent-a",
    target: str = "agent-b",
    label: str = "test event",
    ts: float | None = None,
) -> FlowEvent:
    ev = FlowEvent(kind=kind, source=source, target=target, label=label)
    if ts is not None:
        ev.ts = ts
    return ev


# ---------------------------------------------------------------------------
# Basic emit + recent
# ---------------------------------------------------------------------------


def test_emit_and_recent_roundtrip() -> None:
    bus = EventBus()
    ev = _event(label="hello")
    bus.emit(ev)
    result = bus.recent()
    assert len(result) == 1
    assert result[0] is ev


def test_recent_returns_all_buffered() -> None:
    bus = EventBus()
    events = [_event(label=f"e{i}") for i in range(5)]
    for ev in events:
        bus.emit(ev)
    result = bus.recent()
    assert result == events


# ---------------------------------------------------------------------------
# Ring buffer overflow
# ---------------------------------------------------------------------------


def test_ring_buffer_overflow_drops_oldest() -> None:
    bus = EventBus(maxlen=3)
    events = [_event(label=f"e{i}") for i in range(5)]
    for ev in events:
        bus.emit(ev)
    result = bus.recent()
    assert len(result) == 3
    assert result == events[2:]  # oldest two dropped


def test_ring_buffer_maxlen_one() -> None:
    bus = EventBus(maxlen=1)
    ev1 = _event(label="first")
    ev2 = _event(label="second")
    bus.emit(ev1)
    bus.emit(ev2)
    result = bus.recent()
    assert len(result) == 1
    assert result[0] is ev2


# ---------------------------------------------------------------------------
# recent(since=) timestamp filtering
# ---------------------------------------------------------------------------


def test_recent_since_filters_old_events() -> None:
    bus = EventBus()
    now = time.time()
    old = _event(label="old", ts=now - 10.0)
    new = _event(label="new", ts=now + 1.0)
    bus.emit(old)
    bus.emit(new)

    result = bus.recent(since=now)
    assert result == [new]


def test_recent_since_returns_empty_when_all_old() -> None:
    bus = EventBus()
    now = time.time()
    bus.emit(_event(label="very old", ts=now - 100.0))
    assert bus.recent(since=now) == []


def test_recent_since_returns_all_when_none() -> None:
    bus = EventBus()
    for i in range(3):
        bus.emit(_event(label=f"e{i}"))
    assert len(bus.recent(since=None)) == 3


# ---------------------------------------------------------------------------
# Async subscriptions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscribe_receives_emitted_event() -> None:
    bus = EventBus()
    sub = bus.subscribe()
    ev = _event(label="async-test")

    bus.emit(ev)
    received = await asyncio.wait_for(sub.__anext__(), timeout=1.0)

    assert received is ev
    await sub.aclose()


@pytest.mark.asyncio
async def test_subscribe_receives_multiple_events_in_order() -> None:
    bus = EventBus()
    sub = bus.subscribe()
    events = [_event(label=f"e{i}") for i in range(4)]

    for ev in events:
        bus.emit(ev)

    received = []
    for _ in events:
        received.append(await asyncio.wait_for(sub.__anext__(), timeout=1.0))

    assert received == events
    await sub.aclose()


@pytest.mark.asyncio
async def test_aclose_removes_subscription() -> None:
    bus = EventBus()
    sub = bus.subscribe()
    assert sub in bus._subscribers

    await sub.aclose()
    assert sub not in bus._subscribers


@pytest.mark.asyncio
async def test_aclose_idempotent() -> None:
    bus = EventBus()
    sub = bus.subscribe()
    await sub.aclose()
    await sub.aclose()  # should not raise


@pytest.mark.asyncio
async def test_multiple_subscribers_all_receive() -> None:
    bus = EventBus()
    sub1 = bus.subscribe()
    sub2 = bus.subscribe()
    ev = _event(label="fan-out")

    bus.emit(ev)

    r1 = await asyncio.wait_for(sub1.__anext__(), timeout=1.0)
    r2 = await asyncio.wait_for(sub2.__anext__(), timeout=1.0)
    assert r1 is ev
    assert r2 is ev

    await sub1.aclose()
    await sub2.aclose()


@pytest.mark.asyncio
async def test_subscriber_queue_full_drops_silently() -> None:
    """When subscriber queue is full, emit must not raise."""
    bus = EventBus()
    # maxsize=1 so second emit overflows
    sub = bus.subscribe(maxsize=1)

    bus.emit(_event(label="first"))
    bus.emit(_event(label="overflow — should be dropped silently"))

    # First event is still readable; no exception was raised
    received = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert received.label == "first"
    await sub.aclose()


@pytest.mark.asyncio
async def test_subscribe_async_iteration() -> None:
    """EventBus subscription works as an async for target."""
    bus = EventBus()
    sub = bus.subscribe()
    events = [_event(label=f"iter-{i}") for i in range(3)]

    # Emit on a slight delay so the async for loop has events to consume
    async def _emit() -> None:
        for ev in events:
            bus.emit(ev)
            await asyncio.sleep(0)

    asyncio.create_task(_emit())

    received: list[FlowEvent] = []
    async for ev in sub:
        received.append(ev)
        if len(received) == len(events):
            break

    await sub.aclose()
    assert received == events


# ---------------------------------------------------------------------------
# SSE endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sse_generator_emits_events() -> None:
    """The SSE generator yields events from the bus as JSON."""
    import json
    from unittest.mock import AsyncMock

    from logos.api.routes.events import _event_generator, set_event_bus

    bus = EventBus(maxlen=10)
    set_event_bus(bus)

    # Mock request that never disconnects
    mock_request = AsyncMock()
    mock_request.is_disconnected.return_value = False

    gen = _event_generator(bus, mock_request)

    # Schedule emit after a tick so sub is registered
    async def _emit() -> None:
        await asyncio.sleep(0.01)
        bus.emit(FlowEvent(kind="shm.write", source="a", target="b", label="test"))

    asyncio.create_task(_emit())

    payload = await asyncio.wait_for(gen.__anext__(), timeout=2.0)
    data = json.loads(payload)
    assert data["kind"] == "shm.write"
    assert data["source"] == "a"
    await gen.aclose()
