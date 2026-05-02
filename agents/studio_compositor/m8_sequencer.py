"""M8Sequencer — translate director affordances to M8 MIDI note dispatches.

The M8 receives MIDI on its SONG ROW CUE CHANNEL where:
  notes 0-7   = transport buttons (PLAY/SHIFT/EDIT/OPTION/LEFT/RIGHT/UP/DOWN)
  notes 12-19 = track mutes (tracks 1-8)
  notes 20-27 = track solos (tracks 1-8)

Each press is a note-on followed by a short-hold note-off (the M8 latches
mute/solo state on note-on and releases on note-off — this module mirrors
that latched state so callers can ask whether a track is currently soloed
without polling the device).

cc-task: m8-dmn-mute-solo-transport
"""

from __future__ import annotations

import logging
import time
from typing import Literal

from pydantic import BaseModel, Field

from agents.hapax_daimonion.midi_output import MidiOutput

log = logging.getLogger(__name__)

# M8 SONG ROW CUE CHANNEL note-base offsets (per M8 MIDI receive spec).
_TRANSPORT_BASE = 0
_MUTE_BASE = 12
_SOLO_BASE = 20

_VALID_TRANSPORT_BUTTONS = (
    "PLAY",
    "SHIFT",
    "EDIT",
    "OPTION",
    "LEFT",
    "RIGHT",
    "UP",
    "DOWN",
)
_TRANSPORT_NOTE: dict[str, int] = {
    name: _TRANSPORT_BASE + idx for idx, name in enumerate(_VALID_TRANSPORT_BUTTONS)
}

# Hold note-on for ~30 ms before releasing. Long enough for the M8 to latch
# (M8 MIDI scan is ~5 ms); short enough that the operator perceives it as
# instant.
_NOTE_HOLD_S = 0.03


M8ActionKind = Literal["mute", "solo", "button", "release"]


class M8Action(BaseModel):
    """Director-side intent to actuate the M8.

    For ``kind="mute"`` / ``"solo"`` / ``"release"``, ``track`` is the
    0-indexed track number 0-7. For ``kind="button"``, ``button`` is one
    of the transport-button names.
    """

    kind: M8ActionKind
    track: int | None = Field(default=None, ge=0, le=7)
    button: str | None = None
    channel: int = Field(default=0, ge=0, le=15)


class M8Sequencer:
    """Director → M8 MIDI dispatch with mute/solo state mirroring.

    Mirrors the vocal_chain.VocalChain dispatch shape: takes a single
    action object per call, resolves to MIDI primitives, and updates an
    internal state mirror so consumers can query without polling the M8.
    No-ops cleanly when the M8 MIDI port is absent — the existing
    ``MidiOutput.is_open()`` gate handles that without log spam.
    """

    def __init__(self, midi_output: MidiOutput) -> None:
        self._midi = midi_output
        # Per-track mute/solo latched state (mirrors what the M8 itself
        # holds after each note-on).
        self._muted_tracks: set[int] = set()
        self._soloed_tracks: set[int] = set()

    @property
    def muted_tracks(self) -> frozenset[int]:
        return frozenset(self._muted_tracks)

    @property
    def soloed_tracks(self) -> frozenset[int]:
        return frozenset(self._soloed_tracks)

    def dispatch(self, action: M8Action) -> bool:
        """Route an action to the M8 MIDI port.

        Returns True if a note pair was emitted, False if the action
        was a no-op (port absent, already-in-state, invalid args).
        """
        if action.kind == "button":
            return self._dispatch_button(action)
        if action.kind == "mute":
            return self._dispatch_track_toggle(action, _MUTE_BASE, self._muted_tracks)
        if action.kind == "solo":
            return self._dispatch_track_toggle(action, _SOLO_BASE, self._soloed_tracks)
        if action.kind == "release":
            return self._dispatch_release(action)
        log.warning("M8Sequencer: unknown action kind %r", action.kind)
        return False

    def _dispatch_button(self, action: M8Action) -> bool:
        if action.button not in _TRANSPORT_NOTE:
            log.warning(
                "M8Sequencer: unknown transport button %r (valid: %s)",
                action.button,
                ", ".join(_VALID_TRANSPORT_BUTTONS),
            )
            return False
        note = _TRANSPORT_NOTE[action.button]
        return self._send_note_pair(action.channel, note)

    def _dispatch_track_toggle(
        self,
        action: M8Action,
        note_base: int,
        state: set[int],
    ) -> bool:
        if action.track is None:
            log.warning("M8Sequencer: %s action requires track index", action.kind)
            return False
        note = note_base + action.track
        emitted = self._send_note_pair(action.channel, note)
        if emitted:
            # M8 latches: if track was already in state, this toggles it
            # back off; otherwise it toggles on.
            if action.track in state:
                state.discard(action.track)
            else:
                state.add(action.track)
        return emitted

    def _dispatch_release(self, action: M8Action) -> bool:
        """Explicitly release any latched mute + solo on a track.

        Useful for "return to baseline" affordances at segment boundaries.
        """
        if action.track is None:
            log.warning("M8Sequencer: release action requires track index")
            return False
        emitted = False
        if action.track in self._muted_tracks:
            note = _MUTE_BASE + action.track
            if self._send_note_pair(action.channel, note):
                self._muted_tracks.discard(action.track)
                emitted = True
        if action.track in self._soloed_tracks:
            note = _SOLO_BASE + action.track
            if self._send_note_pair(action.channel, note):
                self._soloed_tracks.discard(action.track)
                emitted = True
        return emitted

    def _send_note_pair(self, channel: int, note: int) -> bool:
        if not self._midi.is_open():
            # Open lazily if not yet attempted; if open succeeds, proceed,
            # otherwise log-once-and-no-op (MidiOutput owns the open path).
            self._midi.send_note_on(channel, note, velocity=100)
            if not self._midi.is_open():
                return False
            self._midi.send_note_off(channel, note)
            return True
        self._midi.send_note_on(channel, note, velocity=100)
        time.sleep(_NOTE_HOLD_S)
        self._midi.send_note_off(channel, note)
        return True
