"""Tests for ConsentLabel join-semilattice proofs."""

from __future__ import annotations

import unittest

from hypothesis import given

from agentgov.consent import ConsentContract
from agentgov.consent_label import ConsentLabel
from tests.strategies import st_consent_label


class TestConsentLabelConstruction(unittest.TestCase):
    def test_bottom_is_empty(self):
        assert ConsentLabel.bottom().policies == frozenset()

    def test_join_combines_policies(self):
        a = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        b = ConsentLabel(frozenset({("carol", frozenset({"dave"}))}))
        assert len(a.join(b).policies) == 2

    def test_can_flow_to_superset(self):
        a = ConsentLabel(frozenset({("alice", frozenset({"bob"}))}))
        b = ConsentLabel(frozenset({("alice", frozenset({"bob"})), ("carol", frozenset({"dave"}))}))
        assert a.can_flow_to(b)
        assert not b.can_flow_to(a)

    def test_frozen(self):
        label = ConsentLabel.bottom()
        with self.assertRaises(AttributeError):
            label.policies = frozenset()  # type: ignore[misc]


class TestConsentLabelBridge(unittest.TestCase):
    def test_active_contract_produces_label(self):
        contract = ConsentContract(id="c1", parties=("hapax", "alice"), scope=frozenset({"email"}))
        assert len(ConsentLabel.from_contract(contract).policies) == 1

    def test_revoked_contract_produces_bottom(self):
        contract = ConsentContract(
            id="c1",
            parties=("hapax", "alice"),
            scope=frozenset({"email"}),
            revoked_at="2026-01-01",
        )
        assert ConsentLabel.from_contract(contract) == ConsentLabel.bottom()

    def test_from_contracts_joins_all(self):
        c1 = ConsentContract(id="c1", parties=("hapax", "alice"), scope=frozenset({"email"}))
        c2 = ConsentContract(id="c2", parties=("hapax", "bob"), scope=frozenset({"calendar"}))
        assert len(ConsentLabel.from_contracts([c1, c2]).policies) == 2


class TestConsentLabelLattice(unittest.TestCase):
    @given(a=st_consent_label(), b=st_consent_label())
    def test_join_commutativity(self, a, b):
        assert a.join(b) == b.join(a)

    @given(a=st_consent_label(), b=st_consent_label(), c=st_consent_label())
    def test_join_associativity(self, a, b, c):
        assert a.join(b).join(c) == a.join(b.join(c))

    @given(a=st_consent_label())
    def test_join_idempotence(self, a):
        assert a.join(a) == a

    @given(a=st_consent_label())
    def test_bottom_is_join_identity(self, a):
        assert a.join(ConsentLabel.bottom()) == a

    @given(a=st_consent_label())
    def test_reflexivity(self, a):
        assert a.can_flow_to(a)

    @given(a=st_consent_label(), b=st_consent_label())
    def test_antisymmetry(self, a, b):
        if a.can_flow_to(b) and b.can_flow_to(a):
            assert a == b

    @given(a=st_consent_label(), b=st_consent_label(), c=st_consent_label())
    def test_transitivity(self, a, b, c):
        if a.can_flow_to(b) and b.can_flow_to(c):
            assert a.can_flow_to(c)

    @given(a=st_consent_label())
    def test_bottom_flows_to_all(self, a):
        assert ConsentLabel.bottom().can_flow_to(a)
