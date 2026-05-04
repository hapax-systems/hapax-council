"""M1 extended audio health dimensions.

Three new measurement dimensions for the audio health classifier suite:

1. **LUFS-S** (Short-term Loudness): EBU R128 short-term integrated
   loudness computed via the ITU-R BS.1770-4 K-weighting filter chain.
   Detects clipping (LUFS > -10) and silent broadcast (LUFS < -50).

2. **Spectral flatness** (Wiener entropy): ratio of geometric to
   arithmetic mean of the power spectrum. Values near 0.0 indicate
   tonal content; near 1.0 indicate noise. Complementary noise/music
   discriminator beyond crest + ZCR.

3. **Inter-stage envelope correlation**: Pearson correlation between
   two stage envelopes (e.g., broadcast-master vs broadcast-normalized).
   Detects signal loss or distortion between processing stages when
   correlation drops below 0.9.

Each dimension:
- Has a hysteresis threshold with configurable env-var overrides
- Produces a Prometheus-compatible gauge value
- Integrates with the meta-monitor's textfile-mtime tracking from M0
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Final

import numpy as np

# ── LUFS-S (Short-term Loudness) ────────────────────────────────────────

# ITU-R BS.1770-4 K-weighting pre-filter coefficients for 48 kHz.
# These are the biquad numerator/denominator pairs for:
#   Stage 1: Shelf filter (+4 dB above ~2 kHz)
#   Stage 2: High-pass filter (~60 Hz, BW~0.5 octave)
# Reference: ITU-R BS.1770-4 §2.1, Table 1.

# Stage 1 shelf (pre-filter) coefficients at 48 kHz
_K_SHELF_B: Final = np.array([1.53512485958697, -2.69169618940638, 1.19839281085285])
_K_SHELF_A: Final = np.array([1.0, -1.69065929318241, 0.73248077421585])

# Stage 2 high-pass coefficients at 48 kHz
_K_HPF_B: Final = np.array([1.0, -2.0, 1.0])
_K_HPF_A: Final = np.array([1.0, -1.99004745483398, 0.99007225036621])


def _biquad_filter(b: np.ndarray, a: np.ndarray, x: np.ndarray) -> np.ndarray:
    """Apply a biquad (IIR) filter. Pure-numpy replacement for scipy.signal.lfilter.

    Direct Form II transposed, matching scipy's lfilter behavior for 2nd-order sections.
    """
    n = len(x)
    y = np.zeros(n, dtype=np.float64)
    # State variables (Direct Form II transposed)
    z1 = 0.0
    z2 = 0.0
    b0, b1, b2 = float(b[0]), float(b[1]), float(b[2])
    a1, a2 = float(a[1]), float(a[2])
    a0_inv = 1.0 / float(a[0])

    for i in range(n):
        xi = float(x[i])
        yi = b0 * a0_inv * xi + z1
        z1 = b1 * a0_inv * xi - a1 * a0_inv * yi + z2
        z2 = b2 * a0_inv * xi - a2 * a0_inv * yi
        y[i] = yi
    return y


def compute_lufs_s(
    samples: np.ndarray,
    sample_rate: int = 48000,
) -> float:
    """Compute short-term (3s window) LUFS per EBU R128 / ITU-R BS.1770-4.

    For windows shorter than 3s, uses the full window. Returns dBFS-scale
    value bounded below by -120.0.

    Parameters
    ----------
    samples : mono float64 array, normalized to [-1, 1]
    sample_rate : sample rate in Hz (default 48000)
    """
    if samples.size == 0:
        return -120.0

    floats = samples.astype(np.float64, copy=False)

    # Apply K-weighting filter chain (Stage 1 shelf → Stage 2 HPF)
    stage1 = _biquad_filter(_K_SHELF_B, _K_SHELF_A, floats)
    weighted = _biquad_filter(_K_HPF_B, _K_HPF_A, stage1)

    # Mean square of K-weighted signal
    mean_sq = float(np.mean(np.square(weighted)))

    if mean_sq <= 0:
        return -120.0

    # LUFS = -0.691 + 10 * log10(mean_sq) per ITU-R BS.1770
    lufs = -0.691 + 10.0 * math.log10(mean_sq)
    return max(-120.0, lufs)


# ── Spectral Flatness (Wiener Entropy) ──────────────────────────────────


def compute_spectral_flatness(samples: np.ndarray) -> float:
    """Compute spectral flatness (Wiener entropy).

    Ratio of geometric mean to arithmetic mean of the power spectrum.
    Values near 0.0 = tonal; near 1.0 = noise-like (white noise).

    Returns a value in [0.0, 1.0], or 0.0 for silent/empty input.
    """
    if samples.size < 2:
        return 0.0

    floats = samples.astype(np.float64, copy=False)

    # All-zero input (silence) has no spectral content → flatness 0.0
    if float(np.max(np.abs(floats))) < 1e-15:
        return 0.0

    # Compute power spectrum via FFT (one-sided for real signal)
    spectrum = np.abs(np.fft.rfft(floats)) ** 2

    # Remove DC component and Nyquist
    if spectrum.size > 2:
        spectrum = spectrum[1:-1]

    if spectrum.size == 0:
        return 0.0

    # Floor to avoid log(0)
    spectrum = np.maximum(spectrum, 1e-20)

    # Geometric mean via log domain
    log_mean = float(np.mean(np.log(spectrum)))
    geometric_mean = math.exp(log_mean)

    # Arithmetic mean
    arithmetic_mean = float(np.mean(spectrum))

    if arithmetic_mean <= 0:
        return 0.0

    flatness = geometric_mean / arithmetic_mean
    return max(0.0, min(1.0, flatness))


# ── Inter-Stage Envelope Correlation ────────────────────────────────────


def compute_envelope_correlation(
    stage_a: np.ndarray,
    stage_b: np.ndarray,
    window_size: int = 256,
) -> float:
    """Compute Pearson correlation between two stage envelopes.

    Each stage's envelope is computed via a sliding RMS window (default
    256 samples ≈ 5ms at 48kHz). Returns correlation in [-1.0, 1.0],
    or 0.0 on error/empty input.

    Parameters
    ----------
    stage_a : mono float64 array for the first stage (e.g., broadcast-master)
    stage_b : mono float64 array for the second stage (e.g., broadcast-normalized)
    window_size : RMS envelope window size in samples
    """
    min_len = min(len(stage_a), len(stage_b))
    if min_len < window_size * 2:
        return 0.0

    a = stage_a[:min_len].astype(np.float64, copy=False)
    b = stage_b[:min_len].astype(np.float64, copy=False)

    # Compute sliding-window RMS envelopes
    def _envelope(x: np.ndarray) -> np.ndarray:
        # Cumulative sum of squares for efficient windowed RMS
        sq = np.square(x)
        cumsum = np.cumsum(sq)
        cumsum = np.insert(cumsum, 0, 0.0)
        windowed = (cumsum[window_size:] - cumsum[:-window_size]) / window_size
        return np.sqrt(np.maximum(windowed, 0.0))

    env_a = _envelope(a)
    env_b = _envelope(b)

    if env_a.size == 0 or env_b.size == 0:
        return 0.0

    # Trim to equal length
    min_env = min(len(env_a), len(env_b))
    env_a = env_a[:min_env]
    env_b = env_b[:min_env]

    # Pearson correlation
    std_a = float(np.std(env_a))
    std_b = float(np.std(env_b))

    if std_a < 1e-10 or std_b < 1e-10:
        # Both near-constant → perfect correlation if both near-zero
        if std_a < 1e-10 and std_b < 1e-10:
            return 1.0
        return 0.0

    corr = float(np.corrcoef(env_a, env_b)[0, 1])
    if math.isnan(corr):
        return 0.0
    return max(-1.0, min(1.0, corr))


# ── M1 Extended Measurement ─────────────────────────────────────────────


@dataclass(frozen=True)
class M1ExtendedMeasurement:
    """Extended measurements from M1 dimensions.

    Supplements :class:`ProbeMeasurement` from M0 with LUFS-S,
    spectral flatness, and (optionally) inter-stage correlation.
    """

    lufs_s: float
    spectral_flatness: float
    interstage_correlation: float | None = None  # None when single-stage


@dataclass(frozen=True)
class M1Config:
    """Tunable M1 thresholds — env-overridable.

    Same pattern as :class:`ClassifierConfig` from M0.
    """

    # LUFS-S thresholds
    lufs_clipping_dbfs: float = -10.0
    lufs_silent_dbfs: float = -50.0

    # Spectral flatness thresholds
    flatness_noise_min: float = 0.8  # above → noise-like
    flatness_tonal_max: float = 0.05  # below → tonal/drone

    # Inter-stage correlation threshold
    correlation_min: float = 0.9  # below → signal distortion

    @classmethod
    def from_env(cls) -> M1Config:
        """Build from ``HAPAX_AUDIO_M1_*`` env vars."""

        def _get(key: str, default: float) -> float:
            raw = os.environ.get(f"HAPAX_AUDIO_M1_{key}")
            if raw is None or raw == "":
                return default
            try:
                return float(raw)
            except ValueError:
                return default

        return cls(
            lufs_clipping_dbfs=_get("LUFS_CLIPPING_DBFS", cls.lufs_clipping_dbfs),
            lufs_silent_dbfs=_get("LUFS_SILENT_DBFS", cls.lufs_silent_dbfs),
            flatness_noise_min=_get("FLATNESS_NOISE_MIN", cls.flatness_noise_min),
            flatness_tonal_max=_get("FLATNESS_TONAL_MAX", cls.flatness_tonal_max),
            correlation_min=_get("CORRELATION_MIN", cls.correlation_min),
        )


class M1Alert:
    """Alert labels for M1 dimensions."""

    LUFS_CLIPPING = "lufs_clipping"
    LUFS_SILENT = "lufs_silent"
    NOISE_SPECTRAL = "noise_spectral"
    TONAL_SPECTRAL = "tonal_spectral"
    INTERSTAGE_DISTORTION = "interstage_distortion"
    NOMINAL = "nominal"


def measure_m1(
    samples: np.ndarray,
    *,
    sample_rate: int = 48000,
    stage_b_samples: np.ndarray | None = None,
    envelope_window: int = 256,
) -> M1ExtendedMeasurement:
    """Compute all M1 extended measurements from a PCM window.

    Parameters
    ----------
    samples : mono float64 array (primary stage, e.g., broadcast-master)
    sample_rate : sample rate in Hz
    stage_b_samples : optional second-stage PCM for inter-stage correlation
    envelope_window : RMS window size for envelope correlation
    """
    if np.issubdtype(samples.dtype, np.integer):
        floats = samples.astype(np.float64) / 32768.0
    else:
        floats = samples.astype(np.float64, copy=False)

    lufs = compute_lufs_s(floats, sample_rate=sample_rate)
    flatness = compute_spectral_flatness(floats)

    correlation: float | None = None
    if stage_b_samples is not None:
        if np.issubdtype(stage_b_samples.dtype, np.integer):
            b_floats = stage_b_samples.astype(np.float64) / 32768.0
        else:
            b_floats = stage_b_samples.astype(np.float64, copy=False)
        correlation = compute_envelope_correlation(floats, b_floats, window_size=envelope_window)

    return M1ExtendedMeasurement(
        lufs_s=lufs,
        spectral_flatness=flatness,
        interstage_correlation=correlation,
    )


def classify_m1(
    measurement: M1ExtendedMeasurement,
    config: M1Config | None = None,
) -> list[str]:
    """Classify M1 measurements into alert labels.

    Returns a list of active alert labels. Empty list means nominal.
    Multiple alerts can fire simultaneously (unlike the M0 precedence
    system, M1 dimensions are independent).
    """
    cfg = config or M1Config.from_env()
    alerts: list[str] = []

    # LUFS-S checks
    if measurement.lufs_s > cfg.lufs_clipping_dbfs:
        alerts.append(M1Alert.LUFS_CLIPPING)
    elif measurement.lufs_s < cfg.lufs_silent_dbfs:
        alerts.append(M1Alert.LUFS_SILENT)

    # Spectral flatness checks
    if measurement.spectral_flatness >= cfg.flatness_noise_min:
        alerts.append(M1Alert.NOISE_SPECTRAL)
    elif measurement.spectral_flatness <= cfg.flatness_tonal_max:
        alerts.append(M1Alert.TONAL_SPECTRAL)

    # Inter-stage correlation check
    if (
        measurement.interstage_correlation is not None
        and measurement.interstage_correlation < cfg.correlation_min
    ):
        alerts.append(M1Alert.INTERSTAGE_DISTORTION)

    return alerts


def m1_prometheus_lines(measurement: M1ExtendedMeasurement) -> list[str]:
    """Generate Prometheus textfile gauge lines for M1 measurements.

    Format compatible with the node_exporter textfile collector used
    by the M0 meta-monitor.
    """
    lines = [
        "# HELP hapax_audio_lufs_s_dbfs Short-term LUFS (EBU R128) in dBFS",
        "# TYPE hapax_audio_lufs_s_dbfs gauge",
        f"hapax_audio_lufs_s_dbfs {measurement.lufs_s:.2f}",
        "# HELP hapax_audio_spectral_flatness Spectral flatness (Wiener entropy) [0-1]",
        "# TYPE hapax_audio_spectral_flatness gauge",
        f"hapax_audio_spectral_flatness {measurement.spectral_flatness:.4f}",
    ]
    if measurement.interstage_correlation is not None:
        lines.extend(
            [
                "# HELP hapax_audio_interstage_correlation Pearson envelope correlation between stages",
                "# TYPE hapax_audio_interstage_correlation gauge",
                f"hapax_audio_interstage_correlation {measurement.interstage_correlation:.4f}",
            ]
        )
    return lines


__all__ = [
    "M1Alert",
    "M1Config",
    "M1ExtendedMeasurement",
    "classify_m1",
    "compute_envelope_correlation",
    "compute_lufs_s",
    "compute_spectral_flatness",
    "m1_prometheus_lines",
    "measure_m1",
]
