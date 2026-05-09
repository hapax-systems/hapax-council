"""Tests for AVSDLC-002 — audio self-perception loop.

Validates:
1. Spectral analyzer: RMS, centroid, balance, V/M/E ratios
2. Stimmung integration: 4 new audio dimensions, update round-trip,
   mapping semantics (0=good, 1=bad), weight class, stance computation
3. VLA wiring: SHM reader injects into stimmung collector
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

# ── Analyzer tests ──────────────────────────────────────────────────────


class TestAnalyzerEmpty:
    def test_empty_input(self):
        from agents.audio_self_perception.analyzer import analyze

        result = analyze(np.array([], dtype=np.int16))
        assert result.rms_dbfs == -120.0
        assert result.spectral_centroid_hz == 0.0
        assert result.sample_count == 0

    def test_single_sample(self):
        from agents.audio_self_perception.analyzer import analyze

        result = analyze(np.array([100], dtype=np.int16))
        assert result.sample_count == 0


class TestAnalyzerSineWave:
    def _sine(self, freq_hz: float, duration_s: float = 1.0, sr: int = 48000) -> np.ndarray:
        t = np.arange(int(sr * duration_s)) / sr
        return (np.sin(2 * np.pi * freq_hz * t) * 16000).astype(np.int16)

    def test_centroid_near_frequency(self):
        from agents.audio_self_perception.analyzer import analyze

        samples = self._sine(1000.0)
        result = analyze(samples, sample_rate=48000)
        assert 900 < result.spectral_centroid_hz < 1100

    def test_high_frequency_centroid(self):
        from agents.audio_self_perception.analyzer import analyze

        low = analyze(self._sine(500.0), sample_rate=48000)
        high = analyze(self._sine(5000.0), sample_rate=48000)
        assert high.spectral_centroid_hz > low.spectral_centroid_hz

    def test_rms_reasonable(self):
        from agents.audio_self_perception.analyzer import analyze

        result = analyze(self._sine(1000.0))
        assert -20 < result.rms_dbfs < 0

    def test_voice_band_sine_has_high_voice_ratio(self):
        from agents.audio_self_perception.analyzer import analyze

        result = analyze(self._sine(1000.0))
        assert result.voice_ratio > 0.5

    def test_low_freq_sine_has_low_voice_ratio(self):
        from agents.audio_self_perception.analyzer import analyze

        result = analyze(self._sine(50.0))
        assert result.voice_ratio < 0.3


class TestAnalyzerNoise:
    def test_white_noise_ratio_reflects_bandwidth(self):
        from agents.audio_self_perception.analyzer import analyze

        rng = np.random.default_rng(42)
        noise = (rng.standard_normal(48000) * 8000).astype(np.int16)
        result = analyze(noise, sample_rate=48000)
        # White noise: equal energy/Hz, so ratio ≈ low_bw/high_bw ≈ 1000/23000 ≈ 0.04
        assert 0.01 < result.low_high_ratio < 0.15

    def test_white_noise_diverse_mix(self):
        from agents.audio_self_perception.analyzer import analyze

        rng = np.random.default_rng(42)
        noise = (rng.standard_normal(48000) * 8000).astype(np.int16)
        result = analyze(noise, sample_rate=48000)
        assert result.voice_ratio > 0.1
        assert result.music_ratio > 0.1
        assert result.env_ratio > 0.1


class TestAnalyzerSilence:
    def test_silence_floor(self):
        from agents.audio_self_perception.analyzer import analyze

        silence = np.zeros(48000, dtype=np.int16)
        result = analyze(silence)
        assert result.rms_dbfs == -120.0


class TestAnalyzerBalance:
    def test_low_freq_dominated_has_high_ratio(self):
        from agents.audio_self_perception.analyzer import analyze

        t = np.arange(48000) / 48000.0
        low = (np.sin(2 * np.pi * 100 * t) * 16000).astype(np.int16)
        result = analyze(low)
        assert result.low_high_ratio > 5.0

    def test_high_freq_dominated_has_low_ratio(self):
        from agents.audio_self_perception.analyzer import analyze

        t = np.arange(48000) / 48000.0
        high = (np.sin(2 * np.pi * 8000 * t) * 16000).astype(np.int16)
        result = analyze(high)
        assert result.low_high_ratio < 0.2


# ── Daemon configuration tests ─────────────────────────────────────────


class TestDaemonConfig:
    def test_default_target_is_normalized_broadcast_egress(self):
        from agents.audio_self_perception import __main__ as daemon

        assert daemon.DEFAULT_TARGET_STAGE == "hapax-broadcast-normalized"

    def test_state_write_includes_source(self, monkeypatch, tmp_path):
        from agents.audio_self_perception import __main__ as daemon

        state_file = tmp_path / "state.json"
        monkeypatch.setattr(daemon, "SHM_DIR", tmp_path)
        monkeypatch.setattr(daemon, "SHM_FILE", state_file)
        monkeypatch.setattr(daemon, "TARGET_STAGE", "hapax-broadcast-normalized")

        daemon._write_state({"rms_dbfs": -20.0})

        payload = json.loads(state_file.read_text(encoding="utf-8"))
        assert payload["stage"] == "hapax-broadcast-normalized"
        assert payload["source"] == "hapax-broadcast-normalized"

    def test_systemd_unit_has_no_unsatisfied_watchdog(self):
        unit = Path("systemd/units/hapax-audio-self-perception.service").read_text(encoding="utf-8")

        assert "WatchdogSec" not in unit
        assert "HAPAX_AUDIO_SELF_PERCEPTION_STAGE=hapax-broadcast-normalized" in unit


# ── Stimmung dimension tests ───────────────────────────────────────────


class TestStimmungAudioDimensions:
    def test_fields_present(self):
        from shared.stimmung import DimensionReading, SystemStimmung

        stim = SystemStimmung()
        for name in [
            "audio_signal_presence",
            "audio_spectral_centroid",
            "audio_spectral_balance",
            "audio_content_mix",
        ]:
            assert hasattr(stim, name)
            assert isinstance(getattr(stim, name), DimensionReading)

    def test_in_dimension_names(self):
        from shared.stimmung import _AUDIO_DIMENSION_NAMES, _DIMENSION_NAMES

        for name in _AUDIO_DIMENSION_NAMES:
            assert name in _DIMENSION_NAMES

    def test_audio_weight_class(self):
        from shared.stimmung import _AUDIO_DIMENSION_NAMES

        assert len(_AUDIO_DIMENSION_NAMES) == 4
        assert "audio_signal_presence" in _AUDIO_DIMENSION_NAMES
        assert "audio_spectral_centroid" in _AUDIO_DIMENSION_NAMES
        assert "audio_spectral_balance" in _AUDIO_DIMENSION_NAMES
        assert "audio_content_mix" in _AUDIO_DIMENSION_NAMES


class TestStimmungAudioUpdate:
    def _collector(self):
        from shared.stimmung import StimmungCollector

        return StimmungCollector(enable_exploration=False)

    def test_healthy_signal_yields_low_presence_pressure(self):
        c = self._collector()
        c.update_audio_perception(rms_dbfs=-20.0)
        snap = c.snapshot()
        assert snap.audio_signal_presence.value < 0.2

    def test_silent_signal_yields_high_presence_pressure(self):
        c = self._collector()
        c.update_audio_perception(rms_dbfs=-60.0)
        snap = c.snapshot()
        assert snap.audio_signal_presence.value > 0.9

    def test_balanced_centroid_low_pressure(self):
        c = self._collector()
        c.update_audio_perception(spectral_centroid_hz=1500.0)
        snap = c.snapshot()
        assert snap.audio_spectral_centroid.value < 0.1

    def test_extreme_centroid_high_pressure(self):
        c = self._collector()
        c.update_audio_perception(spectral_centroid_hz=10000.0)
        snap = c.snapshot()
        assert snap.audio_spectral_centroid.value > 0.5

    def test_balanced_ratio_low_pressure(self):
        c = self._collector()
        c.update_audio_perception(low_high_ratio=1.0)
        snap = c.snapshot()
        assert snap.audio_spectral_balance.value < 0.1

    def test_skewed_ratio_high_pressure(self):
        c = self._collector()
        c.update_audio_perception(low_high_ratio=10.0)
        snap = c.snapshot()
        assert snap.audio_spectral_balance.value > 0.5

    def test_diverse_mix_low_pressure(self):
        c = self._collector()
        c.update_audio_perception(
            voice_ratio=0.33,
            music_ratio=0.33,
            env_ratio=0.34,
        )
        snap = c.snapshot()
        assert snap.audio_content_mix.value < 0.1

    def test_monotonic_mix_high_pressure(self):
        c = self._collector()
        c.update_audio_perception(
            voice_ratio=0.95,
            music_ratio=0.03,
            env_ratio=0.02,
        )
        snap = c.snapshot()
        assert snap.audio_content_mix.value > 0.5


class TestStimmungAudioStance:
    def _collector(self):
        from shared.stimmung import StimmungCollector

        return StimmungCollector(enable_exploration=False)

    def test_audio_does_not_dominate_stance(self):
        from shared.stimmung import Stance

        c = self._collector()
        c.update_audio_perception(rms_dbfs=-120.0)
        snap = c.snapshot()
        assert snap.overall_stance in (Stance.NOMINAL, Stance.CAUTIOUS)

    def test_audio_dimension_in_format_for_prompt(self):
        c = self._collector()
        c.update_audio_perception(rms_dbfs=-30.0)
        snap = c.snapshot()
        text = snap.format_for_prompt()
        assert "audio_signal_presence" in text


class TestStimmungBackwardCompat:
    def test_snapshot_without_audio_update(self):
        from shared.stimmung import StimmungCollector

        c = StimmungCollector(enable_exploration=False)
        snap = c.snapshot()
        assert snap.audio_signal_presence.value == 0.0
        assert snap.audio_spectral_centroid.value == 0.0
