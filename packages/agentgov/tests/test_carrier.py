"""Tests for CarrierRegistry and carrier dynamics."""

from __future__ import annotations

import unittest

from agentgov.carrier import CarrierFact, CarrierRegistry
from agentgov.consent_label import ConsentLabel
from agentgov.labeled import Labeled


def _make_fact(value: str, domain: str = "test", count: int = 1) -> CarrierFact:
    return CarrierFact(
        labeled=Labeled(value=value, label=ConsentLabel.bottom()),
        source_domain=domain,
        observation_count=count,
    )


class TestCarrierRegistry(unittest.TestCase):
    def test_register_and_offer(self):
        reg = CarrierRegistry()
        reg.register("agent-a", capacity=2)
        result = reg.offer("agent-a", _make_fact("fact-1"))
        assert result.inserted is True
        assert len(reg.facts("agent-a")) == 1

    def test_capacity_limit(self):
        reg = CarrierRegistry()
        reg.register("agent-a", capacity=1)
        reg.offer("agent-a", _make_fact("fact-1"))
        result = reg.offer("agent-a", _make_fact("fact-2", count=1))
        assert result.inserted is False

    def test_displacement(self):
        reg = CarrierRegistry(displacement_threshold=2.0)
        reg.register("agent-a", capacity=1)
        reg.offer("agent-a", _make_fact("old", count=1))
        result = reg.offer("agent-a", _make_fact("new", count=3))
        assert result.inserted is True
        assert result.displaced is not None

    def test_duplicate_updates_count(self):
        reg = CarrierRegistry()
        reg.register("agent-a", capacity=2)
        reg.offer("agent-a", _make_fact("fact-1"))
        reg.offer("agent-a", _make_fact("fact-1"))
        facts = reg.facts("agent-a")
        assert len(facts) == 1
        assert facts[0].observation_count == 2

    def test_purge_by_provenance(self):
        reg = CarrierRegistry()
        reg.register("agent-a", capacity=5)
        fact = CarrierFact(
            labeled=Labeled(
                value="secret",
                label=ConsentLabel.bottom(),
                provenance=frozenset({"contract-1"}),
            ),
            source_domain="test",
        )
        reg.offer("agent-a", fact)
        purged = reg.purge_by_provenance("contract-1")
        assert purged == 1
        assert len(reg.facts("agent-a")) == 0

    def test_unregistered_principal_raises(self):
        reg = CarrierRegistry()
        with self.assertRaises(ValueError):
            reg.offer("unknown", _make_fact("fact"))
