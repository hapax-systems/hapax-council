"""Tests for OperatorBiometricField, OperatorMobilityField, CompanionFleetField.

Validates that build_perceptual_field reads watch and phone state files
from ~/hapax-state/watch/ and populates the three companion fleet sub-fields.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

from shared.perceptual_field import build_perceptual_field


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


class TestOperatorBiometricField:
    def test_reads_heartrate(self, tmp_path: Path) -> None:
        _write_json(
            tmp_path / "heartrate.json",
            {
                "current": {"bpm": 72.0, "confidence": "HIGH"},
                "window_1h": {"min": 60, "max": 90, "mean": 72, "readings": 10},
            },
        )
        with patch("shared.perceptual_field._WATCH_STATE_DIR", tmp_path):
            field = build_perceptual_field()
        assert field.operator_biometric.heart_rate_bpm == 72.0
        assert field.operator_biometric.heart_rate_confidence == "HIGH"

    def test_reads_hrv(self, tmp_path: Path) -> None:
        _write_json(tmp_path / "hrv.json", {"current": {"rmssd_ms": 45.2}})
        with patch("shared.perceptual_field._WATCH_STATE_DIR", tmp_path):
            field = build_perceptual_field()
        assert field.operator_biometric.hrv_rmssd_ms == 45.2

    def test_reads_skin_temp(self, tmp_path: Path) -> None:
        _write_json(tmp_path / "skin_temp.json", {"current": {"temp_c": 33.5}})
        with patch("shared.perceptual_field._WATCH_STATE_DIR", tmp_path):
            field = build_perceptual_field()
        assert field.operator_biometric.skin_temp_c == 33.5

    def test_reads_eda(self, tmp_path: Path) -> None:
        _write_json(tmp_path / "eda.json", {"current": {"eda_event": True}})
        with patch("shared.perceptual_field._WATCH_STATE_DIR", tmp_path):
            field = build_perceptual_field()
        assert field.operator_biometric.eda_event is True

    def test_reads_respiration(self, tmp_path: Path) -> None:
        _write_json(tmp_path / "respiration.json", {"current": {"breaths_per_min": 14.5}})
        with patch("shared.perceptual_field._WATCH_STATE_DIR", tmp_path):
            field = build_perceptual_field()
        assert field.operator_biometric.respiration_rate == 14.5

    def test_reads_health_summary_fields(self, tmp_path: Path) -> None:
        _write_json(
            tmp_path / "phone_health_summary.json",
            {
                "spo2_mean": 97.5,
                "sleep_duration_min": 420,
                "resting_hr": 58.0,
            },
        )
        with patch("shared.perceptual_field._WATCH_STATE_DIR", tmp_path):
            field = build_perceptual_field()
        assert field.operator_biometric.spo2_mean == 97.5
        assert field.operator_biometric.sleep_duration_min == 420
        assert field.operator_biometric.resting_hr == 58.0

    def test_degrades_gracefully_when_missing(self, tmp_path: Path) -> None:
        with patch("shared.perceptual_field._WATCH_STATE_DIR", tmp_path):
            field = build_perceptual_field()
        assert field.operator_biometric.heart_rate_bpm is None
        assert field.operator_biometric.hrv_rmssd_ms is None


class TestOperatorMobilityField:
    def test_reads_phone_context(self, tmp_path: Path) -> None:
        _write_json(
            tmp_path / "phone_context.json",
            {"activity_type": "walking", "activity_confidence": 0.85},
        )
        with patch("shared.perceptual_field._WATCH_STATE_DIR", tmp_path):
            field = build_perceptual_field()
        assert field.operator_mobility.activity_type == "walking"
        assert field.operator_mobility.activity_confidence == 0.85

    def test_falls_back_to_watch_activity(self, tmp_path: Path) -> None:
        _write_json(tmp_path / "activity.json", {"state": "RUNNING"})
        with patch("shared.perceptual_field._WATCH_STATE_DIR", tmp_path):
            field = build_perceptual_field()
        assert field.operator_mobility.activity_type == "RUNNING"

    def test_phone_context_takes_priority(self, tmp_path: Path) -> None:
        _write_json(
            tmp_path / "phone_context.json",
            {"activity_type": "in_vehicle", "activity_confidence": 0.9},
        )
        _write_json(tmp_path / "activity.json", {"state": "WALKING"})
        with patch("shared.perceptual_field._WATCH_STATE_DIR", tmp_path):
            field = build_perceptual_field()
        assert field.operator_mobility.activity_type == "in_vehicle"

    def test_reads_steps_from_summary(self, tmp_path: Path) -> None:
        _write_json(
            tmp_path / "phone_health_summary.json",
            {"steps": 8234, "active_minutes": 42},
        )
        with patch("shared.perceptual_field._WATCH_STATE_DIR", tmp_path):
            field = build_perceptual_field()
        assert field.operator_mobility.steps == 8234
        assert field.operator_mobility.active_minutes == 42

    def test_degrades_gracefully_when_missing(self, tmp_path: Path) -> None:
        with patch("shared.perceptual_field._WATCH_STATE_DIR", tmp_path):
            field = build_perceptual_field()
        assert field.operator_mobility.activity_type is None
        assert field.operator_mobility.steps is None


class TestCompanionFleetField:
    def test_watch_connected_recent(self, tmp_path: Path) -> None:
        _write_json(
            tmp_path / "connection.json",
            {"last_seen_epoch": time.time(), "device_id": "pw4", "battery_pct": 85},
        )
        with patch("shared.perceptual_field._WATCH_STATE_DIR", tmp_path):
            field = build_perceptual_field()
        assert field.companion_fleet.watch_connected is True
        assert field.companion_fleet.watch_battery_pct == 85

    def test_watch_disconnected_stale(self, tmp_path: Path) -> None:
        _write_json(
            tmp_path / "connection.json",
            {"last_seen_epoch": time.time() - 3600, "device_id": "pw4"},
        )
        with patch("shared.perceptual_field._WATCH_STATE_DIR", tmp_path):
            field = build_perceptual_field()
        assert field.companion_fleet.watch_connected is False
        assert field.companion_fleet.watch_last_seen_ago_s is not None
        assert field.companion_fleet.watch_last_seen_ago_s > 3500

    def test_phone_connected_recent(self, tmp_path: Path) -> None:
        _write_json(
            tmp_path / "phone_connection.json",
            {
                "last_seen_epoch": time.time(),
                "device_id": "pixel10",
                "battery_pct": 72,
            },
        )
        with patch("shared.perceptual_field._WATCH_STATE_DIR", tmp_path):
            field = build_perceptual_field()
        assert field.companion_fleet.phone_connected is True
        assert field.companion_fleet.phone_battery_pct == 72

    def test_both_missing_defaults_disconnected(self, tmp_path: Path) -> None:
        with patch("shared.perceptual_field._WATCH_STATE_DIR", tmp_path):
            field = build_perceptual_field()
        assert field.companion_fleet.watch_connected is False
        assert field.companion_fleet.phone_connected is False

    def test_json_excludes_none_fields(self, tmp_path: Path) -> None:
        with patch("shared.perceptual_field._WATCH_STATE_DIR", tmp_path):
            field = build_perceptual_field()
        rendered = json.loads(field.model_dump_json(exclude_none=True))
        fleet = rendered.get("companion_fleet", {})
        assert "watch_last_seen_ago_s" not in fleet
        assert "phone_last_seen_ago_s" not in fleet
