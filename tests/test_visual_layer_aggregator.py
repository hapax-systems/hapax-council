"""Tests for visual layer signal aggregator — signal mapping functions."""

from __future__ import annotations

from agents.visual_layer_aggregator import (
    map_biometrics,
    map_briefing,
    map_copilot,
    map_drift,
    map_goals,
    map_gpu,
    map_health,
    map_nudges,
    map_perception,
    map_phone,
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


class TestMapPhone:
    def test_no_phone_data(self):
        assert map_phone({}) == []

    def test_incoming_call(self):
        signals = map_phone({"phone_call_incoming": True, "phone_call_number": "+1234"})
        assert len(signals) == 1
        assert signals[0].category == SignalCategory.PROFILE_STATE
        assert signals[0].severity == SEVERITY_CRITICAL
        assert "+1234" in signals[0].detail

    def test_active_call(self):
        signals = map_phone({"phone_call_active": True})
        assert len(signals) == 1
        assert signals[0].severity == SEVERITY_HIGH
        assert signals[0].category == SignalCategory.PROFILE_STATE
        assert signals[0].title == "On call"

    def test_low_battery(self):
        signals = map_phone({"phone_battery_pct": 10})
        assert len(signals) == 1
        assert signals[0].severity == SEVERITY_HIGH
        assert "10%" in signals[0].detail

    def test_battery_warning(self):
        signals = map_phone({"phone_battery_pct": 25, "phone_battery_charging": False})
        assert len(signals) == 1
        assert signals[0].severity == SEVERITY_MEDIUM

    def test_battery_suppressed_charging(self):
        signals = map_phone({"phone_battery_pct": 25, "phone_battery_charging": True})
        assert signals == []

    def test_sms_unread(self):
        signals = map_phone({"phone_sms_unread": 3, "phone_sms_sender": "Alice"})
        assert len(signals) == 1
        assert signals[0].category == SignalCategory.WORK_TASKS
        assert signals[0].severity == SEVERITY_LOW
        assert "Alice" in signals[0].detail

    def test_notifications_threshold(self):
        assert map_phone({"phone_notification_count": 4}) == []
        signals = map_phone({"phone_notification_count": 5})
        assert len(signals) == 1
        assert signals[0].severity == SEVERITY_LOW

    def test_media_playing(self):
        signals = map_phone(
            {
                "phone_media_playing": True,
                "phone_media_title": "A" * 70,
                "phone_media_artist": "TestArtist",
            }
        )
        assert len(signals) == 1
        assert signals[0].category == SignalCategory.AMBIENT_SENSOR
        assert len(signals[0].detail) <= 60

    def test_kde_disconnected(self):
        # No prior data → no signal
        assert map_phone({"phone_kde_connected": False}) == []
        # With prior data → signal
        signals = map_phone({"phone_kde_connected": False, "phone_battery_pct": 80})
        battery_signals = [s for s in signals if s.source_id == "phone_kde"]
        assert len(battery_signals) == 1
        assert battery_signals[0].category == SignalCategory.HEALTH_INFRA
        assert battery_signals[0].severity == SEVERITY_MEDIUM

    def test_biometrics_phone_fields(self):
        bio = map_biometrics({"phone_battery_pct": 72, "phone_kde_connected": True})
        assert bio.phone_battery_pct == 72
        assert bio.phone_connected is True
