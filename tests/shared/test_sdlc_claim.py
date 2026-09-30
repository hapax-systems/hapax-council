from __future__ import annotations

import errno
import hashlib
import json
import multiprocessing as mp
import os
import queue
import shutil
import stat
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from hapax.context_canon import CommittedOutcomeReceiptLike, canonical_json_bytes
from hapax.context_canon import contract as context_contract

import shared.sdlc_claim as sdlc_claim
import shared.sdlc_task_store as sdlc_task_store
from shared.coord_projection import LifecycleTransitionError
from shared.dispatcher_policy import DispatchAction, RouteDecision
from shared.execution_admission import (
    ACTION_INTENT_SCHEMA,
    APPLIED_CLAIM_OWNERSHIP_SCHEMA,
    BOUND_EXECUTION_CALL_SCHEMA,
    CLAIM_PUBLICATION_COMPLETION_EVIDENCE_SCHEMA,
    EXECUTION_ADMISSION_SCHEMA,
    OUTCOME_PIPELINE_READINESS_QUERY_SCHEMA,
    OUTCOME_RECEIPT_SCHEMA,
    VALID_AUTHORITY_GRANT_SCHEMA,
    ActionIntent,
    AppliedClaimOwnershipProof,
    AppliedClaimResolution,
    BoundExecutionCall,
    ClaimPublicationArtifact,
    ContentAddress,
    EffectManifest,
    ExecutionAdmission,
    ExecutionAdmissionError,
    ExecutionLease,
    ExecutionTargetEvidence,
    ExecutionTrustResolver,
    ExecutorDescriptor,
    ExecutorRegistryProjection,
    FrontierValidityEnvelope,
    HistoricalAppliedClaimOwnershipProofV3,
    OutcomeCommitter,
    OutcomePipelineReadinessQuery,
    OutcomeProjectionSnapshot,
    ProspectiveClaimPublicationBasis,
    RootDisposition,
    ValidAuthorityGrant,
    applied_claim_proof,
    build_authority_evidence,
    build_bound_execution_call,
    build_completion_evaluation,
    build_completion_evaluation_query,
    build_current_claim_position,
    build_effect_manifest,
    build_effect_observation,
    build_event_append_receipt,
    build_execution_lease_issuer_trust_query,
    build_execution_target_evidence,
    build_execution_trust_envelope,
    build_execution_trust_query,
    build_executor_descriptor,
    build_executor_registry_projection,
    build_frontier_validity_envelope,
    build_outcome_event,
    build_outcome_pipeline_readiness_envelope,
    build_outcome_projection_snapshot,
    build_outcome_replay_catalog_snapshot,
    build_protected_action_request,
    build_protected_aperture_decision,
    build_protected_claim_coordinates,
    claim_publication_effect_evidence_refs,
    content_address,
    mint_execution_lease,
    outcome_projection_validity_roots,
    require_applied_claim_ownership_proof,
    require_current_execution_lease,
    require_historical_applied_claim_ownership_proof,
)
from shared.gate0b_claim_publication_effect import publish_gate0b_claim
from shared.gate0b_claim_publication_install import (
    ClaimPublicationCompositionInstall,
    ClaimPublicationCompositionRoots,
    install_claim_publication_composition,
)
from shared.sdlc_claim import (
    ADMITTED_CLAIM_PUBLICATION_RECEIPT_SCHEMA,
    ADMITTED_CLAIM_PUBLICATION_SCHEMA,
    CLAIM_ADMISSION_CONSUMPTION_SCHEMA,
    CLAIM_PUBLICATION_RECEIPT_SCHEMA,
    CLAIM_PUBLICATION_SCHEMA,
    HISTORICAL_ADMITTED_CLAIM_PUBLICATION_RECEIPT_SCHEMA,
    HISTORICAL_ADMITTED_CLAIM_PUBLICATION_SCHEMA,
    AppliedClaimPublicationSnapshot,
    ClaimAdmissionConsumption,
    ClaimPublicationError,
    ClaimPublicationInspection,
    ClaimPublicationIntent,
    HistoricalClaimAdmissionConsumptionV1,
    admitted_claim_publication_id,
    claim_publication_id,
    claim_publication_mutation_scope_address,
    claim_publication_receipt_path,
    inspect_claim_publications,
    load_admitted_claim_publication_receipt,
    load_claim_publication_receipt,
    prospective_claim_publication_basis,
    publish_admitted_claim,
    publish_claim,
    recover_claim_publications,
    require_applied_admitted_claim_publication,
    resolve_applied_claim_publication,
    resolve_claim_publication_admission_provenance,
)
from shared.sdlc_task_store import (
    ClaimDispatchBinding,
    TaskStoreError,
    resolve_task_note,
)


@dataclass(frozen=True)
class ClaimFixture:
    intent: ClaimPublicationIntent
    vault: Path
    cache: Path
    transactions: Path
    locks: Path


@dataclass(frozen=True)
class AdmissionFixture:
    consumption: ClaimAdmissionConsumption
    action: ActionIntent
    admission: ExecutionAdmission
    grant: ValidAuthorityGrant
    basis: ProspectiveClaimPublicationBasis
    target: ExecutionTargetEvidence
    bound_call: BoundExecutionCall
    effect_manifest: EffectManifest
    executor_descriptor: ExecutorDescriptor
    executor_registry_projection: ExecutorRegistryProjection
    issuer_receipt: ContentAddress
    issuer_resolver: ExecutionTrustResolver
    lease: ExecutionLease
    checked_at: datetime
    valid_until: datetime
    proof_paths: tuple[Path, ...]


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _domain_hash(domain: str, body: object) -> str:
    return hashlib.sha256(domain.encode("ascii") + b"\0" + _canonical(body)).hexdigest()


def _wire_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _address(label: str) -> ContentAddress:
    digest = hashlib.sha256(f"fixture:{label}".encode()).hexdigest()
    return ContentAddress(ref=f"{label}@sha256:{digest}", sha256=digest)


def _note(
    *,
    task_id: str,
    status: str,
    assigned_to: str,
    claimed_at: str,
    claimable: bool = True,
) -> bytes:
    claimable_line = f"claimable: {str(claimable).lower()}\n" if claimable else ""
    return f"""---
task_id: {task_id}
status: {status}
assigned_to: {assigned_to}
claimed_at: {claimed_at}
updated_at: 2026-07-11T12:00:00Z
authority_case: CASE-CLAIM-001
parent_spec: spec://claim
{claimable_line}---
# Claim task

Body remains exact.
""".encode()


def _fixture(
    tmp_path: Path,
    *,
    task_id: str = "task-alpha",
    role: str = "cx-red",
    resume: bool = False,
    claimable: bool = True,
) -> ClaimFixture:
    vault = tmp_path / "vault"
    active = vault / "active"
    cache = tmp_path / "cache"
    active.mkdir(parents=True, exist_ok=True)
    (vault / "closed").mkdir(exist_ok=True)
    cache.mkdir(exist_ok=True)
    before = _note(
        task_id=task_id,
        status="pr_open" if resume else "offered",
        assigned_to=role if resume else "unassigned",
        claimed_at="2026-07-10T12:00:00Z" if resume else "null",
        claimable=claimable,
    )
    note_path = active / f"{task_id}.md"
    note_path.write_bytes(before)
    task = resolve_task_note(vault, task_id, require_no_other_state=True)
    binding = ClaimDispatchBinding.create(
        task_id=task_id,
        lane=role,
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
    after = _note(
        task_id=task_id,
        status="pr_open" if resume else "claimed",
        assigned_to=role,
        claimed_at=("2026-07-10T12:00:00Z" if resume else "2026-07-11T12:00:00Z"),
        claimable=claimable,
    )
    if resume:
        after = after.replace(
            b"Body remains exact.",
            b"- 2026-07-11T12:00:00Z cx-red resumed (session-abc)\n\nBody remains exact.",
        )
    intent = ClaimPublicationIntent.create(
        task=task,
        cache_dir=cache,
        note_after=after,
        binding=binding,
    )
    return ClaimFixture(
        intent=intent,
        vault=vault,
        cache=cache,
        transactions=tmp_path / "transactions",
        locks=tmp_path / "locks",
    )


def _home_fixture(
    tmp_path: Path,
    *,
    task_id: str = "task-alpha",
    resume: bool = False,
) -> ClaimFixture:
    home = tmp_path / "home"
    repo_root = Path(__file__).resolve().parents[2]
    vault = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    active = vault / "active"
    cache = home / ".cache" / "hapax"
    active.mkdir(parents=True)
    (vault / "closed").mkdir()
    cache.mkdir(parents=True)
    before = _note(
        task_id=task_id,
        status="pr_open" if resume else "offered",
        assigned_to="cx-red" if resume else "unassigned",
        claimed_at="2026-07-10T12:00:00Z" if resume else "null",
    )
    authorization = (
        b"stage: S6_IMPLEMENTATION\n"
        b"implementation_authorized: true\n"
        b"source_mutation_authorized: true\n"
        b"docs_mutation_authorized: true\n"
        b"runtime_mutation_authorized: false\n"
        b"mutation_scope_refs:\n" + f"  - {repo_root / 'shared' / 'sdlc_claim.py'}\n".encode()
    )
    before = before.replace(b"claimable: true\n---", b"claimable: true\n" + authorization + b"---")
    note_path = active / f"{task_id}.md"
    note_path.write_bytes(before)
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
    after = _note(
        task_id=task_id,
        status="pr_open" if resume else "claimed",
        assigned_to="cx-red",
        claimed_at=("2026-07-10T12:00:00Z" if resume else "2026-07-11T12:00:00Z"),
    )
    after = after.replace(b"claimable: true\n---", b"claimable: true\n" + authorization + b"---")
    if resume:
        after = after.replace(
            b"Body remains exact.",
            b"- 2026-07-11T12:00:00Z cx-red resumed (session-abc)\n\nBody remains exact.",
        )
    intent = ClaimPublicationIntent.create(
        task=task,
        cache_dir=cache,
        note_after=after,
        binding=binding,
    )
    return ClaimFixture(
        intent=intent,
        vault=vault,
        cache=cache,
        transactions=home / ".local" / "share" / "hapax" / "claim-publications",
        locks=home / ".local" / "state" / "hapax" / "task-locks",
    )


def _tree_snapshot(root: Path) -> tuple[tuple[str, str, int | None, str | None], ...]:
    if not root.exists() and not root.is_symlink():
        return ((".", "absent", None, None),)
    paths = (root, *sorted(root.rglob("*"))) if root.is_dir() else (root,)
    rows: list[tuple[str, str, int | None, str | None]] = []
    for path in paths:
        relative = "." if path == root else str(path.relative_to(root))
        if path.is_symlink():
            rows.append((relative, "symlink", None, os.readlink(path)))
        elif path.is_dir():
            rows.append((relative, "directory", stat.S_IMODE(path.stat().st_mode), None))
        elif path.is_file():
            rows.append(
                (
                    relative,
                    "file",
                    stat.S_IMODE(path.stat().st_mode),
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                )
            )
        else:
            rows.append((relative, "other", None, None))
    return tuple(rows)


def _file_identity_snapshot(
    paths: tuple[Path, ...],
) -> tuple[tuple[Path, bytes, int, int, int], ...]:
    rows: list[tuple[Path, bytes, int, int, int]] = []
    for path in paths:
        metadata = path.stat(follow_symlinks=False)
        rows.append(
            (
                path,
                path.read_bytes(),
                stat.S_IMODE(metadata.st_mode),
                metadata.st_ino,
                metadata.st_mtime_ns,
            )
        )
    return tuple(rows)


def _write_model(path: Path, model: object) -> Path:
    payload = model.model_dump(mode="json", by_alias=True)  # type: ignore[attr-defined]
    path.write_bytes(_canonical(payload) + b"\n")
    path.chmod(0o600)
    return path


def _trusted_resolver(query: object, valid_until: datetime) -> ExecutionTrustResolver:
    resolver_address = _address("trust-resolver:test")
    envelope = build_execution_trust_envelope(
        query,
        resolver=resolver_address,
        decision="trusted",
        event_frontier=_address("trust-frontier:test"),
        root_dispositions=tuple(
            RootDisposition(
                root=root,
                disposition="current",
                superseding_roots=(),
                reason_codes=(),
                source_event_refs=(f"event:trust:{index}",),
            )
            for index, root in enumerate(query.required_roots)
        ),
        checked_at=query.queried_at,
        stale_after=valid_until,
    )
    return ExecutionTrustResolver(resolver=resolver_address, envelopes=(envelope,))


def _active_admission_fixture(
    tmp_path: Path,
    fixture: ClaimFixture,
) -> AdmissionFixture:
    now = datetime(2026, 7, 11, 12, 30, tzinfo=UTC)
    valid_until = now + timedelta(minutes=30)
    checked_at = now + timedelta(minutes=2)
    basis = prospective_claim_publication_basis(fixture.intent)
    claim_intent = ContentAddress(
        ref=fixture.intent.intent_ref,
        sha256=fixture.intent.intent_sha256,
    )
    basis_address = ContentAddress(ref=basis.basis_ref, sha256=basis.basis_hash)
    mutation_scope = claim_publication_mutation_scope_address(fixture.intent)
    coordinates = build_protected_claim_coordinates(
        state="prospective",
        task_ref=fixture.intent.task_id,
        lane=fixture.intent.role,
        session_ref=fixture.intent.session_id,
        claim_epoch=fixture.intent.claim_epoch,
        claim_publication_intent=claim_intent,
        claim_basis=basis_address,
    )

    effect_target = mutation_scope
    reconciliation = _address("claim-reconciliation:test")
    effect_manifest = build_effect_manifest(
        operation="claim.publish",
        capability_role="claim_publisher",
        execution_host="appendix",
        mutating=True,
        external_effect=False,
        effect_classes=("claim_publication",),
        effect_targets=(effect_target,),
        scope_refs=(mutation_scope.ref,),
        observation_contract=_address("claim-observation-contract:test"),
        completion_predicate=_address("claim-completion-predicate:test"),
        idempotence_class="idempotent",
        reconciliation_contract=reconciliation,
        compensation=None,
    )
    manifest_address = ContentAddress(
        ref=effect_manifest.manifest_ref,
        sha256=effect_manifest.manifest_hash,
    )
    raw_invocation = _address("raw-claim-invocation:test")
    aperture = build_protected_aperture_decision(
        raw_invocation=raw_invocation,
        disposition="protected",
        aperture_id=None,
        surface="intake",
        operation="claim.publish",
        classifier_module=_address("aperture-classifier:test"),
    )
    runtime_identity = _address("runtime:test")
    ingress_module = _address("claim-ingress-module:test")
    admission_module = _address("claim-admission-module:test")
    protected_request = build_protected_action_request(
        aperture,
        coordinates,
        platform="codex",
        mode="headless",
        profile="ultra",
        execution_host="appendix",
        runtime_identity=runtime_identity,
        ingress_module=ingress_module,
        admission_module=admission_module,
        claim_mode=fixture.intent.claim_mode,
        effect_manifest=manifest_address,
        active_generation_roots=(ingress_module, admission_module),
        requested_effect_targets=(effect_target,),
        requested_scope_refs=(mutation_scope.ref,),
        supersession_frontier_ref="supersession-frontier:test",
        requested_at=now,
        mutating=True,
    )
    protected_request_address = ContentAddress(
        ref=protected_request.request_ref,
        sha256=protected_request.request_hash,
    )
    context_position = _address("context-position:test")
    acting_subject = _address("subject:test")
    parent_spec = _address("parent-spec:test")
    decomposition = _address("decomposition:test")
    action_body: dict[str, object] = {
        "schema": ACTION_INTENT_SCHEMA,
        "task_ref": fixture.intent.task_id,
        "position_ref": context_position.ref,
        "position_hash": context_position.sha256,
        "action_id": "claim-publication:test",
        "action_class": "claim_publication",
        "operation": "claim.publish",
        "capability_role": "claim_publisher",
        "execution_host": "appendix",
        "acting_subject": acting_subject.model_dump(mode="json"),
        "protected_action_request": protected_request_address.model_dump(mode="json"),
        "effect_manifest": manifest_address.model_dump(mode="json"),
        "requested_effect_targets": (effect_target.model_dump(mode="json"),),
        "parent_spec": parent_spec.model_dump(mode="json"),
        "decomposition": decomposition.model_dump(mode="json"),
        "requested_scope_refs": (mutation_scope.ref,),
        "required_authorization_flags": ("implementation_authorized",),
        "lifecycle_admission_ref": None,
        "lifecycle_transition_to": None,
        "lifecycle_transition_edge": None,
        "mutating": True,
        "may_authorize": False,
    }
    action_hash = _domain_hash(ACTION_INTENT_SCHEMA, action_body)
    action = ActionIntent.model_validate(
        {
            **action_body,
            "intent_ref": f"action-intent@sha256:{action_hash}",
            "intent_hash": action_hash,
        }
    )
    action_address = ContentAddress(ref=action.intent_ref, sha256=action.intent_hash)

    issuer = _address("issuer:test")
    authority = build_authority_evidence(
        authority_source=_address("sovereign-act:test"),
        authenticated_receipt=_address("authenticated-authority-receipt:test"),
        issuer=issuer,
        subject=acting_subject,
        authority_case=fixture.intent.binding.authority_case,
        authority_ceiling="bounded_machine_execution",
        authorized_action_classes=("claim_publication",),
        authorized_operations=("claim.publish",),
        authorized_flags=("implementation_authorized",),
        scope_refs=(mutation_scope.ref,),
        not_before=now - timedelta(minutes=1),
        valid_until=valid_until,
        supersession_frontier_ref="supersession-frontier:test",
    )
    evidence_address = ContentAddress(
        ref=authority.evidence_ref,
        sha256=authority.evidence_hash,
    )
    trust_subjects = (
        action_address,
        evidence_address,
        context_position,
        authority.authority_source,
        issuer,
        acting_subject,
    )
    trust_query = build_execution_trust_query(
        trust_class="authenticated_authority_receipt",
        subject_roots=trust_subjects,
        presented_receipt=authority.authenticated_receipt,
        required_roots=trust_subjects,
        supersession_frontier_ref=authority.supersession_frontier_ref,
        queried_at=now,
    )
    trust_envelope = build_execution_trust_envelope(
        trust_query,
        resolver=_address("authority-trust-resolver:test"),
        decision="trusted",
        event_frontier=_address("authority-trust-frontier:test"),
        root_dispositions=tuple(
            RootDisposition(
                root=root,
                disposition="current",
                superseding_roots=(),
                reason_codes=(),
                source_event_refs=(f"event:authority:{index}",),
            )
            for index, root in enumerate(trust_query.required_roots)
        ),
        checked_at=now,
        stale_after=valid_until,
    )
    grant_body: dict[str, object] = {
        "schema": VALID_AUTHORITY_GRANT_SCHEMA,
        "intent_ref": action.intent_ref,
        "intent_hash": action.intent_hash,
        "evidence_ref": authority.evidence_ref,
        "evidence_hash": authority.evidence_hash,
        "authority_source": authority.authority_source.model_dump(mode="json"),
        "authenticated_receipt": authority.authenticated_receipt.model_dump(mode="json"),
        "authority_issuer": issuer.model_dump(mode="json"),
        "acting_subject": acting_subject.model_dump(mode="json"),
        "authority_trust_query": trust_query.model_dump(mode="json", by_alias=True),
        "authority_trust_envelope": trust_envelope.model_dump(mode="json", by_alias=True),
        "position_ref": context_position.ref,
        "position_hash": context_position.sha256,
        "task_ref": fixture.intent.task_id,
        "authority_case": fixture.intent.binding.authority_case,
        "authority_ceiling": authority.authority_ceiling,
        "action_class": "claim_publication",
        "operation": "claim.publish",
        "authorized_flags": ("implementation_authorized",),
        "scope_refs": (mutation_scope.ref,),
        "issued_at": _wire_time(now),
        "valid_until": _wire_time(valid_until),
        "supersession_frontier_ref": authority.supersession_frontier_ref,
        "validation_method_ref": "validation-method:test",
        "authorizes_machine_admission": True,
        "authorizes_operator": False,
        "may_mint_sovereign_act": False,
    }
    grant_hash = _domain_hash(VALID_AUTHORITY_GRANT_SCHEMA, grant_body)
    grant = ValidAuthorityGrant.model_validate(
        {
            **grant_body,
            "grant_ref": f"authority-grant@sha256:{grant_hash}",
            "grant_hash": grant_hash,
        }
    )

    leaf = "codex.headless.full#base"
    descriptor = build_executor_descriptor(
        executor=_address("claim-executor:test"),
        adapter=_address("claim-adapter:test"),
        harness=_address("claim-harness:test"),
        runtime_identity=runtime_identity,
        active_generation_roots=(ingress_module, admission_module),
        execution_host="appendix",
        platform="codex",
        mode="headless",
        profile="ultra",
        selected_descriptor_leaf=leaf,
        entrypoint="claim-publisher:test",
    )
    registry = build_executor_registry_projection(
        execution_host="appendix",
        registry_source=_address("executor-registry:test"),
        event_frontier=_address("executor-registry-frontier:test"),
        descriptors=(descriptor,),
        observed_at=now,
        checked_at=now,
        stale_after=valid_until,
    )
    target = build_execution_target_evidence(
        host_scoped_claim=_address("host-claim:test"),
        effect_manifest=effect_manifest,
        executor_descriptor=descriptor,
        executor_registry_projection=registry,
        environment_observation=_address("environment:test"),
        observed_at=now,
        checked_at=now,
        stale_after=valid_until,
    )
    decision = RouteDecision(
        decision_id="route-decision:test",
        created_at=now,
        task_id=fixture.intent.task_id,
        lane=fixture.intent.role,
        route_id="codex.headless.full",
        platform="codex",
        mode="headless",
        profile="ultra",
        action=DispatchAction.LAUNCH,
        policy_outcome="test",
        launch_allowed=True,
        prompt_allowed=True,
        quality_floor_satisfied=True,
        authority_allowed=True,
        selected_descriptor_leaf=leaf,
        local_execution_target="appendix",
        message="test",
    )
    route_decision = content_address(decision.decision_id, decision)
    target_address = ContentAddress(ref=target.target_ref, sha256=target.target_hash)
    descriptor_address = ContentAddress(
        ref=descriptor.descriptor_ref,
        sha256=descriptor.descriptor_hash,
    )
    registry_address = ContentAddress(
        ref=registry.projection_ref,
        sha256=registry.projection_hash,
    )
    task_note = sdlc_claim.claim_publication_task_note_address(fixture.intent)
    grant_address = ContentAddress(ref=grant.grant_ref, sha256=grant.grant_hash)
    admission_body: dict[str, object] = {
        "schema": EXECUTION_ADMISSION_SCHEMA,
        "decision": "admit",
        "lease_eligible": True,
        "task_ref": fixture.intent.task_id,
        "lane": fixture.intent.role,
        "session_ref": fixture.intent.session_id,
        "authority_case": fixture.intent.binding.authority_case,
        "intent": action_address.model_dump(mode="json"),
        "effect_manifest": manifest_address.model_dump(mode="json"),
        "authority_grant": grant_address.model_dump(mode="json"),
        "authority_trust_query": trust_query.model_dump(mode="json", by_alias=True),
        "authority_trust_envelope": trust_envelope.model_dump(mode="json", by_alias=True),
        "task_note": task_note.model_dump(mode="json"),
        "parent_spec": parent_spec.model_dump(mode="json"),
        "decomposition": decomposition.model_dump(mode="json"),
        "context_frame": _address("context-frame:test").model_dump(mode="json"),
        "context_position": context_position.model_dump(mode="json"),
        "canon_bundle": _address("canon-bundle:test").model_dump(mode="json"),
        "canon_image": _address("canon-image:test").model_dump(mode="json"),
        "impingement_trace": _address("impingement-trace:test").model_dump(mode="json"),
        "fact_frontier": _address("fact-frontier:test").model_dump(mode="json"),
        "context_selection": _address("context-selection:test").model_dump(mode="json"),
        "audience_seal_receipt": _address("audience-seal:test").model_dump(mode="json"),
        "claim_publication_intent": claim_intent.model_dump(mode="json"),
        "demand_vector": _address("demand-vector:test").model_dump(mode="json"),
        "demand_derivation_receipt": _address("demand-derivation:test").model_dump(mode="json"),
        "supply_vector": _address("supply-vector:test").model_dump(mode="json"),
        "supply_refresh_receipt": _address("supply-refresh:test").model_dump(mode="json"),
        "route_decision": route_decision.model_dump(mode="json"),
        "selected_descriptor_leaf": leaf,
        "dependency_closure": _address("dependency-closure:test").model_dump(mode="json"),
        "quota_reservation": _address("quota-reservation:test").model_dump(mode="json"),
        "execution_target": target_address.model_dump(mode="json"),
        "dispatch_message_id": fixture.intent.binding.dispatch_message_id,
        "idempotency_key": fixture.intent.binding.coord_dispatch_idempotency_key,
        "authorized_flags": grant.authorized_flags,
        "immutable_scope_refs": grant.scope_refs,
        "issued_at": _wire_time(now),
        "valid_until": _wire_time(valid_until),
        "supersession_frontier_ref": authority.supersession_frontier_ref,
        "supersedes_refs": (),
        "reason_codes": (),
        "repair_refs": (),
        "may_authorize": False,
        "authorizes_operator": False,
    }
    admission_hash = _domain_hash(EXECUTION_ADMISSION_SCHEMA, admission_body)
    admission = ExecutionAdmission.model_validate(
        {
            **admission_body,
            "admission_ref": f"execution-admission@sha256:{admission_hash}",
            "admission_hash": admission_hash,
        }
    )
    bound_call = build_bound_execution_call(
        admission,
        action,
        grant,
        basis,
        coordinates,
        protected_request,
        task_note,
        target,
        decision,
        effect_manifest,
        descriptor,
        registry,
        invocation_id="claim-publication-invocation:test",
        attempt_fence="c" * 64,
    )
    issuer_receipt = _address("lease-issuer-receipt:test")
    issuer_query = build_execution_lease_issuer_trust_query(
        admission,
        grant,
        basis,
        target,
        bound_call,
        effect_manifest,
        descriptor,
        registry,
        issuer_receipt=issuer_receipt,
        queried_at=now + timedelta(minutes=1),
    )
    issuer_resolver = _trusted_resolver(issuer_query, valid_until)
    lease = mint_execution_lease(
        admission,
        action,
        grant,
        basis,
        target,
        bound_call,
        effect_manifest,
        descriptor,
        registry,
        issuer_receipt=issuer_receipt,
        now=now + timedelta(minutes=1),
        trust_resolver=issuer_resolver,
    )
    assert lease.issuer_trust_query == issuer_query
    assert lease.issuer_trust_envelope == issuer_resolver.require_trusted(issuer_query)

    proof_root = tmp_path / "admission-proofs"
    proof_root.mkdir()
    paths = (
        _write_model(proof_root / "action-intent.json", action),
        _write_model(proof_root / "execution-admission.json", admission),
        _write_model(proof_root / "valid-authority-grant.json", grant),
        _write_model(proof_root / "authority-evidence.json", authority),
        _write_model(proof_root / "execution-lease.json", lease),
    )
    consumption = ClaimAdmissionConsumption.create(
        fixture.intent,
        action_intent_path=paths[0],
        execution_admission_path=paths[1],
        valid_authority_grant_path=paths[2],
        authority_evidence_path=paths[3],
        execution_lease_path=paths[4],
        checked_at=checked_at,
    )
    assert consumption.prospective_claim_basis == basis_address
    assert consumption.executor_descriptor == descriptor_address
    assert consumption.executor_registry_projection == registry_address
    return AdmissionFixture(
        consumption=consumption,
        action=action,
        admission=admission,
        grant=grant,
        basis=basis,
        target=target,
        bound_call=bound_call,
        effect_manifest=effect_manifest,
        executor_descriptor=descriptor,
        executor_registry_projection=registry,
        issuer_receipt=issuer_receipt,
        issuer_resolver=issuer_resolver,
        lease=lease,
        checked_at=checked_at,
        valid_until=valid_until,
        proof_paths=paths,
    )


def _rebuild_admission(admission: ExecutionAdmission, **updates: object) -> ExecutionAdmission:
    body = admission.model_dump(
        mode="json",
        by_alias=True,
        exclude={"admission_ref", "admission_hash"},
    )
    body.update(updates)
    digest = _domain_hash(EXECUTION_ADMISSION_SCHEMA, body)
    return ExecutionAdmission.model_validate(
        {
            **body,
            "admission_ref": f"execution-admission@sha256:{digest}",
            "admission_hash": digest,
        }
    )


def _rebuild_bound_call(call: BoundExecutionCall, **updates: object) -> BoundExecutionCall:
    body = call.model_dump(mode="json", by_alias=True, exclude={"call_ref", "call_hash"})
    body.update(updates)
    digest = _domain_hash(BOUND_EXECUTION_CALL_SCHEMA, body)
    return BoundExecutionCall.model_validate(
        {
            **body,
            "call_ref": f"bound-execution-call@sha256:{digest}",
            "call_hash": digest,
        }
    )


def _mint_lease(active: AdmissionFixture, **overrides: object) -> ExecutionLease:
    args: dict[str, object] = {
        "admission": active.admission,
        "intent": active.action,
        "grant": active.grant,
        "claim_basis": active.basis,
        "target": active.target,
        "bound_call": active.bound_call,
        "effect_manifest": active.effect_manifest,
        "executor_descriptor": active.executor_descriptor,
        "executor_registry_projection": active.executor_registry_projection,
        "issuer_receipt": active.issuer_receipt,
        "now": active.lease.issued_at,
        "trust_resolver": active.issuer_resolver,
    }
    args.update(overrides)
    return mint_execution_lease(
        args["admission"],  # type: ignore[arg-type]
        args["intent"],  # type: ignore[arg-type]
        args["grant"],  # type: ignore[arg-type]
        args["claim_basis"],  # type: ignore[arg-type]
        args["target"],  # type: ignore[arg-type]
        args["bound_call"],  # type: ignore[arg-type]
        args["effect_manifest"],  # type: ignore[arg-type]
        args["executor_descriptor"],  # type: ignore[arg-type]
        args["executor_registry_projection"],  # type: ignore[arg-type]
        issuer_receipt=args["issuer_receipt"],  # type: ignore[arg-type]
        now=args["now"],  # type: ignore[arg-type]
        trust_resolver=args["trust_resolver"],  # type: ignore[arg-type]
        expires_at=args.get("expires_at"),  # type: ignore[arg-type]
        supersedes_refs=args.get("supersedes_refs", ()),  # type: ignore[arg-type]
    )


def test_mint_execution_lease_requires_trusted_issuer_resolver(tmp_path: Path) -> None:
    active = _active_admission_fixture(tmp_path, _fixture(tmp_path))

    with pytest.raises(ExecutionAdmissionError) as raised:
        _mint_lease(active, trust_resolver=None)

    assert raised.value.reason_code == "execution_trust_resolver_unavailable"


def test_mint_execution_lease_binds_roots_and_clamps_expiry(tmp_path: Path) -> None:
    active = _active_admission_fixture(tmp_path, _fixture(tmp_path))

    lease = _mint_lease(
        active,
        expires_at=active.checked_at,
        supersedes_refs=("z-ref", "a-ref", "z-ref"),
    )

    assert lease.admission == ContentAddress(
        ref=active.admission.admission_ref,
        sha256=active.admission.admission_hash,
    )
    assert lease.authority_grant == ContentAddress(
        ref=active.grant.grant_ref,
        sha256=active.grant.grant_hash,
    )
    assert lease.claim_basis == active.basis
    assert lease.bound_call == active.bound_call
    assert lease.effect_manifest == ContentAddress(
        ref=active.effect_manifest.manifest_ref,
        sha256=active.effect_manifest.manifest_hash,
    )
    assert lease.executor_descriptor == ContentAddress(
        ref=active.executor_descriptor.descriptor_ref,
        sha256=active.executor_descriptor.descriptor_hash,
    )
    assert lease.executor_registry_projection == ContentAddress(
        ref=active.executor_registry_projection.projection_ref,
        sha256=active.executor_registry_projection.projection_hash,
    )
    assert lease.issuer_trust_envelope == active.issuer_resolver.require_trusted(
        lease.issuer_trust_query
    )
    assert lease.issued_at == lease.not_before == active.lease.issued_at
    assert lease.expires_at == _wire_time(active.checked_at)
    assert lease.supersedes_refs == ("a-ref", "z-ref")
    assert lease.authorizes_machine_adapter is True
    assert lease.authorizes_operator is False


def test_mint_execution_lease_rejects_admission_intent_mismatch(tmp_path: Path) -> None:
    active = _active_admission_fixture(tmp_path, _fixture(tmp_path))
    other_intent = _address("other-action-intent:test")
    tampered_admission = _rebuild_admission(
        active.admission,
        intent=other_intent.model_dump(mode="json"),
    )
    tampered_bound_call = _rebuild_bound_call(
        active.bound_call,
        admission=ContentAddress(
            ref=tampered_admission.admission_ref,
            sha256=tampered_admission.admission_hash,
        ).model_dump(mode="json"),
        action_intent=other_intent.model_dump(mode="json"),
    )

    with pytest.raises(ExecutionAdmissionError) as raised:
        _mint_lease(active, admission=tampered_admission, bound_call=tampered_bound_call)

    assert raised.value.reason_code == "execution_lease_input_mismatch"
    assert "admission_intent" in str(raised.value)


def test_mint_execution_lease_rejects_malformed_input(tmp_path: Path) -> None:
    active = _active_admission_fixture(tmp_path, _fixture(tmp_path))

    with pytest.raises(ExecutionAdmissionError) as raised:
        _mint_lease(active, claim_basis=object())

    assert raised.value.reason_code == "execution_lease_input_malformed"


def test_mint_execution_lease_rejects_ineligible_admission(tmp_path: Path) -> None:
    active = _active_admission_fixture(tmp_path, _fixture(tmp_path))
    held = _rebuild_admission(
        active.admission,
        decision="hold",
        lease_eligible=False,
        reason_codes=("issuer_hold",),
        repair_refs=("repair:issuer_hold",),
    )

    with pytest.raises(ExecutionAdmissionError) as raised:
        _mint_lease(active, admission=held)

    assert raised.value.reason_code == "execution_lease_admission_not_eligible"


def test_mint_execution_lease_rejects_authority_mismatch(tmp_path: Path) -> None:
    active = _active_admission_fixture(tmp_path, _fixture(tmp_path))
    mismatched = _rebuild_admission(
        active.admission,
        authority_grant=_address("other-authority-grant:test").model_dump(mode="json"),
    )

    with pytest.raises(ExecutionAdmissionError) as raised:
        _mint_lease(active, admission=mismatched)

    assert raised.value.reason_code == "execution_lease_authority_mismatch"


def test_mint_execution_lease_rejects_noncurrent_inputs(tmp_path: Path) -> None:
    active = _active_admission_fixture(tmp_path, _fixture(tmp_path))

    with pytest.raises(ExecutionAdmissionError) as raised:
        _mint_lease(active, now=active.valid_until)

    assert raised.value.reason_code == "execution_lease_inputs_not_current"


def test_mint_execution_lease_rejects_bound_call_mismatch(tmp_path: Path) -> None:
    active = _active_admission_fixture(tmp_path / "one", _fixture(tmp_path / "one"))
    other = _active_admission_fixture(tmp_path / "two", _fixture(tmp_path / "two", task_id="beta"))

    with pytest.raises(ExecutionAdmissionError) as raised:
        _mint_lease(active, target=other.target)

    assert raised.value.reason_code == "execution_lease_input_mismatch"
    assert "execution_target" in str(raised.value)


def test_mint_execution_lease_rejects_empty_validity_window(tmp_path: Path) -> None:
    active = _active_admission_fixture(tmp_path, _fixture(tmp_path))

    with pytest.raises(ExecutionAdmissionError) as raised:
        _mint_lease(active, expires_at=active.lease.issued_at)

    assert raised.value.reason_code == "execution_lease_validity_empty"


def test_current_execution_lease_retains_independent_issuer_refusal(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)

    with pytest.raises(ExecutionAdmissionError) as raised:
        require_current_execution_lease(
            active.lease,
            active.admission,
            active.action,
            active.grant,
            object(),
            object(),
            object(),
            object(),
            object(),
            object(),
            object(),
            object(),
            object(),
            queried_at=active.checked_at,
        )

    assert raised.value.reason_code == "independent_execution_lease_issuer_unavailable"
    assert "install an independently authenticated Gate-0B lease issuer" in str(raised.value)


def _apply_projection_postimages(projections: tuple[object, ...]) -> None:
    for projection in projections:
        path = projection.path
        if projection.after is None:
            if path.exists() or path.is_symlink():
                path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(projection.after)
        assert projection.after_mode is not None
        path.chmod(projection.after_mode)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _write_history_file(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    path.write_bytes(content)
    path.chmod(0o600)
    return path


def _materialize_manifest(
    root: Path,
    publication_id: str,
    projections: tuple[object, ...],
    static: dict[str, object],
    *,
    state: str,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    directory = root / publication_id
    for index, projection in enumerate(projections):
        for label, content in (("before", projection.before), ("after", projection.after)):
            if content is not None:
                _write_history_file(directory / f"{index:04d}.{label}", content)
    return _write_history_file(
        directory / "manifest.json",
        _canonical_bytes({**static, "reason_code": None, "state": state}) + b"\n",
    )


def _materialize_v1_history(fixture: ClaimFixture, *, state: str = "applied") -> str:
    projections = sdlc_claim._projections(fixture.intent)
    publication_id = claim_publication_id(fixture.intent)
    if state == "applied":
        _apply_projection_postimages(projections)
    manifest = _materialize_manifest(
        fixture.transactions,
        publication_id,
        projections,
        sdlc_claim._static_manifest(fixture.intent, projections, publication_id),
        state=state,
    )
    assert manifest.is_file()
    if state == "applied":
        _write_history_file(
            claim_publication_receipt_path(fixture.cache, fixture.intent.binding),
            _canonical_bytes(
                sdlc_claim._receipt_record(fixture.intent, projections, publication_id)
            )
            + b"\n",
        )
    return publication_id


def _historical_consumption(
    fixture: ClaimFixture,
    active: AdmissionFixture,
) -> HistoricalClaimAdmissionConsumptionV1:
    return HistoricalClaimAdmissionConsumptionV1.create(
        fixture.intent,
        execution_admission_path=active.proof_paths[1],
        valid_authority_grant_path=active.proof_paths[2],
        authority_evidence_path=active.proof_paths[3],
        checked_at=active.checked_at,
    )


def _materialize_admitted_history(
    fixture: ClaimFixture,
    consumption: HistoricalClaimAdmissionConsumptionV1 | ClaimAdmissionConsumption,
) -> str:
    projections = sdlc_claim._admitted_projections(fixture.intent, consumption)
    publication_id = admitted_claim_publication_id(fixture.intent, consumption)
    _apply_projection_postimages(projections[:7])
    _materialize_manifest(
        fixture.transactions,
        publication_id,
        projections,
        sdlc_claim._admitted_static_manifest(
            fixture.intent,
            consumption,
            projections,
            publication_id,
        ),
        state="applied",
    )
    _write_history_file(
        claim_publication_receipt_path(fixture.cache, fixture.intent.binding),
        _canonical_bytes(
            sdlc_claim._admitted_receipt_record(
                fixture.intent,
                consumption,
                projections,
                publication_id,
            )
        )
        + b"\n",
    )
    return publication_id


def _resolve(fixture: ClaimFixture):
    return resolve_applied_claim_publication(
        vault_root=fixture.vault,
        cache_dir=fixture.cache,
        role=fixture.intent.role,
        session_id=fixture.intent.session_id,
        task_id=fixture.intent.task_id,
        transaction_root=fixture.transactions,
        lock_root=fixture.locks,
    )


def _activation_fixture(tmp_path: Path):
    fixture = _fixture(tmp_path, task_id="claim-activation-cache-rehydrate-fixture".ljust(54, "x"))
    active = _active_admission_fixture(tmp_path, fixture)
    receipt = sdlc_claim._apply_admitted_claim_publication_transaction(
        fixture.intent,
        active.consumption,
        transaction_root=fixture.transactions,
        receipt_root=tmp_path / "receipts",
        lock_root=fixture.locks,
        now=active.checked_at,
    )
    fixture.intent.note_path.write_bytes(
        fixture.intent.note_after.replace(
            b"updated_at: 2026-07-11T12:00:00Z", b"updated_at: 2026-09-05T02:30:00Z"
        )
        + b"\nLegitimate progress after publication.\n"
    )
    for path in fixture.cache.glob("cc-active-task-*"):
        path.unlink()
    return fixture, receipt


def _rehydrate(fixture: ClaimFixture, receipt_root: Path):
    return sdlc_claim.rehydrate_applied_activation_projections(
        cache_dir=fixture.cache,
        transaction_root=fixture.transactions,
        receipt_root=receipt_root,
        lock_root=fixture.locks,
        task_id=fixture.intent.task_id,
    )


@pytest.mark.parametrize("state", ["aborted", "applied"], ids=["aborted", "superseded"])
@pytest.mark.parametrize("position", ["before", "after"])
def test_rehydrate_selects_current_publication_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str, position: str
) -> None:
    # Keep A away from the hash-space endpoints so both requested B orderings
    # have a substantial probability on every attempt, regardless of tmp_path.
    for attempt in range(128):
        fixture, receipt = _activation_fixture(tmp_path / f"current-{attempt}")
        if "claim-pub-4" <= receipt.publication_id < "claim-pub-c":
            break
    else:
        pytest.fail("could not construct a central publication identity")
    original = {
        path: (path.read_bytes(), path.stat()) for path in tmp_path.rglob("*") if path.is_file()
    }
    fixture.intent.note_path.write_bytes(
        fixture.intent.note_path.read_bytes().replace(b"status: claimed", b"status: pr_open")
    )
    # Publish a second genuine admission with the SAME lease vector. Only the
    # exact publication named by the surviving receipt distinguishes A from B.
    for attempt in range(128):
        intent = ClaimPublicationIntent.create(
            task=resolve_task_note(fixture.vault, fixture.intent.task_id),
            cache_dir=fixture.cache,
            note_after=fixture.intent.note_path.read_bytes()
            + f"\nPublication B {attempt}\n".encode(),
            binding=fixture.intent.binding,
        )
        proof_root = tmp_path / f"publication-b-{attempt}"
        proof_root.mkdir()
        active = _active_admission_fixture(proof_root, replace(fixture, intent=intent))
        other_id = admitted_claim_publication_id(intent, active.consumption)
        if (other_id < receipt.publication_id) == (position == "before"):
            break
    else:
        pytest.fail("could not construct the requested publication ordering")
    receipt.receipt_path.unlink()
    for projection in sdlc_claim._projections(fixture.intent)[1:7]:
        projection.path.unlink(missing_ok=True)
    other = sdlc_claim._apply_admitted_claim_publication_transaction(
        intent,
        active.consumption,
        transaction_root=fixture.transactions,
        receipt_root=receipt.receipt_path.parent,
        lock_root=fixture.locks,
        now=active.checked_at,
    )
    record = json.loads(other.manifest_path.read_bytes())
    record["state"] = state
    record["reason_code"] = "retained-publication-b"
    other.manifest_path.write_bytes(_canonical(record) + b"\n")
    # Retain B's journal; A's receipt and surviving sidecars are the current plane.
    for path, (content, metadata) in original.items():
        path.write_bytes(content)
        path.chmod(stat.S_IMODE(metadata.st_mode))
        os.utime(path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
    paths = tuple(sdlc_claim._projections(fixture.intent)[index].path for index in (1, 4))
    for path in paths:
        path.unlink()
    before_paths = tuple(path for path in tmp_path.rglob("*") if path.is_file())
    before = _file_identity_snapshot(before_paths)
    list_names = sdlc_claim.ReadOnlyFsSnapshot.list_names
    runs = []
    for reverse in (False, True):
        with monkeypatch.context() as patch:
            patch.setattr(
                sdlc_claim.ReadOnlyFsSnapshot,
                "list_names",
                lambda self, directory: tuple(sorted(list_names(self, directory), reverse=reverse)),
            )
            results = _rehydrate(fixture, receipt.receipt_path.parent)
        current = next(item for item in results if item.publication_id == receipt.publication_id)
        ignored = next(item for item in results if item.publication_id == other.publication_id)
        assert len(results) == 2
        assert current.state == "rehydrated"
        assert current.written_paths == paths
        assert ignored.state == state
        assert ignored.reason_code == "claim_publication_not_current"
        assert "retained-publication-b" in ignored.detail
        assert ignored.written_paths == ()
        assert _file_identity_snapshot(before_paths) == before
        assert {path for path in tmp_path.rglob("*") if path.is_file()} == set(before_paths) | set(
            paths
        )
        writes = tuple(
            (path, path.read_bytes(), stat.S_IMODE(path.stat().st_mode)) for path in paths
        )
        assert writes == tuple(
            (path, f"{fixture.intent.task_id}\n".encode(), 0o644) for path in paths
        )
        runs.append((results, writes))
        for path in paths:
            path.unlink()
    assert runs[0] == runs[1]


@pytest.mark.parametrize("failure", ["race", "cas"])
@pytest.mark.parametrize(
    "first_exists", [False, True], ids=["installed_first", "preexisting_first"]
)
def test_rehydrate_second_install_retains_partial_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str, first_exists: bool
) -> None:
    import shared.coord_projection as projection_layer

    fixture, receipt = _activation_fixture(tmp_path)
    first, second = (sdlc_claim._projections(fixture.intent)[index].path for index in (1, 4))
    if first_exists:
        first.write_bytes(f"{fixture.intent.task_id}\n".encode())
        first.chmod(0o644)
    before = _file_identity_snapshot((first,)) if first_exists else None
    rename = projection_layer._renameat2
    calls = []

    def fail_second(src_fd, src_name, dst_fd, dst_name, flags):
        calls.append(dst_name)
        if dst_name == second.name:
            if failure == "race":
                second.write_bytes(b"concurrent-owner\n")
                second.chmod(0o644)
            else:
                with monkeypatch.context() as patch:
                    patch.setattr(projection_layer.ctypes, "CDLL", lambda *args, **kwargs: object())
                    return rename(src_fd, src_name, dst_fd, dst_name, flags)
        return rename(src_fd, src_name, dst_fd, dst_name, flags)

    monkeypatch.setattr(projection_layer, "_renameat2", fail_second)
    with pytest.raises(ClaimPublicationError) as raised:
        _rehydrate(fixture, receipt.receipt_path.parent)
    assert calls == ([second.name] if first_exists else [first.name, second.name])
    assert first.read_bytes() == f"{fixture.intent.task_id}\n".encode()
    if first_exists:
        assert _file_identity_snapshot((first,)) == before
    if failure == "race":
        assert second.read_bytes() == b"concurrent-owner\n"
    else:
        assert not second.exists()
    detail = json.loads(raised.value.detail)
    assert detail["written_paths"] == ([] if first_exists else [str(first)])
    assert detail["failed_path"] == str(second)
    assert (str(first) in detail["retained_effects"]) is not first_exists
    scratches = tuple(fixture.cache.glob("*.transition-scratch"))
    assert len(scratches) == 1
    assert str(scratches[0]) in detail["retained_effects"]
    assert detail["failure_reason"] == (
        "transition_precondition_changed"
        if failure == "race"
        else "transition_atomic_cas_unavailable"
    )
    assert raised.value.reason_code == (
        "claim_activation_cache_conflict"
        if failure == "race"
        else "transition_atomic_cas_unavailable"
    )
    assert raised.value.repair_action == (
        "preserve the activation cache and retry after the named path stabilizes"
        if failure == "race"
        else "run lifecycle projection only on Linux with renameat2 support"
    )


@pytest.mark.parametrize(
    ("error", "remedy"),
    [
        (errno.ENOSPC, "free space on the named filesystem, preserve retained effects, then retry"),
        (
            errno.EIO,
            "repair the named filesystem's I/O failure, preserve retained effects, then retry",
        ),
        (errno.EACCES, "restore access to the named path, preserve retained effects, then retry"),
        (
            errno.EPERM,
            "restore permission for the named operation, preserve retained effects, then retry",
        ),
        (
            errno.ENOTDIR,
            "restore real parent directories for the named path, preserve retained effects, then retry",
        ),
    ],
    ids=["ENOSPC", "EIO", "EACCES", "EPERM", "ENOTDIR"],
)
@pytest.mark.parametrize(
    "phase", ["scratch_open", "scratch_write", "scratch_fsync", "rename", "after_rename"]
)
def test_rehydrate_filesystem_failure_is_actionable_and_retains_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: int, remedy: str, phase: str
) -> None:
    import shared.coord_projection as projection_layer

    fixture, receipt = _activation_fixture(tmp_path)
    first, second = (sdlc_claim._projections(fixture.intent)[index].path for index in (1, 4))
    original_open = projection_layer.os.open
    write = projection_layer.os.write
    rename = projection_layer._renameat2
    fsync = projection_layer.os.fsync
    renamed = False
    injected = False
    scratch_fd = None

    def fail_open(path, flags, *args, **kwargs):
        nonlocal injected, scratch_fd
        target = str(path).startswith(f".{second.name}.") and flags & os.O_CREAT
        if phase == "scratch_open" and target:
            injected = True
            raise OSError(error, os.strerror(error), str(path))
        fd = original_open(path, flags, *args, **kwargs)
        if target:
            scratch_fd = fd
        return fd

    def fail_write(fd, payload):
        nonlocal injected
        if phase == "scratch_write" and fd == scratch_fd:
            injected = True
            write(fd, payload[:3])
            raise OSError(error, os.strerror(error), str(second))
        return write(fd, payload)

    def fail_rename(src_fd, src_name, dst_fd, dst_name, flags):
        nonlocal renamed, injected
        if dst_name == second.name and phase == "rename":
            injected = True
            raise OSError(error, os.strerror(error), dst_name)
        result = rename(src_fd, src_name, dst_fd, dst_name, flags)
        if dst_name == second.name:
            renamed = True
        return result

    def fail_fsync(fd):
        nonlocal injected
        if not injected and (
            (phase == "after_rename" and renamed) or (phase == "scratch_fsync" and fd == scratch_fd)
        ):
            injected = True
            raise OSError(error, os.strerror(error), str(second))
        return fsync(fd)

    with monkeypatch.context() as patch:
        patch.setattr(projection_layer.os, "open", fail_open)
        patch.setattr(projection_layer.os, "write", fail_write)
        patch.setattr(projection_layer, "_renameat2", fail_rename)
        patch.setattr(projection_layer.os, "fsync", fail_fsync)
        with pytest.raises(ClaimPublicationError) as raised:
            _rehydrate(fixture, receipt.receipt_path.parent)
    assert injected
    assert raised.value.reason_code == f"claim_activation_cache_{errno.errorcode[error].lower()}"
    assert raised.value.repair_action == remedy
    detail = json.loads(raised.value.detail)
    assert detail["written_paths"] == [str(first)]
    assert detail["failed_path"] == str(second)
    assert detail["failure_reason"] == errno.errorcode[error]
    assert str(first) in detail["retained_effects"]
    assert first.read_bytes() == f"{fixture.intent.task_id}\n".encode()
    if phase == "after_rename":
        assert second.read_bytes() == first.read_bytes()
        assert str(second) in detail["retained_effects"]
    else:
        assert not second.exists()
    scratches = tuple(fixture.cache.glob("*.transition-scratch"))
    assert len(scratches) == (1 if phase in {"scratch_write", "scratch_fsync", "rename"} else 0)
    for scratch in scratches:
        assert str(scratch) in detail["retained_effects"]


@pytest.mark.parametrize("operation", ["link", "unlink"])
def test_rehydrate_creation_does_not_link_or_unlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    import shared.coord_projection as projection_layer

    fixture, receipt = _activation_fixture(tmp_path)

    def forbidden(*args, **kwargs):
        raise OSError(errno.EIO, f"unexpected {operation} in activation creation")

    with monkeypatch.context() as patch:
        patch.setattr(projection_layer.os, operation, forbidden)
        (result,) = _rehydrate(fixture, receipt.receipt_path.parent)
    assert result.state == "rehydrated"
    assert len(result.written_paths) == 2


def test_rehydrate_applied_activation_preserves_evolved_note_and_survivors(tmp_path: Path) -> None:
    fixture, receipt = _activation_fixture(tmp_path)
    evolved = fixture.intent.note_path.read_bytes()
    paths_before = tuple(sorted(path for path in tmp_path.rglob("*") if path.is_file()))
    before = _file_identity_snapshot(paths_before)
    with pytest.raises(ClaimPublicationError, match="claim_cache_missing"):
        resolve_applied_claim_publication(
            vault_root=fixture.vault,
            cache_dir=fixture.cache,
            role=fixture.intent.role,
            session_id=fixture.intent.session_id,
            task_id=fixture.intent.task_id,
            transaction_root=fixture.transactions,
            receipt_root=receipt.receipt_path.parent,
            lock_root=fixture.locks,
        )
    recovered = recover_claim_publications(
        cache_dir=fixture.cache,
        transaction_root=fixture.transactions,
        receipt_root=receipt.receipt_path.parent,
        lock_root=fixture.locks,
        task_id=fixture.intent.task_id,
    )
    assert [(item.state, item.reason_code) for item in recovered] == [
        ("hold", "claim_publication_postimage_drift")
    ]

    results = _rehydrate(fixture, receipt.receipt_path.parent)

    assert len(results) == 1
    result = results[0]
    expected = tuple(
        fixture.cache / f"cc-active-task-{key}"
        for key in (fixture.intent.role, f"{fixture.intent.role}-{fixture.intent.session_id}")
    )
    assert result.publication_id == receipt.publication_id
    assert result.state == "rehydrated"
    assert result.reason_code is None
    assert result.written_paths == expected
    assert result.observed_before == tuple((path, "absent") for path in expected)
    for path in expected:
        assert str(path) in result.detail
        assert path.read_bytes() == f"{fixture.intent.task_id}\n".encode()
        assert len(path.read_bytes()) == 55
        assert stat.S_IMODE(path.stat().st_mode) == 0o644
    assert fixture.intent.note_path.read_bytes() == evolved
    assert _file_identity_snapshot(paths_before) == before
    assert {path for path in tmp_path.rglob("*") if path.is_file()} == set(paths_before) | set(
        expected
    )
    resolved = resolve_applied_claim_publication(
        vault_root=fixture.vault,
        cache_dir=fixture.cache,
        role=fixture.intent.role,
        session_id=fixture.intent.session_id,
        task_id=fixture.intent.task_id,
        transaction_root=fixture.transactions,
        receipt_root=receipt.receipt_path.parent,
        lock_root=fixture.locks,
    )
    assert resolved.receipt.publication_id == receipt.publication_id
    assert resolved.current_task.content == evolved


def _assert_rehydration_refused(fixture: ClaimFixture, receipt_root: Path, reason: str) -> None:
    root = fixture.cache.parent
    tree = _tree_snapshot(root)
    files = tuple(
        sorted(path for path in root.rglob("*") if path.is_file() and not path.is_symlink())
    )
    before = _file_identity_snapshot(files)
    with pytest.raises(ClaimPublicationError) as raised:
        _rehydrate(fixture, receipt_root)
    assert raised.value.reason_code == reason
    assert raised.value.repair_action
    assert _tree_snapshot(root) == tree
    assert _file_identity_snapshot(files) == before


def test_rehydrate_idempotence_is_no_write(tmp_path: Path) -> None:
    fixture, receipt = _activation_fixture(tmp_path)
    _rehydrate(fixture, receipt.receipt_path.parent)
    paths = tuple(sorted(path for path in tmp_path.rglob("*") if path.is_file()))
    before = _file_identity_snapshot(paths)
    tree = _tree_snapshot(tmp_path)

    (result,) = _rehydrate(fixture, receipt.receipt_path.parent)

    assert result.state == "noop"
    assert result.written_paths == ()
    assert result.observed_before == ()
    assert result.reason_code is None
    assert _file_identity_snapshot(paths) == before
    assert _tree_snapshot(tmp_path) == tree


@pytest.mark.parametrize("index", [1, 4], ids=["role", "session"])
def test_rehydrate_only_missing_activation(tmp_path: Path, index: int) -> None:
    fixture, receipt = _activation_fixture(tmp_path)
    projection = sdlc_claim._projections(fixture.intent)[index]
    projection.path.write_bytes(projection.after)
    projection.path.chmod(projection.after_mode)
    before = _file_identity_snapshot((projection.path,))

    (result,) = _rehydrate(fixture, receipt.receipt_path.parent)

    assert result.state == "rehydrated"
    assert len(result.written_paths) == 1
    assert projection.path not in result.written_paths
    assert _file_identity_snapshot((projection.path,)) == before


@pytest.mark.parametrize("change", ["owner", "authority_case", "mode", "path"])
def test_rehydrate_refuses_current_identity_change(tmp_path: Path, change: str) -> None:
    fixture, receipt = _activation_fixture(tmp_path)
    note = fixture.intent.note_path
    if change == "owner":
        note.write_bytes(note.read_bytes().replace(b"assigned_to: cx-red", b"assigned_to: cx-blue"))
    elif change == "authority_case":
        note.write_bytes(note.read_bytes().replace(b"CASE-CLAIM-001", b"CASE-CLAIM-002"))
    elif change == "mode":
        note.chmod(0o600)
    else:
        note.rename(note.with_name(f"{fixture.intent.task_id}-renamed.md"))

    _assert_rehydration_refused(
        fixture, receipt.receipt_path.parent, "claim_publication_current_identity_mismatch"
    )


@pytest.mark.parametrize("index", [1, 4], ids=["role", "session"])
@pytest.mark.parametrize("change", ["bytes", "mode"])
def test_rehydrate_refuses_existing_activation_conflict(
    tmp_path: Path, index: int, change: str
) -> None:
    fixture, receipt = _activation_fixture(tmp_path)
    projection = sdlc_claim._projections(fixture.intent)[index]
    projection.path.write_bytes(b"another-task\n" if change == "bytes" else projection.after)
    projection.path.chmod(0o600 if change == "mode" else projection.after_mode)

    _assert_rehydration_refused(
        fixture, receipt.receipt_path.parent, "claim_activation_cache_conflict"
    )


@pytest.mark.parametrize(
    "sidecar",
    ["role_epoch", "role_dispatch", "session_epoch", "session_dispatch", "receipt", "manifest"],
)
@pytest.mark.parametrize("change", ["bytes", "mode", "missing"])
def test_rehydrate_refuses_surviving_postimage_drift(
    tmp_path: Path, sidecar: str, change: str
) -> None:
    fixture, receipt = _activation_fixture(tmp_path)
    projections = sdlc_claim._projections(fixture.intent)
    path = {
        "role_epoch": projections[2].path,
        "role_dispatch": projections[3].path,
        "session_epoch": projections[5].path,
        "session_dispatch": projections[6].path,
        "receipt": receipt.receipt_path,
        "manifest": receipt.manifest_path,
    }[sidecar]
    reason = "claim_publication_postimage_drift"
    if change == "bytes":
        # Semantically identical, byte-different: identity parsing alone is insufficient.
        path.write_bytes(path.read_bytes() + b"\n")
        if sidecar == "manifest":
            reason = "claim_publication_journal_noncanonical"
    elif change == "mode":
        path.chmod(0o640)
        if sidecar == "manifest":
            reason = "fs_snapshot_file_unsafe"
    else:
        path.unlink()
        if sidecar == "manifest":
            reason = "claim_publication_manifest_unreadable"

    _assert_rehydration_refused(fixture, receipt.receipt_path.parent, reason)


@pytest.mark.parametrize(
    "index",
    range(7),
    ids=[
        "note",
        "role_claim",
        "role_epoch",
        "role_dispatch",
        "session_claim",
        "session_epoch",
        "session_dispatch",
    ],
)
def test_rehydrate_refuses_projection_symlink(tmp_path: Path, index: int) -> None:
    fixture, receipt = _activation_fixture(tmp_path)
    projection = sdlc_claim._projections(fixture.intent)[index]
    target = tmp_path / "symlink-target"
    target.write_bytes(projection.after)
    target.chmod(projection.after_mode)
    projection.path.unlink(missing_ok=True)
    projection.path.symlink_to(target)

    _assert_rehydration_refused(fixture, receipt.receipt_path.parent, "fs_snapshot_file_unsafe")


@pytest.mark.parametrize("artifact", ["receipt", "manifest", "blob", "proof"])
def test_rehydrate_refuses_evidence_symlink(tmp_path: Path, artifact: str) -> None:
    fixture, receipt = _activation_fixture(tmp_path)
    if artifact == "receipt":
        path = receipt.receipt_path
    elif artifact == "manifest":
        path = receipt.manifest_path
    elif artifact == "blob":
        path = receipt.manifest_path.parent / "0000.after"
    else:
        _, projections, _, _, _ = sdlc_claim._load_any_manifest(receipt.manifest_path)
        path = projections[7].path
    target = tmp_path / "symlink-target"
    target.write_bytes(path.read_bytes())
    target.chmod(stat.S_IMODE(path.stat().st_mode))
    path.unlink()
    path.symlink_to(target)

    _assert_rehydration_refused(fixture, receipt.receipt_path.parent, "fs_snapshot_file_unsafe")


@pytest.mark.parametrize(
    "state", ["created", "projecting", "postimage_complete", "recovery_required", "aborted"]
)
def test_rehydrate_refuses_non_applied_journal(tmp_path: Path, state: str) -> None:
    fixture, receipt = _activation_fixture(tmp_path)
    record = json.loads(receipt.manifest_path.read_bytes())
    record["state"] = state
    receipt.manifest_path.write_bytes(_canonical(record) + b"\n")

    _assert_rehydration_refused(
        fixture, receipt.receipt_path.parent, "claim_publication_not_applied"
    )


@pytest.mark.parametrize("historical", [False, True], ids=["legacy", "historical"])
def test_rehydrate_refuses_non_current_consumption(tmp_path: Path, historical: bool) -> None:
    fixture = _fixture(tmp_path)
    if historical:
        active = _active_admission_fixture(tmp_path, fixture)
        _materialize_admitted_history(fixture, _historical_consumption(fixture, active))
        reason = "historical_claim_publication_recovery_forbidden"
    else:
        _materialize_v1_history(fixture)
        reason = "legacy_claim_publication_recovery_forbidden"
    with sdlc_claim._claim_publication_lock(fixture.intent, lock_root=fixture.locks):
        pass
    for path in fixture.cache.glob("cc-active-task-*"):
        path.unlink()
    receipt_root = claim_publication_receipt_path(fixture.cache, fixture.intent.binding).parent

    _assert_rehydration_refused(fixture, receipt_root, reason)


def test_rehydrate_refuses_unknown_task_without_writes(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    _assert_rehydration_refused(fixture, tmp_path / "receipts", "claim_publication_not_found")


@pytest.mark.parametrize(
    "field", ["task_id", "lane", "session_id", "claim_epoch", "authority_case"]
)
@pytest.mark.parametrize("both", [False, True], ids=["one_binding", "both_bindings"])
def test_rehydrate_refuses_changed_binding_vector(tmp_path: Path, field: str, both: bool) -> None:
    fixture, receipt = _activation_fixture(tmp_path)
    binding = fixture.intent.binding
    value = binding.claim_epoch + 1 if field == "claim_epoch" else "different-identity"
    changed = replace(binding, **{field: value})
    for index in (3, 6) if both else (6,):
        sdlc_claim._projections(fixture.intent)[index].path.write_bytes(
            _canonical(changed.to_record()) + b"\n"
        )
    if field == "claim_epoch" and both:
        for index in (2, 5):
            sdlc_claim._projections(fixture.intent)[index].path.write_bytes(
                f"{value} {fixture.intent.task_id}\n".encode()
            )

    _assert_rehydration_refused(
        fixture, receipt.receipt_path.parent, "claim_publication_postimage_drift"
    )


@pytest.mark.parametrize("artifact", ["receipt", "manifest", "proof"])
def test_rehydrate_refuses_changed_evidence(tmp_path: Path, artifact: str) -> None:
    fixture, receipt = _activation_fixture(tmp_path)
    if artifact == "proof":
        _, projections, _, _, _ = sdlc_claim._load_any_manifest(receipt.manifest_path)
        projections[7].path.write_bytes(b"changed-proof\n")
    else:
        path = receipt.receipt_path if artifact == "receipt" else receipt.manifest_path
        record = json.loads(path.read_bytes())
        if artifact == "receipt":
            record["publication_id"] = "claim-pub-" + "0" * 64
            body = {key: value for key, value in record.items() if key != "receipt_hash"}
            record["receipt_hash"] = hashlib.sha256(_canonical(body)).hexdigest()
        else:
            record["reason_code"] = "unexpected-reason"
        path.write_bytes(_canonical(record) + b"\n")

    _assert_rehydration_refused(
        fixture, receipt.receipt_path.parent, "claim_publication_postimage_drift"
    )


def test_rehydrate_allows_retired_proof_sources(tmp_path: Path) -> None:
    fixture, receipt = _activation_fixture(tmp_path)
    _, projections, _, _, _ = sdlc_claim._load_any_manifest(receipt.manifest_path)
    for projection in projections[7:]:
        projection.path.unlink()

    (result,) = _rehydrate(fixture, receipt.receipt_path.parent)

    assert result.state == "rehydrated"
    assert all(not projection.path.exists() for projection in projections[7:])


def test_rehydrate_uses_publication_lock_and_cas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from contextlib import contextmanager

    fixture, receipt = _activation_fixture(tmp_path)
    original_lock = sdlc_claim._claim_publication_lock
    original_apply = sdlc_claim._apply_projections
    locked = False
    called = False

    @contextmanager
    def checked_lock(intent, *, lock_root):
        nonlocal locked
        assert intent == fixture.intent
        assert lock_root == fixture.locks
        with original_lock(intent, lock_root=lock_root):
            locked = True
            yield
            locked = False

    def racing_apply(projections, scratches, failure_hook):
        nonlocal called
        assert locked
        called = True
        projections[0].path.write_bytes(b"concurrent-owner\n")
        projections[0].path.chmod(0o644)
        original_apply(projections, scratches, failure_hook)

    monkeypatch.setattr(sdlc_claim, "_claim_publication_lock", checked_lock)
    monkeypatch.setattr(sdlc_claim, "_apply_projections", racing_apply)

    with pytest.raises(ClaimPublicationError, match="claim_activation_cache_conflict"):
        _rehydrate(fixture, receipt.receipt_path.parent)

    assert called
    assert (
        fixture.cache / f"cc-active-task-{fixture.intent.role}"
    ).read_bytes() == b"concurrent-owner\n"
    assert not (
        fixture.cache / f"cc-active-task-{fixture.intent.role}-{fixture.intent.session_id}"
    ).exists()


def _outcome_committer(
    active: AdmissionFixture,
    *,
    outcome: str = "succeeded",
    effect_disposition: str = "applied",
    publication_snapshot: AppliedClaimPublicationSnapshot | None = None,
) -> tuple[OutcomeCommitter, OutcomeProjectionSnapshot]:
    lease = active.lease
    checked_at = active.checked_at
    observation = build_effect_observation(
        lease,
        start_event=_address("execution-start:test"),
        returncode=0 if outcome == "succeeded" else (1 if outcome == "failed" else None),
        evidence_refs=(
            claim_publication_effect_evidence_refs(publication_snapshot)
            if publication_snapshot is not None
            else (_address("effect-evidence:test"),)
        ),
        observed_at=checked_at + timedelta(seconds=1),
    )
    completion_query = build_completion_evaluation_query(
        lease,
        observation,
        queried_at=checked_at + timedelta(seconds=2),
    )
    decision = {
        "succeeded": "satisfied",
        "failed": "unsatisfied",
        "indeterminate": "unknown",
    }[outcome]
    evaluator = _address("completion-evaluator:test")
    evaluation = build_completion_evaluation(
        completion_query,
        evaluator=evaluator,
        event_frontier=_address("completion-frontier:test"),
        decision=decision,
        effect_disposition=effect_disposition,
        evaluated_at=checked_at + timedelta(seconds=2),
        reason_codes=("completion_unknown",) if decision == "unknown" else (),
    )
    committer = _address("outcome-committer:test")
    event_plane = _address("event-plane:test")
    expected_frontier = _address("event-frontier:before")
    readiness_body: dict[str, object] = {
        "schema": OUTCOME_PIPELINE_READINESS_QUERY_SCHEMA,
        "execution_lease": ContentAddress(
            ref=lease.lease_ref,
            sha256=lease.lease_hash,
        ).model_dump(mode="json"),
        "bound_execution_call": ContentAddress(
            ref=lease.bound_call.call_ref,
            sha256=lease.bound_call.call_hash,
        ).model_dump(mode="json"),
        "effect_manifest": lease.effect_manifest.model_dump(mode="json"),
        "executor_descriptor": lease.executor_descriptor.model_dump(mode="json"),
        "executor_registry_projection": lease.executor_registry_projection.model_dump(mode="json"),
        "currentness_query": _address("currentness-query:test").model_dump(mode="json"),
        "currentness_envelope": _address("currentness-envelope:test").model_dump(mode="json"),
        "completion_predicate": lease.completion_predicate.model_dump(mode="json"),
        "evaluator": evaluator.model_dump(mode="json"),
        "committer": committer.model_dump(mode="json"),
        "event_plane": event_plane.model_dump(mode="json"),
        "expected_event_frontier": expected_frontier.model_dump(mode="json"),
        "invocation_id": lease.invocation_id,
        "attempt_fence": lease.attempt_fence,
        "idempotency_key": lease.idempotency_key,
        "queried_at": _wire_time(checked_at + timedelta(seconds=3)),
        "may_authorize": False,
    }
    readiness_hash = _domain_hash(OUTCOME_PIPELINE_READINESS_QUERY_SCHEMA, readiness_body)
    readiness_query = OutcomePipelineReadinessQuery.model_validate(
        {
            **readiness_body,
            "query_ref": f"outcome-pipeline-readiness-query@sha256:{readiness_hash}",
            "query_hash": readiness_hash,
        }
    )
    readiness = build_outcome_pipeline_readiness_envelope(
        readiness_query,
        resolver=_address("readiness-resolver:test"),
        decision="ready",
        event_frontier=expected_frontier,
        checked_at=checked_at + timedelta(seconds=3),
        stale_after=checked_at + timedelta(minutes=10),
    )
    event = build_outcome_event(
        lease,
        observation,
        evaluation,
        readiness,
        occurred_at=checked_at + timedelta(seconds=4),
    )
    append = build_event_append_receipt(
        event,
        committer=committer,
        event_plane=event_plane,
        expected_frontier=expected_frontier,
        committed_frontier=_address("event-frontier:after"),
        append_status="appended",
        committed_at=checked_at + timedelta(seconds=5),
    )
    projection = build_outcome_projection_snapshot(
        committer=committer,
        event_plane=event_plane,
        activation_generation_roots=lease.active_generation_roots,
        observation=observation,
        evaluation=evaluation,
        readiness=readiness,
        event=event,
        append_receipt=append,
    )
    validity_resolver = _address("outcome-validity-resolver:test")
    validity_checked_at = checked_at + timedelta(seconds=6)
    validity_roots = outcome_projection_validity_roots(
        projection,
        checked_frontier=projection.event_frontier,
    )
    validity = build_frontier_validity_envelope(
        subject_projection=ContentAddress(
            ref=projection.snapshot_ref,
            sha256=projection.snapshot_hash,
        ),
        resolver=validity_resolver,
        event_plane=event_plane,
        source_frontier=projection.event_frontier,
        checked_frontier=projection.event_frontier,
        root_dispositions=tuple(
            RootDisposition(
                root=root,
                disposition="current",
                superseding_roots=(),
                reason_codes=(),
                source_event_refs=(f"event:outcome-validity:{index}",),
            )
            for index, root in enumerate(validity_roots)
        ),
        decision="valid",
        checked_at=validity_checked_at,
        stale_after=checked_at + timedelta(minutes=10),
    )
    return (
        _catalog_committer(
            committer=committer,
            event_plane=event_plane,
            projection_resolver=_address("outcome-projection-resolver:test"),
            validity_resolver=validity_resolver,
            frontier=projection.event_frontier,
            projections=(projection,),
            validity_envelopes=(validity,),
            observed_at=validity_checked_at,
        ),
        projection,
    )


def _catalog_committer(
    *,
    committer: ContentAddress,
    event_plane: ContentAddress,
    projection_resolver: ContentAddress,
    validity_resolver: ContentAddress,
    frontier: ContentAddress,
    projections: tuple[OutcomeProjectionSnapshot, ...],
    validity_envelopes: tuple[FrontierValidityEnvelope, ...],
    observed_at: datetime,
) -> OutcomeCommitter:
    catalog = build_outcome_replay_catalog_snapshot(
        committer=committer,
        event_plane=event_plane,
        projection_resolver=projection_resolver,
        validity_resolver=validity_resolver,
        checked_frontier=frontier,
        projections=projections,
        validity_envelopes=validity_envelopes,
        source_receipt=_address(
            f"outcome-catalog-read:{frontier.sha256}:{_wire_time(observed_at)}"
        ),
        observed_at=observed_at,
    )
    return OutcomeCommitter(
        committer=committer,
        event_plane=event_plane,
        projection_resolver=projection_resolver,
        validity_resolver=validity_resolver,
        catalog_snapshot=catalog,
    )


def _revalidated_outcome_committer(
    committer: OutcomeCommitter,
    projection: OutcomeProjectionSnapshot,
    *,
    frontier: ContentAddress,
    checked_at: datetime,
) -> tuple[OutcomeCommitter, FrontierValidityEnvelope]:
    assert committer.committer is not None
    assert committer.event_plane is not None
    assert committer.projection_resolver is not None
    assert committer.validity_resolver is not None
    roots = outcome_projection_validity_roots(
        projection,
        checked_frontier=frontier,
    )
    validity = build_frontier_validity_envelope(
        subject_projection=ContentAddress(
            ref=projection.snapshot_ref,
            sha256=projection.snapshot_hash,
        ),
        resolver=committer.validity_resolver,
        event_plane=committer.event_plane,
        source_frontier=projection.event_frontier,
        checked_frontier=frontier,
        root_dispositions=tuple(
            RootDisposition(
                root=root,
                disposition="current",
                superseding_roots=(),
                reason_codes=(),
                source_event_refs=(f"event:outcome-revalidation:{index}",),
            )
            for index, root in enumerate(roots)
        ),
        decision="valid",
        checked_at=checked_at,
        stale_after=checked_at + timedelta(minutes=10),
    )
    return (
        _catalog_committer(
            committer=committer.committer,
            event_plane=committer.event_plane,
            projection_resolver=committer.projection_resolver,
            validity_resolver=committer.validity_resolver,
            frontier=frontier,
            projections=(projection,),
            validity_envelopes=(validity,),
            observed_at=checked_at,
        ),
        validity,
    )


def test_actual_outcome_receipt_matches_context_observability_protocol(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)
    _, projection = _outcome_committer(active)

    actual = projection.outcome_receipt
    receipt: CommittedOutcomeReceiptLike = actual
    body = receipt.model_dump(
        mode="json",
        by_alias=True,
        exclude={"receipt_ref", "receipt_hash"},
    )
    expected_hash = hashlib.sha256(
        OUTCOME_RECEIPT_SCHEMA.encode("ascii") + b"\0" + canonical_json_bytes(body)
    ).hexdigest()

    validated = context_contract._validated_committed_outcome_receipt(receipt)

    assert validated.model_dump(mode="json", by_alias=True) == body
    assert actual.schema_id == OUTCOME_RECEIPT_SCHEMA
    assert body["schema"] == OUTCOME_RECEIPT_SCHEMA
    assert validated.committed_at == actual.committed_at
    assert actual.committed_at == "2026-07-11T12:32:05.000000Z"
    assert receipt.receipt_hash == expected_hash
    assert receipt.receipt_ref == f"outcome-receipt@sha256:{expected_hash}"
    assert actual.append_receipt.ref == (
        f"event-append-receipt@sha256:{actual.append_receipt.sha256}"
    )
    assert actual.event_frontier.ref.endswith(f"@sha256:{actual.event_frontier.sha256}")


def _inspect_without_effect(
    root: Path,
    *,
    cache_dir: Path,
    transaction_root: Path,
    task_id: str | None = None,
    expected_publication_id: str | None = None,
    expected_disposition: str | None = None,
) -> tuple[ClaimPublicationInspection, ...]:
    before = _tree_snapshot(root)
    results = inspect_claim_publications(
        cache_dir=cache_dir,
        transaction_root=transaction_root,
        task_id=task_id,
        expected_publication_id=expected_publication_id,
        expected_disposition=expected_disposition,  # type: ignore[arg-type]
    )
    assert _tree_snapshot(root) == before
    return results


def test_intent_requires_explicit_claimable_true(tmp_path: Path) -> None:
    with pytest.raises(ClaimPublicationError) as raised:
        _fixture(tmp_path, claimable=False)

    assert raised.value.reason_code == "claim_publication_task_not_claimable"


def test_claim_and_resume_intents_bind_exact_preimages(tmp_path: Path) -> None:
    claim = _fixture(tmp_path / "claim")
    resume = _fixture(tmp_path / "resume", resume=True)

    assert claim.intent.claim_mode == "claim"
    assert claim.intent.from_status == "offered"
    assert claim.intent.to_status == "claimed"
    assert resume.intent.claim_mode == "resume"
    assert resume.intent.from_status == resume.intent.to_status == "pr_open"
    assert claim.intent.intent_ref == (
        f"claim-publication-intent@sha256:{claim.intent.intent_sha256}"
    )
    assert prospective_claim_publication_basis(claim.intent).claim_publication_intent == (
        ContentAddress(
            ref=claim.intent.intent_ref,
            sha256=claim.intent.intent_sha256,
        )
    )


def _write_recovery_receipt(root: Path) -> Path:
    """A producer-directory receipt using the existing platform receipt contract."""
    root.mkdir(parents=True, exist_ok=True)
    observed = datetime.now(UTC).isoformat()
    surface = {
        "status": "observed",
        "source": "scripts/hapax-platform-capability-receipts",
        "observed_at": observed,
        "stale_after": "1h",
        "evidence_refs": ["fixture:codex-saved-login-observed"],
        "reason_codes": [],
    }
    receipt = {
        "receipt_schema": 1,
        "receipt_id": "codex-recovery-fixture",
        "platform": "codex",
        "routes": ["codex.headless.full"],
        "observed_at": observed,
        "stale_after": "1h",
        "cli": {"binary": "codex", "available": True, "version": "fixture"},
        "wrapper": {"path": "/fixture/hapax-codex", "exists": True, "executable": True},
        "capability": surface,
        "resource": surface,
        "quota": surface,
        "provider_docs": {
            "refs": ["fixture:provider-docs"],
            "fetched_at": observed,
            "stale_after": "1h",
        },
    }
    path = root / "codex.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    return path


def _blocked_recovery_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ClaimFixture:
    vault = tmp_path / "vault"
    active = vault / "active"
    cache = tmp_path / "cache"
    active.mkdir(parents=True, exist_ok=True)
    (vault / "closed").mkdir(exist_ok=True)
    cache.mkdir(exist_ok=True)
    witness = _write_recovery_receipt(tmp_path / "platform-capability-receipts")
    monkeypatch.setenv("HAPAX_PLATFORM_CAPABILITY_RECEIPT_DIR", str(witness.parent))
    before = f"""---
task_id: task-alpha
status: blocked
assigned_to: cx-red
claimed_at: 2026-09-29T21:38:00Z
updated_at: 2026-09-29T21:40:00Z
authority_case: CASE-CLAIM-001
parent_spec: spec://claim
claimable: true
blocked_reason: codex_platform_capability_receipt_invalid
blocked_witness:
  kind: receipt_fresh
  ref: {witness}
  recovery: claimant_scoped_cc_claim
  resolves_blocked_reason: codex_platform_capability_receipt_invalid
depends_on: []
---
# Claim task

Body remains exact.
""".encode()
    note_path = active / "task-alpha.md"
    note_path.write_bytes(before)
    task = resolve_task_note(vault, "task-alpha", require_no_other_state=True)
    binding = ClaimDispatchBinding.create(
        task_id="task-alpha",
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
    after = before.replace(b"status: blocked", b"status: claimed") + (
        b"\n- 2026-09-29T21:45:00Z cx-red recovered blocked claim.\n"
    )
    intent = ClaimPublicationIntent.create(
        task=task,
        cache_dir=cache,
        note_after=after,
        binding=binding,
    )
    return ClaimFixture(
        intent=intent,
        vault=vault,
        cache=cache,
        transactions=tmp_path / "transactions",
        locks=tmp_path / "locks",
    )


def test_blocked_recovery_intent_binds_blocked_preimage_to_claimed_postimage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _blocked_recovery_fixture(tmp_path, monkeypatch)

    assert fixture.intent.claim_mode == "blocked_recovery"
    assert fixture.intent.from_status == "blocked"
    assert fixture.intent.to_status == "claimed"
    basis = prospective_claim_publication_basis(fixture.intent)
    assert basis.claim_mode == "blocked_recovery"
    assert basis.from_status == "blocked"
    assert basis.to_status == "claimed"


def _install_recovery_publisher(
    tmp_path: Path, fixture: ClaimFixture
) -> ClaimPublicationCompositionInstall:
    return install_claim_publication_composition(
        roots=ClaimPublicationCompositionRoots(
            invocation_store_root=str(tmp_path / "invocations"),
            claim_vault_root=str(fixture.vault),
            claim_cache_dir=str(fixture.cache),
            claim_transaction_root=str(fixture.transactions),
            claim_receipt_root=str(tmp_path / "receipts"),
            claim_lock_root=str(fixture.locks),
        ),
        installed_at=datetime.now(UTC),
        install_task_ref="claimed-blocked-row-recovery-20260929-test",
    )


def test_blocked_recovery_publication_refuses_receipt_invalidated_after_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _blocked_recovery_fixture(tmp_path, monkeypatch)
    install = _install_recovery_publisher(tmp_path, fixture)
    (tmp_path / "platform-capability-receipts/codex.json").write_text("{}")
    before = (_tree_snapshot(fixture.vault), _tree_snapshot(fixture.cache))

    with pytest.raises(ClaimPublicationError) as raised:
        publish_gate0b_claim(fixture.intent, root=install.root, now=datetime.now(UTC))

    assert raised.value.reason_code == "blocked_recovery_witness_refuse"
    assert (_tree_snapshot(fixture.vault), _tree_snapshot(fixture.cache)) == before
    assert not list((tmp_path / "receipts").rglob("*.json"))
    assert not list(fixture.transactions.rglob("manifest.json"))


def test_blocked_recovery_publishes_admitted_claim_with_durable_readback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _blocked_recovery_fixture(tmp_path, monkeypatch)
    install = _install_recovery_publisher(tmp_path, fixture)
    before = resolve_task_note(fixture.vault, fixture.intent.task_id).frontmatter

    receipt = publish_gate0b_claim(fixture.intent, root=install.root, now=datetime.now(UTC))

    assert fixture.intent.note_path.read_bytes() == fixture.intent.note_after
    assert receipt.schema == ADMITTED_CLAIM_PUBLICATION_RECEIPT_SCHEMA
    assert receipt.admission_consumption is not None
    assert receipt.execution_admission is not None
    assert receipt.execution_lease is not None
    record = load_admitted_claim_publication_receipt(receipt.receipt_path)
    assert record["claim_mode"] == "blocked_recovery"
    assert record["from_status"] == "blocked"
    assert record["to_status"] == "claimed"
    assert record["receipt_hash"] == receipt.receipt_hash
    assert record["binding_receipt_hash"] == fixture.intent.binding.receipt_hash
    assert (
        record["claim_note_postimage_sha256"]
        == hashlib.sha256(fixture.intent.note_after).hexdigest()
    )
    manifest = json.loads(receipt.manifest_path.read_text())
    assert manifest["state"] == "applied"
    assert manifest["publication_id"] == receipt.publication_id

    # Resolve from durable receipt, journal, note and role/session sidecars, rather
    # than treating the publisher's return value as proof that recovery happened.
    snapshot_before_readback = _tree_snapshot(tmp_path)
    applied = resolve_applied_claim_publication(
        vault_root=fixture.vault,
        cache_dir=fixture.cache,
        role=fixture.intent.role,
        session_id=fixture.intent.session_id,
        task_id=fixture.intent.task_id,
        transaction_root=fixture.transactions,
        receipt_root=tmp_path / "receipts",
        lock_root=fixture.locks,
    )
    assert applied.receipt.receipt_hash == receipt.receipt_hash
    assert applied.intent == fixture.intent
    assert applied.admission_consumption is not None
    assert applied.current_task.content == fixture.intent.note_after
    assert applied.current_task.frontmatter["status"] == "claimed"
    assert applied.current_task.frontmatter["assigned_to"] == fixture.intent.role
    for field in ("claimed_at", "blocked_reason", "blocked_witness"):
        assert applied.current_task.frontmatter[field] == before[field]
    assert _tree_snapshot(tmp_path) == snapshot_before_readback


def test_blocked_recovery_preflight_refuses_source_change_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _blocked_recovery_fixture(tmp_path, monkeypatch)
    changed = fixture.intent.note_before.replace(
        b"codex_platform_capability_receipt_invalid",
        b"another_blocker",
        1,
    )

    with pytest.raises(TaskStoreError) as raised:
        sdlc_claim.prepare_claim_publication_intent(
            note_path=fixture.intent.note_path,
            note_before=changed,
            note_after=fixture.intent.note_after,
            cache_dir=fixture.cache,
            binding=fixture.intent.binding,
        )

    assert raised.value.reason_code == "claim_publication_task_changed_during_preflight"


def test_publish_claim_is_gate0a_hold_without_mutation(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    before = _tree_snapshot(tmp_path)
    called = False

    def failure_hook(_phase: str, _index: int | None) -> None:
        nonlocal called
        called = True

    with pytest.raises(ClaimPublicationError) as raised:
        publish_claim(
            fixture.intent,
            transaction_root=fixture.transactions,
            lock_root=fixture.locks,
            failure_hook=failure_hook,
        )

    assert raised.value.reason_code == "unadmitted_claim_publication_forbidden"
    assert not called
    assert _tree_snapshot(tmp_path) == before


@pytest.mark.parametrize(
    ("damage", "verdict", "reason_code"),
    [
        ("path_exists", "refuse", "blocked_recovery_witness_unbound"),
        ("unrelated_fresh_yaml", "refuse", "blocked_recovery_witness_refuse"),
        ("outside_producer_root", "refuse", "blocked_recovery_witness_refuse"),
        ("invalid_sibling", "refuse", "blocked_recovery_witness_refuse"),
        ("wrong_platform", "refuse", "blocked_recovery_witness_refuse"),
        ("wrong_route", "refuse", "blocked_recovery_witness_refuse"),
        ("stale_receipt", "unsatisfied", "blocked_recovery_witness_unsatisfied"),
        ("future_receipt", "unsatisfied", "blocked_recovery_witness_unsatisfied"),
        ("stale_surface", "unsatisfied", "blocked_recovery_witness_unsatisfied"),
        ("blocked_surface", "unsatisfied", "blocked_recovery_witness_unsatisfied"),
        ("superseded_receipt", "unsatisfied", "blocked_recovery_witness_unsatisfied"),
        ("unknown_reason", "refuse", "blocked_recovery_reason_unsupported"),
        ("reason_mismatch", "refuse", "blocked_recovery_reason_mismatch"),
    ],
)
def test_blocked_recovery_checks_original_receipt_predicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    damage: str,
    verdict: str,
    reason_code: str,
) -> None:
    from shared.blocked_witness import evaluate_claimant_blocked_recovery

    fixture = _blocked_recovery_fixture(tmp_path, monkeypatch)
    fields = sdlc_claim.blocked_recovery_fields(fixture.intent.note_before)
    receipt = tmp_path / "platform-capability-receipts/codex.json"
    payload = json.loads(receipt.read_text())
    witness = fields["blocked_witness"]
    assert isinstance(witness, dict)
    if damage == "path_exists":
        witness["kind"] = "path_exists"
    elif damage == "unrelated_fresh_yaml":
        payload = {"observed_at": datetime.now(UTC).isoformat(), "stale_after_seconds": 3600}
    elif damage == "outside_producer_root":
        outside = tmp_path / "unrelated.json"
        outside.write_text(json.dumps(payload))
        witness["ref"] = str(outside)
    elif damage == "invalid_sibling":
        (receipt.parent / "invalid.json").write_text("{}")
    elif damage == "wrong_platform":
        payload["platform"] = "claude"
    elif damage == "wrong_route":
        payload["routes"] = ["codex.headless.spark"]
    elif damage == "stale_receipt":
        payload["observed_at"] = "2000-01-01T00:00:00Z"
    elif damage == "future_receipt":
        payload["observed_at"] = (datetime.now(UTC) + timedelta(seconds=30)).isoformat()
    elif damage == "stale_surface":
        payload["capability"]["observed_at"] = "2000-01-01T00:00:00Z"
    elif damage == "blocked_surface":
        payload["capability"].update(status="blocked", reason_codes=["codex_exec_auth_failed"])
    elif damage == "superseded_receipt":
        newer = dict(payload, receipt_id="newer", observed_at=datetime.now(UTC).isoformat())
        (receipt.parent / "newer.json").write_text(json.dumps(newer))
    elif damage == "unknown_reason":
        fields["blocked_reason"] = witness["resolves_blocked_reason"] = "unrecognized_predicate"
    elif damage == "reason_mismatch":
        witness["resolves_blocked_reason"] = "different_predicate"
    receipt.write_text(json.dumps(payload))

    before = _tree_snapshot(tmp_path)
    result = evaluate_claimant_blocked_recovery(fields)

    assert result.verdict == verdict
    assert result.reason_code == reason_code
    assert _tree_snapshot(tmp_path) == before


def test_blocked_recovery_rechecks_receipt_under_publication_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    fixture = _blocked_recovery_fixture(tmp_path, monkeypatch)
    projections = sdlc_claim._projections(fixture.intent)
    (tmp_path / "platform-capability-receipts/codex.json").write_text("{}")
    before = _tree_snapshot(tmp_path)

    with pytest.raises(ClaimPublicationError, match="blocked_recovery_witness_refuse"):
        sdlc_claim._locked_preflight(fixture.intent, projections, deadline_at=time.monotonic() + 10)

    assert _tree_snapshot(tmp_path) == before


@pytest.mark.parametrize("field", ["claimed_at", "blocked_reason", "blocked_witness"])
def test_blocked_recovery_postimage_preserves_original_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    fixture = _blocked_recovery_fixture(tmp_path, monkeypatch)
    after = fixture.intent.note_after
    if field == "claimed_at":
        after = after.replace(
            b"claimed_at: 2026-09-29T21:38:00Z", b"claimed_at: 2026-09-30T00:00:00Z"
        )
    elif field == "blocked_reason":
        after = after.replace(
            b"blocked_reason: codex_platform_capability_receipt_invalid", b"blocked_reason: null", 1
        )
    else:
        after = after.replace(b"  recovery: claimant_scoped_cc_claim", b"  recovery: changed")
    before = _tree_snapshot(tmp_path)

    with pytest.raises(ClaimPublicationError, match="blocked_recovery_evidence_changed"):
        ClaimPublicationIntent.create(
            task=resolve_task_note(fixture.vault, fixture.intent.task_id),
            cache_dir=fixture.cache,
            note_after=after,
            binding=fixture.intent.binding,
        )

    assert _tree_snapshot(tmp_path) == before


def test_publish_admitted_claim_is_gate0a_hold_without_mutation(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)
    before = _tree_snapshot(tmp_path)
    called = False

    def failure_hook(_phase: str, _index: int | None) -> None:
        nonlocal called
        called = True

    with pytest.raises(ClaimPublicationError) as raised:
        publish_admitted_claim(
            fixture.intent,
            active.consumption,
            transaction_root=fixture.transactions,
            lock_root=fixture.locks,
            now=active.checked_at,
            failure_hook=failure_hook,
        )

    assert raised.value.reason_code == "claim_publication_effect_activation_unvalidated"
    assert not called
    assert _tree_snapshot(tmp_path) == before


def test_private_admitted_transaction_applies_live_projections_only(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)
    receipt_root = tmp_path / "receipts"
    proof_before = _file_identity_snapshot(active.proof_paths)

    receipt = sdlc_claim._apply_admitted_claim_publication_transaction(
        fixture.intent,
        active.consumption,
        transaction_root=fixture.transactions,
        receipt_root=receipt_root,
        lock_root=fixture.locks,
        now=active.checked_at,
    )

    projections = sdlc_claim._admitted_projections(fixture.intent, active.consumption)
    publication_id = admitted_claim_publication_id(fixture.intent, active.consumption)
    manifest_path = fixture.transactions / publication_id / "manifest.json"
    receipt_path = claim_publication_receipt_path(
        fixture.cache,
        fixture.intent.binding,
        receipt_root=receipt_root,
    )
    loaded_intent, loaded_projections, loaded_id, state, loaded_consumption = (
        sdlc_claim._load_admitted_manifest(manifest_path)
    )
    receipt_record = load_admitted_claim_publication_receipt(receipt_path)

    assert receipt.schema == ADMITTED_CLAIM_PUBLICATION_RECEIPT_SCHEMA
    assert receipt.receipt_path == receipt_path
    assert receipt_record["schema"] == ADMITTED_CLAIM_PUBLICATION_RECEIPT_SCHEMA
    assert loaded_intent == fixture.intent
    assert loaded_consumption == active.consumption
    assert loaded_projections == projections
    assert loaded_id == publication_id
    assert state == "applied"
    assert len(loaded_projections) == 12
    assert stat.S_IMODE(manifest_path.stat(follow_symlinks=False).st_mode) == 0o600
    assert stat.S_IMODE(receipt_path.stat(follow_symlinks=False).st_mode) == 0o600
    for projection in projections[:7]:
        assert projection.path.read_bytes() == projection.after
        assert projection.after_mode is not None
        assert stat.S_IMODE(projection.path.stat(follow_symlinks=False).st_mode) == (
            projection.after_mode
        )
    assert _file_identity_snapshot(active.proof_paths) == proof_before

    required = require_applied_admitted_claim_publication(
        fixture.intent,
        active.consumption,
        transaction_root=fixture.transactions,
        receipt_root=receipt_root,
        lock_root=fixture.locks,
    )
    again = sdlc_claim._apply_admitted_claim_publication_transaction(
        fixture.intent,
        active.consumption,
        transaction_root=fixture.transactions,
        receipt_root=receipt_root,
        lock_root=fixture.locks,
        now=active.checked_at,
    )
    inspections = inspect_claim_publications(
        cache_dir=fixture.cache,
        transaction_root=fixture.transactions,
        receipt_root=receipt_root,
        task_id=fixture.intent.task_id,
        expected_publication_id=publication_id,
        expected_disposition="terminal_applied",
    )

    assert required.receipt_hash == receipt.receipt_hash
    assert again.receipt_hash == receipt.receipt_hash
    assert inspections[0].disposition == "terminal_applied"
    assert inspections[0].reason_code is None


def test_private_admitted_transaction_refuses_proof_drift_before_live_writes(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)
    active.proof_paths[0].write_bytes(b"{}\n")

    with pytest.raises(ClaimPublicationError) as raised:
        sdlc_claim._apply_admitted_claim_publication_transaction(
            fixture.intent,
            active.consumption,
            transaction_root=fixture.transactions,
            receipt_root=tmp_path / "receipts",
            lock_root=fixture.locks,
            now=active.checked_at,
        )

    assert raised.value.reason_code == "claim_publication_preimage_changed"
    assert (
        fixture.vault / "active" / f"{fixture.intent.task_id}.md"
    ).read_bytes() == fixture.intent.note_before
    assert not fixture.transactions.exists()


def test_private_admitted_transaction_marks_recovery_after_projection_failure(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)
    receipt_root = tmp_path / "receipts"

    def failure_hook(phase: str, index: int | None) -> None:
        if phase == "after_projection" and index == 0:
            raise ClaimPublicationError(
                "claim_publication_projection_simulated",
                "run admitted recovery in the test harness",
                fixture.intent.task_id,
            )

    with pytest.raises(ClaimPublicationError) as raised:
        sdlc_claim._apply_admitted_claim_publication_transaction(
            fixture.intent,
            active.consumption,
            transaction_root=fixture.transactions,
            receipt_root=receipt_root,
            lock_root=fixture.locks,
            now=active.checked_at,
            failure_hook=failure_hook,
        )

    publication_id = admitted_claim_publication_id(fixture.intent, active.consumption)
    manifest_path = fixture.transactions / publication_id / "manifest.json"
    _loaded_intent, _loaded_projections, _loaded_id, state, _loaded_consumption = (
        sdlc_claim._load_admitted_manifest(manifest_path)
    )
    inspections = inspect_claim_publications(
        cache_dir=fixture.cache,
        transaction_root=fixture.transactions,
        receipt_root=receipt_root,
        task_id=fixture.intent.task_id,
        expected_publication_id=publication_id,
    )

    assert raised.value.reason_code == "claim_publication_projection_simulated"
    assert state == "recovery_required"
    assert json.loads(manifest_path.read_text(encoding="ascii"))["reason_code"] == (
        "claim_publication_projection_simulated"
    )
    assert not claim_publication_receipt_path(
        fixture.cache,
        fixture.intent.binding,
        receipt_root=receipt_root,
    ).exists()
    assert inspections[0].disposition == "hold"
    assert inspections[0].reason_code == "admitted_claim_publication_reconciliation_required"
    results = recover_claim_publications(
        cache_dir=fixture.cache,
        transaction_root=fixture.transactions,
        receipt_root=receipt_root,
        lock_root=fixture.locks,
        task_id=fixture.intent.task_id,
    )
    (
        recovered_intent,
        recovered_projections,
        recovered_id,
        recovered_state,
        recovered_consumption,
    ) = sdlc_claim._load_admitted_manifest(manifest_path)
    recovered_receipt = require_applied_admitted_claim_publication(
        fixture.intent,
        active.consumption,
        transaction_root=fixture.transactions,
        receipt_root=receipt_root,
        lock_root=fixture.locks,
    )

    assert results == (sdlc_claim.ClaimPublicationRecoveryResult(publication_id, "applied"),)
    assert recovered_intent == fixture.intent
    assert recovered_consumption == active.consumption
    assert recovered_projections == sdlc_claim._admitted_projections(
        fixture.intent, active.consumption
    )
    assert recovered_id == publication_id
    assert recovered_state == "applied"
    assert recovered_receipt.recovered is False


def test_pre_receipt_projection_failure_does_not_publish_claim_cache(
    tmp_path: Path,
) -> None:
    fixture = _home_fixture(tmp_path, task_id="pre-receipt-claim", resume=True)
    active = _active_admission_fixture(tmp_path, fixture)
    receipt_root = fixture.cache / "claim-publication-receipts"

    def failure_hook(phase: str, index: int | None) -> None:
        if phase == "after_projection" and index == 0:
            raise ClaimPublicationError(
                "claim_publication_pre_receipt_simulated",
                "run admitted recovery in the test harness",
                fixture.intent.task_id,
            )

    with pytest.raises(ClaimPublicationError) as raised:
        sdlc_claim._apply_admitted_claim_publication_transaction(
            fixture.intent,
            active.consumption,
            transaction_root=fixture.transactions,
            receipt_root=receipt_root,
            lock_root=fixture.locks,
            now=active.checked_at,
            failure_hook=failure_hook,
        )

    receipt_path = claim_publication_receipt_path(
        fixture.cache,
        fixture.intent.binding,
        receipt_root=receipt_root,
    )
    role_claim = fixture.cache / "cc-active-task-cx-red"
    session_claim = fixture.cache / "cc-active-task-cx-red-session-abc"

    assert raised.value.reason_code == "claim_publication_pre_receipt_simulated"
    assert not receipt_path.exists()
    assert not role_claim.exists()
    assert not session_claim.exists()

    repo_root = Path(__file__).resolve().parents[2]
    gate_env = os.environ.copy()
    for key in (
        "HAPAX_AGENT_NAME",
        "CODEX_THREAD_NAME",
        "CODEX_SESSION_NAME",
        "CODEX_SESSION",
        "CODEX_ROLE",
        "CLAUDE_ROLE",
        "CLAUDE_CODE_SESSION_ID",
        "HAPAX_SESSION_ID",
    ):
        gate_env.pop(key, None)
    gate_env.update(
        {
            "HOME": str(tmp_path / "home"),
            "HAPAX_AGENT_ROLE": "cx-red",
            "HAPAX_AGENT_NAME": "cx-red",
            "HAPAX_SESSION_ID": "session-abc",
        }
    )
    gated = subprocess.run(
        ["bash", str(repo_root / "hooks" / "scripts" / "cc-task-gate.impl.sh")],
        input=json.dumps(
            {
                "tool_name": "Write",
                "tool_input": {
                    "file_path": str(repo_root / "shared" / "sdlc_claim.py"),
                },
            }
        ),
        env=gate_env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert gated.returncode == 2
    assert "no claimed task" in gated.stderr

    results = recover_claim_publications(
        cache_dir=fixture.cache,
        transaction_root=fixture.transactions,
        receipt_root=receipt_root,
        lock_root=fixture.locks,
        task_id=fixture.intent.task_id,
    )

    assert results == (
        sdlc_claim.ClaimPublicationRecoveryResult(
            admitted_claim_publication_id(fixture.intent, active.consumption),
            "applied",
        ),
    )
    assert receipt_path.exists()
    assert role_claim.read_text(encoding="utf-8") == "pre-receipt-claim\n"
    assert session_claim.read_text(encoding="utf-8") == "pre-receipt-claim\n"


def test_admitted_transaction_persists_receipt_before_activation_phase(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _home_fixture(tmp_path, task_id="receipt-before-activation", resume=True)
    active = _active_admission_fixture(tmp_path, fixture)
    receipt_root = fixture.cache / "claim-publication-receipts"
    events: list[str] = []
    projections = sdlc_claim._admitted_projections(fixture.intent, active.consumption)
    plan = sdlc_claim._receipt_before_activation_projection_plan(projections[:7])

    assert all(
        not item.projection.path.name.startswith("cc-active-task-") for item in plan.pre_receipt
    )
    assert {item.projection.path.name for item in plan.activation} == {
        "cc-active-task-cx-red",
        "cc-active-task-cx-red-session-abc",
    }

    original_persist_receipt = sdlc_claim._persist_admitted_receipt

    def recording_persist_receipt(*args: object, **kwargs: object) -> None:
        events.append("receipt_persist")
        original_persist_receipt(*args, **kwargs)

    def recording_failure_hook(phase: str, index: int | None) -> None:
        del index
        if phase in {"after_projection", "after_activation_projection"}:
            events.append(phase)

    monkeypatch.setattr(sdlc_claim, "_persist_admitted_receipt", recording_persist_receipt)

    receipt = sdlc_claim._apply_admitted_claim_publication_transaction(
        fixture.intent,
        active.consumption,
        transaction_root=fixture.transactions,
        receipt_root=receipt_root,
        lock_root=fixture.locks,
        now=active.checked_at,
        failure_hook=recording_failure_hook,
    )

    receipt_index = events.index("receipt_persist")
    assert "after_projection" in events[:receipt_index]
    assert "after_activation_projection" not in events[:receipt_index]
    assert events[receipt_index + 1 :] == [
        "after_activation_projection",
        "after_activation_projection",
    ]
    assert receipt.receipt_path.exists()
    assert (fixture.cache / "cc-active-task-cx-red").read_text(encoding="utf-8") == (
        "receipt-before-activation\n"
    )
    assert (fixture.cache / "cc-active-task-cx-red-session-abc").read_text(
        encoding="utf-8"
    ) == "receipt-before-activation\n"


def test_activation_failure_hook_names_unexpected_phases_as_claim_activation_context() -> None:
    observed: list[tuple[str, int | None]] = []
    hook = sdlc_claim._activation_failure_hook(lambda phase, index: observed.append((phase, index)))
    assert hook is not None

    hook("scratch_finalize", 3)

    assert observed == [("claim_activation_projection_scratch_finalize", 3)]


def test_active_claim_cache_is_not_published_before_receipt(
    tmp_path: Path,
) -> None:
    fixture = _home_fixture(tmp_path, task_id="receipt-bound-claim", resume=True)
    active = _active_admission_fixture(tmp_path, fixture)
    receipt_root = fixture.cache / "claim-publication-receipts"

    def failure_hook(phase: str, index: int | None) -> None:
        if phase == "after_activation_projection" and index == 0:
            raise ClaimPublicationError(
                "claim_publication_activation_simulated",
                "run admitted recovery in the test harness",
                fixture.intent.task_id,
            )

    with pytest.raises(ClaimPublicationError) as raised:
        sdlc_claim._apply_admitted_claim_publication_transaction(
            fixture.intent,
            active.consumption,
            transaction_root=fixture.transactions,
            receipt_root=receipt_root,
            lock_root=fixture.locks,
            now=active.checked_at,
            failure_hook=failure_hook,
        )

    assert raised.value.reason_code == "claim_publication_activation_simulated"
    receipt_path = claim_publication_receipt_path(
        fixture.cache,
        fixture.intent.binding,
        receipt_root=receipt_root,
    )
    role_claim = fixture.cache / "cc-active-task-cx-red"
    session_claim = fixture.cache / "cc-active-task-cx-red-session-abc"
    assert receipt_path.exists()
    assert role_claim.read_text(encoding="utf-8") == "receipt-bound-claim\n"
    assert not session_claim.exists()

    repo_root = Path(__file__).resolve().parents[2]
    gate_env = os.environ.copy()
    for key in (
        "HAPAX_AGENT_NAME",
        "CODEX_THREAD_NAME",
        "CODEX_SESSION_NAME",
        "CODEX_SESSION",
        "CODEX_ROLE",
        "CLAUDE_ROLE",
        "CLAUDE_CODE_SESSION_ID",
        "HAPAX_SESSION_ID",
    ):
        gate_env.pop(key, None)
    gate_env.update(
        {
            "HOME": str(tmp_path / "home"),
            "HAPAX_AGENT_ROLE": "cx-red",
            "HAPAX_AGENT_NAME": "cx-red",
            "HAPAX_SESSION_ID": "session-abc",
        }
    )
    gated = subprocess.run(
        ["bash", str(repo_root / "hooks" / "scripts" / "cc-task-gate.impl.sh")],
        input=json.dumps(
            {
                "tool_name": "Write",
                "tool_input": {
                    "file_path": str(repo_root / "shared" / "sdlc_claim.py"),
                },
            }
        ),
        env=gate_env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert gated.returncode == 0, gated.stderr
    assert "status: pr_open" in (
        fixture.vault / "active" / f"{fixture.intent.task_id}.md"
    ).read_text(encoding="utf-8")

    results = recover_claim_publications(
        cache_dir=fixture.cache,
        transaction_root=fixture.transactions,
        receipt_root=receipt_root,
        lock_root=fixture.locks,
        task_id=fixture.intent.task_id,
    )

    assert results == (
        sdlc_claim.ClaimPublicationRecoveryResult(
            admitted_claim_publication_id(fixture.intent, active.consumption),
            "applied",
        ),
    )
    assert session_claim.read_text(encoding="utf-8") == "receipt-bound-claim\n"


def test_private_admitted_transaction_refuses_receipt_collision_without_live_writes(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)
    receipt_root = tmp_path / "receipts"
    receipt_path = claim_publication_receipt_path(
        fixture.cache,
        fixture.intent.binding,
        receipt_root=receipt_root,
    )
    _write_history_file(receipt_path, b"{}\n")

    with pytest.raises(ClaimPublicationError) as raised:
        sdlc_claim._apply_admitted_claim_publication_transaction(
            fixture.intent,
            active.consumption,
            transaction_root=fixture.transactions,
            receipt_root=receipt_root,
            lock_root=fixture.locks,
            now=active.checked_at,
        )

    assert raised.value.reason_code == "claim_publication_existing_history_not_terminal"
    assert (
        fixture.vault / "active" / f"{fixture.intent.task_id}.md"
    ).read_bytes() == fixture.intent.note_before
    assert not fixture.transactions.exists()


def test_private_admitted_transaction_holds_existing_journal_without_live_writes(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)
    receipt_root = tmp_path / "receipts"
    publication_id = admitted_claim_publication_id(fixture.intent, active.consumption)
    (fixture.transactions / publication_id).mkdir(parents=True, mode=0o700)
    fixture.transactions.chmod(0o700)

    with pytest.raises(ClaimPublicationError) as raised:
        sdlc_claim._apply_admitted_claim_publication_transaction(
            fixture.intent,
            active.consumption,
            transaction_root=fixture.transactions,
            receipt_root=receipt_root,
            lock_root=fixture.locks,
            now=active.checked_at,
        )

    assert raised.value.reason_code == "claim_publication_existing_history_not_terminal"
    assert "run admitted recovery" in str(raised.value)
    assert (
        fixture.vault / "active" / f"{fixture.intent.task_id}.md"
    ).read_bytes() == fixture.intent.note_before
    assert not claim_publication_receipt_path(
        fixture.cache,
        fixture.intent.binding,
        receipt_root=receipt_root,
    ).exists()


def test_claim_transaction_directory_refuses_collision_and_unsafe_root(
    tmp_path: Path,
) -> None:
    root = tmp_path / "transactions"
    publication_id = f"claim-pub-{'a' * 64}"
    (root / publication_id).mkdir(parents=True, mode=0o700)
    root.chmod(0o700)

    with pytest.raises(ClaimPublicationError) as collision:
        sdlc_claim._create_claim_transaction_directory(root, publication_id)
    assert collision.value.reason_code == "claim_publication_transaction_collision"

    unsafe_root = tmp_path / "transactions-file"
    unsafe_root.write_text("not a directory", encoding="utf-8")
    with pytest.raises(ClaimPublicationError) as unsafe:
        sdlc_claim._create_claim_transaction_directory(unsafe_root, publication_id)
    assert unsafe.value.reason_code == "claim_publication_private_directory_unsafe"


def test_claim_transaction_directory_reports_mkdir_and_stat_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "transactions"
    root.mkdir(mode=0o700)
    publication_id = f"claim-pub-{'b' * 64}"
    target = root / publication_id
    original_mkdir = sdlc_claim.os.mkdir

    def fail_target_mkdir(path: str | bytes | os.PathLike[str], mode: int = 0o777) -> None:
        if Path(path) == target:
            raise OSError("simulated full transaction filesystem")
        original_mkdir(path, mode)

    monkeypatch.setattr(sdlc_claim.os, "mkdir", fail_target_mkdir)
    with pytest.raises(ClaimPublicationError) as unavailable:
        sdlc_claim._create_claim_transaction_directory(root, publication_id)
    assert unavailable.value.reason_code == "claim_publication_transaction_directory_unavailable"

    monkeypatch.setattr(sdlc_claim.os, "mkdir", original_mkdir)
    original_stat = Path.stat

    def fail_target_stat(self: Path, *args: object, **kwargs: object) -> os.stat_result:
        if self == target:
            raise OSError("simulated post-create stat failure")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fail_target_stat)
    with pytest.raises(ClaimPublicationError) as unsafe:
        sdlc_claim._create_claim_transaction_directory(root, publication_id)
    assert unsafe.value.reason_code == "claim_publication_transaction_directory_unsafe"


def test_claim_private_payload_covers_temp_exhaustion_and_readback_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    target = root / "manifest.json"
    scratch = root / ".manifest.json.fixed.claim-tmp"
    scratch.write_bytes(b"collision\n")
    scratch.chmod(0o600)
    monkeypatch.setattr(sdlc_claim.secrets, "token_hex", lambda _size: "fixed")

    with pytest.raises(ClaimPublicationError) as exhausted:
        sdlc_claim._claim_private_payload(target, b"payload\n", overwrite=True)
    assert exhausted.value.reason_code == "claim_publication_private_file_temp_exhausted"

    monkeypatch.setattr(
        sdlc_claim,
        "_strict_file",
        lambda _path, *, reason_code: (b"wrong\n", 0o600),
    )
    with pytest.raises(ClaimPublicationError) as mismatch:
        sdlc_claim._claim_private_payload(root / "readback.json", b"payload\n", overwrite=False)
    assert mismatch.value.reason_code == "claim_publication_private_file_readback_mismatch"


def test_claim_private_payload_covers_replace_and_open_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    target = root / "manifest.json"
    target.write_bytes(b"old\n")
    target.chmod(0o600)
    original_replace = sdlc_claim.os.replace

    def fail_target_replace(src: Path, dst: Path) -> None:
        if Path(dst) == target:
            raise OSError("simulated manifest replace failure")
        original_replace(src, dst)

    monkeypatch.setattr(sdlc_claim.os, "replace", fail_target_replace)
    with pytest.raises(ClaimPublicationError) as install_failed:
        sdlc_claim._claim_private_payload(target, b"new\n", overwrite=True)
    assert install_failed.value.reason_code == "claim_publication_private_file_install_failed"

    monkeypatch.setattr(sdlc_claim.os, "replace", original_replace)
    original_open = sdlc_claim.os.open

    def fail_target_open(
        path: str | bytes | os.PathLike[str],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if Path(path) == root / "blocked.json":
            raise OSError("simulated private file open failure")
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(sdlc_claim.os, "open", fail_target_open)
    with pytest.raises(ClaimPublicationError) as unsafe:
        sdlc_claim._claim_private_payload(root / "blocked.json", b"payload\n", overwrite=False)
    assert unsafe.value.reason_code == "claim_publication_private_file_unsafe"


def test_claim_publication_lock_refuses_hardlinked_lock_file(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    fixture.locks.mkdir(mode=0o700)
    digest = sdlc_claim._claim_publication_role_lock_digest(fixture.intent.role)
    lock_path = fixture.locks / f"{digest}.lock"
    lock_path.write_bytes(b"")
    lock_path.chmod(0o600)
    os.link(lock_path, fixture.locks / "extra-hardlink.lock")

    with pytest.raises(ClaimPublicationError) as raised:
        with sdlc_claim._claim_publication_lock(fixture.intent, lock_root=fixture.locks):
            pass

    assert raised.value.reason_code == "claim_publication_lock_unsafe"


def test_claim_publication_lock_reports_open_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    fixture.locks.mkdir(mode=0o700)
    original_open = sdlc_claim.os.open

    def fail_lock_open(
        path: str | bytes | os.PathLike[str],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if Path(path).name.endswith(".lock"):
            raise OSError("simulated lock open failure")
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(sdlc_claim.os, "open", fail_lock_open)
    with pytest.raises(ClaimPublicationError) as raised:
        with sdlc_claim._claim_publication_lock(fixture.intent, lock_root=fixture.locks):
            pass

    assert raised.value.reason_code == "claim_publication_lock_unavailable"


def _claim_publication_lock_child(
    intent: ClaimPublicationIntent,
    lock_root: Path,
    acquired: mp.Queue,
) -> None:
    with sdlc_claim._claim_publication_lock(intent, lock_root=lock_root):
        acquired.put("acquired")


def test_claim_publication_lock_serializes_contending_process(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    ctx = mp.get_context("fork")
    acquired = ctx.Queue()
    process = ctx.Process(
        target=_claim_publication_lock_child,
        args=(fixture.intent, fixture.locks, acquired),
    )

    with sdlc_claim._claim_publication_lock(fixture.intent, lock_root=fixture.locks):
        process.start()
        with pytest.raises(queue.Empty):
            acquired.get(timeout=0.25)

    assert acquired.get(timeout=5) == "acquired"
    process.join(timeout=5)
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)
    assert process.exitcode == 0


def test_claim_publication_lock_serializes_different_tasks_for_same_role(
    tmp_path: Path,
) -> None:
    first = _fixture(tmp_path / "one", task_id="task-alpha")
    second = _fixture(tmp_path / "two", task_id="task-beta")
    assert first.intent.role == second.intent.role
    assert first.intent.task_id != second.intent.task_id
    ctx = mp.get_context("fork")
    acquired = ctx.Queue()
    process = ctx.Process(
        target=_claim_publication_lock_child,
        args=(second.intent, first.locks, acquired),
    )

    with sdlc_claim._claim_publication_lock(first.intent, lock_root=first.locks):
        process.start()
        with pytest.raises(queue.Empty):
            acquired.get(timeout=0.25)

    assert acquired.get(timeout=5) == "acquired"
    process.join(timeout=5)
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)
    assert process.exitcode == 0


def test_admitted_manifest_state_refuses_invalid_state(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)
    projections = sdlc_claim._admitted_projections(fixture.intent, active.consumption)
    publication_id = admitted_claim_publication_id(fixture.intent, active.consumption)

    with pytest.raises(ClaimPublicationError) as raised:
        sdlc_claim._admitted_manifest_bytes(
            fixture.intent,
            active.consumption,
            projections,
            publication_id,
            state="not-a-state",
        )

    assert raised.value.reason_code == "claim_publication_state_invalid"


def test_private_admitted_transaction_marks_recovery_after_untyped_exception(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)
    receipt_root = tmp_path / "receipts"

    def failure_hook(phase: str, index: int | None) -> None:
        if phase == "after_projection" and index == 0:
            raise RuntimeError("simulated projection crash")

    with pytest.raises(ClaimPublicationError) as raised:
        sdlc_claim._apply_admitted_claim_publication_transaction(
            fixture.intent,
            active.consumption,
            transaction_root=fixture.transactions,
            receipt_root=receipt_root,
            lock_root=fixture.locks,
            now=active.checked_at,
            failure_hook=failure_hook,
        )

    publication_id = admitted_claim_publication_id(fixture.intent, active.consumption)
    manifest_path = fixture.transactions / publication_id / "manifest.json"
    _loaded_intent, _loaded_projections, _loaded_id, state, _loaded_consumption = (
        sdlc_claim._load_admitted_manifest(manifest_path)
    )
    assert state == "recovery_required"
    assert raised.value.reason_code == "claim_publication_projection_failed"
    assert "run admitted recovery" in raised.value.repair_action
    assert json.loads(manifest_path.read_text(encoding="ascii"))["reason_code"] == (
        "claim_publication_projection_failed"
    )


def test_private_admitted_transaction_wraps_journal_update_failure_by_phase(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)
    receipt_root = tmp_path / "receipts"
    original_persist_state = sdlc_claim._persist_admitted_manifest_state

    def fail_postimage_state(*args: object, **kwargs: object) -> None:
        if kwargs.get("state") == "postimage_complete":
            raise RuntimeError("simulated journal write failure")
        original_persist_state(*args, **kwargs)

    monkeypatch.setattr(sdlc_claim, "_persist_admitted_manifest_state", fail_postimage_state)

    with pytest.raises(ClaimPublicationError) as raised:
        sdlc_claim._apply_admitted_claim_publication_transaction(
            fixture.intent,
            active.consumption,
            transaction_root=fixture.transactions,
            receipt_root=receipt_root,
            lock_root=fixture.locks,
            now=active.checked_at,
        )

    publication_id = admitted_claim_publication_id(fixture.intent, active.consumption)
    manifest_path = fixture.transactions / publication_id / "manifest.json"
    _intent, _projections, _loaded_id, state, _consumption = sdlc_claim._load_admitted_manifest(
        manifest_path
    )

    assert raised.value.reason_code == "claim_publication_journal_update_failed"
    assert "transaction root" in raised.value.repair_action
    assert state == "recovery_required"
    assert json.loads(manifest_path.read_text(encoding="ascii"))["reason_code"] == (
        "claim_publication_journal_update_failed"
    )


def test_private_admitted_transaction_wraps_receipt_failure_by_phase(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)
    receipt_root = tmp_path / "receipts"
    original_persist_receipt = sdlc_claim._persist_admitted_receipt

    def fail_receipt_raw(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated receipt sink failure")

    monkeypatch.setattr(sdlc_claim, "_persist_admitted_receipt", fail_receipt_raw)

    with pytest.raises(ClaimPublicationError) as raised:
        sdlc_claim._apply_admitted_claim_publication_transaction(
            fixture.intent,
            active.consumption,
            transaction_root=fixture.transactions,
            receipt_root=receipt_root,
            lock_root=fixture.locks,
            now=active.checked_at,
        )

    publication_id = admitted_claim_publication_id(fixture.intent, active.consumption)
    manifest_path = fixture.transactions / publication_id / "manifest.json"
    _intent, _projections, _loaded_id, state, _consumption = sdlc_claim._load_admitted_manifest(
        manifest_path
    )
    assert raised.value.reason_code == "claim_publication_receipt_persist_failed"
    assert "receipt root" in raised.value.repair_action
    assert state == "recovery_required"
    assert json.loads(manifest_path.read_text(encoding="ascii"))["reason_code"] == (
        "claim_publication_receipt_persist_failed"
    )

    monkeypatch.setattr(sdlc_claim, "_persist_admitted_receipt", original_persist_receipt)
    results = recover_claim_publications(
        cache_dir=fixture.cache,
        transaction_root=fixture.transactions,
        receipt_root=receipt_root,
        lock_root=fixture.locks,
        task_id=fixture.intent.task_id,
    )

    assert results == (sdlc_claim.ClaimPublicationRecoveryResult(publication_id, "applied"),)


def test_admitted_recovery_completes_postimage_without_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)
    receipt_root = tmp_path / "receipts"
    original_persist_receipt = sdlc_claim._persist_admitted_receipt

    def fail_receipt_once(*args: object, **kwargs: object) -> None:
        raise ClaimPublicationError(
            "claim_publication_receipt_simulated",
            "retry admitted recovery after the receipt sink is writable",
            fixture.intent.task_id,
        )

    monkeypatch.setattr(sdlc_claim, "_persist_admitted_receipt", fail_receipt_once)
    with pytest.raises(ClaimPublicationError) as raised:
        sdlc_claim._apply_admitted_claim_publication_transaction(
            fixture.intent,
            active.consumption,
            transaction_root=fixture.transactions,
            receipt_root=receipt_root,
            lock_root=fixture.locks,
            now=active.checked_at,
        )

    publication_id = admitted_claim_publication_id(fixture.intent, active.consumption)
    manifest_path = fixture.transactions / publication_id / "manifest.json"
    _intent, _projections, _loaded_id, state, _consumption = sdlc_claim._load_admitted_manifest(
        manifest_path
    )
    assert raised.value.reason_code == "claim_publication_receipt_simulated"
    assert state == "recovery_required"
    monkeypatch.setattr(sdlc_claim, "_persist_admitted_receipt", original_persist_receipt)

    results = recover_claim_publications(
        cache_dir=fixture.cache,
        transaction_root=fixture.transactions,
        receipt_root=receipt_root,
        lock_root=fixture.locks,
        task_id=fixture.intent.task_id,
    )
    _intent, _projections, _loaded_id, state, _consumption = sdlc_claim._load_admitted_manifest(
        manifest_path
    )
    receipt_path = claim_publication_receipt_path(
        fixture.cache,
        fixture.intent.binding,
        receipt_root=receipt_root,
    )

    assert results == (sdlc_claim.ClaimPublicationRecoveryResult(publication_id, "applied"),)
    assert state == "applied"
    assert load_admitted_claim_publication_receipt(receipt_path)["publication_id"] == publication_id


def test_recovery_holds_legacy_history_without_mutation(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    publication_id = _materialize_v1_history(fixture, state="created")
    before = _tree_snapshot(tmp_path)

    results = recover_claim_publications(
        cache_dir=fixture.cache,
        transaction_root=fixture.transactions,
        lock_root=fixture.locks,
    )

    assert results == (
        sdlc_claim.ClaimPublicationRecoveryResult(
            publication_id,
            "hold",
            "legacy_claim_publication_recovery_forbidden",
        ),
    )
    assert _tree_snapshot(tmp_path) == before


def test_v1_publication_bytes_are_inspection_only(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    publication_id = _materialize_v1_history(fixture)

    results = _inspect_without_effect(
        tmp_path,
        cache_dir=fixture.cache,
        transaction_root=fixture.transactions,
        task_id=fixture.intent.task_id,
        expected_publication_id=publication_id,
    )

    assert len(results) == 1
    assert results[0].disposition == "hold"
    assert results[0].reason_code == "legacy_claim_publication_consumption_required"
    receipt_path = claim_publication_receipt_path(fixture.cache, fixture.intent.binding)
    record = load_claim_publication_receipt(receipt_path)
    assert record["schema"] == CLAIM_PUBLICATION_RECEIPT_SCHEMA
    assert (
        json.loads(
            (fixture.transactions / publication_id / "manifest.json").read_text(encoding="ascii")
        )["schema"]
        == CLAIM_PUBLICATION_SCHEMA
    )


def test_historical_v2_v3_bytes_remain_exact_non_authorizing_history(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)
    consumption = _historical_consumption(fixture, active)
    publication_id = _materialize_admitted_history(fixture, consumption)

    results = _inspect_without_effect(
        tmp_path,
        cache_dir=fixture.cache,
        transaction_root=fixture.transactions,
        task_id=fixture.intent.task_id,
        expected_publication_id=publication_id,
        expected_disposition="terminal_applied",
    )
    snapshot = _resolve(fixture)
    ownership = require_historical_applied_claim_ownership_proof(snapshot)

    assert results[0].disposition == "terminal_applied"
    assert results[0].may_authorize is False
    assert isinstance(ownership, HistoricalAppliedClaimOwnershipProofV3)
    assert ownership.may_authorize is False
    assert snapshot.receipt.schema == HISTORICAL_ADMITTED_CLAIM_PUBLICATION_RECEIPT_SCHEMA
    manifest_record = json.loads(snapshot.manifest_content)
    assert manifest_record["schema"] == HISTORICAL_ADMITTED_CLAIM_PUBLICATION_SCHEMA
    assert manifest_record["admission_consumption"]["schema"] != (
        CLAIM_ADMISSION_CONSUMPTION_SCHEMA
    )


def test_active_v3_v4_history_has_five_proofs_and_twelve_projections(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)
    publication_id = _materialize_admitted_history(fixture, active.consumption)
    manifest_path = fixture.transactions / publication_id / "manifest.json"

    intent, projections, loaded_id, state, loaded_consumption = sdlc_claim._load_admitted_manifest(
        manifest_path
    )
    receipt_path = claim_publication_receipt_path(fixture.cache, fixture.intent.binding)
    receipt = load_admitted_claim_publication_receipt(receipt_path)

    assert intent == fixture.intent
    assert loaded_id == publication_id
    assert state == "applied"
    assert loaded_consumption == active.consumption
    assert len(loaded_consumption.proofs) == 5
    assert {proof.kind for proof in loaded_consumption.proofs} == {
        "action_intent",
        "authority_evidence",
        "execution_admission",
        "execution_lease",
        "valid_authority_grant",
    }
    assert len(projections) == 12
    assert receipt["schema"] == ADMITTED_CLAIM_PUBLICATION_RECEIPT_SCHEMA
    assert receipt["execution_lease_hash"] == active.lease.lease_hash
    assert json.loads(manifest_path.read_text())["schema"] == ADMITTED_CLAIM_PUBLICATION_SCHEMA


def test_claim_admission_requires_the_exact_seven_path_mutation_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)
    monkeypatch.setattr(
        sdlc_claim,
        "claim_publication_mutation_scope_address",
        lambda _intent: _address("wrong-claim-mutation-scope:test"),
    )

    with pytest.raises(ClaimPublicationError) as raised:
        ClaimAdmissionConsumption.create(
            fixture.intent,
            action_intent_path=active.proof_paths[0],
            execution_admission_path=active.proof_paths[1],
            valid_authority_grant_path=active.proof_paths[2],
            authority_evidence_path=active.proof_paths[3],
            execution_lease_path=active.proof_paths[4],
            checked_at=active.checked_at,
        )

    assert raised.value.reason_code == "claim_admission_identity_mismatch"
    assert "claim_publication_mutation_scope_not_exact" in (raised.value.detail or "")


def test_active_publication_provenance_retains_a_without_reusing_it(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)
    _materialize_admitted_history(fixture, active.consumption)
    snapshot = _resolve(fixture)

    provenance = resolve_claim_publication_admission_provenance(snapshot)

    assert provenance.action_intent == active.action
    assert provenance.execution_lease == active.lease
    assert provenance.prospective_claim_basis == prospective_claim_publication_basis(fixture.intent)
    assert provenance.may_authorize is False
    with pytest.raises(
        ExecutionAdmissionError,
        match="current_claim_ownership_outcome_required",
    ):
        applied_claim_proof(snapshot)


def test_active_ownership_requires_matching_closed_applied_outcome(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)
    _materialize_admitted_history(fixture, active.consumption)
    snapshot = _resolve(fixture)
    query_time = active.checked_at + timedelta(seconds=6)
    committer, projection = _outcome_committer(
        active,
        publication_snapshot=snapshot,
    )

    ownership = require_applied_claim_ownership_proof(
        snapshot,
        outcome_committer=committer,
        queried_at=query_time,
    )

    assert isinstance(ownership, AppliedClaimOwnershipProof)
    assert ownership.receipt_schema == ADMITTED_CLAIM_PUBLICATION_RECEIPT_SCHEMA
    assert ownership.publication_execution_lease == active.consumption.execution_lease
    assert ownership.publication_bound_execution_call == active.consumption.bound_execution_call
    assert ownership.publication_action_intent == active.consumption.action_intent
    assert ownership.publication_outcome_committed_at == projection.outcome_receipt.committed_at
    assert ownership.publication_outcome_projection == ContentAddress(
        ref=projection.snapshot_ref,
        sha256=projection.snapshot_hash,
    )
    assert ownership.may_authorize is False

    replay = committer.replay(active.lease, queried_at=query_time)
    assert replay is not None
    position = build_current_claim_position(
        snapshot,
        ownership,
        outcome_replay=replay,
    )
    assert position.applied_claim_ownership == ContentAddress(
        ref=ownership.proof_ref,
        sha256=ownership.proof_hash,
    )
    assert position.current_task_note == ContentAddress(
        ref=str(snapshot.current_task.path),
        sha256=snapshot.current_task.sha256,
    )
    assert tuple((item.key, item.kind) for item in position.lease_files) == tuple(
        (key, kind)
        for key in (
            fixture.intent.role,
            f"{fixture.intent.role}-{fixture.intent.session_id}",
        )
        for kind in ("claim", "epoch", "dispatch_binding")
    )
    assert position.position_ref == f"current-claim-position@sha256:{position.position_hash}"

    snapshot.leases[0].epoch_path.chmod(0o640)
    with pytest.raises(ClaimPublicationError, match="immutable_lease_mismatch"):
        _resolve(fixture)

    with pytest.raises(
        ExecutionAdmissionError,
        match="claim_publication_outcome_receipt_missing",
    ):
        require_applied_claim_ownership_proof(
            snapshot,
            outcome_committer=OutcomeCommitter(
                committer=committer.committer,
                event_plane=committer.event_plane,
                projection_resolver=committer.projection_resolver,
                validity_resolver=committer.validity_resolver,
                catalog_snapshot=build_outcome_replay_catalog_snapshot(
                    committer=committer.committer,
                    event_plane=committer.event_plane,
                    projection_resolver=committer.projection_resolver,
                    validity_resolver=committer.validity_resolver,
                    checked_frontier=committer.current_frontier(
                        queried_at=query_time,
                    ),
                    projections=(),
                    validity_envelopes=(),
                    source_receipt=_address("outcome-catalog-read:empty"),
                    observed_at=query_time,
                ),
            ),
            queried_at=query_time,
        )

    with pytest.raises(
        ExecutionAdmissionError,
        match="claim_publication_outcome_not_applied",
    ):
        failed_committer, _ = _outcome_committer(
            active,
            outcome="failed",
            effect_disposition="not_applied",
            publication_snapshot=snapshot,
        )
        require_applied_claim_ownership_proof(
            snapshot,
            outcome_committer=failed_committer,
            queried_at=query_time,
        )


def test_active_ownership_refuses_outcome_without_exact_publication_postimages(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)
    _materialize_admitted_history(fixture, active.consumption)
    snapshot = _resolve(fixture)
    committer, _ = _outcome_committer(active)

    with pytest.raises(
        ExecutionAdmissionError,
        match="claim_publication_effect_evidence_incomplete",
    ):
        require_applied_claim_ownership_proof(
            snapshot,
            outcome_committer=committer,
            queried_at=active.checked_at + timedelta(seconds=6),
        )


def test_task_evolution_changes_current_position_not_publication_completion(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)
    _materialize_admitted_history(fixture, active.consumption)
    published = _resolve(fixture)
    committer, _ = _outcome_committer(active, publication_snapshot=published)
    query_time = active.checked_at + timedelta(seconds=6)
    ownership = require_applied_claim_ownership_proof(
        published,
        outcome_committer=committer,
        queried_at=query_time,
    )
    replay = committer.replay(active.lease, queried_at=query_time)
    assert replay is not None
    initial_position = build_current_claim_position(
        published,
        ownership,
        outcome_replay=replay,
    )
    task_artifact = next(
        item
        for item in ownership.publication_completion_evidence.artifacts
        if item.kind == "task_note"
    )
    assert task_artifact.content_sha256 == hashlib.sha256(fixture.intent.note_after).hexdigest()

    published.current_task.path.write_bytes(
        published.current_task.content + b"\noperator progress note\n"
    )
    evolved = _resolve(fixture)
    evolved_ownership = require_applied_claim_ownership_proof(
        evolved,
        outcome_committer=committer,
        queried_at=query_time,
    )
    evolved_position = build_current_claim_position(
        evolved,
        evolved_ownership,
        outcome_replay=replay,
    )

    assert evolved_ownership == ownership
    assert evolved_position.current_task_note != initial_position.current_task_note
    assert evolved_position.position_hash != initial_position.position_hash


@pytest.mark.parametrize("mutation", ("path", "mode", "hash"))
def test_claim_publication_artifacts_reject_nonexact_postimages(
    tmp_path: Path,
    mutation: str,
) -> None:
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)
    _materialize_admitted_history(fixture, active.consumption)
    snapshot = _resolve(fixture)
    committer, _ = _outcome_committer(active, publication_snapshot=snapshot)
    ownership = require_applied_claim_ownership_proof(
        snapshot,
        outcome_committer=committer,
        queried_at=active.checked_at + timedelta(seconds=6),
    )
    payload = ownership.publication_completion_evidence.artifacts[0].model_dump(mode="json")
    if mutation == "path":
        payload["path"] = "relative/receipt.json"
    elif mutation == "mode":
        payload["mode"] = 0o640
    else:
        payload["content_sha256"] = "0" * 64

    with pytest.raises(ValueError):
        ClaimPublicationArtifact.model_validate(payload)


@pytest.mark.parametrize("artifact_index", (2, 3, 4))
def test_rehashed_completion_rejects_false_intrinsic_postimage(
    tmp_path: Path,
    artifact_index: int,
) -> None:
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)
    _materialize_admitted_history(fixture, active.consumption)
    snapshot = _resolve(fixture)
    committer, _ = _outcome_committer(active, publication_snapshot=snapshot)
    ownership = require_applied_claim_ownership_proof(
        snapshot,
        outcome_committer=committer,
        queried_at=active.checked_at + timedelta(seconds=6),
    )
    proof = ownership.model_dump(mode="json", by_alias=True)
    completion = proof["publication_completion_evidence"]
    artifact = completion["artifacts"][artifact_index]
    artifact["content_sha256"] = "0" * 64
    artifact["file_address"] = {
        "ref": f"file:{artifact['path']}@sha256:{'0' * 64}",
        "sha256": "0" * 64,
    }
    completion_body = {
        key: value
        for key, value in completion.items()
        if key not in {"evidence_ref", "evidence_hash"}
    }
    completion_hash = _domain_hash(
        CLAIM_PUBLICATION_COMPLETION_EVIDENCE_SCHEMA,
        completion_body,
    )
    completion["evidence_ref"] = f"claim-publication-completion-evidence@sha256:{completion_hash}"
    completion["evidence_hash"] = completion_hash
    proof_body = {
        key: value for key, value in proof.items() if key not in {"proof_ref", "proof_hash"}
    }
    proof_hash = _domain_hash(APPLIED_CLAIM_OWNERSHIP_SCHEMA, proof_body)
    proof["proof_ref"] = f"applied-claim-ownership@sha256:{proof_hash}"
    proof["proof_hash"] = proof_hash

    with pytest.raises(ValueError, match="postimages do not bind"):
        AppliedClaimOwnershipProof.model_validate(proof)


def test_outcome_replay_validity_fails_closed_for_missing_stale_and_old_frontiers(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)
    _materialize_admitted_history(fixture, active.consumption)
    snapshot = _resolve(fixture)
    committer, projection = _outcome_committer(active, publication_snapshot=snapshot)
    query_time = active.checked_at + timedelta(seconds=6)
    assert committer.committer is not None
    assert committer.event_plane is not None
    assert committer.projection_resolver is not None
    assert committer.validity_resolver is not None
    assert committer.catalog_snapshot is not None
    missing = _catalog_committer(
        committer=committer.committer,
        event_plane=committer.event_plane,
        projection_resolver=committer.projection_resolver,
        validity_resolver=committer.validity_resolver,
        frontier=committer.current_frontier(queried_at=query_time),
        projections=(projection,),
        validity_envelopes=(),
        observed_at=query_time,
    )
    with pytest.raises(ExecutionAdmissionError, match="outcome_projection_validity_missing"):
        missing.replay(active.lease, queried_at=query_time)
    with pytest.raises(ExecutionAdmissionError, match="outcome_projection_validity_stale"):
        committer.replay(active.lease, queried_at=active.checked_at + timedelta(minutes=11))
    with pytest.raises(ExecutionAdmissionError, match="outcome_replay_time_rewound"):
        committer.replay(active.lease, queried_at=active.checked_at + timedelta(seconds=5))

    advanced_frontier = _address("event-frontier:advanced-without-validity")
    old_frontier = _catalog_committer(
        committer=committer.committer,
        event_plane=committer.event_plane,
        projection_resolver=committer.projection_resolver,
        validity_resolver=committer.validity_resolver,
        frontier=advanced_frontier,
        projections=(projection,),
        validity_envelopes=(),
        observed_at=query_time,
    )
    with pytest.raises(ExecutionAdmissionError, match="outcome_projection_validity_missing"):
        old_frontier.replay(active.lease, queried_at=query_time)
    with pytest.raises(ValueError, match="differ from their catalog snapshot"):
        _catalog_committer(
            committer=committer.committer,
            event_plane=committer.event_plane,
            projection_resolver=committer.projection_resolver,
            validity_resolver=committer.validity_resolver,
            frontier=advanced_frontier,
            projections=(projection,),
            validity_envelopes=committer.catalog_snapshot.validity_envelopes,
            observed_at=query_time,
        )


def test_outcome_replay_rejects_held_and_overlapping_validity(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)
    _materialize_admitted_history(fixture, active.consumption)
    snapshot = _resolve(fixture)
    committer, projection = _outcome_committer(active, publication_snapshot=snapshot)
    assert committer.committer is not None
    assert committer.event_plane is not None
    assert committer.projection_resolver is not None
    assert committer.validity_resolver is not None
    assert committer.catalog_snapshot is not None
    base = committer.catalog_snapshot.validity_envelopes[0]
    dispositions = list(base.root_dispositions)
    first = dispositions[0]
    dispositions[0] = RootDisposition(
        root=first.root,
        disposition="revoked",
        superseding_roots=(),
        reason_codes=("projection_root_revoked",),
        source_event_refs=first.source_event_refs,
    )
    held = build_frontier_validity_envelope(
        subject_projection=base.subject_projection,
        resolver=base.resolver,
        event_plane=base.event_plane,
        source_frontier=base.source_frontier,
        checked_frontier=base.checked_frontier,
        root_dispositions=dispositions,
        decision="hold",
        reason_codes=("projection_root_revoked",),
        checked_at=base.checked_at,
        stale_after=base.stale_after,
    )
    held_committer = _catalog_committer(
        committer=committer.committer,
        event_plane=committer.event_plane,
        projection_resolver=committer.projection_resolver,
        validity_resolver=committer.validity_resolver,
        frontier=committer.current_frontier(
            queried_at=active.checked_at + timedelta(seconds=6),
        ),
        projections=(projection,),
        validity_envelopes=(held,),
        observed_at=active.checked_at + timedelta(seconds=6),
    )
    with pytest.raises(ExecutionAdmissionError, match="outcome_projection_not_current"):
        held_committer.replay(
            active.lease,
            queried_at=active.checked_at + timedelta(seconds=6),
        )

    overlap = build_frontier_validity_envelope(
        subject_projection=base.subject_projection,
        resolver=base.resolver,
        event_plane=base.event_plane,
        source_frontier=base.source_frontier,
        checked_frontier=base.checked_frontier,
        root_dispositions=base.root_dispositions,
        decision="valid",
        checked_at=active.checked_at + timedelta(seconds=7),
        stale_after=active.checked_at + timedelta(minutes=9),
    )
    with pytest.raises(ValueError, match="intervals must not overlap"):
        _catalog_committer(
            committer=committer.committer,
            event_plane=committer.event_plane,
            projection_resolver=committer.projection_resolver,
            validity_resolver=committer.validity_resolver,
            frontier=committer.current_frontier(
                queried_at=active.checked_at + timedelta(seconds=7),
            ),
            projections=(projection,),
            validity_envelopes=(base, overlap),
            observed_at=active.checked_at + timedelta(seconds=7),
        )
    with pytest.raises(TypeError):
        committer.replay(active.lease)  # type: ignore[call-arg]


def test_outcome_catalog_rejects_precommit_and_incomplete_validity(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)
    _materialize_admitted_history(fixture, active.consumption)
    snapshot = _resolve(fixture)
    committer, projection = _outcome_committer(active, publication_snapshot=snapshot)
    assert committer.committer is not None
    assert committer.event_plane is not None
    assert committer.projection_resolver is not None
    assert committer.validity_resolver is not None
    assert committer.catalog_snapshot is not None
    base = committer.catalog_snapshot.validity_envelopes[0]
    precommit = build_frontier_validity_envelope(
        subject_projection=base.subject_projection,
        resolver=base.resolver,
        event_plane=base.event_plane,
        source_frontier=base.source_frontier,
        checked_frontier=base.checked_frontier,
        root_dispositions=base.root_dispositions,
        decision="valid",
        checked_at=active.checked_at + timedelta(seconds=4),
        stale_after=active.checked_at + timedelta(minutes=10),
    )
    with pytest.raises(ValueError, match="cannot predate its outcome commit"):
        _catalog_committer(
            committer=committer.committer,
            event_plane=committer.event_plane,
            projection_resolver=committer.projection_resolver,
            validity_resolver=committer.validity_resolver,
            frontier=committer.current_frontier(
                queried_at=active.checked_at + timedelta(seconds=6),
            ),
            projections=(projection,),
            validity_envelopes=(precommit,),
            observed_at=active.checked_at + timedelta(seconds=6),
        )
    incomplete = build_frontier_validity_envelope(
        subject_projection=base.subject_projection,
        resolver=base.resolver,
        event_plane=base.event_plane,
        source_frontier=base.source_frontier,
        checked_frontier=base.checked_frontier,
        root_dispositions=base.root_dispositions[:-1],
        decision="valid",
        checked_at=base.checked_at,
        stale_after=base.stale_after,
    )
    incomplete_committer = _catalog_committer(
        committer=committer.committer,
        event_plane=committer.event_plane,
        projection_resolver=committer.projection_resolver,
        validity_resolver=committer.validity_resolver,
        frontier=committer.current_frontier(
            queried_at=active.checked_at + timedelta(seconds=6),
        ),
        projections=(projection,),
        validity_envelopes=(incomplete,),
        observed_at=active.checked_at + timedelta(seconds=6),
    )
    with pytest.raises(ExecutionAdmissionError, match="outcome_projection_not_current"):
        incomplete_committer.replay(
            active.lease,
            queried_at=active.checked_at + timedelta(seconds=6),
        )


def test_outcome_frontier_rejects_catalog_observed_after_query(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)
    _materialize_admitted_history(fixture, active.consumption)
    snapshot = _resolve(fixture)
    committer, projection = _outcome_committer(
        active,
        publication_snapshot=snapshot,
    )
    assert committer.committer is not None
    assert committer.event_plane is not None
    assert committer.projection_resolver is not None
    assert committer.validity_resolver is not None
    assert committer.catalog_snapshot is not None
    query_time = active.checked_at + timedelta(seconds=6)
    observed_at = query_time + timedelta(seconds=1)
    future_catalog = _catalog_committer(
        committer=committer.committer,
        event_plane=committer.event_plane,
        projection_resolver=committer.projection_resolver,
        validity_resolver=committer.validity_resolver,
        frontier=committer.catalog_snapshot.checked_frontier,
        projections=(projection,),
        validity_envelopes=committer.catalog_snapshot.validity_envelopes,
        observed_at=observed_at,
    )

    with pytest.raises(ExecutionAdmissionError, match="outcome_replay_time_rewound"):
        future_catalog.current_frontier(queried_at=query_time)

    assert future_catalog.current_frontier(queried_at=observed_at) == (
        committer.catalog_snapshot.checked_frontier
    )


def test_frontier_validity_builder_rejects_hostile_disposition_before_dispatch() -> None:
    class HostileDisposition:
        touched = False

        @property
        def root(self) -> ContentAddress:
            type(self).touched = True
            raise AssertionError("hostile root access")

    hostile = HostileDisposition()
    with pytest.raises(ExecutionAdmissionError, match="execution_projection_type_invalid"):
        build_frontier_validity_envelope(
            subject_projection=_address("projection:test"),
            resolver=_address("resolver:test"),
            event_plane=_address("event-plane:test"),
            source_frontier=_address("source-frontier:test"),
            checked_frontier=_address("checked-frontier:test"),
            root_dispositions=(hostile,),  # type: ignore[arg-type]
            decision="valid",
            checked_at=datetime(2026, 7, 10, tzinfo=UTC),
            stale_after=datetime(2026, 7, 10, 0, 1, tzinfo=UTC),
        )
    assert hostile.touched is False


def test_refreshed_frontier_preserves_stable_position_and_durable_ownership(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)
    _materialize_admitted_history(fixture, active.consumption)
    snapshot = _resolve(fixture)
    initial, projection = _outcome_committer(active, publication_snapshot=snapshot)
    initial_time = active.checked_at + timedelta(seconds=6)
    initial_ownership = require_applied_claim_ownership_proof(
        snapshot,
        outcome_committer=initial,
        queried_at=initial_time,
    )
    initial_replay = initial.replay(active.lease, queried_at=initial_time)
    assert initial_replay is not None
    initial_position = build_current_claim_position(
        snapshot,
        initial_ownership,
        outcome_replay=initial_replay,
    )
    initial_resolution = AppliedClaimResolution(
        vault_root=fixture.vault,
        cache_dir=fixture.cache,
        role=fixture.intent.role,
        session_id=fixture.intent.session_id,
        task_id=fixture.intent.task_id,
        transaction_root=fixture.transactions,
        lock_root=fixture.locks,
        outcome_committer=initial,
    ).resolve_basis(queried_at=initial_time)
    assert initial_resolution.ownership == initial_ownership
    assert initial_resolution.current_position == initial_position
    with pytest.raises(ExecutionAdmissionError, match="outcome_projection_validity_stale"):
        AppliedClaimResolution(
            vault_root=fixture.vault,
            cache_dir=fixture.cache,
            role=fixture.intent.role,
            session_id=fixture.intent.session_id,
            task_id=fixture.intent.task_id,
            transaction_root=fixture.transactions,
            lock_root=fixture.locks,
            outcome_committer=initial,
        ).resolve_basis(queried_at=active.checked_at + timedelta(minutes=11))

    advanced_time = active.checked_at + timedelta(minutes=1)
    advanced, _ = _revalidated_outcome_committer(
        initial,
        projection,
        frontier=_address("event-frontier:advanced"),
        checked_at=advanced_time,
    )
    advanced_ownership = require_applied_claim_ownership_proof(
        snapshot,
        outcome_committer=advanced,
        queried_at=advanced_time,
    )
    advanced_replay = advanced.replay(active.lease, queried_at=advanced_time)
    assert advanced_replay is not None
    advanced_position = build_current_claim_position(
        snapshot,
        advanced_ownership,
        outcome_replay=advanced_replay,
    )
    advanced_resolution = AppliedClaimResolution(
        vault_root=fixture.vault,
        cache_dir=fixture.cache,
        role=fixture.intent.role,
        session_id=fixture.intent.session_id,
        task_id=fixture.intent.task_id,
        transaction_root=fixture.transactions,
        lock_root=fixture.locks,
        outcome_committer=advanced,
    ).resolve_basis(queried_at=advanced_time)

    assert advanced_ownership == initial_ownership
    assert advanced_position == initial_position
    assert advanced_resolution.ownership == initial_resolution.ownership
    assert advanced_resolution.current_position == initial_resolution.current_position
    assert advanced_replay.catalog_snapshot != initial_replay.catalog_snapshot
    assert advanced_replay.validity != initial_replay.validity


def test_historical_v3_ownership_cannot_be_upgraded_by_supplying_an_outcome(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)
    historical = _historical_consumption(fixture, active)
    _materialize_admitted_history(fixture, historical)
    snapshot = _resolve(fixture)
    committer, _ = _outcome_committer(active)

    with pytest.raises(
        ExecutionAdmissionError,
        match="current_action_claim_ownership_v7_required",
    ):
        require_applied_claim_ownership_proof(
            snapshot,
            outcome_committer=committer,
            queried_at=active.checked_at + timedelta(seconds=6),
        )


def test_active_receipt_and_manifest_schema_are_not_downgrade_aliases(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)
    publication_id = _materialize_admitted_history(fixture, active.consumption)
    receipt_path = claim_publication_receipt_path(fixture.cache, fixture.intent.binding)
    receipt = json.loads(receipt_path.read_text())
    receipt["schema"] = HISTORICAL_ADMITTED_CLAIM_PUBLICATION_RECEIPT_SCHEMA
    downgraded = _canonical(receipt) + b"\n"

    with pytest.raises(ClaimPublicationError) as raised:
        load_admitted_claim_publication_receipt(receipt_path, content=downgraded)
    assert raised.value.reason_code == "claim_publication_receipt_malformed"

    manifest_path = fixture.transactions / publication_id / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["schema"] = HISTORICAL_ADMITTED_CLAIM_PUBLICATION_SCHEMA
    manifest_path.write_bytes(_canonical(manifest) + b"\n")
    with pytest.raises(ClaimPublicationError) as raised:
        sdlc_claim._load_admitted_manifest(manifest_path)
    assert raised.value.reason_code in {
        "claim_publication_manifest_shape_malformed",
        "claim_admission_consumption_malformed",
    }


def test_active_require_is_inspection_only_and_does_not_need_live_proof_files(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)
    _materialize_admitted_history(fixture, active.consumption)
    for path in active.proof_paths:
        path.unlink()
    before = tuple(
        _tree_snapshot(root) for root in (fixture.vault, fixture.cache, fixture.transactions)
    )

    receipt = require_applied_admitted_claim_publication(
        fixture.intent,
        active.consumption,
        transaction_root=fixture.transactions,
        lock_root=fixture.locks,
    )

    assert receipt.schema == ADMITTED_CLAIM_PUBLICATION_RECEIPT_SCHEMA
    assert (
        tuple(_tree_snapshot(root) for root in (fixture.vault, fixture.cache, fixture.transactions))
        == before
    )


def test_inspection_is_read_only_for_active_terminal_history(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)
    publication_id = _materialize_admitted_history(fixture, active.consumption)
    for path in active.proof_paths:
        path.unlink()

    results = _inspect_without_effect(
        tmp_path,
        cache_dir=fixture.cache,
        transaction_root=fixture.transactions,
        task_id=fixture.intent.task_id,
        expected_publication_id=publication_id,
        expected_disposition="terminal_applied",
    )

    assert len(results) == 1
    inspection = results[0]
    assert inspection.disposition == "terminal_applied"
    assert inspection.reason_code is None
    assert inspection.projection_addresses == ()
    assert inspection.inspection_ref == (
        f"claim-publication-inspection@sha256:{inspection.inspection_hash}"
    )
    assert inspection.may_authorize is False


def test_inspection_absence_is_clean_unless_exact_history_is_expected(
    tmp_path: Path,
) -> None:
    transactions = tmp_path / "transactions"
    cache = tmp_path / "cache"
    cache.mkdir()

    assert (
        inspect_claim_publications(
            cache_dir=cache,
            transaction_root=transactions,
        )
        == ()
    )

    publication_id = f"claim-pub-{'f' * 64}"
    results = _inspect_without_effect(
        tmp_path,
        cache_dir=cache,
        transaction_root=transactions,
        task_id="task-alpha",
        expected_publication_id=publication_id,
    )
    assert results[0].publication_id == publication_id
    assert results[0].disposition == "hold"
    assert results[0].reason_code == "claim_publication_manifest_missing"


def test_inspection_rejects_malformed_expectations_without_mutation(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    _materialize_v1_history(fixture)

    malformed = _inspect_without_effect(
        tmp_path,
        cache_dir=fixture.cache,
        transaction_root=fixture.transactions,
        expected_publication_id="claim-pub-NOT-A-DIGEST",
    )
    mode_without_id = _inspect_without_effect(
        tmp_path,
        cache_dir=fixture.cache,
        transaction_root=fixture.transactions,
        expected_disposition="terminal_applied",
    )

    assert any(item.reason_code == "claim_publication_expected_id_invalid" for item in malformed)
    assert any(
        item.reason_code == "claim_publication_expected_mode_without_id" for item in mode_without_id
    )
    assert all(item.disposition == "hold" for item in (*malformed, *mode_without_id))


def test_inspection_holds_unknown_and_unsafe_journal_entries(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    transactions = tmp_path / "transactions"
    transactions.mkdir(mode=0o700)
    corrupt = transactions / "claim-pub-corrupt"
    corrupt.mkdir(mode=0o700)
    (corrupt / "manifest.json").write_bytes(b"{}\n")
    (corrupt / "manifest.json").chmod(0o600)

    corrupt_results = _inspect_without_effect(
        tmp_path,
        cache_dir=cache,
        transaction_root=transactions,
    )
    assert corrupt_results[0].publication_id == "claim-pub-corrupt"
    assert corrupt_results[0].disposition == "hold"

    target = tmp_path / "target"
    target.mkdir()
    symlink = tmp_path / "symlink-transactions"
    symlink.symlink_to(target, target_is_directory=True)
    symlink_results = _inspect_without_effect(
        tmp_path,
        cache_dir=cache,
        transaction_root=symlink,
    )
    assert symlink_results[0].reason_code == "fs_snapshot_directory_unsafe"


def test_inspection_does_not_hold_on_a_journal_it_already_told_you_to_quarantine(
    tmp_path: Path,
) -> None:
    """The remedy must not be the condition.

    An unknown entry's repair action is "quarantine every entry outside the exact
    claim publication grammar", and quarantining renames the journal to
    ``claim-pub-<sha>.quarantined-<stamp>`` — which is outside that grammar. So the
    hold demanded its own cause, and could only be cleared by moving the journal out
    of the scan root by hand (measured 2026-09-13, cx-p0, twice).

    All three stamp shapes that exist on disk are covered, because **no code
    produces this name** — every "quarantine ..." string in the module is a repair
    action addressed to a person, so the suffix is a hand convention and a matcher
    pinned to one stamp grammar would leave the others holding forever.
    """

    cache = tmp_path / "cache"
    cache.mkdir()
    transactions = tmp_path / "transactions"
    transactions.mkdir(mode=0o700)
    sha = "a" * 64
    for stamp in ("20260821", "20260905T0041Z", "20260913T205924Z"):
        quarantined = transactions / f"claim-pub-{sha}.quarantined-{stamp}"
        quarantined.mkdir(mode=0o700)
        (quarantined / "manifest.json").write_bytes(b"{}\n")
        (quarantined / "manifest.json").chmod(0o600)

    results = _inspect_without_effect(
        tmp_path,
        cache_dir=cache,
        transaction_root=transactions,
    )

    assert results == ()

    # Fail-open check: a genuinely foreign entry is still held, so the skip is a
    # verdict about an already-remedied journal and not a hole in the grammar.
    foreign = transactions / "claim-pub-not-a-journal"
    foreign.mkdir(mode=0o700)
    held = _inspect_without_effect(
        tmp_path,
        cache_dir=cache,
        transaction_root=transactions,
    )
    assert [entry.publication_id for entry in held] == ["claim-pub-not-a-journal"]
    assert held[0].reason_code == "claim_publication_transaction_entry_unknown"
    assert foreign.is_dir()
    foreign.rmdir()

    # And the state cx-p0 ACTUALLY produced: the live journal still present beside its
    # quarantined sibling, same sha. "The verdict drops, the evidence does not" has to mean the
    # live journal is inspected normally while the sibling is skipped — so the skip must be
    # narrow (this exact suffixed name) and not sha-wide. A reviewer noted the three stamp
    # grammars above never put both forms on disk at once, which is the case that matters.
    live = transactions / f"claim-pub-{sha}"
    live.mkdir(mode=0o700)
    both = _inspect_without_effect(
        tmp_path,
        cache_dir=cache,
        transaction_root=transactions,
    )
    assert [entry.publication_id for entry in both] == [f"claim-pub-{sha}"], (
        "the live journal was skipped along with its quarantined sibling — the skip is "
        "sha-wide, so quarantining one attempt would hide the next one at the same sha"
    )
    assert live.is_dir()
    for stamp in ("20260821", "20260905T0041Z", "20260913T205924Z"):
        assert (transactions / f"claim-pub-{sha}.quarantined-{stamp}").is_dir()


def test_publication_identity_is_deterministic_but_path_bound(tmp_path: Path) -> None:
    first = _fixture(tmp_path / "one")
    second = _fixture(tmp_path / "two")

    assert claim_publication_id(first.intent) == claim_publication_id(first.intent)
    assert claim_publication_id(first.intent) != claim_publication_id(second.intent)
    assert first.intent.intent_sha256 != second.intent.intent_sha256


def test_gate0a_claim_module_contains_no_filesystem_installers() -> None:
    source = Path(sdlc_claim.__file__).read_text(encoding="utf-8")
    forbidden = (
        "_atomic_install",
        "_install_private_entry",
        "def _write_blob(",
        "def _write_manifest(",
        "def _write_admitted_manifest(",
        "def _write_any_manifest(",
        "def _write_receipt(",
        "def _write_admitted_receipt(",
        "def _write_any_receipt(",
    )
    assert not tuple(item for item in forbidden if item in source)


def _claim_estate(fixture: ClaimFixture) -> tuple[object, ...]:
    return tuple(
        _tree_snapshot(root)
        for root in (
            fixture.vault,
            fixture.cache,
            fixture.transactions,
            fixture.locks,
        )
    )


def test_all_public_require_and_resolve_paths_are_zero_write(tmp_path: Path) -> None:
    legacy = _fixture(tmp_path / "legacy", task_id="task-legacy")
    _materialize_v1_history(legacy)
    before = _claim_estate(legacy)

    required = sdlc_claim.require_applied_claim_publication(
        legacy.intent,
        transaction_root=legacy.transactions,
        lock_root=legacy.locks,
    )
    resolved = sdlc_claim.resolve_applied_claim_publication(
        vault_root=legacy.vault,
        cache_dir=legacy.cache,
        role=legacy.intent.role,
        session_id=legacy.intent.session_id,
        task_id=legacy.intent.task_id,
        transaction_root=legacy.transactions,
        lock_root=legacy.locks,
    )
    resolved_for_task = sdlc_claim.resolve_applied_claim_publication_for_task(
        vault_root=legacy.vault,
        cache_dir=legacy.cache,
        role=legacy.intent.role,
        task_id=legacy.intent.task_id,
        transaction_root=legacy.transactions,
        lock_root=legacy.locks,
    )

    assert required.publication_id == resolved.receipt.publication_id
    assert resolved_for_task == resolved
    assert _claim_estate(legacy) == before
    assert not legacy.locks.exists()

    admitted = _fixture(tmp_path / "admitted", task_id="task-admitted")
    active = _active_admission_fixture(tmp_path / "admitted", admitted)
    _materialize_admitted_history(admitted, active.consumption)
    for path in active.proof_paths:
        path.unlink()
    before = _claim_estate(admitted)

    receipt = sdlc_claim.require_applied_admitted_claim_publication(
        admitted.intent,
        active.consumption,
        transaction_root=admitted.transactions,
        lock_root=admitted.locks,
    )

    assert receipt.schema == ADMITTED_CLAIM_PUBLICATION_RECEIPT_SCHEMA
    assert _claim_estate(admitted) == before
    assert not admitted.locks.exists()


def test_resolver_refuses_active_closed_duplicate_without_lock_writes(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    _materialize_v1_history(fixture)
    closed = fixture.vault / "closed" / f"{fixture.intent.task_id}.md"
    closed.write_bytes(fixture.intent.note_after)
    before = _claim_estate(fixture)

    with pytest.raises(ClaimPublicationError) as raised:
        resolve_applied_claim_publication(
            vault_root=fixture.vault,
            cache_dir=fixture.cache,
            role=fixture.intent.role,
            session_id=fixture.intent.session_id,
            task_id=fixture.intent.task_id,
            transaction_root=fixture.transactions,
            lock_root=fixture.locks,
        )

    assert raised.value.reason_code == "task_note_cross_state_duplicate"
    assert _claim_estate(fixture) == before
    assert not fixture.locks.exists()


def test_resolver_seal_refuses_concurrent_manifest_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    publication_id = _materialize_v1_history(fixture)
    manifest = fixture.transactions / publication_id / "manifest.json"
    original_seal = sdlc_claim.ReadOnlyFsSnapshot.seal

    def mutate_then_seal(snapshot: object) -> object:
        manifest.write_bytes(manifest.read_bytes() + b" ")
        return original_seal(snapshot)

    monkeypatch.setattr(sdlc_claim.ReadOnlyFsSnapshot, "seal", mutate_then_seal)
    with pytest.raises(ClaimPublicationError) as raised:
        resolve_applied_claim_publication(
            vault_root=fixture.vault,
            cache_dir=fixture.cache,
            role=fixture.intent.role,
            session_id=fixture.intent.session_id,
            task_id=fixture.intent.task_id,
            transaction_root=fixture.transactions,
            lock_root=fixture.locks,
        )

    assert raised.value.reason_code in {
        "fs_snapshot_concurrent_change",
        "fs_snapshot_file_changed",
    }
    assert not fixture.locks.exists()


def test_require_refuses_missing_blob_and_unsafe_receipt(tmp_path: Path) -> None:
    missing = _fixture(tmp_path / "missing", task_id="task-missing")
    publication_id = _materialize_v1_history(missing)
    blob = next(
        path
        for path in (missing.transactions / publication_id).iterdir()
        if path.name.endswith(".after")
    )
    blob.unlink()
    with pytest.raises(ClaimPublicationError) as raised:
        sdlc_claim.require_applied_claim_publication(
            missing.intent,
            transaction_root=missing.transactions,
            lock_root=missing.locks,
        )
    assert raised.value.reason_code == "claim_publication_blob_missing"
    assert not missing.locks.exists()

    unsafe = _fixture(tmp_path / "unsafe", task_id="task-unsafe")
    _materialize_v1_history(unsafe)
    receipt = claim_publication_receipt_path(unsafe.cache, unsafe.intent.binding)
    target = tmp_path / "unsafe-receipt-target"
    target.write_bytes(receipt.read_bytes())
    target.chmod(0o600)
    receipt.unlink()
    receipt.symlink_to(target)
    with pytest.raises(ClaimPublicationError) as raised:
        sdlc_claim.require_applied_claim_publication(
            unsafe.intent,
            transaction_root=unsafe.transactions,
            lock_root=unsafe.locks,
        )
    assert raised.value.reason_code == "fs_snapshot_file_unsafe"
    assert not unsafe.locks.exists()


def _churning_transaction_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    churn: str,
    transient: bool = False,
) -> tuple[Path, Path, list[int]]:
    """Make each inspection race a peer claim writing into the shared root."""

    cache = tmp_path / "cache"
    cache.mkdir()
    # The receipt root is absent, so the snapshot lists and watches the whole
    # cache directory, as it does for the busy ~/.cache/hapax in production.
    peer_state = cache / "cc-active-task-peer"
    peer_state.write_bytes(b"peer-task-0\n")
    transactions = tmp_path / "transactions"
    transactions.mkdir(mode=0o700)
    original = sdlc_claim.ReadOnlyFsSnapshot.seal
    captures: list[int] = []

    def racing(snapshot: object) -> object:
        captures.append(len(captures) + 1)
        if not transient or len(captures) == 1:
            if churn == "concurrent_change":
                # A peer lane rewrites its own claim file in place: no listing
                # or directory stamp changes; only the watch guard sees it.
                with peer_state.open("r+b") as handle:
                    handle.write(f"peer-task-{len(captures)}\n".encode())
            else:
                (transactions / f"peer-{len(captures)}.tmp").write_bytes(b"peer")
        return original(snapshot)  # type: ignore[arg-type]

    monkeypatch.setattr(sdlc_claim.ReadOnlyFsSnapshot, "seal", racing)
    return cache, transactions, captures


def test_inspection_retake_is_only_for_concurrent_change_not_other_snapshot_holds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache, transactions, captures = _churning_transaction_root(
        tmp_path, monkeypatch, churn="root_entry_added"
    )
    sleeps: list[float] = []
    monkeypatch.setattr(sdlc_claim, "_churn_sleep", sleeps.append)

    results = inspect_claim_publications(cache_dir=cache, transaction_root=transactions)

    assert [item.reason_code for item in results] == ["fs_snapshot_directory_changed"]
    assert captures == [1]
    assert sleeps == []


def test_inspection_concurrent_change_retake_is_bounded_with_jitter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache, transactions, captures = _churning_transaction_root(
        tmp_path, monkeypatch, churn="concurrent_change"
    )
    sleeps: list[float] = []
    monkeypatch.setattr(sdlc_claim, "_churn_sleep", sleeps.append)

    results = inspect_claim_publications(cache_dir=cache, transaction_root=transactions)

    assert [(item.disposition, item.reason_code) for item in results] == [
        ("hold", "fs_snapshot_concurrent_change")
    ]
    assert results[0].publication_id == f"transaction-root:{transactions}"
    assert len(captures) == sdlc_claim.INSPECTION_CHURN_MAX_ATTEMPTS
    assert len(sleeps) == sdlc_claim.INSPECTION_CHURN_MAX_ATTEMPTS - 1
    low, high = sdlc_claim.INSPECTION_CHURN_JITTER_SECONDS
    assert all(low <= delay <= high for delay in sleeps)


def test_inspection_concurrent_change_retake_stops_at_its_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache, transactions, captures = _churning_transaction_root(
        tmp_path, monkeypatch, churn="concurrent_change"
    )
    now = [0.0]

    def clock() -> float:
        now[0] += 20.0
        return now[0]

    monkeypatch.setattr(sdlc_claim, "_churn_sleep", lambda _seconds: None)
    monkeypatch.setattr(sdlc_claim, "_churn_clock", clock)

    results = inspect_claim_publications(cache_dir=cache, transaction_root=transactions)

    assert [item.reason_code for item in results] == ["fs_snapshot_concurrent_change"]
    assert 1 <= len(captures) < sdlc_claim.INSPECTION_CHURN_MAX_ATTEMPTS


def test_inspection_recovers_from_a_transient_concurrent_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache, transactions, captures = _churning_transaction_root(
        tmp_path, monkeypatch, churn="concurrent_change", transient=True
    )
    sleeps: list[float] = []
    monkeypatch.setattr(sdlc_claim, "_churn_sleep", sleeps.append)

    results = inspect_claim_publications(cache_dir=cache, transaction_root=transactions)

    assert results == ()
    assert captures == [1, 2]
    assert len(sleeps) == 1


# ── task resolution retaken through task-store frontier churn (M95) ──────────
# claim-publication-frontier-churn-bounded-retry-m95-20260927

_CHURN_POINTS = {
    # where a peer lane's write lands inside one resolve_task_note -> the reason it raises
    "index_build": "task_store_frontier_changed_during_index_build",
    "since_index": "task_store_frontier_changed_since_index",
    "during_resolution": "task_store_frontier_changed_during_resolution",
}


def _churning_task_store(
    vault: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    point: str = "index_build",
    churn_on: Callable[[int], bool] = lambda _resolution: True,
) -> list[int]:
    """Change a peer task identity inside a resolution.

    Session-log appends are now accepted when identity is stable. This fixture changes
    the peer's task_id at ``point`` so each refusal remains an identity-frontier race.
    ``churn_on(n)`` decides per resolution attempt; the list counts attempts.
    """

    peer = vault / "active" / "peer-row.md"
    if not peer.exists():
        peer.write_bytes(
            _note(
                task_id="peer-row",
                status="in_progress",
                assigned_to="cx-blue",
                claimed_at="2026-07-11T11:00:00Z",
            )
        )
    attempts: list[int] = []
    index_build_pending = [False]

    def peer_writes() -> None:
        if churn_on(len(attempts)):
            content = peer.read_bytes()
            if b"task_id: peer-row\n" in content:
                peer.write_bytes(
                    content.replace(b"task_id: peer-row\n", b"task_id: peer-row-alt\n")
                )
            else:
                peer.write_bytes(
                    content.replace(b"task_id: peer-row-alt\n", b"task_id: peer-row\n")
                )

    original_build = sdlc_task_store.build_task_identity_index
    original_entry = sdlc_task_store._index_entry
    original_reconcile = sdlc_task_store._reconcile_nonidentity_frontier
    original_snapshot = sdlc_task_store._snapshot

    def build(vault_root: Path) -> object:
        attempts.append(len(attempts) + 1)
        index_build_pending[0] = point == "index_build"
        return original_build(vault_root)

    def index_entry(path: Path, **kwargs: object) -> object:
        entry = original_entry(path, **kwargs)  # type: ignore[arg-type]
        if path.name == "peer-row.md" and index_build_pending[0]:
            index_build_pending[0] = False
            peer_writes()
        return entry

    def reconcile(index: object, *, reason_code: str, **kwargs: object) -> object:
        if point == "since_index" and reason_code == "task_store_frontier_changed_since_index":
            peer_writes()
        return original_reconcile(index, reason_code=reason_code, **kwargs)  # type: ignore[arg-type]

    def snapshot(path: Path, **kwargs: object) -> object:
        if point == "during_resolution":
            peer_writes()
        return original_snapshot(path, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(sdlc_task_store, "build_task_identity_index", build)
    monkeypatch.setattr(sdlc_task_store, "_index_entry", index_entry)
    monkeypatch.setattr(sdlc_task_store, "_reconcile_nonidentity_frontier", reconcile)
    monkeypatch.setattr(sdlc_task_store, "_snapshot", snapshot)
    return attempts


def _open_deadline() -> float:
    """An under-lock deadline far enough out that only the attempt bound applies."""
    return sdlc_claim._churn_clock() + 3600.0


@pytest.mark.parametrize("point", sorted(_CHURN_POINTS))
def test_task_resolution_is_retaken_through_transient_frontier_churn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, point: str
) -> None:
    fixture = _fixture(tmp_path)
    attempts = _churning_task_store(
        fixture.vault, monkeypatch, point=point, churn_on=lambda n: n == 1
    )
    sleeps: list[float] = []
    monkeypatch.setattr(sdlc_claim, "_churn_sleep", sleeps.append)

    task = sdlc_claim.resolve_task_note_through_churn(fixture.vault, "task-alpha")

    assert task.path == fixture.intent.note_path
    assert task.content == fixture.intent.note_before
    assert attempts == [1, 2]
    low, high = sdlc_claim.INSPECTION_CHURN_JITTER_SECONDS
    assert len(sleeps) == 1 and low <= sleeps[0] <= high


@pytest.mark.parametrize("point", sorted(_CHURN_POINTS))
def test_task_resolution_churn_retake_is_bounded_and_raises_the_last_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, point: str
) -> None:
    fixture = _fixture(tmp_path)
    attempts = _churning_task_store(fixture.vault, monkeypatch, point=point)
    sleeps: list[float] = []
    monkeypatch.setattr(sdlc_claim, "_churn_sleep", sleeps.append)

    with pytest.raises(TaskStoreError) as raised:
        sdlc_claim.resolve_task_note_through_churn(fixture.vault, "task-alpha")

    assert raised.value.reason_code == _CHURN_POINTS[point]
    assert len(attempts) == sdlc_claim.INSPECTION_CHURN_MAX_ATTEMPTS
    assert len(sleeps) == sdlc_claim.INSPECTION_CHURN_MAX_ATTEMPTS - 1


def test_task_resolution_churn_retake_stops_at_its_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    attempts = _churning_task_store(fixture.vault, monkeypatch)
    now = [0.0]

    def clock() -> float:
        now[0] += 20.0
        return now[0]

    monkeypatch.setattr(sdlc_claim, "_churn_sleep", lambda _seconds: None)
    monkeypatch.setattr(sdlc_claim, "_churn_clock", clock)

    with pytest.raises(TaskStoreError) as raised:
        sdlc_claim.resolve_task_note_through_churn(fixture.vault, "task-alpha")

    assert raised.value.reason_code == "task_store_frontier_changed_during_index_build"
    assert 1 <= len(attempts) < sdlc_claim.INSPECTION_CHURN_MAX_ATTEMPTS


def test_task_resolution_retake_is_only_for_frontier_churn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    # A closed duplicate is a real refusal, not churn: it is raised at once, never retaken.
    closed_copy = fixture.vault / "closed" / "task-alpha.md"
    closed_copy.write_bytes(fixture.intent.note_before)
    sleeps: list[float] = []
    monkeypatch.setattr(sdlc_claim, "_churn_sleep", sleeps.append)

    with pytest.raises(TaskStoreError) as raised:
        sdlc_claim.resolve_task_note_through_churn(fixture.vault, "task-alpha")

    assert raised.value.reason_code == "task_note_cross_state_duplicate"
    assert sleeps == []


def test_locked_preflight_and_postimage_retake_frontier_churn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The two resolutions under the publication lock (15:14Z and 09-26 21:12Z specimens):
    # the postimage one, after the writes, left a recovery_required journal.
    fixture = _fixture(tmp_path)
    attempts = _churning_task_store(fixture.vault, monkeypatch, churn_on=lambda n: n % 2 == 1)
    monkeypatch.setattr(sdlc_claim, "_churn_sleep", lambda _seconds: None)

    sdlc_claim._locked_preflight(fixture.intent, (), deadline_at=_open_deadline())
    fixture.intent.note_path.write_bytes(fixture.intent.note_after)
    sdlc_claim._require_exact_task_postimage(fixture.intent, deadline_at=_open_deadline())

    assert attempts == [1, 2, 3, 4]


def test_a_claim_publishes_through_churn_at_every_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Every resolution's first attempt races a peer's write; each is retaken, the claim
    # applies, and no journal is left for recovery.
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)
    attempts = _churning_task_store(fixture.vault, monkeypatch, churn_on=lambda n: n % 2 == 1)
    monkeypatch.setattr(sdlc_claim, "_churn_sleep", lambda _seconds: None)

    sdlc_claim._apply_admitted_claim_publication_transaction(
        fixture.intent,
        active.consumption,
        transaction_root=fixture.transactions,
        receipt_root=tmp_path / "receipts",
        lock_root=fixture.locks,
        now=active.checked_at,
    )

    assert fixture.intent.note_path.read_bytes() == fixture.intent.note_after
    # two locked preflights and two postimage checks, each churned once, then retaken
    assert attempts == list(range(1, 9))
    states = [
        json.loads((journal / "manifest.json").read_text(encoding="utf-8"))["state"]
        for journal in fixture.transactions.iterdir()
        if (journal / "manifest.json").exists()
    ]
    assert states == ["applied"]


@pytest.mark.parametrize("holder", ["publication", "recovery"])
def test_each_lock_holder_gives_every_locked_resolution_one_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, holder: str
) -> None:
    # codex on #4829 round 3: the occupancy tests pass one deadline by hand, so they would miss
    # a lock holder that gave each phase a fresh one. This drives the real holders.
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)
    receipt_root = tmp_path / "receipts"
    seen: list[float | None] = []
    original = sdlc_claim.resolve_task_note_through_churn

    def recording(vault_root: Path, task_id: str, *, deadline_at: float | None = None) -> object:
        seen.append(deadline_at)
        return original(vault_root, task_id, deadline_at=deadline_at)

    def transaction() -> None:
        sdlc_claim._apply_admitted_claim_publication_transaction(
            fixture.intent,
            active.consumption,
            transaction_root=fixture.transactions,
            receipt_root=receipt_root,
            lock_root=fixture.locks,
            now=active.checked_at,
        )

    if holder == "recovery":
        # Leave the publication recovery_required at the receipt, as the recovery tests do.
        original_persist = sdlc_claim._persist_admitted_receipt

        def fail_receipt(*_args: object, **_kwargs: object) -> None:
            raise ClaimPublicationError("receipt_simulated", "retry", fixture.intent.task_id)

        monkeypatch.setattr(sdlc_claim, "_persist_admitted_receipt", fail_receipt)
        with pytest.raises(ClaimPublicationError):
            transaction()
        monkeypatch.setattr(sdlc_claim, "_persist_admitted_receipt", original_persist)
        monkeypatch.setattr(sdlc_claim, "resolve_task_note_through_churn", recording)
        recover_claim_publications(
            cache_dir=fixture.cache,
            transaction_root=fixture.transactions,
            receipt_root=receipt_root,
            lock_root=fixture.locks,
            task_id=fixture.intent.task_id,
        )
    else:
        monkeypatch.setattr(sdlc_claim, "resolve_task_note_through_churn", recording)
        transaction()

    # publication: two locked preflights and two postimage checks; recovery: its two postimage
    # checks (glm on #4829 round 4: a dropped locked resolution must turn this red)
    assert len(seen) == {"publication": 4, "recovery": 2}[holder]
    assert None not in seen  # every locked resolution got the holder's deadline
    assert len(set(seen)) == 1  # and it is one deadline, taken once per lock hold


# ── the cc-claim preflight, extracted and tested through churn (#4827 follow-up) ─
# claim-preflight-extract-churn-tested-20260927


def _prepare(fixture: ClaimFixture, *, note_before: bytes | None = None) -> ClaimPublicationIntent:
    return sdlc_claim.prepare_claim_publication_intent(
        note_path=fixture.intent.note_path,
        note_before=fixture.intent.note_before if note_before is None else note_before,
        note_after=fixture.intent.note_after,
        cache_dir=fixture.cache,
        binding=fixture.intent.binding,
    )


@pytest.mark.parametrize("point", sorted(_CHURN_POINTS))
def test_the_claim_preflight_retakes_transient_churn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, point: str
) -> None:
    # Discriminating where tests/scripts/test_cc_claim.py can only pin text: a preflight that
    # resolved bare would raise on the first attempt's churn.
    fixture = _fixture(tmp_path)
    attempts = _churning_task_store(
        fixture.vault, monkeypatch, point=point, churn_on=lambda n: n == 1
    )
    monkeypatch.setattr(sdlc_claim, "_churn_sleep", lambda _seconds: None)

    intent = _prepare(fixture)

    assert intent.intent_ref == fixture.intent.intent_ref
    assert attempts == [1, 2]


@pytest.mark.parametrize("point", sorted(_CHURN_POINTS))
def test_exhausted_churn_in_the_claim_preflight_names_the_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, point: str
) -> None:
    fixture = _fixture(tmp_path)
    _churning_task_store(fixture.vault, monkeypatch, point=point)
    monkeypatch.setattr(sdlc_claim, "_churn_sleep", lambda _seconds: None)

    with pytest.raises(ClaimPublicationError) as raised:
        _prepare(fixture)

    assert raised.value.reason_code == _CHURN_POINTS[point]
    assert raised.value.repair_action == sdlc_claim.TASK_FRONTIER_CHURN_NEXT_ACTION


def test_the_claim_preflight_still_refuses_a_changed_note(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    with pytest.raises(TaskStoreError) as raised:
        _prepare(fixture, note_before=fixture.intent.note_before + b"\n")

    assert raised.value.reason_code == "claim_publication_task_changed_during_preflight"


@pytest.mark.parametrize("point", sorted(_CHURN_POINTS))
@pytest.mark.parametrize(
    ("site", "reason"),
    [
        ("locked_preflight", "claim_publication_task_resolution_refused"),
        ("postimage", "claim_publication_task_projection_invalid"),
    ],
)
def test_exhausted_churn_under_the_lock_names_the_retry_not_a_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, point: str, site: str, reason: str
) -> None:
    # M180 class: the 19:52:40Z HOLD said "restore exactly one active task note" and then named
    # the Gate-0B composition receipt; churn is transient, so the action is a retry.
    fixture = _fixture(tmp_path)
    if site == "postimage":
        fixture.intent.note_path.write_bytes(fixture.intent.note_after)
    _churning_task_store(fixture.vault, monkeypatch, point=point)
    monkeypatch.setattr(sdlc_claim, "_churn_sleep", lambda _seconds: None)

    with pytest.raises(ClaimPublicationError) as raised:
        if site == "postimage":
            sdlc_claim._require_exact_task_postimage(fixture.intent, deadline_at=_open_deadline())
        else:
            sdlc_claim._locked_preflight(fixture.intent, (), deadline_at=_open_deadline())

    assert (raised.value.reason_code, raised.value.detail) == (reason, _CHURN_POINTS[point])
    assert raised.value.repair_action == sdlc_claim.TASK_FRONTIER_CHURN_NEXT_ACTION
    message = sdlc_claim.claim_publication_hold_message(raised.value, intent_ref="intent-x")
    assert sdlc_claim.TASK_FRONTIER_CHURN_NEXT_ACTION in message
    assert "Gate-0B" not in message
    assert "restore exactly one" not in message


def test_a_hold_that_is_not_churn_keeps_the_install_action() -> None:
    exc = ClaimPublicationError(
        "claim_publication_task_resolution_refused",
        "restore exactly one active task note and no closed duplicate",
        "task_note_cross_state_duplicate",
    )

    message = sdlc_claim.claim_publication_hold_message(exc, intent_ref="intent-x")

    assert "Gate-0B claim-publication composition receipt" in message
    assert sdlc_claim.TASK_FRONTIER_CHURN_NEXT_ACTION not in message


def test_retakes_under_one_lock_hold_share_one_budget_and_never_overrun_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # codex on #4829: per-site deadlines let each phase retake for the full budget, and a retake
    # could start just inside a deadline and run past it. Now one deadline per lock hold is
    # shared by every resolution under it, and a retake starts only if it can finish inside it.
    from shared.task_note_lock import DEFAULT_TIMEOUT_SECONDS

    budget = sdlc_claim._UNDER_LOCK_CHURN_BUDGET_SECONDS
    assert budget < sdlc_claim._CLAIM_PUBLICATION_LOCK_TIMEOUT_SECONDS
    assert budget < DEFAULT_TIMEOUT_SECONDS

    fixture = _fixture(tmp_path)
    attempts = _churning_task_store(fixture.vault, monkeypatch)  # churn never settles
    now = [0.0]
    resolution_seconds = 9.0  # measured 2026-09-27: 9.0-9.7 s over 5,767 rows
    original = sdlc_claim.resolve_task_note

    def timed_resolution(*args: object, **kwargs: object) -> object:
        now[0] += resolution_seconds
        return original(*args, **kwargs)  # type: ignore[arg-type]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    monkeypatch.setattr(sdlc_claim, "resolve_task_note", timed_resolution)
    monkeypatch.setattr(sdlc_claim, "_churn_clock", lambda: now[0])
    monkeypatch.setattr(sdlc_claim, "_churn_sleep", sleep)
    deadline = now[0] + budget  # taken once, as the lock holder does

    with pytest.raises(ClaimPublicationError):
        sdlc_claim._locked_preflight(fixture.intent, (), deadline_at=deadline)
    preflight_attempts = len(attempts)
    with pytest.raises(ClaimPublicationError):
        sdlc_claim._require_exact_task_postimage(fixture.intent, deadline_at=deadline)

    assert preflight_attempts == 2  # 9 s + pause + 9 s fits 25 s; a third would not
    assert len(attempts) == 3  # the postimage phase finds the shared budget spent: no retake
    baseline = 2 * resolution_seconds  # each phase's first resolution is not a retake
    assert now[0] - baseline <= budget  # retakes add at most the budget, pauses included


def test_a_slower_retake_overruns_by_at_most_its_excess_and_no_retake_follows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # codex on #4829 round 2: the fit check judges a retake by the attempt before it, and a
    # running resolution is not interrupted. The claim is narrowed to what holds: a slower
    # retake ends past the deadline by at most its excess, and no retake starts after it.
    budget = sdlc_claim._UNDER_LOCK_CHURN_BUDGET_SECONDS
    fixture = _fixture(tmp_path)
    attempts = _churning_task_store(fixture.vault, monkeypatch)  # churn never settles
    durations = iter([9.0, 20.0, 20.0, 20.0])  # the retake runs 11 s longer than it was judged
    now = [0.0]
    original = sdlc_claim.resolve_task_note

    def timed_resolution(*args: object, **kwargs: object) -> object:
        now[0] += next(durations)
        return original(*args, **kwargs)  # type: ignore[arg-type]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    monkeypatch.setattr(sdlc_claim, "resolve_task_note", timed_resolution)
    monkeypatch.setattr(sdlc_claim, "_churn_clock", lambda: now[0])
    monkeypatch.setattr(sdlc_claim, "_churn_sleep", sleep)
    deadline = now[0] + budget

    with pytest.raises(ClaimPublicationError):
        sdlc_claim._locked_preflight(fixture.intent, (), deadline_at=deadline)

    assert len(attempts) == 2  # the retake started (9 + pause + 9 fits); nothing after it
    assert now[0] > deadline  # the slower retake did end past the deadline
    assert (
        now[0] - deadline <= 20.0 - 9.0
    )  # by at most its excess over the attempt it was judged by


def test_an_oversleep_never_starts_a_retake_past_the_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # codex on #4829 round 5: the fit check ran before the backoff sleep only, so a sleep or a
    # scheduler that overshot its delay started a full resolution past the deadline.
    budget = sdlc_claim._UNDER_LOCK_CHURN_BUDGET_SECONDS
    fixture = _fixture(tmp_path)
    attempts = _churning_task_store(fixture.vault, monkeypatch)  # churn never settles
    now = [0.0]
    original = sdlc_claim.resolve_task_note

    def timed_resolution(*args: object, **kwargs: object) -> object:
        now[0] += 9.0
        return original(*args, **kwargs)  # type: ignore[arg-type]

    def oversleep(seconds: float) -> None:
        now[0] += seconds + 10.0  # the sleep returns 10 s late

    monkeypatch.setattr(sdlc_claim, "resolve_task_note", timed_resolution)
    monkeypatch.setattr(sdlc_claim, "_churn_clock", lambda: now[0])
    monkeypatch.setattr(sdlc_claim, "_churn_sleep", oversleep)
    deadline = now[0] + budget

    with pytest.raises(ClaimPublicationError):
        sdlc_claim._locked_preflight(fixture.intent, (), deadline_at=deadline)

    assert len(attempts) == 1  # the retake fit before the sleep, but not after it


@pytest.mark.parametrize(
    "exc",
    [
        TaskStoreError("task_store_frontier_changed_during_index_build", "retry", "delta"),
        ClaimPublicationError(
            "task_store_frontier_changed_since_index", sdlc_claim.TASK_FRONTIER_CHURN_NEXT_ACTION
        ),
    ],
    ids=["raw_task_store_error", "preflight_publication_error"],
)
def test_churn_carried_only_in_reason_code_names_the_retry(exc: Exception) -> None:
    # codex on #4829 round 5: the locked sites carry churn in `detail`, and those are tested;
    # a raw TaskStoreError, and the preflight's ClaimPublicationError, carry it in `reason_code`.
    message = sdlc_claim.claim_publication_hold_message(exc, intent_ref="intent-x")

    assert sdlc_claim.TASK_FRONTIER_CHURN_NEXT_ACTION in message
    assert "Gate-0B" not in message


# ── claim-publication phase observations in the coordination event log ───────
# claim-publication-lock-hold-under-peer-wait-20260927 (clause c), covering
# claim-recovery-manifest-records-store-reason-code-20260927


@pytest.fixture
def coord_ledger(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """This test's own coord tree, set explicitly (not left to the conftest), as its ledger path.

    A sibling of tmp_path, so tests that snapshot tmp_path see no new files.
    """
    coord = tmp_path_factory.mktemp("coord-ledger")
    monkeypatch.setenv("HAPAX_COORD_DIR", str(coord))
    return coord / "ledger.jsonl"


def _phase_observations(ledger: Path) -> list[dict[str, object]]:
    if not ledger.is_file():
        return []
    events = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    return [e for e in events if e["event_type"] == sdlc_claim.CLAIM_PUBLICATION_PHASE_OBSERVED]


def test_a_publication_emits_one_non_authoritative_observation_per_state(
    tmp_path: Path, coord_ledger: Path
) -> None:
    fixture = _applied_publication(tmp_path)

    observed = _phase_observations(coord_ledger)

    assert [e["payload"]["state"] for e in observed] == [
        "created",
        "projecting",
        "postimage_complete",
        "applied",
    ]
    stamps = [str(e["timestamp"]) for e in observed]
    assert stamps == sorted(stamps) and len(set(stamps)) == len(stamps)
    for event in observed:
        assert event["payload"]["authority"] == "non_authoritative_observation"
        assert event["payload"]["task_id"] == fixture.intent.task_id
        assert event["payload"]["role"] == fixture.intent.role
        assert event["subject"] == event["payload"]["publication_id"]
        assert event["payload"]["reason_code"] is None


def test_a_held_publication_observes_the_stores_own_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, coord_ledger: Path
) -> None:
    # The reason_code row's intent: a recovery_required journal names only the wrapper code, so
    # a churn hold was not attributable. The observation carries the store's reason.
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise ClaimPublicationError(
            "claim_publication_task_projection_invalid",
            sdlc_claim.TASK_FRONTIER_CHURN_NEXT_ACTION,
            "task_store_frontier_changed_during_index_build",
        )

    monkeypatch.setattr(sdlc_claim, "_persist_admitted_receipt", refuse)
    with pytest.raises(ClaimPublicationError):
        sdlc_claim._apply_admitted_claim_publication_transaction(
            fixture.intent,
            active.consumption,
            transaction_root=fixture.transactions,
            receipt_root=tmp_path / "receipts",
            lock_root=fixture.locks,
            now=active.checked_at,
        )

    held = _phase_observations(coord_ledger)[-1]["payload"]
    assert held["state"] == "recovery_required"
    assert held["reason_code"] == "claim_publication_task_projection_invalid"
    assert held["reason_detail"] == "task_store_frontier_changed_during_index_build"


@pytest.mark.parametrize(
    ("raised", "detail"),
    [
        (
            LifecycleTransitionError("projection_refused", "repair", "note:changed"),
            "projection_refused:note:changed",
        ),
        (RuntimeError("disk full"), "pre_activation_projection:RuntimeError"),
    ],
    ids=["lifecycle_transition_error", "generic_exception"],
)
def test_the_other_held_branches_observe_their_reasons(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    coord_ledger: Path,
    raised: Exception,
    detail: str,
) -> None:
    # glm on #4830: the LifecycleTransitionError and generic-exception branches of the
    # transaction also write recovery_required; each must observe its wrapped reason.
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise raised

    monkeypatch.setattr(sdlc_claim, "_apply_projections", refuse)
    with pytest.raises(ClaimPublicationError):
        sdlc_claim._apply_admitted_claim_publication_transaction(
            fixture.intent,
            active.consumption,
            transaction_root=fixture.transactions,
            receipt_root=tmp_path / "receipts",
            lock_root=fixture.locks,
            now=active.checked_at,
        )

    held = _phase_observations(coord_ledger)[-1]["payload"]
    assert held["state"] == "recovery_required"
    assert (held["reason_code"], held["reason_detail"]) == (
        "claim_publication_projection_failed",
        detail,
    )


def test_a_failing_emitter_leaves_the_publication_byte_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The unsafe case for a fail-open observation: it must never change a claim. With the event
    # log refusing, the publication still applies, and its manifest and receipt are exactly the
    # deterministic bytes the ownership proof re-derives.
    import shared.coord_event_log as coord_event_log

    def unavailable() -> object:
        raise RuntimeError("coord event log unavailable")

    monkeypatch.setattr(coord_event_log, "default_event_log", unavailable)
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)
    receipt_root = tmp_path / "receipts"

    sdlc_claim._apply_admitted_claim_publication_transaction(
        fixture.intent,
        active.consumption,
        transaction_root=fixture.transactions,
        receipt_root=receipt_root,
        lock_root=fixture.locks,
        now=active.checked_at,
    )

    publication_id = admitted_claim_publication_id(fixture.intent, active.consumption)
    manifest = fixture.transactions / publication_id / "manifest.json"
    _intent, projections, _id, state, _consumption = sdlc_claim._load_admitted_manifest(manifest)
    assert state == "applied"
    assert manifest.read_bytes() == sdlc_claim._admitted_manifest_bytes(
        fixture.intent, active.consumption, projections, publication_id, state="applied"
    )
    receipt = sdlc_claim.claim_publication_receipt_path(
        fixture.intent.cache_dir, fixture.intent.binding, receipt_root=receipt_root
    )
    assert receipt.read_bytes() == (
        sdlc_claim._canonical(
            sdlc_claim._admitted_receipt_record(
                fixture.intent, active.consumption, projections, publication_id
            )
        )
        + b"\n"
    )
    assert fixture.intent.note_path.read_bytes() == fixture.intent.note_after


# ── governed release of a held claim publication (M166, M167) ────────────────
# claim-cache-missing-governed-release-20260926


_RELEASE_STAMP = "20260927T010000Z"


def _held_publication(
    tmp_path: Path, *, edit_note: bool = True
) -> tuple[ClaimFixture, Path, tuple[object, ...]]:
    """A real admitted publication interrupted before its markers (the frontier-churn HOLD
    of M167), and then, unless ``edit_note`` is false, a legitimate note edit (M166)."""

    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)

    def interrupt(phase: str, _index: int | None) -> None:
        if phase == "before_activation_projection":
            raise RuntimeError("simulated HOLD after the note, epoch and dispatch")

    with pytest.raises(ClaimPublicationError):
        sdlc_claim._apply_admitted_claim_publication_transaction(
            fixture.intent,
            active.consumption,
            transaction_root=fixture.transactions,
            receipt_root=tmp_path / "receipts",
            lock_root=fixture.locks,
            now=active.checked_at,
            failure_hook=interrupt,
        )
    journal = fixture.transactions / admitted_claim_publication_id(
        fixture.intent, active.consumption
    )
    _intent, projections, _id, state, _consumption = sdlc_claim._load_admitted_manifest(
        journal / "manifest.json"
    )
    assert state == "recovery_required"
    if edit_note:
        note = fixture.intent.note_path
        note.write_bytes(note.read_bytes().replace(b"Body remains", b"Edited. Body remains"))
    return fixture, journal, projections


def _release_held(fixture: ClaimFixture) -> object:
    return sdlc_claim.release_claim_residue(
        vault_root=fixture.vault,
        cache_dir=fixture.cache,
        transaction_root=fixture.transactions,
        lock_root=fixture.locks,
        role="cx-red",
        task_id="task-alpha",
        observed_at=_RELEASE_STAMP,
    )


def _residue_projections(projections: tuple[object, ...]) -> list[object]:
    return [
        item
        for item in projections[:7]
        if item.path.name.startswith(("cc-claim-epoch-", "cc-claim-dispatch-"))
    ]


def test_release_quarantines_a_held_publication_and_archives_its_residue(
    tmp_path: Path,
) -> None:
    fixture, journal, projections = _held_publication(tmp_path)
    note_before = fixture.intent.note_path.read_bytes()
    residue = _residue_projections(projections)
    assert residue and all(item.path.read_bytes() == item.after for item in residue)

    released = _release_held(fixture)

    assert released.shape == "held_publication"
    assert not journal.exists()
    quarantined = journal.with_name(f"{journal.name}.quarantined-{_RELEASE_STAMP}")
    assert (quarantined / "manifest.json").is_file()
    assert fixture.intent.note_path.read_bytes() == note_before
    assert not any(item.path.exists() for item in residue)
    for item in residue:
        assert (released.archive_dir / item.path.name).read_bytes() == item.after
    assert released.archive_dir.parent == fixture.vault / "_lineage" / "task-alpha"
    # The quarantined journal is the completed remedy: recovery no longer holds on it.
    assert (
        recover_claim_publications(
            cache_dir=fixture.cache,
            transaction_root=fixture.transactions,
            lock_root=fixture.locks,
            task_id="task-alpha",
        )
        == ()
    )


def test_release_refuses_a_held_publication_that_recovery_can_still_finish(
    tmp_path: Path,
) -> None:
    fixture, journal, _projections = _held_publication(tmp_path, edit_note=False)
    before = (_tree_snapshot(fixture.cache), _tree_snapshot(fixture.transactions))

    with pytest.raises(sdlc_claim.ClaimResidueArchiveHold) as raised:
        _release_held(fixture)

    assert "claim_residue_recoverable" in raised.value.message
    assert (_tree_snapshot(fixture.cache), _tree_snapshot(fixture.transactions)) == before


def test_release_refuses_a_held_publication_with_a_live_marker(tmp_path: Path) -> None:
    fixture, _journal, projections = _held_publication(tmp_path)
    marker = next(item for item in projections[:7] if item.path.name.startswith("cc-active-task-"))
    marker.path.write_bytes(marker.after)
    before = (_tree_snapshot(fixture.cache), _tree_snapshot(fixture.transactions))

    with pytest.raises(sdlc_claim.ClaimResidueArchiveHold) as raised:
        _release_held(fixture)

    assert "claim_residue_live_marker" in raised.value.message
    assert (_tree_snapshot(fixture.cache), _tree_snapshot(fixture.transactions)) == before


def test_release_refuses_a_held_publication_whose_residue_differs(tmp_path: Path) -> None:
    fixture, _journal, projections = _held_publication(tmp_path)
    epoch = next(item for item in projections[:7] if item.path.name.startswith("cc-claim-epoch-"))
    epoch.path.write_bytes(b"1 task-alpha\n")
    before = (_tree_snapshot(fixture.cache), _tree_snapshot(fixture.transactions))

    with pytest.raises(sdlc_claim.ClaimResidueArchiveHold) as raised:
        _release_held(fixture)

    assert "claim_residue_hash_mismatch" in raised.value.message
    assert (_tree_snapshot(fixture.cache), _tree_snapshot(fixture.transactions)) == before


def test_release_refuses_a_held_publication_whose_admission_proof_drifted(
    tmp_path: Path,
) -> None:
    fixture, _journal, projections = _held_publication(tmp_path)
    proof = projections[7]
    proof.path.write_bytes(proof.after + b" ")
    before = (_tree_snapshot(fixture.cache), _tree_snapshot(fixture.transactions))

    with pytest.raises(sdlc_claim.ClaimResidueArchiveHold) as raised:
        _release_held(fixture)

    assert "claim_residue_projection_drift" in raised.value.message
    assert (_tree_snapshot(fixture.cache), _tree_snapshot(fixture.transactions)) == before


@pytest.mark.parametrize("content", ["task-alpha\n", "junk\ntask-alpha\n"], ids=["first", "later"])
def test_release_refuses_a_held_publication_while_another_session_holds_the_task(
    tmp_path: Path, content: str
) -> None:
    fixture, _journal, _projections = _held_publication(tmp_path)
    (fixture.cache / "cc-active-task-cx-red-session-xyz").write_text(content)
    before = (_tree_snapshot(fixture.cache), _tree_snapshot(fixture.transactions))

    with pytest.raises(sdlc_claim.ClaimResidueArchiveHold) as raised:
        _release_held(fixture)

    assert "claim_residue_live_marker" in raised.value.message
    assert (_tree_snapshot(fixture.cache), _tree_snapshot(fixture.transactions)) == before


def test_release_counts_an_unreadable_marker_as_a_live_claim(tmp_path: Path) -> None:
    # codex, #4801 round 2: a marker that cannot be decoded may name the task.
    fixture, _journal, _projections = _held_publication(tmp_path)
    unreadable = fixture.cache / "cc-active-task-cx-red-session-xyz"
    unreadable.write_bytes(b"\xff\xfe")
    before = (_tree_snapshot(fixture.cache), _tree_snapshot(fixture.transactions))

    with pytest.raises(sdlc_claim.ClaimResidueArchiveHold) as raised:
        _release_held(fixture)

    assert "claim_residue_live_marker" in raised.value.message
    assert f"inspect the marker at {unreadable}" in raised.value.message
    assert (_tree_snapshot(fixture.cache), _tree_snapshot(fixture.transactions)) == before


def test_release_touches_only_the_cache_its_journal_projected_into(tmp_path: Path) -> None:
    fixture, _journal, _projections = _held_publication(tmp_path)
    other_cache = tmp_path / "other-cache"
    other_cache.mkdir()
    before = (_tree_snapshot(fixture.cache), _tree_snapshot(fixture.transactions))

    with pytest.raises(sdlc_claim.ClaimResidueArchiveHold) as raised:
        sdlc_claim.release_claim_residue(
            vault_root=fixture.vault,
            cache_dir=other_cache,
            transaction_root=fixture.transactions,
            lock_root=fixture.locks,
            role="cx-red",
            task_id="task-alpha",
            observed_at=_RELEASE_STAMP,
        )

    assert "claim_residue_foreign_path" in raised.value.message
    assert (_tree_snapshot(fixture.cache), _tree_snapshot(fixture.transactions)) == before


class _Killed(BaseException):
    """A process kill: nothing after it runs, not even the journal's failure bookkeeping."""


def test_release_refuses_a_journal_that_is_unfinished_but_not_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_persist = sdlc_claim._persist_admitted_manifest_state

    def killed_before_recording_the_failure(*args: object, **kwargs: object) -> None:
        if kwargs.get("state") == "recovery_required":
            raise _Killed
        original_persist(*args, **kwargs)

    monkeypatch.setattr(
        sdlc_claim, "_persist_admitted_manifest_state", killed_before_recording_the_failure
    )
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)

    def interrupt(phase: str, _index: int | None) -> None:
        if phase == "before_activation_projection":
            raise RuntimeError("interrupted before the markers")

    with pytest.raises(_Killed):
        sdlc_claim._apply_admitted_claim_publication_transaction(
            fixture.intent,
            active.consumption,
            transaction_root=fixture.transactions,
            receipt_root=tmp_path / "receipts",
            lock_root=fixture.locks,
            now=active.checked_at,
            failure_hook=interrupt,
        )
    monkeypatch.setattr(sdlc_claim, "_persist_admitted_manifest_state", original_persist)
    note = fixture.intent.note_path
    note.write_bytes(note.read_bytes().replace(b"Body remains", b"Edited. Body remains"))
    before = (_tree_snapshot(fixture.cache), _tree_snapshot(fixture.transactions))

    with pytest.raises(sdlc_claim.ClaimResidueArchiveHold) as raised:
        _release_held(fixture)

    assert "claim_residue_journal_not_held" in raised.value.message
    assert (_tree_snapshot(fixture.cache), _tree_snapshot(fixture.transactions)) == before


def test_release_refuses_a_stamp_outside_the_quarantine_grammar(tmp_path: Path) -> None:
    fixture, journal, _projections = _held_publication(tmp_path)

    with pytest.raises(sdlc_claim.ClaimResidueArchiveHold) as raised:
        sdlc_claim.release_claim_residue(
            vault_root=fixture.vault,
            cache_dir=fixture.cache,
            transaction_root=fixture.transactions,
            lock_root=fixture.locks,
            role="cx-red",
            task_id="task-alpha",
            observed_at="2026-09-27 01:00",
        )

    assert "claim_residue_stamp_invalid" in raised.value.message
    assert journal.exists()


def test_release_of_a_held_publication_finishes_after_an_interrupted_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A crash after the first file is archived; the rerun counts it as released, because the
    # lineage holds exactly its after-image, archives the rest, and quarantines the journal.
    fixture, journal, projections = _held_publication(tmp_path)
    real_archive = sdlc_claim._archive_verified
    calls = {"n": 0}

    def killed_after_first(*args: object, **kwargs: object) -> Path:
        calls["n"] += 1
        if calls["n"] == 2:
            raise _Killed
        return real_archive(*args, **kwargs)

    monkeypatch.setattr(sdlc_claim, "_archive_verified", killed_after_first)
    with pytest.raises(_Killed):
        _release_held(fixture)
    monkeypatch.setattr(sdlc_claim, "_archive_verified", real_archive)
    assert journal.exists()

    released = sdlc_claim.release_claim_residue(
        vault_root=fixture.vault,
        cache_dir=fixture.cache,
        transaction_root=fixture.transactions,
        lock_root=fixture.locks,
        role="cx-red",
        task_id="task-alpha",
        observed_at="20260927T010500Z",
    )

    assert released.shape == "held_publication"
    assert not journal.exists()
    assert not any(item.path.exists() for item in _residue_projections(projections))


def test_release_refuses_a_held_publication_missing_a_residue_file_never_archived(
    tmp_path: Path,
) -> None:
    # codex, #4801 round 1: absent is not "at the after-image". Only an earlier release's
    # archive of exactly those bytes makes an absent file count as released.
    fixture, _journal, projections = _held_publication(tmp_path)
    _residue_projections(projections)[0].path.unlink()
    before = (_tree_snapshot(fixture.cache), _tree_snapshot(fixture.transactions))

    with pytest.raises(sdlc_claim.ClaimResidueArchiveHold) as raised:
        _release_held(fixture)

    assert "claim_residue_projection_missing" in raised.value.message
    assert (_tree_snapshot(fixture.cache), _tree_snapshot(fixture.transactions)) == before


def test_a_sidecar_rewritten_during_the_release_is_never_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # codex, #4801 round 1: a rewrite between the check and the removal must not be lost.
    fixture, journal, projections = _held_publication(tmp_path)
    target = _residue_projections(projections)[0].path
    real_rename = os.rename

    def rewrite_then_rename(src: object, dst: object, *args: object, **kwargs: object) -> None:
        if Path(src) == target:
            target.write_bytes(b"rewritten by a concurrent claim\n")
        real_rename(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "rename", rewrite_then_rename)
    with pytest.raises(sdlc_claim.ClaimResidueArchiveHold) as raised:
        _release_held(fixture)
    monkeypatch.setattr(os, "rename", real_rename)

    # Nothing is lost and nothing is unlinked: the rewritten bytes are the moved original in
    # the cache staging directory and the lineage keeps a verified copy flagged as differing.
    rewritten = b"rewritten by a concurrent claim\n"
    assert "claim_residue_live_differed" in raised.value.message
    staged = (
        fixture.cache / "claim-residue-release" / "task-alpha" / f"{_RELEASE_STAMP}-cx-red"
    ) / target.name
    archive = (
        fixture.vault / "_lineage" / "task-alpha" / f"claim-residue-release-{_RELEASE_STAMP}-cx-red"
    )
    assert staged.read_bytes() == rewritten
    assert (archive / f"{target.name}.live-differed-from-journal").read_bytes() == rewritten
    assert "live differed from journal" in (archive / "README.md").read_text(encoding="utf-8")
    assert not (archive / target.name).exists()  # the journal's image is never archived for it
    assert journal.exists()  # the release stopped before the quarantine


def test_release_refuses_an_archive_name_already_taken(tmp_path: Path) -> None:
    fixture, _journal, projections = _held_publication(tmp_path)
    first = _residue_projections(projections)[0]
    taken = (
        fixture.vault
        / "_lineage"
        / "task-alpha"
        / f"claim-residue-release-{_RELEASE_STAMP}-cx-red"
        / first.path.name
    )
    taken.parent.mkdir(parents=True)
    taken.write_bytes(b"an earlier file\n")
    before = (_tree_snapshot(fixture.cache), _tree_snapshot(fixture.transactions))

    with pytest.raises(sdlc_claim.ClaimResidueArchiveHold) as raised:
        _release_held(fixture)

    assert "claim_residue_archive_collision" in raised.value.message
    assert taken.read_bytes() == b"an earlier file\n"
    assert (_tree_snapshot(fixture.cache), _tree_snapshot(fixture.transactions)) == before


def test_release_refuses_when_the_quarantine_name_is_taken(tmp_path: Path) -> None:
    fixture, journal, _projections = _held_publication(tmp_path)
    journal.with_name(f"{journal.name}.quarantined-{_RELEASE_STAMP}").mkdir()
    before = (_tree_snapshot(fixture.cache), _tree_snapshot(fixture.transactions))

    with pytest.raises(sdlc_claim.ClaimResidueArchiveHold) as raised:
        _release_held(fixture)

    assert "claim_residue_quarantine_exists" in raised.value.message
    assert (_tree_snapshot(fixture.cache), _tree_snapshot(fixture.transactions)) == before


# ── #4801 round-3 residuals (claim-plane-self-resume-own-lapsed-row-20260927 (5), (6)) ──


def test_a_rerun_finishes_the_archive_from_its_own_staged_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # (5): a crash between the staging rename and the lineage copy leaves the moved original
    # only in the cache staging directory; the rerun recognises it and completes the archive.
    fixture, journal, projections = _held_publication(tmp_path)
    first = _residue_projections(projections)[0]

    def killed_before_the_copy(*_args: object, **_kwargs: object) -> None:
        raise _Killed

    monkeypatch.setattr(sdlc_claim, "_copy_verified", killed_before_the_copy)
    with pytest.raises(_Killed):
        _release_held(fixture)
    monkeypatch.undo()
    assert not first.path.exists()

    released = sdlc_claim.release_claim_residue(
        vault_root=fixture.vault,
        cache_dir=fixture.cache,
        transaction_root=fixture.transactions,
        lock_root=fixture.locks,
        role="cx-red",
        task_id="task-alpha",
        observed_at="20260927T010500Z",
    )

    assert released.shape == "held_publication"
    assert not journal.exists()
    assert (released.archive_dir / first.path.name).read_bytes() == first.after


def test_a_file_archived_earlier_counts_after_its_staged_copy_is_gone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The lineage copy alone proves an earlier release, once the cache staging is cleaned.
    fixture, journal, projections = _held_publication(tmp_path)
    real_archive = sdlc_claim._archive_verified
    calls = {"n": 0}

    def killed_after_first(*args: object, **kwargs: object) -> Path:
        calls["n"] += 1
        if calls["n"] == 2:
            raise _Killed
        return real_archive(*args, **kwargs)

    monkeypatch.setattr(sdlc_claim, "_archive_verified", killed_after_first)
    with pytest.raises(_Killed):
        _release_held(fixture)
    monkeypatch.undo()
    for staged in (fixture.cache / "claim-residue-release").rglob("cc-claim-*"):
        staged.rename(tmp_path / f"cleaned-{staged.name}")  # the cache staging was cleaned

    released = sdlc_claim.release_claim_residue(
        vault_root=fixture.vault,
        cache_dir=fixture.cache,
        transaction_root=fixture.transactions,
        lock_root=fixture.locks,
        role="cx-red",
        task_id="task-alpha",
        observed_at="20260927T010500Z",
    )

    assert released.shape == "held_publication"
    assert not journal.exists()


def test_an_earlier_archive_of_another_publication_does_not_count(tmp_path: Path) -> None:
    # (6): the same file name and bytes under another publication's release prove nothing.
    fixture, _journal, projections = _held_publication(tmp_path)
    first = _residue_projections(projections)[0]
    first.path.unlink()
    lineage = fixture.vault / "_lineage" / "task-alpha"
    other = lineage / "claim-residue-release-20260101T000000Z-cx-red"
    other.mkdir(parents=True)
    (other / first.path.name).write_bytes(first.after)
    (other / "README.md").write_text(f"publication_id: claim-pub-{'0' * 64}\n", encoding="utf-8")
    before = (_tree_snapshot(fixture.cache), _tree_snapshot(fixture.transactions))

    with pytest.raises(sdlc_claim.ClaimResidueArchiveHold) as raised:
        _release_held(fixture)

    assert "claim_residue_projection_missing" in raised.value.message
    assert (_tree_snapshot(fixture.cache), _tree_snapshot(fixture.transactions)) == before


def test_a_same_stamp_rerun_keeps_its_own_earlier_readme(tmp_path: Path) -> None:
    # Neither overwritten nor duplicated: a same-stamp rerun reuses its own journal's README.
    fixture, journal, _projections = _held_publication(tmp_path)
    lineage = fixture.vault / "_lineage" / "task-alpha"
    archive = lineage / f"claim-residue-release-{_RELEASE_STAMP}-cx-red"
    archive.mkdir(parents=True)
    earlier = f"an earlier run\npublication_id: {journal.name}\n"
    (archive / "README.md").write_text(earlier, encoding="utf-8")

    _release_held(fixture)

    assert (archive / "README.md").read_text(encoding="utf-8") == earlier


@pytest.mark.parametrize(
    "readme",
    [f"publication_id: claim-pub-{'0' * 64}\n", "an earlier run with no publication_id\n"],
    ids=["another-publication", "no-publication"],
)
def test_a_same_stamp_rerun_refuses_a_readme_of_another_or_no_publication(
    tmp_path: Path, readme: str
) -> None:
    # #4804 round 2 (codex critical): never archive under a receipt that is not this journal's.
    fixture, _journal, _projections = _held_publication(tmp_path)
    lineage = fixture.vault / "_lineage" / "task-alpha"
    archive = lineage / f"claim-residue-release-{_RELEASE_STAMP}-cx-red"
    archive.mkdir(parents=True)
    (archive / "README.md").write_text(readme, encoding="utf-8")
    before = (_tree_snapshot(fixture.cache), _tree_snapshot(fixture.transactions))

    with pytest.raises(sdlc_claim.ClaimResidueArchiveHold) as raised:
        _release_held(fixture)

    assert "claim_residue_archive_collision" in raised.value.message
    assert (_tree_snapshot(fixture.cache), _tree_snapshot(fixture.transactions)) == before


def _applied_publication(tmp_path: Path) -> ClaimFixture:
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)
    sdlc_claim._apply_admitted_claim_publication_transaction(
        fixture.intent,
        active.consumption,
        transaction_root=fixture.transactions,
        receipt_root=tmp_path / "receipts",
        lock_root=fixture.locks,
        now=active.checked_at,
    )
    return fixture


@pytest.mark.parametrize(
    ("assignment", "reassigned"),
    [
        (None, False),
        ("assigned_to:", False),
        ("assigned_to: cx-red  # still mine", False),
        ("assigned_to: cx-other", True),
        ("assigned_to: unassigned", True),
    ],
    ids=["absent", "empty", "own-role-with-comment", "other-role", "unassigned"],
)
def test_only_an_explicit_other_assignment_releases_live_markers(
    tmp_path: Path, assignment: str | None, reassigned: bool
) -> None:
    # #4804 round 4 (codex critical): an absent, empty or commented own assignment is no proof.
    fixture = _applied_publication(tmp_path)
    note = fixture.intent.note_path
    lines = [line for line in note.read_text().splitlines() if not line.startswith("assigned_to:")]
    if assignment is not None:
        lines.insert(3, assignment)
    note.write_text("\n".join(lines) + "\n")
    if reassigned:
        assert _release_held(fixture).shape == "reassigned_task"
        return
    before = _tree_snapshot(fixture.cache)
    with pytest.raises(sdlc_claim.ClaimResidueArchiveHold) as raised:
        _release_held(fixture)
    assert "claim_residue_live_marker" in raised.value.message
    assert _tree_snapshot(fixture.cache) == before


def test_a_same_stamp_rerun_finishes_from_its_own_staged_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # #4804 round 4 (codex): the crashed run's staged original does not collide with its rerun.
    fixture, journal, projections = _held_publication(tmp_path)

    def killed_before_the_copy(*_args: object, **_kwargs: object) -> None:
        raise _Killed

    monkeypatch.setattr(sdlc_claim, "_copy_verified", killed_before_the_copy)
    with pytest.raises(_Killed):
        _release_held(fixture)
    monkeypatch.undo()

    assert _release_held(fixture).shape == "held_publication"
    assert not journal.exists()


def test_the_applied_path_refuses_another_journals_staged_copy(tmp_path: Path) -> None:
    # #4804 round 4 (glm, claude): the applied path's staged rejection, pinned on its own.
    fixture = _applied_publication(tmp_path)
    for marker in fixture.cache.glob("cc-active-task-cx-red*"):
        marker.unlink()
    epoch = next(fixture.cache.glob("cc-claim-epoch-cx-red"))
    content, mode = epoch.read_bytes(), stat.S_IMODE(epoch.stat().st_mode)
    epoch.unlink()
    staging = fixture.cache / "claim-residue-release" / "task-alpha" / "20260101T000000Z-cx-red"
    staging.mkdir(parents=True)
    (staging / "PUBLICATION").write_text(f"claim-pub-{'0' * 64}\n", encoding="ascii")
    (staging / epoch.name).write_bytes(content)
    os.chmod(staging / epoch.name, mode)
    before = _tree_snapshot(fixture.cache)

    with pytest.raises(sdlc_claim.ClaimResidueArchiveHold) as raised:
        _release_held(fixture)

    assert "claim_residue_projection_missing" in raised.value.message
    assert _tree_snapshot(fixture.cache) == before


@pytest.mark.parametrize("damaged", ["README", "PUBLICATION"])
def test_an_unreadable_binding_is_a_collision_not_a_crash(tmp_path: Path, damaged: str) -> None:
    # #4804 round 3 (codex): a damaged README or staging binding holds with the named reason.
    fixture, _journal, _projections = _held_publication(tmp_path)
    if damaged == "README":
        target = (
            fixture.vault
            / "_lineage"
            / "task-alpha"
            / f"claim-residue-release-{_RELEASE_STAMP}-cx-red"
            / "README.md"
        )
    else:
        target = (
            fixture.cache
            / "claim-residue-release"
            / "task-alpha"
            / f"{_RELEASE_STAMP}-cx-red"
            / "PUBLICATION"
        )
    target.parent.mkdir(parents=True)
    target.write_bytes(b"\xff\xfe undecodable")
    before = (_tree_snapshot(fixture.cache), _tree_snapshot(fixture.transactions))

    with pytest.raises(sdlc_claim.ClaimResidueArchiveHold) as raised:
        _release_held(fixture)

    assert "claim_residue_archive_collision" in raised.value.message
    assert (_tree_snapshot(fixture.cache), _tree_snapshot(fixture.transactions)) == before


def test_a_staging_directory_bound_to_another_publication_holds_before_any_move(
    tmp_path: Path,
) -> None:
    # #4804 round 2 (claude): the staging-binding collision, pinned.
    fixture, _journal, _projections = _held_publication(tmp_path)
    staging = fixture.cache / "claim-residue-release" / "task-alpha" / f"{_RELEASE_STAMP}-cx-red"
    staging.mkdir(parents=True)
    (staging / "PUBLICATION").write_text(f"claim-pub-{'0' * 64}\n", encoding="ascii")
    trees = (fixture.cache, fixture.transactions, fixture.vault / "_lineage")
    before = tuple(_tree_snapshot(tree) for tree in trees)

    with pytest.raises(sdlc_claim.ClaimResidueArchiveHold) as raised:
        _release_held(fixture)

    assert "claim_residue_archive_collision" in raised.value.message
    assert tuple(_tree_snapshot(tree) for tree in trees) == before


def _staged_copy(
    fixture: ClaimFixture, publication_id: str, projection: object, content: bytes
) -> None:
    staging = fixture.cache / "claim-residue-release" / "task-alpha" / "20260101T000000Z-cx-red"
    staging.mkdir(parents=True)
    (staging / "PUBLICATION").write_text(f"{publication_id}\n", encoding="utf-8")
    staged = staging / projection.path.name
    staged.write_bytes(content)
    os.chmod(staged, projection.after_mode)


@pytest.mark.parametrize(
    "case",
    ["another-journal-same-bytes", "this-journal-other-bytes"],
    ids=["revert-of-another-journal", "rejection-path"],
)
def test_a_staged_file_of_another_journal_or_with_other_bytes_is_not_recovered(
    tmp_path: Path, case: str
) -> None:
    # #4804 round 1 (codex critical; gemini): a staged original must be this journal's own.
    # Another journal's staging with byte-identical content (a revert) proves nothing.
    fixture, journal, projections = _held_publication(tmp_path)
    first = _residue_projections(projections)[0]
    first.path.unlink()
    if case == "another-journal-same-bytes":
        _staged_copy(fixture, f"claim-pub-{'0' * 64}", first, first.after)
    else:
        _staged_copy(fixture, journal.name, first, first.after + b" ")
    before = (_tree_snapshot(fixture.cache), _tree_snapshot(fixture.transactions))

    with pytest.raises(sdlc_claim.ClaimResidueArchiveHold) as raised:
        _release_held(fixture)

    assert "claim_residue_projection_missing" in raised.value.message
    assert (_tree_snapshot(fixture.cache), _tree_snapshot(fixture.transactions)) == before


def test_an_applied_release_finishes_from_its_own_staged_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # #4804 round 1 (claude, codex): the applied (lapsed-lease) path's crash-window recovery.
    fixture = _fixture(tmp_path)
    active = _active_admission_fixture(tmp_path, fixture)
    sdlc_claim._apply_admitted_claim_publication_transaction(
        fixture.intent,
        active.consumption,
        transaction_root=fixture.transactions,
        receipt_root=tmp_path / "receipts",
        lock_root=fixture.locks,
        now=active.checked_at,
    )
    for marker in fixture.cache.glob("cc-active-task-cx-red*"):
        marker.unlink()  # the lease lapsed
    root = fixture.cache / "claim-residue-release" / "task-alpha"
    (root / "19990101T000000Z-cx-red").mkdir(parents=True)  # a stale, empty staging directory
    (root / "stray-file").write_text("not a directory\n", encoding="utf-8")

    def killed_before_the_copy(*_args: object, **_kwargs: object) -> None:
        raise _Killed

    monkeypatch.setattr(sdlc_claim, "_copy_verified", killed_before_the_copy)
    with pytest.raises(_Killed):
        _release_held(fixture)
    monkeypatch.undo()

    released = sdlc_claim.release_claim_residue(
        vault_root=fixture.vault,
        cache_dir=fixture.cache,
        transaction_root=fixture.transactions,
        lock_root=fixture.locks,
        role="cx-red",
        task_id="task-alpha",
        observed_at="20260927T010500Z",
    )

    assert released.shape == "lapsed_lease"
    assert not any(fixture.cache.glob("cc-claim-*-cx-red*"))
    assert len(released.archived) == 4


def _two_applied_claims_for_one_task(
    tmp_path: Path,
    *,
    successor_session: str = "session-next",
) -> tuple[ClaimFixture, sdlc_claim.ClaimPublicationReceipt, sdlc_claim.ClaimPublicationReceipt]:
    """Two receipt-backed publications, with a governed same-owner note advance between them."""

    fixture = _fixture(tmp_path)
    (tmp_path / "first-proof").mkdir()
    first_admission = _active_admission_fixture(tmp_path / "first-proof", fixture)
    first = sdlc_claim._apply_admitted_claim_publication_transaction(
        fixture.intent,
        first_admission.consumption,
        transaction_root=fixture.transactions,
        receipt_root=tmp_path / "receipts",
        lock_root=fixture.locks,
        now=first_admission.checked_at,
    )
    fixture.intent.note_path.write_bytes(
        fixture.intent.note_path.read_bytes().replace(b"status: claimed", b"status: pr_open")
        + b"\n- 2026-07-11T12:01:00Z cx-red linked its PR.\n"
    )
    for projection in sdlc_claim._projections(fixture.intent)[1:7]:
        if successor_session == "session-abc" or projection.path.stem.endswith("cx-red"):
            projection.path.unlink()
    old = fixture.intent.binding
    successor_binding = ClaimDispatchBinding.create(
        task_id=old.task_id,
        lane=old.lane,
        session_id=successor_session,
        claim_epoch=old.claim_epoch + 1,
        dispatch_message_id="dispatch-msg-next",
        platform=old.platform,
        mode=old.mode,
        profile=old.profile,
        authority_case=old.authority_case,
        binding_hash="b" * 64,
        coord_dispatch_idempotency_key="coord-dispatch-next",
    )
    task = resolve_task_note(fixture.vault, fixture.intent.task_id)
    successor_intent = ClaimPublicationIntent.create(
        task=task,
        cache_dir=fixture.cache,
        note_after=task.content + b"\n- 2026-07-11T12:02:00Z cx-red resumed.\n",
        binding=successor_binding,
    )
    successor_fixture = replace(fixture, intent=successor_intent)
    (tmp_path / "next-proof").mkdir()
    successor_admission = _active_admission_fixture(tmp_path / "next-proof", successor_fixture)
    successor = sdlc_claim._apply_admitted_claim_publication_transaction(
        successor_intent,
        successor_admission.consumption,
        transaction_root=fixture.transactions,
        receipt_root=first.receipt_path.parent,
        lock_root=fixture.locks,
        now=successor_admission.checked_at,
    )
    return fixture, first, successor


def test_recovery_recognizes_receipt_bound_applied_successor_without_replaying_predecessor(
    tmp_path: Path,
) -> None:
    fixture, predecessor, successor = _two_applied_claims_for_one_task(tmp_path)
    before = _tree_snapshot(tmp_path)

    results = recover_claim_publications(
        cache_dir=fixture.cache,
        transaction_root=fixture.transactions,
        receipt_root=predecessor.receipt_path.parent,
        lock_root=fixture.locks,
        task_id=fixture.intent.task_id,
    )

    states = {item.publication_id: (item.state, item.reason_code) for item in results}
    assert states == {
        predecessor.publication_id: (
            "superseded",
            "claim_publication_superseded_by_later_applied",
        ),
        successor.publication_id: ("applied", None),
    }
    assert _tree_snapshot(tmp_path) == before


@pytest.mark.parametrize("corrupt", ["predecessor", "successor"])
def test_recovery_does_not_accept_an_unverified_applied_receipt(
    tmp_path: Path, corrupt: str
) -> None:
    fixture, predecessor, successor = _two_applied_claims_for_one_task(tmp_path)
    (predecessor if corrupt == "predecessor" else successor).receipt_path.write_bytes(b"{}\n")
    before = _tree_snapshot(tmp_path)

    results = recover_claim_publications(
        cache_dir=fixture.cache,
        transaction_root=fixture.transactions,
        receipt_root=predecessor.receipt_path.parent,
        lock_root=fixture.locks,
        task_id=fixture.intent.task_id,
    )

    older = next(item for item in results if item.publication_id == predecessor.publication_id)
    assert older.state == "hold"
    assert older.reason_code == (
        "claim_publication_receipt_malformed"
        if corrupt == "predecessor"
        else "claim_publication_postimage_drift"
    )
    assert _tree_snapshot(tmp_path) == before


def test_recovery_does_not_hide_a_damaged_predecessor_session_lease(tmp_path: Path) -> None:
    fixture, predecessor, _successor = _two_applied_claims_for_one_task(tmp_path)
    old_session_epoch = fixture.cache / "cc-claim-epoch-cx-red-session-abc"
    old_session_epoch.write_bytes(old_session_epoch.read_bytes() + b"tampered\n")
    before = _tree_snapshot(tmp_path)

    results = recover_claim_publications(
        cache_dir=fixture.cache,
        transaction_root=fixture.transactions,
        receipt_root=predecessor.receipt_path.parent,
        lock_root=fixture.locks,
        task_id=fixture.intent.task_id,
    )

    older = next(item for item in results if item.publication_id == predecessor.publication_id)
    assert (older.state, older.reason_code) == ("hold", "claim_publication_postimage_drift")
    assert _tree_snapshot(tmp_path) == before


def _governed_release_fixture(tmp_path: Path):
    fixture = _fixture(tmp_path)
    admission = _active_admission_fixture(tmp_path, fixture)
    receipt = sdlc_claim._apply_admitted_claim_publication_transaction(
        fixture.intent,
        admission.consumption,
        transaction_root=fixture.transactions,
        receipt_root=tmp_path / "receipts",
        lock_root=fixture.locks,
        now=admission.checked_at,
    )
    fixture.intent.note_path.write_bytes(
        fixture.intent.note_path.read_bytes().replace(
            b"status: claimed", b"status: ready_for_review"
        )
    )
    released = sdlc_claim.release_claim_residue(
        vault_root=fixture.vault,
        cache_dir=fixture.cache,
        transaction_root=fixture.transactions,
        lock_root=fixture.locks,
        role=fixture.intent.role,
        task_id=fixture.intent.task_id,
        observed_at="20260928T180000Z",
    )
    assert released.shape == "pipeline_held"
    return fixture, receipt, released


def test_recovery_treats_a_verified_governed_release_as_terminal_history(tmp_path: Path) -> None:
    fixture, receipt, released = _governed_release_fixture(tmp_path)
    before = _tree_snapshot(tmp_path)

    (result,) = recover_claim_publications(
        cache_dir=fixture.cache,
        transaction_root=fixture.transactions,
        receipt_root=receipt.receipt_path.parent,
        lock_root=fixture.locks,
        task_id=fixture.intent.task_id,
    )

    assert (result.state, result.reason_code) == (
        "released",
        "claim_publication_released_by_governed_archive",
    )
    assert result.release is not None
    assert result.release.archive_path == released.archive_dir
    assert result.release.receipt_hash == receipt.receipt_hash
    assert _tree_snapshot(tmp_path) == before


@pytest.mark.parametrize("target", ["epoch", "activation", "readme"])
def test_recovery_holds_a_release_whose_archive_was_changed(tmp_path: Path, target: str) -> None:
    fixture, receipt, released = _governed_release_fixture(tmp_path)
    if target == "readme":
        archived = released.archive_dir / "README.md"
    else:
        prefix = "cc-claim-epoch-" if target == "epoch" else "cc-active-task-"
        archived = next(path for path in released.archived if path.name.startswith(prefix))
    archived.write_bytes(archived.read_bytes() + b"tampered\n")
    before = _tree_snapshot(tmp_path)

    (result,) = recover_claim_publications(
        cache_dir=fixture.cache,
        transaction_root=fixture.transactions,
        receipt_root=receipt.receipt_path.parent,
        lock_root=fixture.locks,
        task_id=fixture.intent.task_id,
    )

    assert (result.state, result.reason_code) == ("hold", "claim_publication_postimage_drift")
    assert _tree_snapshot(tmp_path) == before


def test_recovery_keeps_a_predecessor_settled_after_its_successor_is_released(
    tmp_path: Path,
) -> None:
    fixture, predecessor, successor = _two_applied_claims_for_one_task(
        tmp_path, successor_session="session-abc"
    )
    fixture.intent.note_path.write_bytes(
        fixture.intent.note_path.read_bytes().replace(
            b"status: pr_open", b"status: ready_for_review"
        )
    )
    released = sdlc_claim.release_claim_residue(
        vault_root=fixture.vault,
        cache_dir=fixture.cache,
        transaction_root=fixture.transactions,
        lock_root=fixture.locks,
        role=fixture.intent.role,
        task_id=fixture.intent.task_id,
        observed_at="20260928T180200Z",
    )
    assert released.publication_id == successor.publication_id
    before = _tree_snapshot(tmp_path)

    results = recover_claim_publications(
        cache_dir=fixture.cache,
        transaction_root=fixture.transactions,
        receipt_root=predecessor.receipt_path.parent,
        lock_root=fixture.locks,
        task_id=fixture.intent.task_id,
    )

    assert {result.publication_id: result.state for result in results} == {
        predecessor.publication_id: "superseded",
        successor.publication_id: "released",
    }
    assert _tree_snapshot(tmp_path) == before


def _publish_third_claim(
    tmp_path: Path,
    fixture: ClaimFixture,
    first: sdlc_claim.ClaimPublicationReceipt,
    second: sdlc_claim.ClaimPublicationReceipt,
    *,
    same_epoch: bool = False,
    session_id: str = "session-third",
) -> sdlc_claim.ClaimPublicationReceipt:
    for projection in sdlc_claim._projections(fixture.intent)[1:7]:
        if projection.path.stem.endswith("cx-red") and projection.path.exists():
            projection.path.unlink()
    second_intent = sdlc_claim._load_admitted_manifest(
        fixture.transactions / second.publication_id / "manifest.json"
    )[0]
    old = second_intent.binding
    third_binding = ClaimDispatchBinding.create(
        task_id=old.task_id,
        lane=old.lane,
        session_id=session_id,
        claim_epoch=old.claim_epoch if same_epoch else old.claim_epoch + 1,
        dispatch_message_id="dispatch-msg-third",
        platform=old.platform,
        mode=old.mode,
        profile=old.profile,
        authority_case=old.authority_case,
        binding_hash="c" * 64,
        coord_dispatch_idempotency_key="coord-dispatch-third",
    )
    task = resolve_task_note(fixture.vault, fixture.intent.task_id)
    third_intent = ClaimPublicationIntent.create(
        task=task,
        cache_dir=fixture.cache,
        note_after=task.content + b"\n- 2026-07-11T12:03:00Z cx-red resumed again.\n",
        binding=third_binding,
    )
    (tmp_path / "third-proof").mkdir()
    admission = _active_admission_fixture(
        tmp_path / "third-proof", replace(fixture, intent=third_intent)
    )
    return sdlc_claim._apply_admitted_claim_publication_transaction(
        third_intent,
        admission.consumption,
        transaction_root=fixture.transactions,
        receipt_root=first.receipt_path.parent,
        lock_root=fixture.locks,
        now=admission.checked_at,
    )


def test_recovery_holds_competing_earliest_successor_receipts(tmp_path: Path) -> None:
    fixture, first, second = _two_applied_claims_for_one_task(
        tmp_path, successor_session="session-abc"
    )
    note = fixture.intent.note_path
    note.write_bytes(note.read_bytes().replace(b"status: pr_open", b"status: ready_for_review"))
    released = sdlc_claim.release_claim_residue(
        vault_root=fixture.vault,
        cache_dir=fixture.cache,
        transaction_root=fixture.transactions,
        lock_root=fixture.locks,
        role=fixture.intent.role,
        task_id=fixture.intent.task_id,
        observed_at="20260928T180300Z",
    )
    assert released.publication_id == second.publication_id
    note.write_bytes(note.read_bytes().replace(b"status: ready_for_review", b"status: pr_open"))
    third = _publish_third_claim(
        tmp_path, fixture, first, second, same_epoch=True, session_id="session-abc"
    )
    before = _tree_snapshot(tmp_path)

    results = recover_claim_publications(
        cache_dir=fixture.cache,
        transaction_root=fixture.transactions,
        receipt_root=first.receipt_path.parent,
        lock_root=fixture.locks,
        task_id=fixture.intent.task_id,
    )

    older = next(item for item in results if item.publication_id == first.publication_id)
    assert (older.state, older.reason_code) == (
        "hold",
        "claim_publication_successor_ambiguous",
    )
    assert third.publication_id != second.publication_id
    assert _tree_snapshot(tmp_path) == before


def test_recovery_holds_two_verified_release_archives(tmp_path: Path) -> None:
    fixture, receipt, released = _governed_release_fixture(tmp_path)
    old_stamp, new_stamp = "20260928T180000Z", "20260928T180001Z"
    second_archive = released.archive_dir.with_name(
        released.archive_dir.name.replace(old_stamp, new_stamp)
    )
    staged = fixture.cache / "claim-residue-release" / fixture.intent.task_id
    shutil.copytree(released.archive_dir, second_archive)
    shutil.copytree(
        staged / f"{old_stamp}-{fixture.intent.role}",
        staged / f"{new_stamp}-{fixture.intent.role}",
    )
    readme = second_archive / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8").replace(old_stamp, new_stamp))
    before = _tree_snapshot(tmp_path)

    (result,) = recover_claim_publications(
        cache_dir=fixture.cache,
        transaction_root=fixture.transactions,
        receipt_root=receipt.receipt_path.parent,
        lock_root=fixture.locks,
        task_id=fixture.intent.task_id,
    )

    assert (result.state, result.reason_code) == ("hold", "claim_publication_release_ambiguous")
    assert _tree_snapshot(tmp_path) == before


def test_unfinished_projection_conflict_keeps_peer_note_and_unfinished_journal(
    tmp_path: Path,
) -> None:
    fixture, journal, projections = _held_publication(tmp_path)
    before = _tree_snapshot(tmp_path)
    assert len(projections) > 7
    assert claim_publication_receipt_path(
        fixture.cache, fixture.intent.binding, receipt_root=tmp_path / "receipts"
    ).exists()

    (result,) = recover_claim_publications(
        cache_dir=fixture.cache,
        transaction_root=fixture.transactions,
        receipt_root=tmp_path / "receipts",
        lock_root=fixture.locks,
        task_id=fixture.intent.task_id,
    )

    assert (result.state, result.reason_code) == (
        "hold",
        "claim_publication_recovery_projection_conflict",
    )
    assert sdlc_claim._load_admitted_manifest(journal / "manifest.json")[3] == "recovery_required"
    assert _tree_snapshot(tmp_path) == before


def test_independent_role_claims_publish_across_synthetic_task_store_churn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, coord_ledger: Path
) -> None:
    old_fixture, predecessor, successor = _two_applied_claims_for_one_task(tmp_path)
    control = _fixture(tmp_path, task_id="control-task", role="cx-control")
    control_root = tmp_path / "control-proof"
    control_root.mkdir()
    control_admission = _active_admission_fixture(control_root, control)
    control_receipt = sdlc_claim._apply_admitted_claim_publication_transaction(
        control.intent,
        control_admission.consumption,
        transaction_root=control.transactions,
        receipt_root=predecessor.receipt_path.parent,
        lock_root=control.locks,
        now=control_admission.checked_at,
    )
    assert (
        len(list(control.transactions.glob(f"{control_receipt.publication_id}/manifest.json"))) == 1
    )

    pending: list[tuple[ClaimFixture, AdmissionFixture]] = []
    for index, role in enumerate(("cx-green", "cx-blue", "cx-violet"), start=1):
        fixture = _fixture(tmp_path, task_id=f"independent-{index}", role=role)
        proof_root = tmp_path / f"role-proof-{index}"
        proof_root.mkdir()
        pending.append((fixture, _active_admission_fixture(proof_root, fixture)))
    attempts = _churning_task_store(
        old_fixture.vault, monkeypatch, churn_on=lambda attempt: attempt % 2 == 1
    )
    monkeypatch.setattr(sdlc_claim, "_churn_sleep", lambda _seconds: None)
    published = []
    for fixture, admission in pending:
        published.append(
            sdlc_claim._apply_admitted_claim_publication_transaction(
                fixture.intent,
                admission.consumption,
                transaction_root=fixture.transactions,
                receipt_root=predecessor.receipt_path.parent,
                lock_root=fixture.locks,
                now=admission.checked_at,
            )
        )
    assert attempts == list(range(1, 25))  # four resolution sites, each retaken once, per role
    states = {
        result.publication_id: result.state
        for result in recover_claim_publications(
            cache_dir=old_fixture.cache,
            transaction_root=old_fixture.transactions,
            receipt_root=predecessor.receipt_path.parent,
            lock_root=old_fixture.locks,
        )
    }
    assert states == {
        predecessor.publication_id: "superseded",
        successor.publication_id: "applied",
        control_receipt.publication_id: "applied",
        **{receipt.publication_id: "applied" for receipt in published},
    }
    phases: dict[str, list[str]] = {}
    for event in _phase_observations(coord_ledger):
        payload = event["payload"]
        phases.setdefault(payload["publication_id"], []).append(payload["state"])
    assert set(phases) == set(states)
    assert all(
        phase_list == ["created", "projecting", "postimage_complete", "applied"]
        for phase_list in phases.values()
    )
