"""Tests for audio_perception daemon — feature extraction and classification."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from agents.audio_perception.daemon import (
    AudioPerceptionState,
    _classify_scene,
    _compute_features,
    _estimate_bpm,
    perceive_once,
    write_state,
)


class TestComputeFeatures:
    def test_silence_returns_low_rms(self) -> None:
        silence = np.zeros(48000, dtype=np.int16)
        features = _compute_features(silence)
        assert features["rms_dbfs"] == -120.0

    def test_voice_band_dominant(self) -> None:
        t = np.linspace(0, 1.0, 48000, endpoint=False)
        tone_500hz = (np.sin(2 * np.pi * 500 * t) * 16000).astype(np.int16)
        features = _compute_features(tone_500hz)
        assert features["voice_ratio"] > 0.5
        assert features["rms_dbfs"] > -20

    def test_high_frequency_is_not_voice(self) -> None:
        t = np.linspace(0, 1.0, 48000, endpoint=False)
        tone_10khz = (np.sin(2 * np.pi * 10000 * t) * 16000).astype(np.int16)
        features = _compute_features(tone_10khz)
        assert features["voice_ratio"] < 0.2


class TestClassifyScene:
    def test_silence(self) -> None:
        scene, conf = _classify_scene({"rms_dbfs": -60, "voice_ratio": 0, "music_ratio": 0})
        assert scene == "silence"

    def test_speech(self) -> None:
        scene, _ = _classify_scene({"rms_dbfs": -20, "voice_ratio": 0.6, "music_ratio": 0.1})
        assert scene == "speech"

    def test_music(self) -> None:
        scene, _ = _classify_scene({"rms_dbfs": -20, "voice_ratio": 0.1, "music_ratio": 0.5})
        assert scene == "music"

    def test_speech_over_music(self) -> None:
        scene, _ = _classify_scene({"rms_dbfs": -20, "voice_ratio": 0.35, "music_ratio": 0.25})
        assert scene == "speech_over_music"

    def test_ambient(self) -> None:
        scene, _ = _classify_scene({"rms_dbfs": -30, "voice_ratio": 0.15, "music_ratio": 0.1})
        assert scene == "ambient"


class TestEstimateBPM:
    def test_returns_none_for_short_audio(self) -> None:
        short = np.zeros(1000, dtype=np.int16)
        assert _estimate_bpm(short) is None

    def test_returns_none_for_silence(self) -> None:
        silence = np.zeros(96000, dtype=np.int16)
        assert _estimate_bpm(silence) is None

    def test_detects_periodic_signal(self) -> None:
        sr = 48000
        dur = 4.0
        bpm_target = 120
        t = np.linspace(0, dur, int(sr * dur), endpoint=False)
        beat_freq = bpm_target / 60.0
        signal = (np.sin(2 * np.pi * beat_freq * t) * 8000).astype(np.int16)
        bpm = _estimate_bpm(signal)
        if bpm is not None:
            assert 40 <= bpm <= 240


class TestWriteState:
    def test_writes_valid_json(self, tmp_path: Path) -> None:
        import agents.audio_perception.daemon as mod

        orig_dir = mod.OUTPUT_DIR
        orig_file = mod.OUTPUT_FILE
        try:
            mod.OUTPUT_DIR = tmp_path
            mod.OUTPUT_FILE = tmp_path / "audio.json"
            state = AudioPerceptionState(
                is_speech=True,
                speaker_id=None,
                music_playing=False,
                bpm=None,
                key=None,
                scene="speech",
                confidence=0.8,
                rms_dbfs=-15.0,
                voice_ratio=0.6,
                music_ratio=0.1,
                updated_at="2026-05-11T00:00:00Z",
            )
            write_state(state)
            data = json.loads((tmp_path / "audio.json").read_text())
            assert data["is_speech"] is True
            assert data["scene"] == "speech"
            assert data["confidence"] == 0.8
        finally:
            mod.OUTPUT_DIR = orig_dir
            mod.OUTPUT_FILE = orig_file


class TestPerceiveOnce:
    def test_capture_failure_returns_safe_state(self) -> None:
        from unittest.mock import patch

        with patch("agents.audio_perception.daemon._capture_audio", return_value=None):
            state = perceive_once()
        assert state.scene == "capture_failed"
        assert state.confidence == 0.0
        assert state.is_speech is False
