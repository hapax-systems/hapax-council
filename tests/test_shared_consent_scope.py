"""Unit pins for shared reader custody scope and canonical gate provenance."""

from __future__ import annotations

from agentgov import consent as portable_consent

from shared.governance.consent import ConsentContract, ConsentRegistry
from shared.governance.consent_gate import ConsentGatedWriter
from shared.governance.consent_label import ConsentLabel
from shared.governance.consent_reader import ConsentGatedReader, RetrievedDatum
from shared.governance.governor import GovernorWrapper, consent_output_policy
from shared.governance.labeled import Labeled

OLD_PERSON = "synthetic-predecessor-subject"
NEW_PERSON = "synthetic-successor-subject"
OLD_CONTRACT = "synthetic-predecessor-contract"
NEW_CONTRACT = "synthetic-successor-contract"


def _registry() -> ConsentRegistry:
    return ConsentRegistry(
        _contracts={
            NEW_CONTRACT: ConsentContract(
                NEW_CONTRACT,
                ("operator", NEW_PERSON),
                frozenset({"audio"}),
            )
        }
    )


def test_shared_reader_degradation_uses_the_snapshot_partition(tmp_path, monkeypatch):
    import shared.governance.consent as custody

    original_snapshot = custody.load_identity_snapshot()

    class ScopeCheckingSnapshot:
        principals = original_snapshot.principals
        contracts = original_snapshot.contracts

        def resolve_principal_id(self, value):
            return original_snapshot.resolve_principal_id(value)

        def resolve_contract_id(self, value):
            return original_snapshot.resolve_contract_id(value)

        def mentioned_principal_ids(self, content):
            return original_snapshot.mentioned_principal_ids(content)

        def predecessor_labels(self, value):
            assert portable_consent._identity_snapshot.get() is not None
            return original_snapshot.predecessor_labels(value)

    monkeypatch.setattr(custody, "load_identity_snapshot", lambda: ScopeCheckingSnapshot())
    reader = ConsentGatedReader(_registry(), frozenset(), tmp_path / "reader.jsonl")

    decision = reader.filter(
        RetrievedDatum(
            "synthetic-unregistered-subject",
            frozenset({"synthetic-unregistered-subject"}),
            "audio",
            "synthetic-source",
        )
    )

    assert decision.allowed is True
    assert decision.degradation_level == 2
    assert decision.unconsented_count == 1


def test_shared_gate_resolves_both_provenance_id_spellings_to_canonical():
    registry = _registry()
    governor = GovernorWrapper("synthetic-agent")
    governor.add_output_policy(consent_output_policy(ConsentLabel.bottom()))
    gate = ConsentGatedWriter(registry, governor)

    decision = gate.check(
        Labeled(
            "synthetic-value",
            ConsentLabel.bottom(),
            frozenset({OLD_CONTRACT}),
        ),
        data_category="audio",
        person_ids=(OLD_PERSON,),
    )

    assert decision.allowed is True
    assert decision.provenance == (NEW_CONTRACT,)


def test_shared_gate_accepts_a_canonical_provenance_when_active():
    registry = _registry()
    governor = GovernorWrapper("synthetic-agent")
    governor.add_output_policy(consent_output_policy(ConsentLabel.bottom()))
    gate = ConsentGatedWriter(registry, governor)

    data = Labeled(
        "synthetic-value",
        ConsentLabel.bottom(),
        frozenset({NEW_CONTRACT}),
    )
    decision = gate.check(data, data_category="audio", person_ids=(NEW_PERSON,))

    assert decision.allowed is True
    assert decision.provenance == (NEW_CONTRACT,)
