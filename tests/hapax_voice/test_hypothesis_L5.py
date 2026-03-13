"""Hypothesis property tests for L5: SuppressionField, TimelineMapping, MusicalPosition."""

from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agents.hapax_voice.musical_position import musical_position
from agents.hapax_voice.suppression import SuppressionField, effective_threshold
from agents.hapax_voice.timeline import TimelineMapping
from tests.hapax_voice.hypothesis_strategies import (
    small_floats,
    st_suppression_config,
    st_timeline_mapping,
)


class TestTimelineMappingProperties:
    @given(
        mapping=st_timeline_mapping(playing=True),
        t=st.floats(allow_nan=False, allow_infinity=False, min_value=0.0, max_value=1e6),
    )
    @settings(max_examples=200)
    def test_invertibility(self, mapping, t):
        """time_at_beat(beat_at_time(t)) ≈ t when PLAYING."""
        beat = mapping.beat_at_time(t)
        t_back = mapping.time_at_beat(beat)
        assert math.isclose(t_back, t, rel_tol=1e-9, abs_tol=1e-9)

    @given(
        mapping=st_timeline_mapping(playing=False),
        t=st.floats(allow_nan=False, allow_infinity=False, min_value=0.0, max_value=1e6),
    )
    @settings(max_examples=200)
    def test_stopped_freezes_beat(self, mapping, t):
        """When STOPPED, beat_at_time returns reference_beat for any t."""
        assert mapping.beat_at_time(t) == mapping.reference_beat

    @given(
        mapping=st_timeline_mapping(playing=False),
        b=st.floats(allow_nan=False, allow_infinity=False, min_value=0.0, max_value=1e4),
    )
    @settings(max_examples=200)
    def test_stopped_freezes_time(self, mapping, b):
        """When STOPPED, time_at_beat returns reference_time for any beat."""
        assert mapping.time_at_beat(b) == mapping.reference_time

    @given(
        bad_tempo=st.floats(allow_nan=False, allow_infinity=False, min_value=-1e6, max_value=0.0),
    )
    @settings(max_examples=200)
    def test_invalid_tempo_rejected(self, bad_tempo):
        """tempo <= 0 raises ValueError."""
        with pytest.raises(ValueError, match="Tempo must be positive"):
            TimelineMapping(reference_time=0.0, reference_beat=0.0, tempo=bad_tempo)


class TestSuppressionFieldProperties:
    @given(
        config=st_suppression_config(),
        targets=st.lists(small_floats, min_size=1, max_size=5),
        dt=st.floats(min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100, deadline=None)
    def test_bounded(self, config, targets, dt):
        """Value always in [0, 1] after any sequence of set_target + tick."""
        attack, release, initial = config
        sf = SuppressionField(attack_s=attack, release_s=release, initial=initial)
        t = 0.0
        for target in targets:
            sf.set_target(target, t)
            for _ in range(20):
                t += dt
                val = sf.tick(t)
                assert -1e-9 <= val <= 1.0 + 1e-9

    @given(
        config=st_suppression_config(),
        target=small_floats,
        dt=st.floats(min_value=0.01, max_value=0.5, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100, deadline=None)
    def test_rate_bounded(self, config, target, dt):
        """Rate of change bounded by 1/attack_s (rising) or 1/release_s (falling)."""
        attack, release, initial = config
        sf = SuppressionField(attack_s=attack, release_s=release, initial=initial)
        sf.set_target(target, 0.0)

        t = 0.0
        prev_val = sf.tick(t)  # First tick establishes reference
        for _ in range(30):
            t += dt
            val = sf.tick(t)
            delta = abs(val - prev_val)
            max_rate = max(1.0 / attack, 1.0 / release)
            assert delta <= max_rate * dt + 1e-9
            prev_val = val

    @given(
        config=st_suppression_config(),
        target=small_floats,
    )
    @settings(max_examples=100, deadline=None)
    def test_convergence(self, config, target):
        """After sufficient ticks, value reaches target within epsilon."""
        attack, release, initial = config
        sf = SuppressionField(attack_s=attack, release_s=release, initial=initial)
        sf.set_target(target, 0.0)

        # Tick enough time for full ramp (max of attack and release * 2 for safety)
        total_time = max(attack, release) * 2.0
        t = 0.0
        steps = 100
        dt = total_time / steps
        for _ in range(steps):
            t += dt
            sf.tick(t)

        assert math.isclose(sf.value, target, abs_tol=1e-6)

    @given(
        base=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        s1=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        s2=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_effective_threshold_monotonic(self, base, s1, s2):
        """s1 <= s2 implies effective_threshold(base, s1) <= effective_threshold(base, s2)."""
        if s1 <= s2:
            assert effective_threshold(base, s1) <= effective_threshold(base, s2) + 1e-9


class TestMusicalPositionProperties:
    @given(
        beat=st.floats(min_value=0.0, max_value=1e4, allow_nan=False, allow_infinity=False),
        bpb=st.integers(min_value=1, max_value=16),
        bpp=st.integers(min_value=1, max_value=16),
        pps=st.integers(min_value=1, max_value=16),
    )
    @settings(max_examples=200)
    def test_decomposition_consistency(self, beat, bpb, bpp, pps):
        """beat == bar * beats_per_bar + beat_in_bar, etc."""
        pos = musical_position(beat, bpb, bpp, pps)
        assert pos.beat == beat
        assert math.isclose(pos.bar * bpb + pos.beat_in_bar, beat, rel_tol=1e-9, abs_tol=1e-9)
        assert pos.bar == pos.phrase * bpp + pos.bar_in_phrase
        assert pos.phrase == pos.section * pps + pos.phrase_in_section
