"""End-to-end consent scenario: guest enters → curtail → offer → accept → flow → revoke → purge.

Proves the complete chain works as an integrated system with the
provable property: no persistent write occurs for person-adjacent
data without an active consent contract.

Self-contained, unittest.mock only.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hypothesis import given, settings
from hypothesis import strategies as st

from shared.governance.carrier import CarrierFact, CarrierRegistry
from shared.governance.consent import ConsentContract, ConsentRegistry
from shared.governance.consent_channels import (
    GuestContext,
    build_channel_menu,
)
from shared.governance.consent_gate import ConsentGatedWriter
from shared.governance.consent_label import ConsentLabel
from shared.governance.governor import GovernorWrapper, consent_output_policy
from shared.governance.guest_detection import check_guest_consent
from shared.governance.labeled import Labeled
from shared.governance.revocation import RevocationPropagator


def _registry(*contracts: ConsentContract) -> ConsentRegistry:
    reg = ConsentRegistry()
    for c in contracts:
        reg._contracts[c.id] = c
    return reg


def _contract(person: str, scope: frozenset[str]) -> ConsentContract:
    return ConsentContract(
        id=f"contract-{person}",
        parties=("operator", person),
        scope=scope,
    )


def _gate(registry: ConsentRegistry) -> ConsentGatedWriter:
    gov = GovernorWrapper("scenario-gate")
    gov.add_output_policy(consent_output_policy(ConsentLabel.bottom()))
    return ConsentGatedWriter(_registry=registry, _governor=gov)


def _labeled(value: str, provenance: frozenset[str] | None = None) -> Labeled:
    return Labeled(
        value=value,
        label=ConsentLabel.bottom(),
        provenance=provenance or frozenset(),
    )


class TestConsentScenarioE2E(unittest.TestCase):
    """The full wife-walks-in scenario, step by step."""

    def test_step1_detection_no_consent(self):
        """Step 1: Guest detected, no consent contract exists."""
        with patch("shared.governance.consent.ConsentRegistry.load"):
            event = check_guest_consent("wife", "audio")
            assert not event.has_consent
            assert event.contract_id is None
            assert event.channel_menu_sufficient

    def test_step2_curtailment_blocks_write(self):
        """Step 2: Without consent, the gate blocks persistent writes."""
        reg = _registry()  # no contracts
        gate = _gate(reg)

        decision = gate.check(
            _labeled("wife speaking in background"),
            person_ids=("wife",),
            data_category="audio",
        )
        assert not decision.allowed
        assert "consent contract" in decision.reason.lower()

    def test_step3_channels_available(self):
        """Step 3: Consent channels are offered (menu is sufficient)."""
        menu = build_channel_menu(guest=GuestContext())
        assert menu.sufficient
        available = [o for o in menu.offers if o.available]
        assert len(available) >= 2  # at least QR + operator-mediated
        # Sorted by friction
        frictions = [o.friction.total for o in available]
        assert frictions == sorted(frictions)

    def test_step4_consent_granted_creates_contract(self):
        """Step 4: Guest grants consent → contract created → gate allows."""
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = _registry()
            gate = _gate(reg)

            # Before: denied
            d1 = gate.check(
                _labeled("conversation"),
                person_ids=("wife",),
                data_category="audio",
            )
            assert not d1.allowed

            # Guest grants consent via channel
            reg.create_contract(
                "wife",
                frozenset({"audio", "transcription", "presence"}),
                contracts_dir=Path(tmpdir),
            )

            # After: allowed
            gate2 = _gate(reg)
            d2 = gate2.check(
                _labeled("conversation"),
                person_ids=("wife",),
                data_category="audio",
            )
            assert d2.allowed

    def test_step5_data_flows_with_provenance(self):
        """Step 5: Allowed data carries provenance linking to the contract."""
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = _registry()
            reg.create_contract(
                "wife",
                frozenset({"audio"}),
                contracts_dir=Path(tmpdir),
            )
            gate = _gate(reg)

            contract = reg.get_contract_for("wife")
            assert contract is not None

            # Data with provenance
            data = Labeled(
                value="wife speaking",
                label=ConsentLabel.bottom(),
                provenance=frozenset({contract.id}),
            )
            d = gate.check(data, person_ids=("wife",), data_category="audio")
            assert d.allowed
            assert contract.id in d.provenance

    def test_step6_revocation_cascades(self):
        """Step 6: Wife revokes consent → all her data purged."""
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = _registry()
            reg.create_contract(
                "wife",
                frozenset({"audio"}),
                contracts_dir=Path(tmpdir),
            )
            contract = reg.get_contract_for("wife")
            assert contract is not None

            # Set up carrier registry with a fact about wife
            carrier = CarrierRegistry()
            carrier.register("audio-agent", capacity=5)
            fact = CarrierFact(
                labeled=Labeled(
                    value="wife voice pattern",
                    label=ConsentLabel.bottom(),
                    provenance=frozenset({contract.id}),
                ),
                source_domain="audio",
                first_seen=0.0,
                last_seen=0.0,
            )
            carrier.offer("audio-agent", fact)
            assert len(carrier.facts("audio-agent")) == 1

            # Wire revocation
            prop = RevocationPropagator(reg)
            prop.register_carrier_registry(carrier)

            # Revoke
            report = prop.revoke("wife")
            assert report.contract_revoked
            assert report.total_purged == 1
            assert len(carrier.facts("audio-agent")) == 0

            # Gate now denies
            gate = _gate(reg)
            d = gate.check(
                _labeled("new conversation"),
                person_ids=("wife",),
                data_category="audio",
            )
            assert not d.allowed

    def test_step7_consent_reoffered_after_revocation(self):
        """Step 7: After revocation, consent can be re-offered and re-granted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = _registry()

            # Grant → revoke
            reg.create_contract("wife", frozenset({"audio"}), contracts_dir=Path(tmpdir))
            reg.purge_subject("wife")
            assert not reg.contract_check("wife", "audio")

            # Re-grant
            reg.create_contract(
                "wife",
                frozenset({"audio", "video"}),
                contract_id="contract-wife-v2",
                contracts_dir=Path(tmpdir),
            )
            assert reg.contract_check("wife", "audio")
            assert reg.contract_check("wife", "video")

    def test_granular_scope(self):
        """Guest can consent to audio but not video."""
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = _registry()
            reg.create_contract("wife", frozenset({"audio"}), contracts_dir=Path(tmpdir))
            gate = _gate(reg)

            # Audio: allowed
            d_audio = gate.check(
                _labeled("audio data"), person_ids=("wife",), data_category="audio"
            )
            assert d_audio.allowed

            # Video: denied (not in scope)
            d_video = gate.check(
                _labeled("video data"), person_ids=("wife",), data_category="video"
            )
            assert not d_video.allowed


class TestScenarioProperties(unittest.TestCase):
    """Provable properties of the complete consent scenario."""

    @given(
        person=st.text(
            alphabet=st.characters(whitelist_categories=("L",)),
            min_size=1,
            max_size=10,
        ),
        category=st.sampled_from(["audio", "video", "transcription", "presence", "biometric"]),
    )
    @settings(max_examples=100)
    def test_no_write_without_contract(self, person, category):
        """∀ person, category: gate blocks without contract.

        This is the provable 'no violations occur' property.
        """
        gate = _gate(_registry())
        d = gate.check(
            _labeled("data about person"),
            person_ids=(person,),
            data_category=category,
        )
        assert not d.allowed

    @given(
        person=st.text(
            alphabet=st.characters(whitelist_categories=("L",)),
            min_size=1,
            max_size=10,
        ),
        category=st.sampled_from(["audio", "video", "transcription", "presence", "biometric"]),
    )
    @settings(max_examples=100)
    def test_write_allowed_with_matching_contract(self, person, category):
        """∀ person, category: gate allows with matching contract."""
        c = _contract(person, frozenset({category}))
        gate = _gate(_registry(c))
        d = gate.check(
            _labeled("data"),
            person_ids=(person,),
            data_category=category,
        )
        assert d.allowed

    @given(
        incapabilities=st.frozensets(
            st.sampled_from(["can_see", "can_hear", "has_smartphone", "can_read", "motor_fine"]),
            max_size=5,
        )
    )
    @settings(max_examples=50)
    def test_consent_always_offerable(self, incapabilities):
        """∀ guest profiles: at least one consent channel is available.

        Combined with test_no_write_without_contract, this proves:
        the system never both (a) blocks data and (b) makes consent impossible.
        """
        guest = GuestContext(known_incapabilities=incapabilities)
        menu = build_channel_menu(guest=guest)
        assert menu.sufficient

    @given(
        person=st.text(
            alphabet=st.characters(whitelist_categories=("L",)),
            min_size=1,
            max_size=10,
        ),
    )
    @settings(max_examples=50)
    def test_revocation_makes_gate_deny(self, person):
        """∀ person: grant → revoke → gate denies.

        The lifecycle is complete and reversible.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = _registry()
            reg.create_contract(person, frozenset({"audio"}), contracts_dir=Path(tmpdir))
            assert (
                _gate(reg).check(_labeled("d"), person_ids=(person,), data_category="audio").allowed
            )

            reg.purge_subject(person)
            assert (
                not _gate(reg)
                .check(_labeled("d"), person_ids=(person,), data_category="audio")
                .allowed
            )
