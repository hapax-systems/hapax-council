"""FFT-based audio marker probe — live signal layer.

Pure-logic companion to :mod:`shared.audio_marker_probe_harness` (the
fixture/policy layer shipped via PR #1897). This module produces
real PCM marker tones and detects their presence in a captured
buffer; the existing harness's live runner (a forthcoming slice)
calls into here when the operator authorizes a live probe.

Carrier selection
-----------------

The default carrier is a 17.5 kHz sine wave. That sits above the
operator's voice band (which tops out around 8-10 kHz for speech
fundamentals plus 2-4 kHz of consonant energy) and below the Nyquist
limit of 24 kHz at 48 kHz sample-rate, so:

- The marker is inaudible to most adult listeners (the audience age-
  distribution skew + speaker frequency response makes 17.5 kHz
  effectively silent on broadcast equipment).
- The marker survives standard speech codecs that low-pass around
  16 kHz — they attenuate but don't fully erase the carrier, and the
  detection threshold is set with that attenuation budgeted in.
- The marker doesn't alias when downsampled to 44.1 kHz (Nyquist
  22.05 kHz, well above 17.5).

Detection
---------

:func:`detect_marker_in_capture` runs an FFT on the supplied PCM
samples, identifies the bin closest to the carrier, and computes
the SNR as ``peak_db - noise_floor_db``. The noise floor is the
median magnitude across all bins outside a ±2-bin guard region
around the carrier (median rather than mean so a second strong tone
elsewhere in the band doesn't drag the floor up). When SNR exceeds
the configured threshold (default 12 dB), the marker is reported as
detected.

Pure-logic. The caller (the future live runner) supplies samples;
this module never opens PipeWire, mics, or speakers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np

#: Default carrier frequency. See module docstring for selection
#: rationale (17.5 kHz: above voice band, below Nyquist on every
#: standard sample rate, survives speech codecs).
DEFAULT_MARKER_FREQ_HZ: Final[float] = 17500.0

#: Default sample rate. Matches the operator's audio interface
#: (48 kHz).
DEFAULT_SAMPLE_RATE_HZ: Final[int] = 48000

#: Default tone amplitude as a fraction of int16 full-scale. -20 dBFS
#: keeps the marker quiet enough that it's unlikely to clip at any
#: stage of the broadcast pipeline while staying well above the
#: detection threshold.
DEFAULT_AMPLITUDE: Final[float] = 0.1

#: Default detection threshold in dB. The marker must exceed the
#: noise floor by at least this much to count as detected. 12 dB
#: catches the marker through typical speech-codec attenuation while
#: rejecting random tonal interference.
DEFAULT_SNR_THRESHOLD_DB: Final[float] = 12.0

#: Minimum capture duration. Below this the FFT bin width is too
#: coarse to discriminate the marker from neighbours. 0.05 s at
#: 48 kHz gives a bin width of ~20 Hz which comfortably resolves
#: the carrier.
MIN_CAPTURE_DURATION_S: Final[float] = 0.05


@dataclass(frozen=True)
class MarkerDetection:
    """Outcome of :func:`detect_marker_in_capture`.

    ``detected`` is ``True`` when the SNR exceeded the configured
    threshold. ``snr_db`` and ``peak_freq_hz`` record what the FFT
    actually measured so callers can log the evidence even when the
    detection threshold was missed (post-hoc tuning, intermittent
    routing failures, etc.).

    ``failure_reason`` carries a short tag for the fail-closed paths
    (``"no-samples"``, ``"too-short"``, ``"snr-below-threshold"``,
    ``"all-zero-capture"``) so the caller can route different failure
    modes to different remediation actions.
    """

    detected: bool
    snr_db: float
    peak_freq_hz: float
    target_freq_hz: float
    failure_reason: str | None


def generate_marker_tone(
    freq_hz: float = DEFAULT_MARKER_FREQ_HZ,
    duration_s: float = 1.0,
    *,
    sample_rate: int = DEFAULT_SAMPLE_RATE_HZ,
    amplitude: float = DEFAULT_AMPLITUDE,
) -> np.ndarray:
    """Generate a deterministic int16 PCM sine tone at ``freq_hz``.

    Returns a 1-D ``numpy.ndarray`` of dtype ``int16`` containing
    ``sample_rate * duration_s`` samples (rounded to int). Phase is
    fixed so two calls with identical arguments yield byte-identical
    output — important for fixture tests that need stable evidence.

    Raises ``ValueError`` for non-positive frequency / duration /
    sample-rate, or amplitude outside ``(0, 1]`` (zero would produce
    silence, >1 would clip).
    """
    if freq_hz <= 0:
        raise ValueError(f"freq_hz must be > 0, got {freq_hz}")
    if duration_s <= 0:
        raise ValueError(f"duration_s must be > 0, got {duration_s}")
    if sample_rate <= 0:
        raise ValueError(f"sample_rate must be > 0, got {sample_rate}")
    if not 0.0 < amplitude <= 1.0:
        raise ValueError(f"amplitude must be in (0, 1], got {amplitude}")
    if freq_hz >= sample_rate / 2.0:
        raise ValueError(
            f"freq_hz {freq_hz} exceeds Nyquist {sample_rate / 2.0} for sample_rate {sample_rate}"
        )

    n_samples = int(round(sample_rate * duration_s))
    t = np.arange(n_samples, dtype=np.float64) / float(sample_rate)
    wave = amplitude * np.sin(2.0 * np.pi * freq_hz * t)
    return (wave * (2**15 - 1)).astype(np.int16)


def _spectrum_db(samples: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (frequencies, magnitudes_db) of a real-valued PCM buffer.

    Applies a Hann window before the FFT so spectral leakage doesn't
    smear the marker peak across multiple bins. Magnitudes are
    converted to dB with a tiny epsilon floor so silent buffers don't
    produce ``-inf``.
    """
    n = len(samples)
    if n == 0:
        return np.array([]), np.array([])
    window = np.hanning(n)
    windowed = samples.astype(np.float64) * window
    spectrum = np.fft.rfft(windowed)
    magnitudes = np.abs(spectrum)
    # Add a tiny epsilon so log10(0) doesn't blow up — silent buffers
    # land at -inf otherwise, and arithmetic on them propagates NaN.
    epsilon = 1e-12
    magnitudes_db = 20.0 * np.log10(magnitudes + epsilon)
    freqs = np.fft.rfftfreq(n, d=1.0)
    return freqs, magnitudes_db


def detect_marker_in_capture(
    samples: np.ndarray,
    freq_hz: float = DEFAULT_MARKER_FREQ_HZ,
    *,
    sample_rate: int = DEFAULT_SAMPLE_RATE_HZ,
    snr_threshold_db: float = DEFAULT_SNR_THRESHOLD_DB,
    guard_bins: int = 2,
) -> MarkerDetection:
    """Detect the marker tone in ``samples`` and report its SNR.

    The capture is windowed (Hann), FFT'd, and the bin nearest
    ``freq_hz`` is compared to the median magnitude of all bins
    outside a ±``guard_bins`` guard region around the carrier. When
    the resulting SNR exceeds ``snr_threshold_db``, the marker is
    reported as detected.

    Fail-closed paths return ``detected=False`` with a populated
    ``failure_reason``:

    - ``"no-samples"`` — empty capture
    - ``"too-short"`` — capture below
      :data:`MIN_CAPTURE_DURATION_S`
    - ``"all-zero-capture"`` — capture consists entirely of zeros
      (the upstream stage may have failed to feed audio at all)
    - ``"snr-below-threshold"`` — peak found but didn't clear the
      threshold
    """
    if samples is None or len(samples) == 0:
        return MarkerDetection(
            detected=False,
            snr_db=float("-inf"),
            peak_freq_hz=0.0,
            target_freq_hz=freq_hz,
            failure_reason="no-samples",
        )

    duration_s = len(samples) / float(sample_rate)
    if duration_s < MIN_CAPTURE_DURATION_S:
        return MarkerDetection(
            detected=False,
            snr_db=float("-inf"),
            peak_freq_hz=0.0,
            target_freq_hz=freq_hz,
            failure_reason="too-short",
        )

    if not np.any(samples):
        return MarkerDetection(
            detected=False,
            snr_db=float("-inf"),
            peak_freq_hz=0.0,
            target_freq_hz=freq_hz,
            failure_reason="all-zero-capture",
        )

    freqs_norm, mags_db = _spectrum_db(samples)
    if len(mags_db) == 0:
        return MarkerDetection(
            detected=False,
            snr_db=float("-inf"),
            peak_freq_hz=0.0,
            target_freq_hz=freq_hz,
            failure_reason="no-samples",
        )

    freqs_hz = freqs_norm * float(sample_rate)
    target_bin = int(np.argmin(np.abs(freqs_hz - freq_hz)))

    lo = max(0, target_bin - guard_bins)
    hi = min(len(mags_db), target_bin + guard_bins + 1)
    mask = np.ones(len(mags_db), dtype=bool)
    mask[lo:hi] = False
    floor_db = float(np.median(mags_db[mask])) if mask.any() else float("-inf")

    peak_db = float(mags_db[target_bin])
    snr_db = peak_db - floor_db
    peak_freq_hz = float(freqs_hz[target_bin])

    if snr_db < snr_threshold_db:
        return MarkerDetection(
            detected=False,
            snr_db=snr_db,
            peak_freq_hz=peak_freq_hz,
            target_freq_hz=freq_hz,
            failure_reason="snr-below-threshold",
        )

    return MarkerDetection(
        detected=True,
        snr_db=snr_db,
        peak_freq_hz=peak_freq_hz,
        target_freq_hz=freq_hz,
        failure_reason=None,
    )
