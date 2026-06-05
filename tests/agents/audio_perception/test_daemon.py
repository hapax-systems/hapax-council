"""Tests for audio_perception daemon — spectral fallback and ML-enhanced perception."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

from agents.audio_perception.daemon import (
    CAPTURE_DURATION_S,
    CAPTURE_STAGE,
    SAMPLE_RATE,
    AudioPerceptionState,
    _capture_audio,
    _spectral_bpm,
    _spectral_features,
    _spectral_scene,
    perceive_once,
    write_state,
)


class TestSpectralFeatures:
    def test_silence_returns_low_rms(self) -> None:
        silence = np.zeros(SAMPLE_RATE, dtype=np.int16)
        features = _spectral_features(silence)
        assert features["rms_dbfs"] == -120.0

    def test_voice_band_dominant(self) -> None:
        t = np.linspace(0, 1.0, SAMPLE_RATE, endpoint=False)
        tone_500hz = (np.sin(2 * np.pi * 500 * t) * 16000).astype(np.int16)
        features = _spectral_features(tone_500hz)
        assert features["voice_ratio"] > 0.5
        assert features["rms_dbfs"] > -20

    def test_high_frequency_is_not_voice(self) -> None:
        t = np.linspace(0, 1.0, SAMPLE_RATE, endpoint=False)
        tone_10khz = (np.sin(2 * np.pi * 10000 * t) * 16000).astype(np.int16)
        features = _spectral_features(tone_10khz)
        assert features["voice_ratio"] < 0.2


class TestSpectralScene:
    def test_silence(self) -> None:
        scene, conf = _spectral_scene({"rms_dbfs": -60, "voice_ratio": 0, "music_ratio": 0})
        assert scene == "silence"

    def test_speech(self) -> None:
        scene, _ = _spectral_scene({"rms_dbfs": -20, "voice_ratio": 0.6, "music_ratio": 0.1})
        assert scene == "speech"

    def test_music(self) -> None:
        scene, _ = _spectral_scene({"rms_dbfs": -20, "voice_ratio": 0.1, "music_ratio": 0.5})
        assert scene == "music"

    def test_speech_over_music(self) -> None:
        scene, _ = _spectral_scene({"rms_dbfs": -20, "voice_ratio": 0.35, "music_ratio": 0.25})
        assert scene == "speech_over_music"

    def test_ambient(self) -> None:
        scene, _ = _spectral_scene({"rms_dbfs": -30, "voice_ratio": 0.15, "music_ratio": 0.1})
        assert scene == "ambient"


class TestSpectralBPM:
    def test_returns_none_for_short_audio(self) -> None:
        short = np.zeros(1000, dtype=np.int16)
        assert _spectral_bpm(short) is None

    def test_returns_none_for_silence(self) -> None:
        silence = np.zeros(96000, dtype=np.int16)
        assert _spectral_bpm(silence) is None

    def test_detects_periodic_signal(self) -> None:
        sr = SAMPLE_RATE
        dur = 4.0
        bpm_target = 120
        t = np.linspace(0, dur, int(sr * dur), endpoint=False)
        beat_freq = bpm_target / 60.0
        signal = (np.sin(2 * np.pi * beat_freq * t) * 8000).astype(np.int16)
        bpm = _spectral_bpm(signal)
        if bpm is not None:
            assert 40 <= bpm <= 240


class TestCaptureAudio:
    def test_uses_persistent_probe_set_at_native_rate(self) -> None:
        samples = np.arange(int(SAMPLE_RATE * CAPTURE_DURATION_S), dtype=np.int16)

        class StubProbeSet:
            captured_stage: str | None = None

            def capture(self, stage: str) -> SimpleNamespace:
                self.captured_stage = stage
                return SimpleNamespace(ok=True, error=None, samples_mono=samples)

        probe_set = StubProbeSet()
        result = _capture_audio(probe_set=probe_set)  # type: ignore[arg-type]

        assert probe_set.captured_stage == CAPTURE_STAGE
        np.testing.assert_array_equal(result, samples)


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
        with patch("agents.audio_perception.daemon._capture_audio", return_value=None):
            state = perceive_once(clap=None, essentia=None, pyannote=None)
        assert state.scene == "capture_failed"
        assert state.confidence == 0.0
        assert state.is_speech is False

    def test_spectral_fallback_when_no_models(self) -> None:
        t = np.linspace(0, 2.0, int(SAMPLE_RATE * 2), endpoint=False)
        tone = (np.sin(2 * np.pi * 500 * t) * 16000).astype(np.int16)
        with patch("agents.audio_perception.daemon._capture_audio", return_value=tone):
            state = perceive_once(clap=None, essentia=None, pyannote=None)
        assert state.scene in ("speech", "ambient", "music", "silence", "speech_over_music")
        assert state.confidence > 0
        assert state.speaker_id is None
        assert state.key is None

    def test_clap_result_used_when_available(self) -> None:
        t = np.linspace(0, 2.0, int(SAMPLE_RATE * 2), endpoint=False)
        tone = (np.sin(2 * np.pi * 500 * t) * 16000).astype(np.int16)
        mock_clap = MagicMock()
        mock_clap.classify.return_value = ("music", 0.92)
        with patch("agents.audio_perception.daemon._capture_audio", return_value=tone):
            state = perceive_once(clap=mock_clap, essentia=None, pyannote=None)
        assert state.scene == "music"
        assert state.confidence == 0.92
        assert state.music_playing is True

    def test_essentia_result_used_when_available(self) -> None:
        t = np.linspace(0, 2.0, int(SAMPLE_RATE * 2), endpoint=False)
        tone = (np.sin(2 * np.pi * 500 * t) * 16000).astype(np.int16)
        mock_essentia = MagicMock()
        mock_essentia.analyze.return_value = {"bpm": 128, "key": "C minor", "rms_dbfs": -12.5}
        mock_clap = MagicMock()
        mock_clap.classify.return_value = ("music", 0.85)
        with patch("agents.audio_perception.daemon._capture_audio", return_value=tone):
            state = perceive_once(clap=mock_clap, essentia=mock_essentia, pyannote=None)
        assert state.bpm == 128
        assert state.key == "C minor"
        assert state.rms_dbfs == -12.5

    def test_pyannote_called_for_speech(self) -> None:
        t = np.linspace(0, 2.0, int(SAMPLE_RATE * 2), endpoint=False)
        tone = (np.sin(2 * np.pi * 500 * t) * 16000).astype(np.int16)
        mock_clap = MagicMock()
        mock_clap.classify.return_value = ("speech", 0.9)
        mock_pyannote = MagicMock()
        mock_pyannote.segment.return_value = "spk_0"
        with patch("agents.audio_perception.daemon._capture_audio", return_value=tone):
            state = perceive_once(clap=mock_clap, essentia=None, pyannote=mock_pyannote)
        assert state.speaker_id == "spk_0"
        assert state.is_speech is True
        mock_pyannote.segment.assert_called_once()

    def test_pyannote_skipped_for_music(self) -> None:
        t = np.linspace(0, 2.0, int(SAMPLE_RATE * 2), endpoint=False)
        tone = (np.sin(2 * np.pi * 500 * t) * 16000).astype(np.int16)
        mock_clap = MagicMock()
        mock_clap.classify.return_value = ("music", 0.88)
        mock_pyannote = MagicMock()
        with patch("agents.audio_perception.daemon._capture_audio", return_value=tone):
            state = perceive_once(clap=mock_clap, essentia=None, pyannote=mock_pyannote)
        assert state.speaker_id is None
        mock_pyannote.segment.assert_not_called()

    def test_pyannote_skipped_when_flag_set(self) -> None:
        t = np.linspace(0, 2.0, int(SAMPLE_RATE * 2), endpoint=False)
        tone = (np.sin(2 * np.pi * 500 * t) * 16000).astype(np.int16)
        mock_clap = MagicMock()
        mock_clap.classify.return_value = ("speech", 0.9)
        mock_pyannote = MagicMock()
        with patch("agents.audio_perception.daemon._capture_audio", return_value=tone):
            state = perceive_once(
                clap=mock_clap, essentia=None, pyannote=mock_pyannote, skip_pyannote=True
            )
        assert state.speaker_id is None
        mock_pyannote.segment.assert_not_called()

    def test_clap_exception_falls_back_to_spectral(self) -> None:
        t = np.linspace(0, 2.0, int(SAMPLE_RATE * 2), endpoint=False)
        tone = (np.sin(2 * np.pi * 500 * t) * 16000).astype(np.int16)
        mock_clap = MagicMock()
        mock_clap.classify.side_effect = RuntimeError("CLAP failed")
        with patch("agents.audio_perception.daemon._capture_audio", return_value=tone):
            state = perceive_once(clap=mock_clap, essentia=None, pyannote=None)
        assert state.scene in ("speech", "ambient", "music", "silence", "speech_over_music")
        assert state.confidence > 0
