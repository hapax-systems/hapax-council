"""Integration tests for SSE streaming API contract."""

from __future__ import annotations

import json
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient

from logos.api.app import app
from logos.query_dispatch import QueryResult


def _parse_sse_events(body: str) -> list[dict]:
    """Parse SSE event stream into a list of {event, data} dicts."""
    events = []
    current_event = "message"
    for line in body.split("\n"):
        if line.startswith("event: "):
            current_event = line[7:].strip()
        elif line.startswith("data: "):
            events.append({"event": current_event, "data": line[6:]})
            current_event = "message"
    return events


class TestSSEEventContract:
    @patch("logos.api.routes.query.run_query")
    @patch("logos.api.routes.query.classify_query", return_value="dev_story")
    async def test_event_sequence_status_text_done(self, mock_classify, mock_run):
        mock_run.return_value = QueryResult(
            markdown="## Results\nSome content",
            agent_type="dev_story",
            tokens_in=500,
            tokens_out=200,
            elapsed_ms=1000,
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/query/run", json={"query": "test query"})
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

        events = _parse_sse_events(resp.text)
        event_types = [e["event"] for e in events]
        assert "status" in event_types, "Missing status event"
        assert "text_delta" in event_types, "Missing text_delta event"
        assert "done" in event_types, "Missing done event"

        status_idx = event_types.index("status")
        text_idx = event_types.index("text_delta")
        done_idx = event_types.index("done")
        assert status_idx < text_idx < done_idx

    @patch("logos.api.routes.query.run_query")
    @patch("logos.api.routes.query.classify_query", return_value="dev_story")
    async def test_status_event_has_phase_and_agent(self, mock_classify, mock_run):
        mock_run.return_value = QueryResult(
            markdown="test",
            agent_type="dev_story",
            tokens_in=10,
            tokens_out=5,
            elapsed_ms=100,
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/query/run", json={"query": "test"})

        events = _parse_sse_events(resp.text)
        status_events = [e for e in events if e["event"] == "status"]
        assert len(status_events) >= 1
        data = json.loads(status_events[0]["data"])
        assert data["phase"] == "querying"
        assert data["agent"] == "dev_story"

    @patch("logos.api.routes.query.run_query")
    @patch("logos.api.routes.query.classify_query", return_value="dev_story")
    async def test_done_event_has_metadata(self, mock_classify, mock_run):
        mock_run.return_value = QueryResult(
            markdown="test",
            agent_type="dev_story",
            tokens_in=500,
            tokens_out=200,
            elapsed_ms=1234,
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/query/run", json={"query": "test"})

        events = _parse_sse_events(resp.text)
        done_events = [e for e in events if e["event"] == "done"]
        assert len(done_events) == 1
        data = json.loads(done_events[0]["data"])
        assert data["agent_used"] == "dev_story"
        assert data["tokens_in"] == 500
        assert data["tokens_out"] == 200
        assert data["elapsed_ms"] == 1234

    async def test_empty_query_rejected(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/query/run", json={"query": "  "})
        assert resp.status_code == 422

    @patch("logos.api.routes.query.run_query")
    @patch("logos.api.routes.query.classify_query", return_value="dev_story")
    async def test_empty_markdown_still_completes(self, mock_classify, mock_run):
        mock_run.return_value = QueryResult(
            markdown="",
            agent_type="dev_story",
            tokens_in=50,
            tokens_out=10,
            elapsed_ms=200,
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/query/run", json={"query": "empty test"})
        assert resp.status_code == 200
        assert "event: done" in resp.text
