"""First-piece custody and duplicate guards, using only synthetic private records."""

import importlib
import json

import pytest
import yaml
from agentgov import consent as portable

from shared.governance import consent
from tests.shared.synthetic_custody import CONTRACT, ENTRY, OLD_CONTRACT, PRINCIPAL, document


@pytest.mark.parametrize("alias", [False])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize(
    "change",
    [
        {"revoked_at": "2026-09-28T00:00:00Z"},
        {"parties": ["operator", "synthetic-other-subject"]},
        {"scope": ["video"]},
        {"direction": "two_way"},
        {"guardian": "synthetic-guardian"},
        {"principal_class": "child"},
        {"visibility_mechanism": "continuous"},
        {"created_at": "2026-09-27T00:00:00Z"},
    ],
)
def test_conflicting_grants_never_authorize(alias, reverse, change, tmp_path):
    first = {"id": CONTRACT, "parties": ["operator", PRINCIPAL], "scope": ["audio"]}
    second = {**first, "id": OLD_CONTRACT if alias else CONTRACT, **change}
    records = [first, second][::-1] if reverse else [first, second]
    for index, record in enumerate(records):
        (tmp_path / f"record-{index}.yaml").write_text(yaml.safe_dump(record))
    registry = consent.ConsentRegistry()
    assert registry.load(tmp_path, strict=True) == 0
    assert all(not record.active for record in registry)
    assert not registry.contract_check(PRINCIPAL, "audio")
    assert not registry.contract_check("synthetic-other-subject", "audio")


@pytest.mark.parametrize("alias", [False])
def test_identical_duplicates_preserve_consent_and_same_id_counts_once(tmp_path, alias):
    record = {"id": CONTRACT, "parties": ["operator", PRINCIPAL], "scope": ["audio"]}
    for name in ("a", "b"):
        (tmp_path / f"{name}.yaml").write_text(
            yaml.safe_dump({**record, "id": OLD_CONTRACT if alias and name == "b" else CONTRACT})
        )
    registry = consent.ConsentRegistry()
    assert registry.load(tmp_path, strict=True) == (2 if alias else 1)
    assert registry.contract_check(PRINCIPAL, "audio")


def test_custody_reader_returns_real_filestore_document(synthetic_custody):
    assert json.loads(consent._read_compatibility_document()) == document()
    snapshot = consent.load_identity_snapshot()
    assert snapshot.resolve_contract_id(OLD_CONTRACT) == CONTRACT
    assert snapshot.resolve_contract_id("synthetic-unknown") == "synthetic-unknown"


@pytest.mark.parametrize("failure", ["exception", "unreadable", "missing"])
def test_filestore_failure_is_named_and_private(failure, synthetic_custody, monkeypatch):
    api = importlib.import_module("k0.key_capture")
    if failure == "missing":
        synthetic_custody.delete(ENTRY)
    else:

        def fail(store, name):
            if failure == "exception":
                raise OSError("synthetic-private-detail")
            return None

        monkeypatch.setattr(api.FileStore, "get", fail)
    reason = "compat_missing" if failure == "missing" else "compat_unreadable"
    with pytest.raises(portable.IdentityMigrationUnavailable, match=f"^{reason}$") as caught:
        consent._read_compatibility_document()
    assert "synthetic-private-detail" not in str(caught.value)
    assert caught.value.__cause__ is None


@pytest.mark.parametrize("shape", ["duplicate-key", "missing", "extra", "duplicate-inventory"])
def test_custody_inventory_and_duplicate_keys_refuse(shape, synthetic_custody):
    data = document()
    reason = "compat_incomplete"
    if shape == "missing":
        data["inventory"].pop()
    elif shape == "extra":
        data["inventory"].append("synthetic-undeclared")
    elif shape == "duplicate-inventory":
        data["inventory"].append(data["inventory"][0])
        reason = "compat_conflict"
    raw = json.dumps(data)
    if shape == "duplicate-key":
        raw = raw.replace('"version": 1', '"version": 1, "version": 1')
        reason = "compat_conflict"
    synthetic_custody.put(ENTRY, raw.encode())
    with pytest.raises(portable.IdentityMigrationUnavailable, match=f"^{reason}$"):
        consent.load_identity_snapshot()


def test_required_estate_resolvers_name_an_unavailable_snapshot(monkeypatch):
    from contextlib import contextmanager

    @contextmanager
    def unavailable(binding):
        assert binding == consent._ESTATE_BINDING
        yield None

    monkeypatch.setattr(consent, "identity_operation", unavailable)
    for resolve in (consent.resolve_contract_id, consent.resolve_principal_id):
        with pytest.raises(portable.IdentityMigrationUnavailable, match="^compat_malformed$"):
            resolve("synthetic-unknown")
