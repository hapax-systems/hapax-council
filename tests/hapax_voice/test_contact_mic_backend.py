"""Tests for ContactMicBackend — desk activity perception from contact mic.

All tests use synthetic PCM frames — no audio hardware or PipeWire needed.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import numpy as np
import pytest

from agents.hapax_voice.backends.contact_mic import (
    ContactMicBackend,
    _classify_activity,
    _compute_rms,
    _compute_spectral_centroid,
    _ContactMicCache,
    _detect_onsets,
)
from agents.hapax_voice.primitives import Behavior


def _make_pcm_frame(freq_hz: float = 440.0, amplitude: float = 0.5, n_samples: int = 512) -> bytes:
    """Generate a pure sine tone as int16 PCM bytes."""
    t = np.arange(n_samples) / 16000.0
    samples = (amplitude * 32767 * np.sin(2 * np.pi * freq_hz * t)).astype(np.int16)
    return samples.tobytes()


def _make_silence(n_samples: int = 512) -> bytes:
    return b"\x00" * (n_samples * 2)


class TestComputeRms:
    def test_silence_is_zero(self):
        assert _compute_rms(_make_silence()) == pytest.approx(0.0, abs=1e-6)

    def test_loud_signal_high_rms(self):
        rms = _compute_rms(_make_pcm_frame(amplitude=0.9))
        assert rms > 0.5

    def test_quiet_signal_low_rms(self):
        rms = _compute_rms(_make_pcm_frame(amplitude=0.01))
        assert rms < 0.02


class TestSpectralCentroid:
    def test_low_freq_low_centroid(self):
        c_low = _compute_spectral_centroid(_make_pcm_frame(freq_hz=100.0))
        c_high = _compute_spectral_centroid(_make_pcm_frame(freq_hz=4000.0))
        assert c_low < c_high

    def test_silence_returns_zero(self):
        assert _compute_spectral_centroid(_make_silence()) == pytest.approx(0.0, abs=1.0)


class TestOnsetDetection:
    def test_no_onsets_in_silence(self):
        onsets = _detect_onsets([_make_silence()] * 10, threshold=0.01)
        assert len(onsets) == 0

    def test_detects_onset_after_silence(self):
        frames = [_make_silence()] * 5 + [_make_pcm_frame(amplitude=0.8)] * 3
        onsets = _detect_onsets(frames, threshold=0.01)
        assert len(onsets) >= 1

    def test_respects_min_interval(self):
        # Two loud frames back to back should be one onset, not two
        frames = [_make_silence()] * 3 + [_make_pcm_frame(amplitude=0.8)] * 2
        onsets = _detect_onsets(frames, threshold=0.01, min_interval_frames=3)
        assert len(onsets) == 1


class TestClassifyActivity:
    def test_idle_when_silent(self):
        assert (
            _classify_activity(energy=0.0, onset_rate=0.0, centroid=0.0, autocorr_peak=0.0)
            == "idle"
        )

    def test_typing_high_onset_low_energy(self):
        assert (
            _classify_activity(energy=0.2, onset_rate=2.0, centroid=300.0, autocorr_peak=0.0)
            == "typing"
        )

    def test_tapping_moderate_onset_higher_energy(self):
        # energy >= 0.4 so typing branch (energy < 0.4) is skipped, falls to tapping (onset >= 1.6)
        assert (
            _classify_activity(energy=0.45, onset_rate=2.0, centroid=300.0, autocorr_peak=0.0)
            == "tapping"
        )

    def test_drumming_high_energy_low_centroid(self):
        assert (
            _classify_activity(energy=0.5, onset_rate=2.0, centroid=150.0, autocorr_peak=0.0)
            == "drumming"
        )


class TestContactMicCache:
    def test_initial_values(self):
        cache = _ContactMicCache()
        data = cache.read()
        assert data["desk_activity"] == "idle"
        assert data["desk_energy"] == 0.0
        assert data["desk_onset_rate"] == 0.0
        assert data["desk_tap_gesture"] == "none"

    def test_update_and_read(self):
        cache = _ContactMicCache()
        cache.update(
            desk_activity="typing",
            desk_energy=0.3,
            desk_onset_rate=5.0,
            desk_tap_gesture="none",
        )
        data = cache.read()
        assert data["desk_activity"] == "typing"
        assert data["desk_energy"] == 0.3

    def test_thread_safety(self):
        import threading

        cache = _ContactMicCache()
        errors: list[str] = []

        def writer():
            try:
                for _ in range(100):
                    cache.update(
                        desk_activity="typing",
                        desk_energy=0.5,
                        desk_onset_rate=3.0,
                        desk_tap_gesture="none",
                    )
            except Exception as e:
                errors.append(str(e))

        def reader():
            try:
                for _ in range(100):
                    cache.read()
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors


class TestGestureDetection:
    """Gesture pattern matching is tested via the cache's tap_gesture field.

    The gesture state machine runs inside the capture thread. We test the
    exported _classify_gesture() function directly.
    """

    def test_no_gesture_single_onset(self):
        from agents.hapax_voice.backends.contact_mic import _classify_gesture

        now = time.monotonic()
        assert _classify_gesture([now]) == "none"

    def test_double_tap(self):
        from agents.hapax_voice.backends.contact_mic import _classify_gesture

        now = time.monotonic()
        assert _classify_gesture([now, now + 0.15]) == "double_tap"

    def test_triple_tap(self):
        from agents.hapax_voice.backends.contact_mic import _classify_gesture

        now = time.monotonic()
        assert _classify_gesture([now, now + 0.12, now + 0.25]) == "triple_tap"

    def test_too_slow_is_no_gesture(self):
        from agents.hapax_voice.backends.contact_mic import _classify_gesture

        now = time.monotonic()
        # 500ms between taps — too slow for double tap
        assert _classify_gesture([now, now + 0.5]) == "none"


class TestContactMicBackendProtocol:
    def test_name(self):
        with patch("agents.hapax_voice.backends.contact_mic.pyaudio", None):
            backend = ContactMicBackend(source_name="Test Mic")
            assert backend.name == "contact_mic"

    def test_provides(self):
        with patch("agents.hapax_voice.backends.contact_mic.pyaudio", None):
            backend = ContactMicBackend(source_name="Test Mic")
            assert backend.provides == frozenset(
                {
                    "desk_activity",
                    "desk_energy",
                    "desk_onset_rate",
                    "desk_tap_gesture",
                    "desk_spectral_centroid",
                    "desk_autocorr_peak",
                }
            )

    def test_tier_is_fast(self):
        from agents.hapax_voice.perception import PerceptionTier

        with patch("agents.hapax_voice.backends.contact_mic.pyaudio", None):
            backend = ContactMicBackend(source_name="Test Mic")
            assert backend.tier == PerceptionTier.FAST

    def test_contribute_updates_behaviors(self):
        with patch("agents.hapax_voice.backends.contact_mic.pyaudio", None):
            backend = ContactMicBackend(source_name="Test Mic")
            behaviors: dict[str, Behavior] = {}
            backend.contribute(behaviors)
            assert "desk_activity" in behaviors
            assert "desk_energy" in behaviors
            assert "desk_onset_rate" in behaviors
            assert "desk_tap_gesture" in behaviors
            assert "desk_spectral_centroid" in behaviors
            assert "desk_autocorr_peak" in behaviors
            assert behaviors["desk_activity"].value == "idle"


class TestEnvelopeAutocorrelation:
    def test_oscillating_envelope_high_peak(self):
        import math
        from collections import deque

        from agents.hapax_voice.backends.contact_mic import _compute_envelope_autocorrelation

        # Simulate scratching: sinusoidal energy at 5 Hz (200ms period, lag ~6 at 32ms)
        buf: deque[float] = deque(maxlen=60)
        for i in range(60):
            buf.append(0.3 + 0.2 * math.sin(2 * math.pi * 5.0 * i * 0.032))
        peak = _compute_envelope_autocorrelation(buf)
        assert peak > 0.4  # strong periodic signal

    def test_flat_envelope_low_peak(self):
        from collections import deque

        from agents.hapax_voice.backends.contact_mic import _compute_envelope_autocorrelation

        buf: deque[float] = deque(maxlen=60)
        for _ in range(60):
            buf.append(0.3)  # constant energy, no oscillation
        peak = _compute_envelope_autocorrelation(buf)
        assert peak < 0.2

    def test_impulsive_envelope_low_peak(self):
        from collections import deque

        from agents.hapax_voice.backends.contact_mic import _compute_envelope_autocorrelation

        # Simulate typing: aperiodic sparse impulses (not evenly spaced)
        buf: deque[float] = deque(maxlen=60)
        impulse_indices = {3, 11, 22, 38, 51}  # irregular spacing
        for i in range(60):
            buf.append(0.5 if i in impulse_indices else 0.01)
        peak = _compute_envelope_autocorrelation(buf)
        # Aperiodic impulses have weak autocorrelation in the scratch range
        assert peak < 0.4

    def test_short_buffer_returns_zero(self):
        from collections import deque

        from agents.hapax_voice.backends.contact_mic import _compute_envelope_autocorrelation

        buf: deque[float] = deque(maxlen=60)
        buf.append(0.5)
        assert _compute_envelope_autocorrelation(buf) == 0.0


class TestScratchClassification:
    def test_scratching_high_autocorr(self):
        assert (
            _classify_activity(energy=0.12, onset_rate=0.0, centroid=200.0, autocorr_peak=0.95)
            == "scratching"
        )

    def test_no_scratch_low_autocorr(self):
        # Same energy but no autocorrelation -> falls through to other categories
        # energy >= 0.4 skips typing branch, onset_rate >= 1.6 hits tapping
        assert (
            _classify_activity(energy=0.45, onset_rate=2.0, centroid=300.0, autocorr_peak=0.1)
            == "tapping"
        )

    def test_scratch_before_drumming(self):
        # High energy + low centroid would be drumming, but autocorr makes it scratching
        assert (
            _classify_activity(energy=0.5, onset_rate=0.0, centroid=150.0, autocorr_peak=0.95)
            == "scratching"
        )

    def test_idle_not_affected(self):
        # Below idle threshold, autocorr doesn't matter
        assert (
            _classify_activity(energy=0.001, onset_rate=0.0, centroid=0.0, autocorr_peak=0.6)
            == "idle"
        )
