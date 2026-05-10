"""CLAP continuous audio grounding daemon.

Captures from the PipeWire broadcast chain every 5s via parecord,
classifies the audio scene using CLAP zero-shot classification, and
writes structured JSON to /dev/shm/hapax-audio-grounding/state.json.

Runs CPU-only (CUDA_VISIBLE_DEVICES='') to avoid contending with
TabbyAPI for GPU VRAM.

Run: ``uv run python -m agents.audio_grounding``
Systemd: ``systemd/units/hapax-audio-grounding.service``
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
SOURCE: str = os.environ.get("HAPAX_AUDIO_GROUNDING_SOURCE", DEFAULT_SOURCE)
SHM_DIR: Path = Path("/dev/shm/hapax-audio-grounding")
SHM_FILE: Path = SHM_DIR / "state.json"

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


def _handle_signal(signum: int, _frame: object) -> None:
    global _shutdown
    _shutdown = True
    log.info("Received signal %d, shutting down", signum)


def _classify_scene(probs: dict[str, float]) -> dict:
    top_label = max(probs, key=probs.get)  # type: ignore[arg-type]
    top_score = probs[top_label]

    if top_label == "silence":
        scene_category = "silence"
    elif top_label == "speech or conversation":
        scene_category = "speech"
    elif top_label == "keyboard typing on a mechanical keyboard":
        scene_category = "typing"
    elif top_label == "ambient room noise":
        scene_category = "ambient"
    elif top_label in GENRE_LABELS:
        scene_category = "music"
    else:
        scene_category = "unknown"

    genre = top_label if top_label in GENRE_LABELS else None

    music_score = sum(probs.get(g, 0.0) for g in GENRE_LABELS)

    above_threshold = {
        label: round(score, 4)
        for label, score in sorted(probs.items(), key=lambda x: x[1], reverse=True)
        if score >= CONFIDENCE_THRESHOLD
    }

    return {
        "scene": scene_category,
        "scene_label": top_label,
        "scene_confidence": round(top_score, 4),
        "genre": genre,
        "music_score": round(music_score, 4),
        "labels_above_threshold": above_threshold,
    }


def _write_state(classification: dict, error: str | None = None) -> None:
    SHM_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        **classification,
        "timestamp": time.time(),
        "source": SOURCE,
        "capture_duration_s": CAPTURE_DURATION_S,
    }
    if error:
        payload["error"] = error
    tmp = SHM_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.rename(SHM_FILE)


def _capture_and_classify() -> None:
    config = ProbeConfig(
        duration_s=CAPTURE_DURATION_S,
        sample_rate=CLAP_SAMPLE_RATE,
        channels=2,
    )
    try:
        raw = _capture_parecord(SOURCE, config)
    except ProbeError as exc:
        log.debug("Capture failed: %s", exc)
        _write_state({}, error=str(exc))
        return

    samples_s16 = _decode_s16le_to_mono(raw, config.channels)
    waveform = samples_s16.astype(np.float32) / 32768.0

    probs = classify_zero_shot(waveform, SCENE_LABELS, sr=CLAP_SAMPLE_RATE)
    classification = _classify_scene(probs)
    _write_state(classification)
    log.debug(
        "scene=%s conf=%.2f genre=%s music=%.2f",
        classification["scene"],
        classification["scene_confidence"],
        classification.get("genre"),
        classification["music_score"],
    )


def main() -> None:
    logging.basicConfig(
        level=logging.DEBUG if "--debug" in sys.argv else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    log.info(
        "Audio grounding daemon starting (source=%s, interval=%.1fs, labels=%d)",
        SOURCE,
        PROBE_INTERVAL_S,
        len(SCENE_LABELS),
    )

    while not _shutdown:
        t0 = time.monotonic()
        try:
            _capture_and_classify()
        except Exception:
            log.exception("Grounding cycle failed")
        elapsed = time.monotonic() - t0
        sleep_s = max(0.1, PROBE_INTERVAL_S - elapsed)
        time.sleep(sleep_s)

    log.info("Audio grounding daemon stopped")


if __name__ == "__main__":
    main()
