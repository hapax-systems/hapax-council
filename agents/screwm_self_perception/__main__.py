"""Drift self-perception daemon — the audit-only re-perceivable surface (Chiasm Contract ``get``).

Reads the per-zone drift currency the engine consumes
(``/dev/shm/hapax-compositor/quake-drift-currency.bgra``, 256x256 BGRA8), projects it onto the 9
expressive dimensions, and atomically writes
``/dev/shm/hapax-screwm-self-perception/state.json``.

AUDIT-ONLY: this records the drift entity's realized state for observation; it does NOT yet mint a bus
``Impingement`` or feed ``select()`` — closing the chiasm is the gated loop-closure (spec PR-E), which
requires a feedback-gain measurement first. The state.json is the get surface's observable output and
the input PR-E will turn into the minted impingement (strength = clamped prediction-error vs the
expressed target).

Run: ``uv run python -m agents.screwm_self_perception``
Systemd (dormant): ``systemd/units/hapax-screwm-self-perception.service``
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

from agents.screwm_self_perception.analyzer import analyze

log = logging.getLogger(__name__)

PROBE_INTERVAL_S: float = 3.0
FIELD_SIZE: int = int(os.environ.get("HAPAX_DRIFT_FIELD_SIZE", "256"))
CURRENCY_PATH: Path = Path("/dev/shm/hapax-compositor/quake-drift-currency.bgra")
SHM_DIR: Path = Path("/dev/shm/hapax-screwm-self-perception")
SHM_FILE: Path = SHM_DIR / "state.json"
SOURCE: str = "screwm.drift.self_perception"
INTENT_FAMILY: str = "drift.self"

_shutdown = False


def _handle_signal(signum: int, _frame: object) -> None:
    global _shutdown
    _shutdown = True
    log.info("Received signal %d, shutting down", signum)


def _read_currency() -> np.ndarray | None:
    """Read the currency BGRA, or None if absent / wrong size (daemon not yet deployed/live)."""
    try:
        raw = CURRENCY_PATH.read_bytes()
    except FileNotFoundError:
        return None
    expected = FIELD_SIZE * FIELD_SIZE * 4
    if len(raw) != expected:
        return None
    return np.frombuffer(raw, dtype=np.uint8).reshape(FIELD_SIZE, FIELD_SIZE, 4)


def _write_state(payload: dict) -> None:
    SHM_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SHM_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.rename(SHM_FILE)


def _probe_once() -> None:
    bgra = _read_currency()
    if bgra is None:
        _write_state(
            {
                "timestamp": time.time(),
                "source": SOURCE,
                "intent_family": INTENT_FAMILY,
                "error": "currency-absent",
                "provenance": {"readback_source": str(CURRENCY_PATH), "mtime": None},
            }
        )
        log.debug("currency absent at %s (daemon not yet live)", CURRENCY_PATH)
        return

    perception = analyze(bgra)
    try:
        mtime = CURRENCY_PATH.stat().st_mtime
    except OSError:
        mtime = None
    _write_state(
        {
            **perception.to_dict(),
            "timestamp": time.time(),
            "source": SOURCE,
            "intent_family": INTENT_FAMILY,
            "provenance": {"readback_source": str(CURRENCY_PATH), "mtime": mtime},
        }
    )
    d = perception.dims
    log.debug(
        "drift get: intensity=%.3f tension=%.3f coherence=%.3f depth=%.3f diffusion=%.3f",
        d["intensity"],
        d["tension"],
        d["coherence"],
        d["depth"],
        d["diffusion"],
    )


def main() -> None:
    logging.basicConfig(
        level=logging.DEBUG if "--debug" in sys.argv else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    log.info(
        "Drift self-perception daemon starting (audit-only; currency=%s, interval=%.1fs)",
        CURRENCY_PATH,
        PROBE_INTERVAL_S,
    )

    while not _shutdown:
        t0 = time.monotonic()
        try:
            _probe_once()
        except Exception:
            log.exception("Probe cycle failed")
        sleep_s = max(0.1, PROBE_INTERVAL_S - (time.monotonic() - t0))
        time.sleep(sleep_s)

    log.info("Drift self-perception daemon stopped")


if __name__ == "__main__":
    main()
