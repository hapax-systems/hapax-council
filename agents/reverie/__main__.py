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
from pathlib import Path

from shared.impingement_consumer import ImpingementConsumer

log = logging.getLogger("reverie")

IMPINGEMENT_PATH = Path("/dev/shm/hapax-dmn/impingements.jsonl")
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

    async def tick(self) -> None:
        """One daemon cycle: consume impingements, update sources, tick mixer."""
        impingements = self._consumer.read_new()
        for imp in impingements:
            if self._mixer is not None:
                self._mixer.dispatch_impingement(imp)

        # Update camera sources from compositor
        from agents.reverie.camera_source import update_camera_sources

        update_camera_sources()

        if self._mixer is not None:
            await self._mixer.tick()

    async def run(self) -> None:
        """Main loop — never stops unless signalled."""
        log.info("Reverie daemon starting")
        while self._running:
            try:
                await self.tick()
            except Exception:
                log.exception("Reverie tick failed")
            await asyncio.sleep(TICK_INTERVAL_S)
        log.info("Reverie daemon stopped")

    def stop(self) -> None:
        self._running = False


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

    await daemon.run()


if __name__ == "__main__":
    asyncio.run(main())
