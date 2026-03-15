"""Tests for consent-gated writer — provable consent enforcement.

The key property: ∀ data, persons:
    gate.check(data) succeeds → data.provenance ⊆ active_contracts
                               ∧ ∀ person ∈ persons: contract_exists(person, category)

Self-contained, unittest.mock only.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from shared.governance.consent import ConsentContract, ConsentRegistry
from shared.governance.consent_gate import ConsentGatedWriter
from shared.governance.consent_label import ConsentLabel
from shared.governance.governor import GovernorWrapper, consent_output_policy
from shared.governance.labeled import Labeled


def _registry_with(*contracts: ConsentContract) -> ConsentRegistry:
    reg = ConsentRegistry()
    for c in contracts:
        reg._contracts[c.id] = c
    return reg


def _contract(cid: str, person: str, scope: frozenset[str], active: bool = True) -> ConsentContract:
    return ConsentContract(
        id=cid,
        parties=("operator", person),
        scope=scope,
        revoked_at=None if active else "2026-01-01",
    )


def _gate(registry: ConsentRegistry) -> ConsentGatedWriter:
    gov = GovernorWrapper("test-gate")
    gov.add_output_policy(consent_output_policy(ConsentLabel.bottom()))
    return ConsentGatedWriter(_registry=registry, _governor=gov)


def _labeled(value: str, provenance: frozenset[str] | None = None) -> Labeled:
    return Labeled(
        value=value,
        label=ConsentLabel.bottom(),
        provenance=provenance or frozenset(),
    )


# ── Basic gate behavior ─────────────────────────────────────────────


class TestConsentGateBasic(unittest.TestCase):
    def test_public_data_always_allowed(self):
        """Data with no provenance and no person_ids is public — always allowed."""
        gate = _gate(_registry_with())
        decision = gate.check(_labeled("public data"))
        assert decision.allowed
        assert "passed" in decision.reason

    def test_person_without_contract_denied(self):
        """Data about a person without a consent contract is denied."""
        gate = _gate(_registry_with())
        decision = gate.check(
            _labeled("conversation with alice"),
            person_ids=("alice",),
            data_category="audio",
        )
        assert not decision.allowed
        assert "alice" in decision.reason
        assert "consent contract" in decision.reason.lower()

    def test_person_with_contract_allowed(self):
        """Data about a person WITH a consent contract is allowed."""
        c = _contract("c-alice", "alice", frozenset({"audio"}))
        gate = _gate(_registry_with(c))
        decision = gate.check(
            _labeled("conversation with alice"),
            person_ids=("alice",),
            data_category="audio",
        )
        assert decision.allowed

    def test_person_with_wrong_scope_denied(self):
        """Contract exists but scope doesn't cover data category."""
        c = _contract("c-alice", "alice", frozenset({"video"}))  # video, not audio
        gate = _gate(_registry_with(c))
        decision = gate.check(
            _labeled("audio conversation"),
            person_ids=("alice",),
            data_category="audio",
        )
        assert not decision.allowed

    def test_revoked_contract_in_provenance_denied(self):
        """Data whose provenance includes a revoked contract is denied."""
        c = _contract("c-alice", "alice", frozenset({"audio"}), active=False)
        gate = _gate(_registry_with(c))
        decision = gate.check(
            _labeled("old data", provenance=frozenset({"c-alice"})),
            data_category="audio",
        )
        assert not decision.allowed
        assert "revoked" in decision.reason.lower()

    def test_operator_always_allowed(self):
        """Data only about the operator needs no contract."""
        gate = _gate(_registry_with())
        decision = gate.check(
            _labeled("my own notes"),
            person_ids=("operator",),
            data_category="audio",
        )
        assert decision.allowed

    def test_multiple_persons_all_need_contracts(self):
        """All non-operator persons must have contracts."""
        c_alice = _contract("c-alice", "alice", frozenset({"audio"}))
        gate = _gate(_registry_with(c_alice))  # bob has no contract
        decision = gate.check(
            _labeled("group conversation"),
            person_ids=("alice", "bob"),
            data_category="audio",
        )
        assert not decision.allowed
        assert "bob" in decision.reason


# ── Audit trail ──────────────────────────────────────────────────────


class TestConsentGateAudit(unittest.TestCase):
    def test_decisions_recorded(self):
        gate = _gate(_registry_with())
        gate.check(_labeled("data1"))
        gate.check(_labeled("data2"), person_ids=("alice",), data_category="audio")
        assert len(gate.decisions) == 2
        assert gate.decisions[0].allowed
        assert not gate.decisions[1].allowed

    def test_audit_log_written_to_disk(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            audit_path = Path(f.name)

        try:
            gate = ConsentGatedWriter(
                _registry=_registry_with(),
                _governor=GovernorWrapper("test"),
                _audit_path=audit_path,
            )
            gate.check(_labeled("data"), person_ids=("alice",), data_category="x")

            import json

            entries = [json.loads(l) for l in audit_path.read_text().splitlines()]
            assert len(entries) == 1
            assert entries[0]["allowed"] is False
            assert "alice" in entries[0]["person_ids"]
        finally:
            audit_path.unlink()


# ── Write behavior ───────────────────────────────────────────────────


class TestConsentGateWrite(unittest.TestCase):
    def test_allowed_write_persists(self):
        gate = _gate(_registry_with())
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            path = Path(f.name)
        try:
            decision = gate.check_and_write(_labeled("public content"), path)
            assert decision.allowed
            assert path.read_text() == "public content"
        finally:
            path.unlink()

    def test_denied_write_does_not_persist(self):
        gate = _gate(_registry_with())
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("original content")
            path = Path(f.name)
        try:
            decision = gate.check_and_write(
                _labeled("private data"),
                path,
                person_ids=("alice",),
                data_category="audio",
            )
            assert not decision.allowed
            assert path.read_text() == "original content"  # unchanged
        finally:
            path.unlink()


# ── Contract creation ────────────────────────────────────────────────


class TestConsentContractCreation(unittest.TestCase):
    def test_create_contract_at_runtime(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            contracts_dir = Path(tmpdir)
            registry = ConsentRegistry()

            contract = registry.create_contract(
                "wife",
                frozenset({"audio", "transcription"}),
                contracts_dir=contracts_dir,
            )

            assert contract.active
            assert contract.parties == ("operator", "wife")
            assert "audio" in contract.scope
            assert (contracts_dir / f"{contract.id}.yaml").exists()
            assert registry.contract_check("wife", "audio")

    def test_created_contract_enables_gate(self):
        """After creating a contract, the gate allows writes for that person."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ConsentRegistry()

            # Before contract: denied
            gate = _gate(registry)
            decision = gate.check(
                _labeled("conversation"),
                person_ids=("wife",),
                data_category="audio",
            )
            assert not decision.allowed

            # Create contract
            registry.create_contract(
                "wife",
                frozenset({"audio"}),
                contracts_dir=Path(tmpdir),
            )

            # After contract: allowed
            gate2 = _gate(registry)
            decision2 = gate2.check(
                _labeled("conversation"),
                person_ids=("wife",),
                data_category="audio",
            )
            assert decision2.allowed

    def test_revoke_after_create_denies(self):
        """Create → revoke → gate denies."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ConsentRegistry()
            registry.create_contract(
                "wife",
                frozenset({"audio"}),
                contracts_dir=Path(tmpdir),
            )
            assert registry.contract_check("wife", "audio")

            registry.purge_subject("wife")
            assert not registry.contract_check("wife", "audio")


# ── Provable property ───────────────────────────────────────────────


class TestConsentGateProperty(unittest.TestCase):
    """The key algebraic property: allowed writes have valid provenance."""

    @given(
        person_id=st.text(
            alphabet=st.characters(whitelist_categories=("L",)),
            min_size=1,
            max_size=10,
        ),
        category=st.sampled_from(["audio", "video", "transcription", "biometric"]),
        has_contract=st.booleans(),
    )
    @settings(max_examples=100)
    def test_allowed_iff_contract_exists(self, person_id, category, has_contract):
        """∀ person, category: gate allows ↔ contract exists for (person, category)."""
        contracts = []
        if has_contract:
            contracts.append(_contract(f"c-{person_id}", person_id, frozenset({category})))
        gate = _gate(_registry_with(*contracts))

        decision = gate.check(
            _labeled("data"),
            person_ids=(person_id,),
            data_category=category,
        )

        assert decision.allowed == has_contract, (
            f"Gate {'allowed' if decision.allowed else 'denied'} "
            f"but contract {'exists' if has_contract else 'missing'} "
            f"for person={person_id}, category={category}"
        )

    @given(
        n_persons=st.integers(min_value=1, max_value=4),
        n_with_contracts=st.integers(min_value=0, max_value=4),
    )
    @settings(max_examples=50)
    def test_all_persons_must_have_contracts(self, n_persons, n_with_contracts):
        """∀ group: gate allows only if ALL non-operator persons have contracts."""
        n_with_contracts = min(n_with_contracts, n_persons)
        persons = [f"person{i}" for i in range(n_persons)]
        contracts = [
            _contract(f"c-{p}", p, frozenset({"audio"})) for p in persons[:n_with_contracts]
        ]
        gate = _gate(_registry_with(*contracts))

        decision = gate.check(
            _labeled("group data"),
            person_ids=tuple(persons),
            data_category="audio",
        )

        all_covered = n_with_contracts >= n_persons
        assert decision.allowed == all_covered

    @given(
        contract_active=st.booleans(),
    )
    @settings(max_examples=50)
    def test_revoked_provenance_always_denied(self, contract_active):
        """∀ data: provenance with revoked contract → denied."""
        c = _contract("c1", "alice", frozenset({"audio"}), active=contract_active)
        gate = _gate(_registry_with(c))

        decision = gate.check(
            _labeled("data", provenance=frozenset({"c1"})),
            data_category="audio",
        )

        if not contract_active:
            assert not decision.allowed
