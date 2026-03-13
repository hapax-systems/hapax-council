"""Hypothesis property tests for L1: Behavior[T], Event[T]."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agents.hapax_voice.governance import FusedContext
from agents.hapax_voice.primitives import Behavior, Event, Stamped
from tests.hapax_voice.hypothesis_strategies import st_monotonic_timestamps, watermarks


class TestBehaviorProperties:
    @given(data=st_monotonic_timestamps())
    @settings(max_examples=200)
    def test_watermark_monotonicity_accepted(self, data):
        """Any non-decreasing timestamp sequence is accepted by update()."""
        base_wm, timestamps = data
        b = Behavior(0, watermark=base_wm)
        for i, ts in enumerate(timestamps):
            b.update(i, ts)
        assert b.watermark == timestamps[-1]

    @given(
        wm=st.floats(allow_nan=False, allow_infinity=False, min_value=1.0, max_value=1e6),
        delta=st.floats(min_value=0.001, max_value=1e3, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_watermark_regression_rejected(self, wm, delta):
        """Any strictly decreasing timestamp raises ValueError."""
        b = Behavior(0, watermark=wm)
        with pytest.raises(ValueError, match="Watermark regression"):
            b.update(1, wm - delta)

    @given(data=st_monotonic_timestamps())
    @settings(max_examples=200)
    def test_sample_always_returns_stamped(self, data):
        """sample() returns Stamped matching current state after any update sequence."""
        base_wm, timestamps = data
        b = Behavior("init", watermark=base_wm)
        for i, ts in enumerate(timestamps):
            b.update(f"val_{i}", ts)
            s = b.sample()
            assert isinstance(s, Stamped)
            assert s.value == f"val_{i}"
            assert s.watermark == ts

    @given(
        value=st.integers(),
        init_wm=st.floats(allow_nan=False, allow_infinity=False, min_value=0.0, max_value=1e6),
        ts=st.floats(allow_nan=False, allow_infinity=False, min_value=0.0, max_value=1e6),
    )
    @settings(max_examples=200)
    def test_update_reflects_latest(self, value, init_wm, ts):
        """After update(v, ts), value == v and watermark == ts (if ts >= init_wm)."""
        if ts < init_wm:
            return  # Skip regression cases — tested separately
        b = Behavior(0, watermark=init_wm)
        b.update(value, ts)
        assert b.value == value
        assert b.watermark == ts

    @given(
        init_wm=st.floats(allow_nan=False, allow_infinity=False, min_value=0.0, max_value=1e6),
        value=st.integers(),
    )
    @settings(max_examples=200)
    def test_composition_contract_to_L2(self, init_wm, value):
        """Behavior.sample() result is valid as FusedContext.samples value."""
        b = Behavior(value, watermark=init_wm)
        s = b.sample()
        ctx = FusedContext(
            trigger_time=init_wm,
            trigger_value=None,
            samples={"test": s},
            min_watermark=s.watermark,
        )
        assert ctx.get_sample("test") == s


class TestEventProperties:
    @given(n=st.integers(min_value=0, max_value=20))
    @settings(max_examples=200)
    def test_subscriber_count_invariant(self, n):
        """After N subscribes, subscriber_count == N."""
        event: Event[int] = Event()
        unsubs = []
        for _ in range(n):
            unsubs.append(event.subscribe(lambda ts, v: None))
        assert event.subscriber_count == n

        # Unsubscribe half and verify
        half = n // 2
        for unsub in unsubs[:half]:
            unsub()
        assert event.subscriber_count == n - half

    @given(
        n=st.integers(min_value=1, max_value=10),
        ts=watermarks,
        value=st.integers(),
    )
    @settings(max_examples=100)
    def test_emit_delivers_to_all(self, n, ts, value):
        """Emitting to N subscribers delivers exactly N times."""
        event: Event[int] = Event()
        received: list[tuple[float, int]] = []
        for _ in range(n):
            event.subscribe(lambda t, v: received.append((t, v)))
        event.emit(ts, value)
        assert len(received) == n
        assert all(t == ts and v == value for t, v in received)

    @given(
        n_good=st.integers(min_value=1, max_value=5),
        n_bad=st.integers(min_value=1, max_value=5),
        ts=watermarks,
    )
    @settings(max_examples=100)
    def test_exception_isolation(self, n_good, n_bad, ts):
        """Failing subscribers do not prevent delivery to other subscribers."""
        event: Event[int] = Event()
        received: list[float] = []

        for _ in range(n_bad):
            event.subscribe(lambda t, v: (_ for _ in ()).throw(RuntimeError("boom")))
        for _ in range(n_good):
            event.subscribe(lambda t, v: received.append(t))

        event.emit(ts, 42)
        assert len(received) == n_good
