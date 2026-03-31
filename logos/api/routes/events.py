"""logos/api/routes/events.py — SSE stream of real-time flow events."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import asdict

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from logos.event_bus import EventBus

router = APIRouter(tags=["events"])

_bus: EventBus | None = None


def set_event_bus(bus: EventBus) -> None:
    global _bus
    _bus = bus


def get_event_bus() -> EventBus:
    if _bus is None:
        raise RuntimeError("EventBus not initialized")
    return _bus


async def _event_generator(bus: EventBus, request: Request) -> AsyncIterator[str]:
    sub = bus.subscribe()
    try:
        async for event in sub:
            if await request.is_disconnected():
                break
            yield json.dumps(asdict(event))
    finally:
        await sub.aclose()


@router.get("/events/stream")
async def event_stream(request: Request) -> EventSourceResponse:
    bus = get_event_bus()
    return EventSourceResponse(_event_generator(bus, request))
