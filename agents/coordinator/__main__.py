"""Gate-0A coordination observation daemon.

The daemon may inspect task, lane, event-log, and pending-spool support state.
Task-bearing effects remain held behind methodology admission and a future
execution lease; the Gate-0A loop does not launch, repair, reap, or publish.

Run: ``.venv/bin/python -I -m agents.coordinator``
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


def _boot_inspect() -> None:
    """Inspect durable event and spool support without materializing effects."""
    try:
        from shared.coord_event_log import default_event_log

        event_log = default_event_log()
        replay = event_log.replay(fail_open=True)
        spool_pending = (
            sum(1 for _ in event_log.spool_dir.glob("*.jsonl"))
            if event_log.spool_dir.is_dir()
            else 0
        )
        log.info(
            "coord boot inspection: replayed=%d spool_pending=%d source=%s "
            "degraded=%s support_only=true effects=0",
            len(replay.events),
            spool_pending,
            replay.source,
            replay.degraded,
        )
    except Exception:
        log.exception("coord boot inspection HOLD (continuing effect-free daemon start)")


def main() -> None:
    logging.basicConfig(
        level=logging.DEBUG if "--debug" in sys.argv else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    tick_s = float(os.environ.get("HAPAX_COORDINATOR_TICK_S", "30"))

    coordinator = Coordinator()

    _boot_inspect()

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
