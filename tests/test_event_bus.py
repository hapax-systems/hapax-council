"""Tests for logos.event_bus — EventBus core with ring buffer and async subscriptions."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

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


# ---------------------------------------------------------------------------
# Task 3: FlowObserver emits shm.write events on mtime change
# ---------------------------------------------------------------------------


def test_flow_observer_emits_shm_write_on_mtime_change(tmp_path: Path) -> None:
    """FlowObserver emits shm.write events when a watched file's mtime changes."""
    from logos.api.flow_observer import FlowObserver

    bus = EventBus()
    shm_root = tmp_path / "shm"
    agent_dir = shm_root / "hapax-stimmung"
    agent_dir.mkdir(parents=True)
    state_file = agent_dir / "state.json"
    state_file.write_text("{}")

    observer = FlowObserver(shm_root=shm_root, event_bus=bus)
    observer.register_reader("perception", str(state_file))

    # First scan — populates prev_mtimes, no events yet
    observer.scan()
    assert len(bus.recent()) == 0

    # Touch the file to change mtime
    import os

    orig_mtime = state_file.stat().st_mtime
    os.utime(state_file, (orig_mtime + 1, orig_mtime + 1))

    # Second scan — mtime changed, should emit
    observer.scan()
    events = bus.recent()
    assert len(events) == 1
    assert events[0].kind == "shm.write"
    assert events[0].source == "stimmung"
    assert events[0].target == "perception"


def test_flow_observer_no_event_without_bus(tmp_path: Path) -> None:
    """FlowObserver works without event_bus (no crash, no events)."""
    from logos.api.flow_observer import FlowObserver

    shm_root = tmp_path / "shm"
    agent_dir = shm_root / "hapax-test"
    agent_dir.mkdir(parents=True)
    (agent_dir / "data.json").write_text("{}")

    observer = FlowObserver(shm_root=shm_root)  # no event_bus
    observer.scan()
    observer.scan()  # should not crash


# ---------------------------------------------------------------------------
# Task 4: ReactiveEngine._agent_from_path
# ---------------------------------------------------------------------------


def test_agent_from_path_shm_path() -> None:
    """_agent_from_path extracts agent name from SHM paths."""
    from logos.engine import ReactiveEngine

    assert ReactiveEngine._agent_from_path("/dev/shm/hapax-stimmung/state.json") == "stimmung"
    assert ReactiveEngine._agent_from_path("/dev/shm/hapax-temporal/bands.json") == "temporal"


def test_agent_from_path_no_hapax_prefix() -> None:
    """_agent_from_path falls back to stem when no hapax- prefix."""
    from logos.engine import ReactiveEngine

    assert ReactiveEngine._agent_from_path("/tmp/some/file.json") == "file"


# ---------------------------------------------------------------------------
# Task 5: Pi handler emits pi.detection events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pi_handler_emits_detection_event() -> None:
    """Pi IR detection handler emits pi.detection event on success."""
    from pathlib import Path as _Path
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    bus = EventBus()

    # Build a minimal FastAPI app with the pi router
    from fastapi import FastAPI

    from logos.api.routes.pi import router

    test_app = FastAPI()
    test_app.state.event_bus = bus
    test_app.include_router(router)

    with (
        patch("logos.api.routes.pi.IR_STATE_DIR", _Path("/tmp/test-ir-state")),
        patch("logos.api.routes.pi._last_post_time", {}),
    ):
        _Path("/tmp/test-ir-state").mkdir(parents=True, exist_ok=True)
        client = TestClient(test_app)
        resp = client.post(
            "/api/pi/desk/ir",
            json={
                "pi": "hapax-pi1",
                "role": "desk",
                "ts": "2026-03-31T12:00:00",
                "persons": [],
                "hands": [],
                "screens": [],
                "inference_ms": 50,
            },
        )
        assert resp.status_code == 200

    events = bus.recent()
    pi_events = [e for e in events if e.kind == "pi.detection"]
    assert len(pi_events) == 1
    assert pi_events[0].source == "pi-desk"
    assert pi_events[0].target == "perception"
