"""Tests for revocation → carrier wiring (DD-8, DD-23, DD-26).

Self-contained, asyncio_mode="auto", unittest.mock only.
"""

from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from hypothesis import given, settings
from hypothesis import strategies as st

from shared.governance.carrier import CarrierRegistry
from shared.governance.consent import ConsentContract, ConsentRegistry
from shared.governance.consent_label import ConsentLabel
from shared.governance.labeled import Labeled
from shared.governance.revocation import RevocationPropagator
from shared.governance.revocation_wiring import (
    get_revocation_propagator,
    set_revocation_propagator,
)


def _make_consent_registry(*contracts: ConsentContract) -> ConsentRegistry:
    reg = ConsentRegistry()
    for c in contracts:
        reg._contracts[c.id] = c
    return reg


def _make_contract(contract_id: str, person_id: str) -> ConsentContract:
    return ConsentContract(
        id=contract_id,
        parties=("operator", person_id),
        scope=frozenset({"observation"}),
        direction="one_way",
        visibility_mechanism="on_request",
        created_at="2026-01-01",
    )


def _make_carrier_with_fact(
    principal_id: str,
    contract_id: str,
    domain: str = "test-domain",
) -> CarrierRegistry:
    from shared.governance.carrier import CarrierFact

    registry = CarrierRegistry()
    registry.register(principal_id, capacity=5)
    label = ConsentLabel(frozenset({contract_id}))
    labeled = Labeled(value="test-value", label=label, provenance=frozenset({contract_id}))
    now = time.monotonic()
    fact = CarrierFact(
        labeled=labeled,
        source_domain=domain,
        first_seen=now,
        last_seen=now,
    )
    registry.offer(principal_id, fact)
    return registry


class TestRevocationWiringModule(unittest.TestCase):
    """Tests for the module-level singleton wiring."""

    def setUp(self):
        # Reset singleton before each test
        set_revocation_propagator(None)

    def tearDown(self):
        set_revocation_propagator(None)

    def test_set_and_get(self):
        """set_revocation_propagator stores instance for get."""
        cr = _make_consent_registry()
        prop = RevocationPropagator(cr)
        set_revocation_propagator(prop)
        assert get_revocation_propagator() is prop

    def test_reset_to_none(self):
        """Setting None resets, next get creates a new instance."""
        cr = _make_consent_registry()
        prop1 = RevocationPropagator(cr)
        set_revocation_propagator(prop1)
        set_revocation_propagator(None)

        with patch("shared.governance.revocation_wiring.load_contracts") as mock_load:
            mock_load.return_value = cr
            with patch(
                "cockpit.engine.reactive_rules.get_carrier_registry",
                side_effect=ImportError("no reactive engine"),
            ):
                prop2 = get_revocation_propagator()
                assert prop2 is not prop1

    @patch("shared.governance.revocation_wiring.load_contracts")
    def test_lazy_init_loads_contracts(self, mock_load):
        """First call to get_revocation_propagator loads consent contracts."""
        cr = _make_consent_registry()
        mock_load.return_value = cr
        with patch("cockpit.engine.reactive_rules.get_carrier_registry") as mock_carrier:
            mock_carrier.return_value = CarrierRegistry()
            prop = get_revocation_propagator()
            assert prop is not None
            mock_load.assert_called_once()

    @patch("shared.governance.revocation_wiring.load_contracts")
    def test_lazy_init_wires_carrier_registry(self, mock_load):
        """First call wires the carrier registry from reactive_rules."""
        cr = _make_consent_registry()
        mock_load.return_value = cr
        carrier = CarrierRegistry()

        with patch("cockpit.engine.reactive_rules.get_carrier_registry") as mock_get:
            mock_get.return_value = carrier
            prop = get_revocation_propagator()
            # Verify the carrier registry handler was registered
            assert any(name == "carrier_registry" for name, _ in prop._handlers)

    @patch("shared.governance.revocation_wiring.load_contracts")
    def test_lazy_init_survives_carrier_import_failure(self, mock_load):
        """Propagator still works if carrier registry import fails."""
        cr = _make_consent_registry()
        mock_load.return_value = cr

        with patch(
            "cockpit.engine.reactive_rules.get_carrier_registry",
            side_effect=ImportError("no watchdog"),
        ):
            prop = get_revocation_propagator()
            assert prop is not None
            # No carrier handler registered
            assert not any(name == "carrier_registry" for name, _ in prop._handlers)

    def test_accepts_injected_consent_registry(self):
        """Can inject a custom ConsentRegistry."""
        contract = _make_contract("c1", "alice")
        cr = _make_consent_registry(contract)

        with patch("cockpit.engine.reactive_rules.get_carrier_registry") as mock_get:
            mock_get.return_value = CarrierRegistry()
            prop = get_revocation_propagator(consent_registry=cr)
            # Revoke should find alice's contract
            report = prop.revoke("alice")
            assert report.contract_revoked


class TestRevocationCarrierCascade(unittest.TestCase):
    """End-to-end: revocation cascades into carrier purge via wiring."""

    def setUp(self):
        set_revocation_propagator(None)

    def tearDown(self):
        set_revocation_propagator(None)

    def test_revoke_purges_carrier_facts(self):
        """Revoking consent purges carrier facts with matching provenance."""
        contract = _make_contract("c1", "alice")
        cr = _make_consent_registry(contract)
        carrier = _make_carrier_with_fact("agent-a", "c1")

        prop = RevocationPropagator(cr)
        prop.register_carrier_registry(carrier)
        set_revocation_propagator(prop)

        result_prop = get_revocation_propagator()
        report = result_prop.revoke("alice")

        assert report.contract_revoked
        assert report.total_purged == 1
        assert len(carrier.facts("agent-a")) == 0

    def test_revoke_leaves_unrelated_facts(self):
        """Revocation only purges facts with matching provenance."""
        from shared.governance.carrier import CarrierFact

        c1 = _make_contract("c1", "alice")
        cr = _make_consent_registry(c1)
        carrier = CarrierRegistry()
        carrier.register("agent-a", capacity=5)

        now = time.monotonic()

        # Fact with c1 provenance (should be purged)
        label1 = ConsentLabel(frozenset({"c1"}))
        labeled1 = Labeled(value="alice-data", label=label1, provenance=frozenset({"c1"}))
        fact1 = CarrierFact(
            labeled=labeled1, source_domain="domain-1", first_seen=now, last_seen=now
        )
        carrier.offer("agent-a", fact1)

        # Fact with c2 provenance (should survive)
        label2 = ConsentLabel(frozenset({"c2"}))
        labeled2 = Labeled(value="bob-data", label=label2, provenance=frozenset({"c2"}))
        fact2 = CarrierFact(
            labeled=labeled2, source_domain="domain-2", first_seen=now + 1, last_seen=now + 1
        )
        carrier.offer("agent-a", fact2)

        prop = RevocationPropagator(cr)
        prop.register_carrier_registry(carrier)
        set_revocation_propagator(prop)

        report = get_revocation_propagator().revoke("alice")
        assert report.contract_revoked
        assert report.total_purged == 1
        facts = carrier.facts("agent-a")
        assert len(facts) == 1
        assert facts[0].labeled.value == "bob-data"

    def test_revoke_unknown_person_is_noop(self):
        """Revoking a non-existent person does nothing."""
        cr = _make_consent_registry()
        carrier = _make_carrier_with_fact("agent-a", "c1")

        prop = RevocationPropagator(cr)
        prop.register_carrier_registry(carrier)
        set_revocation_propagator(prop)

        report = get_revocation_propagator().revoke("nobody")
        assert not report.contract_revoked
        assert report.total_purged == 0
        assert len(carrier.facts("agent-a")) == 1


class TestConsentRoute(unittest.TestCase):
    """Tests for the POST /consent/revoke/{person_id} endpoint."""

    def setUp(self):
        set_revocation_propagator(None)

    def tearDown(self):
        set_revocation_propagator(None)

    def test_revoke_endpoint(self):
        """POST /consent/revoke/{person_id} triggers revocation cascade."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from cockpit.api.routes.consent import router

        test_app = FastAPI()
        test_app.include_router(router)

        contract = _make_contract("c1", "alice")
        cr = _make_consent_registry(contract)
        carrier = _make_carrier_with_fact("agent-a", "c1")

        prop = RevocationPropagator(cr)
        prop.register_carrier_registry(carrier)
        set_revocation_propagator(prop)

        client = TestClient(test_app)
        resp = client.post("/api/consent/revoke/alice")
        assert resp.status_code == 200
        data = resp.json()
        assert data["contract_revoked"] is True
        assert data["total_purged"] == 1
        assert len(data["purge_results"]) == 1
        assert data["purge_results"][0]["subsystem"] == "carrier_registry"

    def test_revoke_endpoint_unknown_person(self):
        """POST /consent/revoke/{unknown} returns no-op."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from cockpit.api.routes.consent import router

        test_app = FastAPI()
        test_app.include_router(router)

        cr = _make_consent_registry()
        prop = RevocationPropagator(cr)
        set_revocation_propagator(prop)

        client = TestClient(test_app)
        resp = client.post("/api/consent/revoke/nobody")
        assert resp.status_code == 200
        data = resp.json()
        assert data["contract_revoked"] is False
        assert data["total_purged"] == 0


class TestRevocationHypothesis(unittest.TestCase):
    """Property-based tests for revocation wiring."""

    @given(
        person_id=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=20,
        ),
        contract_id=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=20,
        ),
    )
    @settings(max_examples=50)
    def test_revocation_purges_iff_contract_exists(self, person_id, contract_id):
        """Revocation purges carrier facts iff the consent contract exists."""
        set_revocation_propagator(None)

        contract = _make_contract(contract_id, person_id)
        cr = _make_consent_registry(contract)
        carrier = _make_carrier_with_fact("agent", contract_id)

        prop = RevocationPropagator(cr)
        prop.register_carrier_registry(carrier)

        report = prop.revoke(person_id)
        assert report.contract_revoked
        assert report.total_purged == 1
        assert len(carrier.facts("agent")) == 0

    @given(
        person_id=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=20,
        ),
    )
    @settings(max_examples=50)
    def test_revocation_noop_without_contract(self, person_id):
        """Revocation is a no-op when no contract exists for the person."""
        set_revocation_propagator(None)

        cr = _make_consent_registry()  # empty
        carrier = _make_carrier_with_fact("agent", "unrelated-contract")

        prop = RevocationPropagator(cr)
        prop.register_carrier_registry(carrier)

        report = prop.revoke(person_id)
        assert not report.contract_revoked
        assert report.total_purged == 0
        assert len(carrier.facts("agent")) == 1  # untouched
