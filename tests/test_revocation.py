"""Tests for shared.revocation — revocation propagation (DD-8, DD-23)."""

from __future__ import annotations

import unittest

from hypothesis import given
from hypothesis import strategies as st

from shared.carrier import CarrierFact, CarrierRegistry
from shared.consent import ConsentContract, ConsentRegistry
from shared.consent_label import ConsentLabel
from shared.labeled import Labeled
from shared.revocation import (
    PurgeResult,
    RevocationPropagator,
    RevocationReport,
    check_provenance,
)

# ── Helpers ──────────────────────────────────────────────────────────


def _make_registry_with_contract(
    contract_id: str = "c1",
    person: str = "alice",
    scope: frozenset[str] | None = None,
) -> ConsentRegistry:
    reg = ConsentRegistry()
    contract = ConsentContract(
        id=contract_id,
        parties=("operator", person),
        scope=scope or frozenset({"profile"}),
    )
    reg._contracts[contract_id] = contract
    return reg


def _make_carrier_with_fact(
    principal: str = "agent-a",
    contract_id: str = "c1",
    value: str = "fact-1",
) -> CarrierRegistry:
    carrier = CarrierRegistry()
    carrier.register(principal, capacity=5)
    fact = CarrierFact(
        labeled=Labeled(
            value=value,
            label=ConsentLabel.bottom(),
            provenance=frozenset({contract_id}),
        ),
        source_domain="test",
    )
    carrier.offer(principal, fact)
    return carrier


# ── RevocationReport ────────────────────────────────────────────────


class TestRevocationReport(unittest.TestCase):
    def test_total_purged(self):
        report = RevocationReport(
            contract_id="c1",
            person_id="alice",
            contract_revoked=True,
            purge_results=(
                PurgeResult("carrier", 3),
                PurgeResult("custom", 2),
            ),
        )
        assert report.total_purged == 5

    def test_empty_purge(self):
        report = RevocationReport(
            contract_id="", person_id="bob", contract_revoked=False, purge_results=()
        )
        assert report.total_purged == 0


# ── RevocationPropagator ────────────────────────────────────────────


class TestRevocationPropagator(unittest.TestCase):
    def test_revoke_with_carrier_purge(self):
        consent = _make_registry_with_contract("c1", "alice")
        carrier = _make_carrier_with_fact("agent-a", "c1")
        assert len(carrier.facts("agent-a")) == 1

        prop = RevocationPropagator(consent)
        prop.register_carrier_registry(carrier)
        report = prop.revoke("alice")

        assert report.contract_revoked
        assert report.total_purged == 1
        assert len(carrier.facts("agent-a")) == 0

    def test_revoke_no_contract(self):
        consent = ConsentRegistry()
        prop = RevocationPropagator(consent)
        report = prop.revoke("unknown")
        assert not report.contract_revoked
        assert report.total_purged == 0

    def test_revoke_multiple_subsystems(self):
        consent = _make_registry_with_contract("c1", "alice")
        carrier = _make_carrier_with_fact("a", "c1")

        custom_purged = []

        def custom_handler(contract_id: str) -> int:
            custom_purged.append(contract_id)
            return 5  # simulate 5 items purged

        prop = RevocationPropagator(consent)
        prop.register_carrier_registry(carrier)
        prop.register_handler("custom_store", custom_handler)
        report = prop.revoke("alice")

        assert report.contract_revoked
        assert report.total_purged == 6  # 1 carrier + 5 custom
        assert len(report.purge_results) == 2
        assert custom_purged == ["c1"]

    def test_revoke_no_matching_facts(self):
        consent = _make_registry_with_contract("c1", "alice")
        carrier = _make_carrier_with_fact("a", "c2")  # different contract

        prop = RevocationPropagator(consent)
        prop.register_carrier_registry(carrier)
        report = prop.revoke("alice")

        assert report.contract_revoked
        assert report.total_purged == 0  # no carrier facts match c1
        assert len(carrier.facts("a")) == 1  # c2 fact untouched

    def test_revoke_cascades_multiple_contracts(self):
        consent = ConsentRegistry()
        consent._contracts["c1"] = ConsentContract(
            id="c1", parties=("operator", "alice"), scope=frozenset({"profile"})
        )
        consent._contracts["c2"] = ConsentContract(
            id="c2", parties=("operator", "alice"), scope=frozenset({"calendar"})
        )

        carrier = CarrierRegistry()
        carrier.register("a", 5)
        carrier.offer(
            "a",
            CarrierFact(
                labeled=Labeled(
                    value="f1", label=ConsentLabel.bottom(), provenance=frozenset({"c1"})
                ),
                source_domain="d1",
            ),
        )
        carrier.offer(
            "a",
            CarrierFact(
                labeled=Labeled(
                    value="f2", label=ConsentLabel.bottom(), provenance=frozenset({"c2"})
                ),
                source_domain="d2",
            ),
        )

        prop = RevocationPropagator(consent)
        prop.register_carrier_registry(carrier)
        report = prop.revoke("alice")

        assert report.contract_revoked
        assert report.total_purged == 2
        assert len(carrier.facts("a")) == 0


# ── check_provenance ────────────────────────────────────────────────


class TestCheckProvenance(unittest.TestCase):
    def test_empty_provenance_valid(self):
        data = Labeled(value="x", label=ConsentLabel.bottom())
        assert check_provenance(data, frozenset())

    def test_all_active_valid(self):
        data = Labeled(value="x", label=ConsentLabel.bottom(), provenance=frozenset({"c1", "c2"}))
        assert check_provenance(data, frozenset({"c1", "c2", "c3"}))

    def test_revoked_contract_invalid(self):
        data = Labeled(value="x", label=ConsentLabel.bottom(), provenance=frozenset({"c1", "c2"}))
        assert not check_provenance(data, frozenset({"c1"}))  # c2 not active

    def test_all_revoked_invalid(self):
        data = Labeled(value="x", label=ConsentLabel.bottom(), provenance=frozenset({"c1"}))
        assert not check_provenance(data, frozenset())


# ── Hypothesis properties ────────────────────────────────────────────


class TestRevocationHypothesis(unittest.TestCase):
    @given(
        provenance=st.frozensets(
            st.text(min_size=1, max_size=5, alphabet=st.characters(whitelist_categories=("L",))),
            min_size=0,
            max_size=5,
        ),
        active=st.frozensets(
            st.text(min_size=1, max_size=5, alphabet=st.characters(whitelist_categories=("L",))),
            min_size=0,
            max_size=5,
        ),
    )
    def test_provenance_subset_iff_valid(self, provenance: frozenset[str], active: frozenset[str]):
        """check_provenance returns True iff provenance ⊆ active_contracts."""
        data = Labeled(value=0, label=ConsentLabel.bottom(), provenance=provenance)
        expected = provenance <= active
        assert check_provenance(data, active) == expected

    @given(
        provenance=st.frozensets(
            st.text(min_size=1, max_size=5, alphabet=st.characters(whitelist_categories=("L",))),
            min_size=1,
            max_size=3,
        ),
    )
    def test_empty_active_always_invalid(self, provenance: frozenset[str]):
        """Non-empty provenance with no active contracts is always invalid."""
        data = Labeled(value=0, label=ConsentLabel.bottom(), provenance=provenance)
        assert not check_provenance(data, frozenset())


if __name__ == "__main__":
    unittest.main()
