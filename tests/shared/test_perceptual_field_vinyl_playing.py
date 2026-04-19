"""Tests for the derived `vinyl_playing` signal on PerceptualField.

#127 SPLATTRIBUTION — music featuring must be decoupled from raw vinyl
playback. The `vinyl_playing` computed property combines MIDI transport
state with the beat_position_rate tendency signal so that consumers
(album overlay, track-ID attribution, twitch director music framing,
Hapax-music-repo path #130, SoundCloud passthrough #131) gate on one
authoritative boolean. Guards against a stale transport_state that
reports PLAYING when the clock source has silently stopped ticking.

Pins the behavior under the 4 operative conditions listed in the
spec (`docs/superpowers/specs/2026-04-18-splattribution-design.md` §9):

    1. transport PLAYING + positive rate  -> True
    2. transport STOPPED                  -> False
    3. transport PLAYING + zero rate      -> False (scratch stop / stall)
    4. MIDI state absent entirely         -> False (fail-safe)
"""

from __future__ import annotations

from shared.perceptual_field import (
    AudioField,
    MidiState,
    PerceptualField,
    TendencyField,
)


def _make_field(
    transport_state: str | None,
    beat_position_rate: float | None,
) -> PerceptualField:
    """Construct a minimal PerceptualField with only the fields #127 needs."""
    return PerceptualField(
        audio=AudioField(midi=MidiState(transport_state=transport_state)),
        tendency=TendencyField(beat_position_rate=beat_position_rate),
    )


def test_playing_with_positive_rate_is_true():
    field = _make_field(transport_state="PLAYING", beat_position_rate=2.0)
    assert field.vinyl_playing is True


def test_stopped_is_false_regardless_of_rate():
    # Even if a stale rate sample is lying around from before the stop,
    # the transport flag must veto.
    field = _make_field(transport_state="STOPPED", beat_position_rate=2.0)
    assert field.vinyl_playing is False


def test_playing_with_zero_rate_is_false():
    """Scratch stop: transport was never STOP'd but the platter isn't
    moving. The rate signal catches this where the raw transport flag
    cannot.
    """
    field = _make_field(transport_state="PLAYING", beat_position_rate=0.0)
    assert field.vinyl_playing is False


def test_missing_midi_state_is_false_failsafe():
    """Fail-safe: if MIDI state was never populated, assume no vinyl."""
    field = _make_field(transport_state=None, beat_position_rate=None)
    assert field.vinyl_playing is False


def test_missing_rate_is_false_failsafe():
    """The tendency sampler returns None on the first read after reset.
    `vinyl_playing` must stay False until a rate has actually been
    observed, otherwise the first tick after boot would false-positive.
    """
    field = _make_field(transport_state="PLAYING", beat_position_rate=None)
    assert field.vinyl_playing is False


def test_playing_with_negative_rate_is_false():
    """Negative rate = beat position going backwards (scratched back).
    Not a valid 'music is playing forward' state for attribution.
    """
    field = _make_field(transport_state="PLAYING", beat_position_rate=-0.5)
    assert field.vinyl_playing is False


def test_paused_transport_is_false():
    """The Literal accepts PAUSED even though MidiClockBackend only
    writes PLAYING/STOPPED today. If future code ever writes PAUSED,
    vinyl_playing must still be False (spec §10 open question - we
    codify the conservative answer).
    """
    field = _make_field(transport_state="PAUSED", beat_position_rate=1.0)
    assert field.vinyl_playing is False


def test_default_field_is_false():
    """A freshly constructed PerceptualField with no arguments must
    report False - matches the fail-safe invariant end-to-end.
    """
    assert PerceptualField().vinyl_playing is False
