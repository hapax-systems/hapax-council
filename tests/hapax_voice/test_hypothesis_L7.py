"""Hypothesis property tests for L7: compose_mc_governance, compose_obs_governance."""

from __future__ import annotations

from hypothesis import given, settings

from agents.hapax_voice.governance import FusedContext, Veto, VetoChain, VetoResult
from agents.hapax_voice.mc_governance import (
    MCConfig,
    build_mc_fallback_chain,
    build_mc_veto_chain,
)
from tests.hapax_voice.hypothesis_strategies import st_mc_fused_context


class TestMCGovernanceProperties:
    @given(ctx=st_mc_fused_context())
    @settings(max_examples=100)
    def test_veto_chain_produces_valid_result(self, ctx):
        """build_mc_veto_chain().evaluate(ctx) returns valid VetoResult for any FusedContext."""
        chain = build_mc_veto_chain()
        result = chain.evaluate(ctx)
        assert isinstance(result, VetoResult)
        assert isinstance(result.allowed, bool)
        if not result.allowed:
            assert len(result.denied_by) > 0

    @given(ctx=st_mc_fused_context())
    @settings(max_examples=100)
    def test_deny_wins_monotonicity(self, ctx):
        """Adding a restrictive veto to MC chain never allows previously denied contexts."""
        chain = build_mc_veto_chain()
        result_before = chain.evaluate(ctx)

        # Add an extra always-deny veto
        extra = Veto[FusedContext](name="extra_deny", predicate=lambda _: False)
        extended = chain | VetoChain([extra])
        result_after = extended.evaluate(ctx)

        if not result_before.allowed:
            assert not result_after.allowed
        # The extra veto should always deny
        assert not result_after.allowed

    @given(ctx=st_mc_fused_context())
    @settings(max_examples=100)
    def test_fallback_determinism(self, ctx):
        """Same FusedContext always produces same FallbackChain selection."""
        chain = build_mc_fallback_chain()
        result1 = chain.select(ctx)
        result2 = chain.select(ctx)
        assert result1.action == result2.action
        assert result1.selected_by == result2.selected_by

    @given(ctx=st_mc_fused_context())
    @settings(max_examples=100)
    def test_veto_chain_with_custom_config(self, ctx):
        """VetoChain with custom thresholds still produces valid VetoResult."""
        cfg = MCConfig(
            speech_vad_threshold=0.3,
            energy_min_threshold=0.5,
            spacing_cooldown_s=2.0,
        )
        chain = build_mc_veto_chain(cfg)
        result = chain.evaluate(ctx)
        assert isinstance(result, VetoResult)

    @given(ctx=st_mc_fused_context())
    @settings(max_examples=100)
    def test_fallback_selects_from_known_actions(self, ctx):
        """FallbackChain always selects a known MCAction or default."""
        from agents.hapax_voice.mc_governance import MCAction

        chain = build_mc_fallback_chain()
        result = chain.select(ctx)
        valid_actions = {MCAction.VOCAL_THROW, MCAction.AD_LIB, MCAction.SILENCE}
        assert result.action in valid_actions
