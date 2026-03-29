"""DMN daemon — continuous cognitive substrate for Hapax.

Runs a multi-rate pulse loop that reads sensor data, produces structured
micro-assessments via a local LLM (Ollama), and accumulates them in a
buffer formatted for consumption by on-demand TPN (deliberative) models.

Usage:
    uv run python -m agents.dmn

The buffer is written to /dev/shm/hapax-dmn/buffer.txt for consumption
by the voice daemon, fortress governor, and other TPN consumers.
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import time
from pathlib import Path

from agents.dmn.buffer import DMNBuffer
from agents.dmn.pulse import DMNPulse
from agents.imagination import CURRENT_PATH, ImaginationFragment, ImaginationLoop
from agents.imagination_resolver import CONTENT_DIR, cleanup_content_dir, resolve_references

log = logging.getLogger("dmn")

# Output paths
DMN_STATE_DIR = Path("/dev/shm/hapax-dmn")
BUFFER_FILE = DMN_STATE_DIR / "buffer.txt"
STATUS_FILE = DMN_STATE_DIR / "status.json"
IMPINGEMENTS_FILE = DMN_STATE_DIR / "impingements.jsonl"
TPN_ACTIVE_FILE = DMN_STATE_DIR / "tpn_active"

# Main loop tick rate (fastest possible — individual ticks have their own cadence)
LOOP_TICK_S = 1.0


class DMNDaemon:
    """Always-on DMN daemon."""

    def __init__(self) -> None:
        self._buffer = DMNBuffer()
        self._pulse = DMNPulse(self._buffer)
        self._imagination = ImaginationLoop()
        self._running = True
        self._start_time = time.monotonic()

    async def run(self) -> None:
        """Main loop — never stops unless signalled."""
        DMN_STATE_DIR.mkdir(parents=True, exist_ok=True)
        log.info("DMN daemon starting")

        asyncio.create_task(self._imagination_loop())
        asyncio.create_task(self._resolver_loop())

        while self._running:
            try:
                await self._pulse.tick()
                self._write_output()
            except Exception:
                log.exception("DMN tick failed")

            await asyncio.sleep(LOOP_TICK_S)

        log.info("DMN daemon stopped")

    async def _imagination_loop(self) -> None:
        """Run imagination loop on its own variable cadence."""
        from agents.dmn.sensor import read_all

        log.info("Imagination loop starting")
        while self._running:
            try:
                try:
                    if TPN_ACTIVE_FILE.exists():
                        active = TPN_ACTIVE_FILE.read_text().strip() == "1"
                        self._imagination.set_tpn_active(active)
                except OSError:
                    pass

                observations = self._buffer.recent_observations(5)
                snapshot = read_all()
                await self._imagination.tick(observations, snapshot)
            except Exception:
                log.warning("Imagination tick failed", exc_info=True)

            interval = self._imagination.cadence.current_interval()
            await asyncio.sleep(interval)

    async def _resolver_loop(self) -> None:
        """Watch imagination fragments and resolve slow content references."""
        log.info("Content resolver starting")
        last_fragment_id = ""
        CONTENT_DIR.mkdir(parents=True, exist_ok=True)

        while self._running:
            try:
                if CURRENT_PATH.exists():
                    data = json.loads(CURRENT_PATH.read_text())
                    frag_id = data.get("id", "")
                    if frag_id and frag_id != last_fragment_id:
                        last_fragment_id = frag_id
                        frag = ImaginationFragment.model_validate(data)
                        cleanup_content_dir()
                        resolve_references(frag)
                        log.debug("Resolved content for fragment %s", frag_id)
            except Exception:
                log.warning("Resolver tick failed", exc_info=True)

            await asyncio.sleep(0.5)

    def _write_output(self) -> None:
        """Write buffer, impingements, and status to /dev/shm."""
        # Buffer formatted for U-curve
        buffer_text = self._buffer.format_for_tpn()
        try:
            tmp = BUFFER_FILE.with_suffix(".tmp")
            tmp.write_text(buffer_text, encoding="utf-8")
            tmp.rename(BUFFER_FILE)
        except OSError:
            pass

        # Drain and persist impingements (cross-daemon transport)
        impingements = self._pulse.drain_impingements()
        impingements.extend(self._imagination.drain_impingements())
        if impingements:
            try:
                with IMPINGEMENTS_FILE.open("a", encoding="utf-8") as f:
                    for imp in impingements:
                        f.write(imp.model_dump_json() + "\n")
                log.info("Emitted %d impingements to JSONL", len(impingements))
            except OSError:
                pass

        # Read TPN active flag (anti-correlation signal from voice daemon)
        try:
            if TPN_ACTIVE_FILE.exists():
                active = TPN_ACTIVE_FILE.read_text().strip() == "1"
                self._pulse.set_tpn_active(active)
        except OSError:
            pass

        # Status for monitoring
        status = {
            "running": True,
            "uptime_s": round(time.monotonic() - self._start_time, 1),
            "buffer_entries": len(self._buffer),
            "tick": self._buffer.tick,
            "imagination_active": self._imagination.activation_level > 0,
            "timestamp": time.time(),
        }
        try:
            tmp = STATUS_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(status), encoding="utf-8")
            tmp.rename(STATUS_FILE)
        except OSError:
            pass

    def stop(self) -> None:
        self._running = False


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    daemon = DMNDaemon()

    def handle_signal(sig: int, frame: object) -> None:
        log.info("Signal %d received, stopping", sig)
        daemon.stop()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    await daemon.run()


if __name__ == "__main__":
    asyncio.run(main())
