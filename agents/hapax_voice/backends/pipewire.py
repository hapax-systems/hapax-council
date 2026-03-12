"""PipeWire perception backend — audio system state via wpctl/aconnect.

Provides audio-related Behaviors by polling PipeWire state through
wpctl (volume) and aconnect (MIDI connections). Replaces the subprocess
calls that were previously inline in ContextGate veto predicates.
"""

from __future__ import annotations

import logging
import subprocess

from agents.hapax_voice.perception import PerceptionTier
from agents.hapax_voice.primitives import Behavior

log = logging.getLogger(__name__)


class PipeWireBackend:
    """PerceptionBackend that reads audio state from PipeWire/ALSA.

    Provides:
      - sink_volume: float (0.0-1.0+)
      - midi_active: bool
    """

    def __init__(self) -> None:
        self._b_sink_volume: Behavior[float] = Behavior(0.0)
        self._b_midi_active: Behavior[bool] = Behavior(False)

    @property
    def name(self) -> str:
        return "pipewire"

    @property
    def provides(self) -> frozenset[str]:
        return frozenset({"sink_volume", "midi_active"})

    @property
    def tier(self) -> PerceptionTier:
        return PerceptionTier.FAST

    def available(self) -> bool:
        """Check if wpctl is accessible."""
        try:
            result = subprocess.run(
                ["wpctl", "status"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        """Poll PipeWire state and update behaviors."""
        import time

        now = time.monotonic()

        # Volume
        volume = self._poll_volume()
        if volume is not None:
            self._b_sink_volume.update(volume, now)

        # MIDI
        midi_active = self._poll_midi()
        self._b_midi_active.update(midi_active, now)

        behaviors["sink_volume"] = self._b_sink_volume
        behaviors["midi_active"] = self._b_midi_active

    def start(self) -> None:
        log.info("PipeWire backend started")

    def stop(self) -> None:
        log.info("PipeWire backend stopped")

    def _poll_volume(self) -> float | None:
        """Get default audio sink volume via wpctl."""
        try:
            result = subprocess.run(
                ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            parts = result.stdout.strip().split()
            if len(parts) >= 2:
                return float(parts[1])
        except Exception as exc:
            log.debug("Failed to get sink volume: %s", exc)
        return None

    def _poll_midi(self) -> bool:
        """Check for active MIDI connections via aconnect."""
        try:
            result = subprocess.run(
                ["aconnect", "-l"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in result.stdout.splitlines():
                stripped = line.strip()
                if stripped.startswith(("Connecting To:", "Connected From:")):
                    if "Through" not in stripped:
                        return True
        except Exception as exc:
            log.debug("Failed to check MIDI connections: %s", exc)
        return False
