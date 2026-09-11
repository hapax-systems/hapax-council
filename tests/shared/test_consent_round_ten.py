"""Contract guests and the independent migration vocabulary must both be recognized."""

import importlib
from pathlib import Path

import pytest

from shared.governance import consent
from tests.shared.synthetic_custody import ENTRY, OLD_PRINCIPAL, PRINCIPAL

GUEST = "synthetic-ordinary-guest"
REGISTERED = "principal-a1"
UNRELATED = "synthetic-unrelated-string"


@pytest.fixture(params=["shared.governance.consent_reader", "agents._governance.consent_reader"])
def reader_module(request):
    return importlib.import_module(request.param)


def guest_registry():
    contract = consent.ConsentContract(
        "synthetic-guest-video-grant", ("operator", GUEST), frozenset({"video"})
    )
    return consent.ConsentRegistry(_contracts={contract.id: contract}, _contracts_dir=None)


def test_video_only_guest_is_recognized_in_document_search(reader_module, synthetic_custody):
    snapshot = consent.load_identity_snapshot()
    assert GUEST not in snapshot.principals
    assert GUEST not in snapshot.principals.values()
    assert GUEST not in consent.REGISTERED_PRINCIPALS
    registry = guest_registry()
    assert registry.contract_check(GUEST, "video")
    assert not registry.contract_check(GUEST, "document")
    reader = reader_module.ConsentGatedReader(registry, frozenset({"operator"}))
    text = f"Notes about {GUEST}."

    result = reader.filter_tool_result("search_documents", text)

    assert len(reader.decisions) == 1
    assert result != text
    assert result == "Notes about someone."
    assert GUEST not in result
    decision = reader.decisions[0]
    assert decision.person_ids == (GUEST,)
    assert decision.degradation_level == 2
    assert decision.unconsented_count == 1
    assert decision.consented_count == 0
    assert not registry.contract_check(GUEST, "document")


def test_registered_principal_is_recognized_without_contracts(reader_module, synthetic_custody):
    snapshot = consent.load_identity_snapshot()
    assert REGISTERED in consent.REGISTERED_PRINCIPALS
    assert REGISTERED not in snapshot.principals
    assert REGISTERED not in snapshot.principals.values()
    registry = consent.ConsentRegistry(_contracts_dir=None)
    assert registry.active_contracts == []
    reader = reader_module.ConsentGatedReader(registry, frozenset({"operator"}))

    assert reader.filter_tool_result("search_documents", f"Notes about {REGISTERED}.") == (
        "Notes about someone."
    )
    assert len(reader.decisions) == 1
    assert reader.decisions[0].person_ids == (REGISTERED,)
    assert reader.decisions[0].unconsented_count == 1
    assert not registry.contract_check(REGISTERED, "document")


def test_unrelated_string_is_not_recognized(reader_module, synthetic_custody):
    reader = reader_module.ConsentGatedReader(guest_registry(), frozenset({"operator"}))
    assert UNRELATED not in reader._build_known_persons()
    text = f"Notes about {UNRELATED}."

    assert reader.filter_tool_result("search_documents", text) == text
    assert reader.decisions == []


@pytest.mark.parametrize("principal", [REGISTERED, OLD_PRINCIPAL])
def test_unreadable_registry_keeps_independent_recognition(
    principal, reader_module, synthetic_custody, monkeypatch, tmp_path
):
    directory = tmp_path / "unreadable-contracts"
    directory.mkdir()
    original = Path.glob

    def denied(path, *args, **kwargs):
        if path == directory:
            raise PermissionError("synthetic contract directory refusal")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "glob", denied)
    registry = consent.ConsentRegistry(_contracts_dir=directory)
    assert registry.load(directory) == 0
    assert registry.fail_closed
    assert not registry.contract_check(principal, "document")
    reader = reader_module.ConsentGatedReader(registry, frozenset({"operator"}))
    text = f"Notes about {principal}."

    result = reader.filter_tool_result("search_documents", text)

    assert len(reader.decisions) == 1
    assert result != text
    assert result == "Notes about someone."
    assert reader.decisions[0].person_ids == (REGISTERED if principal == REGISTERED else PRINCIPAL,)
    assert reader.decisions[0].unconsented_count == 1
    assert reader._build_known_persons() >= {REGISTERED, OLD_PRINCIPAL, PRINCIPAL}


def test_union_uses_one_snapshot_and_excludes_only_contract_operators(
    reader_module, synthetic_custody, monkeypatch
):
    registry = guest_registry()
    operator_alias = "synthetic-operator-alias"
    registry._contracts["synthetic-operator-grant"] = consent.ConsentContract(
        "synthetic-operator-grant", ("operator", operator_alias), frozenset({"video"})
    )
    reader = reader_module.ConsentGatedReader(
        registry, frozenset({"operator", operator_alias, PRINCIPAL})
    )
    original = consent._read_compatibility_document
    reads = []

    def read_once():
        reads.append(True)
        raw = original()
        synthetic_custody.delete(ENTRY)
        return raw

    monkeypatch.setattr(consent, "_read_compatibility_document", read_once)
    vocabulary = reader._build_known_persons()

    assert {GUEST, REGISTERED, OLD_PRINCIPAL, PRINCIPAL} <= vocabulary
    assert "operator" not in vocabulary
    assert operator_alias not in vocabulary
    assert reads == [True]
