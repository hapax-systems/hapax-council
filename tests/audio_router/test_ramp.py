"""Phase C1 — ramp-time responsiveness formula (spec §6.4).

``compute_ramp_seconds(velocity)`` returns the CC-interpolation duration
that the router should use when transitioning tiers. Ramp time scales
inversely with stimmung velocity and is clamped to [0.2, 2.5] seconds.
"""

from __future__ import annotations

from agents.audio_router import compute_ramp_seconds


def test_high_velocity_clamps_to_minimum_0p2s() -> None:
    """Velocity ≥ 4.0 → ramp_s = 0.2 (snappy floor)."""
    assert compute_ramp_seconds(stimmung_velocity=5.0) == 0.2
    assert compute_ramp_seconds(stimmung_velocity=10.0) == 0.2


def test_low_velocity_clamps_to_maximum_2p5s() -> None:
    """Velocity ≤ 0.32 → ramp_s = 2.5 (smooth ceiling)."""
    assert compute_ramp_seconds(stimmung_velocity=0.1) == 2.5
    assert compute_ramp_seconds(stimmung_velocity=0.01) == 2.5


def test_zero_velocity_does_not_divide_by_zero() -> None:
    """stimmung_velocity=0 is clamped to 0.1 via max() before division."""
    assert compute_ramp_seconds(stimmung_velocity=0.0) == 2.5


def test_negative_velocity_treated_as_zero() -> None:
    """Negative velocity (should never happen live; guard anyway)."""
    assert compute_ramp_seconds(stimmung_velocity=-1.0) == 2.5


def test_default_velocity_yields_1s() -> None:
    """Stimmung velocity ~0.8 d(stance)/s → ~1.0 s ramp (the default)."""
    assert abs(compute_ramp_seconds(stimmung_velocity=0.8) - 1.0) < 0.01


def test_ramp_monotonic_in_inverse_velocity() -> None:
    """Higher velocity → shorter ramp; lower → longer. Strict within
    the unclamped mid-band."""
    assert compute_ramp_seconds(stimmung_velocity=1.0) < compute_ramp_seconds(stimmung_velocity=0.5)
    assert compute_ramp_seconds(stimmung_velocity=0.5) < compute_ramp_seconds(stimmung_velocity=0.2)


def test_ramp_always_in_valid_range() -> None:
    """For any input, result in [0.2, 2.5]."""
    for v in [0.0, 0.1, 0.5, 1.0, 2.0, 5.0, 100.0, -1.0]:
        ramp = compute_ramp_seconds(stimmung_velocity=v)
        assert 0.2 <= ramp <= 2.5
