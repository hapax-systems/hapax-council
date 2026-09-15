"""Portable binding contracts; synthetic documents cross the actual provider boundary."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentgov import consent
from agentgov.carrier import CarrierFact, CarrierRegistry
from agentgov.consent_label import ConsentLabel
from agentgov.labeled import Labeled
from agentgov.provenance import ProvenanceExpr

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


def test_independent_installation_has_no_estate_imports(tmp_path):
    package_src = Path(__file__).resolve().parents[1] / "src"
    code = """
import importlib.abc
import sys
class NoEstate(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'shared', 'k0', 'reins'}:
            raise AssertionError('estate_import_forbidden')
sys.meta_path.insert(0, NoEstate())
from agentgov.consent import ConsentRegistry
from agentgov.carrier import CarrierFact, CarrierRegistry
from agentgov.consent_label import ConsentLabel
from agentgov.labeled import Labeled
from agentgov.provenance import ProvenanceExpr
from agentgov.revocation import RevocationPropagator
reg = ConsentRegistry()
reg.create_contract('synthetic-subject', frozenset({'audio'}), contract_id='synthetic-contract')
assert reg.contract_check('synthetic-subject', 'audio')
assert ProvenanceExpr.leaf('synthetic-contract').evaluate(frozenset({'synthetic-contract'}))
facts = CarrierRegistry()
facts.register('synthetic-agent', 1)
facts.offer('synthetic-agent', CarrierFact(
    Labeled('synthetic-value', ConsentLabel.bottom(), frozenset({'synthetic-contract'})), 'audio'))
prop = RevocationPropagator(reg)
prop.register_carrier_registry(facts)
assert prop.revoke('synthetic-subject').purge_complete
assert not facts.facts('synthetic-agent')
assert not any(name.split('.')[0] in {'shared', 'k0', 'reins'} for name in sys.modules)
"""
    env = {**os.environ, "PYTHONPATH": str(package_src), "AGENTGOV_IDENTITY_MIGRATION": "none"}
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("kind", ["registry", "provenance", "carrier"])
def test_operation_uses_one_provider_snapshot(kind, monkeypatch):
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
    if kind == "registry":
        assert registry().contract_check("synthetic-after-subject", "audio")
    elif kind == "provenance":
        assert ProvenanceExpr.leaf("synthetic-before-contract").evaluate(
            frozenset({"synthetic-after-contract"})
        )
    else:
        facts = CarrierRegistry()
        facts.register("synthetic-agent", 1)
        facts.offer(
            "synthetic-agent",
            CarrierFact(
                Labeled(
                    "synthetic-value",
                    ConsentLabel.bottom(),
                    frozenset({"synthetic-before-contract"}),
                ),
                "audio",
            ),
        )
        assert facts.purge_by_provenance("synthetic-after-contract") == 1
    assert calls == 1
    with pytest.raises(consent.IdentityMigrationUnavailable, match="^compat_missing$"):
        consent.resolve_contract_id("synthetic-after-contract")
