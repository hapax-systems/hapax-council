"""Tests for Says monad."""

from __future__ import annotations

import unittest

from agentgov.consent_label import ConsentLabel
from agentgov.principal import Principal, PrincipalKind
from agentgov.says import Says


class TestSaysMonad(unittest.TestCase):
    def test_unit(self):
        p = Principal(id="hapax", kind=PrincipalKind.SOVEREIGN)
        s = Says.unit(p, 42)
        assert s.principal == p
        assert s.value == 42

    def test_map(self):
        p = Principal(id="hapax", kind=PrincipalKind.SOVEREIGN)
        s = Says.unit(p, 10).map(lambda x: x * 2)
        assert s.value == 20
        assert s.principal == p

    def test_bind_preserves_original_principal(self):
        p1 = Principal(id="hapax", kind=PrincipalKind.SOVEREIGN)
        p2 = Principal(
            id="agent",
            kind=PrincipalKind.BOUND,
            delegated_by="hapax",
            authority=frozenset({"email"}),
        )
        s = Says.unit(p1, 10).bind(lambda x: Says.unit(p2, x + 1))
        assert s.value == 11
        assert s.principal == p1

    def test_handoff(self):
        p1 = Principal(id="hapax", kind=PrincipalKind.SOVEREIGN)
        p2 = Principal(
            id="agent",
            kind=PrincipalKind.BOUND,
            delegated_by="hapax",
            authority=frozenset({"email"}),
        )
        s = Says.unit(p1, "data").handoff(p2)
        assert s.principal == p2

    def test_handoff_non_amplification(self):
        p = Principal(
            id="agent",
            kind=PrincipalKind.BOUND,
            delegated_by="hapax",
            authority=frozenset({"email"}),
        )
        target = Principal(
            id="sub",
            kind=PrincipalKind.BOUND,
            delegated_by="agent",
            authority=frozenset({"calendar"}),
        )
        s = Says.unit(p, "data")
        with self.assertRaises(ValueError):
            s.handoff(target, scope=frozenset({"calendar"}))

    def test_to_labeled(self):
        p = Principal(id="hapax", kind=PrincipalKind.SOVEREIGN)
        s = Says.unit(p, "data")
        labeled = s.to_labeled(ConsentLabel.bottom(), frozenset({"c1"}))
        assert labeled.value == "data"
        assert labeled.provenance == frozenset({"c1"})

    def test_speaks_for_self(self):
        p = Principal(id="hapax", kind=PrincipalKind.SOVEREIGN)
        s = Says.unit(p, "data")
        assert s.speaks_for(p) is True

    def test_speaks_for_delegate(self):
        p = Principal(id="hapax", kind=PrincipalKind.SOVEREIGN)
        child = Principal(
            id="agent",
            kind=PrincipalKind.BOUND,
            delegated_by="hapax",
            authority=frozenset(),
        )
        s = Says.unit(p, "data")
        assert s.speaks_for(child) is True
