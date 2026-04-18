"""Tests for PerceptualField.tendency (S4 anticipation signals).

Pins the rate-computation invariants: first read returns None, second
read returns a per-second diff, samples older than TTL are discarded.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from shared import perceptual_field as pf


@pytest.fixture(autouse=True)
def _reset_cache():
    pf.reset_tendency_cache()
    yield
    pf.reset_tendency_cache()


def test_first_read_returns_none():
    assert pf._compute_rate("x", 1.0, clock=100.0) is None


def test_second_read_returns_per_second_rate():
    pf._compute_rate("x", 1.0, clock=100.0)
    rate = pf._compute_rate("x", 3.0, clock=102.0)
    assert rate == pytest.approx(1.0)  # (3 - 1) / (102 - 100)


def test_negative_rate_preserved():
    pf._compute_rate("x", 10.0, clock=100.0)
    rate = pf._compute_rate("x", 5.0, clock=105.0)
    assert rate == pytest.approx(-1.0)


def test_stale_sample_is_discarded():
    pf._compute_rate("x", 1.0, clock=100.0)
    # Next read is 30s later — beyond the 10s TTL. Must return None so
    # the director never reasons from a minute-old diff.
    rate = pf._compute_rate("x", 5.0, clock=130.0)
    assert rate is None


def test_missing_value_returns_none_and_does_not_clobber_cache():
    pf._compute_rate("x", 1.0, clock=100.0)
    # MIDI briefly unavailable — do not break the sample chain.
    assert pf._compute_rate("x", None, clock=101.0) is None
    # Next valid reading diffs against the 100.0 sample, not 101.0.
    rate = pf._compute_rate("x", 4.0, clock=103.0)
    assert rate == pytest.approx(1.0)  # (4 - 1) / (103 - 100)


def test_zero_delta_t_returns_none():
    """Two reads in the same clock instant — defensive guard against
    the director loop calling build twice for the same tick."""
    pf._compute_rate("x", 1.0, clock=100.0)
    assert pf._compute_rate("x", 2.0, clock=100.0) is None


def test_tendency_field_populated_on_second_build(tmp_path, monkeypatch):
    """End-to-end: two builds spaced in time yield populated tendency."""
    # Minimal perception-state.json with beat_position + desk_energy
    state1 = {"beat_position": 1.0, "desk_energy": 0.1, "transport_state": "PLAYING"}
    state2 = {"beat_position": 3.0, "desk_energy": 0.3, "transport_state": "PLAYING"}

    clock = [1000.0]
    monkeypatch.setattr(pf.time, "time", lambda: clock[0])

    with patch.object(pf, "_read_perception_state", return_value=state1):
        first = pf.build_perceptual_field()
    assert first.tendency.beat_position_rate is None
    assert first.tendency.desk_energy_rate is None

    clock[0] = 1002.0
    with patch.object(pf, "_read_perception_state", return_value=state2):
        second = pf.build_perceptual_field()

    assert second.tendency.beat_position_rate == pytest.approx(1.0)
    assert second.tendency.desk_energy_rate == pytest.approx(0.1)
