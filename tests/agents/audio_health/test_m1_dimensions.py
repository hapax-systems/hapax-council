"""Tests for M1 extended audio health dimensions.

At least 3 test cases per dimension (detect, no-detect, edge),
plus integration tests verifying Prometheus output format.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import pytest

from agents.audio_health.m1_dimensions import (
    M1Alert,
    M1Config,
    M1ExtendedMeasurement,
    classify_m1,
    compute_envelope_correlation,
    compute_lufs_s,
    compute_spectral_flatness,
    m1_prometheus_lines,
    measure_m1,
)

# ── Synthesize test signals ─────────────────────────────────────────────

_SR = 48000  # sample rate


def _sine(freq: float = 440.0, duration: float = 0.5, amplitude: float = 0.5) -> np.ndarray:
    """Synthesize a pure sine wave."""
    t = np.arange(int(_SR * duration)) / _SR
    return (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float64)


def _white_noise(duration: float = 0.5, amplitude: float = 0.3) -> np.ndarray:
    """Synthesize white noise."""
    rng = np.random.default_rng(42)
    return (amplitude * rng.standard_normal(int(_SR * duration))).astype(np.float64)


def _silence(duration: float = 0.5) -> np.ndarray:
    """Synthesize silence."""
    return np.zeros(int(_SR * duration), dtype=np.float64)


def _music_like(duration: float = 0.5) -> np.ndarray:
    """Synthesize a music-like signal (multiple sine harmonics + envelope)."""
    t = np.arange(int(_SR * duration)) / _SR
    signal = (
        0.3 * np.sin(2 * np.pi * 220 * t)
        + 0.2 * np.sin(2 * np.pi * 440 * t)
        + 0.15 * np.sin(2 * np.pi * 660 * t)
        + 0.1 * np.sin(2 * np.pi * 880 * t)
    )
    # Add amplitude modulation for transients
    envelope = 0.5 + 0.5 * np.sin(2 * np.pi * 4 * t)
    return (signal * envelope).astype(np.float64)


def _clipping_signal(duration: float = 0.5) -> np.ndarray:
    """Synthesize a clipping signal (loud, near-full-scale)."""
    t = np.arange(int(_SR * duration)) / _SR
    return (0.95 * np.sin(2 * np.pi * 440 * t)).astype(np.float64)


# ── LUFS-S tests ────────────────────────────────────────────────────────


class TestLufsS:
    """compute_lufs_s tests: detect, no-detect, edge."""

    def test_loud_signal_exceeds_clipping_threshold(self) -> None:
        """A loud sine should produce LUFS above -10 dBFS (clipping zone)."""
        signal = _clipping_signal()
        lufs = compute_lufs_s(signal, sample_rate=_SR)
        assert lufs > -10.0, f"Expected LUFS > -10 for clipping, got {lufs}"

    def test_music_signal_is_nominal(self) -> None:
        """A normal music-like signal should be between -50 and -10 dBFS."""
        signal = _music_like()
        lufs = compute_lufs_s(signal, sample_rate=_SR)
        assert -50.0 < lufs < -10.0, f"Expected nominal LUFS, got {lufs}"

    def test_silent_signal_below_threshold(self) -> None:
        """Silence should produce LUFS below -50 dBFS."""
        signal = _silence()
        lufs = compute_lufs_s(signal, sample_rate=_SR)
        assert lufs < -50.0, f"Expected LUFS < -50 for silence, got {lufs}"

    def test_empty_array_returns_floor(self) -> None:
        lufs = compute_lufs_s(np.array([], dtype=np.float64))
        assert lufs == -120.0

    def test_white_noise_has_measurable_lufs(self) -> None:
        signal = _white_noise(amplitude=0.1)
        lufs = compute_lufs_s(signal, sample_rate=_SR)
        assert -120.0 < lufs < 0.0


# ── Spectral flatness tests ────────────────────────────────────────────


class TestSpectralFlatness:
    """compute_spectral_flatness tests: detect, no-detect, edge."""

    def test_white_noise_is_flat(self) -> None:
        """White noise should have high spectral flatness (near 1.0)."""
        signal = _white_noise(amplitude=0.3)
        flatness = compute_spectral_flatness(signal)
        assert flatness > 0.5, f"Expected flatness > 0.5 for noise, got {flatness}"

    def test_pure_sine_is_tonal(self) -> None:
        """A pure sine should have very low spectral flatness (near 0)."""
        signal = _sine(freq=1000, amplitude=0.5)
        flatness = compute_spectral_flatness(signal)
        assert flatness < 0.1, f"Expected flatness < 0.1 for sine, got {flatness}"

    def test_music_signal_is_intermediate(self) -> None:
        """A music-like signal should have intermediate flatness."""
        signal = _music_like()
        flatness = compute_spectral_flatness(signal)
        assert 0.0 < flatness < 0.8, f"Expected intermediate flatness, got {flatness}"

    def test_empty_array_returns_zero(self) -> None:
        flatness = compute_spectral_flatness(np.array([], dtype=np.float64))
        assert flatness == 0.0

    def test_single_sample_returns_zero(self) -> None:
        flatness = compute_spectral_flatness(np.array([0.5]))
        assert flatness == 0.0

    def test_silence_returns_zero(self) -> None:
        signal = _silence()
        flatness = compute_spectral_flatness(signal)
        assert flatness == 0.0


# ── Inter-stage envelope correlation tests ──────────────────────────────


class TestEnvelopeCorrelation:
    """compute_envelope_correlation tests: detect, no-detect, edge."""

    def test_identical_signals_perfect_correlation(self) -> None:
        """Two identical signals should have correlation ~1.0."""
        signal = _music_like()
        corr = compute_envelope_correlation(signal, signal.copy())
        assert corr > 0.99, f"Expected corr > 0.99, got {corr}"

    def test_scaled_signals_high_correlation(self) -> None:
        """Scaling preserves envelope shape → high correlation."""
        signal = _music_like()
        scaled = signal * 0.5  # normalized but same shape
        corr = compute_envelope_correlation(signal, scaled)
        assert corr > 0.9, f"Expected corr > 0.9 for scaled, got {corr}"

    def test_distorted_signal_low_correlation(self) -> None:
        """Signal with injected noise distortion should have lower correlation."""
        signal = _music_like()
        distorted = signal + _white_noise(amplitude=0.5)
        corr = compute_envelope_correlation(signal, distorted)
        # Correlation should drop but not necessarily below 0.9 — distortion
        # level matters. At 0.5 noise amplitude vs ~0.3 signal, this should
        # be noticeably reduced.
        assert corr < 0.95, f"Expected corr < 0.95 for distorted, got {corr}"

    def test_unrelated_signals_low_correlation(self) -> None:
        """Two completely unrelated signals should have low correlation."""
        signal_a = _sine(freq=440)
        signal_b = _white_noise()
        corr = compute_envelope_correlation(signal_a, signal_b)
        assert abs(corr) < 0.5, f"Expected |corr| < 0.5, got {corr}"

    def test_too_short_returns_zero(self) -> None:
        """Signals shorter than 2 × window_size should return 0.0."""
        short = np.array([0.1, 0.2, 0.3], dtype=np.float64)
        corr = compute_envelope_correlation(short, short, window_size=256)
        assert corr == 0.0

    def test_both_silent_returns_one(self) -> None:
        """Two silent signals have constant envelope → correlation 1.0."""
        silent = _silence()
        corr = compute_envelope_correlation(silent, silent)
        assert corr == 1.0


# ── M1 alert classification tests ──────────────────────────────────────


class TestClassifyM1:
    """classify_m1 integration tests."""

    def test_nominal_no_alerts(self) -> None:
        """Nominal measurement should produce no alerts."""
        m = M1ExtendedMeasurement(
            lufs_s=-25.0,
            spectral_flatness=0.3,
            interstage_correlation=0.95,
        )
        alerts = classify_m1(m)
        assert alerts == []

    def test_lufs_clipping_alert(self) -> None:
        m = M1ExtendedMeasurement(lufs_s=-5.0, spectral_flatness=0.3)
        alerts = classify_m1(m)
        assert M1Alert.LUFS_CLIPPING in alerts

    def test_lufs_silent_alert(self) -> None:
        m = M1ExtendedMeasurement(lufs_s=-60.0, spectral_flatness=0.0)
        alerts = classify_m1(m)
        assert M1Alert.LUFS_SILENT in alerts

    def test_noise_spectral_alert(self) -> None:
        m = M1ExtendedMeasurement(lufs_s=-25.0, spectral_flatness=0.9)
        alerts = classify_m1(m)
        assert M1Alert.NOISE_SPECTRAL in alerts

    def test_tonal_spectral_alert(self) -> None:
        m = M1ExtendedMeasurement(lufs_s=-25.0, spectral_flatness=0.02)
        alerts = classify_m1(m)
        assert M1Alert.TONAL_SPECTRAL in alerts

    def test_interstage_distortion_alert(self) -> None:
        m = M1ExtendedMeasurement(lufs_s=-25.0, spectral_flatness=0.3, interstage_correlation=0.7)
        alerts = classify_m1(m)
        assert M1Alert.INTERSTAGE_DISTORTION in alerts

    def test_multiple_alerts_can_fire(self) -> None:
        """M1 dimensions are independent — multiple can fire."""
        m = M1ExtendedMeasurement(lufs_s=-5.0, spectral_flatness=0.9, interstage_correlation=0.5)
        alerts = classify_m1(m)
        assert M1Alert.LUFS_CLIPPING in alerts
        assert M1Alert.NOISE_SPECTRAL in alerts
        assert M1Alert.INTERSTAGE_DISTORTION in alerts

    def test_no_correlation_no_interstage_alert(self) -> None:
        """When interstage_correlation is None, no distortion alert fires."""
        m = M1ExtendedMeasurement(lufs_s=-25.0, spectral_flatness=0.3, interstage_correlation=None)
        alerts = classify_m1(m)
        assert M1Alert.INTERSTAGE_DISTORTION not in alerts


# ── measure_m1 integration ──────────────────────────────────────────────


class TestMeasureM1:
    """measure_m1 integration with real synthesized signals."""

    def test_measure_broadband_music_all_nominal(self) -> None:
        """A broadband music-like signal (harmonics + noise floor) should be nominal."""
        signal = _music_like() + _white_noise(amplitude=0.05)
        m = measure_m1(signal, sample_rate=_SR)
        alerts = classify_m1(m)
        # Should not trigger LUFS clipping/silent, noise, or distortion
        assert M1Alert.LUFS_CLIPPING not in alerts
        assert M1Alert.LUFS_SILENT not in alerts
        assert M1Alert.NOISE_SPECTRAL not in alerts

    def test_measure_pure_harmonics_triggers_tonal(self) -> None:
        """A pure-harmonic signal correctly triggers tonal alert."""
        signal = _music_like()
        m = measure_m1(signal, sample_rate=_SR)
        alerts = classify_m1(m)
        assert M1Alert.TONAL_SPECTRAL in alerts

    def test_measure_with_two_stages(self) -> None:
        signal = _music_like()
        m = measure_m1(signal, sample_rate=_SR, stage_b_samples=signal.copy())
        assert m.interstage_correlation is not None
        assert m.interstage_correlation > 0.99

    def test_measure_clipping_signal(self) -> None:
        signal = _clipping_signal()
        m = measure_m1(signal, sample_rate=_SR)
        alerts = classify_m1(m)
        assert M1Alert.LUFS_CLIPPING in alerts

    def test_measure_int16_input(self) -> None:
        """measure_m1 should handle int16 input correctly."""
        signal_f = _music_like()
        signal_i16 = (signal_f * 32768).astype(np.int16)
        m = measure_m1(signal_i16, sample_rate=_SR)
        assert -120.0 < m.lufs_s < 0.0
        assert 0.0 <= m.spectral_flatness <= 1.0


# ── Prometheus output tests ─────────────────────────────────────────────


class TestPrometheusOutput:
    """m1_prometheus_lines format verification."""

    def test_lines_contain_expected_metrics(self) -> None:
        m = M1ExtendedMeasurement(lufs_s=-20.0, spectral_flatness=0.3, interstage_correlation=0.95)
        lines = m1_prometheus_lines(m)
        text = "\n".join(lines)
        assert "hapax_audio_lufs_s_dbfs" in text
        assert "hapax_audio_spectral_flatness" in text
        assert "hapax_audio_interstage_correlation" in text

    def test_lines_without_correlation(self) -> None:
        m = M1ExtendedMeasurement(lufs_s=-20.0, spectral_flatness=0.3)
        lines = m1_prometheus_lines(m)
        text = "\n".join(lines)
        assert "hapax_audio_lufs_s_dbfs" in text
        assert "hapax_audio_spectral_flatness" in text
        assert "hapax_audio_interstage_correlation" not in text

    def test_lines_are_valid_prometheus_format(self) -> None:
        m = M1ExtendedMeasurement(lufs_s=-20.5, spectral_flatness=0.3456)
        lines = m1_prometheus_lines(m)
        for line in lines:
            if line.startswith("#"):
                continue
            parts = line.split()
            assert len(parts) == 2, f"Bad Prometheus line: {line}"
            float(parts[1])  # should not raise


# ── M1Config env override tests ─────────────────────────────────────────


class TestM1Config:
    """M1Config.from_env tests."""

    def test_defaults(self) -> None:
        cfg = M1Config()
        assert cfg.lufs_clipping_dbfs == -10.0
        assert cfg.lufs_silent_dbfs == -50.0
        assert cfg.correlation_min == 0.9

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HAPAX_AUDIO_M1_LUFS_CLIPPING_DBFS", "-8")
        monkeypatch.setenv("HAPAX_AUDIO_M1_CORRELATION_MIN", "0.85")
        cfg = M1Config.from_env()
        assert cfg.lufs_clipping_dbfs == -8.0
        assert cfg.correlation_min == 0.85

    def test_invalid_env_uses_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HAPAX_AUDIO_M1_LUFS_CLIPPING_DBFS", "not_a_number")
        cfg = M1Config.from_env()
        assert cfg.lufs_clipping_dbfs == -10.0
