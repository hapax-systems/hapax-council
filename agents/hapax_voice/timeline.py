"""TimelineMapping — bijective affine map between wall-clock and an alternate time domain.

General-purpose primitive: maps between monotonic wall-clock time and any linear
time domain (beat time, timecode, etc.). Frozen dataclass like Stamped and Command.
Modeled as Behavior[TimelineMapping] — MIDI clock Events update it, callers resolve
Schedule.wall_time via time_at_beat() at construction time.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TransportState(Enum):
    """Transport state for a timeline."""

    PLAYING = "playing"
    STOPPED = "stopped"


@dataclass(frozen=True)
class TimelineMapping:
    """Bijective affine map between wall-clock and an alternate time domain.

    When PLAYING: beat = ref_beat + (t - ref_time) * (tempo / 60)
    When STOPPED: beat_at_time returns reference_beat, time_at_beat returns reference_time.
    """

    reference_time: float
    reference_beat: float
    tempo: float
    transport: TransportState = TransportState.STOPPED

    def __post_init__(self) -> None:
        if self.tempo <= 0:
            raise ValueError(f"Tempo must be positive, got {self.tempo}")

    def beat_at_time(self, t: float) -> float:
        """Wall-clock → beat. Frozen when stopped."""
        if self.transport is TransportState.STOPPED:
            return self.reference_beat
        return self.reference_beat + (t - self.reference_time) * (self.tempo / 60.0)

    def time_at_beat(self, b: float) -> float:
        """Beat → wall-clock. Inverse of beat_at_time when playing."""
        if self.transport is TransportState.STOPPED:
            return self.reference_time
        return self.reference_time + (b - self.reference_beat) * (60.0 / self.tempo)
