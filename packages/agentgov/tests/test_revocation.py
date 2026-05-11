"""Tests for revocation cascade."""

from __future__ import annotations

import unittest

from agentgov.carrier import CarrierFact, CarrierRegistry
from agentgov.consent import ConsentContract, ConsentRegistry
from agentgov.consent_label import ConsentLabel
from agentgov.labeled import Labeled
from agentgov.revocation import RevocationPropagator, check_provenance


class TestRevocationPropagator(unittest.TestCase):
    def test_revoke_with_carrier_purge(self):
        reg = ConsentRegistry()
        contract = ConsentContract(
            id="c1", parties=("operator", "alice"), scope=frozenset({"email"})
        )
        reg._contracts["c1"] = contract

        carrier = CarrierRegistry()
        carrier.register("agent-a", capacity=5)
        fact = CarrierFact(
            labeled=Labeled(
                value="data",
                label=ConsentLabel.bottom(),
                provenance=frozenset({"c1"}),
            ),
            source_domain="test",
        )
        carrier.offer("agent-a", fact)

        prop = RevocationPropagator(reg)
        prop.register_carrier_registry(carrier)

        report = prop.revoke("alice")
        assert report.contract_revoked is True
        assert report.total_purged == 1
        assert len(carrier.facts("agent-a")) == 0

    def test_revoke_unknown_person(self):
        reg = ConsentRegistry()
        prop = RevocationPropagator(reg)
        report = prop.revoke("nobody")
        assert report.contract_revoked is False


class TestCheckProvenance(unittest.TestCase):
    def test_active_provenance(self):
        data = Labeled(
            value="hello",
            label=ConsentLabel.bottom(),
            provenance=frozenset({"c1"}),
        )
        assert check_provenance(data, frozenset({"c1"})) is True

    def test_revoked_provenance(self):
        data = Labeled(
            value="hello",
            label=ConsentLabel.bottom(),
            provenance=frozenset({"c1"}),
        )
        assert check_provenance(data, frozenset()) is False

    def test_empty_provenance(self):
        data = Labeled(value="hello", label=ConsentLabel.bottom())
        assert check_provenance(data, frozenset()) is True
