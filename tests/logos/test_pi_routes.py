"""tests/logos/test_pi_routes.py — Tests for Pi NoIR API receiver."""

import json
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path):
    """Create test client with isolated state directory."""
    with patch("logos.api.routes.pi.IR_STATE_DIR", tmp_path):
        # Reset rate limiter between tests
        import logos.api.routes.pi as pi_mod

        pi_mod._last_post_time.clear()
        app = FastAPI()
        app.include_router(pi_mod.router)
        yield TestClient(app)


def test_post_ir_detection(client, tmp_path):
    report = {
        "pi": "hapax-pi6",
        "role": "overhead",
        "ts": "2026-03-29T14:30:00-05:00",
        "motion_delta": 0.23,
        "persons": [{"confidence": 0.87, "bbox": [120, 80, 400, 460]}],
        "hands": [],
        "screens": [],
        "ir_brightness": 142,
        "inference_ms": 280,
        "biometrics": {"heart_rate_bpm": 72},
    }
    resp = client.post("/api/pi/overhead/ir", json=report)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["cam_id"] == "primary"
    state_file = tmp_path / "overhead.json"
    camera_state_file = tmp_path / "overhead-primary.json"
    assert state_file.exists()
    assert camera_state_file.exists()
    data = json.loads(state_file.read_text())
    assert data["role"] == "overhead"
    assert data["cam_id"] == "primary"


def test_post_ir_detection_with_secondary_cam_id(client, tmp_path):
    report = {
        "pi": "hapax-pi6",
        "role": "overhead",
        "cam_id": "secondary",
        "ts": "2026-03-29T14:30:00-05:00",
        "motion_delta": 0.23,
        "persons": [],
        "hands": [],
        "screens": [],
        "ir_brightness": 142,
        "inference_ms": 80,
        "biometrics": {},
    }
    resp = client.post("/api/pi/overhead/ir", json=report)
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "role": "overhead", "cam_id": "secondary"}

    assert not (tmp_path / "overhead.json").exists()
    camera_state_file = tmp_path / "overhead-secondary.json"
    assert camera_state_file.exists()
    data = json.loads(camera_state_file.read_text())
    assert data["role"] == "overhead"
    assert data["cam_id"] == "secondary"
    cadence = json.loads((tmp_path / "overhead-secondary-cadence.json").read_text())
    assert cadence["cam_id"] == "secondary"


def test_post_invalid_role(client):
    report = {
        "pi": "hapax-pi6",
        "role": "invalid",
        "ts": "2026-03-29T14:30:00-05:00",
        "motion_delta": 0.0,
    }
    resp = client.post("/api/pi/invalid/ir", json=report)
    assert resp.status_code == 422


def test_get_pi_status_empty(client):
    resp = client.get("/api/pi/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "desk" in data
    assert data["desk"]["online"] is False


def test_get_pi_status_with_data(client, tmp_path):
    report = {"pi": "hapax-pi6", "role": "overhead", "ts": "2026-03-29T14:30:00-05:00"}
    (tmp_path / "overhead.json").write_text(json.dumps(report))
    resp = client.get("/api/pi/status")
    assert resp.status_code == 200
    assert resp.json()["overhead"]["online"] is True
