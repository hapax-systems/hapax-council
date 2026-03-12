"""Audio energy perception backend — RMS energy and onset detection.

Stub backend: reserves behavior names and proves the protocol.
Actual implementation requires real-time audio analysis.
"""

from __future__ import annotations

import logging

from agents.hapax_voice.perception import PerceptionTier
from agents.hapax_voice.primitives import Behavior

log = logging.getLogger(__name__)


class AudioEnergyBackend:
    """PerceptionBackend for audio energy analysis.

    Provides:
      - audio_energy_rms: float (0.0-1.0, current RMS energy)
      - audio_onset: bool (True on transient onset detection)
    """

    @property
    def name(self) -> str:
        return "audio_energy"

    @property
    def provides(self) -> frozenset[str]:
        return frozenset({"audio_energy_rms", "audio_onset"})

    @property
    def tier(self) -> PerceptionTier:
        return PerceptionTier.FAST

    def available(self) -> bool:
        return False

    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        pass

    def start(self) -> None:
        log.info("AudioEnergy backend started (stub)")

    def stop(self) -> None:
        log.info("AudioEnergy backend stopped (stub)")
