"""Energy arc perception backend — macro energy trajectory of a session.

Stub backend: reserves behavior names and proves the protocol.
Actual implementation requires windowed energy analysis over the session timeline.
"""

from __future__ import annotations

import logging

from agents.hapax_voice.perception import PerceptionTier
from agents.hapax_voice.primitives import Behavior

log = logging.getLogger(__name__)


class EnergyArcBackend:
    """PerceptionBackend for energy arc analysis.

    Provides:
      - energy_arc_phase: str (e.g. "building", "peak", "declining", "rest")
      - energy_arc_intensity: float (0.0-1.0)
    """

    @property
    def name(self) -> str:
        return "energy_arc"

    @property
    def provides(self) -> frozenset[str]:
        return frozenset({"energy_arc_phase", "energy_arc_intensity"})

    @property
    def tier(self) -> PerceptionTier:
        return PerceptionTier.SLOW

    def available(self) -> bool:
        return False

    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        pass

    def start(self) -> None:
        log.info("EnergyArc backend started (stub)")

    def stop(self) -> None:
        log.info("EnergyArc backend stopped (stub)")
