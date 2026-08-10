from __future__ import annotations

import ast
import json
import stat
import subprocess
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from shared.execution_admission import (
    DEFAULT_EXECUTION_COMPOSITION_ROOT,
    ContentAddress,
    ExecutionAdmissionError,
)
from shared.gate0b_claim_publication_effect import (
    ClaimPublicationEffectInvocation,
    apply_claim_publication_effect,
    publish_gate0b_claim,
)
from shared.gate0b_claim_publication_install import (
    GATE0B_SLICE1_RATIFIED_INFLECTION_REF,
    ClaimPublicationCompositionRoots,
    claim_publication_install_receipt_bytes,
    install_claim_publication_composition,
    load_claim_publication_composition,
    require_claim_publication_install_receipt,
)
from shared.gate0b_claim_publication_lease import (
    Gate0BClaimPublicationAuthorityReceipt,
    materialize_claim_publication_proofs,
    prepare_claim_publication_admission,
)
from shared.sdlc_claim import (
    ClaimAdmissionConsumption,
    ClaimPublicationError,
    ClaimPublicationIntent,
    recover_claim_publications,
)
from shared.sdlc_task_store import ClaimDispatchBinding, resolve_task_note


@dataclass(frozen=True)
class Gate0BFixture:
    intent: ClaimPublicationIntent
    roots: ClaimPublicationCompositionRoots
    vault: Path
    cache: Path


def _note(task_id: str) -> bytes:
    return f"""---
task_id: {task_id}
status: offered
assigned_to: unassigned
claimed_at: null
updated_at: 2026-07-11T12:00:00Z
authority_case: CASE-CLAIM-001
parent_spec: spec://claim
claimable: true
---
# Claim task

Body remains exact.
""".encode()


def _fixture(tmp_path: Path, *, task_id: str = "task-alpha") -> Gate0BFixture:
    vault = tmp_path / "vault"
    active = vault / "active"
    cache = tmp_path / "cache"
    active.mkdir(parents=True)
    (vault / "closed").mkdir()
    cache.mkdir()
    before = _note(task_id)
    note_path = active / f"{task_id}.md"
    note_path.write_bytes(before)
    note_path.chmod(0o644)
    task = resolve_task_note(vault, task_id, require_no_other_state=True)
    binding = ClaimDispatchBinding.create(
        task_id=task_id,
        lane="cx-red",
        session_id="session-abc",
        claim_epoch=1_720_700_000,
        dispatch_message_id="dispatch-msg-001",
        platform="codex",
        mode="headless",
        profile="ultra",
        authority_case="CASE-CLAIM-001",
        binding_hash="a" * 64,
        coord_dispatch_idempotency_key="coord-dispatch-001",
    )
    after = (
        before.replace(b"status: offered", b"status: claimed")
        .replace(b"assigned_to: unassigned", b"assigned_to: cx-red")
        .replace(b"claimed_at: null", b"claimed_at: 2026-07-11T12:00:00Z")
    )
    intent = ClaimPublicationIntent.create(
        task=task,
        cache_dir=cache,
        note_after=after,
        binding=binding,
    )
    roots = ClaimPublicationCompositionRoots(
        invocation_store_root=str(tmp_path / "invocations"),
        claim_vault_root=str(vault),
        claim_cache_dir=str(cache),
        claim_transaction_root=str(tmp_path / "transactions"),
        claim_receipt_root=str(tmp_path / "receipts"),
        claim_lock_root=str(tmp_path / "locks"),
    )
    return Gate0BFixture(intent=intent, roots=roots, vault=vault, cache=cache)


def _install(tmp_path: Path, fixture: Gate0BFixture):
    return install_claim_publication_composition(
        roots=fixture.roots,
        installed_at=datetime(2026, 8, 9, 17, 0, tzinfo=UTC),
        install_task_ref="cc-task-gate0b-slice1a-dormant-machinery-20260809",
    )


def test_only_cc_claim_live_path_imports_gate0b_publication_machinery() -> None:
    allowed_prefixes = ("tests/",)
    allowed_files = {
        "scripts/cc-claim",
        "shared/execution_admission.py",
        "shared/gate0b_claim_publication_effect.py",
        "shared/gate0b_claim_publication_install.py",
        "shared/gate0b_claim_publication_lease.py",
    }
    dormant_modules = {
        "shared.gate0b_claim_publication_effect",
        "shared.gate0b_claim_publication_install",
        "shared.gate0b_claim_publication_lease",
    }
    result = subprocess.run(
        ["git", "ls-files", "*.py", "scripts/cc-claim"],
        cwd=Path.cwd(),
        check=True,
        capture_output=True,
        text=True,
    )
    offenders: list[str] = []
    for relpath in result.stdout.splitlines():
        allowed = relpath in allowed_files or relpath.startswith(allowed_prefixes)
        if allowed:
            continue
        if relpath == "scripts/cc-claim":
            continue
        if not relpath.endswith(".py"):
            continue
        tree = ast.parse(Path(relpath).read_text(encoding="utf-8"), filename=relpath)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in dormant_modules:
                        offenders.append(f"{relpath}:{node.lineno}")
            elif isinstance(node, ast.ImportFrom) and node.module in dormant_modules:
                offenders.append(f"{relpath}:{node.lineno}")
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module == "shared.execution_admission"
                and any(alias.name == "mint_execution_lease" for alias in node.names)
            ):
                offenders.append(f"{relpath}:{node.lineno}:mint_execution_lease")
            elif isinstance(node, ast.Call):
                called = node.func
                if isinstance(called, ast.Name) and called.id == "mint_execution_lease":
                    offenders.append(f"{relpath}:{node.lineno}:mint_execution_lease")
                if isinstance(called, ast.Attribute) and called.attr == "mint_execution_lease":
                    offenders.append(f"{relpath}:{node.lineno}:mint_execution_lease")

    assert offenders == []

    cc_claim = Path("scripts/cc-claim").read_text(encoding="utf-8")
    assert "from shared.gate0b_claim_publication_effect import publish_gate0b_claim" in cc_claim
    assert "from shared.gate0b_claim_publication_install import (" in cc_claim
    assert "from shared.gate0b_claim_publication_lease" not in cc_claim


def test_install_receipt_activates_only_claim_publication_root(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    install = _install(tmp_path, fixture)

    receipt = require_claim_publication_install_receipt(install.root)
    assert receipt.operator_inflection_ref == GATE0B_SLICE1_RATIFIED_INFLECTION_REF
    install.root.require_effect_activation()
    loaded = load_claim_publication_composition(Path(fixture.roots.invocation_store_root))
    assert loaded.receipt == receipt

    with pytest.raises(ExecutionAdmissionError, match="execution_composition_activation"):
        DEFAULT_EXECUTION_COMPOSITION_ROOT.require_effect_activation()

    (Path(fixture.roots.invocation_store_root) / "activation-receipt.json").unlink()
    with pytest.raises(ExecutionAdmissionError, match="gate0b_install_receipt_missing"):
        install.root.require_effect_activation()


def test_install_receipt_rejects_noncanonical_receipt_bytes(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    install = _install(tmp_path, fixture)
    receipt_path = Path(fixture.roots.invocation_store_root) / "activation-receipt.json"
    record = json.loads(claim_publication_install_receipt_bytes(install.receipt).decode("ascii"))
    receipt_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="ascii")

    with pytest.raises(ExecutionAdmissionError, match="gate0b_install_receipt_noncanonical"):
        require_claim_publication_install_receipt(install.root)


def test_install_receipt_rejects_malformed_receipt_with_next_action(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    install = _install(tmp_path, fixture)
    receipt_path = Path(fixture.roots.invocation_store_root) / "activation-receipt.json"
    receipt_path.write_text("{}\n", encoding="ascii")

    with pytest.raises(ExecutionAdmissionError) as excinfo:
        require_claim_publication_install_receipt(install.root)

    assert excinfo.value.reason_code == "gate0b_install_receipt_malformed"
    assert "restore a canonical Gate-0B install receipt" in excinfo.value.repair_action


def test_install_rejects_existing_receipt_collision(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    receipt_path = Path(fixture.roots.invocation_store_root) / "activation-receipt.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text("{}\n", encoding="ascii")

    with pytest.raises(ExecutionAdmissionError, match="gate0b_install_file_collision"):
        _install(tmp_path, fixture)


def test_invocation_store_private_writer_is_idempotent_and_rejects_collision(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    install = _install(tmp_path, fixture)
    assert install.root.invocation_store is not None
    store = install.root.invocation_store
    store._ensure_private_directory(store.objects_root)
    object_path = store.objects_root / f"{'a' * 64}.json"
    payload = b'{"schema":"fixture"}\n'

    store._install_private_file(object_path, payload, mode=0o600)
    first = object_path.stat(follow_symlinks=False)
    store._install_private_file(object_path, payload, mode=0o600)
    second = object_path.stat(follow_symlinks=False)

    assert object_path.read_bytes() == payload
    assert stat.S_IMODE(second.st_mode) == 0o600
    assert (second.st_ino, second.st_mtime_ns, second.st_size) == (
        first.st_ino,
        first.st_mtime_ns,
        first.st_size,
    )

    with pytest.raises(
        ExecutionAdmissionError, match="execution_invocation_store_object_collision"
    ):
        store._install_private_file(object_path, b'{"schema":"different"}\n', mode=0o600)


def test_install_rejects_undeclared_overlapping_roots(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    roots = ClaimPublicationCompositionRoots(
        invocation_store_root=str(tmp_path / "same"),
        claim_vault_root=str(fixture.vault),
        claim_cache_dir=str(tmp_path / "same"),
        claim_transaction_root=str(tmp_path / "transactions"),
        claim_receipt_root=str(tmp_path / "same" / "receipts"),
        claim_lock_root=str(tmp_path / "locks"),
    )
    with pytest.raises(ValueError, match="overlap"):
        install_claim_publication_composition(
            roots=roots,
            installed_at=datetime(2026, 8, 9, 17, 0, tzinfo=UTC),
            install_task_ref="cc-task-gate0b-slice1a-dormant-machinery-20260809",
        )


def test_lease_materializes_five_current_proofs_and_rejects_drift(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    install = _install(tmp_path, fixture)
    package = prepare_claim_publication_admission(
        fixture.intent,
        root=install.root,
        install_receipt=install.receipt,
        now=datetime(2026, 8, 9, 17, 1, tzinfo=UTC),
        proof_root=tmp_path / "proofs",
    )
    consumption = materialize_claim_publication_proofs(package)

    assert tuple(proof.kind for proof in consumption.proofs) == (
        "action_intent",
        "authority_evidence",
        "execution_admission",
        "execution_lease",
        "valid_authority_grant",
    )
    for proof in consumption.proofs:
        assert stat.S_IMODE(proof.path.stat().st_mode) == 0o600
    assert (
        package.authority_receipt.operator_inflection_ref == GATE0B_SLICE1_RATIFIED_INFLECTION_REF
    )
    assert package.execution_lease.lease_ref.startswith("execution-lease@sha256:")
    assert package.execution_lease.bound_call.operation == "claim.publish"
    assert (
        package.execution_lease.issuer_receipt == package.install_receipt.lease_issuer_receipt_root
    )
    assert package.execution_lease.authorizes_machine_adapter is True
    assert package.execution_lease.authorizes_operator is False

    with pytest.raises(ClaimPublicationError, match="claim_admission_identity_mismatch"):
        ClaimAdmissionConsumption.create(
            fixture.intent,
            action_intent_path=package.action_intent_path,
            authority_evidence_path=package.authority_evidence_path,
            execution_admission_path=package.execution_admission_path,
            valid_authority_grant_path=package.valid_authority_grant_path,
            execution_lease_path=package.execution_lease_path,
            checked_at=datetime(2026, 8, 9, 19, 0, tzinfo=UTC),
        )

    package.authority_evidence_path.write_bytes(b"{}\n")
    with pytest.raises(ClaimPublicationError, match="claim_admission_proof_drift"):
        consumption.require_source_proofs(fixture.intent)


def test_lease_materialization_rejects_existing_proof_collision(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    install = _install(tmp_path, fixture)
    package = prepare_claim_publication_admission(
        fixture.intent,
        root=install.root,
        install_receipt=install.receipt,
        now=datetime(2026, 8, 9, 17, 1, tzinfo=UTC),
        proof_root=tmp_path / "proofs",
    )
    package.action_intent_path.parent.mkdir(parents=True)
    package.action_intent_path.write_text("{}\n", encoding="ascii")

    with pytest.raises(ClaimPublicationError, match="claim_publication_proof_collision"):
        materialize_claim_publication_proofs(package)


def test_lease_materialization_rejects_existing_proof_mode_drift(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    install = _install(tmp_path, fixture)
    package = prepare_claim_publication_admission(
        fixture.intent,
        root=install.root,
        install_receipt=install.receipt,
        now=datetime(2026, 8, 9, 17, 1, tzinfo=UTC),
        proof_root=tmp_path / "proofs",
    )
    materialize_claim_publication_proofs(package)
    package.action_intent_path.chmod(0o644)

    with pytest.raises(ClaimPublicationError, match="claim_publication_proof_mode_mismatch"):
        materialize_claim_publication_proofs(package)


def test_authority_receipt_rejects_noncanonical_timestamp(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    install = _install(tmp_path, fixture)
    package = prepare_claim_publication_admission(
        fixture.intent,
        root=install.root,
        install_receipt=install.receipt,
        now=datetime(2026, 8, 9, 17, 1, tzinfo=UTC),
        proof_root=tmp_path / "proofs",
    )
    payload = package.authority_receipt.model_dump(mode="json", by_alias=True)
    payload["issued_at"] = "2026-08-09T17:01:00+00:00"

    with pytest.raises(ValueError, match="canonical UTC"):
        Gate0BClaimPublicationAuthorityReceipt.model_validate(payload)


def test_lease_rejects_mismatched_dispatch_binding(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    install = _install(tmp_path, fixture)
    package = prepare_claim_publication_admission(
        fixture.intent,
        root=install.root,
        install_receipt=install.receipt,
        now=datetime(2026, 8, 9, 17, 1, tzinfo=UTC),
        proof_root=tmp_path / "proofs",
    )
    materialize_claim_publication_proofs(package)
    replacement = ClaimDispatchBinding.create(
        task_id=fixture.intent.task_id,
        lane=fixture.intent.role,
        session_id=fixture.intent.session_id,
        claim_epoch=fixture.intent.claim_epoch,
        dispatch_message_id="dispatch-msg-002",
        platform="codex",
        mode="headless",
        profile="ultra",
        authority_case=fixture.intent.binding.authority_case,
        binding_hash="b" * 64,
        coord_dispatch_idempotency_key="coord-dispatch-002",
    )
    tampered_intent = ClaimPublicationIntent(**{**fixture.intent.__dict__, "binding": replacement})
    with pytest.raises(ClaimPublicationError, match="claim_admission_identity_mismatch"):
        ClaimAdmissionConsumption.create(
            tampered_intent,
            action_intent_path=package.action_intent_path,
            authority_evidence_path=package.authority_evidence_path,
            execution_admission_path=package.execution_admission_path,
            valid_authority_grant_path=package.valid_authority_grant_path,
            execution_lease_path=package.execution_lease_path,
            checked_at=package.checked_at,
        )


def test_effect_carrier_applies_admitted_publication_once_installed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    install = _install(tmp_path, fixture)

    receipt = publish_gate0b_claim(
        fixture.intent,
        root=install.root,
        now=datetime(2026, 8, 9, 17, 1, tzinfo=UTC),
    )

    assert receipt.admission_consumption is not None
    assert receipt.execution_admission is not None
    assert receipt.execution_lease is not None
    manifest = Path(receipt.manifest_path)
    receipt_path = Path(receipt.receipt_path)
    manifest_record = json.loads(manifest.read_text(encoding="ascii"))
    assert manifest_record["state"] == "applied"
    assert receipt_path.is_file()
    assert stat.S_IMODE(receipt_path.stat(follow_symlinks=False).st_mode) == 0o600
    assert (
        fixture.vault / "active" / f"{fixture.intent.task_id}.md"
    ).read_bytes() == fixture.intent.note_after
    for key in (
        fixture.intent.role,
        f"{fixture.intent.role}-{fixture.intent.session_id}",
    ):
        assert (fixture.cache / f"cc-active-task-{key}").read_text(encoding="utf-8") == (
            f"{fixture.intent.task_id}\n"
        )
        assert (fixture.cache / f"cc-claim-epoch-{key}").read_text(encoding="utf-8") == (
            f"{fixture.intent.claim_epoch} {fixture.intent.task_id}\n"
        )
        binding = json.loads(
            (fixture.cache / f"cc-claim-dispatch-{key}.json").read_text(encoding="ascii")
        )
        assert binding["receipt_hash"] == fixture.intent.binding.receipt_hash


def test_effect_carrier_rejects_wrong_installed_root_without_mutation(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path / "one")
    install = _install(tmp_path / "one", fixture)
    package = prepare_claim_publication_admission(
        fixture.intent,
        root=install.root,
        install_receipt=install.receipt,
        now=datetime(2026, 8, 9, 17, 1, tzinfo=UTC),
        proof_root=tmp_path / "proofs",
    )
    consumption = materialize_claim_publication_proofs(package)
    assert install.root.composition_manifest is not None
    invocation = ClaimPublicationEffectInvocation.create(
        intent=fixture.intent,
        consumption=consumption,
        package=package,
        install_receipt=install.receipt,
        composition_manifest=ContentAddress(
            ref=install.root.composition_manifest.manifest_ref,
            sha256=install.root.composition_manifest.manifest_hash,
        ),
    )
    other_fixture = _fixture(tmp_path / "two", task_id="task-beta")
    other_install = _install(tmp_path / "two", other_fixture)

    with pytest.raises(
        ClaimPublicationError,
        match="claim_publication_effect_invocation_mismatch",
    ):
        apply_claim_publication_effect(invocation, root=other_install.root)

    assert not Path(fixture.roots.claim_transaction_root).exists()
    assert not Path(fixture.roots.claim_receipt_root).exists()
    assert (
        fixture.vault / "active" / f"{fixture.intent.task_id}.md"
    ).read_bytes() == fixture.intent.note_before


def test_effect_invocation_identity_mismatch_has_repair_action(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    install = _install(tmp_path, fixture)
    package = prepare_claim_publication_admission(
        fixture.intent,
        root=install.root,
        install_receipt=install.receipt,
        now=datetime(2026, 8, 9, 17, 1, tzinfo=UTC),
        proof_root=tmp_path / "proofs",
    )
    consumption = materialize_claim_publication_proofs(package)
    assert install.root.composition_manifest is not None
    invocation = ClaimPublicationEffectInvocation.create(
        intent=fixture.intent,
        consumption=consumption,
        package=package,
        install_receipt=install.receipt,
        composition_manifest=ContentAddress(
            ref=install.root.composition_manifest.manifest_ref,
            sha256=install.root.composition_manifest.manifest_hash,
        ),
    )

    with pytest.raises(ValueError, match="recreate the carrier"):
        replace(invocation, invocation_hash="0" * 64)


def test_recovery_path_remains_fail_closed_with_next_action(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))

    with pytest.raises(ClaimPublicationError) as raised:
        recover_claim_publications(
            cache_dir=fixture.cache,
            transaction_root=Path(fixture.roots.claim_transaction_root),
            receipt_root=Path(fixture.roots.claim_receipt_root),
            lock_root=Path(fixture.roots.claim_lock_root),
            task_id=fixture.intent.task_id,
        )

    assert raised.value.reason_code == "claim_publication_recovery_activation_unvalidated"
    assert "Next action: dispatch recovery" in str(raised.value)
    assert sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*")) == before
