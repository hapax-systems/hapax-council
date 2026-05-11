"""Gemini-backed coordination daemon.

Replaces: triage_officer daemon, lane idle watchdog, RTE relay pattern.

Tick loop:
  1. Scan task queue for unassigned/offered tasks
  2. Check lane health (relay YAML + PID files)
  3. Match tasks to idle lanes using Gemini for intelligent routing
  4. Dispatch work via hapax-claude/hapax-codex/hapax-gemini scripts
  5. Write coordination state to /dev/shm/hapax-coordinator/state.json

Run: ``uv run python -m agents.coordinator``
Systemd: ``systemd/units/hapax-coordinator.service``
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time

from agents.coordinator.core import Coordinator

log = logging.getLogger(__name__)

_shutdown = False


def _handle_signal(signum: int, _frame: object) -> None:
    global _shutdown
    _shutdown = True
    log.info("Received signal %d, shutting down", signum)


def main() -> None:
    logging.basicConfig(
        level=logging.DEBUG if "--debug" in sys.argv else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    tick_s = float(os.environ.get("HAPAX_COORDINATOR_TICK_S", "30"))

    coordinator = Coordinator()

    log.info("Coordinator daemon starting (tick=%.1fs)", tick_s)

    if "--once" in sys.argv:
        coordinator.tick()
        return

    while not _shutdown:
        t0 = time.monotonic()
        try:
            coordinator.tick()
        except Exception:
            log.exception("Coordinator tick failed")
        elapsed = time.monotonic() - t0
        sleep_s = max(1.0, tick_s - elapsed)
        time.sleep(sleep_s)

    log.info("Coordinator daemon stopped")


if __name__ == "__main__":
    main()
