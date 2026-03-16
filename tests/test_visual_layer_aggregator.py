"""Tests for visual layer signal aggregator — signal mapping functions."""

from __future__ import annotations

from agents.visual_layer_aggregator import (
    map_briefing,
    map_copilot,
    map_drift,
    map_goals,
    map_gpu,
    map_health,
    map_nudges,
    map_perception,
)
from agents.visual_layer_state import (
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    SignalCategory,
)


class TestMapHealth:
    def test_healthy_no_signals(self):
        assert map_health({"overall_status": "healthy"}) == []

    def test_degraded(self):
        signals = map_health(
            {"overall_status": "degraded", "failed": 1, "failed_checks": ["qdrant"]}
        )
        assert len(signals) == 1
        assert signals[0].category == SignalCategory.HEALTH_INFRA
        assert signals[0].severity == SEVERITY_HIGH
        assert "degraded" in signals[0].title.lower()

    def test_failed_critical(self):
        signals = map_health(
            {"overall_status": "failed", "failed": 5, "failed_checks": ["a", "b", "c"]}
        )
        assert signals[0].severity == SEVERITY_CRITICAL

    def test_many_failures_critical(self):
        signals = map_health(
            {"overall_status": "degraded", "failed": 3, "failed_checks": ["a", "b", "c"]}
        )
        assert signals[0].severity == SEVERITY_CRITICAL

    def test_empty_dict(self):
        assert map_health({}) == []


class TestMapGpu:
    def test_normal_no_signals(self):
        assert map_gpu({"usage_pct": 50, "temperature_c": 60}) == []

    def test_high_vram(self):
        signals = map_gpu({"usage_pct": 91, "free_mb": 200, "temperature_c": 60})
        assert len(signals) == 1
        assert signals[0].severity == SEVERITY_HIGH
        assert "VRAM" in signals[0].title

    def test_medium_vram(self):
        signals = map_gpu({"usage_pct": 82, "temperature_c": 60})
        assert signals[0].severity == SEVERITY_MEDIUM

    def test_high_temp(self):
        signals = map_gpu({"usage_pct": 50, "temperature_c": 90})
        assert len(signals) == 1
        assert "°C" in signals[0].title

    def test_both_high(self):
        signals = map_gpu({"usage_pct": 95, "free_mb": 100, "temperature_c": 90})
        assert len(signals) == 2


class TestMapNudges:
    def test_empty(self):
        assert map_nudges([]) == []

    def test_top_three(self):
        nudges = [
            {
                "priority_label": "critical",
                "priority_score": 95,
                "title": "Fix health",
                "source_id": "n1",
            },
            {
                "priority_label": "high",
                "priority_score": 80,
                "title": "Review PR",
                "source_id": "n2",
            },
            {
                "priority_label": "medium",
                "priority_score": 50,
                "title": "Update docs",
                "source_id": "n3",
            },
            {"priority_label": "low", "priority_score": 20, "title": "Optional", "source_id": "n4"},
        ]
        signals = map_nudges(nudges)
        assert len(signals) == 3  # Top 3 only
        assert signals[0].severity == SEVERITY_CRITICAL
        assert signals[1].severity == SEVERITY_HIGH
        assert signals[2].severity == SEVERITY_MEDIUM

    def test_all_work_tasks(self):
        signals = map_nudges([{"priority_label": "low", "title": "t", "source_id": "x"}])
        assert signals[0].category == SignalCategory.WORK_TASKS


class TestMapBriefing:
    def test_no_headline(self):
        assert map_briefing({}) == []
        assert map_briefing({"headline": ""}) == []

    def test_with_headline(self):
        signals = map_briefing({"headline": "Good morning", "action_items": []})
        assert len(signals) == 1
        assert signals[0].category == SignalCategory.CONTEXT_TIME
        assert signals[0].severity == SEVERITY_LOW

    def test_high_priority_actions(self):
        signals = map_briefing(
            {
                "headline": "Busy day",
                "action_items": [{"priority": "high", "action": "Do thing"}],
            }
        )
        assert signals[0].severity == SEVERITY_MEDIUM


class TestMapDrift:
    def test_no_items(self):
        assert map_drift({"items": []}) == []

    def test_high_severity_items(self):
        signals = map_drift(
            {
                "items": [
                    {"severity": "high", "description": "Config mismatch"},
                    {"severity": "low", "description": "Minor"},
                ]
            }
        )
        assert len(signals) == 1
        assert signals[0].category == SignalCategory.GOVERNANCE
        assert "drift" in signals[0].title.lower()

    def test_only_low_items(self):
        signals = map_drift({"items": [{"severity": "low", "description": "Minor"}]})
        assert len(signals) == 0


class TestMapGoals:
    def test_no_stale(self):
        assert map_goals({"primary_stale": []}) == []

    def test_stale_goals(self):
        signals = map_goals({"primary_stale": ["conviction-plan", "visual-layer"]})
        assert len(signals) == 1
        assert signals[0].category == SignalCategory.WORK_TASKS
        assert "2 stale goals" in signals[0].title


class TestMapCopilot:
    def test_empty(self):
        assert map_copilot({}) == []
        assert map_copilot({"message": ""}) == []
        assert map_copilot({"message": "short"}) == []  # < 10 chars

    def test_with_message(self):
        signals = map_copilot({"message": "System healthy. Briefing is 2 hours old."})
        assert len(signals) == 1
        assert signals[0].category == SignalCategory.CONTEXT_TIME


class TestMapPerception:
    def test_idle_no_signals(self):
        signals, flow, audio, prod = map_perception(
            {
                "flow_score": 0.0,
                "flow_state": "idle",
                "audio_energy_rms": 0.0,
                "production_activity": "idle",
                "consent_phase": "no_guest",
            }
        )
        assert signals == []
        assert flow == 0.0
        assert not prod

    def test_guest_present(self):
        signals, _, _, _ = map_perception(
            {
                "consent_phase": "pending_consent",
                "flow_score": 0.0,
                "audio_energy_rms": 0.0,
                "production_activity": "idle",
            }
        )
        assert any(s.category == SignalCategory.GOVERNANCE for s in signals)

    def test_music_genre(self):
        signals, _, _, _ = map_perception(
            {
                "music_genre": "trap beat",
                "flow_score": 0.0,
                "audio_energy_rms": 0.0,
                "production_activity": "idle",
                "consent_phase": "no_guest",
            }
        )
        assert any(s.title == "trap beat" for s in signals)

    def test_production_active(self):
        _, _, _, prod = map_perception(
            {
                "production_activity": "production",
                "flow_score": 0.5,
                "audio_energy_rms": 0.3,
                "consent_phase": "no_guest",
            }
        )
        assert prod is True

    def test_empty_dict(self):
        signals, flow, audio, prod = map_perception({})
        assert flow == 0.0
        assert not prod
