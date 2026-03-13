"""Hypothesis property tests for L0: Stamped[T]."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from agents.hapax_voice.primitives import Behavior, Stamped
from tests.hapax_voice.hypothesis_strategies import st_stamped, watermarks


class TestStampedProperties:
    @given(value=st.integers(), wm=watermarks)
    @settings(max_examples=200)
    def test_equality_reflexivity(self, value, wm):
        """Stamped(v, w) == Stamped(v, w) for all v, w."""
        a = Stamped(value=value, watermark=wm)
        b = Stamped(value=value, watermark=wm)
        assert a == b

    @given(s=st_stamped())
    @settings(max_examples=200)
    def test_frozen_immutability(self, s):
        """setattr on a Stamped always raises AttributeError."""
        try:
            s.value = 999  # type: ignore[misc]
            raise AssertionError("Should have raised AttributeError")
        except AttributeError:
            pass
        try:
            s.watermark = 999.0  # type: ignore[misc]
            raise AssertionError("Should have raised AttributeError")
        except AttributeError:
            pass

    @given(
        value=st.one_of(
            st.integers(),
            st.text(max_size=20),
            st.none(),
            st.floats(allow_nan=False, allow_infinity=False),
            st.lists(st.integers(), max_size=5),
        ),
        wm=watermarks,
    )
    @settings(max_examples=200)
    def test_any_type_accepted(self, value, wm):
        """Construction succeeds for any value type with any finite watermark."""
        s = Stamped(value=value, watermark=wm)
        assert s.value == value or s.value is value
        assert s.watermark == wm

    @given(value=st.integers(), wm=watermarks)
    @settings(max_examples=200)
    def test_hash_consistency(self, value, wm):
        """Equal Stamped instances have equal hashes."""
        a = Stamped(value=value, watermark=wm)
        b = Stamped(value=value, watermark=wm)
        assert a == b
        assert hash(a) == hash(b)

    @given(value=st.integers(), wm=watermarks)
    @settings(max_examples=200)
    def test_composition_contract_to_L1(self, value, wm):
        """Behavior(v, w).sample() produces Stamped(v, w) — L0 is L1's output type."""
        b = Behavior(value, watermark=wm)
        s = b.sample()
        assert isinstance(s, Stamped)
        assert s.value == value
        assert s.watermark == wm
