"""Audio self-perception daemon — AVSDLC-002.

Captures persistently from the normalized broadcast egress via parecord,
computes spectral features, and writes
``/dev/shm/hapax-audio-self-perception/state.json`` for VLA to inject into
stimmung.

Run: ``uv run python -m agents.audio_self_perception``
Systemd: ``systemd/units/hapax-audio-self-perception.service``
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from pathlib import Path

from agents.audio_health.probes import (
    PersistentProbeSet,
    ProbeConfig,
)
from agents.audio_self_perception.analyzer import analyze

log = logging.getLogger(__name__)

PROBE_INTERVAL_S: float = 5.0
CAPTURE_DURATION_S: float = 2.0
DEFAULT_SAMPLE_RATE: int = 48000
DEFAULT_TARGET_STAGE: str = "hapax-broadcast-normalized"
TARGET_STAGE: str = os.environ.get("HAPAX_AUDIO_SELF_PERCEPTION_STAGE", DEFAULT_TARGET_STAGE)
SHM_DIR: Path = Path("/dev/shm/hapax-audio-self-perception")
SHM_FILE: Path = SHM_DIR / "state.json"

_shutdown = False


def _handle_signal(signum: int, _frame: object) -> None:
    global _shutdown
    _shutdown = True
    log.info("Received signal %d, shutting down", signum)


def _write_state(perception: dict, error: str | None = None) -> None:
    SHM_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        **perception,
        "timestamp": time.time(),
        "stage": TARGET_STAGE,
        "source": TARGET_STAGE,
    }
    if error:
        payload["error"] = error
    tmp = SHM_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.rename(SHM_FILE)


def _probe_once(probes: PersistentProbeSet) -> None:
    result = probes.capture(TARGET_STAGE)
    if result.error:
        log.debug("Capture failed: %s", result.error)
        _write_state({}, error=result.error)
        return

    perception = analyze(result.samples_mono, sample_rate=result.sample_rate)
    _write_state(perception.to_dict())
    log.debug(
        "rms=%.1f centroid=%.0f bal=%.2f v/m/e=%.2f/%.2f/%.2f",
        perception.rms_dbfs,
        perception.spectral_centroid_hz,
        perception.low_high_ratio,
        perception.voice_ratio,
        perception.music_ratio,
        perception.env_ratio,
    )


def main() -> None:
    logging.basicConfig(
        level=logging.DEBUG if "--debug" in sys.argv else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    log.info(
        "Audio self-perception daemon starting (stage=%s, interval=%.1fs, rate=%d)",
        TARGET_STAGE,
        PROBE_INTERVAL_S,
        DEFAULT_SAMPLE_RATE,
    )

    config = ProbeConfig(
        duration_s=CAPTURE_DURATION_S,
        sample_rate=DEFAULT_SAMPLE_RATE,
        channels=2,
    )
    with PersistentProbeSet(config=config) as probes:
        while not _shutdown:
            t0 = time.monotonic()
            try:
                _probe_once(probes)
            except Exception:
                log.exception("Probe cycle failed")
            elapsed = time.monotonic() - t0
            sleep_s = max(0.1, PROBE_INTERVAL_S - elapsed)
            time.sleep(sleep_s)

    log.info("Audio self-perception daemon stopped")


if __name__ == "__main__":
    main()
