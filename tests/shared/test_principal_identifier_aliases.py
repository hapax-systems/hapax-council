"""Migration pins use synthetic predecessor identifiers exclusively."""

from __future__ import annotations

import ast
import hashlib
import importlib
import importlib.util
import re
import sys
from pathlib import Path

import pytest
import yaml

from shared.governance import consent

ROOT = Path(__file__).resolve().parents[2]
PRINCIPAL = "principal-c1"
CONTRACT = "contract-principal-c1"
OLD_PRINCIPAL = "synthetic-predecessor-subject"
OLD_CONTRACT = "synthetic-predecessor-contract"
UNKNOWN = "synthetic-unregistered-contract"
CONTRACTS = (
    CONTRACT,
    "contract-principal-c2",
    "contract-principal-a1-2026-04-19",
    "contract-principal-a1-enroll-2026-04-19",
)


def digest(value):
    return hashlib.sha256(("principal-alias-v1:" + value).encode()).hexdigest()


@pytest.fixture
def aliases(monkeypatch):
    monkeypatch.setitem(consent._PRINCIPAL_ALIASES, digest(OLD_PRINCIPAL), PRINCIPAL)
    monkeypatch.setitem(consent._CONTRACT_ALIASES, digest(OLD_CONTRACT), CONTRACT)


def file_module(path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("principal", ["principal-c1", "principal-c2", "principal-a1"])
def test_opaque_principal_resolution(principal):
    assert consent.resolve_principal_id(principal) == principal


@pytest.mark.parametrize("contract", CONTRACTS)
def test_opaque_contract_resolution(contract):
    assert consent.resolve_contract_id(contract) == contract


def test_digest_resolution(aliases):
    assert consent.resolve_principal_id(OLD_PRINCIPAL) == PRINCIPAL
    assert consent.resolve_contract_id(OLD_CONTRACT) == CONTRACT
    assert consent.is_child_principal(OLD_PRINCIPAL)


def test_unregistered_resolution():
    for candidate in (UNKNOWN, digest(UNKNOWN), "", "principal-z99"):
        assert consent.resolve_principal_id(candidate) is None
        assert consent.resolve_contract_id(candidate) is None


@pytest.mark.parametrize("contract_id", CONTRACTS)
def test_contract_schema_and_digests(contract_id):
    path = ROOT / "axioms/contracts" / f"{contract_id}.yaml"
    assert path.exists(), "successor contract is missing"
    data = yaml.safe_load(path.read_text())
    assert data["schema_version"] == 2
    assert data["id"] == contract_id
    assert consent.parse_contract(data).id == contract_id
    assert all(re.fullmatch(r"(?:principal-[a-z][0-9]+|operator)", p) for p in data["parties"])
    for kind, registry in (
        ("principals", consent._PRINCIPAL_ALIASES),
        ("contracts", consent._CONTRACT_ALIASES),
    ):
        aliases = data["predecessor_aliases"][kind]
        assert aliases
        for successor, hashes in aliases.items():
            assert hashes
            for value in hashes:
                assert re.fullmatch(r"[0-9a-f]{64}", value)
                assert registry[value] == successor


@pytest.mark.parametrize(
    "path", ["agents/_governance.py", "logos/_governance.py", "agents/_governance/consent.py"]
)
def test_mirrors_import_authoritative_set(path):
    tree = ast.parse((ROOT / path).read_text())
    names = {"REGISTERED_CHILD_PRINCIPALS", "REGISTERED_PRINCIPALS"}
    imported = {
        alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "shared.governance.consent"
        for alias in node.names
    }
    assert names <= imported
    for node in tree.body:
        targets = (
            node.targets
            if isinstance(node, ast.Assign)
            else [node.target]
            if isinstance(node, ast.AnnAssign)
            else []
        )
        assert not any(isinstance(target, ast.Name) and target.id in names for target in targets)
    module = file_module(path, "alias_mirror_" + path.replace("/", "_").replace(".", "_"))
    assert module.REGISTERED_CHILD_PRINCIPALS is consent.REGISTERED_CHILD_PRINCIPALS
    assert module.REGISTERED_PRINCIPALS is consent.REGISTERED_PRINCIPALS


@pytest.mark.parametrize(
    "module_name",
    [
        "shared.governance.consent",
        "agents._governance.consent",
        "logos._governance",
        "agents/_governance.py",
    ],
)
def test_consent_lookup_and_subject_purge(module_name, aliases):
    module = (
        file_module(module_name, "alias_agents_flat_consent")
        if "/" in module_name
        else importlib.import_module(module_name)
    )
    contract = module.ConsentContract(CONTRACT, ("operator", PRINCIPAL), frozenset({"audio"}))
    registry = module.ConsentRegistry(_contracts={CONTRACT: contract})
    assert registry.get(OLD_CONTRACT) == contract
    assert registry.get_contract_for(OLD_PRINCIPAL) == contract
    assert registry.contract_check(OLD_PRINCIPAL, "audio")
    assert registry.subject_data_categories(OLD_PRINCIPAL) == frozenset({"audio"})
    assert registry.purge_subject(OLD_PRINCIPAL) == [CONTRACT]


@pytest.mark.parametrize("prefix", ["agentgov", "agents._governance"])
def test_revoke_purges_predecessor_carrier(prefix, aliases):
    carrier = importlib.import_module(prefix + ".carrier")
    labeled = importlib.import_module(prefix + ".labeled")
    labels = importlib.import_module(prefix + ".consent_label")
    revocation = importlib.import_module(prefix + ".revocation")
    registry = consent.ConsentRegistry(
        _contracts={
            CONTRACT: consent.ConsentContract(
                CONTRACT, ("operator", PRINCIPAL), frozenset({"audio"})
            )
        }
    )
    facts = carrier.CarrierRegistry()
    facts.register("synthetic-agent", capacity=3)
    for cid in (OLD_CONTRACT, UNKNOWN, digest(UNKNOWN)):
        facts.offer(
            "synthetic-agent",
            carrier.CarrierFact(
                labeled.Labeled(cid, labels.ConsentLabel.bottom(), frozenset({cid})),
                "synthetic-domain",
            ),
        )
    propagator = revocation.RevocationPropagator(registry)
    propagator.register_carrier_registry(facts)
    report = propagator.revoke(PRINCIPAL)
    assert report.contract_revoked
    assert report.total_purged == 1
    assert {fact.labeled.value for fact in facts.facts("synthetic-agent")} == {
        UNKNOWN,
        digest(UNKNOWN),
    }
    assert facts.purge_by_provenance(digest(UNKNOWN)) == 0
    assert propagator.revoke(UNKNOWN).total_purged == 0


@pytest.mark.parametrize("prefix", ["agentgov", "agents._governance"])
def test_revocation_resolves_before_dispatch(prefix, aliases):
    from unittest.mock import Mock

    revocation = importlib.import_module(prefix + ".revocation")
    registry = Mock()
    registry.purge_subject.return_value = [OLD_CONTRACT]
    handler = Mock(return_value=1)
    propagator = revocation.RevocationPropagator(registry)
    propagator.register_handler("synthetic", handler)
    propagator.revoke(OLD_PRINCIPAL)
    registry.purge_subject.assert_called_once_with(PRINCIPAL)
    handler.assert_called_once_with(CONTRACT)


@pytest.mark.parametrize(
    "module_name",
    [
        "agentgov.provenance",
        "agents._governance.provenance",
        "logos._governance",
        "agents/_governance.py",
    ],
)
def test_provenance_resolves_contracts(module_name, aliases):
    module = (
        file_module(module_name, "alias_agents_flat_provenance")
        if "/" in module_name
        else importlib.import_module(module_name)
    )
    expr = module.ProvenanceExpr
    assert expr.leaf(OLD_CONTRACT).evaluate(frozenset({CONTRACT}))
    assert expr.leaf(CONTRACT).evaluate(frozenset({OLD_CONTRACT}))
    assert not expr.leaf(UNKNOWN).evaluate(frozenset({OLD_CONTRACT}))


def test_purge_cli_example():
    tree = ast.parse((ROOT / "scripts/archive-purge.py").read_text())
    assert re.search(r"--consent-revoked-for principal-c[12]\b", ast.get_docstring(tree))


def test_archive_resolves_before_lookup(aliases, monkeypatch, tmp_path):
    from unittest.mock import Mock

    archive = file_module("scripts/archive-purge.py", "alias_archive")
    registry = Mock()
    registry.get_contract_for.return_value = Mock(active=True, id=CONTRACT)
    monkeypatch.setattr(consent, "ConsentRegistry", lambda: registry)
    ok, _ = archive._consent_revocation_check(OLD_PRINCIPAL, tmp_path)
    assert not ok
    registry.get_contract_for.assert_called_once_with(PRINCIPAL)


def test_enrollment_resolves_lookup_and_deletion(aliases, tmp_path):
    import numpy as np

    from shared.face_enrollment_registry import enroll_principal, load_enrollment, revoke_enrollment

    registry = consent.ConsentRegistry(
        _contracts={
            CONTRACT: consent.ConsentContract(
                CONTRACT, ("operator", PRINCIPAL), frozenset({"face_enrollment"})
            )
        }
    )
    embedding = np.ones(512, dtype=np.float32)
    path = enroll_principal(OLD_PRINCIPAL, embedding, consent=registry, root=tmp_path)
    assert path.name == PRINCIPAL + ".npz"
    legacy = tmp_path / (OLD_PRINCIPAL + ".npz")
    path.rename(legacy)
    np.savez(tmp_path / (UNKNOWN + ".npz"), embedding=embedding)
    assert np.array_equal(load_enrollment(PRINCIPAL, root=tmp_path), embedding)
    assert revoke_enrollment(PRINCIPAL, root=tmp_path)
    assert not legacy.exists()
    assert (tmp_path / (UNKNOWN + ".npz")).exists()


def test_package_and_agent_share_implementations():
    for name, symbol in (
        ("carrier", "CarrierRegistry"),
        ("provenance", "ProvenanceExpr"),
        ("revocation", "RevocationPropagator"),
    ):
        package = importlib.import_module("agentgov." + name)
        mirror = importlib.import_module("agents._governance." + name)
        assert getattr(package, symbol) is getattr(mirror, symbol)
