"""Synthetic witnesses for unchanged retrieval and actionable custody refusals."""

import importlib
import json
import logging
import sys

import pytest

from shared.governance import consent
from tests.shared.synthetic_custody import (
    ENTRY,
    OLD_PRINCIPAL,
    PRINCIPAL,
    document,
    installed_api,
)


@pytest.fixture(params=["shared.governance.consent_reader", "agents._governance.consent_reader"])
def reader_module(request):
    return importlib.import_module(request.param)


def test_substring_is_not_a_person(reader_module, synthetic_custody, tmp_path, monkeypatch):
    data = document()
    data["principals"]["syn"] = PRINCIPAL
    data["inventory"].append("syn")
    synthetic_custody.put(ENTRY, json.dumps(data).encode())
    registry = consent.ConsentRegistry()
    calls = []
    monkeypatch.setattr(registry, "contract_check", lambda *args: calls.append(args) or False)
    reader = reader_module.ConsentGatedReader(registry, frozenset({"operator"}))
    content = "A synapse spans this sentence.\r\nSpacing stays:  two."
    assert reader.filter_tool_result("search_documents", content).encode() == content.encode()
    assert reader.decisions == []
    assert calls == []


@pytest.mark.parametrize("operator", [False, True])
def test_whole_word_preserves_original_and_canonical_partition(
    reader_module, operator, synthetic_custody, tmp_path, monkeypatch, caplog
):
    registry = consent.ConsentRegistry()
    calls = []
    monkeypatch.setattr(registry, "contract_check", lambda *args: calls.append(args) or True)
    audit_path = tmp_path / "reader.jsonl"
    reader = reader_module.ConsentGatedReader(
        registry, frozenset({OLD_PRINCIPAL}) if operator else frozenset({"operator"}), audit_path
    )
    content = f"A whole word: {OLD_PRINCIPAL.upper()}.\r\nUnchanged  spacing."
    datum = reader_module.RetrievedDatum(
        content, frozenset({OLD_PRINCIPAL, PRINCIPAL}), "document", "synthetic-source"
    )
    decision = reader.filter(datum)
    assert decision.filtered_content.encode() == content.encode()
    assert datum.content == content
    assert decision.person_ids == (PRINCIPAL,)
    assert decision.consented_count == 1
    assert decision.unconsented_count == 0
    assert calls == ([] if operator else [(PRINCIPAL, "document")])
    snapshot = consent.load_identity_snapshot()
    assert not snapshot.contains_predecessor(audit_path.read_text().lower())
    assert not snapshot.contains_predecessor(caplog.text.lower())


def test_unlisted_predecessor_is_gated_from_original_content(
    reader_module, synthetic_custody, monkeypatch, tmp_path, caplog
):
    # No contracts and no initial IDs: extraction must consult the entire label set.
    registry = consent.ConsentRegistry()
    calls = []
    monkeypatch.setattr(registry, "contract_check", lambda *args: calls.append(args) or False)
    reader = reader_module.ConsentGatedReader(
        registry, frozenset({"operator"}), tmp_path / "reader.jsonl"
    )
    content = f"Notes about {OLD_PRINCIPAL}."
    original_degrade = reader_module.degrade
    degradation_inputs = []

    def observe_degradation(text, identifiers, category):
        degradation_inputs.append(text)
        return original_degrade(text, identifiers, category)

    monkeypatch.setattr(reader_module, "degrade", observe_degradation)
    caplog.set_level(logging.INFO)
    datum = reader_module.RetrievedDatum(content, frozenset(), "document", "synthetic-source")
    decision = reader.filter(datum)
    assert decision.person_ids == (PRINCIPAL,)
    assert decision.unconsented_count == 1
    assert decision.filtered_content == "Notes about someone."
    assert reader.filter_tool_result("search_documents", content) == decision.filtered_content
    assert degradation_inputs == [content, content]
    assert calls == [(PRINCIPAL, "document"), (PRINCIPAL, "document")]
    snapshot = consent.load_identity_snapshot()
    assert not snapshot.contains_predecessor((tmp_path / "reader.jsonl").read_text())
    assert not snapshot.contains_predecessor(caplog.text)


@pytest.mark.parametrize("failure", ["import", "integrity", "message"])
def test_custody_failure_warns_with_safe_cause(
    failure, synthetic_custody, monkeypatch, tmp_path, caplog
):
    snapshot = consent.load_identity_snapshot()
    if failure == "import":
        api = installed_api()
        monkeypatch.setenv("HAPAX_REINS_API", str(tmp_path / "missing-api"))
        monkeypatch.setattr(sys, "path", [p for p in sys.path if p != str(api)])
        for name in list(sys.modules):
            if name == "k0" or name.startswith("k0."):
                monkeypatch.delitem(sys.modules, name)
        expected = "ModuleNotFoundError"
    elif failure == "integrity":
        (synthetic_custody.root / f"{ENTRY}.bin").write_bytes(b"synthetic corrupt bytes")
        expected = "CompatibilityIntegrityError"
    else:
        module = importlib.import_module("k0.key_capture")

        def failed_read(*args):
            raise PermissionError(f"{tmp_path}/{OLD_PRINCIPAL}: synthetic private exception")

        monkeypatch.setattr(module.FileStore, "get", failed_read)
        expected = "PermissionError"
    with pytest.raises(consent.IdentityMigrationUnavailable) as caught:
        consent.resolve_principal_id(PRINCIPAL)
    assert str(caught.value) == "compat_unreadable"
    assert caught.value.cause_class == expected
    assert caught.value.__suppress_context__
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings
    assert expected in caplog.text
    assert "remedy=restore_compat_custody" in caplog.text
    if failure == "import":
        assert "missing_module=k0" in caplog.text
    assert str(tmp_path) not in caplog.text
    assert "synthetic corrupt bytes" not in caplog.text
    assert "synthetic private exception" not in caplog.text
    assert not snapshot.contains_predecessor(caplog.text)
    assert not snapshot.contains_predecessor(str(caught.value))
    assert all(record.exc_info is None for record in caplog.records)
