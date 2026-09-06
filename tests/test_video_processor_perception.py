"""Tests for perception-informed video segment classification."""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

from agents import video_processor as video
from agents.video_processor import (
    _aggregate_perception_minutes,
    _classify_from_perception,
    _parse_segment_timestamp,
)
from tests import test_affordance_pipeline as consent_cases
from tests.test_affordance_pipeline import (
    CUSTODY_FAILURES,
    assert_custody_diagnostic,
)

synthetic_custody = consent_cases.synthetic_custody
consent_contract = consent_cases.consent_contract


@pytest.fixture
def guest_segment(monkeypatch, tmp_path):
    segment = tmp_path / "synthetic-camera_20260101-120000_0001.mkv"
    classification = video.SegmentClassification(
        category="conversation",
        value_score=0.9,
        people_count=2,
        max_people=2,
        motion_score=0.4,
        scene_change=True,
        ssim=0.7,
        frame_analyses=[video.FrameAnalysis(people_count=2, face_count=2, body_count=2)],
    )
    monkeypatch.setattr(video, "_classify_segment_dispatch", lambda _: classification)
    monkeypatch.setattr(video, "_upload_to_gdrive", Mock(return_value=True))
    monkeypatch.setattr(video, "CACHE_DIR", tmp_path / "video-cache")
    monkeypatch.setattr(video, "STATE_FILE", tmp_path / "video-cache" / "state.json")
    monkeypatch.setattr(video, "CHANGES_LOG", tmp_path / "video-cache" / "changes.jsonl")
    return segment, classification


def assert_withheld_video(data):
    assert data["category"] == "consent_withheld"
    assert data["consent_status"] == "withheld"
    assert data["disposition"] == "withheld"
    for field in ("value_score", "people_count", "motion_score", "scene_change"):
        assert data[field] is None


@pytest.mark.parametrize("mode", CUSTODY_FAILURES)
@pytest.mark.parametrize("people_count", (1, 2))
def test_sidecar_withholds_all_guest_fields_on_custody_failure(
    mode, people_count, synthetic_custody, consent_contract, guest_segment, caplog
):
    consent_contract(person="guest")
    synthetic_custody["mode"] = mode
    segment, classification = guest_segment
    classification.people_count = people_count
    sidecar = video._write_sidecar(segment, classification, "uploaded", suffix=".processed")
    assert sidecar.suffix == ".classified"
    data = json.loads(sidecar.read_text())
    assert_withheld_video(data)
    assert data["max_people"] is None
    assert data["ssim"] is None
    assert "frame_analyses" not in data
    assert set(data) == {
        "filename",
        "classified_at",
        "category",
        "value_score",
        "people_count",
        "max_people",
        "motion_score",
        "scene_change",
        "ssim",
        "consent_status",
        "disposition",
    }
    assert classification.people_count == people_count
    assert classification.max_people == 2
    assert_custody_diagnostic(caplog.text, mode)


@pytest.mark.parametrize("mode", CUSTODY_FAILURES)
def test_video_processing_caller_withholds_custody_failure(
    mode, synthetic_custody, consent_contract, guest_segment, caplog
):
    consent_contract(person="guest")
    synthetic_custody["mode"] = mode
    segment, classification = guest_segment
    classification.people_count = 1
    state = video.VideoProcessorState()
    info = video._process_segment(segment, state)
    assert_withheld_video(info.model_dump())
    video._upload_to_gdrive.assert_not_called()
    state.processed_files[segment.name] = info
    video._save_state(state)
    assert_withheld_video(json.loads(video.STATE_FILE.read_text())["processed_files"][segment.name])
    sidecar = json.loads(segment.with_suffix(".mkv.classified").read_text())
    assert_withheld_video(sidecar)
    assert sidecar["max_people"] is None
    assert sidecar["ssim"] is None
    change = json.loads(video.CHANGES_LOG.read_text())
    assert change["type"] == "consent_withheld"
    assert not set(change) & set(classification.model_dump())
    assert synthetic_custody["reads"] == 1
    assert_custody_diagnostic(caplog.text, mode)


@pytest.mark.parametrize("allowed", (True, False))
def test_video_valid_custody_controls(
    allowed, synthetic_custody, consent_contract, guest_segment, caplog
):
    consent_contract(person="guest", scope=("video",) if allowed else ("audio",))
    segment, classification = guest_segment
    data = json.loads(video._write_sidecar(segment, classification, "uploaded").read_text())
    info = video._process_segment(segment, video.VideoProcessorState())
    assert video._upload_to_gdrive.call_count == int(allowed)
    assert synthetic_custody["reads"] == 2
    if allowed:
        for field, value in classification.model_dump(exclude={"frame_analyses"}).items():
            assert data[field] == value
        assert info.people_count == 2
        assert info.uploaded is True
    else:
        assert_withheld_video(data)
        assert_withheld_video(info.model_dump())
        assert "consent_no_match: cause_class=NoActiveContract" in caplog.text
        assert "remedy=establish_matching_consent" in caplog.text


@pytest.mark.parametrize("people_count", (0, 1))
def test_video_without_guest_evidence_keeps_permitting(
    people_count, synthetic_custody, guest_segment
):
    synthetic_custody["mode"] = "missing"
    segment, classification = guest_segment
    classification.people_count = classification.max_people = people_count
    data = json.loads(video._write_sidecar(segment, classification, "uploaded").read_text())
    assert data["people_count"] == people_count
    info = video._process_segment(segment, video.VideoProcessorState())
    assert info.uploaded is True
    assert synthetic_custody["reads"] == 0


@pytest.mark.parametrize("stage", ("load", "contract_check"))
def test_video_caller_sanitizes_registry_exceptions(stage, guest_segment, monkeypatch, caplog):
    from shared.governance import consent

    monkeypatch.setattr(
        consent.ConsentRegistry,
        stage,
        Mock(side_effect=RuntimeError("synthetic-private-person-and-path")),
    )
    segment, classification = guest_segment
    info = video._process_segment(segment, video.VideoProcessorState())
    assert_withheld_video(info.model_dump())
    video._upload_to_gdrive.assert_not_called()
    assert "consent_check_failed: cause_class=RuntimeError" in caplog.text
    assert "remedy=restore_consent_registry" in caplog.text
    assert "synthetic-private" not in caplog.text


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

    def test_production_session_beats_conversation(self):
        """Production with a consented guest should be production_session, not conversation."""
        agg = _aggregate_perception_minutes(
            [
                _minute(
                    activity="producing",
                    flow_mean=0.7,
                    operator_present=True,
                    person_count_max=2,
                    consent_phase="consent_granted",
                ),
            ]
            * 5
        )
        result = _classify_from_perception(agg)
        assert result.category == "production_session"
        assert result.value_score == 1.0

    def test_ssim_clamped_to_valid_range(self):
        """ssim must stay in [0.0, 1.0] even with high audio energy."""
        agg = _aggregate_perception_minutes(
            [_minute(audio_mean=1.5, activity="producing", flow_mean=0.7)] * 5
        )
        result = _classify_from_perception(agg)
        assert 0.0 <= result.ssim <= 1.0
        assert 0.0 <= result.motion_score <= 1.0


class TestAggregateEmpty:
    def test_empty_list_no_division_error(self):
        agg = _aggregate_perception_minutes([])
        assert agg["operator_present"] is False
        assert agg["flow_score_mean"] == 0.0
        assert agg["activity_mode"] == ""
