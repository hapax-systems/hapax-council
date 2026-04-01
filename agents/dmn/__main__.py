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

from agents._impingement import Impingement
from agents.dmn.buffer import DMNBuffer
from agents.dmn.pulse import DMNPulse

log = logging.getLogger("dmn")

# Output paths
DMN_STATE_DIR = Path("/dev/shm/hapax-dmn")
BUFFER_FILE = DMN_STATE_DIR / "buffer.txt"
STATUS_FILE = DMN_STATE_DIR / "status.json"
IMPINGEMENTS_FILE = DMN_STATE_DIR / "impingements.jsonl"

# Main loop tick rate (fastest possible — individual ticks have their own cadence)
LOOP_TICK_S = 1.0


class DMNDaemon:
    """Always-on DMN daemon."""

    def __init__(self) -> None:
        self._buffer = DMNBuffer()
        self._pulse = DMNPulse(self._buffer)
        self._running = True
        self._start_time = time.monotonic()
        self._feedback_cursor: int = 0  # byte offset into impingements.jsonl

    async def run(self) -> None:
        """Main loop — never stops unless signalled."""
        DMN_STATE_DIR.mkdir(parents=True, exist_ok=True)
        log.info("DMN daemon starting")

        while self._running:
            try:
                await self._pulse.tick()
                self._write_output()
                self._consume_fortress_feedback()
            except Exception:
                log.exception("DMN tick failed")

            await asyncio.sleep(LOOP_TICK_S)

        log.info("DMN daemon stopped")

    def _write_output(self) -> None:
        """Write buffer, impingements, and status to /dev/shm."""
        # Buffer formatted for U-curve
        buffer_text = self._buffer.format_for_tpn()
        try:
            tmp = BUFFER_FILE.with_suffix(".tmp")
            tmp.write_text(buffer_text, encoding="utf-8")
            tmp.rename(BUFFER_FILE)
        except OSError:
            log.warning("Failed to write buffer to %s", BUFFER_FILE, exc_info=True)

        # Drain and persist impingements (cross-daemon transport)
        impingements = self._pulse.drain_impingements()
        if impingements:
            try:
                with IMPINGEMENTS_FILE.open("a", encoding="utf-8") as f:
                    for imp in impingements:
                        f.write(imp.model_dump_json() + "\n")
                log.info("Emitted %d impingements to JSONL", len(impingements))
            except OSError:
                log.warning("Failed to write impingements to %s", IMPINGEMENTS_FILE, exc_info=True)

        # Publish sensor snapshot for imagination daemon
        try:
            from agents.dmn.sensor import publish_snapshot, read_all

            snapshot = read_all()
            publish_snapshot(snapshot)
        except Exception:
            log.warning("Failed to publish sensor snapshot", exc_info=True)

        # Publish observations for imagination daemon
        try:
            self._buffer.publish_observations(5)
        except Exception:
            log.warning("Failed to publish observations", exc_info=True)

        # Status for monitoring
        status = {
            "running": True,
            "uptime_s": round(time.monotonic() - self._start_time, 1),
            "buffer_entries": len(self._buffer),
            "tick": self._buffer.tick,
            "timestamp": time.time(),
        }
        try:
            tmp = STATUS_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(status), encoding="utf-8")
            tmp.rename(STATUS_FILE)
        except OSError:
            log.warning("Failed to write status to %s", STATUS_FILE, exc_info=True)

    def _consume_fortress_feedback(self) -> None:
        """Read fortress feedback impingements from JSONL and suppress re-emission."""
        if not IMPINGEMENTS_FILE.exists():
            return
        try:
            size = IMPINGEMENTS_FILE.stat().st_size
            if size <= self._feedback_cursor:
                return
            with IMPINGEMENTS_FILE.open("r", encoding="utf-8") as f:
                f.seek(self._feedback_cursor)
                feedback = []
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        imp = Impingement.model_validate_json(line)
                        if imp.source == "fortress.action_taken":
                            feedback.append(imp)
                    except Exception:
                        continue
                self._feedback_cursor = f.tell()
            if feedback:
                self._pulse.consume_fortress_feedback(feedback)
                log.debug("Consumed %d fortress feedback impingements", len(feedback))
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
