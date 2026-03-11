"""Tests for query API route — SSE streaming, refinement, agent listing."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from cockpit.query_dispatch import QueryAgentInfo, QueryResult


@pytest.fixture
async def client():
    from cockpit.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestQueryAgentsList:
    @patch("cockpit.api.routes.query.get_agent_list")
    async def test_list_agents(self, mock_list, client):
        mock_list.return_value = [
            QueryAgentInfo(
                agent_type="dev_story",
                name="Development Archaeology",
                description="Query development history",
            )
        ]
        resp = await client.get("/api/query/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["agent_type"] == "dev_story"


class TestQueryRun:
    @patch("cockpit.api.routes.query.run_query")
    @patch("cockpit.api.routes.query.classify_query")
    async def test_run_returns_sse_stream(self, mock_classify, mock_run, client):
        mock_classify.return_value = "dev_story"
        mock_run.return_value = QueryResult(
            markdown="## Hello\nWorld",
            agent_type="dev_story",
            tokens_in=100,
            tokens_out=50,
            elapsed_ms=1234,
        )
        resp = await client.post(
            "/api/query/run",
            json={"query": "tell me the story"},
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

    @patch("cockpit.api.routes.query.run_query")
    @patch("cockpit.api.routes.query.classify_query")
    async def test_run_empty_query_rejected(self, mock_classify, mock_run, client):
        resp = await client.post("/api/query/run", json={"query": ""})
        assert resp.status_code == 422 or resp.status_code == 400


class TestQueryRefine:
    @patch("cockpit.api.routes.query.run_query")
    async def test_refine_passes_context(self, mock_run, client):
        mock_run.return_value = QueryResult(
            markdown="## Refined\nResult",
            agent_type="dev_story",
            tokens_in=200,
            tokens_out=100,
            elapsed_ms=2000,
        )
        resp = await client.post(
            "/api/query/refine",
            json={
                "query": "zoom into voice pipeline",
                "prior_result": "## Previous result...",
                "agent_type": "dev_story",
            },
        )
        assert resp.status_code == 200
        # Verify prior_context was passed
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args[1]["prior_context"] is not None or (
            len(call_args[0]) >= 3 and call_args[0][2] is not None
        )


class TestSSEEventOrder:
    @patch("cockpit.api.routes.query.run_query")
    @patch("cockpit.api.routes.query.classify_query", return_value="dev_story")
    async def test_events_follow_status_text_done_sequence(self, mock_classify, mock_run, client):
        mock_run.return_value = QueryResult(
            markdown="## Test\nContent here",
            agent_type="dev_story",
            tokens_in=100,
            tokens_out=50,
            elapsed_ms=500,
        )
        resp = await client.post("/api/query/run", json={"query": "test query"})
        assert resp.status_code == 200

        body = resp.text
        # SSE events should contain status, text_delta, done in order
        status_pos = body.find("event: status")
        text_pos = body.find("event: text_delta")
        done_pos = body.find("event: done")
        assert status_pos >= 0, "Missing status event"
        assert text_pos >= 0, "Missing text_delta event"
        assert done_pos >= 0, "Missing done event"
        assert status_pos < text_pos < done_pos, "Events out of order"

    @patch("cockpit.api.routes.query.run_query")
    @patch("cockpit.api.routes.query.classify_query", return_value="dev_story")
    async def test_empty_result_still_completes(self, mock_classify, mock_run, client):
        mock_run.return_value = QueryResult(
            markdown="",
            agent_type="dev_story",
            tokens_in=50,
            tokens_out=10,
            elapsed_ms=200,
        )
        resp = await client.post("/api/query/run", json={"query": "empty test"})
        assert resp.status_code == 200
        assert "event: done" in resp.text
