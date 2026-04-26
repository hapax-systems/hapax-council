"""Tests for the L-12 scribble-strip ward data model."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agents.scribble_strip_ward import (
    AuxAssertion,
    ScribbleStripState,
    StripAssertion,
    evilpet_send_b_invariant_present,
)


def _full_strips() -> list[StripAssertion]:
    """12 minimal strips covering channels 1-12."""
    return [
        StripAssertion(channel=i, label=f"CH {i}", phantom="n/a", notes="") for i in range(1, 13)
    ]


def test_strip_assertion_basic():
    s = StripAssertion(channel=2, label="Cortado contact mic", phantom="+48V")
    assert s.channel == 2


def test_strip_label_max_length():
    with pytest.raises(ValidationError):
        StripAssertion(channel=1, label="x" * 25)


def test_strip_rejects_narrative_phrases():
    with pytest.raises(ValidationError, match="narrative"):
        StripAssertion(channel=1, label="currently active")


def test_strip_channel_out_of_range():
    with pytest.raises(ValidationError):
        StripAssertion(channel=13, label="invalid")
    with pytest.raises(ValidationError):
        StripAssertion(channel=0, label="invalid")


def test_state_requires_12_strips():
    state = ScribbleStripState(strips=_full_strips(), aux=[])
    assert len(state.strips) == 12

    with pytest.raises(ValidationError, match="12 input channels"):
        ScribbleStripState(
            strips=[StripAssertion(channel=1, label="solo")],
            aux=[],
        )


def test_state_rejects_duplicate_channel():
    strips = _full_strips()
    # Two strips on channel 1
    strips[1] = StripAssertion(channel=1, label="dup")
    with pytest.raises(ValidationError):
        ScribbleStripState(strips=strips, aux=[])


def test_state_rejects_duplicate_aux():
    state_kwargs = dict(
        strips=_full_strips(),
        aux=[
            AuxAssertion(bus="A", label="A1"),
            AuxAssertion(bus="A", label="A2"),
        ],
    )
    with pytest.raises(ValidationError, match="duplicate AUX bus"):
        ScribbleStripState(**state_kwargs)


def test_evilpet_invariant_present():
    state = ScribbleStripState(
        strips=_full_strips(),
        aux=[
            AuxAssertion(
                bus="B",
                label="Evil Pet send",
                invariant="CH 6 SEND-B-MUST-BE-ZERO",
            )
        ],
    )
    assert evilpet_send_b_invariant_present(state) is True


def test_evilpet_invariant_absent():
    state = ScribbleStripState(
        strips=_full_strips(),
        aux=[AuxAssertion(bus="B", label="Evil Pet send", invariant="")],
    )
    assert evilpet_send_b_invariant_present(state) is False


def test_evilpet_invariant_missing_bus():
    state = ScribbleStripState(
        strips=_full_strips(),
        aux=[AuxAssertion(bus="A", label="other")],
    )
    assert evilpet_send_b_invariant_present(state) is False


def test_aux_assertion_bus_validation():
    with pytest.raises(ValidationError):
        AuxAssertion(bus="X", label="invalid")  # not in Literal
