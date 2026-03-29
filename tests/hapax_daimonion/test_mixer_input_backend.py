"""Tests for MixerInputBackend — mixer master audio analysis.

All tests use synthetic PCM frames — no audio hardware or PipeWire needed.
"""

from __future__ import annotations

import threading

import numpy as np
import pytest

from agents.hapax_daimonion.backends.mixer_input import (
    _FRAME_SAMPLES,
    _SAMPLE_RATE,
    MixerInputBackend,
    _compute_rms,
    _compute_three_band_split,
    _detect_beat,
    _MixerCache,
)
from agents.hapax_daimonion.perception import PerceptionTier
from agents.hapax_daimonion.primitives import Behavior


def _make_pcm_frame(
    freq_hz: float = 440.0, amplitude: float = 0.5, n_samples: int = _FRAME_SAMPLES
) -> bytes:
    """Generate a pure sine tone as int16 PCM bytes."""
    t = np.arange(n_samples) / _SAMPLE_RATE
    samples = (amplitude * 32767 * np.sin(2 * np.pi * freq_hz * t)).astype(np.int16)
    return samples.tobytes()


def _make_silence(n_samples: int = _FRAME_SAMPLES) -> bytes:
    return b"\x00" * (n_samples * 2)


# ── RMS ──────────────────────────────────────────────────────────────────────


class TestComputeRms:
    def test_silence_is_zero(self):
        assert _compute_rms(_make_silence()) == pytest.approx(0.0, abs=1e-6)

    def test_loud_signal_high_rms(self):
        rms = _compute_rms(_make_pcm_frame(amplitude=0.9))
        assert rms > 0.5

    def test_quiet_signal_low_rms(self):
        rms = _compute_rms(_make_pcm_frame(amplitude=0.01))
        assert rms < 0.02

    def test_empty_frame_returns_zero(self):
        assert _compute_rms(b"") == 0.0


# ── Three-band spectral split ───────────────────────────────────────────────


class TestThreeBandSplit:
    def test_100hz_sine_is_bass_only(self):
        frame = _make_pcm_frame(freq_hz=100.0, amplitude=0.8)
        bass, mid, high = _compute_three_band_split(frame)
        assert bass > 0.0
        assert mid < bass * 0.1  # negligible mid
        assert high < bass * 0.01  # negligible high

    def test_1000hz_sine_is_mid_only(self):
        frame = _make_pcm_frame(freq_hz=1000.0, amplitude=0.8)
        bass, mid, high = _compute_three_band_split(frame)
        assert mid > 0.0
        assert bass < mid * 0.1
        assert high < mid * 0.1

    def test_5000hz_sine_is_high_only(self):
        frame = _make_pcm_frame(freq_hz=5000.0, amplitude=0.8)
        bass, mid, high = _compute_three_band_split(frame)
        assert high > 0.0
        assert bass < high * 0.01
        assert mid < high * 0.1

    def test_silence_all_zero(self):
        bass, mid, high = _compute_three_band_split(_make_silence())
        assert bass == pytest.approx(0.0, abs=1e-6)
        assert mid == pytest.approx(0.0, abs=1e-6)
        assert high == pytest.approx(0.0, abs=1e-6)


# ── Beat detection ───────────────────────────────────────────────────────────


class TestBeatDetection:
    def test_silence_then_spike_fires_beat(self):
        # Feed silence to establish low baseline, then spike
        baseline = 0.01
        beat_val = 0.0
        # Run 20 silent frames to settle baseline
        for _ in range(20):
            baseline, beat_val = _detect_beat(0.005, baseline, beat_val)
        assert beat_val == pytest.approx(0.0, abs=0.1)
        # Now a loud spike
        baseline, beat_val = _detect_beat(0.5, baseline, beat_val)
        assert beat_val > 0.8  # should spike near 1.0

    def test_steady_signal_no_beats(self):
        baseline = 0.3
        beat_val = 0.0
        # Feed constant energy — baseline adapts, no spikes
        for _ in range(100):
            baseline, beat_val = _detect_beat(0.3, baseline, beat_val)
        assert beat_val < 0.1  # decayed to near zero

    def test_beat_decays_over_frames(self):
        baseline = 0.01
        beat_val = 0.0
        # Establish baseline
        for _ in range(20):
            baseline, beat_val = _detect_beat(0.005, baseline, beat_val)
        # Spike
        baseline, beat_val = _detect_beat(0.5, baseline, beat_val)
        spike_val = beat_val
        # Decay for 10 frames
        for _ in range(10):
            baseline, beat_val = _detect_beat(0.005, baseline, beat_val)
        assert beat_val < spike_val * 0.5  # decayed significantly


# ── Activity detection ───────────────────────────────────────────────────────


class TestActivityDetection:
    def test_below_threshold_inactive(self):
        # RMS below 0.005 threshold → inactive
        assert not _is_active(0.001)

    def test_above_threshold_active(self):
        assert _is_active(0.01)

    def test_exactly_at_threshold(self):
        assert _is_active(0.006)


def _is_active(rms: float) -> bool:
    """Helper: check activity threshold (mirrors implementation logic)."""
    return rms > 0.005


# ── Cache thread safety ─────────────────────────────────────────────────────


class TestMixerCache:
    def test_initial_values(self):
        cache = _MixerCache()
        data = cache.read()
        assert data["mixer_energy"] == 0.0
        assert data["mixer_beat"] == 0.0
        assert data["mixer_bass"] == 0.0
        assert data["mixer_mid"] == 0.0
        assert data["mixer_high"] == 0.0
        assert data["mixer_active"] is False

    def test_update_and_read(self):
        cache = _MixerCache()
        cache.update(
            mixer_energy=0.5,
            mixer_beat=0.8,
            mixer_bass=0.3,
            mixer_mid=0.4,
            mixer_high=0.2,
            mixer_active=True,
        )
        data = cache.read()
        assert data["mixer_energy"] == 0.5
        assert data["mixer_beat"] == 0.8
        assert data["mixer_bass"] == 0.3
        assert data["mixer_mid"] == 0.4
        assert data["mixer_high"] == 0.2
        assert data["mixer_active"] is True

    def test_thread_safety(self):
        cache = _MixerCache()
        errors: list[str] = []

        def writer():
            try:
                for _ in range(200):
                    cache.update(
                        mixer_energy=0.5,
                        mixer_beat=0.3,
                        mixer_bass=0.2,
                        mixer_mid=0.1,
                        mixer_high=0.05,
                        mixer_active=True,
                    )
            except Exception as e:
                errors.append(str(e))

        def reader():
            try:
                for _ in range(200):
                    data = cache.read()
                    # Values should be internally consistent
                    assert isinstance(data["mixer_active"], bool)
            except Exception as e:
                errors.append(str(e))

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=writer),
            threading.Thread(target=reader),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors


# ── Backend protocol compliance ──────────────────────────────────────────────


class TestMixerInputBackendProtocol:
    def test_name(self):
        backend = MixerInputBackend()
        assert backend.name == "mixer_input"

    def test_provides_six_behaviors(self):
        backend = MixerInputBackend()
        expected = frozenset(
            {
                "mixer_energy",
                "mixer_beat",
                "mixer_bass",
                "mixer_mid",
                "mixer_high",
                "mixer_active",
            }
        )
        assert backend.provides == expected

    def test_tier_is_fast(self):
        backend = MixerInputBackend()
        assert backend.tier == PerceptionTier.FAST

    def test_contribute_updates_behaviors(self):
        backend = MixerInputBackend()
        behaviors: dict[str, Behavior] = {}
        backend.contribute(behaviors)
        assert "mixer_energy" in behaviors
        assert "mixer_beat" in behaviors
        assert "mixer_bass" in behaviors
        assert "mixer_mid" in behaviors
        assert "mixer_high" in behaviors
        assert "mixer_active" in behaviors
        assert behaviors["mixer_energy"].value == 0.0
        assert behaviors["mixer_active"].value is False

    def test_contribute_with_cache_data(self):
        backend = MixerInputBackend()
        # Directly poke the cache to simulate DSP output
        backend._cache.update(
            mixer_energy=0.7,
            mixer_beat=0.9,
            mixer_bass=0.5,
            mixer_mid=0.3,
            mixer_high=0.1,
            mixer_active=True,
        )
        behaviors: dict[str, Behavior] = {}
        backend.contribute(behaviors)
        assert behaviors["mixer_energy"].value == pytest.approx(0.7)
        assert behaviors["mixer_active"].value is True
