"""Tests for logos/api/routes/engine.py — engine API endpoints.

Self-contained, asyncio_mode="auto", unittest.mock only.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from logos.api.routes.engine import router


def _make_app(engine=None) -> FastAPI:
    """Create a test app with optional engine on state."""
    app = FastAPI()
    app.include_router(router)
    if engine is not None:
        app.state.engine = engine
    return app


def _mock_engine(running=True, paused=False):
    """Create a mock ReactiveEngine with realistic status."""
    engine = MagicMock()
    engine.status = {
        "running": running,
        "paused": paused,
        "uptime_s": 120.5,
        "events_processed": 10,
        "rules_evaluated": 50,
        "actions_executed": 8,
        "errors": 1,
    }

    # Mock registry with rules
    rule1 = MagicMock()
    rule1.name = "collector-refresh"
    rule1.description = "Refresh cache"
    rule1.phase = 0
    rule1.cooldown_s = 0

    rule2 = MagicMock()
    rule2.name = "rag-source-landed"
    rule2.description = "Ingest RAG source"
    rule2.phase = 1
    rule2.cooldown_s = 0

    engine.registry = [rule1, rule2]

    # Mock history
    entry = MagicMock()
    entry.timestamp = datetime(2026, 3, 13, 12, 0, 0)
    entry.event_path = "/profiles/health-history.jsonl"
    entry.doc_type = "health-event"
    entry.rules_matched = ["collector-refresh"]
    entry.actions = ["collector-refresh-fast"]
    entry.errors = []
    engine.history = [entry]

    return engine


# ── TestEngineStatus ────────────────────────────────────────────────────


class TestEngineStatus:
    def test_returns_status(self):
        engine = _mock_engine()
        client = TestClient(_make_app(engine))
        resp = client.get("/api/engine/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is True
        assert data["events_processed"] == 10

    def test_503_when_no_engine(self):
        client = TestClient(_make_app())
        resp = client.get("/api/engine/status")
        assert resp.status_code == 503


# ── TestEngineRules ─────────────────────────────────────────────────────


class TestEngineRules:
    def test_returns_rules_list(self):
        engine = _mock_engine()
        client = TestClient(_make_app(engine))
        resp = client.get("/api/engine/rules")
        assert resp.status_code == 200
        rules = resp.json()
        assert len(rules) == 2
        assert rules[0]["name"] == "collector-refresh"
        assert rules[1]["phase"] == 1

    def test_503_when_no_engine(self):
        client = TestClient(_make_app())
        resp = client.get("/api/engine/rules")
        assert resp.status_code == 503


# ── TestEngineHistory ───────────────────────────────────────────────────


class TestEngineHistory:
    def test_returns_history(self):
        engine = _mock_engine()
        client = TestClient(_make_app(engine))
        resp = client.get("/api/engine/history")
        assert resp.status_code == 200
        history = resp.json()
        assert len(history) == 1
        assert history[0]["event_path"] == "/profiles/health-history.jsonl"
        assert history[0]["doc_type"] == "health-event"

    def test_limit_parameter(self):
        engine = _mock_engine()
        client = TestClient(_make_app(engine))
        resp = client.get("/api/engine/history?limit=0")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_503_when_no_engine(self):
        client = TestClient(_make_app())
        resp = client.get("/api/engine/history")
        assert resp.status_code == 503
