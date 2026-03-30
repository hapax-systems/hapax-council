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
from agents.imagination_resolver import CONTENT_DIR, resolve_references_staged

log = logging.getLogger("dmn")

# Output paths
DMN_STATE_DIR = Path("/dev/shm/hapax-dmn")
BUFFER_FILE = DMN_STATE_DIR / "buffer.txt"
STATUS_FILE = DMN_STATE_DIR / "status.json"
IMPINGEMENTS_FILE = DMN_STATE_DIR / "impingements.jsonl"
TPN_ACTIVE_FILE = DMN_STATE_DIR / "tpn_active"

MATERIAL_MAP = {"water": 0, "fire": 1, "earth": 2, "air": 3, "void": 4}
UNIFORMS_FILE = Path("/dev/shm/hapax-imagination/pipeline/uniforms.json")

# Main loop tick rate (fastest possible — individual ticks have their own cadence)
LOOP_TICK_S = 1.0


def write_imagination_uniforms(
    imagination_path: Path | None = None,
    uniforms_path: Path | None = None,
) -> None:
    """Write imagination state to uniforms.json for the Rust visual pipeline."""
    if imagination_path is None:
        imagination_path = CURRENT_PATH
    if uniforms_path is None:
        uniforms_path = UNIFORMS_FILE

    try:
        if not imagination_path.exists():
            return
        data = json.loads(imagination_path.read_text())
    except (OSError, json.JSONDecodeError):
        return

    material = data.get("material", "water")
    material_val = float(MATERIAL_MAP.get(material, 0))
    salience = float(data.get("salience", 0.0))

    uniforms = {
        "custom": [material_val],
        "slot_opacities": [salience, 0.0, 0.0, 0.0],
    }

    try:
        uniforms_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = uniforms_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(uniforms))
        tmp.rename(uniforms_path)
    except OSError:
        pass


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

        # Bootstrap Reverie's quiescent substrate before entering loops.
        # Analogous to Daimonion's subsystem init before cognitive loop starts.
        try:
            from agents.reverie.bootstrap import write_substrate_plan

            if write_substrate_plan():
                log.info("Reverie substrate bootstrapped")
        except Exception:
            log.warning("Reverie bootstrap failed", exc_info=True)

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
                        resolve_references_staged(frag)
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

        # Write imagination uniforms for visual pipeline
        write_imagination_uniforms()

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
