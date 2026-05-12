"""agents/audio_perception/daemon.py — CPU-only audio perception daemon.

Captures from broadcast egress via parecord, computes speech/music
classification, and writes structured JSON to /dev/shm for segment prep
and other perception consumers.

Zero VRAM: all inference runs on CPU (spectral band analysis + autocorrelation).
"""

from __future__ import annotations

import json
import logging
import math
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

OUTPUT_DIR = Path("/dev/shm/hapax-perception")
OUTPUT_FILE = OUTPUT_DIR / "audio.json"

CAPTURE_DURATION_S = 2.0
SAMPLE_RATE = 48000
TICK_INTERVAL_S = 1.0

VOICE_LOW_HZ = 85.0
VOICE_HIGH_HZ = 3000.0
MUSIC_LOW_HZ = 40.0
MUSIC_HIGH_HZ = 8000.0
SPEECH_VOICE_RATIO_THRESHOLD = 0.45
MUSIC_RATIO_THRESHOLD = 0.25
SILENCE_DBFS = -50.0


@dataclass(frozen=True)
class AudioPerceptionState:
    is_speech: bool
    speaker_id: str | None
    music_playing: bool
    bpm: int | None
    key: str | None
    scene: str
    confidence: float
    rms_dbfs: float
    voice_ratio: float
    music_ratio: float
    updated_at: str


def _capture_audio(duration_s: float = CAPTURE_DURATION_S) -> np.ndarray | None:
    target_bytes = int(SAMPLE_RATE * duration_s * 2)
    try:
        proc = subprocess.Popen(
            [
                "parecord",
                "--raw",
                "--format=s16le",
                f"--rate={SAMPLE_RATE}",
                "--channels=1",
                f"--latency-msec={int(duration_s * 1000)}",
                "--device=hapax-broadcast-normalized",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (FileNotFoundError, OSError) as exc:
        log.warning("parecord spawn failed: %s", exc)
        return None

    captured = bytearray()
    deadline = time.monotonic() + duration_s
    try:
        while time.monotonic() < deadline and len(captured) < target_bytes:
            chunk = proc.stdout.read(min(4096, target_bytes - len(captured)))
            if not chunk:
                break
            captured.extend(chunk)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    if len(captured) < 64:
        return None
    n = len(captured) - (len(captured) % 2)
    return np.frombuffer(bytes(captured[:n]), dtype=np.int16)


def _compute_features(samples: np.ndarray) -> dict:
    floats = samples.astype(np.float64) / 32768.0
    rms = float(np.sqrt(np.mean(np.square(floats))))
    rms_dbfs = max(-120.0, 20.0 * math.log10(rms)) if rms > 0 else -120.0

    spectrum = np.abs(np.fft.rfft(floats)) ** 2
    if spectrum.size > 2:
        spectrum = spectrum[1:-1]
    n_bins = spectrum.size
    if n_bins == 0:
        return {"rms_dbfs": rms_dbfs, "voice_ratio": 0.0, "music_ratio": 0.0, "env_ratio": 0.0}

    freqs = np.linspace(0, SAMPLE_RATE / 2.0, n_bins + 2)[1:-1]
    total_energy = float(np.sum(spectrum))
    if total_energy < 1e-20:
        return {"rms_dbfs": rms_dbfs, "voice_ratio": 0.0, "music_ratio": 0.0, "env_ratio": 0.0}

    voice_mask = (freqs >= VOICE_LOW_HZ) & (freqs <= VOICE_HIGH_HZ)
    music_mask = ((freqs >= MUSIC_LOW_HZ) & (freqs < VOICE_LOW_HZ)) | (
        (freqs > VOICE_HIGH_HZ) & (freqs <= MUSIC_HIGH_HZ)
    )
    env_mask = ~voice_mask & ~music_mask

    voice_e = float(np.sum(spectrum[voice_mask])) if np.any(voice_mask) else 0.0
    music_e = float(np.sum(spectrum[music_mask])) if np.any(music_mask) else 0.0
    env_e = float(np.sum(spectrum[env_mask])) if np.any(env_mask) else 0.0
    band_total = voice_e + music_e + env_e

    if band_total > 0:
        voice_ratio = voice_e / band_total
        music_ratio = music_e / band_total
        env_ratio = env_e / band_total
    else:
        voice_ratio = music_ratio = env_ratio = 0.0

    return {
        "rms_dbfs": rms_dbfs,
        "voice_ratio": voice_ratio,
        "music_ratio": music_ratio,
        "env_ratio": env_ratio,
    }


def _estimate_bpm(samples: np.ndarray) -> int | None:
    if len(samples) < SAMPLE_RATE:
        return None
    floats = np.abs(samples.astype(np.float64) / 32768.0)
    hop = SAMPLE_RATE // 20
    envelope = np.array([np.mean(floats[i : i + hop]) for i in range(0, len(floats) - hop, hop)])
    if len(envelope) < 10:
        return None
    envelope = envelope - np.mean(envelope)
    corr = np.correlate(envelope, envelope, mode="full")
    corr = corr[len(corr) // 2 :]
    if len(corr) < 4:
        return None
    min_lag = 3
    max_lag = min(len(corr) - 1, 40)
    if min_lag >= max_lag:
        return None
    peak_lag = int(np.argmax(corr[min_lag:max_lag])) + min_lag
    if peak_lag <= 0:
        return None
    fps = 20.0
    bpm = int(round(60.0 * fps / peak_lag))
    if 40 <= bpm <= 240:
        return bpm
    return None


def _classify_scene(features: dict) -> tuple[str, float]:
    rms = features["rms_dbfs"]
    voice_r = features["voice_ratio"]
    music_r = features["music_ratio"]

    if rms < SILENCE_DBFS:
        return "silence", 0.95
    if voice_r > SPEECH_VOICE_RATIO_THRESHOLD and voice_r > music_r:
        return "speech", min(0.95, voice_r)
    if music_r > MUSIC_RATIO_THRESHOLD and music_r > voice_r:
        return "music", min(0.95, music_r)
    if voice_r > 0.3 and music_r > 0.15:
        return "speech_over_music", min(0.9, (voice_r + music_r) / 2)
    return "ambient", 0.5


def perceive_once() -> AudioPerceptionState:
    samples = _capture_audio()
    if samples is None or len(samples) < 64:
        return AudioPerceptionState(
            is_speech=False,
            speaker_id=None,
            music_playing=False,
            bpm=None,
            key=None,
            scene="capture_failed",
            confidence=0.0,
            rms_dbfs=-120.0,
            voice_ratio=0.0,
            music_ratio=0.0,
            updated_at=datetime.now(UTC).isoformat(),
        )

    features = _compute_features(samples)
    scene, confidence = _classify_scene(features)
    bpm = _estimate_bpm(samples) if features["music_ratio"] > 0.15 else None
    is_speech = scene in ("speech", "speech_over_music")
    music_playing = scene in ("music", "speech_over_music")

    return AudioPerceptionState(
        is_speech=is_speech,
        speaker_id=None,
        music_playing=music_playing,
        bpm=bpm,
        key=None,
        scene=scene,
        confidence=round(confidence, 3),
        rms_dbfs=round(features["rms_dbfs"], 2),
        voice_ratio=round(features["voice_ratio"], 4),
        music_ratio=round(features["music_ratio"], 4),
        updated_at=datetime.now(UTC).isoformat(),
    )


def write_state(state: AudioPerceptionState) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = OUTPUT_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(state), indent=2) + "\n")
    tmp.rename(OUTPUT_FILE)


def run_forever(tick_s: float = TICK_INTERVAL_S) -> None:
    log.info("audio-perception daemon starting (tick=%.1fs)", tick_s)
    while True:
        try:
            state = perceive_once()
            write_state(state)
            if state.scene != "capture_failed":
                log.debug(
                    "scene=%s speech=%s music=%s bpm=%s rms=%.1f",
                    state.scene,
                    state.is_speech,
                    state.music_playing,
                    state.bpm,
                    state.rms_dbfs,
                )
        except Exception:
            log.exception("perception tick failed")
        time.sleep(tick_s)
