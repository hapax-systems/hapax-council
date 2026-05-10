"""Tests for the CLAP audio grounding daemon."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from agents.audio_grounding.__main__ import (
    CAPTURE_DURATION_S,
    CONFIDENCE_THRESHOLD,
    GENRE_LABELS,
    SCENE_LABELS,
    SOURCE,
    _classify_scene,
    _write_state,
)


class TestClassifyScene:
    def _make_probs(self, dominant: str, score: float = 0.6) -> dict[str, float]:
        remaining = 1.0 - score
        per_other = remaining / (len(SCENE_LABELS) - 1)
        return {label: (score if label == dominant else per_other) for label in SCENE_LABELS}

    def test_silence_detected(self) -> None:
        probs = self._make_probs("silence", 0.7)
        result = _classify_scene(probs)
        assert result["scene"] == "silence"
        assert result["scene_label"] == "silence"
        assert result["scene_confidence"] == pytest.approx(0.7, abs=0.01)
        assert result["genre"] is None

    def test_speech_detected(self) -> None:
        probs = self._make_probs("speech or conversation", 0.5)
        result = _classify_scene(probs)
        assert result["scene"] == "speech"
        assert result["genre"] is None

    def test_typing_detected(self) -> None:
        probs = self._make_probs("keyboard typing on a mechanical keyboard", 0.4)
        result = _classify_scene(probs)
        assert result["scene"] == "typing"

    def test_ambient_detected(self) -> None:
        probs = self._make_probs("ambient room noise", 0.5)
        result = _classify_scene(probs)
        assert result["scene"] == "ambient"

    def test_music_genre_detected(self) -> None:
        probs = self._make_probs("jazz music", 0.55)
        result = _classify_scene(probs)
        assert result["scene"] == "music"
        assert result["genre"] == "jazz music"
        assert result["music_score"] > 0.55

    def test_music_score_aggregates_all_genres(self) -> None:
        probs = {label: 0.0 for label in SCENE_LABELS}
        probs["rock music"] = 0.3
        probs["electronic music"] = 0.2
        probs["jazz music"] = 0.1
        total = sum(probs.values())
        probs = {k: v / total for k, v in probs.items()} if total > 0 else probs
        result = _classify_scene(probs)
        assert result["music_score"] > 0.5

    def test_labels_above_threshold_filtered(self) -> None:
        probs = self._make_probs("silence", 0.8)
        result = _classify_scene(probs)
        for _label, score in result["labels_above_threshold"].items():
            assert score >= CONFIDENCE_THRESHOLD

    def test_all_genre_labels_in_scene_labels(self) -> None:
        for genre in GENRE_LABELS:
            assert genre in SCENE_LABELS


class TestWriteState:
    def test_writes_valid_json(self, tmp_path: Path) -> None:
        shm_dir = tmp_path / "hapax-audio-grounding"
        shm_file = shm_dir / "state.json"
        with (
            patch("agents.audio_grounding.__main__.SHM_DIR", shm_dir),
            patch("agents.audio_grounding.__main__.SHM_FILE", shm_file),
        ):
            classification = {
                "scene": "music",
                "scene_label": "jazz music",
                "scene_confidence": 0.85,
                "genre": "jazz music",
                "music_score": 0.90,
                "labels_above_threshold": {"jazz music": 0.85},
            }
            _write_state(classification)
            data = json.loads(shm_file.read_text())
            assert data["scene"] == "music"
            assert data["genre"] == "jazz music"
            assert data["source"] == SOURCE
            assert data["capture_duration_s"] == CAPTURE_DURATION_S
            assert "timestamp" in data
            assert abs(data["timestamp"] - time.time()) < 5

    def test_writes_error_field(self, tmp_path: Path) -> None:
        shm_dir = tmp_path / "hapax-audio-grounding"
        shm_file = shm_dir / "state.json"
        with (
            patch("agents.audio_grounding.__main__.SHM_DIR", shm_dir),
            patch("agents.audio_grounding.__main__.SHM_FILE", shm_file),
        ):
            _write_state({}, error="parecord not found")
            data = json.loads(shm_file.read_text())
            assert data["error"] == "parecord not found"

    def test_atomic_write(self, tmp_path: Path) -> None:
        shm_dir = tmp_path / "hapax-audio-grounding"
        shm_file = shm_dir / "state.json"
        with (
            patch("agents.audio_grounding.__main__.SHM_DIR", shm_dir),
            patch("agents.audio_grounding.__main__.SHM_FILE", shm_file),
        ):
            _write_state({"scene": "silence"})
            assert shm_file.exists()
            assert not shm_file.with_suffix(".tmp").exists()


class TestCaptureAndClassify:
    def test_capture_failure_writes_error(self, tmp_path: Path) -> None:
        from agents.audio_grounding.__main__ import _capture_and_classify

        shm_dir = tmp_path / "hapax-audio-grounding"
        shm_file = shm_dir / "state.json"
        with (
            patch("agents.audio_grounding.__main__.SHM_DIR", shm_dir),
            patch("agents.audio_grounding.__main__.SHM_FILE", shm_file),
            patch(
                "agents.audio_grounding.__main__._capture_parecord",
                side_effect=__import__(
                    "agents.audio_health.probes", fromlist=["ProbeError"]
                ).ProbeError("no sink"),
            ),
        ):
            _capture_and_classify()
            data = json.loads(shm_file.read_text())
            assert "error" in data

    def test_successful_classification(self, tmp_path: Path) -> None:
        from agents.audio_grounding.__main__ import _capture_and_classify

        shm_dir = tmp_path / "hapax-audio-grounding"
        shm_file = shm_dir / "state.json"
        raw_pcm = np.zeros(48000 * 5 * 2, dtype=np.int16).tobytes()

        mock_probs = {label: 1.0 / len(SCENE_LABELS) for label in SCENE_LABELS}
        mock_probs["silence"] = 0.7
        total = sum(mock_probs.values())
        mock_probs = {k: v / total for k, v in mock_probs.items()}

        with (
            patch("agents.audio_grounding.__main__.SHM_DIR", shm_dir),
            patch("agents.audio_grounding.__main__.SHM_FILE", shm_file),
            patch(
                "agents.audio_grounding.__main__._capture_parecord",
                return_value=raw_pcm,
            ),
            patch(
                "agents.audio_grounding.__main__.classify_zero_shot",
                return_value=mock_probs,
            ),
        ):
            _capture_and_classify()
            data = json.loads(shm_file.read_text())
            assert data["scene"] == "silence"
            assert "error" not in data
            assert "timestamp" in data


class TestDaemonSignals:
    def test_signal_handler_sets_shutdown(self) -> None:
        from agents.audio_grounding import __main__ as mod

        mod._shutdown = False
        mod._handle_signal(15, None)
        assert mod._shutdown is True
        mod._shutdown = False


class TestLabelIntegrity:
    def test_no_duplicate_labels(self) -> None:
        assert len(SCENE_LABELS) == len(set(SCENE_LABELS))

    def test_genre_labels_subset_of_scene_labels(self) -> None:
        assert GENRE_LABELS.issubset(set(SCENE_LABELS))

    def test_minimum_label_count(self) -> None:
        assert len(SCENE_LABELS) >= 5
