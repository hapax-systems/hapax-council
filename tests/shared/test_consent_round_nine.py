"""Synthetic witnesses for recognition, label comparison, and atomic refresh."""

import importlib
import json
from pathlib import Path

import pytest
from agentgov.consent import ConsentContractLoadError

from shared.governance import consent
from shared.governance.revocation import RevocationPropagator
from tests.shared.synthetic_custody import (
    CONTRACT,
    ENTRY,
    OLD_PRINCIPAL,
    PRINCIPAL,
    document,
)


@pytest.mark.parametrize(
    "module_name", ["shared.governance.consent_reader", "agents._governance.consent_reader"]
)
@pytest.mark.parametrize("boundary", ["retrieval", "filter"])
def test_canonical_only_recognition_survives_revocation(
    module_name, boundary, synthetic_custody, monkeypatch, tmp_path
):
    module = importlib.import_module(module_name)
    principal = "synthetic-opaque-only-principal"
    cid = "synthetic-opaque-only-grant"
    doc = document()
    doc["contracts"]["synthetic-historical-opaque-grant"] = cid
    doc["inventory"].append("synthetic-historical-opaque-grant")
    synthetic_custody.put(ENTRY, json.dumps(doc).encode())
    monkeypatch.setattr(consent, "REGISTERED_PRINCIPALS", frozenset({principal}))
    monkeypatch.setattr(module, "REGISTERED_PRINCIPALS", consent.REGISTERED_PRINCIPALS)
    snapshot = consent.load_identity_snapshot()
    assert principal not in snapshot.principals
    assert principal not in snapshot.principals.values()
    directory = tmp_path / "contracts"
    registry = consent.ConsentRegistry(_contracts_dir=directory)
    registry.create_contract(principal, frozenset({"document"}), contract_id=cid)
    monkeypatch.setattr(module, "load_contracts", lambda: consent.load_contracts(directory))
    reader = module.ConsentGatedReader(registry, frozenset({"operator"}))
    content = f"Notes about {principal}."

    def retrieve():
        if boundary == "retrieval":
            return reader.filter_tool_result("search_documents", content)
        return reader.filter(
            module.RetrievedDatum(content, frozenset(), "document", "synthetic-source")
        ).filtered_content

    assert retrieve() == content
    assert reader.decisions[-1].person_ids == (principal,)
    registry.revoke_contract(cid)
    for stage in ("revoked", "reload", "empty"):
        if stage == "reload":
            reader.reload_contracts()
        elif stage == "empty":
            reader = module.ConsentGatedReader(
                consent.ConsentRegistry(_contracts_dir=None), frozenset({"operator"})
            )
        before = len(reader.decisions)
        assert retrieve() == "Notes about someone."
        assert len(reader.decisions) == before + 1
        assert reader.decisions[-1].person_ids == (principal,)
        assert reader.decisions[-1].unconsented_count == 1


@pytest.mark.parametrize(
    "module_name", ["shared.governance.consent_reader", "agents._governance.consent_reader"]
)
def test_vocabulary_reuses_callers_snapshot(module_name, synthetic_custody, monkeypatch):
    module = importlib.import_module(module_name)
    original = consent._read_compatibility_document
    reads = []

    def read_once():
        reads.append(True)
        raw = original()
        synthetic_custody.delete(ENTRY)
        return raw

    monkeypatch.setattr(consent, "_read_compatibility_document", read_once)
    reader = module.ConsentGatedReader(
        consent.ConsentRegistry(_contracts_dir=None), frozenset({"operator"})
    )
    with consent.estate_identity_operation():
        vocabulary = reader._build_known_persons()
        assert {OLD_PRINCIPAL, PRINCIPAL} <= vocabulary
        assert vocabulary >= module.REGISTERED_PRINCIPALS
        assert reader.filter_tool_result("search_documents", f"Notes about {PRINCIPAL}.") == (
            "Notes about someone."
        )
    assert len(reads) == 1


@pytest.mark.parametrize(
    "module_name", ["agentgov.consent_label", "agents._governance.consent_label"]
)
def test_mixed_labels_compare_canonical_policies(module_name, synthetic_custody):
    label = importlib.import_module(module_name).ConsentLabel
    old = label(frozenset({(OLD_PRINCIPAL, frozenset({"operator", OLD_PRINCIPAL}))}))
    new = label(frozenset({(PRINCIPAL, frozenset({"operator", PRINCIPAL}))}))
    mixed = label(frozenset({(OLD_PRINCIPAL, frozenset({"operator", PRINCIPAL}))}))
    different = label(frozenset({(PRINCIPAL, frozenset({"operator"}))}))
    assert old.can_flow_to(new)
    assert new.can_flow_to(old)
    assert mixed.can_flow_to(new) and new.can_flow_to(mixed)
    assert not old.can_flow_to(different)
    assert not old.can_flow_to(label.bottom())
    assert label.bottom().can_flow_to(old)


@pytest.mark.parametrize("failure", ["file", "directory", "missing"])
def test_refresh_refuses_unreadable_contracts_without_shrinking(
    failure, synthetic_custody, monkeypatch, tmp_path, caplog
):
    directory = tmp_path / "contracts"
    registry = consent.ConsentRegistry(_contracts_dir=directory)
    registry.create_contract(PRINCIPAL, frozenset({"audio"}), contract_id=CONTRACT)
    prop = RevocationPropagator(registry)
    before = dict(registry._contracts)
    original_read = Path.read_text
    original_iter = Path.iterdir

    def denied_read(path, *args, **kwargs):
        if path.parent == directory:
            raise PermissionError(f"synthetic refusal {OLD_PRINCIPAL}")
        return original_read(path, *args, **kwargs)

    def denied_directory(path):
        if path == directory:
            raise PermissionError(f"synthetic refusal {OLD_PRINCIPAL}")
        return original_iter(path)

    with monkeypatch.context() as patch:
        if failure == "file":
            patch.setattr(Path, "read_text", denied_read)
        elif failure == "directory":
            patch.setattr(Path, "iterdir", denied_directory)
        else:
            patch.setattr(registry, "_contracts_dir", tmp_path / "unavailable")
        with pytest.raises(ConsentContractLoadError, match="^consent_refresh_unavailable$"):
            prop.refresh_contracts()
        assert registry._contracts == before
        assert registry.contract_check(PRINCIPAL, "audio")
    assert OLD_PRINCIPAL not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
    registry.revoke_contract(CONTRACT)
    prop.refresh_contracts()
    assert registry.active_contracts == []  # A readable empty directory is valid.
