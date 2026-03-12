"""Tests for Detective primitives: VetoChain, FallbackChain, FreshnessGuard, FusedContext."""

from __future__ import annotations

import time

import pytest
from hypothesis import given
from hypothesis import strategies as st

from agents.hapax_voice.governance import (
    Candidate,
    FallbackChain,
    FreshnessGuard,
    FreshnessRequirement,
    FusedContext,
    GatedResult,
    Veto,
    VetoChain,
    VetoResult,
)
from agents.hapax_voice.primitives import Stamped

# ------------------------------------------------------------------
# FusedContext
# ------------------------------------------------------------------


class TestFusedContext:
    def test_get_sample(self):
        ctx = FusedContext(
            trigger_time=1.0,
            trigger_value=None,
            samples={"vad": Stamped(0.8, 1.0), "face": Stamped(True, 0.9)},
            min_watermark=0.9,
        )
        assert ctx.get_sample("vad").value == 0.8
        assert ctx.get_sample("face").value is True

    def test_get_sample_missing_raises(self):
        ctx = FusedContext(trigger_time=1.0, trigger_value=None)
        with pytest.raises(KeyError):
            ctx.get_sample("nonexistent")

    def test_min_watermark(self):
        ctx = FusedContext(
            trigger_time=5.0,
            trigger_value="tick",
            samples={"a": Stamped(1, 3.0), "b": Stamped(2, 5.0)},
            min_watermark=3.0,
        )
        assert ctx.min_watermark == 3.0

    def test_frozen(self):
        ctx = FusedContext(trigger_time=1.0, trigger_value=None)
        with pytest.raises(AttributeError):
            ctx.trigger_time = 2.0  # type: ignore[misc]


# ------------------------------------------------------------------
# VetoChain
# ------------------------------------------------------------------


class TestVetoChain:
    def test_empty_chain_allows(self):
        chain: VetoChain[int] = VetoChain()
        result = chain.evaluate(42)
        assert result.allowed is True
        assert result.denied_by == ()

    def test_single_allow(self):
        chain: VetoChain[int] = VetoChain([Veto("positive", predicate=lambda x: x > 0)])
        assert chain.evaluate(5).allowed is True

    def test_single_deny(self):
        chain: VetoChain[int] = VetoChain([Veto("positive", predicate=lambda x: x > 0)])
        result = chain.evaluate(-1)
        assert result.allowed is False
        assert result.denied_by == ("positive",)

    def test_multiple_vetoes_all_allow(self):
        chain: VetoChain[int] = VetoChain(
            [
                Veto("positive", predicate=lambda x: x > 0),
                Veto("small", predicate=lambda x: x < 100),
            ]
        )
        assert chain.evaluate(50).allowed is True

    def test_any_denial_blocks(self):
        chain: VetoChain[int] = VetoChain(
            [
                Veto("positive", predicate=lambda x: x > 0),
                Veto("small", predicate=lambda x: x < 100),
            ]
        )
        result = chain.evaluate(200)
        assert result.allowed is False
        assert "small" in result.denied_by

    def test_multiple_denials_reported(self):
        chain: VetoChain[int] = VetoChain(
            [
                Veto("positive", predicate=lambda x: x > 0),
                Veto("even", predicate=lambda x: x % 2 == 0),
            ]
        )
        result = chain.evaluate(-3)
        assert result.allowed is False
        assert set(result.denied_by) == {"positive", "even"}

    def test_commutativity(self):
        """Order of vetoes doesn't affect outcome."""
        v1 = Veto("a", predicate=lambda x: x > 0)
        v2 = Veto("b", predicate=lambda x: x < 100)
        chain_ab: VetoChain[int] = VetoChain([v1, v2])
        chain_ba: VetoChain[int] = VetoChain([v2, v1])
        for val in [-5, 50, 200]:
            assert chain_ab.evaluate(val).allowed == chain_ba.evaluate(val).allowed

    def test_all_vetoes_deny(self):
        chain: VetoChain[int] = VetoChain(
            [
                Veto("positive", predicate=lambda x: x > 0),
                Veto("even", predicate=lambda x: x % 2 == 0),
                Veto("small", predicate=lambda x: x < 10),
            ]
        )
        result = chain.evaluate(-3)
        assert result.allowed is False
        assert set(result.denied_by) == {"positive", "even"}

    def test_monotonic_safety(self):
        """Adding a veto can only restrict, never relax."""
        chain: VetoChain[int] = VetoChain([Veto("positive", predicate=lambda x: x > 0)])
        assert chain.evaluate(5).allowed is True
        chain.add(Veto("odd", predicate=lambda x: x % 2 != 0))
        # 5 is odd and positive → still allowed
        assert chain.evaluate(5).allowed is True
        # 4 was allowed, now denied
        assert chain.evaluate(4).allowed is False

    def test_add_veto(self):
        chain: VetoChain[int] = VetoChain()
        assert chain.evaluate(0).allowed is True
        chain.add(Veto("positive", predicate=lambda x: x > 0))
        assert chain.evaluate(0).allowed is False

    def test_axiom_field(self):
        v = Veto("no_multi_user", predicate=lambda _: True, axiom="single_user")
        assert v.axiom == "single_user"

    def test_description_field(self):
        v = Veto("test", predicate=lambda _: True, description="Blocks multi-user access")
        assert v.description == "Blocks multi-user access"

    def test_description_default_empty(self):
        v = Veto("test", predicate=lambda _: True)
        assert v.description == ""

    def test_axiom_ids_on_veto_result(self):
        chain: VetoChain[int] = VetoChain(
            [
                Veto("a", predicate=lambda x: x > 0, axiom="single_user"),
                Veto("b", predicate=lambda x: x > 0, axiom="exec_fn"),
                Veto("c", predicate=lambda x: x > 0),  # no axiom
            ]
        )
        result = chain.evaluate(-1)
        assert result.allowed is False
        assert set(result.axiom_ids) == {"single_user", "exec_fn"}

    def test_axiom_ids_empty_when_allowed(self):
        chain: VetoChain[int] = VetoChain(
            [Veto("a", predicate=lambda x: x > 0, axiom="single_user")]
        )
        result = chain.evaluate(5)
        assert result.axiom_ids == ()

    def test_or_composition(self):
        chain_a: VetoChain[int] = VetoChain([Veto("positive", predicate=lambda x: x > 0)])
        chain_b: VetoChain[int] = VetoChain([Veto("small", predicate=lambda x: x < 100)])
        combined = chain_a | chain_b
        assert len(combined.vetoes) == 2
        assert combined.evaluate(50).allowed is True
        assert combined.evaluate(-1).allowed is False
        assert combined.evaluate(200).allowed is False

    def test_or_does_not_mutate(self):
        chain_a: VetoChain[int] = VetoChain([Veto("a", predicate=lambda _: True)])
        chain_b: VetoChain[int] = VetoChain([Veto("b", predicate=lambda _: True)])
        _ = chain_a | chain_b
        assert len(chain_a.vetoes) == 1
        assert len(chain_b.vetoes) == 1

    def test_gate_allowed(self):
        chain: VetoChain[int] = VetoChain([Veto("positive", predicate=lambda x: x > 0)])
        gated = chain.gate(5, "payload")
        assert isinstance(gated, GatedResult)
        assert gated.value == "payload"
        assert gated.veto_result.allowed is True

    def test_gate_denied(self):
        chain: VetoChain[int] = VetoChain([Veto("positive", predicate=lambda x: x > 0)])
        gated = chain.gate(-1, "payload")
        assert gated.value is None
        assert gated.veto_result.allowed is False
        assert "positive" in gated.veto_result.denied_by


# ------------------------------------------------------------------
# VetoChain property-based tests (Hypothesis)
# ------------------------------------------------------------------


def _make_threshold_veto(name: str, threshold: int) -> Veto[int]:
    """Helper: veto that allows values > threshold."""
    return Veto(name, predicate=lambda x, t=threshold: x > t)


class TestVetoChainProperties:
    """Hypothesis property-based tests for VetoChain algebraic properties."""

    @given(st.integers(min_value=-1000, max_value=1000))
    def test_or_associativity(self, val: int):
        """(a | b) | c ≡ a | (b | c) in evaluation outcome."""
        a: VetoChain[int] = VetoChain([_make_threshold_veto("a", 0)])
        b: VetoChain[int] = VetoChain([_make_threshold_veto("b", 10)])
        c: VetoChain[int] = VetoChain([_make_threshold_veto("c", -10)])
        left = (a | b) | c
        right = a | (b | c)
        assert left.evaluate(val).allowed == right.evaluate(val).allowed

    @given(st.integers(min_value=-1000, max_value=1000))
    def test_or_identity(self, val: int):
        """a | empty ≡ a in evaluation outcome."""
        a: VetoChain[int] = VetoChain([_make_threshold_veto("a", 0)])
        empty: VetoChain[int] = VetoChain()
        combined = a | empty
        assert combined.evaluate(val).allowed == a.evaluate(val).allowed

    @given(st.integers(min_value=-1000, max_value=1000))
    def test_or_monotonic(self, val: int):
        """Composing chains can only restrict, never relax."""
        a: VetoChain[int] = VetoChain([_make_threshold_veto("a", 0)])
        b: VetoChain[int] = VetoChain([_make_threshold_veto("b", 50)])
        combined = a | b
        # If combined allows, each component must also allow
        if combined.evaluate(val).allowed:
            assert a.evaluate(val).allowed
            assert b.evaluate(val).allowed

    @given(
        st.integers(min_value=-100, max_value=100),
        st.integers(min_value=-100, max_value=100),
    )
    def test_closure(self, threshold_a: int, threshold_b: int):
        """| always produces a valid VetoChain."""
        a: VetoChain[int] = VetoChain([_make_threshold_veto("a", threshold_a)])
        b: VetoChain[int] = VetoChain([_make_threshold_veto("b", threshold_b)])
        combined = a | b
        assert isinstance(combined, VetoChain)
        # Must be evaluable without error
        result = combined.evaluate(0)
        assert isinstance(result, VetoResult)

    @given(st.integers(min_value=-1000, max_value=1000))
    def test_idempotence(self, val: int):
        """a | a ≡ a in evaluation outcome (just redundant denials)."""
        a: VetoChain[int] = VetoChain([_make_threshold_veto("a", 0)])
        doubled = a | a
        assert doubled.evaluate(val).allowed == a.evaluate(val).allowed


# ------------------------------------------------------------------
# FallbackChain property-based tests (Hypothesis)
# ------------------------------------------------------------------


class TestFallbackChainProperties:
    @given(st.integers(min_value=-1000, max_value=1000))
    def test_or_preserves_priority(self, val: int):
        """a | b: self's candidates evaluate before other's."""
        a: FallbackChain[int, str] = FallbackChain(
            [Candidate("high", predicate=lambda x: x > 100, action="high")],
            default="a_default",
        )
        b: FallbackChain[int, str] = FallbackChain(
            [Candidate("low", predicate=lambda x: x > 0, action="low")],
            default="b_default",
        )
        combined = a | b
        result = combined.select(val)
        # If 'high' matches, it must be selected (it comes first)
        if val > 100:
            assert result.selected_by == "high"


# ------------------------------------------------------------------
# FallbackChain
# ------------------------------------------------------------------


class TestFallbackChain:
    def test_default_when_no_candidates(self):
        chain: FallbackChain[int, str] = FallbackChain(candidates=[], default="idle")
        result = chain.select(42)
        assert result.action == "idle"
        assert result.selected_by == "default"

    def test_first_eligible_wins(self):
        chain: FallbackChain[int, str] = FallbackChain(
            candidates=[
                Candidate("high", predicate=lambda x: x > 100, action="high_action"),
                Candidate("medium", predicate=lambda x: x > 10, action="medium_action"),
            ],
            default="low_action",
        )
        assert chain.select(200).action == "high_action"
        assert chain.select(200).selected_by == "high"

    def test_second_candidate_when_first_fails(self):
        chain: FallbackChain[int, str] = FallbackChain(
            candidates=[
                Candidate("high", predicate=lambda x: x > 100, action="high_action"),
                Candidate("medium", predicate=lambda x: x > 10, action="medium_action"),
            ],
            default="low_action",
        )
        result = chain.select(50)
        assert result.action == "medium_action"
        assert result.selected_by == "medium"

    def test_default_when_none_eligible(self):
        chain: FallbackChain[int, str] = FallbackChain(
            candidates=[
                Candidate("high", predicate=lambda x: x > 100, action="high_action"),
            ],
            default="fallback",
        )
        result = chain.select(5)
        assert result.action == "fallback"
        assert result.selected_by == "default"

    def test_determinism(self):
        """Same context always produces same selection."""
        chain: FallbackChain[int, str] = FallbackChain(
            candidates=[
                Candidate("a", predicate=lambda x: x > 50, action="a"),
                Candidate("b", predicate=lambda x: x > 10, action="b"),
            ],
            default="c",
        )
        for _ in range(10):
            assert chain.select(75).action == "a"
            assert chain.select(25).action == "b"
            assert chain.select(5).action == "c"

    def test_or_composition(self):
        chain_a: FallbackChain[int, str] = FallbackChain(
            [Candidate("high", predicate=lambda x: x > 100, action="high")],
            default="a_default",
        )
        chain_b: FallbackChain[int, str] = FallbackChain(
            [Candidate("low", predicate=lambda x: x > 0, action="low")],
            default="b_default",
        )
        combined = chain_a | chain_b
        assert combined.select(200).action == "high"
        assert combined.select(50).action == "low"
        assert combined.select(-1).action == "a_default"  # self's default wins

    def test_or_does_not_mutate(self):
        chain_a: FallbackChain[int, str] = FallbackChain(
            [Candidate("a", predicate=lambda _: True, action="a")], default="d"
        )
        chain_b: FallbackChain[int, str] = FallbackChain(
            [Candidate("b", predicate=lambda _: True, action="b")], default="d"
        )
        _ = chain_a | chain_b
        assert len(chain_a.candidates) == 1
        assert len(chain_b.candidates) == 1


# ------------------------------------------------------------------
# FreshnessGuard
# ------------------------------------------------------------------


class TestFreshnessGuard:
    def _make_context(self, watermarks: dict[str, float]) -> FusedContext:
        samples = {name: Stamped(value=0, watermark=wm) for name, wm in watermarks.items()}
        return FusedContext(
            trigger_time=0.0,
            trigger_value=None,
            samples=samples,
            min_watermark=min(watermarks.values()) if watermarks else 0.0,
        )

    def test_all_fresh(self):
        guard = FreshnessGuard(
            [
                FreshnessRequirement("vad", max_staleness_s=1.0),
                FreshnessRequirement("face", max_staleness_s=2.0),
            ]
        )
        now = 10.0
        ctx = self._make_context({"vad": 9.5, "face": 9.0})
        result = guard.check(ctx, now)
        assert result.fresh_enough is True
        assert result.violations == ()

    def test_one_stale(self):
        guard = FreshnessGuard(
            [
                FreshnessRequirement("vad", max_staleness_s=1.0),
                FreshnessRequirement("face", max_staleness_s=2.0),
            ]
        )
        now = 10.0
        ctx = self._make_context({"vad": 8.0, "face": 9.0})
        result = guard.check(ctx, now)
        assert result.fresh_enough is False
        assert len(result.violations) == 1
        assert "vad" in result.violations[0]

    def test_multiple_stale(self):
        guard = FreshnessGuard(
            [
                FreshnessRequirement("vad", max_staleness_s=1.0),
                FreshnessRequirement("face", max_staleness_s=1.0),
            ]
        )
        now = 10.0
        ctx = self._make_context({"vad": 5.0, "face": 5.0})
        result = guard.check(ctx, now)
        assert result.fresh_enough is False
        assert len(result.violations) == 2

    def test_empty_guard_passes(self):
        guard = FreshnessGuard()
        ctx = FusedContext(trigger_time=0.0, trigger_value=None)
        assert guard.check(ctx, 100.0).fresh_enough is True

    def test_freshness_exact_boundary(self):
        guard = FreshnessGuard([FreshnessRequirement("vad", max_staleness_s=1.0)])
        now = 10.0
        # Exactly at boundary — should pass
        ctx_exact = self._make_context({"vad": 9.0})
        assert guard.check(ctx_exact, now).fresh_enough is True
        # Just over boundary — should fail
        ctx_over = self._make_context({"vad": 8.999})
        assert guard.check(ctx_over, now).fresh_enough is False

    def test_freshness_guard_missing_behavior(self):
        guard = FreshnessGuard([FreshnessRequirement("nonexistent", max_staleness_s=1.0)])
        ctx = FusedContext(trigger_time=0.0, trigger_value=None)
        result = guard.check(ctx, 10.0)
        assert result.fresh_enough is False
        assert len(result.violations) == 1
        assert "nonexistent" in result.violations[0]
        assert "not present" in result.violations[0]

    def test_composable_with_veto_chain(self):
        """FreshnessGuard can be used as a veto predicate."""
        guard = FreshnessGuard([FreshnessRequirement("energy", max_staleness_s=0.1)])

        def freshness_veto(ctx_and_now: tuple) -> bool:
            ctx, now = ctx_and_now
            return guard.check(ctx, now).fresh_enough

        chain: VetoChain[tuple] = VetoChain(
            [
                Veto("freshness", predicate=freshness_veto),
            ]
        )

        fresh_ctx = FusedContext(
            trigger_time=10.0,
            trigger_value=None,
            samples={"energy": Stamped(0.5, 9.95)},
            min_watermark=9.95,
        )
        assert chain.evaluate((fresh_ctx, 10.0)).allowed is True

        stale_ctx = FusedContext(
            trigger_time=10.0,
            trigger_value=None,
            samples={"energy": Stamped(0.5, 5.0)},
            min_watermark=5.0,
        )
        assert chain.evaluate((stale_ctx, 10.0)).allowed is False


# ------------------------------------------------------------------
# Governor integration (VetoChain + FallbackChain)
# ------------------------------------------------------------------


class TestGovernorGovernance:
    """Verify Governor uses governance types internally."""

    def test_governor_has_veto_chain(self):
        from agents.hapax_voice.governor import PipelineGovernor

        gov = PipelineGovernor()
        assert isinstance(gov.veto_chain, VetoChain)
        assert len(gov.veto_chain.vetoes) == 2

    def test_governor_records_veto_result(self):
        from agents.hapax_voice.governor import PipelineGovernor
        from agents.hapax_voice.perception import EnvironmentState

        gov = PipelineGovernor()
        state = EnvironmentState(timestamp=time.monotonic(), operator_present=True, face_count=1)
        gov.evaluate(state)
        assert gov.last_veto_result is not None
        assert gov.last_veto_result.allowed is True

    def test_governor_veto_on_production(self):
        from agents.hapax_voice.governor import PipelineGovernor
        from agents.hapax_voice.perception import EnvironmentState

        gov = PipelineGovernor()
        state = EnvironmentState(
            timestamp=time.monotonic(), activity_mode="production", operator_present=True
        )
        result = gov.evaluate(state)
        assert result == "pause"
        assert gov.last_veto_result is not None
        assert "activity_mode" in gov.last_veto_result.denied_by

    def test_governor_records_selection(self):
        from agents.hapax_voice.governor import PipelineGovernor
        from agents.hapax_voice.perception import EnvironmentState

        gov = PipelineGovernor()
        state = EnvironmentState(timestamp=time.monotonic(), operator_present=True, face_count=1)
        gov.evaluate(state)
        assert gov.last_selected is not None
        assert gov.last_selected.action == "process"
        assert gov.last_selected.selected_by == "default"
