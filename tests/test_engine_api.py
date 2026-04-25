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


# ── TestSystemDegradedStatus ────────────────────────────────────────────


class TestSystemDegradedStatus:
    def test_returns_posterior_and_state(self):
        from agents.hapax_daimonion.system_degraded_engine import SystemDegradedEngine

        sde = SystemDegradedEngine()
        app = _make_app(_mock_engine())
        app.state.system_degraded_engine = sde
        client = TestClient(app)
        resp = client.get("/api/engine/system_degraded")
        assert resp.status_code == 200
        data = resp.json()
        assert "posterior" in data
        assert "state" in data
        assert 0.0 <= data["posterior"] <= 1.0
        assert data["state"] in {"DEGRADED", "UNCERTAIN", "HEALTHY"}

    def test_state_responds_to_observations(self):
        from agents.hapax_daimonion.backends.engine_queue_depth import (
            DEFAULT_WATERMARK_DEPTH,
            queue_depth_observation,
        )
        from agents.hapax_daimonion.system_degraded_engine import SystemDegradedEngine

        class _StubQueue:
            def qsize(self):
                return DEFAULT_WATERMARK_DEPTH + 100

        sde = SystemDegradedEngine(prior=0.1, enter_ticks=2)
        for _ in range(8):
            sde.contribute(queue_depth_observation(_StubQueue()))
        app = _make_app(_mock_engine())
        app.state.system_degraded_engine = sde
        client = TestClient(app)
        resp = client.get("/api/engine/system_degraded")
        assert resp.status_code == 200
        assert resp.json()["state"] == "DEGRADED"

    def test_503_when_no_sde(self):
        client = TestClient(_make_app())
        resp = client.get("/api/engine/system_degraded")
        assert resp.status_code == 503


# ── TestLogosDriftBridge ────────────────────────────────────────────────


class TestLogosDriftBridge:
    """Drift bridge: collect_drift() → drift_score() Protocol."""

    def test_no_summary_yields_zero_score(self):
        from unittest.mock import patch

        from logos.api.app import LogosDriftBridge

        with patch("logos.data.drift.collect_drift", return_value=None):
            assert LogosDriftBridge().drift_score() == 0.0

    def test_no_high_items_yields_zero(self):
        from unittest.mock import MagicMock, patch

        from logos.api.app import LogosDriftBridge

        summary = MagicMock()
        item = MagicMock()
        item.severity = "low"
        summary.items = [item, item, item]
        with patch("logos.data.drift.collect_drift", return_value=summary):
            assert LogosDriftBridge().drift_score() == 0.0

    def test_5_high_items_yields_half_score(self):
        from unittest.mock import MagicMock, patch

        from logos.api.app import LogosDriftBridge

        summary = MagicMock()
        items = [MagicMock(severity="HIGH") for _ in range(5)]
        items.extend([MagicMock(severity="low") for _ in range(2)])
        summary.items = items
        with patch("logos.data.drift.collect_drift", return_value=summary):
            assert LogosDriftBridge().drift_score() == 0.5

    def test_score_saturates_at_one(self):
        from unittest.mock import MagicMock, patch

        from logos.api.app import LogosDriftBridge

        summary = MagicMock()
        summary.items = [MagicMock(severity="HIGH") for _ in range(50)]
        with patch("logos.data.drift.collect_drift", return_value=summary):
            assert LogosDriftBridge().drift_score() == 1.0

    def test_severity_case_insensitive(self):
        from unittest.mock import MagicMock, patch

        from logos.api.app import LogosDriftBridge

        summary = MagicMock()
        summary.items = [
            MagicMock(severity="High"),
            MagicMock(severity="HIGH"),
            MagicMock(severity="high"),
        ]
        with patch("logos.data.drift.collect_drift", return_value=summary):
            assert LogosDriftBridge().drift_score() == 0.3

    def test_drift_bridge_drives_engine_to_degraded(self):
        from unittest.mock import MagicMock, patch

        from agents.hapax_daimonion.backends.drift_significant import (
            drift_significant_observation,
        )
        from agents.hapax_daimonion.system_degraded_engine import SystemDegradedEngine
        from logos.api.app import LogosDriftBridge

        summary = MagicMock()
        summary.items = [MagicMock(severity="HIGH") for _ in range(15)]
        with patch("logos.data.drift.collect_drift", return_value=summary):
            bridge = LogosDriftBridge()
            sde = SystemDegradedEngine(prior=0.1, enter_ticks=2)
            for _ in range(8):
                sde.contribute(drift_significant_observation(bridge))
            assert sde.state == "DEGRADED"
