"""Tests for governance primitives (VetoChain, FallbackChain)."""

from __future__ import annotations

import unittest

from agentgov.primitives import Candidate, FallbackChain, Veto, VetoChain


class TestVetoChain(unittest.TestCase):
    def test_empty_chain_allows(self):
        result = VetoChain().evaluate("any")
        assert result.allowed is True

    def test_single_veto_denies(self):
        chain = VetoChain([Veto("block", lambda x: False)])
        result = chain.evaluate("ctx")
        assert result.allowed is False
        assert "block" in result.denied_by

    def test_deny_wins(self):
        chain = VetoChain([Veto("allow", lambda x: True), Veto("deny", lambda x: False)])
        assert chain.evaluate("ctx").allowed is False

    def test_all_vetoes_evaluated(self):
        chain = VetoChain([Veto("a", lambda x: False), Veto("b", lambda x: False)])
        assert len(chain.evaluate("ctx").denied_by) == 2

    def test_axiom_ids_collected(self):
        chain = VetoChain([Veto("rule", lambda x: False, axiom="single_user")])
        assert "single_user" in chain.evaluate("ctx").axiom_ids

    def test_compose_with_or(self):
        a = VetoChain([Veto("a", lambda x: True)])
        b = VetoChain([Veto("b", lambda x: False)])
        assert (a | b).evaluate("ctx").allowed is False

    def test_gate_allowed(self):
        gated = VetoChain().gate("ctx", "value")
        assert gated.value == "value"

    def test_gate_denied(self):
        gated = VetoChain([Veto("block", lambda x: False)]).gate("ctx", "value")
        assert gated.value is None


class TestFallbackChain(unittest.TestCase):
    def test_default_when_no_candidates(self):
        result = FallbackChain([], default="idle").select("ctx")
        assert result.action == "idle"
        assert result.selected_by == "default"

    def test_first_eligible_wins(self):
        chain = FallbackChain(
            [
                Candidate("first", lambda x: True, "action_a"),
                Candidate("second", lambda x: True, "action_b"),
            ],
            default="idle",
        )
        assert chain.select("ctx").action == "action_a"

    def test_skips_ineligible(self):
        chain = FallbackChain(
            [Candidate("skip", lambda x: False, "nope"), Candidate("pick", lambda x: True, "yes")],
            default="idle",
        )
        assert chain.select("ctx").action == "yes"

    def test_compose_with_or(self):
        a = FallbackChain([Candidate("a", lambda x: False, "nope")], default="default_a")
        b = FallbackChain([Candidate("b", lambda x: True, "yes")], default="default_b")
        assert (a | b).select("ctx").action == "yes"
