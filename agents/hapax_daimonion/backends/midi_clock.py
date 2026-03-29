"""MIDI Clock perception backend — real ALSA MIDI via mido/rtmidi.

Receives MIDI clock (24 PPQN), transport start/stop/continue messages.
Updates timeline_mapping, beat_position, and bar_position Behaviors.

Tempo detected from rolling average of clock tick intervals
(24 ticks = 1 beat at any tempo).
"""

from __future__ import annotations

import collections
import logging
import threading
import time

from agents.hapax_daimonion.perception import PerceptionTier
from agents.hapax_daimonion.primitives import Behavior
from agents.hapax_daimonion.timeline import TimelineMapping, TransportState

try:
    import mido
except ImportError:
    mido = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

# MIDI clock sends 24 ticks per quarter note
_PPQN = 24
_DEFAULT_TEMPO = 120.0
_ROLLING_WINDOW = _PPQN  # average over 1 beat of ticks


class MidiClockBackend:
    """Receives MIDI clock from an ALSA MIDI port via mido.

    Provides:
      - timeline_mapping: TimelineMapping (tempo + transport state)
      - beat_position: float (current beat)
      - bar_position: float (current bar)
    """

    def __init__(
        self,
        port_name: str = "OXI One",
        beats_per_bar: int = 4,
    ) -> None:
        self._port_name = port_name
        self._beats_per_bar = beats_per_bar

        # Thread-safe state
        self._lock = threading.Lock()
        self._transport = TransportState.STOPPED
        self._tick_count: int = 0
        self._tick_times: collections.deque[float] = collections.deque(maxlen=_ROLLING_WINDOW)
        self._tempo: float = _DEFAULT_TEMPO
        self._reference_time: float = 0.0
        self._reference_beat: float = 0.0

        self._port = None
        self._available = False

    @property
    def name(self) -> str:
        return "midi_clock"

    @property
    def provides(self) -> frozenset[str]:
        return frozenset({"timeline_mapping", "beat_position", "bar_position"})

    @property
    def tier(self) -> PerceptionTier:
        return PerceptionTier.FAST

    def available(self) -> bool:
        return self._available

    def start(self) -> None:
        """Open MIDI input port with callback thread."""
        if mido is None:
            log.info("mido not installed, MIDI clock backend unavailable")
            self._available = False
            return
        try:
            self._port = mido.open_input(self._port_name, callback=self._on_message)
            self._available = True
            log.info("MIDI clock listening on port: %s", self._port_name)
        except Exception as exc:
            log.info("MIDI port '%s' not available: %s", self._port_name, exc)
            self._available = False

    def stop(self) -> None:
        """Close the MIDI port."""
        if self._port is not None:
            try:
                self._port.close()
            except Exception:
                pass
            self._port = None
        self._available = False

    def _on_message(self, msg) -> None:
        """Callback from mido's input thread. Updates state behind lock."""
        now = time.monotonic()
        with self._lock:
            if msg.type == "clock":
                self._tick_times.append(now)
                if self._transport is TransportState.PLAYING:
                    self._tick_count += 1
                    self._update_tempo()
            elif msg.type == "start":
                self._transport = TransportState.PLAYING
                self._tick_count = 0
                self._reference_time = now
                self._reference_beat = 0.0
                self._tick_times.clear()
            elif msg.type == "stop":
                self._snap_reference(now)
                self._transport = TransportState.STOPPED
            elif msg.type == "continue":
                self._reference_time = now
                self._transport = TransportState.PLAYING

    def _update_tempo(self) -> None:
        """Calculate tempo from rolling average of tick intervals. Called under lock."""
        if len(self._tick_times) < 2:
            return
        intervals = [
            self._tick_times[i] - self._tick_times[i - 1] for i in range(1, len(self._tick_times))
        ]
        avg_interval = sum(intervals) / len(intervals)
        if avg_interval > 0:
            # 24 ticks per beat → beat interval = avg_interval * 24
            beat_interval = avg_interval * _PPQN
            self._tempo = 60.0 / beat_interval

    def _snap_reference(self, now: float) -> None:
        """Snap reference point to current position before stopping. Called under lock."""
        if self._transport is TransportState.PLAYING:
            self._reference_beat = self._tick_count / _PPQN
            self._reference_time = now

    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        """Read latest state and update Behaviors."""
        now = time.monotonic()
        with self._lock:
            mapping = TimelineMapping(
                reference_time=self._reference_time,
                reference_beat=self._reference_beat,
                tempo=self._tempo,
                transport=self._transport,
            )
            # Use tick count for beat position (more accurate than affine extrapolation)
            if self._transport is TransportState.PLAYING:
                beat = self._reference_beat + self._tick_count / _PPQN
            else:
                beat = self._reference_beat
            bar = beat / self._beats_per_bar

        if "timeline_mapping" not in behaviors:
            behaviors["timeline_mapping"] = Behavior(mapping, watermark=now)
        else:
            behaviors["timeline_mapping"].update(mapping, now)

        if "beat_position" not in behaviors:
            behaviors["beat_position"] = Behavior(beat, watermark=now)
        else:
            behaviors["beat_position"].update(beat, now)

        if "bar_position" not in behaviors:
            behaviors["bar_position"] = Behavior(bar, watermark=now)
        else:
            behaviors["bar_position"].update(bar, now)
