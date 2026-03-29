"""Tests for shared governance primitives."""

from __future__ import annotations

import unittest

from shared.governance import (
    Candidate,
    FallbackChain,
    Veto,
    VetoChain,
)


class TestVetoChain(unittest.TestCase):
    def test_empty_chain_allows(self):
        chain = VetoChain()
        result = chain.evaluate("any")
        assert result.allowed is True
        assert result.denied_by == ()

    def test_single_veto_allows(self):
        chain = VetoChain([Veto("check", lambda x: True)])
        assert chain.evaluate("ctx").allowed is True

    def test_single_veto_denies(self):
        chain = VetoChain([Veto("block", lambda x: False)])
        result = chain.evaluate("ctx")
        assert result.allowed is False
        assert "block" in result.denied_by

    def test_deny_wins(self):
        chain = VetoChain(
            [
                Veto("allow", lambda x: True),
                Veto("deny", lambda x: False),
            ]
        )
        assert chain.evaluate("ctx").allowed is False

    def test_all_vetoes_evaluated(self):
        chain = VetoChain(
            [
                Veto("a", lambda x: False),
                Veto("b", lambda x: False),
            ]
        )
        result = chain.evaluate("ctx")
        assert len(result.denied_by) == 2

    def test_axiom_ids_collected(self):
        chain = VetoChain(
            [
                Veto("rule", lambda x: False, axiom="single_user"),
            ]
        )
        result = chain.evaluate("ctx")
        assert "single_user" in result.axiom_ids

    def test_compose_with_or(self):
        a = VetoChain([Veto("a", lambda x: True)])
        b = VetoChain([Veto("b", lambda x: False)])
        combined = a | b
        assert combined.evaluate("ctx").allowed is False

    def test_gate_allowed(self):
        chain = VetoChain()
        gated = chain.gate("ctx", "value")
        assert gated.value == "value"
        assert gated.veto_result.allowed is True

    def test_gate_denied(self):
        chain = VetoChain([Veto("block", lambda x: False)])
        gated = chain.gate("ctx", "value")
        assert gated.value is None
        assert gated.veto_result.allowed is False


class TestFallbackChain(unittest.TestCase):
    def test_default_when_no_candidates(self):
        chain = FallbackChain([], default="idle")
        result = chain.select("ctx")
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
        result = chain.select("ctx")
        assert result.action == "action_a"
        assert result.selected_by == "first"

    def test_skips_ineligible(self):
        chain = FallbackChain(
            [
                Candidate("skip", lambda x: False, "nope"),
                Candidate("pick", lambda x: True, "yes"),
            ],
            default="idle",
        )
        result = chain.select("ctx")
        assert result.action == "yes"

    def test_compose_with_or(self):
        a = FallbackChain([Candidate("a", lambda x: False, "nope")], default="default_a")
        b = FallbackChain([Candidate("b", lambda x: True, "yes")], default="default_b")
        combined = a | b
        result = combined.select("ctx")
        assert result.action == "yes"
        assert result.selected_by == "b"
