"""Hypothesis property tests for L3: with_latest_from combinator."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from agents.hapax_voice.combinator import with_latest_from
from agents.hapax_voice.governance import FusedContext, VetoChain
from agents.hapax_voice.primitives import Behavior, Event


class TestWithLatestFromProperties:
    @given(
        trigger_times=st.lists(
            st.floats(allow_nan=False, allow_infinity=False, min_value=0.0, max_value=1e6),
            min_size=1,
            max_size=10,
        ),
        init_wm=st.floats(allow_nan=False, allow_infinity=False, min_value=0.0, max_value=1e6),
    )
    @settings(max_examples=100)
    def test_output_fires_only_at_trigger_times(self, trigger_times, init_wm):
        """Output timestamps exactly match trigger emission timestamps."""
        trigger: Event[None] = Event()
        b = Behavior(0, watermark=init_wm)
        output = with_latest_from(trigger, {"val": b})

        received: list[float] = []
        output.subscribe(lambda ts, ctx: received.append(ts))

        for ts in trigger_times:
            trigger.emit(ts, None)

        assert received == trigger_times

    @given(
        values=st.lists(st.integers(), min_size=1, max_size=10),
        init_wm=st.floats(allow_nan=False, allow_infinity=False, min_value=0.0, max_value=100.0),
    )
    @settings(max_examples=100)
    def test_samples_reflect_latest_values(self, values, init_wm):
        """Each output context samples the latest behavior value at trigger time."""
        trigger: Event[None] = Event()
        b = Behavior(values[0], watermark=init_wm)
        output = with_latest_from(trigger, {"val": b})

        received: list[FusedContext] = []
        output.subscribe(lambda ts, ctx: received.append(ctx))

        ts = init_wm
        for v in values:
            ts += 1.0
            b.update(v, ts)
            trigger.emit(ts, None)

        for i, ctx in enumerate(received):
            assert ctx.get_sample("val").value == values[i]

    @given(
        n_behaviors=st.integers(min_value=1, max_value=5),
        trigger_ts=st.floats(allow_nan=False, allow_infinity=False, min_value=100.0, max_value=1e6),
    )
    @settings(max_examples=200)
    def test_min_watermark_correct(self, n_behaviors, trigger_ts):
        """min_watermark == min(sample.watermarks) when behaviors present."""
        trigger: Event[None] = Event()
        behaviors = {}
        for i in range(n_behaviors):
            wm = trigger_ts - (i + 1) * 10.0  # Spread watermarks
            behaviors[f"b{i}"] = Behavior(i, watermark=wm)

        output = with_latest_from(trigger, behaviors)
        received: list[FusedContext] = []
        output.subscribe(lambda ts, ctx: received.append(ctx))

        trigger.emit(trigger_ts, None)
        ctx = received[0]

        expected_min = min(s.watermark for s in ctx.samples.values())
        assert ctx.min_watermark == expected_min

    @given(
        n_updates=st.integers(min_value=1, max_value=20),
        init_wm=st.floats(allow_nan=False, allow_infinity=False, min_value=0.0, max_value=1e6),
    )
    @settings(max_examples=100)
    def test_behavior_update_no_output(self, n_updates, init_wm):
        """N behavior updates with 0 trigger emissions yield 0 outputs."""
        trigger: Event[None] = Event()
        b = Behavior(0, watermark=init_wm)
        output = with_latest_from(trigger, {"val": b})

        received: list[FusedContext] = []
        output.subscribe(lambda ts, ctx: received.append(ctx))

        ts = init_wm
        for i in range(n_updates):
            ts += 1.0
            b.update(i, ts)

        assert len(received) == 0

    @given(
        init_wm=st.floats(allow_nan=False, allow_infinity=False, min_value=0.0, max_value=1e6),
    )
    @settings(max_examples=100)
    def test_composition_contract_to_L4(self, init_wm):
        """Output FusedContext is valid input to VetoChain.evaluate()."""
        trigger: Event[None] = Event()
        b = Behavior(0.5, watermark=init_wm)
        output = with_latest_from(trigger, {"val": b})

        received: list[FusedContext] = []
        output.subscribe(lambda ts, ctx: received.append(ctx))
        trigger.emit(init_wm + 1.0, None)

        ctx = received[0]
        chain: VetoChain[FusedContext] = VetoChain()
        result = chain.evaluate(ctx)
        assert result.allowed  # Empty chain allows everything
