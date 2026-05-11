"""Unified audio perception daemon.

Captures from the PipeWire broadcast chain, runs three CPU-only analysis
stages in sequence, and writes structured JSON to
/dev/shm/hapax-perception/audio.json at ~0.2 Hz (one 5s capture window
per tick).

Stages:
  1. CLAP zero-shot scene classification (speech/music/silence/typing/ambient)
  2. pyannote VAD for speech detection + activity ratio
  3. librosa BPM + key estimation (only when music detected)

Run: ``uv run python -m agents.audio_perception``
Systemd: ``systemd/units/hapax-audio-perception.service``
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from pathlib import Path

import numpy as np

from agents.audio_health.probes import (
    ProbeConfig,
    ProbeError,
    _capture_parecord,
    _decode_s16le_to_mono,
)
from shared.clap import CLAP_SAMPLE_RATE, classify_zero_shot

log = logging.getLogger(__name__)

PROBE_INTERVAL_S: float = 5.0
CAPTURE_DURATION_S: float = 5.0
DEFAULT_SOURCE: str = "hapax-broadcast-normalized"
SOURCE: str = os.environ.get("HAPAX_AUDIO_PERCEPTION_SOURCE", DEFAULT_SOURCE)
SHM_DIR: Path = Path("/dev/shm/hapax-perception")
SHM_FILE: Path = SHM_DIR / "audio.json"

SCENE_LABELS: list[str] = [
    "silence",
    "speech or conversation",
    "keyboard typing on a mechanical keyboard",
    "ambient room noise",
    "rock music",
    "electronic music",
    "jazz music",
    "classical music",
    "hip hop music",
    "pop music",
    "folk or acoustic music",
    "metal music",
    "ambient or drone music",
]

GENRE_LABELS: set[str] = {
    "rock music",
    "electronic music",
    "jazz music",
    "classical music",
    "hip hop music",
    "pop music",
    "folk or acoustic music",
    "metal music",
    "ambient or drone music",
}

CONFIDENCE_THRESHOLD: float = 0.15

_shutdown = False
_vad_pipeline = None
_vad_load_attempted = False


def _handle_signal(signum: int, _frame: object) -> None:
    global _shutdown
    _shutdown = True
    log.info("Received signal %d, shutting down", signum)


def _get_vad_pipeline():
    """Lazy-load pyannote VAD pipeline (CPU-only)."""
    global _vad_pipeline, _vad_load_attempted
    if _vad_load_attempted:
        return _vad_pipeline
    _vad_load_attempted = True
    try:
        import torch
        from pyannote.audio.pipelines import VoiceActivityDetection

        vad = VoiceActivityDetection(segmentation="pyannote/segmentation-3.0")
        vad.instantiate(
            {
                "onset": 0.5,
                "offset": 0.3,
                "min_duration_on": 0.2,
                "min_duration_off": 0.1,
            }
        )
        if hasattr(vad, "_segmentation") and hasattr(vad._segmentation, "model"):
            vad._segmentation.model = vad._segmentation.model.to(torch.device("cpu"))
        _vad_pipeline = vad
        log.info("pyannote VAD pipeline loaded (CPU)")
    except Exception:
        log.warning("pyannote VAD unavailable; is_speech will use CLAP fallback", exc_info=True)
    return _vad_pipeline


def _classify_scene(probs: dict[str, float]) -> dict:
    top_label = max(probs, key=probs.get)  # type: ignore[arg-type]
    top_score = probs[top_label]

    if top_label == "silence":
        scene = "silence"
    elif top_label == "speech or conversation":
        scene = "speech"
    elif top_label == "keyboard typing on a mechanical keyboard":
        scene = "typing"
    elif top_label == "ambient room noise":
        scene = "ambient"
    elif top_label in GENRE_LABELS:
        scene = "music"
    else:
        scene = "unknown"

    genre = top_label if top_label in GENRE_LABELS else None
    music_score = sum(probs.get(g, 0.0) for g in GENRE_LABELS)

    return {
        "scene": scene,
        "scene_label": top_label,
        "confidence": round(top_score, 4),
        "genre": genre,
        "music_score": round(music_score, 4),
        "music_playing": music_score > 0.3,
    }


def _detect_speech(waveform: np.ndarray, sr: int) -> dict:
    """Run pyannote VAD on waveform, return speech metrics."""
    vad = _get_vad_pipeline()
    if vad is None:
        return {"is_speech": None, "speech_ratio": None, "vad_available": False}

    try:
        import torch
        import torchaudio

        tensor = torch.from_numpy(waveform).unsqueeze(0).float()
        if sr != 16000:
            tensor = torchaudio.functional.resample(tensor, sr, 16000)

        annotation = vad({"waveform": tensor, "sample_rate": 16000})
        total_speech = sum(seg.duration for seg in annotation.itersegments())
        duration = waveform.shape[0] / sr
        speech_ratio = total_speech / duration if duration > 0 else 0.0

        return {
            "is_speech": speech_ratio > 0.1,
            "speech_ratio": round(speech_ratio, 3),
            "vad_available": True,
        }
    except Exception:
        log.debug("VAD inference failed", exc_info=True)
        return {"is_speech": None, "speech_ratio": None, "vad_available": False}


def _analyze_music(waveform: np.ndarray, sr: int) -> dict:
    """Estimate BPM and key using librosa (CPU-only)."""
    try:
        import librosa

        if sr != 22050:
            waveform_resampled = librosa.resample(waveform, orig_sr=sr, target_sr=22050)
        else:
            waveform_resampled = waveform

        tempo_arr = librosa.beat.beat_track(y=waveform_resampled, sr=22050)[0]
        bpm = int(round(float(np.atleast_1d(tempo_arr)[0])))

        chroma = librosa.feature.chroma_cqt(y=waveform_resampled, sr=22050)
        key_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        key_idx = int(np.argmax(np.mean(chroma, axis=1)))
        key = key_names[key_idx]

        return {"bpm": bpm, "key": key}
    except Exception:
        log.debug("Music analysis failed", exc_info=True)
        return {"bpm": None, "key": None}


def _write_state(payload: dict, error: str | None = None) -> None:
    SHM_DIR.mkdir(parents=True, exist_ok=True)
    payload["timestamp"] = time.time()
    payload["source"] = SOURCE
    if error:
        payload["error"] = error
    tmp = SHM_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.rename(SHM_FILE)


def _tick() -> None:
    config = ProbeConfig(
        duration_s=CAPTURE_DURATION_S,
        sample_rate=CLAP_SAMPLE_RATE,
        channels=2,
    )
    try:
        raw = _capture_parecord(SOURCE, config)
    except ProbeError as exc:
        log.debug("Capture failed: %s", exc)
        _write_state(
            {"scene": "error", "is_speech": None, "music_playing": False},
            error=str(exc),
        )
        return

    samples_s16 = _decode_s16le_to_mono(raw, config.channels)
    waveform = samples_s16.astype(np.float32) / 32768.0

    clap_probs = classify_zero_shot(waveform, SCENE_LABELS, sr=CLAP_SAMPLE_RATE)
    scene = _classify_scene(clap_probs)

    speech = _detect_speech(waveform, CLAP_SAMPLE_RATE)
    if speech["is_speech"] is None and scene["scene"] == "speech":
        speech["is_speech"] = True

    music_analysis: dict = {"bpm": None, "key": None}
    if scene["music_playing"]:
        music_analysis = _analyze_music(waveform, CLAP_SAMPLE_RATE)

    payload = {
        "is_speech": speech.get("is_speech", False),
        "speech_ratio": speech.get("speech_ratio"),
        "speaker_id": None,
        "music_playing": scene["music_playing"],
        "bpm": music_analysis["bpm"],
        "key": music_analysis["key"],
        "scene": scene["scene"],
        "scene_label": scene["scene_label"],
        "confidence": scene["confidence"],
        "genre": scene["genre"],
        "music_score": scene["music_score"],
        "vad_available": speech.get("vad_available", False),
    }

    _write_state(payload)
    log.debug(
        "scene=%s is_speech=%s music=%s bpm=%s key=%s conf=%.2f",
        payload["scene"],
        payload["is_speech"],
        payload["music_playing"],
        payload["bpm"],
        payload["key"],
        payload["confidence"],
    )


def main() -> None:
    logging.basicConfig(
        level=logging.DEBUG if "--debug" in sys.argv else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    log.info(
        "Audio perception daemon starting (source=%s, interval=%.1fs)",
        SOURCE,
        PROBE_INTERVAL_S,
    )

    while not _shutdown:
        t0 = time.monotonic()
        try:
            _tick()
        except Exception:
            log.exception("Perception tick failed")
        elapsed = time.monotonic() - t0
        sleep_s = max(0.1, PROBE_INTERVAL_S - elapsed)
        time.sleep(sleep_s)

    log.info("Audio perception daemon stopped")


if __name__ == "__main__":
    main()
