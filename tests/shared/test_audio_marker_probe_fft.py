"""Tests for ``shared.audio_marker_probe_fft``.

Coverage:

- ``generate_marker_tone``: input validation (non-positive freq /
  duration / sample-rate, amplitude bounds, freq above Nyquist),
  output shape (int16, length matches duration*rate), determinism
  (same args → same bytes), spectrum check (FFT peak at requested
  frequency).
- ``detect_marker_in_capture`` truth table:
  - generated tone alone → detected
  - generated tone + moderate noise → detected with reduced SNR
  - white noise alone → not detected (snr-below-threshold)
  - tone at different frequency → not detected
  - empty capture → fail-closed (no-samples)
  - too-short capture → fail-closed (too-short)
  - all-zero capture → fail-closed (all-zero-capture)
  - silence padded to threshold length → fail-closed
- Constant pins so future tuning is auditable.
"""

from __future__ import annotations

import numpy as np
import pytest

from shared.audio_marker_probe_fft import (
    DEFAULT_AMPLITUDE,
    DEFAULT_MARKER_FREQ_HZ,
    DEFAULT_SAMPLE_RATE_HZ,
    DEFAULT_SNR_THRESHOLD_DB,
    MIN_CAPTURE_DURATION_S,
    MarkerDetection,
    detect_marker_in_capture,
    generate_marker_tone,
)

# ── Constants ────────────────────────────────────────────────────────────


class TestConstants:
    def test_carrier_above_voice_band(self) -> None:
        """Sub-audible / supersonic: carrier must be above typical
        voice-band content (>16 kHz)."""
        assert DEFAULT_MARKER_FREQ_HZ > 16000

    def test_carrier_below_nyquist(self) -> None:
        """Carrier must be below Nyquist at the default rate."""
        assert DEFAULT_MARKER_FREQ_HZ < DEFAULT_SAMPLE_RATE_HZ / 2

    def test_amplitude_safe(self) -> None:
        """Amplitude in (0, 1] so generated samples don't clip."""
        assert 0.0 < DEFAULT_AMPLITUDE <= 1.0

    def test_threshold_positive_db(self) -> None:
        """Threshold must demand the marker stand above the noise
        floor by a meaningful margin."""
        assert DEFAULT_SNR_THRESHOLD_DB > 0


# ── generate_marker_tone ─────────────────────────────────────────────────


class TestGenerateMarkerTone:
    def test_int16_shape(self) -> None:
        samples = generate_marker_tone(duration_s=1.0)
        assert samples.dtype == np.int16
        assert samples.shape == (DEFAULT_SAMPLE_RATE_HZ,)

    def test_length_scales_with_duration(self) -> None:
        samples = generate_marker_tone(duration_s=0.5)
        assert len(samples) == DEFAULT_SAMPLE_RATE_HZ // 2

    def test_deterministic(self) -> None:
        a = generate_marker_tone(duration_s=0.25)
        b = generate_marker_tone(duration_s=0.25)
        assert (a == b).all()

    @pytest.mark.parametrize("bad", [0, -1, -100])
    def test_rejects_nonpositive_freq(self, bad: float) -> None:
        with pytest.raises(ValueError, match="freq_hz must be > 0"):
            generate_marker_tone(freq_hz=bad)

    @pytest.mark.parametrize("bad", [0, -0.1])
    def test_rejects_nonpositive_duration(self, bad: float) -> None:
        with pytest.raises(ValueError, match="duration_s must be > 0"):
            generate_marker_tone(duration_s=bad)

    @pytest.mark.parametrize("bad", [0, -1])
    def test_rejects_nonpositive_sample_rate(self, bad: int) -> None:
        with pytest.raises(ValueError, match="sample_rate must be > 0"):
            generate_marker_tone(sample_rate=bad)

    @pytest.mark.parametrize("bad", [0.0, -0.5, 1.1, 2.0])
    def test_rejects_amplitude_out_of_range(self, bad: float) -> None:
        with pytest.raises(ValueError, match="amplitude must be in"):
            generate_marker_tone(amplitude=bad)

    def test_rejects_above_nyquist(self) -> None:
        with pytest.raises(ValueError, match="exceeds Nyquist"):
            generate_marker_tone(freq_hz=30000.0, sample_rate=48000)

    def test_fft_peak_at_carrier(self) -> None:
        """The generated tone's FFT must show its largest peak at the
        requested carrier frequency."""
        sample_rate = 48000
        freq_hz = 17500.0
        samples = generate_marker_tone(freq_hz=freq_hz, duration_s=0.5, sample_rate=sample_rate)
        spectrum = np.abs(np.fft.rfft(samples.astype(np.float64)))
        freqs = np.fft.rfftfreq(len(samples), d=1.0 / sample_rate)
        peak_idx = int(np.argmax(spectrum))
        # ±1 bin tolerance; bin width = sample_rate / n_samples.
        bin_width = sample_rate / len(samples)
        assert abs(freqs[peak_idx] - freq_hz) <= bin_width


# ── detect_marker_in_capture truth table ─────────────────────────────────


def _white_noise(n_samples: int, *, amplitude: float = 0.05, seed: int = 0) -> np.ndarray:
    """Reproducible white noise scaled to int16 range."""
    rng = np.random.default_rng(seed)
    floats = rng.normal(0.0, amplitude, size=n_samples)
    return (floats * (2**15 - 1)).astype(np.int16)


class TestDetectMarker:
    def test_detected_in_pure_tone(self) -> None:
        samples = generate_marker_tone(duration_s=0.5)
        result = detect_marker_in_capture(samples)
        assert result.detected is True
        assert result.failure_reason is None
        assert result.snr_db > DEFAULT_SNR_THRESHOLD_DB
        assert abs(result.peak_freq_hz - DEFAULT_MARKER_FREQ_HZ) < 50.0

    def test_detected_in_tone_plus_moderate_noise(self) -> None:
        """Add white noise at ~30% of the marker amplitude. The marker
        should still clear the SNR threshold (with reduced margin)."""
        marker = generate_marker_tone(duration_s=0.5, amplitude=DEFAULT_AMPLITUDE).astype(np.int32)
        noise = _white_noise(len(marker), amplitude=DEFAULT_AMPLITUDE * 0.3, seed=42).astype(
            np.int32
        )
        mixed = np.clip(marker + noise, -32768, 32767).astype(np.int16)
        result = detect_marker_in_capture(mixed)
        assert result.detected is True

    def test_not_detected_in_white_noise(self) -> None:
        samples = _white_noise(48000, seed=1)
        result = detect_marker_in_capture(samples)
        assert result.detected is False
        # Noise should fail SNR (the marker freq has no excess power).
        assert result.failure_reason == "snr-below-threshold"

    def test_not_detected_when_tone_at_different_frequency(self) -> None:
        """A 5 kHz tone (well outside the carrier) must not trip the
        17.5 kHz detector."""
        samples = generate_marker_tone(freq_hz=5000.0, duration_s=0.5)
        result = detect_marker_in_capture(samples)
        assert result.detected is False
        assert result.failure_reason == "snr-below-threshold"

    def test_empty_capture_fails_closed(self) -> None:
        result = detect_marker_in_capture(np.array([], dtype=np.int16))
        assert result.detected is False
        assert result.failure_reason == "no-samples"

    def test_too_short_capture_fails_closed(self) -> None:
        # Below MIN_CAPTURE_DURATION_S (0.05 s = 2400 samples at 48 kHz).
        samples = generate_marker_tone(duration_s=0.01)
        result = detect_marker_in_capture(samples)
        assert result.detected is False
        assert result.failure_reason == "too-short"

    def test_all_zero_capture_fails_closed(self) -> None:
        samples = np.zeros(int(MIN_CAPTURE_DURATION_S * DEFAULT_SAMPLE_RATE_HZ * 2), dtype=np.int16)
        result = detect_marker_in_capture(samples)
        assert result.detected is False
        assert result.failure_reason == "all-zero-capture"

    def test_detection_records_target_freq(self) -> None:
        """Every detection result carries the requested frequency for
        post-hoc evidence."""
        samples = generate_marker_tone(duration_s=0.25)
        result = detect_marker_in_capture(samples, freq_hz=17500.0)
        assert result.target_freq_hz == pytest.approx(17500.0)

    def test_custom_threshold_can_force_detection(self) -> None:
        """Lowering the threshold below the natural noise-floor SNR
        should make even noise pass — useful for negative-test
        calibration. Pin so future SNR-default changes are deliberate."""
        samples = _white_noise(48000, seed=2)
        result = detect_marker_in_capture(samples, snr_threshold_db=-100.0)
        # With a permissive threshold, the noise spectrum's natural
        # spread will trip detection — pinning the calibration knob.
        assert result.detected is True


# ── MarkerDetection shape ────────────────────────────────────────────────


class TestMarkerDetectionShape:
    def test_carries_typed_fields(self) -> None:
        det = MarkerDetection(
            detected=True,
            snr_db=20.0,
            peak_freq_hz=17500.0,
            target_freq_hz=17500.0,
            failure_reason=None,
        )
        assert det.detected is True
        assert det.snr_db == pytest.approx(20.0)

    def test_is_frozen_dataclass(self) -> None:
        det = MarkerDetection(
            detected=False,
            snr_db=0.0,
            peak_freq_hz=0.0,
            target_freq_hz=DEFAULT_MARKER_FREQ_HZ,
            failure_reason="no-samples",
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            det.detected = True  # type: ignore[misc]
