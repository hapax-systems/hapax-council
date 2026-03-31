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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.reverie.mixer import ReverieMixer

from agents._impingement import Impingement, ImpingementType
from agents.dmn.buffer import DMNBuffer
from agents.dmn.pulse import DMNPulse
from agents.imagination import CURRENT_PATH, ImaginationFragment
from agents.imagination_loop import ImaginationLoop
from agents.imagination_resolver import CONTENT_DIR, resolve_references_staged

log = logging.getLogger("dmn")

# Output paths
DMN_STATE_DIR = Path("/dev/shm/hapax-dmn")
BUFFER_FILE = DMN_STATE_DIR / "buffer.txt"
STATUS_FILE = DMN_STATE_DIR / "status.json"
IMPINGEMENTS_FILE = DMN_STATE_DIR / "impingements.jsonl"
TPN_ACTIVE_FILE = DMN_STATE_DIR / "tpn_active"

# Main loop tick rate (fastest possible — individual ticks have their own cadence)
LOOP_TICK_S = 1.0


def _read_tpn_active(path: Path = TPN_ACTIVE_FILE, stale_s: float = 5.0) -> bool:
    """Read TPN active signal with staleness check.

    Format: "1:{timestamp}" or "0:{timestamp}" (new) or bare "1"/"0" (legacy).
    """
    try:
        raw = path.read_text().strip()
        if ":" in raw:
            value, ts = raw.split(":", 1)
            if time.time() - float(ts) > stale_s:
                return False
            return value == "1"
        return raw == "1"
    except (OSError, ValueError):
        return False


class DMNDaemon:
    """Always-on DMN daemon."""

    def __init__(self) -> None:
        self._buffer = DMNBuffer()
        self._pulse = DMNPulse(self._buffer)
        self._imagination = ImaginationLoop()
        self._running = True
        self._start_time = time.monotonic()
        self._reverie: ReverieMixer | None = None  # initialized in run()
        self._resolver_failures: dict[str, int] = {}
        self._resolver_skip_until: dict[str, float] = {}
        self._resolver_consecutive_failures: int = 0
        self._feedback_cursor: int = 0  # byte offset into impingements.jsonl

    async def run(self) -> None:
        """Main loop — never stops unless signalled."""
        DMN_STATE_DIR.mkdir(parents=True, exist_ok=True)
        log.info("DMN daemon starting")

        # Write the permanent visual vocabulary (graph structure never changes).
        # There is no idle state — params are driven by imagination fragments.
        try:
            from agents.reverie.bootstrap import write_vocabulary_plan

            if write_vocabulary_plan():
                log.info("Reverie vocabulary written")
        except Exception:
            log.warning("Reverie vocabulary write failed", exc_info=True)

        # Initialize Reverie mixer — visual peer of Daimonion
        try:
            from agents.reverie.mixer import ReverieMixer

            self._reverie = ReverieMixer()
            log.info("Reverie mixer initialized")
        except Exception:
            log.warning("Reverie actuation init failed", exc_info=True)

        asyncio.create_task(self._imagination_loop())
        asyncio.create_task(self._resolver_loop())

        # Fire first imagination tick immediately — Reverie should reflect
        # DMN state from the very first frame, not wait for cadence timer.
        try:
            from agents.dmn.sensor import read_all

            observations = self._buffer.recent_observations(5)
            snapshot = read_all()
            await self._imagination.tick(observations, snapshot)
            log.info("First imagination tick fired")
        except Exception:
            log.warning("First imagination tick failed", exc_info=True)

        while self._running:
            try:
                await self._pulse.tick()
                self._write_output()
                self._consume_fortress_feedback()

                # Reverie actuation tick (1s cadence, same as main loop)
                if self._reverie is not None:
                    await self._reverie.tick()
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
                self._imagination.set_tpn_active(_read_tpn_active())
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
                        skip_until = self._resolver_skip_until.get(frag_id)
                        if skip_until and time.time() < skip_until:
                            pass
                        else:
                            if skip_until:
                                del self._resolver_skip_until[frag_id]
                            last_fragment_id = frag_id
                            try:
                                frag = ImaginationFragment.model_validate(data)
                                resolve_references_staged(frag)
                                self._resolver_failures.pop(frag_id, None)
                                self._resolver_consecutive_failures = 0
                                log.debug("Resolved content for fragment %s", frag_id)
                            except Exception:
                                count = self._resolver_failures.get(frag_id, 0) + 1
                                self._resolver_failures[frag_id] = count
                                self._resolver_consecutive_failures += 1
                                if count >= 5:
                                    self._resolver_skip_until[frag_id] = time.time() + 60.0
                                    log.warning(
                                        "Resolver: skipping fragment %s after %d failures",
                                        frag_id,
                                        count,
                                    )
                                else:
                                    log.debug("Resolver tick failed for %s (%d/5)", frag_id, count)
                                if self._resolver_consecutive_failures == 3:
                                    self._emit_resolver_degraded()
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
            log.warning("Failed to write buffer to %s", BUFFER_FILE, exc_info=True)

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
                log.warning("Failed to write impingements to %s", IMPINGEMENTS_FILE, exc_info=True)

            # Feed impingements to Reverie via affordance pipeline
            if self._reverie is not None:
                for imp in impingements:
                    candidates = self._reverie.pipeline.select(imp)
                    for c in candidates:
                        if c.capability_name == "shader_graph":
                            self._reverie.shader_capability.activate(imp, imp.strength)
                        elif c.capability_name == "visual_chain":
                            score = self._reverie.visual_chain.can_resolve(imp)
                            if score > 0:
                                self._reverie.visual_chain.activate(imp, score)

        # Read TPN active flag (anti-correlation signal from voice daemon)
        self._pulse.set_tpn_active(_read_tpn_active())

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

    def _emit_resolver_degraded(self) -> None:
        """Emit an impingement when the content resolver is failing repeatedly."""
        imp = Impingement(
            timestamp=time.time(),
            source="dmn.resolver",
            type=ImpingementType.ABSOLUTE_THRESHOLD,
            strength=0.6,
            content={"metric": "resolver_consecutive_failures", "value": 3},
        )
        try:
            with IMPINGEMENTS_FILE.open("a", encoding="utf-8") as f:
                f.write(imp.model_dump_json() + "\n")
            log.warning(
                "Content resolver degraded — emitted impingement after 3 consecutive failures"
            )
        except OSError:
            log.warning("Content resolver degraded but failed to write impingement")

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
