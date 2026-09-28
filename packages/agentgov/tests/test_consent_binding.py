"""Portable binding contracts; synthetic documents cross the actual provider boundary."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from agentgov import consent

_DOCUMENT = json.dumps(
    {
        "principals": {"synthetic-before-subject": "synthetic-after-subject"},
        "contracts": {"synthetic-before-contract": "synthetic-after-contract"},
    }
)


def load_identity_snapshot():
    data = json.loads(_DOCUMENT)
    return SimpleNamespace(
        resolve_principal_id=lambda value: data["principals"].get(value, value),
        resolve_contract_id=lambda value: data["contracts"].get(value, value),
    )


@pytest.fixture(autouse=True)
def explicit_binding(monkeypatch):
    monkeypatch.setattr(consent, "_configured_binding", None)
    monkeypatch.delenv("AGENTGOV_IDENTITY_MIGRATION", raising=False)
    monkeypatch.delenv("AGENTGOV_IDENTITY_PROVIDER", raising=False)


def registry():
    return consent.ConsentRegistry(
        _contracts={
            "synthetic-before-contract": consent.ConsentContract(
                "synthetic-before-contract",
                ("operator", "synthetic-before-subject"),
                frozenset({"audio"}),
            )
        }
    )


@pytest.mark.parametrize("mode", [None, "", "unknown", "NONE", " required"])
def test_unconfigured_never_means_exact(mode, monkeypatch):
    if mode is not None:
        monkeypatch.setenv("AGENTGOV_IDENTITY_MIGRATION", mode)
    reg = registry()
    with pytest.raises(consent.IdentityMigrationUnavailable, match="^identity_unconfigured$"):
        reg.contract_check("synthetic-before-subject", "audio")
    with pytest.raises(consent.IdentityMigrationUnavailable, match="^identity_unconfigured$"):
        reg.get("synthetic-before-contract")


@pytest.mark.parametrize("provider", [None, "", "synthetic_missing_provider"])
def test_required_never_falls_through(provider, monkeypatch):
    monkeypatch.setenv("AGENTGOV_IDENTITY_MIGRATION", "required")
    if provider is not None:
        monkeypatch.setenv("AGENTGOV_IDENTITY_PROVIDER", provider)
    reg = registry()
    with pytest.raises(consent.IdentityMigrationUnavailable, match="^identity_unconfigured$"):
        reg.contract_check("synthetic-before-subject", "audio")


def test_required_import_error_is_sanitized(monkeypatch):
    consent.configure_identity_migration("required", "synthetic_provider")

    def unavailable(name):
        raise RuntimeError("synthetic-private-detail")

    monkeypatch.setattr(consent, "import_module", unavailable)
    with pytest.raises(consent.IdentityMigrationUnavailable) as caught:
        registry().get("synthetic-before-contract")
    assert str(caught.value) == "identity_unconfigured"
    assert caught.value.__suppress_context__


def test_required_valid_resolves_both_sides(monkeypatch):
    consent.configure_identity_migration("required", __name__)
    reg = registry()
    assert reg.contract_check("synthetic-after-subject", "audio")
    assert reg.get("synthetic-after-contract").id == "synthetic-before-contract"
    reg._contracts = {
        "synthetic-after-contract": consent.ConsentContract(
            "synthetic-after-contract",
            ("operator", "synthetic-after-subject"),
            frozenset({"audio"}),
        )
    }
    assert reg.contract_check("synthetic-before-subject", "audio")
    assert reg.get("synthetic-before-contract").id == "synthetic-after-contract"


def test_none_is_exact(monkeypatch):
    monkeypatch.setenv("AGENTGOV_IDENTITY_MIGRATION", "none")
    reg = registry()
    assert reg.contract_check("synthetic-before-subject", "audio")
    assert not reg.contract_check("synthetic-after-subject", "audio")
    assert reg.get("synthetic-after-contract") is None


def test_operation_uses_one_provider_snapshot(monkeypatch):
    """A compound registry operation loads one snapshot and shares it across nested calls.

    The consumers that resolve through this binding (``carrier.purge_by_provenance``,
    ``ProvenanceExpr.evaluate`` and ``ConsentLabel.can_flow_to``) are covered where their
    code lands, in ``test_revocation_cascade.py``.
    """
    consent.configure_identity_migration("required", __name__)
    original = load_identity_snapshot
    calls = 0

    def once():
        nonlocal calls
        calls += 1
        if calls > 1:
            raise consent.IdentityMigrationUnavailable("compat_missing")
        return original()

    monkeypatch.setattr(sys.modules[__name__], "load_identity_snapshot", once)
    assert registry().contract_check("synthetic-after-subject", "audio")
    assert calls == 1
    with pytest.raises(consent.IdentityMigrationUnavailable, match="^compat_missing$"):
        consent.resolve_contract_id("synthetic-after-contract")


def test_load_time_alias_conflict_fails_closed(tmp_path: Path) -> None:
    """Unsafe case: a revoked successor beside an active predecessor, after a restore, a copy or
    a partial migration. Every reader grants through any *active* member, so the live pair would
    authorize a flow the operator already revoked; load must fail closed on the group instead."""
    consent.configure_identity_migration("required", __name__)
    (tmp_path / "synthetic-before-contract.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "synthetic-before-contract",
                "parties": ["operator", "synthetic-before-subject"],
                "scope": ["audio"],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "synthetic-after-contract.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "synthetic-after-contract",
                "parties": ["operator", "synthetic-after-subject"],
                "scope": ["audio"],
                "revoked_at": "2026-09-28T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    registry = consent.ConsentRegistry()
    registry.load(tmp_path)

    assert registry.contract_check("synthetic-after-subject", "audio") is False
    assert registry.contract_check("synthetic-before-subject", "audio") is False
    assert registry.get_contract_for("synthetic-after-subject") is None
    assert registry.subject_data_categories("synthetic-after-subject") == frozenset()


def test_load_keeps_an_unconflicted_group_usable(tmp_path: Path) -> None:
    """The conflict rule narrows to the group: an unrelated principal's contract still grants."""
    consent.configure_identity_migration("required", __name__)
    (tmp_path / "synthetic-after-contract.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "synthetic-after-contract",
                "parties": ["operator", "synthetic-after-subject"],
                "scope": ["audio"],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "synthetic-unrelated-contract.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "synthetic-unrelated-contract",
                "parties": ["operator", "synthetic-unrelated-subject"],
                "scope": ["audio"],
            }
        ),
        encoding="utf-8",
    )
    registry = consent.ConsentRegistry()
    registry.load(tmp_path)
    assert registry.contract_check("synthetic-after-subject", "audio") is True
    assert registry.contract_check("synthetic-unrelated-subject", "audio") is True


@pytest.mark.parametrize(
    "revoked_name, active_name", [("a-revoked", "b-active"), ("a-active", "b-revoked")]
)
def test_same_id_duplicate_revoked_and_active_fails_closed(
    tmp_path: Path, revoked_name: str, active_name: str
) -> None:
    """A later same-id file must never overwrite a revoked record and grant consent."""
    consent.configure_identity_migration("required", __name__)
    for name, revoked_at in ((revoked_name, "2026-09-28T00:00:00+00:00"), (active_name, None)):
        payload = {
            "id": "synthetic-duplicate-contract",
            "parties": ["operator", "synthetic-after-subject"],
            "scope": ["audio"],
        }
        if revoked_at is not None:
            payload["revoked_at"] = revoked_at
        (tmp_path / f"{name}.yaml").write_text(yaml.safe_dump(payload), encoding="utf-8")

    registry = consent.ConsentRegistry()
    registry.load(tmp_path)

    assert registry.contract_check("synthetic-after-subject", "audio") is False
    assert registry.get_contract_for("synthetic-after-subject") is None


def test_same_id_identical_duplicate_collapses_without_revoking(tmp_path: Path) -> None:
    consent.configure_identity_migration("required", __name__)
    payload = {
        "id": "synthetic-identical-contract",
        "parties": ["operator", "synthetic-after-subject"],
        "scope": ["audio"],
    }
    for name in ("a-first", "b-copy"):
        (tmp_path / f"{name}.yaml").write_text(yaml.safe_dump(payload), encoding="utf-8")

    registry = consent.ConsentRegistry()
    assert registry.load(tmp_path) == 1
    assert registry.contract_check("synthetic-after-subject", "audio") is True


def test_purge_subject_exposes_revoked_and_pending_ids_on_persistence_failure(monkeypatch):
    monkeypatch.setenv("AGENTGOV_IDENTITY_MIGRATION", "none")
    registry = consent.ConsentRegistry(
        _contracts={
            "synthetic-first-contract": consent.ConsentContract(
                "synthetic-first-contract",
                ("operator", "synthetic-after-subject"),
                frozenset({"audio"}),
            ),
            "synthetic-second-contract": consent.ConsentContract(
                "synthetic-second-contract",
                ("operator", "synthetic-after-subject"),
                frozenset({"audio"}),
            ),
        }
    )
    real = consent.ConsentRegistry.revoke_contract
    calls = 0

    def flaky(self, contract_id, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("storage unavailable")
        return real(self, contract_id, **kwargs)

    monkeypatch.setattr(consent.ConsentRegistry, "revoke_contract", flaky)
    with pytest.raises(consent.SubjectPurgeIncomplete) as caught:
        registry.purge_subject("synthetic-after-subject")
    assert caught.value.revoked_ids == ("synthetic-first-contract",)
    assert caught.value.pending_ids == ("synthetic-second-contract",)


def test_private_load_error_sanitizes_a_predecessor_path(tmp_path: Path) -> None:
    consent.configure_identity_migration("required", __name__)
    path = tmp_path / "synthetic-before-contract.yaml"
    path.write_text("id: [malformed\n", encoding="utf-8")

    registry = consent.ConsentRegistry()
    with pytest.raises(consent.ConsentContractLoadError, match="^consent_contract_malformed$"):
        registry.load(tmp_path, strict=True)
