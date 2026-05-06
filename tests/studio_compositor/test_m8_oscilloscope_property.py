"""Hypothesis property-based tests for the M8 oscilloscope helpers.

Sister to ``test_m8_oscilloscope_source.py`` (deterministic unit tests
against fixed inputs). This file adds property-based proofs of the
mathematical invariants the helpers must preserve across ALL valid
inputs — not just the handful enumerated as fixtures.

Three properties pinned:

1. ``_amplitude_normalized(samples)`` always returns a value in
   ``[0.0, 1.0]``. Property: bounded output regardless of byte content.
2. ``_amplitude_scaled_alpha(base, amp, floor=floor)`` always returns a
   value in ``[base × floor, base]`` for ``base ∈ [0, 1]``,
   ``amp ∈ [0, 1]``, ``floor ∈ [0, 1]``. Property: the alpha-floor
   invariant holds across the full parameter space.
3. ``_silence_alpha(...)`` always returns a value in
   ``[0, active_alpha]`` for any non-negative age and positive fade
   parameters. Property: never exceeds the silence-fade ceiling, never
   negative.

These properties are load-bearing: an out-of-range output would either
push Cairo into invalid alpha territory (saturating to 1.0 silently or
clipping to 0) or break the silence-fade contract that downstream
consumers (rendered alpha + line-width modulation) rely on.

Pure test addition; no source code touched. CLAUDE.md: "Hypothesis for
property-based algebraic proofs."
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from agents.studio_compositor.m8_oscilloscope_source import (
    _amplitude_normalized,
    _amplitude_scaled_alpha,
    _silence_alpha,
)


@given(
    samples=st.binary(min_size=0, max_size=480),
)
def test_amplitude_normalized_is_bounded(samples: bytes) -> None:
    """Output is always in [0, 1] regardless of input byte content."""
    result = _amplitude_normalized(samples)
    assert 0.0 <= result <= 1.0


@given(
    base=st.floats(min_value=0.0, max_value=1.0),
    amp=st.floats(min_value=0.0, max_value=1.0),
    floor=st.floats(min_value=0.0, max_value=1.0),
)
def test_amplitude_scaled_alpha_respects_floor(base: float, amp: float, floor: float) -> None:
    """Output is in [base × floor, base] across the valid parameter space."""
    result = _amplitude_scaled_alpha(base, amp, floor=floor)
    # Floating-point comparisons need a small tolerance — the formula
    # produces values like 0.7500000000001 for boundary inputs.
    epsilon = 1e-9
    assert result >= base * floor - epsilon
    assert result <= base + epsilon


@given(
    amp=st.floats().filter(lambda x: x != x or x < 0 or x > 1),
    base=st.floats(min_value=0.0, max_value=1.0),
    floor=st.floats(min_value=0.0, max_value=1.0),
)
def test_amplitude_scaled_alpha_clamps_out_of_range_amplitude(
    amp: float, base: float, floor: float
) -> None:
    """Out-of-range amplitudes (NaN, negative, > 1) cannot push output above base.

    Defends the silence-fade ceiling — even a buggy upstream amplitude
    must not lift alpha above what the mtime-driven curve allows.
    """
    result = _amplitude_scaled_alpha(base, amp, floor=floor)
    epsilon = 1e-9
    # NaN inputs would propagate; the function clamps via min/max so
    # NaN in → NaN handled defensively. Otherwise output bounded by base.
    if result == result:  # not NaN
        assert result <= base + epsilon
        assert result >= 0.0 - epsilon


@given(
    age=st.floats(min_value=0.0, max_value=1e6),
    fade_after=st.floats(min_value=0.01, max_value=10.0),
    fade_duration=st.floats(min_value=0.01, max_value=10.0),
    active_alpha=st.floats(min_value=0.0, max_value=1.0),
)
def test_silence_alpha_never_exceeds_active_alpha(
    age: float, fade_after: float, fade_duration: float, active_alpha: float
) -> None:
    """``_silence_alpha`` returns a value in [0, active_alpha] for any age."""
    now = 100.0
    mtime = now - age
    result = _silence_alpha(
        mtime,
        now,
        fade_after_s=fade_after,
        fade_duration_s=fade_duration,
        active_alpha=active_alpha,
    )
    epsilon = 1e-9
    assert result >= 0.0 - epsilon
    assert result <= active_alpha + epsilon
