"""Acoustic impulse writer — cross-modal signal from Daimonion to Reverie.

Computes RMS energy from PCM audio output and writes a signal file
that the ReverieMixer reads to create visual impingements from sound.
"""

from __future__ import annotations

import json
import logging
import math
import struct
import time
from pathlib import Path

log = logging.getLogger(__name__)

ACOUSTIC_IMPULSE_FILE = Path("/dev/shm/hapax-visual/acoustic-impulse.json")


def write_acoustic_impulse(
    pcm_data: bytes,
    sample_rate: int = 24000,
    channels: int = 1,
    path: Path | None = None,
) -> None:
    """Compute RMS energy from PCM16 data and write acoustic impulse for Reverie.

    Called from TTS/audio executors after synthesizing or playing audio.
    The ReverieMixer reads this file and injects it as a visual impingement.
    """
    p = path or ACOUSTIC_IMPULSE_FILE

    energy = _compute_rms_energy(pcm_data, channels)
    if energy < 0.01:
        return  # below noise floor, don't write

    # Detect onset (energy jump) — simple threshold
    onset = energy > 0.3

    # Estimate fundamental pitch from zero-crossing rate (rough but cheap)
    pitch_hz = _estimate_pitch_zcr(pcm_data, sample_rate, channels)

    data = {
        "source": "daimonion",
        "timestamp": time.time(),
        "signals": {
            "energy": round(energy, 3),
            "onset": onset,
            "pitch_hz": round(pitch_hz, 1),
        },
    }

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        tmp.rename(p)
    except OSError:
        log.debug("Failed to write acoustic impulse", exc_info=True)


def _compute_rms_energy(pcm_data: bytes, channels: int = 1) -> float:
    """Compute RMS energy from PCM16 audio, normalized to [0, 1]."""
    if len(pcm_data) < 4:
        return 0.0

    num_samples = len(pcm_data) // 2
    if num_samples == 0:
        return 0.0

    sum_sq = 0.0
    for i in range(0, len(pcm_data) - 1, 2 * channels):
        sample = struct.unpack_from("<h", pcm_data, i)[0]
        sum_sq += sample * sample

    samples_counted = num_samples // channels
    if samples_counted == 0:
        return 0.0

    rms = math.sqrt(sum_sq / samples_counted)
    # Normalize: PCM16 max is 32767
    return min(1.0, rms / 32767.0 * 3.0)  # scale factor for typical speech levels


def _estimate_pitch_zcr(pcm_data: bytes, sample_rate: int, channels: int) -> float:
    """Estimate pitch via zero-crossing rate. Rough but no dependencies."""
    if len(pcm_data) < 100:
        return 0.0

    crossings = 0
    prev_sign = 0
    for i in range(0, len(pcm_data) - 1, 2 * channels):
        sample = struct.unpack_from("<h", pcm_data, i)[0]
        sign = 1 if sample >= 0 else -1
        if prev_sign != 0 and sign != prev_sign:
            crossings += 1
        prev_sign = sign

    samples_counted = len(pcm_data) // (2 * channels)
    if samples_counted == 0:
        return 0.0

    duration_s = samples_counted / sample_rate
    if duration_s == 0:
        return 0.0

    # ZCR → frequency: f ≈ crossings / (2 * duration)
    return crossings / (2.0 * duration_s)
