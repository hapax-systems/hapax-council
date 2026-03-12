"""Tests for WatchBackend — physiological signals from watch state files."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from agents.hapax_voice.backends.watch import (
    WatchBackend,
    _compute_physiological_load,
    _compute_sleep_quality,
)
from agents.hapax_voice.primitives import Behavior


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


class TestPhysiologicalLoad:
    def test_normal_hrv_zero_load(self):
        load = _compute_physiological_load(current_rmssd=50.0, mean_rmssd=50.0, eda_duration=0.0)
        assert load == pytest.approx(0.0, abs=0.01)

    def test_hrv_40pct_drop(self):
        load = _compute_physiological_load(current_rmssd=30.0, mean_rmssd=50.0, eda_duration=0.0)
        assert load == pytest.approx(0.4, abs=0.01)

    def test_eda_180s(self):
        load = _compute_physiological_load(current_rmssd=None, mean_rmssd=None, eda_duration=180.0)
        assert load == pytest.approx(0.5, abs=0.01)  # capped at 0.5 for EDA alone

    def test_hrv_drop_plus_eda(self):
        load = _compute_physiological_load(current_rmssd=30.0, mean_rmssd=50.0, eda_duration=180.0)
        # 0.4 (HRV) + 0.5 (EDA capped) = 0.9
        assert load == pytest.approx(0.9, abs=0.01)

    def test_none_values_default_zero(self):
        load = _compute_physiological_load(current_rmssd=None, mean_rmssd=None, eda_duration=0.0)
        assert load == pytest.approx(0.0, abs=0.01)


class TestSleepQuality:
    def test_8h_sleep(self):
        sq = _compute_sleep_quality(480)
        assert sq == pytest.approx(1.0, abs=0.01)

    def test_5h_sleep(self):
        sq = _compute_sleep_quality(300)
        # 300/420 * 0.8 = ~0.571
        assert sq == pytest.approx(0.571, abs=0.01)

    def test_3h_sleep(self):
        sq = _compute_sleep_quality(180)
        # 180/420 * 0.8 = ~0.343
        assert sq == pytest.approx(0.343, abs=0.01)

    def test_quality_bonus(self):
        sq = _compute_sleep_quality(420, deep_min=70, rem_min=60)
        # min(420/420, 1.0) = 1.0; deep+rem=130 >= 120 → +0.1, capped at 1.0
        assert sq == pytest.approx(1.0, abs=0.01)

    def test_short_sleep_with_quality_bonus(self):
        sq = _compute_sleep_quality(360, deep_min=70, rem_min=60)
        # 360/420 = 0.857; no <360 penalty; deep+rem=130 → +0.1 = 0.957
        assert sq == pytest.approx(0.957, abs=0.01)

    def test_very_short_with_quality(self):
        sq = _compute_sleep_quality(300, deep_min=70, rem_min=60)
        # 300/420 * 0.8 = 0.571; +0.1 = 0.671
        assert sq == pytest.approx(0.671, abs=0.01)


class TestWatchBackendContribute:
    def test_missing_files_defaults(self, tmp_path):
        watch_dir = tmp_path / "watch"
        watch_dir.mkdir()
        backend = WatchBackend(watch_dir=watch_dir)
        behaviors: dict[str, Behavior] = {}
        backend.contribute(behaviors)
        assert behaviors["stress_elevated"].value is False
        assert behaviors["physiological_load"].value == pytest.approx(0.0, abs=0.01)
        assert behaviors["sleep_quality"].value == pytest.approx(1.0, abs=0.01)

    def test_hrv_drop_triggers_stress(self, tmp_path):
        watch_dir = tmp_path / "watch"
        _write_json(watch_dir / "hrv.json", {
            "current": {"rmssd_ms": 20.0, "heart_rate_bpm": 90},
            "window_1h": {"mean": 50.0},
        })
        backend = WatchBackend(watch_dir=watch_dir, cache_ttl=0)
        behaviors: dict[str, Behavior] = {}
        backend.contribute(behaviors)
        assert behaviors["stress_elevated"].value is True
        assert behaviors["physiological_load"].value > 0.3

    def test_sleep_from_phone_summary(self, tmp_path):
        watch_dir = tmp_path / "watch"
        watch_dir.mkdir(parents=True, exist_ok=True)
        _write_json(watch_dir / "phone_health_summary.json", {
            "sleep_duration_min": 300,
            "deep_min": 40,
            "rem_min": 30,
        })
        backend = WatchBackend(watch_dir=watch_dir, cache_ttl=0)
        behaviors: dict[str, Behavior] = {}
        backend.contribute(behaviors)
        assert behaviors["sleep_quality"].value < 0.7
