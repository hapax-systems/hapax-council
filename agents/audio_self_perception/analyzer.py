"""Spectral analysis for audio self-perception.

Computes four features from a mono PCM buffer captured from normalized
broadcast egress:

1. RMS (dBFS) — signal presence
2. Spectral centroid (Hz) — frequency balance center of mass
3. Spectral balance — low-band vs high-band energy ratio
4. Voice/Music/Environment ratios — heuristic band-energy classification
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

_DBFS_FLOOR: float = -120.0

# Band boundaries (Hz) for heuristic V/M/E classification.
# Voice: 85–3000 Hz (fundamental + formants)
# Music: 40–8000 Hz minus voice band
# Environment: everything else (sub-bass rumble + high-frequency air)
_VOICE_LOW: float = 85.0
_VOICE_HIGH: float = 3000.0
_MUSIC_LOW: float = 40.0
_MUSIC_HIGH: float = 8000.0

# Spectral balance split frequency
_BALANCE_SPLIT_HZ: float = 1000.0


@dataclass(frozen=True)
class AudioPerception:
    """One snapshot of the system's audio self-perception."""

    rms_dbfs: float
    spectral_centroid_hz: float
    low_high_ratio: float
    voice_ratio: float
    music_ratio: float
    env_ratio: float
    sample_rate: int
    sample_count: int

    def to_dict(self) -> dict:
        return {
            "rms_dbfs": round(self.rms_dbfs, 2),
            "spectral_centroid_hz": round(self.spectral_centroid_hz, 1),
            "low_high_ratio": round(self.low_high_ratio, 4),
            "voice_ratio": round(self.voice_ratio, 4),
            "music_ratio": round(self.music_ratio, 4),
            "env_ratio": round(self.env_ratio, 4),
            "sample_rate": self.sample_rate,
            "sample_count": self.sample_count,
        }


def analyze(samples: np.ndarray, sample_rate: int = 48000) -> AudioPerception:
    """Compute all four audio self-perception features from mono PCM.

    Accepts int16 (parecord raw) or float arrays. Returns an
    AudioPerception with all fields populated.
    """
    if samples.size < 2:
        return AudioPerception(
            rms_dbfs=_DBFS_FLOOR,
            spectral_centroid_hz=0.0,
            low_high_ratio=1.0,
            voice_ratio=0.0,
            music_ratio=0.0,
            env_ratio=0.0,
            sample_rate=sample_rate,
            sample_count=0,
        )

    if np.issubdtype(samples.dtype, np.integer):
        floats = samples.astype(np.float64) / 32768.0
    else:
        floats = samples.astype(np.float64, copy=False)

    rms = float(np.sqrt(np.mean(np.square(floats))))
    if rms <= 0:
        rms_dbfs = _DBFS_FLOOR
    else:
        import math

        rms_dbfs = max(_DBFS_FLOOR, 20.0 * math.log10(rms))

    spectrum = np.abs(np.fft.rfft(floats)) ** 2
    if spectrum.size > 2:
        spectrum = spectrum[1:-1]

    n_bins = spectrum.size
    if n_bins == 0:
        return AudioPerception(
            rms_dbfs=rms_dbfs,
            spectral_centroid_hz=0.0,
            low_high_ratio=1.0,
            voice_ratio=0.0,
            music_ratio=0.0,
            env_ratio=0.0,
            sample_rate=sample_rate,
            sample_count=int(samples.size),
        )

    freqs = np.linspace(0, sample_rate / 2.0, n_bins + 2)[1:-1]
    total_energy = float(np.sum(spectrum))

    if total_energy < 1e-20:
        return AudioPerception(
            rms_dbfs=rms_dbfs,
            spectral_centroid_hz=0.0,
            low_high_ratio=1.0,
            voice_ratio=0.0,
            music_ratio=0.0,
            env_ratio=0.0,
            sample_rate=sample_rate,
            sample_count=int(samples.size),
        )

    centroid = float(np.sum(freqs * spectrum) / total_energy)

    low_mask = freqs < _BALANCE_SPLIT_HZ
    high_mask = freqs >= _BALANCE_SPLIT_HZ
    low_energy = float(np.sum(spectrum[low_mask])) if np.any(low_mask) else 0.0
    high_energy = float(np.sum(spectrum[high_mask])) if np.any(high_mask) else 0.0
    low_high_ratio = low_energy / max(high_energy, 1e-20)

    voice_mask = (freqs >= _VOICE_LOW) & (freqs <= _VOICE_HIGH)
    music_mask = ((freqs >= _MUSIC_LOW) & (freqs < _VOICE_LOW)) | (
        (freqs > _VOICE_HIGH) & (freqs <= _MUSIC_HIGH)
    )
    env_mask = ~voice_mask & ~music_mask

    voice_energy = float(np.sum(spectrum[voice_mask])) if np.any(voice_mask) else 0.0
    music_energy = float(np.sum(spectrum[music_mask])) if np.any(music_mask) else 0.0
    env_energy = float(np.sum(spectrum[env_mask])) if np.any(env_mask) else 0.0

    band_total = voice_energy + music_energy + env_energy
    if band_total > 0:
        voice_ratio = voice_energy / band_total
        music_ratio = music_energy / band_total
        env_ratio = env_energy / band_total
    else:
        voice_ratio = music_ratio = env_ratio = 0.0

    return AudioPerception(
        rms_dbfs=rms_dbfs,
        spectral_centroid_hz=centroid,
        low_high_ratio=low_high_ratio,
        voice_ratio=voice_ratio,
        music_ratio=music_ratio,
        env_ratio=env_ratio,
        sample_rate=sample_rate,
        sample_count=int(samples.size),
    )


__all__ = ["AudioPerception", "analyze"]
