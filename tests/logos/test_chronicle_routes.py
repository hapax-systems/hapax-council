"""tests/logos/test_chronicle_routes.py — Tests for chronicle API endpoints."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from logos.api.routes.chronicle import router
from shared.chronicle import ChronicleEvent, record


def _app():
    app = FastAPI()
    app.include_router(router)
    return app


def _make_event(source: str, event_type: str, ts: float | None = None) -> ChronicleEvent:
    return ChronicleEvent(
        ts=ts if ts is not None else time.time(),
        trace_id="a" * 32,
        span_id="b" * 16,
        parent_span_id=None,
        source=source,
        event_type=event_type,
        payload={"key": "value"},
    )


def test_chronicle_query_returns_events(tmp_path):
    event_file = tmp_path / "events.jsonl"
    ev = _make_event("engine", "rule.fired")
    record(ev, path=event_file)

    with patch("logos.api.routes.chronicle.CHRONICLE_FILE", event_file):
        client = TestClient(_app())
        resp = client.get("/api/chronicle", params={"since": "-1h"})

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["source"] == "engine"
    assert data[0]["event_type"] == "rule.fired"


def test_chronicle_query_empty(tmp_path):
    nonexistent = tmp_path / "no_such_file.jsonl"

    with patch("logos.api.routes.chronicle.CHRONICLE_FILE", nonexistent):
        client = TestClient(_app())
        resp = client.get("/api/chronicle", params={"since": "-1h"})

    assert resp.status_code == 200
    assert resp.json() == []


def test_chronicle_query_filters_source(tmp_path):
    event_file = tmp_path / "events.jsonl"
    record(_make_event("engine", "rule.fired"), path=event_file)
    record(_make_event("stimmung", "snapshot"), path=event_file)

    with patch("logos.api.routes.chronicle.CHRONICLE_FILE", event_file):
        client = TestClient(_app())
        resp = client.get("/api/chronicle", params={"since": "-1h", "source": "stimmung"})

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["source"] == "stimmung"


def test_narrate_returns_narrative(tmp_path):
    event_file = tmp_path / "events.jsonl"
    record(_make_event("visual", "technique.activated"), path=event_file)

    mock_agent = MagicMock()
    mock_result = MagicMock()
    mock_result.output = "The reaction-diffusion technique activated."
    mock_agent.run_sync = MagicMock(return_value=mock_result)

    with (
        patch("logos.api.routes.chronicle.CHRONICLE_FILE", event_file),
        patch("logos.api.routes.chronicle._get_narration_agent", return_value=mock_agent),
    ):
        client = TestClient(_app())
        resp = client.get(
            "/api/chronicle/narrate",
            params={"since": "-1h", "question": "What happened with the visual system?"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["narrative"] == "The reaction-diffusion technique activated."
    assert data["event_count"] == 1


def test_narrate_requires_question(tmp_path):
    event_file = tmp_path / "events.jsonl"

    with patch("logos.api.routes.chronicle.CHRONICLE_FILE", event_file):
        client = TestClient(_app())
        resp = client.get("/api/chronicle/narrate", params={"since": "-1h"})

    assert resp.status_code == 422
