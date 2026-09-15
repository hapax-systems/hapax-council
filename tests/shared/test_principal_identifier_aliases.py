"""Migration pins use synthetic predecessor identifiers exclusively."""

from __future__ import annotations

import ast
import hashlib
import importlib
import importlib.machinery
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from shared.governance import consent

# Synthetic custody is autouse for the whole tree through tests/conftest.py.

ROOT = Path(__file__).resolve().parents[2]
PRINCIPAL = "synthetic-successor-subject"
CONTRACT = "synthetic-successor-contract"
OLD_PRINCIPAL = "synthetic-predecessor-subject"
OLD_CONTRACT = "synthetic-predecessor-contract"
UNKNOWN = "synthetic-unregistered-contract"
CONTRACTS = (
    "contract-principal-c1",
    "contract-principal-c2",
    "contract-principal-a1-2026-04-19",
    "contract-principal-a1-enroll-2026-04-19",
)


def digest(value):
    return hashlib.sha256(("principal-alias-v1:" + value).encode()).hexdigest()


@pytest.fixture
def aliases(synthetic_custody):
    return synthetic_custody


def file_module(path, name):
    loader = importlib.machinery.SourceFileLoader(name, str(ROOT / path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_synthetic_resolution(aliases):
    assert consent.resolve_principal_id(PRINCIPAL) == PRINCIPAL
    assert consent.resolve_principal_id(OLD_PRINCIPAL) == PRINCIPAL
    assert consent.resolve_contract_id(CONTRACT) == CONTRACT
    assert consent.resolve_contract_id(OLD_CONTRACT) == CONTRACT
    registry = consent.ConsentRegistry(
        _contracts={
            CONTRACT: consent.ConsentContract(
                CONTRACT, ("operator", PRINCIPAL), frozenset({"audio"}), principal_class="child"
            )
        }
    )
    assert consent.is_child_principal(OLD_PRINCIPAL, registry)


def test_unregistered_resolution(aliases):
    for candidate in (UNKNOWN, digest(UNKNOWN), "", "synthetic-unregistered-subject"):
        assert consent.resolve_principal_id(candidate) == candidate
        assert consent.resolve_contract_id(candidate) == candidate


@pytest.mark.parametrize("contract_id", CONTRACTS)
def test_public_contract_has_no_correspondence(contract_id):
    path = ROOT / "axioms/contracts" / f"{contract_id}.yaml"
    data = yaml.safe_load(path.read_text())
    assert data["schema_version"] == 2
    assert data["id"] == contract_id
    assert consent.parse_contract(data).id == contract_id
    assert "predecessor_aliases" not in data
    assert "sha256" not in path.read_text()


def test_public_resolver_has_no_digest_table():
    tree = ast.parse((ROOT / "shared/governance/consent.py").read_text())
    assert not any(
        isinstance(node, ast.Dict)
        and any(
            isinstance(key, ast.Constant)
            and isinstance(key.value, str)
            and re.fullmatch(r"[0-9a-f]{64}", key.value)
            for key in node.keys
        )
        for node in ast.walk(tree)
    )
    assert not any(
        isinstance(node, ast.Name) and node.id in {"_PRINCIPAL_ALIASES", "_CONTRACT_ALIASES"}
        for node in ast.walk(tree)
    )


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
    assert facts.purge_by_provenance(digest(UNKNOWN)) == 1
    assert propagator.revoke(UNKNOWN).total_purged == 0


@pytest.mark.parametrize("prefix", ["agentgov", "agents._governance"])
@pytest.mark.parametrize("audit_id", [OLD_CONTRACT, CONTRACT])
def test_revocation_purges_real_recordings(prefix, audit_id, aliases, monkeypatch, tmp_path):
    from functools import partial

    from agents.studio_compositor import consent as recording

    revocation = importlib.import_module(prefix + ".revocation")
    registry = consent.ConsentRegistry(_contracts_dir=tmp_path / "contracts")
    registry.create_contract(OLD_PRINCIPAL, frozenset({"video"}), contract_id=OLD_CONTRACT)
    compositor, segments = recording_fixture(tmp_path, audit_id, monkeypatch)
    propagator = revocation.RevocationPropagator(registry)
    propagator.register_handler("recordings", partial(recording.purge_video_recordings, compositor))
    report = propagator.revoke(OLD_PRINCIPAL)
    assert report.contract_revoked
    assert report.contract_id == CONTRACT
    assert report.person_id == PRINCIPAL
    assert report.total_purged == 2
    assert all(not path.exists() for path in segments)
    assert (tmp_path / "recordings/camera/segment_20260904-120000_000.mkv").exists()
    fresh = consent.ConsentRegistry(_contracts_dir=tmp_path / "contracts")
    fresh.load(tmp_path / "contracts")
    assert not fresh.contract_check(OLD_PRINCIPAL, "video")


def recording_fixture(tmp_path, audit_id, monkeypatch):
    from agents.studio_compositor import consent as recording

    audit = tmp_path / "audit.jsonl"
    audit.write_text(
        "\n".join(
            json.dumps({"event": event, "timestamp": stamp, "active_contracts": [audit_id]})
            for event, stamp in (
                ("recording_resumed", "2026-09-05T12:00:00+00:00"),
                ("recording_paused", "2026-09-05T12:02:00+00:00"),
            )
        )
    )
    monkeypatch.setattr(recording, "CONSENT_AUDIT_PATH", audit)
    rec_dir = tmp_path / "recordings"
    hls_dir = tmp_path / "hls"
    (rec_dir / "camera").mkdir(parents=True)
    hls_dir.mkdir()
    mkv = rec_dir / "camera/segment_20260905-120100_000.mkv"
    hls = hls_dir / "segment.ts"
    mkv.write_bytes(b"synthetic recording")
    hls.write_bytes(b"synthetic segment")
    from datetime import datetime

    stamp = datetime.fromisoformat("2026-09-05T12:01:00+00:00").timestamp()
    os.utime(hls, (stamp, stamp))
    (rec_dir / "camera/segment_20260904-120000_000.mkv").write_bytes(b"unrelated recording")
    compositor = SimpleNamespace(
        config=SimpleNamespace(
            recording=SimpleNamespace(output_dir=rec_dir),
            hls=SimpleNamespace(output_dir=hls_dir),
        )
    )
    return compositor, (mkv, hls)


def test_recording_purge_resolves_supplied_predecessor(aliases, monkeypatch, tmp_path):
    from agents.studio_compositor.consent import purge_video_recordings

    compositor, segments = recording_fixture(tmp_path, CONTRACT, monkeypatch)
    result = purge_video_recordings(compositor, OLD_CONTRACT)
    assert result.items_purged == 2
    assert result.purge_complete
    assert all(not path.exists() for path in segments)


@pytest.mark.parametrize("stored_party", [PRINCIPAL, OLD_PRINCIPAL])
def test_guest_cli_grant_revoke_lifecycle(stored_party, aliases, monkeypatch, tmp_path, capsys):
    cli = file_module("scripts/hapax-guest-consent", "alias_guest_cli")
    monkeypatch.setenv("HAPAX_GUEST_CONSENT_DIR", str(tmp_path))
    assert cli.cmd_grant(OLD_PRINCIPAL) == 0
    granted = cli._registry(tmp_path)
    assert granted.contract_check(OLD_PRINCIPAL, "world_render")
    contract = granted.get_contract_for(PRINCIPAL)
    assert contract.parties == ("operator", PRINCIPAL)
    assert contract.id.startswith(f"guest-render-{PRINCIPAL}-")
    path = tmp_path / f"{contract.id}.yaml"
    data = yaml.safe_load(path.read_text())
    data["parties"] = ["operator", stored_party]
    path.write_text(yaml.safe_dump(data))
    assert cli.cmd_revoke(OLD_PRINCIPAL) == 0
    reloaded = cli._registry(tmp_path)
    assert not reloaded.contract_check(PRINCIPAL, "world_render")
    assert not reloaded.contract_check(OLD_PRINCIPAL, "world_render")
    assert not path.exists()
    assert len(list((tmp_path / "revoked").glob("*.yaml"))) == 1
    capsys.readouterr()


@pytest.mark.parametrize("module_name", ["agentgov.consent", "shared.governance.consent"])
@pytest.mark.parametrize("lookup_id", [OLD_CONTRACT, CONTRACT])
@pytest.mark.parametrize("filename", [f"{OLD_CONTRACT}.yaml", "predecessor-storage.yaml"])
def test_predecessor_keyed_registry_lifecycle(module_name, lookup_id, filename, aliases, tmp_path):
    module = importlib.import_module(module_name)
    path = tmp_path / filename
    data = {"id": OLD_CONTRACT, "parties": ["operator", OLD_PRINCIPAL], "scope": ["audio"]}
    path.write_text(yaml.safe_dump(data))
    registry = module.ConsentRegistry()
    assert registry.load(tmp_path) == 1
    assert registry.get(lookup_id).id == OLD_CONTRACT
    assert registry.contract_check(PRINCIPAL, "audio")
    registry.revoke_contract(lookup_id)
    assert not registry.get(lookup_id).active
    assert not registry.contract_check(OLD_PRINCIPAL, "audio")
    assert not path.exists()
    archived = list((tmp_path / "revoked").glob("*.yaml"))
    assert len(archived) == 1
    assert archived[0].name.endswith(filename)
    assert yaml.safe_load(archived[0].read_text()) == data
    fresh = module.ConsentRegistry()
    assert fresh.load(tmp_path) == 0
    assert not fresh.contract_check(PRINCIPAL, "audio")


def test_revocation_removes_both_stored_contract_aliases(aliases, tmp_path):
    registry = consent.ConsentRegistry(_contracts_dir=tmp_path)
    for cid in (OLD_CONTRACT, CONTRACT):
        registry.create_contract(PRINCIPAL, frozenset({"audio"}), contract_id=cid)
    registry.load(tmp_path)
    registry.revoke_contract(CONTRACT)
    assert not registry.active_contracts
    assert not list(tmp_path.glob("*.yaml"))
    assert len(list((tmp_path / "revoked").glob("*.yaml"))) == 2


def test_memory_only_contract_does_not_infer_storage_ownership(aliases, tmp_path):
    from agentgov.consent import ConsentRegistry

    unrelated = tmp_path / f"{CONTRACT}.yaml"
    unrelated.write_text("unloaded storage")
    registry = ConsentRegistry(
        _contracts_dir=tmp_path,
        _contracts={
            CONTRACT: consent.ConsentContract(
                CONTRACT, ("operator", PRINCIPAL), frozenset({"audio"})
            )
        },
    )
    assert registry.purge_subject(OLD_PRINCIPAL) == [CONTRACT]
    assert not registry.contract_check(PRINCIPAL, "audio")
    assert unrelated.read_text() == "unloaded storage"


@pytest.mark.parametrize("cid", [digest(UNKNOWN), digest(OLD_CONTRACT)])
def test_hex_contract_carrier_revocation(cid, aliases, tmp_path):
    from agentgov.carrier import CarrierFact, CarrierRegistry
    from agentgov.consent import ConsentRegistry
    from agentgov.consent_label import ConsentLabel
    from agentgov.labeled import Labeled
    from agentgov.revocation import RevocationPropagator

    registry = ConsentRegistry(_contracts_dir=tmp_path)
    registry.create_contract(PRINCIPAL, frozenset({"audio"}), contract_id=cid)
    assert registry.get(cid).active
    facts = CarrierRegistry()
    facts.register("synthetic-agent", capacity=1)
    facts.offer(
        "synthetic-agent",
        CarrierFact(Labeled("synthetic fact", ConsentLabel.bottom(), frozenset({cid})), "audio"),
    )
    propagator = RevocationPropagator(registry)
    propagator.register_carrier_registry(facts)
    report = propagator.revoke(PRINCIPAL)
    assert report.contract_revoked
    assert report.total_purged == 1
    assert not facts.facts("synthetic-agent")
    assert not registry.get(cid).active


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


@pytest.mark.parametrize("failed_id", [OLD_PRINCIPAL, PRINCIPAL])
@pytest.mark.parametrize("requested_id", [OLD_PRINCIPAL, PRINCIPAL])
def test_partial_enrollment_revocation(
    failed_id, requested_id, aliases, monkeypatch, tmp_path, caplog
):
    import numpy as np

    from shared import face_enrollment_registry as enrollment

    registry = consent.ConsentRegistry(_contracts_dir=tmp_path / "contracts")
    registry.create_contract(PRINCIPAL, frozenset({"face_enrollment"}))
    embedding = np.ones(512, dtype=np.float32)
    current = enrollment.enroll_principal(PRINCIPAL, embedding, consent=registry, root=tmp_path)
    predecessor = tmp_path / f"{OLD_PRINCIPAL}.npz"
    np.savez(predecessor, embedding=embedding)
    assert enrollment.match_principal(embedding, root=tmp_path) == PRINCIPAL
    original_unlink = Path.unlink

    def fail_one(path, *args, **kwargs):
        if path == tmp_path / f"{failed_id}.npz":
            raise PermissionError("synthetic-storage-detail")
        return original_unlink(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", fail_one)
        assert enrollment.revoke_enrollment(requested_id, root=tmp_path) is False
    assert sum(path.exists() for path in (current, predecessor)) == 1
    assert "revocation incomplete" in caplog.text
    assert "PermissionError" in caplog.text
    assert "Correct storage access and retry" in caplog.text
    assert "synthetic-storage-detail" not in caplog.text
    assert OLD_PRINCIPAL not in caplog.text
    # A fresh module has no in-memory revocation state to hide surviving files.
    fresh = file_module("shared/face_enrollment_registry.py", "alias_fresh_enrollment")
    for pid in (OLD_PRINCIPAL, PRINCIPAL):
        assert fresh.load_enrollment(pid, root=tmp_path) is None
        assert fresh.match_principal(embedding, root=tmp_path, candidates=[pid]) is None
    assert fresh.match_principal(embedding, root=tmp_path) is None
    assert fresh.revoke_enrollment(requested_id, root=tmp_path) is True
    assert not current.exists() and not predecessor.exists()
    assert fresh.load_enrollment(PRINCIPAL, root=tmp_path) is None
    fresh.enroll_principal(OLD_PRINCIPAL, embedding, consent=registry, root=tmp_path)
    assert fresh.match_principal(embedding, root=tmp_path) == PRINCIPAL


def test_enrollment_refuses_when_revocation_marker_cannot_persist(aliases, monkeypatch, tmp_path):
    import numpy as np

    from shared import face_enrollment_registry as enrollment

    path = tmp_path / f"{OLD_PRINCIPAL}.npz"
    np.savez(path, embedding=np.ones(512, dtype=np.float32))

    def deny_marker(*args, **kwargs):
        raise PermissionError("synthetic-storage-detail")

    monkeypatch.setattr(Path, "touch", deny_marker)
    with pytest.raises(enrollment.FaceEnrollmentError, match="correct storage access and retry"):
        enrollment.revoke_enrollment(PRINCIPAL, root=tmp_path)
    assert path.exists()


@pytest.mark.parametrize("missing", ["shared", "shared.governance", "shared.governance.consent"])
def test_required_resolver_absence_refuses_lifecycle(missing, aliases, monkeypatch, tmp_path):
    from agentgov.carrier import CarrierFact, CarrierRegistry
    from agentgov.consent import ConsentRegistry
    from agentgov.consent_label import ConsentLabel
    from agentgov.labeled import Labeled
    from agentgov.revocation import RevocationPropagator

    cli = file_module("scripts/hapax-guest-consent", "alias_guest_cli_missing_resolver")
    monkeypatch.setenv("HAPAX_GUEST_CONSENT_DIR", str(tmp_path))
    registry = ConsentRegistry(_contracts_dir=tmp_path)
    registry.create_contract(OLD_PRINCIPAL, frozenset({"world_render"}), contract_id=CONTRACT)
    facts = CarrierRegistry()
    facts.register("synthetic-agent", 1)
    facts.offer(
        "synthetic-agent",
        CarrierFact(
            Labeled("synthetic fact", ConsentLabel.bottom(), frozenset({OLD_CONTRACT})), "audio"
        ),
    )
    # Simulate the optional council package being absent, including cached children.
    for name in tuple(sys.modules):
        if name == missing or name.startswith(missing + "."):
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.setitem(sys.modules, missing, None)
    for operation in (
        lambda: cli.cmd_grant(OLD_PRINCIPAL),
        lambda: cli.cmd_revoke(OLD_PRINCIPAL),
        lambda: registry.get(OLD_CONTRACT),
        lambda: registry.revoke_contract(OLD_CONTRACT),
        lambda: registry.contract_check(OLD_PRINCIPAL, "world_render"),
        lambda: RevocationPropagator(registry).revoke(OLD_PRINCIPAL),
        lambda: facts.purge_by_provenance(CONTRACT),
    ):
        with pytest.raises(RuntimeError, match="^identity_unconfigured$"):
            operation()
    assert (tmp_path / f"{CONTRACT}.yaml").exists()
    assert registry.active_contracts
    assert facts.facts("synthetic-agent")


def test_package_and_agent_share_implementations():
    for name, symbol in (
        ("carrier", "CarrierRegistry"),
        ("provenance", "ProvenanceExpr"),
        ("revocation", "RevocationPropagator"),
    ):
        package = importlib.import_module("agentgov." + name)
        mirror = importlib.import_module("agents._governance." + name)
        assert getattr(package, symbol) is getattr(mirror, symbol)


@pytest.mark.parametrize("failed_kind", ["audit", "recording", "hls", "timestamp"])
def test_partial_recording_purge_keeps_revocation_and_retry(
    failed_kind, aliases, monkeypatch, tmp_path
):
    from functools import partial

    from agentgov.revocation import RevocationPropagator

    from agents.studio_compositor import consent as recording

    registry = consent.ConsentRegistry(_contracts_dir=tmp_path / "contracts")
    registry.create_contract(PRINCIPAL, frozenset({"video"}), contract_id=CONTRACT)
    compositor, segments = recording_fixture(tmp_path, OLD_CONTRACT, monkeypatch)
    original_unlink = Path.unlink
    original_read = Path.read_text
    invalid = tmp_path / "recordings/camera/invalid.mkv"
    if failed_kind == "timestamp":
        invalid.write_bytes(b"synthetic recording")

    def fail_delete(path, *args, **kwargs):
        target = segments[0 if failed_kind == "recording" else 1]
        if failed_kind in {"recording", "hls"} and path == target:
            raise PermissionError("synthetic-private-detail")
        return original_unlink(path, *args, **kwargs)

    def fail_audit(path, *args, **kwargs):
        if failed_kind == "audit" and path == recording.CONSENT_AUDIT_PATH:
            raise PermissionError("synthetic-private-detail")
        return original_read(path, *args, **kwargs)

    propagator = RevocationPropagator(registry)
    propagator.register_handler("recordings", partial(recording.purge_video_recordings, compositor))
    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", fail_delete)
        patch.setattr(Path, "read_text", fail_audit)
        report = propagator.revoke(OLD_PRINCIPAL)
    assert report.contract_revoked
    assert not report.purge_complete
    from dataclasses import asdict

    assert asdict(report)["purge_complete"] is False
    assert report.retry_contract_ids
    assert report.purge_results[0].failures
    assert all(re.fullmatch(r"[a-z_]+", reason) for reason in report.purge_results[0].failures)
    assert (
        report.total_purged == {"audit": 0, "recording": 1, "hls": 1, "timestamp": 2}[failed_kind]
    )
    assert sum(path.exists() for path in segments) == 2 - report.total_purged
    assert not registry.contract_check(PRINCIPAL, "video")
    fresh = consent.ConsentRegistry(_contracts_dir=tmp_path / "contracts")
    fresh.load(tmp_path / "contracts")
    assert not fresh.contract_check(OLD_PRINCIPAL, "video")
    if invalid.exists():
        invalid.unlink()
    retry = RevocationPropagator(fresh)
    retry.register_handler("recordings", partial(recording.purge_video_recordings, compositor))
    completed = retry.retry_purge(report)
    assert completed.contract_revoked
    assert completed.purge_complete
    assert completed.total_purged == 2
    assert completed.prior_purge_results[0].failures
    assert not any(path.exists() for path in segments)
    assert not fresh.contract_check(PRINCIPAL, "video")


def test_mapping_failure_is_not_recording_success(aliases, monkeypatch, tmp_path):
    from agents.studio_compositor import consent as recording

    compositor, segments = recording_fixture(tmp_path, OLD_CONTRACT, monkeypatch)
    aliases.delete("consent-identifier-compatibility")
    report = recording.purge_video_recordings(compositor, CONTRACT)
    assert not report.purge_complete
    assert report.items_purged == 0
    assert report.failures == ("compat_missing",)
    assert all(path.exists() for path in segments)


def test_guest_source_reconciles_binding_and_denies_errors(aliases, monkeypatch, tmp_path, capsys):
    cli = file_module("scripts/hapax-guest-consent", "synthetic_guest_grant")
    source = file_module("scripts/screwm-guest-source.py", "synthetic_guest_source")
    monkeypatch.setenv("HAPAX_GUEST_CONSENT_DIR", str(tmp_path / "contracts"))
    assert cli.cmd_grant(OLD_PRINCIPAL) == 0
    capsys.readouterr()
    assert source.consented(PRINCIPAL, tmp_path / "contracts")
    aliases.delete("consent-identifier-compatibility")
    assert not source.consented(PRINCIPAL, tmp_path / "contracts")
    diagnostic = capsys.readouterr().err
    assert "consent_unavailable: cause_class=IdentityMigrationUnavailable" in diagnostic
    assert "restore identity custody before retrying" in diagnostic
    assert OLD_PRINCIPAL not in diagnostic
    with pytest.raises(RuntimeError, match="^compat_missing$"):
        cli.cmd_grant(PRINCIPAL)


def test_downstream_exception_retains_completed_effects(aliases, tmp_path):
    from agentgov.revocation import RevocationPropagator

    registry = consent.ConsentRegistry(_contracts_dir=tmp_path / "contracts")
    registry.create_contract(PRINCIPAL, frozenset({"audio"}), contract_id=CONTRACT)
    artifact = tmp_path / "synthetic-artifact"
    artifact.write_bytes(b"synthetic")

    def completed(contract_id):
        artifact.unlink()
        return 1

    def fail(contract_id):
        raise OSError("synthetic-private-detail")

    propagator = RevocationPropagator(registry)
    propagator.register_handler("completed", completed)
    propagator.register_handler("failed", fail)
    report = propagator.revoke(PRINCIPAL)
    assert report.contract_revoked and not report.purge_complete
    assert report.total_purged == 1
    assert report.purge_results[-1].failures == ("purge_failed",)
    assert not artifact.exists()
    assert not registry.contract_check(PRINCIPAL, "audio")


def test_retry_requires_failed_handlers_and_preserves_history(aliases, tmp_path):
    from agentgov.revocation import RevocationPropagator

    registry = consent.ConsentRegistry(_contracts_dir=tmp_path / "contracts")
    registry.create_contract(PRINCIPAL, frozenset({"audio"}), contract_id=CONTRACT)
    calls = []

    def complete(contract_id):
        calls.append(True)
        return 1

    def fail(contract_id):
        raise OSError("synthetic-private-detail")

    cascade = RevocationPropagator(registry)
    cascade.register_handler("complete", complete)
    cascade.register_handler("failed", fail)
    report = cascade.revoke(PRINCIPAL)
    fresh = consent.ConsentRegistry(_contracts_dir=tmp_path / "contracts")
    fresh.load(tmp_path / "contracts")
    retry = RevocationPropagator(fresh)
    retry.register_handler("complete", complete)
    pending = retry.retry_purge(report)
    assert pending.contract_revoked and not pending.purge_complete
    assert pending.purge_results[0].failures == ("purge_handler_missing",)
    assert len(calls) == 1
    retry.register_handler("failed", lambda contract_id: 1)
    completed = retry.retry_purge(pending)
    assert completed.purge_complete
    assert completed.total_purged == 2
    assert len(calls) == 1
    assert any(result.failures for result in completed.prior_purge_results)


@pytest.mark.parametrize("operation", ["grant", "enrollment", "cascade", "archive"])
def test_compound_lifecycle_uses_one_custody_read(
    operation, aliases, monkeypatch, tmp_path, capsys
):
    import numpy as np
    from agentgov.revocation import RevocationPropagator

    from shared import face_enrollment_registry as enrollment

    registry = consent.ConsentRegistry(_contracts_dir=tmp_path / "contracts")
    registry.create_contract(PRINCIPAL, frozenset({"face_enrollment"}), contract_id=CONTRACT)
    cli = file_module("scripts/hapax-guest-consent", "synthetic_snapshot_cli")
    archive = file_module("scripts/archive-purge.py", "synthetic_snapshot_archive")
    monkeypatch.setenv("HAPAX_GUEST_CONSENT_DIR", str(tmp_path / "contracts"))
    api = importlib.import_module("k0.key_capture")
    original = api.FileStore.get
    reads = []

    def read_once(store, name):
        raw = original(store, name)
        reads.append(True)
        aliases.delete("consent-identifier-compatibility")
        return raw

    monkeypatch.setattr(api.FileStore, "get", read_once)
    if operation == "grant":
        assert cli.cmd_grant(OLD_PRINCIPAL) == 0
    elif operation == "enrollment":
        path = enrollment.enroll_principal(
            OLD_PRINCIPAL, np.ones(512, dtype=np.float32), consent=registry, root=tmp_path
        )
        assert path.exists()
    elif operation == "cascade":
        assert RevocationPropagator(registry).revoke(OLD_PRINCIPAL).contract_revoked
    else:
        assert not archive._consent_revocation_check(OLD_PRINCIPAL, tmp_path / "contracts")[0]
    assert len(reads) == 1
    with pytest.raises(RuntimeError, match="^compat_missing$"):
        registry.contract_check(PRINCIPAL, "face_enrollment")
    assert len(reads) == 2
    capsys.readouterr()
