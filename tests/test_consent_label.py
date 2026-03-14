"""Tests for shared.consent_label — ConsentLabel join-semilattice proofs."""

from __future__ import annotations

import unittest

from hypothesis import given

from shared.consent import ConsentContract
from shared.consent_label import ConsentLabel
from tests.consent_strategies import st_consent_label


class TestConsentLabelConstruction(unittest.TestCase):
    """Construction and basic operations."""

    def test_bottom_is_empty(self):
        b = ConsentLabel.bottom()
        assert b.policies == frozenset()

    def test_single_policy(self):
        label = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        assert len(label.policies) == 1

    def test_join_combines_policies(self):
        a = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        b = ConsentLabel(frozenset({("carol", frozenset({"dave"}))}))
        joined = a.join(b)
        assert len(joined.policies) == 2

    def test_can_flow_to_superset(self):
        a = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        b = ConsentLabel(
            frozenset({("alice", frozenset({"bob"})), ("carol", frozenset({"dave"}))})
        )
        assert a.can_flow_to(b)
        assert not b.can_flow_to(a)

    def test_can_flow_to_self(self):
        a = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        assert a.can_flow_to(a)

    def test_frozen(self):
        label = ConsentLabel.bottom()
        with self.assertRaises(AttributeError):
            label.policies = frozenset()  # type: ignore[misc]


class TestConsentLabelBridge(unittest.TestCase):
    """Bridge from ConsentContract to ConsentLabel."""

    def test_active_contract_produces_label(self):
        contract = ConsentContract(
            id="c1",
            parties=("hapax", "alice"),
            scope=frozenset({"email"}),
        )
        label = ConsentLabel.from_contract(contract)
        assert len(label.policies) == 1

    def test_revoked_contract_produces_bottom(self):
        contract = ConsentContract(
            id="c1",
            parties=("hapax", "alice"),
            scope=frozenset({"email"}),
            revoked_at="2026-01-01",
        )
        label = ConsentLabel.from_contract(contract)
        assert label == ConsentLabel.bottom()

    def test_from_contracts_joins_all(self):
        c1 = ConsentContract(id="c1", parties=("hapax", "alice"), scope=frozenset({"email"}))
        c2 = ConsentContract(id="c2", parties=("hapax", "bob"), scope=frozenset({"calendar"}))
        label = ConsentLabel.from_contracts([c1, c2])
        assert len(label.policies) == 2

    def test_from_contracts_empty(self):
        label = ConsentLabel.from_contracts([])
        assert label == ConsentLabel.bottom()


class TestConsentLabelLattice(unittest.TestCase):
    """Property-based proofs that ConsentLabel is a join-semilattice."""

    @given(a=st_consent_label(), b=st_consent_label())
    def test_join_commutativity(self, a: ConsentLabel, b: ConsentLabel):
        """a ⊔ b == b ⊔ a"""
        assert a.join(b) == b.join(a)

    @given(a=st_consent_label(), b=st_consent_label(), c=st_consent_label())
    def test_join_associativity(self, a: ConsentLabel, b: ConsentLabel, c: ConsentLabel):
        """(a ⊔ b) ⊔ c == a ⊔ (b ⊔ c)"""
        assert a.join(b).join(c) == a.join(b.join(c))

    @given(a=st_consent_label())
    def test_join_idempotence(self, a: ConsentLabel):
        """a ⊔ a == a"""
        assert a.join(a) == a

    @given(a=st_consent_label())
    def test_bottom_is_join_identity(self, a: ConsentLabel):
        """a ⊔ ⊥ == a"""
        assert a.join(ConsentLabel.bottom()) == a

    @given(a=st_consent_label())
    def test_reflexivity(self, a: ConsentLabel):
        """a ⊑ a"""
        assert a.can_flow_to(a)

    @given(a=st_consent_label(), b=st_consent_label())
    def test_antisymmetry(self, a: ConsentLabel, b: ConsentLabel):
        """a ⊑ b ∧ b ⊑ a → a == b"""
        if a.can_flow_to(b) and b.can_flow_to(a):
            assert a == b

    @given(a=st_consent_label(), b=st_consent_label(), c=st_consent_label())
    def test_transitivity(self, a: ConsentLabel, b: ConsentLabel, c: ConsentLabel):
        """a ⊑ b ∧ b ⊑ c → a ⊑ c"""
        if a.can_flow_to(b) and b.can_flow_to(c):
            assert a.can_flow_to(c)

    @given(a=st_consent_label(), b=st_consent_label())
    def test_join_is_lub(self, a: ConsentLabel, b: ConsentLabel):
        """a ⊑ (a ⊔ b) ∧ b ⊑ (a ⊔ b)"""
        joined = a.join(b)
        assert a.can_flow_to(joined)
        assert b.can_flow_to(joined)

    @given(a=st_consent_label(), b=st_consent_label(), c=st_consent_label())
    def test_monotonicity(self, a: ConsentLabel, b: ConsentLabel, c: ConsentLabel):
        """a ⊑ b → (a ⊔ c) ⊑ (b ⊔ c)"""
        if a.can_flow_to(b):
            assert a.join(c).can_flow_to(b.join(c))

    @given(a=st_consent_label())
    def test_bottom_flows_to_all(self, a: ConsentLabel):
        """⊥ ⊑ a"""
        assert ConsentLabel.bottom().can_flow_to(a)


if __name__ == "__main__":
    unittest.main()
