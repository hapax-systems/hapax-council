"""Tests for profiler watch data extraction."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest


class TestWatchSourceReader:
    """Extracts profile facts from watch state files."""

    def test_extracts_resting_hr(self, watch_state_dir):
        from agents.profiler_sources import read_watch_facts
        facts = read_watch_facts(watch_state_dir)
        hr_facts = [f for f in facts if f["key"] == "health.resting_hr"]
        assert len(hr_facts) == 1
        assert hr_facts[0]["dimension"] == "energy_and_attention"
        assert hr_facts[0]["authority"] == "observation"

    def test_extracts_hrv_baseline(self, watch_state_dir):
        from agents.profiler_sources import read_watch_facts
        facts = read_watch_facts(watch_state_dir)
        hrv_facts = [f for f in facts if f["key"] == "health.hrv_baseline"]
        assert len(hrv_facts) == 1

    def test_extracts_active_minutes(self, watch_state_dir):
        from agents.profiler_sources import read_watch_facts
        facts = read_watch_facts(watch_state_dir)
        active = [f for f in facts if f["key"] == "health.active_minutes"]
        assert len(active) == 1

    def test_returns_empty_when_no_watch_data(self, tmp_path):
        from agents.profiler_sources import read_watch_facts
        facts = read_watch_facts(tmp_path)
        assert facts == []

    def test_facts_are_observation_authority(self, watch_state_dir):
        from agents.profiler_sources import read_watch_facts
        facts = read_watch_facts(watch_state_dir)
        for fact in facts:
            assert fact["authority"] == "observation"


@pytest.fixture
def watch_state_dir(tmp_path):
    """Create a watch state directory with sample data."""
    (tmp_path / "heartrate.json").write_text(json.dumps({
        "source": "pixel_watch_4",
        "updated_at": "2026-03-12T14:30:00-05:00",
        "current": {"bpm": 72, "confidence": "HIGH"},
        "window_1h": {"min": 58, "max": 95, "mean": 71, "readings": 120},
    }))
    (tmp_path / "hrv.json").write_text(json.dumps({
        "current": {"rmssd_ms": 42},
        "window_1h": {"mean": 45},
        "updated_at": "2026-03-12T14:30:00-05:00",
    }))
    (tmp_path / "activity.json").write_text(json.dumps({
        "state": "STILL",
        "active_minutes_today": 35,
        "updated_at": "2026-03-12T14:30:00-05:00",
    }))
    (tmp_path / "connection.json").write_text(json.dumps({
        "last_seen_epoch": time.time(),
        "battery_pct": 78,
    }))
    return tmp_path
