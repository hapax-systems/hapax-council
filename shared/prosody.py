"""Prosodic feature extraction for speech perception.

Extracts paralinguistic features from speech audio so the LLM knows
HOW something was said, not just WHAT. Features are written to /dev/shm
and read by phenomenal_context Layer 2c.

Dependencies: parselmouth (Praat wrapper), numpy. No GPU needed.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

PROSODY_SHM_PATH = Path("/dev/shm/hapax-daimonion/prosody.json")
_STALENESS_THRESHOLD = 30  # seconds
_PAUSE_THRESHOLD_S = 0.3
_BASELINE_WPM = 140.0


@dataclass(frozen=True)
class ProsodyFeatures:
    """Extracted prosodic features from a single utterance."""

    f0_mean_hz: float | None = None
    f0_std_hz: float | None = None
    speaking_rate_wpm: float | None = None
    pause_count: int = 0
    pause_total_s: float = 0.0
    rms_db: float | None = None
    hnr_db: float | None = None
    duration_s: float = 0.0
    word_count: int = 0
    timestamp: float = 0.0


def extract_prosody(
    audio: np.ndarray,
    sample_rate: int = 16000,
    word_timestamps: list[dict] | None = None,
) -> ProsodyFeatures:
    """Extract prosodic features from speech audio.

    Args:
        audio: Float32 normalized audio (-1 to 1)
        sample_rate: Sample rate in Hz
        word_timestamps: List of {"word": str, "start": float, "end": float}
    """
    duration = len(audio) / sample_rate
    now = time.time()

    rms = float(20 * np.log10(max(np.sqrt(np.mean(audio**2)), 1e-10)))

    f0_mean = None
    f0_std = None
    hnr_mean = None
    try:
        import parselmouth

        snd = parselmouth.Sound(audio, sampling_frequency=sample_rate)

        pitch = snd.to_pitch()
        f0_values = pitch.selected_array["frequency"]
        voiced = f0_values[f0_values > 0]
        if len(voiced) > 2:
            f0_mean = round(float(np.mean(voiced)), 1)
            f0_std = round(float(np.std(voiced)), 1)

        harmonicity = snd.to_harmonicity()
        hnr_values = harmonicity.values[harmonicity.values != -200]
        if len(hnr_values) > 0:
            hnr_mean = round(float(np.mean(hnr_values)), 1)
    except Exception:
        pass

    wpm = None
    pause_count = 0
    pause_total = 0.0
    word_count = 0

    if word_timestamps:
        word_count = len(word_timestamps)
        if duration > 0:
            wpm = round(word_count / (duration / 60), 1)

        for i in range(1, len(word_timestamps)):
            gap = word_timestamps[i]["start"] - word_timestamps[i - 1]["end"]
            if gap >= _PAUSE_THRESHOLD_S:
                pause_count += 1
                pause_total += gap

    return ProsodyFeatures(
        f0_mean_hz=f0_mean,
        f0_std_hz=f0_std,
        speaking_rate_wpm=wpm,
        pause_count=pause_count,
        pause_total_s=round(pause_total, 2),
        rms_db=round(rms, 1),
        hnr_db=hnr_mean,
        duration_s=round(duration, 2),
        word_count=word_count,
        timestamp=now,
    )


def write_prosody(features: ProsodyFeatures, path: Path = PROSODY_SHM_PATH) -> None:
    """Write prosody features to /dev/shm atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp")
    tmp.write_text(json.dumps(asdict(features)), encoding="utf-8")
    tmp.replace(path)


def read_prosody_block(path: Path = PROSODY_SHM_PATH) -> str:
    """Read prosody features and render as natural language for LLM injection.

    Returns empty string if data is missing or stale (>30s).
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        ts = raw.get("timestamp", 0)
        if ts > 0 and (time.time() - ts) > _STALENESS_THRESHOLD:
            return ""

        lines: list[str] = []

        wpm = raw.get("speaking_rate_wpm")
        if wpm is not None:
            if wpm < 100:
                pace = "slow"
            elif wpm < 160:
                pace = "measured"
            elif wpm < 200:
                pace = "brisk"
            else:
                pace = "rapid"
            lines.append(f"pace: {pace} ({wpm:.0f} wpm)")

        f0_mean = raw.get("f0_mean_hz")
        f0_std = raw.get("f0_std_hz")
        if f0_mean is not None and f0_std is not None:
            if f0_std < 15:
                contour = "flat"
            elif f0_std < 30:
                contour = "moderate variation"
            else:
                contour = "expressive"
            lines.append(f"pitch: {contour} (mean {f0_mean:.0f} Hz, variation {f0_std:.0f} Hz)")

        rms = raw.get("rms_db")
        if rms is not None:
            if rms > -15:
                energy = "loud"
            elif rms > -25:
                energy = "normal"
            elif rms > -35:
                energy = "quiet"
            else:
                energy = "very quiet"
            lines.append(f"energy: {energy} ({rms:.0f} dB)")

        pause_count = raw.get("pause_count", 0)
        if pause_count > 0:
            pause_total = raw.get("pause_total_s", 0)
            lines.append(f"pauses: {pause_count} pause(s), {pause_total:.1f}s total")

        hnr = raw.get("hnr_db")
        if hnr is not None:
            if hnr > 20:
                quality = "clear"
            elif hnr > 10:
                quality = "normal"
            else:
                quality = "breathy"
            lines.append(f"voice quality: {quality} (HNR {hnr:.0f} dB)")

        if not lines:
            return ""

        return "Operator speech prosody:\n" + "\n".join(f"  {l}" for l in lines)
    except Exception:
        return ""
