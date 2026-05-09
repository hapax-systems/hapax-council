"""Audio self-perception daemon — AVSDLC-002.

Captures from broadcast-master at 5s cadence via parecord, computes
spectral features, writes to /dev/shm/hapax-audio-self-perception/state.json
for VLA to inject into stimmung.

Run: ``uv run python -m agents.audio_self_perception``
Systemd: ``systemd/units/hapax-audio-self-perception.service``
"""

from __future__ import annotations

import json
import logging
import signal
import sys
import time
from pathlib import Path

from agents.audio_health.probes import (
    ProbeConfig,
    ProbeError,
    _capture_parecord,
    _decode_s16le_to_mono,
)
from agents.audio_self_perception.analyzer import analyze

log = logging.getLogger(__name__)

PROBE_INTERVAL_S: float = 5.0
CAPTURE_DURATION_S: float = 2.0
TARGET_STAGE: str = "hapax-broadcast-master"
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
    }
    if error:
        payload["error"] = error
    tmp = SHM_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.rename(SHM_FILE)


def _probe_once() -> None:
    config = ProbeConfig(
        duration_s=CAPTURE_DURATION_S,
        sample_rate=48000,
        channels=2,
    )
    try:
        raw = _capture_parecord(TARGET_STAGE, config)
    except ProbeError as exc:
        log.debug("Capture failed: %s", exc)
        _write_state({}, error=str(exc))
        return

    samples = _decode_s16le_to_mono(raw, config.channels)
    perception = analyze(samples, sample_rate=config.sample_rate)
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
        "Audio self-perception daemon starting (stage=%s, interval=%.1fs)",
        TARGET_STAGE,
        PROBE_INTERVAL_S,
    )

    while not _shutdown:
        t0 = time.monotonic()
        try:
            _probe_once()
        except Exception:
            log.exception("Probe cycle failed")
        elapsed = time.monotonic() - t0
        sleep_s = max(0.1, PROBE_INTERVAL_S - elapsed)
        time.sleep(sleep_s)

    log.info("Audio self-perception daemon stopped")


if __name__ == "__main__":
    main()
