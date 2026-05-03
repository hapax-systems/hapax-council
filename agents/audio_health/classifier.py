"""Signal classification: RMS, crest, ZCR, then label.

Per the source research §3.1, a 5-class classification covers the
failure modes the operator actually cares about:

- ``silent``: RMS < silence_floor_dbfs (default -55 dBFS, override via env).
- ``tone``: crest factor < tone_crest_max (default 2.0). Sine-like;
  format-conversion drone or DC-offset hum lands here.
- ``music`` / ``voice``: crest factor > music_crest_min (default 5.0)
  AND zero-crossing rate < music_zcr_max (default 0.15). Wide-band
  natural broadcast content with strong transients.
- ``noise``: crest factor in the white-noise band [2.5, 5.0] AND ZCR
  > noise_zcr_min (default 0.25). Caught the +20 dB OBS clipping noise
  and the broadcast-master white-noise pathology in the source research.
- ``clipping``: peak > clipping_peak_dbfs (default -1 dBFS) sustained,
  OR crest < 5 with RMS > clipping_rms_dbfs (default -10 dBFS) — the
  "broadcast normalized but slammed against the limiter" failure mode.

The thresholds form a strict precedence order: ``clipping > silent >
tone > noise > music_voice``. A waveform that simultaneously matches
multiple classes lands on the worst (most failure-mode-like) class so
the operator gets the strongest signal.

Decision matrix is fully tunable via environment variables (see
:class:`ClassifierConfig`) so the operator can re-tune thresholds
without redeploying.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

import numpy as np

# Reference full-scale for int16 dBFS conversion: 1.0 in unit-normalized
# float space. parecord emits s16le; we divide by 32768 before measure.
_INT16_FULL_SCALE: Final[float] = 32768.0

# Floor for log10 conversion — avoids -inf when RMS is exactly zero.
_DBFS_FLOOR: Final[float] = -120.0


class Classification(StrEnum):
    """Five mutually-exclusive classification labels.

    Ordered by precedence: when a waveform matches multiple, the worst
    (highest-index) wins so the alerter never under-reports severity.
    """

    MUSIC_VOICE = "music_voice"
    TONE = "tone"
    NOISE = "noise"
    SILENT = "silent"
    CLIPPING = "clipping"


@dataclass(frozen=True)
class ClassifierConfig:
    """Tunable thresholds — env-overridable so operator can retune live.

    Defaults match the source research §3.1 heuristics. Every field
    reads ``HAPAX_AUDIO_SIGNAL_<UPPER>`` if set, falls back to the
    constructor default otherwise.
    """

    silence_floor_dbfs: float = -55.0
    tone_crest_max: float = 2.0
    music_crest_min: float = 5.0
    music_zcr_max: float = 0.15
    noise_crest_min: float = 2.5
    noise_crest_max: float = 5.0
    noise_zcr_min: float = 0.25
    clipping_peak_dbfs: float = -1.0
    clipping_rms_dbfs: float = -10.0
    clipping_crest_max: float = 5.0

    @classmethod
    def from_env(cls) -> ClassifierConfig:
        """Build from ``HAPAX_AUDIO_SIGNAL_*`` env vars, falling back to defaults."""

        def _get(key: str, default: float) -> float:
            raw = os.environ.get(f"HAPAX_AUDIO_SIGNAL_{key}")
            if raw is None or raw == "":
                return default
            try:
                return float(raw)
            except ValueError:
                return default

        return cls(
            silence_floor_dbfs=_get("SILENCE_FLOOR_DBFS", cls.silence_floor_dbfs),
            tone_crest_max=_get("TONE_CREST_MAX", cls.tone_crest_max),
            music_crest_min=_get("MUSIC_CREST_MIN", cls.music_crest_min),
            music_zcr_max=_get("MUSIC_ZCR_MAX", cls.music_zcr_max),
            noise_crest_min=_get("NOISE_CREST_MIN", cls.noise_crest_min),
            noise_crest_max=_get("NOISE_CREST_MAX", cls.noise_crest_max),
            noise_zcr_min=_get("NOISE_ZCR_MIN", cls.noise_zcr_min),
            clipping_peak_dbfs=_get("CLIPPING_PEAK_DBFS", cls.clipping_peak_dbfs),
            clipping_rms_dbfs=_get("CLIPPING_RMS_DBFS", cls.clipping_rms_dbfs),
            clipping_crest_max=_get("CLIPPING_CREST_MAX", cls.clipping_crest_max),
        )


@dataclass(frozen=True)
class ProbeMeasurement:
    """Raw acoustic measurements derived from a captured PCM window.

    All fields are pure functions of the captured samples — no
    classification decision lives here. Measurement is decoupled from
    classification so we can re-classify cached measurements with new
    thresholds without re-capturing audio.
    """

    rms_dbfs: float
    peak_dbfs: float
    crest_factor: float
    zero_crossing_rate: float
    sample_count: int = field(default=0)


def measure_pcm(samples: np.ndarray) -> ProbeMeasurement:
    """Compute RMS, peak, crest factor, ZCR from a raw PCM window.

    Accepts either ``int16`` (parecord raw output) or ``float`` arrays.
    Mono is required: callers that want stereo must downmix or pick a
    channel before invoking this. ``float`` inputs are treated as
    already-normalised to ``[-1, 1]``.

    The returned :class:`ProbeMeasurement` is normalised so all dBFS
    values are bounded below by ``_DBFS_FLOOR`` (no -inf), and
    ``crest_factor`` is bounded below by 0.
    """

    if samples.ndim != 1:
        raise ValueError(f"measure_pcm requires mono samples, got ndim={samples.ndim}")
    if samples.size == 0:
        return ProbeMeasurement(
            rms_dbfs=_DBFS_FLOOR,
            peak_dbfs=_DBFS_FLOOR,
            crest_factor=0.0,
            zero_crossing_rate=0.0,
            sample_count=0,
        )

    if np.issubdtype(samples.dtype, np.integer):
        # int16 → unit-normalised float for measurement.
        floats = samples.astype(np.float64) / _INT16_FULL_SCALE
    else:
        floats = samples.astype(np.float64, copy=False)

    abs_samples = np.abs(floats)
    peak = float(abs_samples.max())
    rms = float(np.sqrt(np.mean(np.square(floats))))

    if rms <= 0.0:
        rms_dbfs = _DBFS_FLOOR
        crest_factor = 0.0
    else:
        rms_dbfs = max(_DBFS_FLOOR, 20.0 * math.log10(rms))
        # Crest factor is the dimensionless ratio peak / RMS. A square
        # wave is ~1.0, sine ~1.41, white noise ~3.5–4.5, music 5+.
        crest_factor = peak / rms

    if peak <= 0.0:
        peak_dbfs = _DBFS_FLOOR
    else:
        peak_dbfs = max(_DBFS_FLOOR, 20.0 * math.log10(peak))

    # Zero-crossing rate: how often the signal flips polarity. Tones
    # have very low ZCR (one crossing per period), noise has high ZCR.
    # Counted on the unit-normalised float buffer so dtype doesn't
    # affect the rate.
    if floats.size > 1:
        signs = np.signbit(floats)
        crossings = int(np.count_nonzero(np.diff(signs)))
        zcr = crossings / (floats.size - 1)
    else:
        zcr = 0.0

    return ProbeMeasurement(
        rms_dbfs=rms_dbfs,
        peak_dbfs=peak_dbfs,
        crest_factor=crest_factor,
        zero_crossing_rate=zcr,
        sample_count=int(samples.size),
    )


def classify(
    measurement: ProbeMeasurement,
    config: ClassifierConfig | None = None,
) -> Classification:
    """Map a :class:`ProbeMeasurement` to a :class:`Classification`.

    Precedence (highest-severity wins):

    1. Clipping (peak > -1 dBFS sustained, OR crest < 5 with RMS > -10).
    2. Silent (RMS < silence floor).
    3. Tone (crest < 2.0 — DC offset / hum / format-conversion drone).
    4. Noise (crest in [2.5, 5.0] AND high ZCR).
    5. Music/voice (crest > 5.0 AND low ZCR).

    A measurement that doesn't match any explicit class falls through
    to ``music_voice`` — the daemon errs toward "not bad" so it cannot
    cause false-positive auto-mute (read-only constraint). Spurious
    music_voice classifications cause alerts to be *suppressed*, never
    raised; the operator still notices the absence via the existing
    LUFS / silence-ratio gates.
    """

    cfg = config or ClassifierConfig.from_env()

    # Clipping — checked first so peak-saturated chains don't get
    # classified as music. The OBS clipping pathology has peak ~ 0
    # dBFS and crest < 3.0 from the limiter slamming.
    if measurement.peak_dbfs >= cfg.clipping_peak_dbfs:
        return Classification.CLIPPING
    if (
        measurement.crest_factor < cfg.clipping_crest_max
        and measurement.rms_dbfs > cfg.clipping_rms_dbfs
    ):
        return Classification.CLIPPING

    # Silent — no real signal flowing.
    if measurement.rms_dbfs < cfg.silence_floor_dbfs:
        return Classification.SILENT

    # Tone — sine-like or DC drone. Caught format-conversion noise in
    # source research (crest 2.0 ish at -45 dB drone).
    if measurement.crest_factor < cfg.tone_crest_max:
        return Classification.TONE

    # Noise — white/pink/format-conversion artefact. The +20 dB
    # broadcast clipping noise from the source research lands here
    # when amplitude doesn't yet hit the clipping precedence above.
    if (
        cfg.noise_crest_min <= measurement.crest_factor <= cfg.noise_crest_max
        and measurement.zero_crossing_rate >= cfg.noise_zcr_min
    ):
        return Classification.NOISE

    # Music / voice — wide crest, lower ZCR, real natural signal.
    if (
        measurement.crest_factor >= cfg.music_crest_min
        and measurement.zero_crossing_rate <= cfg.music_zcr_max
    ):
        return Classification.MUSIC_VOICE

    # Unclassified residue (high crest with high ZCR, or mid-crest
    # with low ZCR) — read-only daemon defaults to "looks fine" so it
    # never cries wolf. Operator-visible failure surfaces (LUFS,
    # silence-ratio, voice-output-witness) catch silent-broadcast
    # cases independently.
    return Classification.MUSIC_VOICE


# Bad-state classifications that should fire alerts when sustained at
# the OBS-bound stage during livestream. Music/voice + tone are
# considered nominal-ish; silent only fires during livestream (handled
# by the transition layer).
BAD_STEADY_STATES: Final[frozenset[Classification]] = frozenset(
    {Classification.SILENT, Classification.NOISE, Classification.CLIPPING}
)


__all__ = [
    "BAD_STEADY_STATES",
    "Classification",
    "ClassifierConfig",
    "ProbeMeasurement",
    "classify",
    "measure_pcm",
]
