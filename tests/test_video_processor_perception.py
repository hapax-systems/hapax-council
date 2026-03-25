"""Tests for perception-informed video segment classification."""

from __future__ import annotations

from agents.video_processor import (
    _aggregate_perception_minutes,
    _classify_from_perception,
    _parse_segment_timestamp,
)


class TestParseSegmentTimestamp:
    def test_standard_format(self):
        ts = _parse_segment_timestamp("brio-operator_20260324-154619_0233.mkv")
        assert ts is not None
        assert isinstance(ts, float)
        assert ts > 0

    def test_invalid_format(self):
        assert _parse_segment_timestamp("bad-filename.mkv") is None

    def test_missing_timestamp(self):
        assert _parse_segment_timestamp("noparts.mkv") is None


def _minute(
    *,
    activity: str = "coding",
    flow_mean: float = 0.5,
    operator_present: bool = True,
    person_count_max: int = 1,
    consent_phase: str = "no_guest",
    voice_active: bool = False,
    audio_mean: float = 0.01,
    stress_elevated: bool = False,
    hr_mean: float = 70.0,
) -> dict:
    return {
        "timestamp": 1711303560.0,
        "activity": activity,
        "flow_mean": flow_mean,
        "operator_present": operator_present,
        "person_count_max": person_count_max,
        "consent_phase": consent_phase,
        "voice_active": voice_active,
        "audio_mean": audio_mean,
        "stress_elevated": stress_elevated,
        "hr_mean": hr_mean,
    }


class TestAggregatePerceptionMinutes:
    def test_single_minute(self):
        agg = _aggregate_perception_minutes([_minute()])
        assert agg["operator_present"] is True
        assert agg["person_count_max"] == 1
        assert agg["activity_mode"] == "coding"

    def test_mixed_presence(self):
        minutes = [
            _minute(operator_present=True),
            _minute(operator_present=False),
            _minute(operator_present=True),
        ]
        agg = _aggregate_perception_minutes(minutes)
        assert agg["operator_present"] is True
        assert abs(agg["operator_present_ratio"] - 2 / 3) < 0.01

    def test_activity_changed(self):
        minutes = [
            _minute(activity="coding"),
            _minute(activity="producing"),
        ]
        agg = _aggregate_perception_minutes(minutes)
        assert agg["activity_changed"] is True

    def test_no_activity_change(self):
        minutes = [_minute(activity="coding")] * 3
        agg = _aggregate_perception_minutes(minutes)
        assert agg["activity_changed"] is False


class TestClassifyFromPerception:
    def test_production_session(self):
        agg = _aggregate_perception_minutes(
            [
                _minute(activity="producing", flow_mean=0.7, operator_present=True),
            ]
            * 5
        )
        result = _classify_from_perception(agg)
        assert result.category == "production_session"
        assert result.value_score == 1.0

    def test_conversation_requires_consent(self):
        agg = _aggregate_perception_minutes(
            [
                _minute(person_count_max=3, consent_phase="consent_granted"),
            ]
            * 5
        )
        result = _classify_from_perception(agg)
        assert result.category == "conversation"
        assert result.value_score == 0.8

    def test_multiple_people_without_consent_not_conversation(self):
        agg = _aggregate_perception_minutes(
            [
                _minute(person_count_max=3, consent_phase="no_guest"),
            ]
            * 5
        )
        result = _classify_from_perception(agg)
        # Should NOT be conversation without consent
        assert result.category != "conversation"

    def test_active_work(self):
        agg = _aggregate_perception_minutes(
            [
                _minute(activity="coding", flow_mean=0.5, operator_present=True),
            ]
            * 5
        )
        result = _classify_from_perception(agg)
        assert result.category == "active_work"
        assert result.value_score == 0.6

    def test_idle_occupied(self):
        agg = _aggregate_perception_minutes(
            [
                _minute(activity="idle", flow_mean=0.1, operator_present=True),
            ]
            * 5
        )
        result = _classify_from_perception(agg)
        assert result.category == "idle_occupied"
        assert result.value_score == 0.3

    def test_empty_room(self):
        agg = _aggregate_perception_minutes(
            [
                _minute(operator_present=False, activity=""),
            ]
            * 5
        )
        result = _classify_from_perception(agg)
        assert result.category == "empty_room"
        assert result.value_score == 0.0

    def test_voice_active_bonus(self):
        agg = _aggregate_perception_minutes(
            [
                _minute(activity="coding", flow_mean=0.5, voice_active=True),
            ]
            * 5
        )
        result = _classify_from_perception(agg)
        assert result.value_score == 0.7  # 0.6 base + 0.1 voice bonus

    def test_activity_transition_bonus(self):
        minutes = [
            _minute(activity="coding", flow_mean=0.5),
            _minute(activity="coding", flow_mean=0.5),
            _minute(activity="producing", flow_mean=0.5),
            _minute(activity="coding", flow_mean=0.5),
            _minute(activity="coding", flow_mean=0.5),
        ]
        agg = _aggregate_perception_minutes(minutes)
        result = _classify_from_perception(agg)
        assert result.value_score == 0.7  # 0.6 base + 0.1 transition bonus
