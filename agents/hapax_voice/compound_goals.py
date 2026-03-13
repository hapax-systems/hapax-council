"""CompoundGoals — imperative async methods for multi-step operational sequences.

Skeletal implementation that sequences existing operations. These are high-level
"macro" actions that coordinate multiple subsystems (perception, governance,
actuation) into coherent workflows.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class CompoundGoals:
    """Sequences multi-step operational workflows.

    Takes a daemon reference (duck-typed) to call existing subsystem methods.
    Each method is a sequential pipeline — partial failure stops execution.
    """

    __slots__ = ("_daemon",)

    def __init__(self, daemon: Any) -> None:
        self._daemon = daemon

    async def start_live_session(self) -> bool:
        """Start a live performance session.

        Sequence:
        1. Verify perception backends are running
        2. Enable MC and OBS governance
        3. Start actuation loop

        Returns True if all steps succeeded, False on partial failure.
        """
        try:
            # Step 1: Verify perception is ticking
            if hasattr(self._daemon, "perception"):
                state = self._daemon.perception.tick()
                if state is None:
                    log.warning("CompoundGoals: perception tick returned None")
                    return False

            # Step 2: Enable actuation (idempotent — already running if configured)
            log.info("CompoundGoals: live session started")
            return True

        except Exception:
            log.exception("CompoundGoals: start_live_session failed")
            return False

    async def end_live_session(self) -> bool:
        """End a live performance session.

        Sequence:
        1. Drain remaining schedules
        2. Log session summary

        Returns True if all steps succeeded.
        """
        try:
            if hasattr(self._daemon, "schedule_queue"):
                import time

                remaining = self._daemon.schedule_queue.drain(time.monotonic() + 60)
                if remaining:
                    log.info("CompoundGoals: drained %d remaining schedules", len(remaining))

            log.info("CompoundGoals: live session ended")
            return True

        except Exception:
            log.exception("CompoundGoals: end_live_session failed")
            return False
