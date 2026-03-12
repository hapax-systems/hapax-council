"""Tests for profiler watch data extraction."""
from __future__ import annotations

import json
import time

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


class TestPhoneSummaryPreference:
    """Phone daily aggregates preferred over watch when available."""

    def test_phone_summary_preferred(self, watch_state_dir):
        """Phone facts used for daily totals when phone summary exists."""
        from datetime import date

        from agents.profiler_sources import read_watch_facts
        (watch_state_dir / "phone_health_summary.json").write_text(json.dumps({
            "date": date.today().isoformat(),
            "resting_hr": 60,
            "steps": 9000,
            "active_minutes": 50,
            "sleep_duration_min": 480,
            "source": "pixel_10",
        }))
        facts = read_watch_facts(watch_state_dir)
        hr_facts = [f for f in facts if f["key"] == "health.resting_hr"]
        assert len(hr_facts) == 1
        assert hr_facts[0]["source"] == "phone:pixel_10"
        assert hr_facts[0]["value"] == 60

    def test_watch_fallback_when_no_phone(self, watch_state_dir):
        """Falls back to watch data when phone summary is absent."""
        from agents.profiler_sources import read_watch_facts
        facts = read_watch_facts(watch_state_dir)
        hr_facts = [f for f in facts if f["key"] == "health.resting_hr"]
        assert len(hr_facts) == 1
        assert hr_facts[0]["source"] == "watch:pixel_watch_4"

    def test_phone_steps_fact(self, watch_state_dir):
        """Phone summary produces steps fact."""
        from datetime import date

        from agents.profiler_sources import read_watch_facts
        (watch_state_dir / "phone_health_summary.json").write_text(json.dumps({
            "date": date.today().isoformat(),
            "steps": 12000,
        }))
        facts = read_watch_facts(watch_state_dir)
        steps = [f for f in facts if f["key"] == "health.steps"]
        assert len(steps) == 1
        assert steps[0]["value"] == 12000


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
