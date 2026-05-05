"""Operator voice pitch baseline for mood-valence calibration.

The mood-valence bridge only needs a low-cardinality acoustic feature:
recent operator F0, its session-local baseline, and whether the latest
voiced sample is elevated. This module never persists audio or transcript
content; it writes numeric pitch statistics to a SHM JSON file.
"""

from __future__ import annotations

import json
import logging
import math
import struct
import time
from pathlib import Path
from statistics import median

log = logging.getLogger(__name__)

DEFAULT_VOICE_PITCH_PATH = Path("/dev/shm/hapax-daimonion/operator-voice-pitch.json")
WINDOW_S = 1800.0
STALE_S = 120.0
MIN_SAMPLES = 5
MIN_INTERVAL_S = 0.5
MIN_RMS = 0.015
MIN_PITCH_HZ = 60.0
MAX_PITCH_HZ = 400.0
MIN_ELEVATION_DELTA_HZ = 25.0
MAX_STORED_SAMPLES = 3600


def publish_operator_voice_pitch_sample(
    pcm_data: bytes,
    *,
    sample_rate_hz: int = 16000,
    channels: int = 1,
    path: Path | str = DEFAULT_VOICE_PITCH_PATH,
    now: float | None = None,
    operator_speech: bool = True,
    min_interval_s: float = MIN_INTERVAL_S,
) -> bool:
    """Publish a numeric operator-voice pitch sample if the frame is voiced.

    Returns ``True`` when a fresh sample was written. ``operator_speech=False``
    is the consent/session guard used by the audio loop to avoid learning from
    non-operator speech.
    """
    if not operator_speech:
        return False
    if now is None:
        now = time.time()

    target = Path(path)
    state = _read_state(target)
    last_ts = _float_or_none(state.get("timestamp")) if state is not None else None
    if last_ts is not None and now - last_ts < min_interval_s:
        return False

    rms = _compute_rms(pcm_data, channels=channels)
    if rms < MIN_RMS:
        return False

    pitch_hz = _estimate_pitch_zcr(pcm_data, sample_rate_hz=sample_rate_hz, channels=channels)
    if pitch_hz < MIN_PITCH_HZ or pitch_hz > MAX_PITCH_HZ:
        return False

    samples = _samples_from_state(state, now=now)
    samples.append({"timestamp": now, "pitch_hz": pitch_hz})
    samples = samples[-MAX_STORED_SAMPLES:]
    stats = _stats([float(s["pitch_hz"]) for s in samples])
    threshold = _threshold(stats)

    payload: dict[str, object] = {
        "source": "operator_voice",
        "timestamp": now,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "current": {
            "pitch_hz": round(pitch_hz, 2),
            "rms": round(rms, 4),
        },
        "window_30m": stats,
        "threshold": {"elevated_hz": round(threshold, 2)},
        "samples": [
            {
                "timestamp": round(float(s["timestamp"]), 3),
                "pitch_hz": round(float(s["pitch_hz"]), 2),
            }
            for s in samples
        ],
    }
    _atomic_write_json(target, payload)
    return True


def operator_voice_pitch_is_elevated(
    *,
    path: Path | str = DEFAULT_VOICE_PITCH_PATH,
    now: float | None = None,
    stale_s: float = STALE_S,
    min_samples: int = MIN_SAMPLES,
) -> bool | None:
    """Return whether the latest operator voice pitch exceeds baseline.

    ``None`` means missing, stale, corrupt, or still warming up. Once the
    bootstrap baseline has enough samples, the accessor returns ``bool`` on
    every fresh sample.
    """
    if now is None:
        now = time.time()
    state = _read_state(Path(path))
    if state is None:
        return None

    ts = _float_or_none(state.get("timestamp"))
    if ts is None or now - ts > stale_s:
        return None

    current = state.get("current")
    if not isinstance(current, dict):
        return None
    pitch_hz = _float_or_none(current.get("pitch_hz"))
    if pitch_hz is None:
        return None

    window = state.get("window_30m")
    if not isinstance(window, dict):
        return None
    readings = int(_float_or_none(window.get("readings")) or 0)
    baseline = _float_or_none(window.get("median_hz"))
    if readings < min_samples or baseline is None:
        return None

    threshold_block = state.get("threshold")
    threshold = None
    if isinstance(threshold_block, dict):
        threshold = _float_or_none(threshold_block.get("elevated_hz"))
    if threshold is None:
        threshold = _threshold(window)
    return pitch_hz > threshold


def _read_state(path: Path) -> dict[str, object] | None:
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _samples_from_state(state: dict[str, object] | None, *, now: float) -> list[dict[str, float]]:
    if state is None:
        return []
    raw = state.get("samples")
    if not isinstance(raw, list):
        return []
    cutoff = now - WINDOW_S
    samples: list[dict[str, float]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        ts = _float_or_none(item.get("timestamp"))
        pitch = _float_or_none(item.get("pitch_hz"))
        if ts is None or pitch is None or ts < cutoff:
            continue
        samples.append({"timestamp": ts, "pitch_hz": pitch})
    return samples


def _stats(values: list[float]) -> dict[str, object]:
    if not values:
        return {
            "readings": 0,
            "mean_hz": None,
            "median_hz": None,
            "stddev_hz": None,
            "min_hz": None,
            "max_hz": None,
        }
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    stddev = math.sqrt(variance)
    return {
        "readings": len(values),
        "mean_hz": round(mean, 2),
        "median_hz": round(float(median(values)), 2),
        "stddev_hz": round(stddev, 2),
        "min_hz": round(min(values), 2),
        "max_hz": round(max(values), 2),
    }


def _threshold(stats: dict[str, object]) -> float:
    baseline = _float_or_none(stats.get("median_hz")) or 0.0
    stddev = _float_or_none(stats.get("stddev_hz")) or 0.0
    return baseline + max(MIN_ELEVATION_DELTA_HZ, stddev)


def _compute_rms(pcm_data: bytes, *, channels: int = 1) -> float:
    if len(pcm_data) < 4 or channels <= 0:
        return 0.0
    sum_sq = 0.0
    count = 0
    step = 2 * channels
    for i in range(0, len(pcm_data) - 1, step):
        sample = struct.unpack_from("<h", pcm_data, i)[0]
        sum_sq += float(sample * sample)
        count += 1
    if count == 0:
        return 0.0
    return min(1.0, math.sqrt(sum_sq / count) / 32767.0)


def _estimate_pitch_zcr(pcm_data: bytes, *, sample_rate_hz: int, channels: int) -> float:
    if len(pcm_data) < 100 or channels <= 0 or sample_rate_hz <= 0:
        return 0.0
    crossings = 0
    prev_sign = 0
    sample_count = 0
    step = 2 * channels
    for i in range(0, len(pcm_data) - 1, step):
        sample = struct.unpack_from("<h", pcm_data, i)[0]
        sign = 1 if sample >= 0 else -1
        if prev_sign != 0 and sign != prev_sign:
            crossings += 1
        prev_sign = sign
        sample_count += 1
    if sample_count == 0:
        return 0.0
    duration_s = sample_count / float(sample_rate_hz)
    if duration_s <= 0:
        return 0.0
    return crossings / (2.0 * duration_s)


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f"{path.suffix}.tmp")
        tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        log.debug("operator voice pitch state write failed", exc_info=True)


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
