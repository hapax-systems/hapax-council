"""Hypothesis property tests for L2: FusedContext, FreshnessGuard.

VetoChain and FallbackChain algebraic properties already live in test_governance.py (6 tests).
This file covers the gaps: FusedContext invariants and FreshnessGuard predicate correctness.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from agents.hapax_daimonion.governance import (
    FreshnessGuard,
    FreshnessRequirement,
    FusedContext,
    VetoChain,
)
from agents.hapax_daimonion.primitives import Stamped
from tests.hapax_daimonion.hypothesis_strategies import (
    st_fused_context,
    st_threshold_veto,
    st_veto_chain,
)


class TestFusedContextProperties:
    @given(ctx=st_fused_context())
    @settings(max_examples=200)
    def test_min_watermark_invariant(self, ctx):
        """min_watermark <= min(sample.watermark for all samples), or == trigger_time if empty."""
        if ctx.samples:
            min_sample_wm = min(s.watermark for s in ctx.samples.values())
            assert ctx.min_watermark <= min_sample_wm + 1e-9
        else:
            assert ctx.min_watermark == ctx.trigger_time

    @given(ctx=st_fused_context())
    @settings(max_examples=200)
    def test_frozen(self, ctx):
        """FusedContext is frozen — attribute assignment raises AttributeError."""
        try:
            ctx.trigger_time = 999.0  # type: ignore[misc]
            raise AssertionError("Should have raised AttributeError")
        except AttributeError:
            pass

    @given(ctx=st_fused_context(behavior_names=["a", "b"]))
    @settings(max_examples=200)
    def test_samples_immutable(self, ctx):
        """FusedContext.samples rejects mutation."""
        try:
            ctx.samples["injected"] = Stamped(0, 0.0)  # type: ignore[index]
            raise AssertionError("Should have raised TypeError")
        except TypeError:
            pass


class TestFreshnessGuardProperties:
    @given(
        wm=st.floats(allow_nan=False, allow_infinity=False, min_value=0.0, max_value=1e6),
        max_staleness=st.floats(
            min_value=0.01, max_value=100.0, allow_nan=False, allow_infinity=False
        ),
        extra_staleness=st.floats(
            min_value=0.001, max_value=100.0, allow_nan=False, allow_infinity=False
        ),
    )
    @settings(max_examples=200)
    def test_stale_detection(self, wm, max_staleness, extra_staleness):
        """now - watermark > max_staleness implies not fresh_enough."""
        now = wm + max_staleness + extra_staleness
        ctx = FusedContext(
            trigger_time=now,
            trigger_value=None,
            samples={"sig": Stamped(0.5, wm)},
            min_watermark=wm,
        )
        guard = FreshnessGuard([FreshnessRequirement("sig", max_staleness)])
        result = guard.check(ctx, now)
        assert not result.fresh_enough

    @given(
        wm=st.floats(allow_nan=False, allow_infinity=False, min_value=0.0, max_value=1e6),
        max_staleness=st.floats(
            min_value=0.01, max_value=100.0, allow_nan=False, allow_infinity=False
        ),
        fraction=st.floats(min_value=0.0, max_value=0.99, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_fresh_acceptance(self, wm, max_staleness, fraction):
        """now - watermark < max_staleness implies fresh_enough."""
        now = wm + max_staleness * fraction
        ctx = FusedContext(
            trigger_time=now,
            trigger_value=None,
            samples={"sig": Stamped(0.5, wm)},
            min_watermark=wm,
        )
        guard = FreshnessGuard([FreshnessRequirement("sig", max_staleness)])
        result = guard.check(ctx, now)
        assert result.fresh_enough

    @given(
        max_staleness=st.floats(
            min_value=0.01, max_value=100.0, allow_nan=False, allow_infinity=False
        ),
        now=st.floats(allow_nan=False, allow_infinity=False, min_value=0.0, max_value=1e6),
    )
    @settings(max_examples=200)
    def test_missing_behavior_always_stale(self, max_staleness, now):
        """Requirement for absent behavior always produces a violation."""
        ctx = FusedContext(trigger_time=now, trigger_value=None)
        guard = FreshnessGuard([FreshnessRequirement("absent", max_staleness)])
        result = guard.check(ctx, now)
        assert not result.fresh_enough
        assert any("not present" in v for v in result.violations)


class TestVetoChainDenyWins:
    @given(
        chain=st_veto_chain(min_vetoes=1, max_vetoes=3),
        extra=st_threshold_veto(),
        context=st.integers(min_value=-1000, max_value=1000),
    )
    @settings(max_examples=200)
    def test_deny_wins_monotonicity(self, chain, extra, context):
        """If chain denies context, then (chain | extra_veto) also denies."""
        result_before = chain.evaluate(context)
        extended = chain | VetoChain([extra])
        result_after = extended.evaluate(context)
        if not result_before.allowed:
            assert not result_after.allowed
