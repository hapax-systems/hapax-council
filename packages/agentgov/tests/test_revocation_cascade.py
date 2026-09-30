"""The revocation cascade's failure, retry and identity branches.

The re-land rewrites revocation and purge: ``revoke()`` and ``retry_purge()``, the
``PurgeResult`` / ``RevocationReport`` failure semantics, the ``record_purge_*`` pair with
``pending_purges()``, and the identity resolution threaded into
``carrier.purge_by_provenance``, ``consent_label.can_flow_to`` and ``ProvenanceExpr.evaluate``.
Each complex branch gets a test that would go red if the branch were removed: a persistence
failure, a partial retry, a handler that is no longer registered, and the outstanding-contract
bookkeeping the retry reads back.
"""

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
from agentgov.consent import ConsentContract, ConsentRegistry
from agentgov.consent_label import ConsentLabel
from agentgov.labeled import Labeled
from agentgov.provenance import ProvenanceExpr
from agentgov.revocation import PurgeResult, RevocationPropagator, RevocationReport

_OLD_PRINCIPAL = "synthetic-predecessor-subject"
_NEW_PRINCIPAL = "synthetic-successor-subject"
_OLD_CONTRACT = "synthetic-predecessor-contract"
_NEW_CONTRACT = "synthetic-successor-contract"

_CORRESPONDENCE = {
    "principals": {_OLD_PRINCIPAL: _NEW_PRINCIPAL},
    "contracts": {_OLD_CONTRACT: _NEW_CONTRACT},
}


def load_identity_snapshot():
    """The provider this module declares; only the three identity tests select it."""
    return SimpleNamespace(
        resolve_principal_id=lambda value: _CORRESPONDENCE["principals"].get(value, value),
        resolve_contract_id=lambda value: _CORRESPONDENCE["contracts"].get(value, value),
    )


@pytest.fixture(autouse=True)
def exact_binding(monkeypatch):
    """No ambient custody here: exact identifiers unless a test selects a provider."""
    monkeypatch.setattr(consent, "_configured_binding", None)
    monkeypatch.setenv("AGENTGOV_IDENTITY_MIGRATION", "none")
    monkeypatch.delenv("AGENTGOV_IDENTITY_PROVIDER", raising=False)


def _registry(*contract_ids: str) -> ConsentRegistry:
    return ConsentRegistry(
        _contracts={
            contract_id: ConsentContract(
                contract_id, ("operator", _NEW_PRINCIPAL), frozenset({"audio"})
            )
            for contract_id in contract_ids
        }
    )


def _report(*contract_ids: str) -> RevocationReport:
    return RevocationReport(
        contract_id=",".join(contract_ids),
        person_id=_NEW_PRINCIPAL,
        contract_revoked=True,
        purge_results=(),
        retry_contract_ids=contract_ids,
    )


# ── Persistence failure ─────────────────────────────────────────────────


def test_a_persistence_failure_stays_revoked_and_names_the_outstanding_contract(monkeypatch):
    """Unsafe case: a revoke that cannot persist is reported complete, or restores consent."""
    registry = _registry("synthetic-contract-one", "synthetic-contract-two")
    real = ConsentRegistry.revoke_contract
    calls = {"n": 0}

    def flaky(self, contract_id, **kwargs):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise OSError("contract storage is read-only")
        return real(self, contract_id, **kwargs)

    monkeypatch.setattr(ConsentRegistry, "revoke_contract", flaky)

    report = RevocationPropagator(registry).revoke(_NEW_PRINCIPAL)

    assert report.contract_revoked is True
    assert report.purge_complete is False
    # The contract that did persist is revoked; the one that did not is outstanding.
    assert registry.get("synthetic-contract-one").active is False
    assert report.retry_revocation_ids == ("synthetic-contract-two",)
    assert "synthetic-contract-two" in report.retry_contract_ids
    assert "contract_persistence" in {r.subsystem for r in report.purge_results if r.failures}


def test_retry_completes_a_persistence_failure_without_reactivating_consent(monkeypatch):
    registry = _registry("synthetic-contract-one", "synthetic-contract-two")
    real = ConsentRegistry.revoke_contract
    calls = {"n": 0}

    def flaky(self, contract_id, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("contract storage is read-only")
        return real(self, contract_id, **kwargs)

    monkeypatch.setattr(ConsentRegistry, "revoke_contract", flaky)
    propagator = RevocationPropagator(registry)
    first = propagator.revoke(_NEW_PRINCIPAL)
    assert first.purge_complete is False

    monkeypatch.setattr(ConsentRegistry, "revoke_contract", real)  # storage recovers
    second = propagator.retry_purge(first)

    assert second.purge_complete is True
    assert second.retry_contract_ids == ()
    assert registry.get("synthetic-contract-two").active is False


# ── Partial retry and the outstanding-contract readback ─────────────────


def test_a_partial_retry_resolves_only_the_contracts_it_completed(tmp_path: Path):
    """Unsafe case: one completed contract clears the whole person's obligation."""
    audit = tmp_path / "purge.log"
    propagator = RevocationPropagator(_registry())
    report = _report("synthetic-contract-one", "synthetic-contract-two")

    propagator.record_purge_pending(report, audit)
    assert propagator.pending_purges(audit) == {
        _NEW_PRINCIPAL: ("synthetic-contract-one", "synthetic-contract-two")
    }

    propagator.record_purge_complete(_NEW_PRINCIPAL, ("synthetic-contract-one",), audit)
    assert propagator.pending_purges(audit) == {_NEW_PRINCIPAL: ("synthetic-contract-two",)}

    propagator.record_purge_complete(_NEW_PRINCIPAL, ("synthetic-contract-two",), audit)
    assert propagator.pending_purges(audit) == {}


def test_pending_purges_leaves_an_existing_archive_entry_alone(tmp_path: Path):
    audit = tmp_path / "purge.log"
    audit.write_text(
        json.dumps({"ts": "2026-09-28T00:00:00+00:00", "event": "archive_purge"}) + "\n",
        encoding="utf-8",
    )
    assert RevocationPropagator(_registry()).pending_purges(audit) == {}


def test_pending_purges_is_empty_without_an_audit_file(tmp_path: Path):
    assert RevocationPropagator(_registry()).pending_purges(tmp_path / "absent.log") == {}


def test_an_unwritable_audit_path_is_a_named_error(tmp_path: Path):
    blocked = tmp_path / "audit-dir"
    blocked.write_text("a file where the audit directory would be", encoding="utf-8")
    propagator = RevocationPropagator(_registry())
    with pytest.raises(RuntimeError, match="^purge_audit_unwritten$"):
        propagator.record_purge_complete(
            _NEW_PRINCIPAL, ("synthetic-contract",), blocked / "purge.log"
        )


# ── A handler that is gone, and one that returns nonsense ───────────────


def test_retry_reports_a_handler_that_is_no_longer_registered():
    """Unsafe case: a dropped handler is read as a completed purge."""
    registry = _registry("synthetic-contract")

    def store_offline(_contract_id: str) -> int:
        raise RuntimeError("store offline")

    propagator = RevocationPropagator(registry)
    propagator.register_handler("ephemeral-store", store_offline)
    first = propagator.revoke(_NEW_PRINCIPAL)
    assert first.purge_complete is False
    assert first.retry_contract_ids

    fresh = RevocationPropagator(registry)  # nothing registered after the reload
    second = fresh.retry_purge(first)

    assert second.purge_complete is False
    assert "ephemeral-store" in {r.subsystem for r in second.purge_results}
    assert any("purge_handler_missing" in r.failures for r in second.purge_results)


def test_a_handler_returning_a_non_count_is_a_failure_not_a_success():
    registry = _registry("synthetic-contract")
    propagator = RevocationPropagator(registry)
    propagator.register_handler("confused-store", lambda _contract_id: "purged")

    report = propagator.revoke(_NEW_PRINCIPAL)

    assert report.purge_complete is False
    results = [r for r in report.purge_results if r.subsystem == "confused-store"]
    assert results and isinstance(results[0], PurgeResult)
    assert results[0].failures == ("purge_invalid",)
    assert results[0].items_purged == 0


def test_a_handler_returning_an_invalid_structured_count_is_a_failure():
    registry = _registry("synthetic-contract")
    propagator = RevocationPropagator(registry)
    propagator.register_handler(
        "structured-store",
        lambda _contract_id: PurgeResult("ignored", -1),
    )

    report = propagator.revoke(_NEW_PRINCIPAL)

    result = next(r for r in report.purge_results if r.subsystem == "structured-store")
    assert result.items_purged == 0
    assert result.failures == ("purge_invalid",)
    assert report.purge_complete is False


def test_refresh_contracts_replaces_the_registry_from_durable_storage(tmp_path: Path):
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "synthetic-contract.yaml").write_text(
        "id: synthetic-contract\nparties: [operator, synthetic-successor-subject]\n"
        "scope: [audio]\n",
        encoding="utf-8",
    )
    registry = ConsentRegistry(_contracts_dir=contracts)
    propagator = RevocationPropagator(registry)

    propagator.refresh_contracts()

    assert registry.get("synthetic-contract") is not None
    assert registry.contract_check(_NEW_PRINCIPAL, "audio") is True


def test_refresh_contracts_keeps_known_grants_when_storage_cannot_be_read(tmp_path: Path):
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("not a directory", encoding="utf-8")
    registry = ConsentRegistry(
        _contracts={
            "synthetic-contract": ConsentContract(
                "synthetic-contract",
                ("operator", _NEW_PRINCIPAL),
                frozenset({"audio"}),
            ),
        },
        _contracts_dir=blocked,
    )
    propagator = RevocationPropagator(registry)

    with pytest.raises(consent.ConsentContractLoadError, match="^consent_refresh_unavailable$"):
        propagator.refresh_contracts()

    assert registry.get("synthetic-contract") is not None
    assert registry.contract_check(_NEW_PRINCIPAL, "audio") is True


# ── Identity resolution threaded through the three layers ───────────────


def test_identity_resolution_is_threaded_through_carrier_label_and_provenance():
    consent.configure_identity_migration("required", __name__)

    facts = CarrierRegistry()
    facts.register("synthetic-agent", 2)
    # One fact carries each spelling of the same contract, so the count pins both sides of
    # the resolution: the queried id (``_OLD_CONTRACT``) and each fact's provenance.
    for value, contract in (("synthetic-old", _OLD_CONTRACT), ("synthetic-new", _NEW_CONTRACT)):
        facts.offer(
            "synthetic-agent",
            CarrierFact(
                Labeled(value, ConsentLabel.bottom(), frozenset({contract})),
                "audio",
            ),
        )
    assert facts.purge_by_provenance(_OLD_CONTRACT) == 2

    source = ConsentLabel(frozenset({(_OLD_PRINCIPAL, frozenset({_OLD_PRINCIPAL}))}))
    target = ConsentLabel(frozenset({(_NEW_PRINCIPAL, frozenset({_NEW_PRINCIPAL}))}))
    assert source.can_flow_to(target) is True

    assert ProvenanceExpr.leaf(_OLD_CONTRACT).evaluate(frozenset({_NEW_CONTRACT})) is True


@pytest.mark.parametrize("kind", ["provenance", "carrier"])
def test_a_consumer_operation_uses_one_provider_snapshot(kind, monkeypatch):
    """The consumers share the operation's snapshot instead of resolving twice.

    The registry's own snapshot scope is covered in ``test_consent_binding.py``; this is the
    consumer side, whose resolution code lands here.
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
    if kind == "provenance":
        assert ProvenanceExpr.leaf(_OLD_CONTRACT).evaluate(frozenset({_NEW_CONTRACT}))
    else:
        facts = CarrierRegistry()
        facts.register("synthetic-agent", 1)
        facts.offer(
            "synthetic-agent",
            CarrierFact(
                Labeled("synthetic-value", ConsentLabel.bottom(), frozenset({_OLD_CONTRACT})),
                "audio",
            ),
        )
        assert facts.purge_by_provenance(_NEW_CONTRACT) == 1
    assert calls == 1
    with pytest.raises(consent.IdentityMigrationUnavailable, match="^compat_missing$"):
        consent.resolve_contract_id(_NEW_CONTRACT)


def test_a_complete_installation_runs_without_estate_imports(tmp_path: Path):
    """The package's full revoke-and-purge path needs no shared/, k0/ or reins import."""
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
