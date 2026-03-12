"""Tests for watch-receiver FastAPI service."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from agents.watch_receiver import create_app, WATCH_STATE_DIR, _hr_window, _hrv_window


@pytest.fixture
def state_dir(tmp_path):
    """Override WATCH_STATE_DIR for tests and clear rolling windows."""
    _hr_window.clear()
    _hrv_window.clear()
    with patch("agents.watch_receiver.WATCH_STATE_DIR", tmp_path):
        yield tmp_path


@pytest.fixture
def client(state_dir):
    app = create_app()
    return TestClient(app)


class TestSensorIngestion:
    """POST /watch/sensors writes atomic JSON files."""

    def test_heartrate_creates_file(self, client, state_dir):
        """Heart rate readings create heartrate.json."""
        payload = {
            "ts": int(time.time() * 1000),
            "device_id": "pw4",
            "readings": [
                {"type": "heart_rate", "bpm": 72, "confidence": "HIGH",
                 "ts": "2026-03-12T14:29:55-05:00"}
            ],
        }
        resp = client.post("/watch/sensors", json=payload)
        assert resp.status_code == 200
        hr_file = state_dir / "heartrate.json"
        assert hr_file.exists()
        data = json.loads(hr_file.read_text())
        assert data["current"]["bpm"] == 72

    def test_activity_state_creates_file(self, client, state_dir):
        """Activity state readings create activity.json."""
        payload = {
            "ts": int(time.time() * 1000),
            "device_id": "pw4",
            "readings": [
                {"type": "activity", "state": "WALKING",
                 "ts": "2026-03-12T14:30:00-05:00"}
            ],
        }
        resp = client.post("/watch/sensors", json=payload)
        assert resp.status_code == 200
        act_file = state_dir / "activity.json"
        assert act_file.exists()
        data = json.loads(act_file.read_text())
        assert data["state"] == "WALKING"

    def test_connection_updated_on_any_post(self, client, state_dir):
        """Every sensor POST updates connection.json with last_seen."""
        payload = {
            "ts": int(time.time() * 1000),
            "device_id": "pw4",
            "readings": [],
        }
        resp = client.post("/watch/sensors", json=payload)
        assert resp.status_code == 200
        conn = state_dir / "connection.json"
        assert conn.exists()
        data = json.loads(conn.read_text())
        assert "last_seen_epoch" in data

    def test_atomic_write(self, client, state_dir):
        """Files are written atomically (via tmp + rename)."""
        for bpm in (65, 80):
            client.post("/watch/sensors", json={
                "ts": int(time.time() * 1000),
                "device_id": "pw4",
                "readings": [{"type": "heart_rate", "bpm": bpm,
                              "confidence": "HIGH", "ts": "2026-03-12T14:30:00-05:00"}],
            })
        data = json.loads((state_dir / "heartrate.json").read_text())
        assert data["current"]["bpm"] == 80

    def test_rejects_unknown_device(self, client, state_dir):
        """Rejects payloads from unrecognized device_id."""
        resp = client.post("/watch/sensors", json={
            "ts": int(time.time() * 1000),
            "device_id": "unknown",
            "readings": [],
        })
        assert resp.status_code == 403


class TestStatusEndpoint:
    """GET /watch/status returns connectivity info."""

    def test_returns_ok(self, client):
        resp = client.get("/watch/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestVoiceTrigger:
    """POST /watch/voice-trigger signals the voice daemon."""

    def test_writes_trigger_file(self, client, state_dir):
        """Creates a trigger file for the voice daemon to detect."""
        resp = client.post("/watch/voice-trigger", json={"device_id": "pw4"})
        assert resp.status_code == 200
        trigger = state_dir / "voice_trigger.json"
        assert trigger.exists()


class TestRollingWindow:
    """Heart rate and HRV maintain 1-hour rolling windows."""

    def test_heartrate_window_stats(self, client, state_dir):
        """Window tracks min/max/mean/readings count."""
        for bpm in [60, 70, 80, 90]:
            client.post("/watch/sensors", json={
                "ts": int(time.time() * 1000),
                "device_id": "pw4",
                "readings": [{"type": "heart_rate", "bpm": bpm,
                              "confidence": "HIGH", "ts": "2026-03-12T14:30:00-05:00"}],
            })
        data = json.loads((state_dir / "heartrate.json").read_text())
        assert data["window_1h"]["min"] == 60
        assert data["window_1h"]["max"] == 90
        assert data["window_1h"]["readings"] == 4
