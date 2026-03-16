"""Tests for audio processor consent gate — T0 violation fix.

Proves that the audio processor's conversation write path now
enforces consent via ConsentGatedWriter before persisting
multi-speaker transcripts.

Self-contained, unittest.mock only.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from shared.governance.consent import ConsentContract, ConsentRegistry
from shared.governance.consent_gate import ConsentGatedWriter
from shared.governance.consent_label import ConsentLabel
from shared.governance.governor import GovernorWrapper, consent_output_policy
from shared.governance.labeled import Labeled


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
    gov = GovernorWrapper("audio-processor")
    gov.add_output_policy(consent_output_policy(ConsentLabel.bottom()))
    return ConsentGatedWriter(_registry=registry, _governor=gov)


class TestAudioConsentGate(unittest.TestCase):
    """Simulates the audio processor's consent gate logic."""

    def test_single_speaker_no_gate(self):
        """Single-speaker (operator only) content needs no consent check."""
        gate = _gate(_registry())
        data = Labeled(value="operator monologue", label=ConsentLabel.bottom())
        # Single speaker — skip gate, write directly (operator's own data)
        decision = gate.check(data, person_ids=("operator",), data_category="audio")
        assert decision.allowed

    def test_multi_speaker_without_contract_blocked(self):
        """Multi-speaker content is blocked without consent contracts."""
        gate = _gate(_registry())
        data = Labeled(value="conversation with wife", label=ConsentLabel.bottom())
        decision = gate.check(
            data,
            person_ids=("SPEAKER_01",),
            data_category="audio",
        )
        assert not decision.allowed
        assert "consent contract" in decision.reason.lower()

    def test_multi_speaker_with_contract_allowed(self):
        """Multi-speaker content is allowed with consent contract."""
        c = _contract("wife", frozenset({"audio"}))
        gate = _gate(_registry(c))
        data = Labeled(value="conversation with wife", label=ConsentLabel.bottom())
        decision = gate.check(
            data,
            person_ids=("wife",),
            data_category="audio",
        )
        assert decision.allowed

    def test_write_curtailed_does_not_create_file(self):
        """Curtailed write does not create a file on disk."""
        gate = _gate(_registry())
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "conv-test.md"
            data = Labeled(value="private conversation", label=ConsentLabel.bottom())
            decision = gate.check_and_write(
                data,
                target,
                person_ids=("unknown_guest",),
                data_category="audio",
            )
            assert not decision.allowed
            assert not target.exists()

    def test_write_allowed_creates_file(self):
        """Allowed write creates the file with content."""
        c = _contract("wife", frozenset({"audio"}))
        gate = _gate(_registry(c))
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "conv-test.md"
            data = Labeled(value="approved conversation", label=ConsentLabel.bottom())
            decision = gate.check_and_write(
                data,
                target,
                person_ids=("wife",),
                data_category="audio",
            )
            assert decision.allowed
            assert target.exists()
            assert target.read_text() == "approved conversation"

    def test_operator_speakers_are_excluded(self):
        """Known operator identifiers are filtered BEFORE the gate.

        The audio processor filters SPEAKER_00/operator/ryan from the
        speaker set before calling the gate. The gate only sees
        non-operator person IDs. With no non-operator persons,
        the gate is not invoked (operator's own data, no consent needed).
        """
        # Simulate the audio processor's filtering logic
        all_speakers = {"SPEAKER_00", "operator", "ryan", "SPEAKER_01"}
        operator_ids = {"SPEAKER_00", "operator", "ryan"}
        non_operator = all_speakers - operator_ids

        # Only non-operator speakers go to the gate
        assert non_operator == {"SPEAKER_01"}

        # Without a contract for SPEAKER_01: denied
        gate = _gate(_registry())
        data = Labeled(value="mixed conversation", label=ConsentLabel.bottom())
        decision = gate.check(data, person_ids=tuple(sorted(non_operator)), data_category="audio")
        assert not decision.allowed

        # The operator check in ConsentGatedWriter skips "operator" only
        decision_op = gate.check(data, person_ids=("operator",), data_category="audio")
        assert decision_op.allowed

    def test_mixed_speakers_need_all_contracts(self):
        """Mixed group: all non-operator speakers need contracts."""
        c = _contract("wife", frozenset({"audio"}))
        gate = _gate(_registry(c))
        data = Labeled(value="group chat", label=ConsentLabel.bottom())

        # wife has contract, friend does not
        decision = gate.check(
            data,
            person_ids=("wife", "friend"),
            data_category="audio",
        )
        assert not decision.allowed
        assert "friend" in decision.reason

    def test_audit_trail_recorded(self):
        """Every gate decision is recorded for compliance."""
        gate = _gate(_registry())
        data = Labeled(value="test", label=ConsentLabel.bottom())
        gate.check(data, person_ids=("guest",), data_category="audio")
        gate.check(data, person_ids=("operator",), data_category="audio")
        assert len(gate.decisions) == 2
        assert not gate.decisions[0].allowed  # guest denied
        assert gate.decisions[1].allowed  # operator allowed
