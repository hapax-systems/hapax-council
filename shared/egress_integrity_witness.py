"""Egress-integrity witness — classify capture audio quality.

Distinguishes four egress states at the broadcast-master capture point:
- SILENCE: no audio (below noise floor)
- NORMAL: clean programme audio (music/voice)
- GARBLED: clipped, corrupt, or distorted capture (high zero-crossing rate
  with abnormal crest factor)
- UNKNOWN: insufficient data or probe failure

The witness samples broadcast-master audio and applies lightweight DSP
heuristics. It does NOT use pw-cat directly — callers provide PCM data
or the witness reads from a pre-existing loopback capture file.

Cc-task: audio-egress-integrity-l12-wake-lock-20260521
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import numpy as np

log = logging.getLogger(__name__)


class EgressQuality(StrEnum):
    """Capture audio quality classification."""

    SILENCE = "silence"
    NORMAL = "normal"
    GARBLED = "garbled"
    UNKNOWN = "unknown"


# ── Thresholds ───────────────────────────────────────────────────────────────

# RMS below this is silence (-60 dBFS)
SILENCE_THRESHOLD_DBFS: float = -60.0

# Zero-crossing rate above this suggests garbled/clipped audio.
# Normal music: 500-3000 ZCR/s. Garbled/corrupt: >8000 ZCR/s.
GARBLED_ZCR_THRESHOLD: float = 8000.0

# Crest factor (peak/RMS ratio in dB) below this with high ZCR = garbled.
# Normal music: 10-20 dB. Hard-clipped/garbled: <4 dB.
GARBLED_CREST_FACTOR_THRESHOLD_DB: float = 4.0

# Minimum sample count for reliable analysis (0.5s at 48kHz)
MIN_SAMPLES: int = 24000


@dataclass(frozen=True)
class EgressIntegrityReport:
    """Result of an egress integrity check."""

    quality: EgressQuality
    rms_dbfs: float  # -inf for silence
    peak_dbfs: float
    crest_factor_db: float  # peak - rms in dB
    zero_crossing_rate: float  # per second
    sample_count: int
    sample_rate: int
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "quality": self.quality.value,
            "rms_dbfs": self.rms_dbfs if math.isfinite(self.rms_dbfs) else None,
            "peak_dbfs": self.peak_dbfs if math.isfinite(self.peak_dbfs) else None,
            "crest_factor_db": (
                self.crest_factor_db if math.isfinite(self.crest_factor_db) else None
            ),
            "zero_crossing_rate": self.zero_crossing_rate,
            "sample_count": self.sample_count,
            "sample_rate": self.sample_rate,
            "reasons": self.reasons,
        }


def _rms_dbfs(samples: np.ndarray) -> float:
    """RMS level in dBFS for int16 PCM."""
    if len(samples) == 0:
        return float("-inf")
    rms = np.sqrt(np.mean(samples.astype(np.float64) ** 2))
    if rms < 1e-10:
        return float("-inf")
    return 20.0 * math.log10(rms / 32768.0)


def _peak_dbfs(samples: np.ndarray) -> float:
    """Peak level in dBFS for int16 PCM."""
    if len(samples) == 0:
        return float("-inf")
    peak = float(np.max(np.abs(samples.astype(np.float64))))
    if peak < 1e-10:
        return float("-inf")
    return 20.0 * math.log10(peak / 32768.0)


def _zero_crossing_rate(samples: np.ndarray, sample_rate: int) -> float:
    """Zero-crossing rate per second."""
    if len(samples) < 2:
        return 0.0
    signs = np.sign(samples.astype(np.float64))
    crossings = np.sum(np.abs(np.diff(signs)) > 0)
    duration_s = len(samples) / sample_rate
    if duration_s < 1e-6:
        return 0.0
    return float(crossings) / duration_s


def classify_egress(
    pcm_int16: bytes | np.ndarray,
    *,
    sample_rate: int = 48000,
    channels: int = 1,
    channel_index: int = 0,
    silence_threshold_dbfs: float = SILENCE_THRESHOLD_DBFS,
    garbled_zcr_threshold: float = GARBLED_ZCR_THRESHOLD,
    garbled_crest_threshold_db: float = GARBLED_CREST_FACTOR_THRESHOLD_DB,
    min_samples: int = MIN_SAMPLES,
) -> EgressIntegrityReport:
    """Classify audio capture quality from raw PCM data.

    Accepts interleaved int16 PCM. If multi-channel, extracts the
    specified channel_index.
    """
    # Convert bytes to numpy array
    if isinstance(pcm_int16, bytes):
        if not pcm_int16:
            return EgressIntegrityReport(
                quality=EgressQuality.UNKNOWN,
                rms_dbfs=float("-inf"),
                peak_dbfs=float("-inf"),
                crest_factor_db=float("-inf"),
                zero_crossing_rate=0.0,
                sample_count=0,
                sample_rate=sample_rate,
                reasons=["empty PCM buffer"],
            )
        arr = np.frombuffer(pcm_int16, dtype=np.int16)
    else:
        arr = pcm_int16.astype(np.int16)

    # Extract single channel from interleaved
    if channels > 1:
        # Truncate to whole-frame boundary
        frame_count = len(arr) // channels
        arr = arr[: frame_count * channels]
        arr = arr[channel_index::channels]

    sample_count = len(arr)
    if sample_count < min_samples:
        return EgressIntegrityReport(
            quality=EgressQuality.UNKNOWN,
            rms_dbfs=float("-inf"),
            peak_dbfs=float("-inf"),
            crest_factor_db=float("-inf"),
            zero_crossing_rate=0.0,
            sample_count=sample_count,
            sample_rate=sample_rate,
            reasons=[f"insufficient samples: {sample_count} < {min_samples}"],
        )

    rms = _rms_dbfs(arr)
    peak = _peak_dbfs(arr)
    zcr = _zero_crossing_rate(arr, sample_rate)
    crest_db = peak - rms if math.isfinite(peak) and math.isfinite(rms) else float("-inf")

    reasons: list[str] = []

    # Silence check
    if rms < silence_threshold_dbfs:
        return EgressIntegrityReport(
            quality=EgressQuality.SILENCE,
            rms_dbfs=rms,
            peak_dbfs=peak,
            crest_factor_db=crest_db,
            zero_crossing_rate=zcr,
            sample_count=sample_count,
            sample_rate=sample_rate,
            reasons=[f"RMS {rms:.1f} dBFS below silence threshold {silence_threshold_dbfs}"],
        )

    # Garbled check: high ZCR + low crest factor = clipped/corrupt
    is_garbled = False
    if zcr > garbled_zcr_threshold and crest_db < garbled_crest_threshold_db:
        is_garbled = True
        reasons.append(
            f"high ZCR ({zcr:.0f}/s > {garbled_zcr_threshold}) "
            f"with low crest factor ({crest_db:.1f} dB < {garbled_crest_threshold_db})"
        )

    # Near-clipping with sustained high level also suggests garbled
    if peak > -0.5 and crest_db < 3.0:
        is_garbled = True
        reasons.append(
            f"near-clipping peak ({peak:.1f} dBFS) with crushed dynamics (crest {crest_db:.1f} dB)"
        )

    quality = EgressQuality.GARBLED if is_garbled else EgressQuality.NORMAL
    if not reasons:
        reasons.append(
            f"normal audio: RMS={rms:.1f} dBFS, peak={peak:.1f} dBFS, "
            f"crest={crest_db:.1f} dB, ZCR={zcr:.0f}/s"
        )

    return EgressIntegrityReport(
        quality=quality,
        rms_dbfs=rms,
        peak_dbfs=peak,
        crest_factor_db=crest_db,
        zero_crossing_rate=zcr,
        sample_count=sample_count,
        sample_rate=sample_rate,
        reasons=reasons,
    )


__all__ = [
    "EgressIntegrityReport",
    "EgressQuality",
    "classify_egress",
]
