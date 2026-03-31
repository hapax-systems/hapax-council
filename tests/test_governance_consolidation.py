"""Tests for governance consolidation fixes."""

from shared.governance.primitives import (
    Candidate,
    FallbackChain,
    Veto,
    VetoChain,
)


def test_fallback_chain_evaluates_nested_veto_chain():
    """Candidate with a denying veto_chain should be skipped."""
    deny_chain: VetoChain[str] = VetoChain([Veto("always_deny", lambda _ctx: False, axiom="test")])
    chain: FallbackChain[str, str] = FallbackChain(
        [
            Candidate("vetoed", lambda _ctx: True, "action_a", veto_chain=deny_chain),
            Candidate("allowed", lambda _ctx: True, "action_b"),
        ],
        default="fallback",
    )
    result = chain.select("any_context")
    assert result.action == "action_b"
    assert result.selected_by == "allowed"


def test_fallback_chain_nested_veto_allows():
    """Candidate with an allowing veto_chain should be selected."""
    allow_chain: VetoChain[str] = VetoChain([Veto("always_allow", lambda _ctx: True)])
    chain: FallbackChain[str, str] = FallbackChain(
        [Candidate("gated", lambda _ctx: True, "action_a", veto_chain=allow_chain)],
        default="fallback",
    )
    result = chain.select("any_context")
    assert result.action == "action_a"
    assert result.selected_by == "gated"
