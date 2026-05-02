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
    """Receives MIDI clock from one or more ALSA MIDI ports via mido.

    Multi-port behavior (post m8-midi-clock-peer-tempo-source 2026-05-02):
    pass `port_names=["OXI One", "M8 MIDI 1"]` to subscribe to multiple
    MIDI clock sources concurrently. The most-recently-PLAYING port wins
    the canonical timeline_mapping. When neither is PLAYING, the most-
    recently-active port's last tempo is held. Single-port `port_name`
    arg is preserved for backward compatibility.

    Provides:
      - timeline_mapping: TimelineMapping (tempo + transport state)
      - beat_position: float (current beat)
      - bar_position: float (current bar)
      - midi_clock_transport: str (transport state name)
    """

    def __init__(
        self,
        port_name: str | None = None,
        port_names: list[str] | None = None,
        beats_per_bar: int = 4,
    ) -> None:
        # Single-port backward compat: port_name → single-element port_names.
        # If both passed, port_names wins (multi-port mode is the new default).
        if port_names is None:
            port_names = [port_name or "OXI One"]
        elif port_name is not None and port_name not in port_names:
            port_names = [port_name, *port_names]
        self._port_names: list[str] = port_names
        # Keep _port_name for log/test back-compat (tracks the most-recently-
        # active winning port).
        self._port_name = self._port_names[0]
        self._beats_per_bar = beats_per_bar

        # Thread-safe state — owned by whichever port is currently winning.
        self._lock = threading.Lock()
        self._transport = TransportState.STOPPED
        self._tick_count: int = 0
        self._tick_times: collections.deque[float] = collections.deque(maxlen=_ROLLING_WINDOW)
        self._tempo: float = _DEFAULT_TEMPO
        self._reference_time: float = 0.0
        self._reference_beat: float = 0.0
        # Track which port last received a clock/transport message so we can
        # break ties when both are running. Set by `_on_message` callbacks.
        self._active_port: str = self._port_names[0]
        self._last_msg_time: dict[str, float] = {n: 0.0 for n in self._port_names}

        # Open ports list (parallel to _port_names; some entries may be None
        # if a given port wasn't enumerable at start time).
        self._ports: list[object] = []
        self._available = False

    @property
    def name(self) -> str:
        return "midi_clock"

    @property
    def provides(self) -> frozenset[str]:
        return frozenset(
            {
                "timeline_mapping",
                "beat_position",
                "bar_position",
                "midi_clock_transport",
            }
        )

    @property
    def tier(self) -> PerceptionTier:
        return PerceptionTier.FAST

    def available(self) -> bool:
        return self._available

    def start(self) -> None:
        """Open all configured MIDI input ports with callback threads.

        Tolerates per-port absence — if a port can't be opened, log INFO
        and skip; backend is `available` if at least one port opened.
        """
        if mido is None:
            log.info("mido not installed, MIDI clock backend unavailable")
            self._available = False
            return
        opened: list[str] = []
        for name in self._port_names:
            try:
                # Bind callback with port name so we can track per-port activity.
                callback = self._make_callback(name)
                port = mido.open_input(name, callback=callback)
                self._ports.append(port)
                opened.append(name)
                log.info("MIDI clock listening on port: %s", name)
            except Exception as exc:
                log.info("MIDI port '%s' not available: %s", name, exc)
        self._available = bool(opened)
        if opened:
            self._port_name = opened[0]  # back-compat reference

    def stop(self) -> None:
        """Close all MIDI ports."""
        for port in self._ports:
            try:
                port.close()
            except Exception:
                pass
        self._ports = []
        self._available = False

    def _make_callback(self, port_name: str):
        """Create a per-port callback closure that tags messages with their source."""

        def _cb(msg) -> None:
            self._on_message(msg, source_port=port_name)

        return _cb

    def _on_message(self, msg, source_port: str | None = None) -> None:
        """Callback from mido's input thread. Updates state behind lock.

        Multi-port arbitration: the most-recently-active port wins the
        canonical state. If the source_port is not the current winner AND
        the current winner is in PLAY, ignore non-transport messages from
        the loser to prevent tempo cross-contamination.
        """
        now = time.monotonic()
        if source_port is None:
            source_port = self._port_names[0]
        with self._lock:
            self._last_msg_time[source_port] = now
            # Arbitration: transport messages from any port can take over.
            # Clock messages from non-winning port are ignored while the
            # winning port is PLAYING (prevents two tempos blending).
            is_transport = msg.type in ("start", "stop", "continue")
            if (
                not is_transport
                and self._transport is TransportState.PLAYING
                and source_port != self._active_port
            ):
                return  # let the winning port own the clock
            if is_transport:
                # Transport messages always promote the source port to active.
                self._active_port = source_port
                self._port_name = source_port

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
            transport_name = self._transport.name

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

        # Cross-process publishable transport state for OperatorActivityEngine.
        # ``midi_clock_active`` (Phase 6a-i.B Part 4) reads this through the
        # perception-state.json bridge — emitting the enum *name* keeps the
        # JSON-serialised behavior value stable for the bridge.
        if "midi_clock_transport" not in behaviors:
            behaviors["midi_clock_transport"] = Behavior(transport_name, watermark=now)
        else:
            behaviors["midi_clock_transport"].update(transport_name, now)
