"""Tests for the unified audio perception daemon."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np


class TestClassifyScene:
    def test_speech_detection(self):
        from agents.audio_perception.__main__ import _classify_scene

        probs = {
            "silence": 0.05,
            "speech or conversation": 0.7,
            "keyboard typing on a mechanical keyboard": 0.1,
            "ambient room noise": 0.05,
            "rock music": 0.02,
            "electronic music": 0.02,
            "jazz music": 0.01,
            "classical music": 0.01,
            "hip hop music": 0.01,
            "pop music": 0.01,
            "folk or acoustic music": 0.01,
            "metal music": 0.005,
            "ambient or drone music": 0.005,
        }
        result = _classify_scene(probs)
        assert result["scene"] == "speech"
        assert result["music_playing"] is False
        assert result["confidence"] == 0.7

    def test_music_detection(self):
        from agents.audio_perception.__main__ import _classify_scene

        probs = {
            "silence": 0.02,
            "speech or conversation": 0.05,
            "keyboard typing on a mechanical keyboard": 0.01,
            "ambient room noise": 0.02,
            "rock music": 0.6,
            "electronic music": 0.1,
            "jazz music": 0.05,
            "classical music": 0.02,
            "hip hop music": 0.02,
            "pop music": 0.02,
            "folk or acoustic music": 0.03,
            "metal music": 0.03,
            "ambient or drone music": 0.03,
        }
        result = _classify_scene(probs)
        assert result["scene"] == "music"
        assert result["music_playing"] is True
        assert result["genre"] == "rock music"

    def test_silence_detection(self):
        from agents.audio_perception.__main__ import _classify_scene

        probs = {
            label: 0.02
            for label in [
                "speech or conversation",
                "keyboard typing on a mechanical keyboard",
                "ambient room noise",
                "rock music",
                "electronic music",
                "jazz music",
                "classical music",
                "hip hop music",
                "pop music",
                "folk or acoustic music",
                "metal music",
                "ambient or drone music",
            ]
        }
        probs["silence"] = 0.8
        result = _classify_scene(probs)
        assert result["scene"] == "silence"
        assert result["music_playing"] is False


class TestWriteState:
    def test_atomic_write(self, tmp_path: Path):
        from agents.audio_perception.__main__ import _write_state

        shm_dir = tmp_path / "hapax-perception"
        shm_file = shm_dir / "audio.json"

        with (
            patch("agents.audio_perception.__main__.SHM_DIR", shm_dir),
            patch("agents.audio_perception.__main__.SHM_FILE", shm_file),
        ):
            _write_state({"scene": "speech", "is_speech": True, "music_playing": False})

        assert shm_file.exists()
        data = json.loads(shm_file.read_text())
        assert data["scene"] == "speech"
        assert data["is_speech"] is True
        assert "timestamp" in data
        assert not (shm_dir / "audio.json.tmp").exists()

    def test_error_field(self, tmp_path: Path):
        from agents.audio_perception.__main__ import _write_state

        shm_dir = tmp_path / "hapax-perception"
        shm_file = shm_dir / "audio.json"

        with (
            patch("agents.audio_perception.__main__.SHM_DIR", shm_dir),
            patch("agents.audio_perception.__main__.SHM_FILE", shm_file),
        ):
            _write_state({"scene": "error"}, error="capture failed")

        data = json.loads(shm_file.read_text())
        assert data["error"] == "capture failed"


class TestOutputSchema:
    def test_all_required_fields_present(self, tmp_path: Path):
        from agents.audio_perception.__main__ import _write_state

        shm_dir = tmp_path / "hapax-perception"
        shm_file = shm_dir / "audio.json"

        payload = {
            "is_speech": True,
            "speech_ratio": 0.6,
            "speaker_id": None,
            "music_playing": False,
            "bpm": None,
            "key": None,
            "scene": "speech",
            "scene_label": "speech or conversation",
            "confidence": 0.85,
            "genre": None,
            "music_score": 0.05,
            "vad_available": True,
        }

        with (
            patch("agents.audio_perception.__main__.SHM_DIR", shm_dir),
            patch("agents.audio_perception.__main__.SHM_FILE", shm_file),
        ):
            _write_state(payload)

        data = json.loads(shm_file.read_text())
        required = {
            "is_speech",
            "speaker_id",
            "music_playing",
            "bpm",
            "key",
            "scene",
            "confidence",
            "timestamp",
        }
        assert required.issubset(data.keys())


class TestAnalyzeMusic:
    def test_returns_bpm_and_key(self):
        from agents.audio_perception.__main__ import _analyze_music

        sr = 22050
        duration = 5
        n_samples = sr * duration
        t = np.linspace(0, duration, n_samples, endpoint=False)
        waveform = np.sin(2 * np.pi * 440 * t).astype(np.float32)
        bpm_target = 120
        beat_interval = sr * 60 // bpm_target
        for i in range(0, n_samples, beat_interval):
            end = min(i + 200, n_samples)
            waveform[i:end] += 0.8

        result = _analyze_music(waveform, sr)
        assert result["bpm"] is None or isinstance(result["bpm"], int)
        assert result["key"] is None or result["key"] in [
            "C",
            "C#",
            "D",
            "D#",
            "E",
            "F",
            "F#",
            "G",
            "G#",
            "A",
            "A#",
            "B",
        ]

    def test_failure_returns_none(self):
        from agents.audio_perception.__main__ import _analyze_music

        result = _analyze_music(np.zeros(100, dtype=np.float32), 22050)
        assert "bpm" in result
        assert "key" in result
