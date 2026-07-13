from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from hapax.context_canon import CommittedOutcomeReceiptLike, canonical_json_bytes
from hapax.context_canon import contract as context_contract

import shared.sdlc_claim as sdlc_claim
from shared.dispatcher_policy import DispatchAction, RouteDecision
from shared.execution_admission import (
    ACTION_INTENT_SCHEMA,
    APPLIED_CLAIM_OWNERSHIP_SCHEMA,
    CLAIM_PUBLICATION_COMPLETION_EVIDENCE_SCHEMA,
    EXECUTION_ADMISSION_SCHEMA,
    OUTCOME_PIPELINE_READINESS_QUERY_SCHEMA,
    OUTCOME_RECEIPT_SCHEMA,
    VALID_AUTHORITY_GRANT_SCHEMA,
    ActionIntent,
    AppliedClaimOwnershipProof,
    AppliedClaimResolution,
    ClaimPublicationArtifact,
    ContentAddress,
    ExecutionAdmission,
    ExecutionAdmissionError,
    ExecutionLease,
    ExecutionTrustResolver,
    FrontierValidityEnvelope,
    HistoricalAppliedClaimOwnershipProofV3,
    OutcomeCommitter,
    OutcomePipelineReadinessQuery,
    OutcomeProjectionSnapshot,
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
    require_historical_applied_claim_ownership_proof,
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
    lease: ExecutionLease
    checked_at: datetime
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
    resume: bool = False,
    claimable: bool = True,
) -> ClaimFixture:
    vault = tmp_path / "vault"
    active = vault / "active"
    cache = tmp_path / "cache"
    active.mkdir(parents=True)
    (vault / "closed").mkdir()
    cache.mkdir()
    before = _note(
        task_id=task_id,
        status="pr_open" if resume else "offered",
        assigned_to="cx-red" if resume else "unassigned",
        claimed_at="2026-07-10T12:00:00Z" if resume else "null",
        claimable=claimable,
    )
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
        trust_resolver=_trusted_resolver(issuer_query, valid_until),
    )

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
        lease=lease,
        checked_at=checked_at,
        proof_paths=paths,
    )


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
        OUTCOME_RECEIPT_SCHEMA.encode("ascii")
        + b"\0"
        + canonical_json_bytes(body)
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
    assert actual.event_frontier.ref.endswith(
        f"@sha256:{actual.event_frontier.sha256}"
    )


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


def test_recovery_is_gate0a_hold_and_never_reconciles_history(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    _materialize_v1_history(fixture, state="created")
    before = _tree_snapshot(tmp_path)

    with pytest.raises(ClaimPublicationError) as raised:
        recover_claim_publications(
            cache_dir=fixture.cache,
            transaction_root=fixture.transactions,
            lock_root=fixture.locks,
        )

    assert raised.value.reason_code == "claim_publication_recovery_activation_unvalidated"
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
    assert task_artifact.content_sha256 == hashlib.sha256(
        fixture.intent.note_after
    ).hexdigest()

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
    completion["evidence_ref"] = (
        f"claim-publication-completion-evidence@sha256:{completion_hash}"
    )
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
