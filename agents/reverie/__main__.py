# agents/reverie/__main__.py
"""Reverie daemon — independent visual expression service.

Owns the ReverieMixer lifecycle, consumes impingements from DMN via
ImpingementConsumer, and ticks the mixer on a 1s governance cadence.

Usage:
    uv run python -m agents.reverie
"""

from __future__ import annotations

import asyncio
import logging
import signal
import time
from pathlib import Path

from shared.control_signal import ControlSignal, publish_health
from shared.impingement_consumer import ImpingementConsumer

log = logging.getLogger("reverie")

IMPINGEMENT_PATH = Path("/dev/shm/hapax-dmn/impingements.jsonl")
EXPLORATION_STATE_PATH = Path.home() / ".cache" / "hapax" / "exploration-tracker-state.json"
TICK_INTERVAL_S = 1.0


class ReverieDaemon:
    """Standalone Reverie visual expression daemon."""

    def __init__(
        self,
        impingement_path: Path = IMPINGEMENT_PATH,
        mixer: object | None = None,
        skip_bootstrap: bool = False,
    ) -> None:
        self._consumer = ImpingementConsumer(impingement_path)
        self._running = True
        # Control law state
        self._cl_errors = 0
        self._cl_ok = 0
        self._cl_degraded = False
        self._cl_original_tick = TICK_INTERVAL_S

        if not skip_bootstrap:
            from agents.reverie.bootstrap import write_vocabulary_plan

            try:
                if write_vocabulary_plan():
                    log.info("Reverie vocabulary written")
            except Exception:
                log.warning("Reverie vocabulary write failed", exc_info=True)

        if mixer is not None:
            self._mixer = mixer
        elif not skip_bootstrap:
            from agents.reverie.mixer import ReverieMixer

            self._mixer = ReverieMixer()
        else:
            self._mixer = None

        self._load_exploration_state()

    async def tick(self) -> None:
        """One daemon cycle: consume impingements, tick mixer."""
        impingements = self._consumer.read_new()
        for imp in impingements:
            if self._mixer is not None:
                self._mixer.dispatch_impingement(imp)

        if self._mixer is not None:
            await self._mixer.tick()

    async def run(self) -> None:
        """Main loop — never stops unless signalled."""
        global TICK_INTERVAL_S
        log.info("Reverie daemon starting")
        self._last_save = time.monotonic()
        while self._running:
            try:
                await self.tick()
            except Exception:
                log.exception("Reverie tick failed")
                publish_health(ControlSignal(component="reverie", reference=1.0, perception=0.0))
                # Control law: tick exception → slow down
                self._cl_errors += 1
                self._cl_ok = 0

                if self._cl_errors >= 3 and not self._cl_degraded:
                    self._cl_original_tick = TICK_INTERVAL_S
                    TICK_INTERVAL_S = TICK_INTERVAL_S * 2.0
                    self._cl_degraded = True
                    log.warning("Control law [reverie]: degrading — doubling tick interval")
            else:
                # Successful tick
                self._cl_errors = 0
                self._cl_ok += 1
                if self._cl_ok >= 5 and self._cl_degraded:
                    TICK_INTERVAL_S = self._cl_original_tick
                    self._cl_degraded = False
                    log.info("Control law [reverie]: recovered")
            await asyncio.sleep(TICK_INTERVAL_S)
        log.info("Reverie daemon stopped")

    def _save_exploration_state(self) -> None:
        """Persist exploration tracker state to disk."""
        if self._mixer is None:
            return
        import json

        tracker = getattr(self._mixer, "_exploration", None)
        if tracker is None:
            return
        try:
            EXPLORATION_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = EXPLORATION_STATE_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(tracker.state_dict()), encoding="utf-8")
            tmp.rename(EXPLORATION_STATE_PATH)
        except Exception:
            log.debug("Exploration state save failed", exc_info=True)

    def _load_exploration_state(self) -> None:
        """Restore exploration tracker state from disk."""
        if self._mixer is None:
            log.debug("No mixer, skipping exploration state load")
            return
        import json

        tracker = getattr(self._mixer, "_exploration", None)
        if tracker is None:
            log.debug("No _exploration on mixer, skipping load")
            return
        try:
            if EXPLORATION_STATE_PATH.exists():
                state = json.loads(EXPLORATION_STATE_PATH.read_text(encoding="utf-8"))
                tracker.load_state_dict(state)
                log.info("Loaded exploration tracker state from %s", EXPLORATION_STATE_PATH)
            else:
                log.info("No exploration state file yet at %s", EXPLORATION_STATE_PATH)
        except Exception:
            log.warning("Exploration state load failed", exc_info=True)

    def stop(self) -> None:
        self._running = False
        # Persist recruitment learning (Thompson sampling + Hebbian associations)
        if self._mixer is not None:
            try:
                self._mixer.pipeline.save_activation_state()
                self._save_exploration_state()
                log.info("Saved recruitment learning + exploration state")
            except Exception:
                log.debug("Failed to save state", exc_info=True)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    daemon = ReverieDaemon()

    def handle_signal(sig: int, frame: object) -> None:
        log.info("Signal %d received, stopping", sig)
        daemon.stop()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    # Periodic save in a background thread (event loop may be starved by tick I/O)
    import threading

    def _save_thread() -> None:
        while daemon._running:
            time.sleep(60)
            if daemon._mixer is not None:
                try:
                    daemon._mixer.pipeline.save_activation_state()
                    daemon._save_exploration_state()
                    log.info("Periodic state saved")
                except Exception:
                    log.warning("Periodic save failed", exc_info=True)

    saver = threading.Thread(target=_save_thread, daemon=True)
    saver.start()

    await daemon.run()


if __name__ == "__main__":
    asyncio.run(main())
