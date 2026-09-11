"""Private custody validation with an isolated, wholly synthetic FileStore.

The custody fixture itself lives in tests/shared/synthetic_custody.py and is
autouse for the whole tree through the conftests; this module tests it.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from agentgov import consent as portable

from shared.governance import consent

# The `synthetic_custody` fixture the tests below request by name is the plugin
# fixture registered from tests/conftest.py (tests/shared/synthetic_custody.py).
from tests.shared.synthetic_custody import (
    CONTRACT,
    ENTRY,
    INSTALLED_API_ABSENT,
    OLD_CONTRACT,
    OLD_PRINCIPAL,
    PRINCIPAL,
    UNKNOWN_CONTRACT,
    UNKNOWN_PRINCIPAL,
    document,
    installed_api,
    installed_api_present,
)


def test_installed_api_is_present():
    """One named failure, with the remedy, where the consent-bound suites cannot run.

    The estate registry is bound `required` and reads its custody document through
    the installed reins API; without it every identity operation refuses. This test
    turns that into one explicit failure instead of a scatter of setup errors.
    """
    assert installed_api_present(), INSTALLED_API_ABSENT.format(api=installed_api())


@pytest.mark.parametrize("side", ["estate", "portable"])
@pytest.mark.parametrize("kind", ["principal", "contract"])
def test_unknown_identifiers_resolve_exactly_required(side, kind, synthetic_custody):
    module = consent if side == "estate" else portable
    candidate = UNKNOWN_PRINCIPAL if kind == "principal" else UNKNOWN_CONTRACT
    assert getattr(module, f"resolve_{kind}_id")(candidate) == candidate


@pytest.mark.parametrize("kind", ["principal", "contract"])
def test_portable_unknown_provider_none_is_exact(kind, synthetic_custody, monkeypatch):
    method = f"resolve_{kind}_id"
    original = getattr(consent._CorrespondenceSnapshot, method)

    def unknown_as_none(snapshot, candidate):
        resolved = original(snapshot, candidate)
        return None if resolved == candidate else resolved

    monkeypatch.setattr(consent._CorrespondenceSnapshot, method, unknown_as_none)
    candidate = UNKNOWN_PRINCIPAL if kind == "principal" else UNKNOWN_CONTRACT
    assert getattr(portable, method)(candidate) == candidate


@pytest.mark.parametrize("side", ["estate", "portable"])
@pytest.mark.parametrize("kind", ["principal", "contract"])
def test_unknown_identifiers_refuse_missing_document(side, kind, synthetic_custody):
    module = consent if side == "estate" else portable
    candidate = UNKNOWN_PRINCIPAL if kind == "principal" else UNKNOWN_CONTRACT
    synthetic_custody.delete(ENTRY)
    with pytest.raises(portable.IdentityMigrationUnavailable, match="^compat_missing$"):
        getattr(module, f"resolve_{kind}_id")(candidate)


@pytest.mark.parametrize("side", ["estate", "portable"])
def test_unknown_identifiers_match_both_registry_sides(side, synthetic_custody):
    module = consent if side == "estate" else portable
    contract = portable.ConsentContract(
        UNKNOWN_CONTRACT, ("operator", UNKNOWN_PRINCIPAL), frozenset({"audio"})
    )
    registry = module.ConsentRegistry(_contracts={UNKNOWN_CONTRACT: contract})
    assert registry.get(UNKNOWN_CONTRACT) is contract
    assert registry.get_contract_for(UNKNOWN_PRINCIPAL) is contract
    assert registry.contract_check(UNKNOWN_PRINCIPAL, "audio")


@pytest.mark.parametrize("side", ["estate", "portable"])
@pytest.mark.parametrize("known", [False, True])
def test_revoke_nonexistent_preserves_requested_id(side, known, synthetic_custody):
    module = consent if side == "estate" else portable
    candidate = CONTRACT if known else UNKNOWN_CONTRACT
    with pytest.raises(KeyError) as caught:
        module.ConsentRegistry().revoke_contract(candidate)
    assert caught.value.args == (f"Contract {candidate} not registered",)


@pytest.mark.parametrize("side", ["estate", "portable"])
@pytest.mark.parametrize("kind", ["principal", "contract"])
def test_revoke_nonexistent_predecessor_is_sanitized(side, kind, synthetic_custody):
    module = consent if side == "estate" else portable
    candidate = OLD_PRINCIPAL if kind == "principal" else OLD_CONTRACT
    with pytest.raises(KeyError) as caught:
        module.ConsentRegistry().revoke_contract(candidate)
    assert caught.value.args == ("consent_contract_unregistered",)
    assert candidate not in str(caught.value)


@pytest.mark.parametrize("side", ["estate", "portable"])
@pytest.mark.parametrize("strict", [False, True])
def test_unknown_contract_load_preserves_parse_error(
    side, strict, synthetic_custody, tmp_path, caplog, monkeypatch
):
    module = consent if side == "estate" else portable
    path = tmp_path / f"{UNKNOWN_CONTRACT}.yaml"
    path.write_text(f"id: {UNKNOWN_CONTRACT}\nparties: [operator]\n")
    api = importlib.import_module("k0.key_capture")
    original = api.FileStore.get
    reads = []

    def read(store, entry):
        reads.append(True)
        return original(store, entry)

    monkeypatch.setattr(api.FileStore, "get", read)
    registry = module.ConsentRegistry()
    if strict:
        with pytest.raises(portable.ConsentContractLoadError) as caught:
            registry.load(tmp_path, strict=True)
        assert path.name in str(caught.value)
        assert isinstance(caught.value.__cause__, ValueError)
        assert "exactly 2 parties" in str(caught.value.__cause__)
    else:
        assert registry.load(tmp_path) == 0
        assert any(path.name in record.getMessage() for record in caplog.records)
    assert reads == [True]


@pytest.mark.parametrize("side", ["estate", "portable"])
@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("exposure", ["filename", "parser"])
def test_predecessor_load_diagnostics_are_sanitized(
    side, strict, exposure, synthetic_custody, tmp_path, caplog
):
    import traceback

    import yaml

    module = consent if side == "estate" else portable
    if exposure == "filename":
        path = tmp_path / f"{OLD_CONTRACT}.yaml"
        path.write_text("parties: [operator]\n")
    else:
        path = tmp_path / f"{UNKNOWN_CONTRACT}.yaml"
        path.write_text(f"parties: [{OLD_PRINCIPAL}] unexpected\n")
        with pytest.raises(yaml.YAMLError) as parse_error:
            yaml.safe_load(path.read_text())
        assert OLD_PRINCIPAL in str(parse_error.value)
    registry = module.ConsentRegistry()
    if strict:
        with pytest.raises(portable.ConsentContractLoadError) as caught:
            registry.load(tmp_path, strict=True)
        assert str(caught.value) == "consent_contract_malformed"
        assert caught.value.__cause__ is None
        assert caught.value.__suppress_context__
        diagnostic = "".join(traceback.format_exception(caught.value))
        assert OLD_PRINCIPAL not in diagnostic
        assert OLD_CONTRACT not in diagnostic
    else:
        assert registry.load(tmp_path) == 0
    assert OLD_PRINCIPAL not in caplog.text
    assert OLD_CONTRACT not in caplog.text


@pytest.mark.parametrize(
    "payload,reason",
    [
        (b"{", "compat_malformed"),
        (b"[]", "compat_malformed"),
        (b'{"version":1,"version":1}', "compat_conflict"),
        (b'{"version":true}', "compat_malformed"),
        (b'{"version":2}', "compat_malformed"),
    ],
)
def test_invalid_document_refuses(payload, reason, synthetic_custody):
    synthetic_custody.put(ENTRY, payload)
    with pytest.raises(portable.IdentityMigrationUnavailable, match=f"^{reason}$"):
        portable.resolve_principal_id(PRINCIPAL)


@pytest.mark.parametrize(
    "change,reason",
    [
        (lambda d: d.update(principals={}), "compat_malformed"),
        (lambda d: d.update(contracts=[]), "compat_malformed"),
        (lambda d: d.update(inventory=[]), "compat_malformed"),
        (lambda d: d["principals"].update({OLD_PRINCIPAL: 1}), "compat_malformed"),
        (lambda d: d["principals"].update({OLD_PRINCIPAL: OLD_PRINCIPAL}), "compat_conflict"),
        (lambda d: d["contracts"].update({OLD_CONTRACT: OLD_PRINCIPAL}), "compat_conflict"),
        (lambda d: d["contracts"].update({OLD_PRINCIPAL: CONTRACT}), "compat_conflict"),
        (lambda d: d["inventory"].append(OLD_PRINCIPAL), "compat_conflict"),
        (lambda d: d["inventory"].append("synthetic-uncovered"), "compat_incomplete"),
        (lambda d: d["inventory"].pop(), "compat_incomplete"),
    ],
)
def test_validation_requires_complete_consistent_inventory(change, reason, synthetic_custody):
    data = document()
    change(data)
    synthetic_custody.put(ENTRY, json.dumps(data).encode())
    with pytest.raises(portable.IdentityMigrationUnavailable, match=f"^{reason}$"):
        consent.resolve_contract_id(CONTRACT)


@pytest.mark.parametrize("damage", ["missing", "integrity", "key_missing", "key_invalid"])
def test_unavailable_store_never_initializes_key(damage, synthetic_custody, monkeypatch):
    store = synthetic_custody
    key = store.root / ".key"
    if damage == "missing":
        store.delete(ENTRY)
    elif damage == "integrity":
        (store.root / f"{ENTRY}.bin").write_bytes(b"synthetic-corrupt-blob")
    elif damage == "key_missing":
        key.unlink()
    else:
        key.write_bytes(b"synthetic-invalid-key")
    original = key.read_bytes() if key.exists() else None
    api = importlib.import_module("k0.key_capture")

    initialization_calls = []

    def forbid_initialization(self):
        initialization_calls.append(True)
        raise AssertionError("initializing_accessor_called")

    monkeypatch.setattr(api.FileStore, "_key", forbid_initialization)
    reason = "compat_missing" if damage == "missing" else "compat_unreadable"
    with pytest.raises(portable.IdentityMigrationUnavailable, match=f"^{reason}$"):
        consent.resolve_principal_id(PRINCIPAL)
    assert (key.read_bytes() if key.exists() else None) == original
    assert not initialization_calls


def test_absent_store_root_is_not_created(synthetic_custody, monkeypatch, tmp_path):
    root = tmp_path / "absent-custody"
    monkeypatch.setenv("REINS_SECRET_STORE", str(root))
    with pytest.raises(portable.IdentityMigrationUnavailable, match="^compat_missing$"):
        consent.resolve_principal_id(PRINCIPAL)
    assert not root.exists()


def test_read_error_is_sanitized(synthetic_custody, monkeypatch):
    original = Path.read_bytes

    def deny(path):
        if path.name == ".key":
            raise PermissionError("synthetic-private-detail")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", deny)
    with pytest.raises(portable.IdentityMigrationUnavailable) as caught:
        consent.resolve_principal_id(PRINCIPAL)
    assert str(caught.value) == "compat_unreadable"
    assert caught.value.__suppress_context__


def test_no_stale_snapshot_across_operations(synthetic_custody, tmp_path):
    registry = consent.ConsentRegistry(_contracts_dir=tmp_path / "contracts")
    registry.create_contract(PRINCIPAL, frozenset({"audio"}), contract_id=CONTRACT)
    assert registry.contract_check(OLD_PRINCIPAL, "audio")
    synthetic_custody.delete(ENTRY)
    for operation in (
        lambda: registry.contract_check(PRINCIPAL, "audio"),
        lambda: registry.get(CONTRACT),
        lambda: registry.load(tmp_path / "contracts"),
        lambda: registry.revoke_contract(CONTRACT),
    ):
        with pytest.raises(portable.IdentityMigrationUnavailable, match="^compat_missing$"):
            operation()


def test_two_sides_share_one_read(synthetic_custody, monkeypatch):
    api = importlib.import_module("k0.key_capture")
    original = api.FileStore.get
    calls = 0

    def read_once(store, name):
        nonlocal calls
        calls += 1
        raw = original(store, name)
        synthetic_custody.delete(ENTRY)
        return raw

    registry = consent.ConsentRegistry(
        _contracts={
            OLD_CONTRACT: consent.ConsentContract(
                OLD_CONTRACT, ("operator", OLD_PRINCIPAL), frozenset({"audio"})
            )
        }
    )
    monkeypatch.setattr(api.FileStore, "get", read_once)
    assert registry.contract_check(PRINCIPAL, "audio")
    assert calls == 1
    with pytest.raises(portable.IdentityMigrationUnavailable, match="^compat_missing$"):
        registry.contract_check(PRINCIPAL, "audio")
    assert calls == 2


def test_missing_installed_api_refuses(synthetic_custody, monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "k0.key_capture", None)
    with pytest.raises(portable.IdentityMigrationUnavailable, match="^compat_unreadable$"):
        consent.resolve_contract_id(CONTRACT)


@pytest.mark.parametrize("cause", ["missing", "unreadable", "malformed", "conflict", "incomplete"])
def test_required_causes_refuse_lifecycle(cause, synthetic_custody, monkeypatch, tmp_path):
    from functools import partial

    import numpy as np
    from agentgov.carrier import CarrierFact, CarrierRegistry
    from agentgov.consent_label import ConsentLabel
    from agentgov.labeled import Labeled
    from agentgov.revocation import RevocationPropagator

    from agents.studio_compositor import consent as recording
    from shared import face_enrollment_registry as enrollment
    from tests.shared.test_principal_identifier_aliases import file_module, recording_fixture

    cli = file_module("scripts/hapax-guest-consent", "synthetic_unavailable_cli")
    source = file_module("scripts/screwm-guest-source.py", "synthetic_unavailable_source")
    directory = tmp_path / "contracts"
    monkeypatch.setenv("HAPAX_GUEST_CONSENT_DIR", str(directory))
    registry = consent.ConsentRegistry(_contracts_dir=directory)
    registry.create_contract(
        PRINCIPAL, frozenset({"face_enrollment", "world_render"}), contract_id=CONTRACT
    )
    embedding = np.ones(512, dtype=np.float32)
    enrollment_path = enrollment.enroll_principal(
        PRINCIPAL, embedding, consent=registry, root=tmp_path
    )
    compositor, segments = recording_fixture(tmp_path, OLD_CONTRACT, monkeypatch)
    facts = CarrierRegistry()
    facts.register("synthetic-agent", 1)
    facts.offer(
        "synthetic-agent",
        CarrierFact(
            Labeled("synthetic-value", ConsentLabel.bottom(), frozenset({OLD_CONTRACT})), "audio"
        ),
    )
    cascade = RevocationPropagator(registry)
    cascade.register_carrier_registry(facts)
    cascade.register_handler("recordings", partial(recording.purge_video_recordings, compositor))
    if cause == "missing":
        synthetic_custody.delete(ENTRY)
    elif cause == "unreadable":
        (synthetic_custody.root / ".key").unlink()
    elif cause == "malformed":
        synthetic_custody.put(ENTRY, b"{")
    elif cause == "conflict":
        synthetic_custody.put(ENTRY, b'{"version":1,"version":1}')
    else:
        data = document()
        data["inventory"].append("synthetic-uncovered")
        synthetic_custody.put(ENTRY, json.dumps(data).encode())
    for operation in (
        lambda: registry.get(CONTRACT),
        lambda: registry.get_contract_for(PRINCIPAL),
        lambda: registry.contract_check(PRINCIPAL, "world_render"),
        lambda: registry.revoke_contract(CONTRACT),
        lambda: cli.cmd_grant(PRINCIPAL),
        lambda: cli.cmd_revoke(PRINCIPAL),
        lambda: cascade.revoke(PRINCIPAL),
        lambda: facts.purge_by_provenance(CONTRACT),
        lambda: enrollment.enroll_principal(PRINCIPAL, embedding, consent=registry, root=tmp_path),
        lambda: enrollment.load_enrollment(PRINCIPAL, root=tmp_path),
        lambda: enrollment.match_principal(embedding, root=tmp_path),
        lambda: enrollment.revoke_enrollment(PRINCIPAL, root=tmp_path),
    ):
        with pytest.raises(portable.IdentityMigrationUnavailable, match=f"^compat_{cause}$"):
            operation()
    assert not source.consented(PRINCIPAL, directory)
    result = recording.purge_video_recordings(compositor, CONTRACT)
    assert not result.purge_complete
    assert result.failures == (f"compat_{cause}",)
    assert all(path.exists() for path in segments)
    assert enrollment_path.exists()
    assert facts.facts("synthetic-agent")
    assert (directory / f"{CONTRACT}.yaml").exists()
    assert registry.active_contracts
