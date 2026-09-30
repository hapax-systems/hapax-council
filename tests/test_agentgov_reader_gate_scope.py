"""Unit pins for the agents reader, writer gate and registry lookup boundary."""

from __future__ import annotations

from agentgov import consent as portable_consent

from agents._governance.consent import ConsentContract, ConsentRegistry
from agents._governance.consent_gate import ConsentGatedWriter
from agents._governance.consent_label import ConsentLabel
from agents._governance.consent_reader import ConsentGatedReader, RetrievedDatum
from agents._governance.governor import GovernorWrapper, consent_output_policy
from agents._governance.labeled import Labeled

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


def test_reader_partitions_canonical_consented_and_unconsented_ids(tmp_path, monkeypatch):
    import shared.governance.consent as custody

    original_snapshot = custody.load_identity_snapshot()
    assert original_snapshot.predecessor_labels(NEW_PERSON) == {OLD_PERSON}
    assert original_snapshot.mentioned_principal_ids(f"{OLD_PERSON} {NEW_PERSON}") == {NEW_PERSON}

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

    allowed = reader.filter(
        RetrievedDatum(
            "synthetic-successor-subject",
            frozenset({OLD_PERSON}),
            "audio",
            "synthetic-source",
        )
    )
    denied = reader.filter(
        RetrievedDatum(
            "synthetic-unregistered-subject",
            frozenset({"synthetic-unregistered-subject"}),
            "audio",
            "synthetic-source",
        )
    )

    assert allowed.person_ids == (NEW_PERSON,)
    assert allowed.consented_count == 1
    assert allowed.unconsented_count == 0
    assert denied.unconsented_count == 1
    assert denied.degradation_level == 2


def test_registry_lookup_resolves_predecessor_contract_and_subject_ids():
    registry = _registry()

    assert registry.get(OLD_CONTRACT).id == NEW_CONTRACT
    assert registry.contract_check(OLD_PERSON, "audio") is True
    assert registry.get_contract_for(OLD_PERSON).id == NEW_CONTRACT
    assert registry.subject_data_categories(OLD_PERSON) == frozenset({"audio"})


def test_writer_gate_allows_canonicalized_person_and_denies_revoked_provenance():
    registry = _registry()
    governor = GovernorWrapper("synthetic-agent")
    governor.add_output_policy(consent_output_policy(ConsentLabel.bottom()))
    gate = ConsentGatedWriter(registry, governor)

    allowed = gate.check(
        Labeled("synthetic-value", ConsentLabel.bottom(), frozenset()),
        data_category="audio",
        person_ids=(OLD_PERSON,),
    )
    revoked_registry = ConsentRegistry(
        _contracts={
            NEW_CONTRACT: ConsentContract(
                NEW_CONTRACT,
                ("operator", NEW_PERSON),
                frozenset({"audio"}),
                revoked_at="2026-09-28T00:00:00+00:00",
            )
        }
    )
    revoked_gate = ConsentGatedWriter(revoked_registry, governor)
    denied = revoked_gate.check(
        Labeled("synthetic-value", ConsentLabel.bottom(), frozenset({OLD_CONTRACT})),
        data_category="audio",
        person_ids=(OLD_PERSON,),
    )

    assert allowed.allowed is True
    assert allowed.person_ids == (NEW_PERSON,)
    assert denied.allowed is False
    assert denied.provenance == (NEW_CONTRACT,)
