"""Tests for CLAP scene_classification wiring in PerceptualField (GAP-4)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from shared.perceptual_field import (
    SceneClassificationState,
    _read_scene_classification,
    build_perceptual_field,
)


def _write_state(tmp_path: Path, payload: dict) -> Path:
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(payload), encoding="utf-8")
    return state_file


class TestSceneClassificationState:
    def test_model_accepts_valid_classification(self) -> None:
        state = SceneClassificationState(
            scene="music",
            scene_label="rock music",
            scene_confidence=0.82,
            genre="rock music",
            music_score=0.91,
        )
        assert state.scene == "music"
        assert state.genre == "rock music"
        assert state.music_score == 0.91

    def test_model_defaults_to_none(self) -> None:
        state = SceneClassificationState()
        assert state.scene is None
        assert state.scene_confidence is None
        assert state.genre is None

    def test_model_ignores_extra_fields(self) -> None:
        state = SceneClassificationState(
            scene="speech",
            labels_above_threshold={"speech": 0.9},  # type: ignore[call-arg]
        )
        assert state.scene == "speech"


class TestReadSceneClassification:
    def test_reads_valid_state(self, tmp_path: Path) -> None:
        state_file = _write_state(
            tmp_path,
            {
                "scene": "music",
                "scene_label": "electronic music",
                "scene_confidence": 0.78,
                "genre": "electronic music",
                "music_score": 0.85,
                "labels_above_threshold": {"electronic music": 0.78},
                "timestamp": 1778444374.0,
                "source": "hapax-broadcast-normalized",
                "capture_duration_s": 5.0,
            },
        )
        with patch("shared.perceptual_field._AUDIO_GROUNDING_STATE", state_file):
            result = _read_scene_classification()
        assert result.scene == "music"
        assert result.scene_label == "electronic music"
        assert result.scene_confidence == 0.78
        assert result.genre == "electronic music"
        assert result.music_score == 0.85

    def test_returns_empty_on_error_state(self, tmp_path: Path) -> None:
        state_file = _write_state(
            tmp_path,
            {
                "timestamp": 1778444374.0,
                "source": "hapax-broadcast-normalized",
                "capture_duration_s": 5.0,
                "error": "parecord captured 0 bytes",
            },
        )
        with patch("shared.perceptual_field._AUDIO_GROUNDING_STATE", state_file):
            result = _read_scene_classification()
        assert result.scene is None
        assert result.scene_confidence is None

    def test_returns_empty_on_missing_file(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.json"
        with patch("shared.perceptual_field._AUDIO_GROUNDING_STATE", missing):
            result = _read_scene_classification()
        assert result.scene is None


class TestBuildPerceptualFieldIncludesSceneClassification:
    def test_scene_classification_in_audio_field(self, tmp_path: Path) -> None:
        state_file = _write_state(
            tmp_path,
            {
                "scene": "typing",
                "scene_label": "keyboard typing on a mechanical keyboard",
                "scene_confidence": 0.92,
                "genre": None,
                "music_score": 0.03,
                "labels_above_threshold": {},
                "timestamp": 1778444374.0,
                "source": "hapax-broadcast-normalized",
                "capture_duration_s": 5.0,
            },
        )
        with patch("shared.perceptual_field._AUDIO_GROUNDING_STATE", state_file):
            field = build_perceptual_field()
        assert field.audio.scene_classification.scene == "typing"
        assert field.audio.scene_classification.scene_confidence == 0.92

    def test_serializes_in_director_json(self, tmp_path: Path) -> None:
        state_file = _write_state(
            tmp_path,
            {
                "scene": "speech",
                "scene_label": "speech or conversation",
                "scene_confidence": 0.88,
                "genre": None,
                "music_score": 0.01,
                "labels_above_threshold": {},
                "timestamp": 1778444374.0,
                "source": "hapax-broadcast-normalized",
                "capture_duration_s": 5.0,
            },
        )
        with patch("shared.perceptual_field._AUDIO_GROUNDING_STATE", state_file):
            field = build_perceptual_field()
        dumped = json.loads(field.model_dump_json(exclude_none=True))
        sc = dumped["audio"]["scene_classification"]
        assert sc["scene"] == "speech"
        assert sc["scene_confidence"] == 0.88
        assert "genre" not in sc  # None excluded

    def test_missing_grounding_produces_empty_section(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.json"
        with patch("shared.perceptual_field._AUDIO_GROUNDING_STATE", missing):
            field = build_perceptual_field()
        dumped = json.loads(field.model_dump_json(exclude_none=True))
        sc = dumped.get("audio", {}).get("scene_classification", {})
        assert sc == {}
