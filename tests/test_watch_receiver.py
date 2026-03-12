"""Tests for watch-receiver FastAPI service."""

from __future__ import annotations

import json
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from agents.watch_receiver import _hr_window, _hrv_window, create_app


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
                {
                    "type": "heart_rate",
                    "bpm": 72,
                    "confidence": "HIGH",
                    "ts": "2026-03-12T14:29:55-05:00",
                }
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
                {"type": "activity", "state": "WALKING", "ts": "2026-03-12T14:30:00-05:00"}
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
            client.post(
                "/watch/sensors",
                json={
                    "ts": int(time.time() * 1000),
                    "device_id": "pw4",
                    "readings": [
                        {
                            "type": "heart_rate",
                            "bpm": bpm,
                            "confidence": "HIGH",
                            "ts": "2026-03-12T14:30:00-05:00",
                        }
                    ],
                },
            )
        data = json.loads((state_dir / "heartrate.json").read_text())
        assert data["current"]["bpm"] == 80

    def test_rejects_unknown_device(self, client, state_dir):
        """Rejects payloads from unrecognized device_id."""
        resp = client.post(
            "/watch/sensors",
            json={
                "ts": int(time.time() * 1000),
                "device_id": "unknown",
                "readings": [],
            },
        )
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


class TestMultiDevice:
    """Multi-device support for watch and phone."""

    def test_phone_accepted(self, client, state_dir):
        """Phone device_id pixel10 is accepted."""
        resp = client.post(
            "/watch/sensors",
            json={
                "ts": int(time.time() * 1000),
                "device_id": "pixel10",
                "readings": [],
                "battery_pct": 85,
            },
        )
        assert resp.status_code == 200

    def test_phone_writes_phone_connection(self, client, state_dir):
        """Phone POSTs write phone_connection.json, not connection.json."""
        client.post(
            "/watch/sensors",
            json={
                "ts": int(time.time() * 1000),
                "device_id": "pixel10",
                "readings": [],
                "battery_pct": 85,
            },
        )
        assert (state_dir / "phone_connection.json").exists()
        assert not (state_dir / "connection.json").exists()

    def test_watch_still_writes_connection(self, client, state_dir):
        """Watch POSTs still write connection.json."""
        client.post(
            "/watch/sensors",
            json={
                "ts": int(time.time() * 1000),
                "device_id": "pw4",
                "readings": [],
            },
        )
        assert (state_dir / "connection.json").exists()
        assert not (state_dir / "phone_connection.json").exists()

    def test_phone_source_in_sensor_files(self, client, state_dir):
        """Phone sensor readings have source pixel_10."""
        client.post(
            "/watch/sensors",
            json={
                "ts": int(time.time() * 1000),
                "device_id": "pixel10",
                "readings": [
                    {"type": "activity", "state": "WALKING", "ts": "2026-03-12T14:30:00-05:00"}
                ],
            },
        )
        data = json.loads((state_dir / "activity.json").read_text())
        assert data["source"] == "pixel_10"

    def test_unknown_device_rejected(self, client, state_dir):
        """Unknown device_id is rejected with 403."""
        resp = client.post(
            "/watch/sensors",
            json={
                "ts": int(time.time() * 1000),
                "device_id": "unknown_phone",
                "readings": [],
            },
        )
        assert resp.status_code == 403


class TestHealthSummary:
    """POST /phone/health-summary writes summary files."""

    def test_writes_summary_file(self, client, state_dir):
        """Creates phone_health_summary.json."""
        resp = client.post(
            "/phone/health-summary",
            json={
                "device_id": "pixel10",
                "date": "2026-03-12",
                "resting_hr": 62,
                "steps": 8234,
                "active_minutes": 42,
                "sleep_duration_min": 453,
            },
        )
        assert resp.status_code == 200
        summary = state_dir / "phone_health_summary.json"
        assert summary.exists()
        data = json.loads(summary.read_text())
        assert data["resting_hr"] == 62
        assert data["source"] == "pixel_10"

    def test_writes_rag_markdown(self, client, state_dir, tmp_path):
        """Creates health-YYYY-MM-DD.md in rag-sources."""
        with patch("agents.watch_receiver.HAPAX_HOME", tmp_path):
            resp = client.post(
                "/phone/health-summary",
                json={
                    "device_id": "pixel10",
                    "date": "2026-03-12",
                    "resting_hr": 62,
                    "steps": 8234,
                },
            )
        assert resp.status_code == 200
        rag_file = (
            tmp_path / "documents" / "rag-sources" / "health-connect" / "health-2026-03-12.md"
        )
        assert rag_file.exists()
        content = rag_file.read_text()
        assert "device: pixel_10" in content

    def test_rejects_unknown_device(self, client, state_dir):
        """Rejects unknown device_id."""
        resp = client.post(
            "/phone/health-summary",
            json={
                "device_id": "unknown",
                "date": "2026-03-12",
                "resting_hr": 62,
            },
        )
        assert resp.status_code == 403

    def test_idempotent_same_date(self, client, state_dir):
        """Re-posting same date overwrites cleanly."""
        for hr in (62, 64):
            client.post(
                "/phone/health-summary",
                json={
                    "device_id": "pixel10",
                    "date": "2026-03-12",
                    "resting_hr": hr,
                },
            )
        data = json.loads((state_dir / "phone_health_summary.json").read_text())
        assert data["resting_hr"] == 64


class TestRollingWindow:
    """Heart rate and HRV maintain 1-hour rolling windows."""

    def test_heartrate_window_stats(self, client, state_dir):
        """Window tracks min/max/mean/readings count."""
        for bpm in [60, 70, 80, 90]:
            client.post(
                "/watch/sensors",
                json={
                    "ts": int(time.time() * 1000),
                    "device_id": "pw4",
                    "readings": [
                        {
                            "type": "heart_rate",
                            "bpm": bpm,
                            "confidence": "HIGH",
                            "ts": "2026-03-12T14:30:00-05:00",
                        }
                    ],
                },
            )
        data = json.loads((state_dir / "heartrate.json").read_text())
        assert data["window_1h"]["min"] == 60
        assert data["window_1h"]["max"] == 90
        assert data["window_1h"]["readings"] == 4
