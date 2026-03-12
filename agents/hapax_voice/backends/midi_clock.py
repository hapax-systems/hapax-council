"""MIDI clock perception backend — transport state and beat position.

Stub backend: reserves behavior names and proves the protocol.
Actual hardware integration requires ALSA MIDI or JACK transport.
"""

from __future__ import annotations

import logging

from agents.hapax_voice.perception import PerceptionTier
from agents.hapax_voice.primitives import Behavior

log = logging.getLogger(__name__)


class MidiClockBackend:
    """PerceptionBackend for MIDI clock signals.

    Provides:
      - timeline_mapping: TimelineMapping (transport + tempo)
      - beat_position: float (current beat)
      - bar_position: float (current bar, assuming 4/4)
    """

    @property
    def name(self) -> str:
        return "midi_clock"

    @property
    def provides(self) -> frozenset[str]:
        return frozenset({"timeline_mapping", "beat_position", "bar_position"})

    @property
    def tier(self) -> PerceptionTier:
        return PerceptionTier.EVENT

    def available(self) -> bool:
        return False

    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        pass

    def start(self) -> None:
        log.info("MidiClock backend started (stub)")

    def stop(self) -> None:
        log.info("MidiClock backend stopped (stub)")
