"""Tests for Says monad."""

from __future__ import annotations

import unittest

from hypothesis import given, settings
from hypothesis import strategies as st

from agentgov.consent_label import ConsentLabel
from agentgov.principal import Principal, PrincipalKind
from agentgov.says import Says
from tests.strategies import st_sovereign


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


# ---------------------------------------------------------------------------
# Monad law property tests (Hypothesis)
# ---------------------------------------------------------------------------


class TestSaysMonadLaws:
    """Verify the three monad laws for Says."""

    @given(p=st_sovereign(), a=st.integers())
    @settings(max_examples=100)
    def test_left_identity(self, p, a):
        """unit(p, a).bind(f) should have same value as f(a)."""

        def f(x):
            return Says.unit(p, x * 2)

        lhs = Says.unit(p, a).bind(f)
        rhs = f(a)
        assert lhs.value == rhs.value

    @given(p=st_sovereign(), a=st.integers())
    @settings(max_examples=100)
    def test_right_identity(self, p, a):
        """m.bind(unit) should preserve value."""
        m = Says.unit(p, a)
        result = m.bind(lambda x: Says.unit(m.principal, x))
        assert result.value == m.value
        assert result.principal == m.principal

    @given(p=st_sovereign(), a=st.integers())
    @settings(max_examples=100)
    def test_associativity(self, p, a):
        """m.bind(f).bind(g) == m.bind(lambda x: f(x).bind(g))."""

        def f(x):
            return Says.unit(p, x + 1)

        def g(x):
            return Says.unit(p, x * 3)

        m = Says.unit(p, a)
        lhs = m.bind(f).bind(g)
        rhs = m.bind(lambda x: f(x).bind(g))
        assert lhs.value == rhs.value
