"""Tests for Says monad — consent formalism #1.

Verifies monadic laws, authority threading, handoff, speaks-for,
and integration with Labeled[T].
"""

from __future__ import annotations

import pytest

from shared.governance.consent_label import ConsentLabel
from shared.governance.labeled import Labeled
from shared.governance.principal import Principal, PrincipalKind
from shared.governance.says import Says

# ── Fixtures ─────────────────────────────────────────────────────────────────


def _sovereign(name: str = "operator") -> Principal:
    return Principal(id=name, kind=PrincipalKind.SOVEREIGN)


def _bound(
    name: str = "agent-sync", delegator: str = "operator", scope: frozenset[str] | None = None
) -> Principal:
    return Principal(
        id=name,
        kind=PrincipalKind.BOUND,
        delegated_by=delegator,
        authority=scope or frozenset({"read", "write"}),
    )


# ── Monadic Laws ─────────────────────────────────────────────────────────────


class TestMonadicLaws:
    """Says must satisfy the three monad laws."""

    def test_left_identity(self):
        """unit(a) >>= f  ==  f(a)"""
        p = _sovereign()

        def f(x):
            return Says(principal=p, value=x * 2)

        left = Says.unit(p, 5).bind(f)
        right = f(5)

        assert left.value == right.value

    def test_right_identity(self):
        """m >>= unit  ==  m"""
        p = _sovereign()
        m = Says(principal=p, value=42)

        result = m.bind(lambda x: Says.unit(p, x))

        assert result.value == m.value
        assert result.principal == m.principal

    def test_associativity(self):
        """(m >>= f) >>= g  ==  m >>= (λx. f(x) >>= g)"""
        p = _sovereign()
        m = Says(principal=p, value=10)

        def f(x):
            return Says(principal=p, value=x + 1)

        def g(x):
            return Says(principal=p, value=x * 2)

        left = m.bind(f).bind(g)
        right = m.bind(lambda x: f(x).bind(g))

        assert left.value == right.value


# ── Functor Map ──────────────────────────────────────────────────────────────


class TestFunctorMap:
    def test_map_preserves_principal(self):
        p = _sovereign()
        s = Says(principal=p, value=10)
        result = s.map(lambda x: x * 3)
        assert result.value == 30
        assert result.principal is p

    def test_map_identity(self):
        """map(id) == id"""
        p = _sovereign()
        s = Says(principal=p, value="hello")
        assert s.map(lambda x: x).value == s.value

    def test_map_composition(self):
        """map(f . g) == map(f) . map(g)"""
        p = _sovereign()
        s = Says(principal=p, value=5)

        def f(x):
            return x + 1

        def g(x):
            return x * 2

        left = s.map(lambda x: f(g(x)))
        right = s.map(g).map(f)

        assert left.value == right.value


# ── Authority & Handoff ──────────────────────────────────────────────────────


class TestAuthority:
    def test_sovereign_handoff_to_bound(self):
        """Sovereign can hand off to any bound principal."""
        op = _sovereign()
        agent = _bound()
        s = Says(principal=op, value="data")
        result = s.handoff(agent)
        assert result.principal is agent
        assert result.value == "data"

    def test_bound_handoff_within_authority(self):
        """Bound principal can hand off within its authority scope."""
        parent = _bound("parent-agent", scope=frozenset({"read", "write"}))
        child = _bound("child-agent", delegator="parent-agent", scope=frozenset({"read"}))
        s = Says(principal=parent, value="data")
        result = s.handoff(child, scope=frozenset({"read"}))
        assert result.principal is child

    def test_bound_handoff_exceeds_authority(self):
        """Bound principal cannot hand off beyond its authority."""
        agent = _bound(scope=frozenset({"read"}))
        target = _bound("target", scope=frozenset({"read", "write", "delete"}))
        s = Says(principal=agent, value="data")
        with pytest.raises(ValueError, match="Non-amplification"):
            s.handoff(target, scope=frozenset({"delete"}))

    def test_authority_property(self):
        agent = _bound(scope=frozenset({"read", "write"}))
        s = Says(principal=agent, value="test")
        assert s.authority == frozenset({"read", "write"})

    def test_asserter_id(self):
        op = _sovereign("operator")
        s = Says(principal=op, value="test")
        assert s.asserter_id == "operator"


# ── Speaks-For ───────────────────────────────────────────────────────────────


class TestSpeaksFor:
    def test_self_speaks_for_self(self):
        op = _sovereign()
        s = Says(principal=op, value="test")
        assert s.speaks_for(op) is True

    def test_sovereign_speaks_for_delegate(self):
        op = _sovereign()
        agent = _bound(delegator="operator")
        s = Says(principal=op, value="test")
        assert s.speaks_for(agent) is True

    def test_delegate_does_not_speak_for_sovereign(self):
        op = _sovereign()
        agent = _bound(delegator="operator")
        s = Says(principal=agent, value="test")
        assert s.speaks_for(op) is False

    def test_unrelated_principals(self):
        p1 = _sovereign("alice")
        p2 = _sovereign("bob")
        s = Says(principal=p1, value="test")
        assert s.speaks_for(p2) is False


# ── Integration with Labeled ─────────────────────────────────────────────────


class TestLabeledIntegration:
    def test_to_labeled(self):
        """Says converts to Labeled with label and provenance."""
        op = _sovereign()
        s = Says(principal=op, value="personal data")
        label = ConsentLabel.bottom()
        provenance = frozenset({"contract-001"})

        labeled = s.to_labeled(label, provenance)

        assert labeled.value == "personal data"
        assert labeled.label == label
        assert labeled.provenance == provenance

    def test_from_labeled(self):
        """Labeled can be wrapped with principal attribution."""
        op = _sovereign()
        labeled = Labeled(
            value="fact",
            label=ConsentLabel.bottom(),
            provenance=frozenset({"c1"}),
        )

        s = Says.from_labeled(op, labeled)

        assert s.principal is op
        assert s.value is labeled
        assert s.value.provenance == frozenset({"c1"})

    def test_says_then_label_then_gate_flow(self):
        """Full flow: Says → to_labeled → can check provenance."""
        op = _sovereign()
        s = Says(principal=op, value="meeting notes about alice")
        label = ConsentLabel(frozenset({("alice", frozenset({"operator", "alice"}))}))
        provenance = frozenset({"consent-alice-001"})

        labeled = s.to_labeled(label, provenance)

        # Provenance check: contract is active
        active = frozenset({"consent-alice-001"})
        assert labeled.provenance <= active

        # Flow check: data can flow to matching label
        assert labeled.can_flow_to(label)


# ── Bind Preserves Originator ────────────────────────────────────────────────


class TestBindPreservesOriginator:
    def test_bind_keeps_original_principal(self):
        """Bind preserves the initiating principal, not the intermediate."""
        op = _sovereign("operator")
        agent = _bound("agent", delegator="operator")

        s = Says(principal=op, value=10)
        result = s.bind(lambda x: Says(principal=agent, value=x * 2))

        # The result carries operator (originator), not agent
        assert result.principal.id == "operator"
        assert result.value == 20

    def test_chained_binds_preserve_originator(self):
        op = _sovereign("operator")
        a1 = _bound("a1", delegator="operator")
        a2 = _bound("a2", delegator="operator")

        result = (
            Says(principal=op, value=1)
            .bind(lambda x: Says(principal=a1, value=x + 1))
            .bind(lambda x: Says(principal=a2, value=x + 1))
        )

        assert result.principal.id == "operator"
        assert result.value == 3
