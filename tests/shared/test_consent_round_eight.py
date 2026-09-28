"""Synthetic retrieval and reason-specific refusal witnesses for round eight."""

import importlib
import json
import logging

import pytest
from agentgov import consent as portable

from shared.governance import consent
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
@pytest.mark.parametrize("spelling", [OLD_PRINCIPAL, PRINCIPAL])
@pytest.mark.parametrize("scope", ["document", "audio"])
def test_retrieval_recognition_survives_revocation_reload_and_empty_registry(
    module_name, spelling, scope, synthetic_custody, monkeypatch, tmp_path, caplog
):
    module = importlib.import_module(module_name)
    directory = tmp_path / "contracts"
    registry = consent.ConsentRegistry(_contracts_dir=directory)
    registry.create_contract(PRINCIPAL, frozenset({scope}), contract_id=CONTRACT)
    monkeypatch.setattr(module, "load_contracts", lambda: consent.load_contracts(directory))
    reader = module.ConsentGatedReader(registry, frozenset({"operator"}), tmp_path / "audit.jsonl")
    content = f"Notes about {spelling}."
    caplog.set_level(logging.INFO)
    result = reader.filter_tool_result("search_documents", content)
    assert result == (content if scope == "document" else "Notes about someone.")
    assert len(reader.decisions) == 1
    assert reader.decisions[-1].person_ids == (PRINCIPAL,)
    assert reader.decisions[-1].consented_count == int(scope == "document")
    registry.revoke_contract(CONTRACT)
    for stage in ("revoked", "reload", "empty"):
        if stage == "reload":
            reader.reload_contracts()
        elif stage == "empty":
            reader = module.ConsentGatedReader(consent.ConsentRegistry(), frozenset({"operator"}))
        before = len(reader.decisions)
        assert reader.filter_tool_result("search_documents", content) == "Notes about someone."
        assert len(reader.decisions) == before + 1
        assert reader.decisions[-1].person_ids == (PRINCIPAL,)
        assert reader.decisions[-1].unconsented_count == 1
        assert reader.decisions[-1].consented_count == 0
    snapshot = consent.load_identity_snapshot()
    assert not snapshot.contains_predecessor(caplog.text)
    assert not snapshot.contains_predecessor((tmp_path / "audit.jsonl").read_text())


@pytest.fixture
def custody_refusal(request, synthetic_custody, monkeypatch):
    reason, remedy = request.param
    snapshot = consent.load_identity_snapshot()
    if reason == "compat_missing":
        synthetic_custody.delete(ENTRY)
    elif reason == "compat_malformed":
        synthetic_custody.put(ENTRY, b"{")
    elif reason == "compat_conflict":
        synthetic_custody.put(ENTRY, b'{"version":1,"version":1}')
    elif reason == "compat_incomplete":
        data = document()
        data["inventory"].append("synthetic-unmapped-label")
        synthetic_custody.put(ENTRY, json.dumps(data).encode())
    else:
        original = portable.import_module

        def refused_provider(name):
            if name == "shared.governance.consent":
                raise ModuleNotFoundError(f"synthetic private exception: {OLD_PRINCIPAL}")
            return original(name)

        monkeypatch.setattr(portable, "import_module", refused_provider)
    return reason, remedy, snapshot


REFUSALS = [
    ("compat_missing", "restore_compat_custody"),
    ("compat_malformed", "repair_compat_document"),
    ("compat_conflict", "reconcile_compat_conflict"),
    ("compat_incomplete", "complete_compat_inventory"),
    ("identity_unconfigured", "configure_identity_binding"),
]


@pytest.mark.parametrize("custody_refusal", REFUSALS, indirect=True)
@pytest.mark.parametrize("caller", ["estate", "portable", "catching_loader"])
def test_every_custody_refusal_warns_with_reason_and_remedy(custody_refusal, caller, caplog):
    from logos.api.routes import data

    reason, remedy, snapshot = custody_refusal
    caplog.clear()
    caplog.set_level(logging.WARNING)
    if caller == "catching_loader":
        assert data._load_consent_registry() is None
        records = [record for record in caplog.records if record.name == data.__name__]
    else:
        module = consent if caller == "estate" else portable
        with pytest.raises(portable.IdentityMigrationUnavailable) as caught:
            module.resolve_principal_id(PRINCIPAL)
        assert str(caught.value) == reason
        assert caught.value.__suppress_context__
        records = caplog.records
    assert records
    assert all(record.levelno >= logging.WARNING for record in records)
    assert any(
        reason in record.message and f"remedy={remedy}" in record.message for record in records
    )
    if reason in {"compat_malformed", "identity_unconfigured"}:
        cause = "JSONDecodeError" if reason == "compat_malformed" else "ModuleNotFoundError"
        assert any(f"cause_class={cause}" in record.message for record in records)
    assert not snapshot.contains_predecessor(caplog.text)
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.parametrize("custody_refusal", REFUSALS, indirect=True)
@pytest.mark.parametrize("surface", ["briefing", "nudges"])
async def test_public_catching_path_warns_before_empty_response(
    custody_refusal, surface, monkeypatch, caplog
):
    from logos.api.routes import data

    reason, remedy, snapshot = custody_refusal
    monkeypatch.setattr(data, "is_publicly_visible", lambda: True)
    items = [{"action": "synthetic action", "detail": "synthetic detail"}]
    monkeypatch.setattr(
        data.cache, surface, {"action_items": items} if surface == "briefing" else items
    )
    caplog.clear()
    response = await getattr(data, f"get_{surface}")()
    result = json.loads(response.body)
    assert (result["action_items"] if surface == "briefing" else result) == []
    assert any(
        record.name == data.__name__
        and record.levelno >= logging.WARNING
        and reason in record.message
        and f"remedy={remedy}" in record.message
        for record in caplog.records
    )
    assert not snapshot.contains_predecessor(caplog.text)
