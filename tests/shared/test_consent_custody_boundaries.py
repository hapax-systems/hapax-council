"""Synthetic witnesses for complete estate consent operations."""

from __future__ import annotations

import importlib
import json
import logging
from dataclasses import asdict

import pytest
from agentgov import consent as portable

from shared.governance import consent
from tests.shared.synthetic_custody import (
    CONTRACT,
    ENTRY,
    OLD_CONTRACT,
    OLD_PRINCIPAL,
    PRINCIPAL,
    document,
)
from tests.shared.test_principal_identifier_aliases import file_module


@pytest.mark.parametrize(
    "module_name", ["shared.governance.consent_reader", "agents._governance.consent_reader"]
)
def test_reader_recognition_revalidates_and_keeps_labels_private(
    module_name, synthetic_custody, tmp_path, caplog
):
    module = importlib.import_module(module_name)
    data = document()
    alternate = "synthetic-predecessor-alternate"
    data["principals"][alternate] = PRINCIPAL
    data["inventory"].append(alternate)
    synthetic_custody.put(ENTRY, json.dumps(data).encode())
    registry = consent.ConsentRegistry(
        _contracts={
            CONTRACT: consent.ConsentContract(
                CONTRACT, ("operator", PRINCIPAL), frozenset({"audio"})
            )
        }
    )
    reader = module.ConsentGatedReader(registry, frozenset({"operator"}), tmp_path / "audit.jsonl")
    caplog.set_level(logging.INFO)
    for label in (OLD_PRINCIPAL, alternate, PRINCIPAL):
        assert (
            reader.filter_tool_result("search_documents", f"Notes about {label}.")
            == "Notes about someone."
        )
        assert reader.decisions[-1].unconsented_count == 1
    assert (
        reader.filter_tool_result("search_documents", "No people mentioned.")
        == "No people mentioned."
    )
    assert len(reader.decisions) == 3
    for label in (OLD_PRINCIPAL, alternate):
        assert label not in (tmp_path / "audit.jsonl").read_text()
        assert label not in caplog.text
        assert label not in repr([asdict(d) for d in reader.decisions])
    synthetic_custody.delete(ENTRY)
    with pytest.raises(portable.IdentityMigrationUnavailable, match="compat_missing"):
        reader.filter_tool_result("search_documents", "No people mentioned.")


@pytest.mark.parametrize(
    "module_name", ["shared.governance.consent_gate", "agents._governance.consent_gate"]
)
def test_writer_startup_without_process_binding(
    module_name, synthetic_custody, monkeypatch, tmp_path
):
    module = importlib.import_module(module_name)
    monkeypatch.delenv("AGENTGOV_IDENTITY_MIGRATION", raising=False)
    monkeypatch.delenv("AGENTGOV_IDENTITY_PROVIDER", raising=False)
    assert portable._configured_binding is None
    directory = tmp_path / "contracts"
    registry = consent.ConsentRegistry(_contracts_dir=directory)
    registry.create_contract(PRINCIPAL, frozenset({"audio"}), contract_id=CONTRACT)
    monkeypatch.setattr(consent, "publish_health", lambda *_: None)
    monkeypatch.setattr(module, "load_contracts", lambda: consent.load_contracts(directory))
    writer = module.ConsentGatedWriter.create(audit_path=tmp_path / "writer.jsonl")
    calls = 0
    original = consent._read_compatibility_document

    def counted_read():
        nonlocal calls
        calls += 1
        return original()

    monkeypatch.setattr(consent, "_read_compatibility_document", counted_read)
    data = module.Labeled(
        "synthetic value", module.ConsentLabel.bottom(), frozenset({OLD_CONTRACT})
    )
    decision = writer.check(data, data_category="audio", person_ids=(OLD_PRINCIPAL,))
    assert decision.allowed
    assert decision.person_ids == (PRINCIPAL,)
    assert decision.provenance == (CONTRACT,)
    assert calls == 1
    assert OLD_PRINCIPAL not in (tmp_path / "writer.jsonl").read_text()
    assert OLD_CONTRACT not in (tmp_path / "writer.jsonl").read_text()


@pytest.mark.parametrize(
    "module_name", ["shared.governance.carrier", "agents._governance.carrier", "logos._carrier"]
)
def test_estate_carrier_without_process_binding(
    module_name, synthetic_custody, monkeypatch, tmp_path
):
    from agentgov.consent_label import ConsentLabel
    from agentgov.labeled import Labeled

    module = importlib.import_module(module_name)
    monkeypatch.delenv("AGENTGOV_IDENTITY_MIGRATION", raising=False)
    monkeypatch.delenv("AGENTGOV_IDENTITY_PROVIDER", raising=False)
    registry = module.CarrierRegistry()
    registry.register("synthetic-agent", 1)
    registry.offer(
        "synthetic-agent",
        module.CarrierFact(
            Labeled("value", ConsentLabel.bottom(), frozenset({OLD_CONTRACT})), "audio"
        ),
    )
    from agentgov.revocation import RevocationPropagator

    contracts = consent.ConsentRegistry(_contracts_dir=tmp_path)
    contracts.create_contract(PRINCIPAL, frozenset({"audio"}), contract_id=CONTRACT)
    propagator = RevocationPropagator(contracts)
    propagator.register_carrier_registry(registry)
    report = propagator.revoke(PRINCIPAL)
    assert report.purge_complete
    assert report.total_purged == 1


@pytest.fixture(params=["logos/_governance.py", "agents/_governance.py"])
def mirror(request):
    return file_module(request.param, "synthetic_round_six_" + request.param.split("/")[0])


@pytest.mark.parametrize("requested", [OLD_CONTRACT, CONTRACT])
def test_mirror_get_predecessor_storage(mirror, requested, synthetic_custody, tmp_path, caplog):
    caplog.set_level(logging.INFO)
    (tmp_path / f"{OLD_CONTRACT}.yaml").write_text(
        json.dumps({"id": OLD_CONTRACT, "parties": ["operator", OLD_PRINCIPAL], "scope": ["audio"]})
    )
    registry = mirror.ConsentRegistry()
    assert registry.load(tmp_path) == 1
    assert registry.get(requested).id == OLD_CONTRACT
    assert OLD_CONTRACT not in caplog.text
    assert OLD_PRINCIPAL not in caplog.text


@pytest.mark.parametrize(
    "operation", ["contract_check", "provenance", "subject_data_categories", "purge_subject"]
)
def test_mirror_decision_pins_snapshot(mirror, operation, synthetic_custody, monkeypatch):
    other_old = "synthetic-predecessor-other"
    other_new = "synthetic-successor-other"
    data = document()
    section = "contracts" if operation == "provenance" else "principals"
    old = OLD_CONTRACT if operation == "provenance" else OLD_PRINCIPAL
    new = CONTRACT if operation == "provenance" else PRINCIPAL
    data[section][other_old] = other_new
    data["inventory"].append(other_old)
    synthetic_custody.put(ENTRY, json.dumps(data).encode())
    original = consent._read_compatibility_document
    calls = 0

    def swap_after_read():
        nonlocal calls
        calls += 1
        raw = original()
        data[section].update({old: other_new, other_old: new})
        synthetic_custody.put(ENTRY, json.dumps(data).encode())
        return raw

    monkeypatch.setattr(consent, "_read_compatibility_document", swap_after_read)
    if operation != "provenance":
        registry = mirror.ConsentRegistry(
            _contracts={
                CONTRACT: mirror.ConsentContract(
                    CONTRACT, ("operator", other_old), frozenset({"audio"})
                )
            }
        )
        if operation == "contract_check":
            assert not registry.contract_check(old, "audio")
        elif operation == "subject_data_categories":
            assert registry.subject_data_categories(old) == frozenset()
        else:
            assert registry.purge_subject(old) == []
            assert registry._contracts[CONTRACT].active
    else:
        assert not mirror.ProvenanceExpr.leaf(old).evaluate(frozenset({other_old}))
    assert calls == 1


@pytest.mark.parametrize("requested", [OLD_PRINCIPAL, PRINCIPAL])
def test_enrollment_read_failure_sanitizes_both_requested_forms(
    requested, synthetic_custody, monkeypatch, tmp_path, caplog
):
    import numpy as np

    from shared import face_enrollment_registry as enrollment

    path = tmp_path / f"{OLD_PRINCIPAL}.npz"
    path.write_bytes(b"synthetic enrollment")

    def fail_read(filename):
        raise OSError(f"synthetic read error: {filename}")

    monkeypatch.setattr(np, "load", fail_read)
    assert enrollment.load_enrollment(requested, root=tmp_path) is None
    assert OLD_PRINCIPAL not in caplog.text
    assert "enrollment_read_failed" in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
