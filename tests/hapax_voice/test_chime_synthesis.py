"""Tests for chime WAV synthesis."""
import wave
from pathlib import Path

import numpy as np
import pytest

from agents.hapax_voice.chime_synthesis import synthesize_chime, generate_all_chimes, CHIME_SPECS


class TestSynthesizeChime:
    """Test individual chime synthesis."""

    def test_returns_numpy_array(self):
        audio = synthesize_chime("activation")
        assert isinstance(audio, np.ndarray)
        assert audio.dtype == np.int16

    def test_activation_duration(self):
        """Activation chime should be ~350ms at 48kHz."""
        audio = synthesize_chime("activation")
        duration_ms = len(audio) / 48000 * 1000
        assert 340 <= duration_ms <= 360

    def test_deactivation_duration(self):
        """Deactivation chime should be ~280ms."""
        audio = synthesize_chime("deactivation")
        duration_ms = len(audio) / 48000 * 1000
        assert 270 <= duration_ms <= 290

    def test_error_duration(self):
        """Error chime should be ~200ms."""
        audio = synthesize_chime("error")
        duration_ms = len(audio) / 48000 * 1000
        assert 190 <= duration_ms <= 210

    def test_completion_duration(self):
        """Completion chime should be ~150ms."""
        audio = synthesize_chime("completion")
        duration_ms = len(audio) / 48000 * 1000
        assert 140 <= duration_ms <= 160

    def test_peak_amplitude_within_bounds(self):
        """Audio should be normalized to avoid clipping."""
        audio = synthesize_chime("activation")
        peak = np.max(np.abs(audio))
        assert peak > 15000, "Audio too quiet"
        assert peak <= 32767, "Audio clipping"

    def test_unknown_chime_raises(self):
        with pytest.raises(KeyError):
            synthesize_chime("nonexistent")

    def test_chime_specs_has_all_types(self):
        assert set(CHIME_SPECS.keys()) == {"activation", "deactivation", "error", "completion"}


class TestGenerateAllChimes:
    """Test batch WAV file generation."""

    def test_generates_four_wav_files(self, tmp_path):
        generate_all_chimes(tmp_path)
        wav_files = sorted(tmp_path.glob("*.wav"))
        assert len(wav_files) == 4
        names = {f.stem for f in wav_files}
        assert names == {"activation", "deactivation", "error", "completion"}

    def test_wav_format_correct(self, tmp_path):
        generate_all_chimes(tmp_path)
        with wave.open(str(tmp_path / "activation.wav"), "rb") as f:
            assert f.getnchannels() == 1
            assert f.getsampwidth() == 2
            assert f.getframerate() == 48000

    def test_wav_not_empty(self, tmp_path):
        generate_all_chimes(tmp_path)
        for wav_file in tmp_path.glob("*.wav"):
            assert wav_file.stat().st_size > 100, f"{wav_file.name} is too small"
