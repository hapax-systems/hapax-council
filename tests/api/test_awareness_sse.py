"""Tests for the /api/awareness/stream SSE endpoint.

The generator is structured so the test can drive it without a real
event loop / network: ``_awareness_sse_generator`` accepts
``state_path``, ``iter_limit``, and ``sleep_fn`` for deterministic
exercising. Connection plumbing (sse-starlette response, FastAPI
route) is covered by the route-registration smoke; the event-sequence
correctness lives in the pure generator tests.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agents.operator_awareness.state import AwarenessState, write_state_atomic
from logos.api.routes.awareness import _awareness_sse_generator


def _write_state(path: Path, *, ttl_seconds: int = 300) -> None:
    state = AwarenessState(timestamp=datetime.now(UTC), ttl_seconds=ttl_seconds)
    write_state_atomic(state, path)


async def _drive(gen) -> list[dict[str, str]]:
    return [ev async for ev in gen]


# ── Generator: event sequence ───────────────────────────────────────


@pytest.mark.asyncio
async def test_emits_state_on_first_observation(tmp_path: Path):
    """First mtime observation always fires a ``state`` event so the
    subscriber renders immediately rather than waiting for a change."""
    path = tmp_path / "state.json"
    _write_state(path)

    async def fake_sleep(_: float) -> None:
        pass

    events = await _drive(
        _awareness_sse_generator(
            public=False,
            state_path=path,
            iter_limit=1,
            sleep_fn=fake_sleep,
        )
    )
    assert len(events) == 1
    assert events[0]["event"] == "state"
    body = json.loads(events[0]["data"])
    assert body["schema_version"] == 1


@pytest.mark.asyncio
async def test_no_state_emit_when_unchanged(tmp_path: Path):
    """No mtime change → no state event on subsequent iterations
    (heartbeat disabled in this test)."""
    path = tmp_path / "state.json"
    _write_state(path)

    async def fake_sleep(_: float) -> None:
        pass

    events = await _drive(
        _awareness_sse_generator(
            public=False,
            state_path=path,
            iter_limit=5,
            sleep_fn=fake_sleep,
            heartbeat_interval_s=1000.0,
        )
    )
    assert sum(1 for e in events if e["event"] == "state") == 1


@pytest.mark.asyncio
async def test_emits_state_on_mtime_change(tmp_path: Path):
    """Re-stamp mtime mid-stream → second ``state`` event."""
    path = tmp_path / "state.json"
    _write_state(path)

    bumped = False

    async def fake_sleep(_: float) -> None:
        nonlocal bumped
        if not bumped:
            later = time.time() + 10
            os.utime(path, (later, later))
            bumped = True

    events = await _drive(
        _awareness_sse_generator(
            public=False,
            state_path=path,
            iter_limit=4,
            sleep_fn=fake_sleep,
            heartbeat_interval_s=1000.0,
        )
    )
    state_events = [e for e in events if e["event"] == "state"]
    assert len(state_events) == 2


@pytest.mark.asyncio
async def test_emits_stale_event_when_past_ttl(tmp_path: Path):
    """File age > ttl_seconds → ``stale`` follows ``state``."""
    path = tmp_path / "state.json"
    _write_state(path, ttl_seconds=1)
    old = time.time() - 30
    os.utime(path, (old, old))

    async def fake_sleep(_: float) -> None:
        pass

    events = await _drive(
        _awareness_sse_generator(
            public=False,
            state_path=path,
            iter_limit=1,
            sleep_fn=fake_sleep,
        )
    )
    assert events[0]["event"] == "state"
    assert events[1]["event"] == "stale"
    body = json.loads(events[1]["data"])
    assert body["age_s"] >= 1


@pytest.mark.asyncio
async def test_emits_heartbeat_when_no_change(tmp_path: Path):
    """Heartbeat interval 0s → every iteration after first state
    emits a heartbeat (no mtime change)."""
    path = tmp_path / "state.json"
    _write_state(path)

    async def fake_sleep(_: float) -> None:
        pass

    events = await _drive(
        _awareness_sse_generator(
            public=False,
            state_path=path,
            iter_limit=4,
            sleep_fn=fake_sleep,
            heartbeat_interval_s=0.0,
        )
    )
    types = [e["event"] for e in events]
    assert types[0] == "state"
    assert "heartbeat" in types[1:]


@pytest.mark.asyncio
async def test_missing_file_yields_no_events_short_run(tmp_path: Path):
    """Absent file + no heartbeat-due → no events, generator polls."""
    path = tmp_path / "absent.json"

    async def fake_sleep(_: float) -> None:
        pass

    events = await _drive(
        _awareness_sse_generator(
            public=False,
            state_path=path,
            iter_limit=3,
            sleep_fn=fake_sleep,
            heartbeat_interval_s=10000.0,
        )
    )
    assert events == []


@pytest.mark.asyncio
async def test_public_filter_applied_when_public_true(tmp_path: Path):
    """``public=True`` runs the payload through public_filter."""
    path = tmp_path / "state.json"
    _write_state(path)

    async def fake_sleep(_: float) -> None:
        pass

    events = await _drive(
        _awareness_sse_generator(
            public=True,
            state_path=path,
            iter_limit=1,
            sleep_fn=fake_sleep,
        )
    )
    body = json.loads(events[0]["data"])
    assert body["schema_version"] == 1
    assert "refusals_recent" in body


# ── Route registration ──────────────────────────────────────────────


def test_sse_route_registered_under_awareness_path():
    """``/api/awareness/stream`` is GET-only — adding SSE doesn't
    introduce mutation siblings."""
    from logos.api.routes.awareness import router

    routes = {r.path: getattr(r, "methods", set()) for r in router.routes}
    assert "/api/awareness/stream" in routes
    assert routes["/api/awareness/stream"] == {"GET"}
