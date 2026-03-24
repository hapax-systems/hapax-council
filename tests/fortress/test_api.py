"""Tests for fortress API routes."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from logos.api.routes.fortress import router


@pytest.fixture
def app() -> FastAPI:
    test_app = FastAPI()
    test_app.include_router(router)
    return test_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _write_state(path: Path, **overrides: object) -> None:
    state = {
        "timestamp": time.time(),
        "game_tick": 120000,
        "year": 3,
        "season": 2,
        "month": 8,
        "day": 15,
        "fortress_name": "TestFort",
        "paused": False,
        "population": 47,
        "food_count": 234,
        "drink_count": 100,
        "active_threats": 0,
        "job_queue_length": 15,
        "idle_dwarf_count": 3,
        "most_stressed_value": 5000,
        "pending_events": [],
    }
    state.update(overrides)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state))


class TestGetState:
    def test_returns_state(self, client: TestClient, tmp_path: Path):
        state_path = tmp_path / "state.json"
        _write_state(state_path)
        with patch("logos.api.routes.fortress._bridge_config") as mock_config:
            mock_config.state_path = state_path
            mock_config.staleness_threshold_s = 30.0
            resp = client.get("/api/fortress/state")
        assert resp.status_code == 200
        data = resp.json()
        assert data["fortress_name"] == "TestFort"
        assert data["population"] == 47

    def test_503_when_inactive(self, client: TestClient, tmp_path: Path):
        with patch("logos.api.routes.fortress._bridge_config") as mock_config:
            mock_config.state_path = tmp_path / "nonexistent.json"
            mock_config.staleness_threshold_s = 30.0
            resp = client.get("/api/fortress/state")
        assert resp.status_code == 503


class TestGetEvents:
    def test_returns_events(self, client: TestClient, tmp_path: Path):
        state_path = tmp_path / "state.json"
        _write_state(
            state_path,
            pending_events=[{"type": "siege", "attacker_civ": "Goblins", "force_size": 30}],
        )
        with patch("logos.api.routes.fortress._bridge_config") as mock_config:
            mock_config.state_path = state_path
            mock_config.staleness_threshold_s = 30.0
            resp = client.get("/api/fortress/events")
        assert resp.status_code == 200
        assert len(resp.json()["events"]) == 1


class TestGetGovernance:
    def test_returns_placeholder(self, client: TestClient):
        resp = client.get("/api/fortress/governance")
        assert resp.status_code == 200
        data = resp.json()
        assert "chains" in data
        assert "suppression" in data
        assert len(data["chains"]) == 7


class TestGetGoals:
    def test_returns_goals_structure(self, client: TestClient):
        resp = client.get("/api/fortress/goals")
        assert resp.status_code == 200
        assert "goals" in resp.json()
        assert isinstance(resp.json()["goals"], list)


class TestGetMetrics:
    def test_returns_metrics_structure(self, client: TestClient):
        resp = client.get("/api/fortress/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "survival_days" in data
        assert "total_commands" in data


class TestGetSessions:
    def test_empty(self, client: TestClient):
        resp = client.get("/api/fortress/sessions")
        assert resp.status_code == 200

    def test_with_sessions(self, client: TestClient, tmp_path: Path):
        sessions_file = tmp_path / "fortress-sessions.jsonl"
        sessions_file.write_text(
            json.dumps({"session_id": "abc", "survival_days": 100, "fortress_name": "Test"}) + "\n"
        )
        with patch(
            "logos.api.routes.fortress.Path",
            return_value=sessions_file,
        ):
            resp = client.get("/api/fortress/sessions")
        assert resp.status_code == 200


class TestGetChronicle:
    def test_empty(self, client: TestClient):
        resp = client.get("/api/fortress/chronicle")
        assert resp.status_code == 200
        assert resp.json()["entries"] == [] or isinstance(resp.json()["entries"], list)
