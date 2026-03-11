"""Tests for scout decision API endpoints."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from cockpit.api.app import app


@pytest.fixture
def decisions_file(tmp_path):
    return tmp_path / "scout-decisions.jsonl"


@pytest.mark.asyncio
async def test_record_decision(decisions_file):
    with patch("cockpit.api.routes.scout.DECISIONS_FILE", decisions_file):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/scout/litellm-proxy/decide",
                json={
                    "decision": "adopted",
                    "notes": "Time to upgrade",
                },
            )
    assert resp.status_code == 200
    data = resp.json()
    assert data["component"] == "litellm-proxy"
    assert data["decision"] == "adopted"
    # Verify persisted
    lines = decisions_file.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["component"] == "litellm-proxy"
    assert record["decision"] == "adopted"
    assert record["notes"] == "Time to upgrade"


@pytest.mark.asyncio
async def test_get_decisions(decisions_file):
    # Pre-populate with 2 decisions
    decisions_file.write_text(
        json.dumps(
            {
                "component": "foo",
                "decision": "adopted",
                "timestamp": "2026-03-09T10:00:00Z",
                "notes": "",
            }
        )
        + "\n"
        + json.dumps(
            {
                "component": "bar",
                "decision": "dismissed",
                "timestamp": "2026-03-09T11:00:00Z",
                "notes": "",
            }
        )
        + "\n"
    )
    with patch("cockpit.api.routes.scout.DECISIONS_FILE", decisions_file):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/scout/decisions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["decisions"]) == 2
    assert data["decisions"][0]["component"] == "foo"


@pytest.mark.asyncio
async def test_invalid_decision():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/scout/litellm-proxy/decide",
            json={
                "decision": "invalid_value",
            },
        )
    assert resp.status_code == 422
