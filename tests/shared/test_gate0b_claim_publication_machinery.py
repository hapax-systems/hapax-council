from __future__ import annotations

import stat
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
    publish_gate0b_claim,
)
from shared.gate0b_claim_publication_install import (
    GATE0B_SLICE1_RATIFIED_INFLECTION_REF,
    ClaimPublicationCompositionRoots,
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


def test_effect_carrier_validates_but_remains_dormant_without_mutation(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    install = _install(tmp_path, fixture)

    with pytest.raises(
        ClaimPublicationError,
        match="claim_publication_effect_activation_unvalidated",
    ):
        publish_gate0b_claim(
            fixture.intent,
            root=install.root,
            now=datetime(2026, 8, 9, 17, 1, tzinfo=UTC),
        )

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
