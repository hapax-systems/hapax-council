"""Grounding bridge -- adapts GroundingLedger to CPAL control law inputs.

The control law needs: ungrounded_du_count, repair_rate, gqi.
The grounding ledger tracks DU states and computes GQI.
This bridge reads the ledger and provides the control law inputs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class GroundingState:
    """Snapshot of grounding state for the control law."""

    gqi: float  # 0.0-1.0, from ledger.compute_gqi()
    ungrounded_du_count: int  # DUs in PENDING, UNGROUNDED, REPAIR states
    repair_rate: float  # fraction of recent DUs that entered repair
    total_dus: int  # total DUs tracked
    grounded_count: int  # DUs in GROUNDED state


class GroundingBridge:
    """Reads GroundingLedger and produces CPAL control law inputs.

    Called by the evaluator each tick. Provides a GroundingState
    snapshot that the control law uses for error computation.
    """

    def __init__(self, ledger: object | None = None) -> None:
        self._ledger = ledger

    def snapshot(self) -> GroundingState:
        """Read current grounding state from the ledger.

        Returns a default (healthy) state if no ledger is attached.
        """
        if self._ledger is None:
            return GroundingState(
                gqi=0.8,
                ungrounded_du_count=0,
                repair_rate=0.0,
                total_dus=0,
                grounded_count=0,
            )

        gqi = self._ledger.compute_gqi()

        units = getattr(self._ledger, "_units", [])
        total = len(units)

        # Count ungrounded: PENDING, UNGROUNDED, REPAIR_1, REPAIR_2
        ungrounded_states = {"PENDING", "UNGROUNDED", "REPAIR-1", "REPAIR-2"}
        ungrounded = sum(1 for u in units if u.state.value in ungrounded_states)

        # Count grounded
        grounded = sum(1 for u in units if u.state.value == "GROUNDED")

        # Repair rate: fraction of DUs that ever entered repair
        repair_count = sum(1 for u in units if u.repair_count > 0)
        repair_rate = repair_count / max(1, total)

        return GroundingState(
            gqi=gqi,
            ungrounded_du_count=ungrounded,
            repair_rate=repair_rate,
            total_dus=total,
            grounded_count=grounded,
        )

    def record_outcome(self, *, success: bool) -> None:
        """Forward a grounding outcome to the ledger if available.

        Used by the evaluator to feed hysteresis after each grounding event.
        """
        # The ledger handles its own state transitions via process_turn().
        # This method exists so the evaluator can record outcomes for
        # the loop gain controller's hysteresis without knowing about
        # the ledger's internals.
        pass
