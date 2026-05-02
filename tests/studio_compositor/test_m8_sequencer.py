"""Unit tests for M8Sequencer.

Verifies note-on/off pair emission, latched state mirroring, port-absent
no-op, transport button mapping, and release-action behavior.

cc-task: m8-dmn-mute-solo-transport
"""

from __future__ import annotations

import pytest

from agents.studio_compositor.m8_sequencer import (
    _MUTE_BASE,
    _SOLO_BASE,
    _TRANSPORT_NOTE,
    M8Action,
    M8Sequencer,
)


class FakeMidiOutput:
    """In-memory MidiOutput stand-in. Records sent messages for inspection."""

    def __init__(self, *, port_open: bool = True) -> None:
        self._port_open = port_open
        self.note_on_calls: list[tuple[int, int, int]] = []
        self.note_off_calls: list[tuple[int, int]] = []

    def is_open(self) -> bool:
        return self._port_open

    def send_note_on(self, channel: int, note: int, velocity: int = 100) -> None:
        self.note_on_calls.append((channel, note, velocity))

    def send_note_off(self, channel: int, note: int) -> None:
        self.note_off_calls.append((channel, note))


def test_button_press_emits_note_pair():
    midi = FakeMidiOutput()
    seq = M8Sequencer(midi)
    ok = seq.dispatch(M8Action(kind="button", button="PLAY", channel=0))

    assert ok is True
    assert midi.note_on_calls == [(0, _TRANSPORT_NOTE["PLAY"], 100)]
    assert midi.note_off_calls == [(0, _TRANSPORT_NOTE["PLAY"])]


def test_all_transport_buttons_have_distinct_notes():
    """Sanity: 8 transport buttons map to 8 distinct notes 0-7."""
    notes = list(_TRANSPORT_NOTE.values())
    assert sorted(notes) == list(range(8))


def test_unknown_button_logged_and_no_op():
    midi = FakeMidiOutput()
    seq = M8Sequencer(midi)
    ok = seq.dispatch(M8Action(kind="button", button="BOGUS", channel=0))

    assert ok is False
    assert midi.note_on_calls == []


def test_mute_track_emits_correct_note():
    midi = FakeMidiOutput()
    seq = M8Sequencer(midi)
    ok = seq.dispatch(M8Action(kind="mute", track=2, channel=0))

    assert ok is True
    assert midi.note_on_calls == [(0, _MUTE_BASE + 2, 100)]
    assert seq.muted_tracks == {2}


def test_solo_track_emits_correct_note():
    midi = FakeMidiOutput()
    seq = M8Sequencer(midi)
    ok = seq.dispatch(M8Action(kind="solo", track=0, channel=0))

    assert ok is True
    assert midi.note_on_calls == [(0, _SOLO_BASE + 0, 100)]
    assert seq.soloed_tracks == {0}


def test_mute_toggle_releases_on_second_press():
    """M8 latches mute state: pressing the same mute again toggles it off."""
    midi = FakeMidiOutput()
    seq = M8Sequencer(midi)
    seq.dispatch(M8Action(kind="mute", track=3, channel=0))
    assert seq.muted_tracks == {3}

    seq.dispatch(M8Action(kind="mute", track=3, channel=0))
    assert seq.muted_tracks == set()
    assert len(midi.note_on_calls) == 2  # both presses emitted


def test_solo_toggle_releases_on_second_press():
    midi = FakeMidiOutput()
    seq = M8Sequencer(midi)
    seq.dispatch(M8Action(kind="solo", track=5, channel=0))
    seq.dispatch(M8Action(kind="solo", track=5, channel=0))
    assert seq.soloed_tracks == set()


def test_release_clears_both_mute_and_solo():
    midi = FakeMidiOutput()
    seq = M8Sequencer(midi)
    seq.dispatch(M8Action(kind="mute", track=4, channel=0))
    seq.dispatch(M8Action(kind="solo", track=4, channel=0))
    assert seq.muted_tracks == {4}
    assert seq.soloed_tracks == {4}

    ok = seq.dispatch(M8Action(kind="release", track=4, channel=0))
    assert ok is True
    assert seq.muted_tracks == set()
    assert seq.soloed_tracks == set()


def test_release_no_op_when_nothing_latched():
    midi = FakeMidiOutput()
    seq = M8Sequencer(midi)
    ok = seq.dispatch(M8Action(kind="release", track=0, channel=0))

    assert ok is False
    assert midi.note_on_calls == []


def test_port_absent_returns_false():
    midi = FakeMidiOutput(port_open=False)
    seq = M8Sequencer(midi)
    ok = seq.dispatch(M8Action(kind="button", button="PLAY", channel=0))

    assert ok is False
    # MidiOutput.send_note_on was called once (lazy-open attempt) but
    # the second is_open() check still returns False so no note pair.
    assert len(midi.note_on_calls) == 1
    assert midi.note_off_calls == []


def test_track_action_requires_track_index():
    midi = FakeMidiOutput()
    seq = M8Sequencer(midi)
    # pydantic enforces type, so we have to construct manually
    ok = seq.dispatch(M8Action(kind="mute", track=None, channel=0))
    assert ok is False


def test_mute_and_solo_use_independent_state():
    midi = FakeMidiOutput()
    seq = M8Sequencer(midi)
    seq.dispatch(M8Action(kind="mute", track=1, channel=0))
    seq.dispatch(M8Action(kind="solo", track=2, channel=0))

    assert seq.muted_tracks == {1}
    assert seq.soloed_tracks == {2}


def test_unknown_action_kind_logs_and_no_op():
    midi = FakeMidiOutput()
    seq = M8Sequencer(midi)

    # Construct via .model_construct to bypass pydantic validation
    action = M8Action.model_construct(kind="bogus", track=None, button=None, channel=0)
    ok = seq.dispatch(action)

    assert ok is False
    assert midi.note_on_calls == []


def test_channel_routing_passes_through():
    midi = FakeMidiOutput()
    seq = M8Sequencer(midi)
    seq.dispatch(M8Action(kind="button", button="PLAY", channel=7))

    assert midi.note_on_calls[0][0] == 7
    assert midi.note_off_calls[0][0] == 7


def test_track_index_out_of_range_rejected_by_pydantic():
    """Pydantic ge=0/le=7 constraint catches invalid track ranges."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        M8Action(kind="mute", track=8, channel=0)
    with pytest.raises(ValidationError):
        M8Action(kind="mute", track=-1, channel=0)
