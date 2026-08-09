"""Dormant Gate-0B claim-publication admission and lease issuer machinery."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from shared.dispatcher_policy import DispatchAction, RouteDecision
from shared.execution_admission import (
    ACTION_INTENT_SCHEMA,
    EXECUTION_ADMISSION_SCHEMA,
    VALID_AUTHORITY_GRANT_SCHEMA,
    ActionIntent,
    AuthorityEvidence,
    ContentAddress,
    ExecutionAdmission,
    ExecutionLease,
    ExecutorDescriptor,
    ExecutorRegistryProjection,
    ProtectedActionRequest,
    RootDisposition,
    ValidAuthorityGrant,
    build_authority_evidence,
    build_bound_execution_call,
    build_effect_manifest,
    build_execution_lease_issuer_trust_query,
    build_execution_target_evidence,
    build_execution_trust_envelope,
    build_execution_trust_query,
    build_protected_action_request,
    build_protected_aperture_decision,
    build_protected_claim_coordinates,
    content_address,
    mint_execution_lease,
    module_file_address,
)
from shared.gate0b_claim_publication_install import (
    GATE0B_CLAIM_PUBLICATION_CAPABILITY_ROLE,
    GATE0B_CLAIM_PUBLICATION_EXECUTION_HOST,
    GATE0B_CLAIM_PUBLICATION_OPERATION,
    GATE0B_SLICE1_RATIFIED_INFLECTION_REF,
    GATE0B_SLICE1_REQUEST_REF,
    Gate0BClaimPublicationInstallReceipt,
    claim_publication_executor_descriptor,
    claim_publication_executor_registry_projection,
    require_claim_publication_install_receipt,
)
from shared.sdlc_claim import (
    ClaimAdmissionConsumption,
    ClaimPublicationError,
    ClaimPublicationIntent,
    claim_publication_mutation_scope_address,
    claim_publication_task_note_address,
    prospective_claim_publication_basis,
)

AUTHORITY_RECEIPT_SCHEMA = "hapax.gate0b-claim-publication-authority-receipt.v1"
PROOF_ROOT_SCHEMA = "hapax.gate0b-claim-publication-proof-root.v1"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


def _canonical_timestamp(value: str | datetime) -> str:
    parsed = (
        datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    )
    if parsed.tzinfo is None:
        raise ValueError("timestamp must carry a timezone")
    return parsed.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _jsonable(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True)
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, Path):
        return str(value)
    return value


def _canonical(value: object) -> bytes:
    return json.dumps(
        _jsonable(value),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _self_hash(domain: str, body: object) -> str:
    return _sha256(domain.encode("ascii") + b"\0" + _canonical(body))


def _content_address(label: str, body: object) -> ContentAddress:
    digest = _self_hash(f"hapax.{label}.v1", body)
    return ContentAddress(ref=f"{label}@sha256:{digest}", sha256=digest)


def _write_model(path: Path, model: BaseModel) -> Path:
    payload = _canonical(model.model_dump(mode="json", by_alias=True)) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        existing = path.read_bytes()
    except FileNotFoundError:
        existing = None
    if existing == payload:
        if path.stat(follow_symlinks=False).st_mode & 0o777 != 0o600:
            raise ClaimPublicationError(
                "claim_publication_proof_mode_mismatch",
                "restore materialized admission proofs to mode 0600",
                str(path),
            )
        return path
    if existing is not None:
        raise ClaimPublicationError(
            "claim_publication_proof_collision",
            "quarantine the colliding admission proof file",
            str(path),
        )
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{secrets.token_hex(8)}")
    fd = os.open(
        tmp,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
        0o600,
    )
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        os.replace(tmp, path)
        os.chmod(path, 0o600, follow_symlinks=False)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise
    return path


class Gate0BClaimPublicationAuthorityReceipt(_FrozenModel):
    schema_id: Literal["hapax.gate0b-claim-publication-authority-receipt.v1"] = Field(
        alias="schema"
    )
    receipt_ref: str
    receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    operator_inflection_ref: str
    request_ref: str
    implementation_task_ref: str
    authority_case: str
    parent_spec: ContentAddress
    decomposition: ContentAddress
    install_receipt: ContentAddress
    authorized_operations: tuple[Literal["claim.publish"], ...]
    authorized_action_classes: tuple[Literal["claim_publication"], ...]
    authorized_flags: tuple[Literal["implementation_authorized"], ...]
    scope_refs: tuple[str, ...]
    issued_at: str
    valid_until: str
    may_authorize: Literal[False]
    authorizes_operator: Literal[False]
    may_mint_sovereign_act: Literal[False]

    @field_validator(
        "receipt_ref",
        "operator_inflection_ref",
        "request_ref",
        "implementation_task_ref",
        "authority_case",
        "issued_at",
        "valid_until",
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("authority receipt strings must be nonblank")
        return value

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        if self.issued_at != _canonical_timestamp(self.issued_at) or (
            self.valid_until != _canonical_timestamp(self.valid_until)
        ):
            raise ValueError("authority receipt timestamps must be canonical UTC")
        if (
            self.authorized_operations != (GATE0B_CLAIM_PUBLICATION_OPERATION,)
            or self.authorized_action_classes != ("claim_publication",)
            or self.authorized_flags != ("implementation_authorized",)
            or self.issued_at >= self.valid_until
        ):
            raise ValueError("authority receipt grants only bounded claim publication")
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"receipt_ref", "receipt_hash"},
        )
        expected = _self_hash(AUTHORITY_RECEIPT_SCHEMA, body)
        if (
            self.receipt_hash != expected
            or self.receipt_ref != f"gate0b-claim-publication-authority@sha256:{expected}"
        ):
            raise ValueError("authority receipt reference/hash do not bind its body")
        return self


@dataclass(frozen=True)
class ClaimPublicationAdmissionPackage:
    intent: ClaimPublicationIntent
    proof_root: Path
    checked_at: str
    install_receipt: Gate0BClaimPublicationInstallReceipt
    authority_receipt: Gate0BClaimPublicationAuthorityReceipt
    action_intent: ActionIntent
    authority_evidence: AuthorityEvidence
    valid_authority_grant: ValidAuthorityGrant
    execution_admission: ExecutionAdmission
    execution_lease: ExecutionLease
    protected_request: ProtectedActionRequest
    effect_manifest: object
    executor_descriptor: ExecutorDescriptor
    executor_registry_projection: ExecutorRegistryProjection

    @property
    def action_intent_path(self) -> Path:
        return self.proof_root / "action-intent.json"

    @property
    def authority_evidence_path(self) -> Path:
        return self.proof_root / "authority-evidence.json"

    @property
    def execution_admission_path(self) -> Path:
        return self.proof_root / "execution-admission.json"

    @property
    def valid_authority_grant_path(self) -> Path:
        return self.proof_root / "valid-authority-grant.json"

    @property
    def execution_lease_path(self) -> Path:
        return self.proof_root / "execution-lease.json"


def _authority_receipt(
    intent: ClaimPublicationIntent,
    install_receipt: Gate0BClaimPublicationInstallReceipt,
    *,
    parent_spec: ContentAddress,
    decomposition: ContentAddress,
    scope_refs: tuple[str, ...],
    issued_at: str,
    valid_until: str,
) -> Gate0BClaimPublicationAuthorityReceipt:
    body: dict[str, object] = {
        "schema": AUTHORITY_RECEIPT_SCHEMA,
        "operator_inflection_ref": GATE0B_SLICE1_RATIFIED_INFLECTION_REF,
        "request_ref": GATE0B_SLICE1_REQUEST_REF,
        "implementation_task_ref": install_receipt.install_task_ref,
        "authority_case": intent.binding.authority_case,
        "parent_spec": parent_spec,
        "decomposition": decomposition,
        "install_receipt": ContentAddress(
            ref=install_receipt.receipt_ref,
            sha256=install_receipt.receipt_hash,
        ),
        "authorized_operations": (GATE0B_CLAIM_PUBLICATION_OPERATION,),
        "authorized_action_classes": ("claim_publication",),
        "authorized_flags": ("implementation_authorized",),
        "scope_refs": scope_refs,
        "issued_at": issued_at,
        "valid_until": valid_until,
        "may_authorize": False,
        "authorizes_operator": False,
        "may_mint_sovereign_act": False,
    }
    digest = _self_hash(AUTHORITY_RECEIPT_SCHEMA, body)
    return Gate0BClaimPublicationAuthorityReceipt.model_validate(
        {
            **body,
            "receipt_ref": f"gate0b-claim-publication-authority@sha256:{digest}",
            "receipt_hash": digest,
        }
    )


def _trusted_resolver(query: object, *, resolver: ContentAddress, valid_until: str):
    envelope = build_execution_trust_envelope(
        query,
        resolver=resolver,
        decision="trusted",
        event_frontier=_content_address("gate0b-trust-frontier", {"query": query}),
        root_dispositions=tuple(
            RootDisposition(
                root=root,
                disposition="current",
                superseding_roots=(),
                reason_codes=(),
                source_event_refs=(f"event:gate0b:{index}",),
            )
            for index, root in enumerate(query.required_roots)
        ),
        checked_at=query.queried_at,
        stale_after=valid_until,
    )
    from shared.execution_admission import ExecutionTrustResolver

    return ExecutionTrustResolver(resolver=resolver, envelopes=(envelope,))


def _default_proof_root(
    intent: ClaimPublicationIntent,
    *,
    claim_transaction_root: Path,
    attempt_fence: str,
) -> Path:
    root = claim_transaction_root.parent / "execution-admission" / "claim-publication"
    return root / intent.intent_sha256 / attempt_fence


def prepare_claim_publication_admission(
    intent: ClaimPublicationIntent,
    *,
    root,
    install_receipt: Gate0BClaimPublicationInstallReceipt | None = None,
    now: str | datetime,
    proof_root: Path | None = None,
    lease_seconds: int = 1800,
) -> ClaimPublicationAdmissionPackage:
    receipt = install_receipt or require_claim_publication_install_receipt(root)
    root.require_effect_activation()
    checked_at = _canonical_timestamp(now)
    valid_until = _canonical_timestamp(
        datetime.fromisoformat(checked_at.replace("Z", "+00:00")) + timedelta(seconds=lease_seconds)
    )
    mutation_scope = claim_publication_mutation_scope_address(intent)
    basis = prospective_claim_publication_basis(intent)
    claim_intent = ContentAddress(ref=intent.intent_ref, sha256=intent.intent_sha256)
    basis_address = ContentAddress(ref=basis.basis_ref, sha256=basis.basis_hash)
    coordinates = build_protected_claim_coordinates(
        state="prospective",
        task_ref=intent.task_id,
        lane=intent.role,
        session_ref=intent.session_id,
        claim_epoch=intent.claim_epoch,
        claim_publication_intent=claim_intent,
        claim_basis=basis_address,
    )
    effect_manifest = build_effect_manifest(
        operation=GATE0B_CLAIM_PUBLICATION_OPERATION,
        capability_role=GATE0B_CLAIM_PUBLICATION_CAPABILITY_ROLE,
        execution_host=GATE0B_CLAIM_PUBLICATION_EXECUTION_HOST,
        mutating=True,
        external_effect=False,
        effect_classes=("claim_publication",),
        effect_targets=(mutation_scope,),
        scope_refs=(mutation_scope.ref,),
        observation_contract=_content_address(
            "gate0b-claim-observation-contract", {"operation": GATE0B_CLAIM_PUBLICATION_OPERATION}
        ),
        completion_predicate=_content_address(
            "gate0b-claim-completion-predicate", {"operation": GATE0B_CLAIM_PUBLICATION_OPERATION}
        ),
        idempotence_class="idempotent",
        reconciliation_contract=_content_address(
            "gate0b-claim-reconciliation-contract",
            {"operation": GATE0B_CLAIM_PUBLICATION_OPERATION},
        ),
        compensation=None,
    )
    effect_address = ContentAddress(
        ref=effect_manifest.manifest_ref,
        sha256=effect_manifest.manifest_hash,
    )
    executor_descriptor = claim_publication_executor_descriptor(receipt)
    registry = claim_publication_executor_registry_projection(receipt, executor_descriptor)
    runtime_identity = executor_descriptor.runtime_identity
    shared = Path(__file__).resolve().parent
    ingress_module = module_file_address(shared / "gate0b_claim_publication_effect.py")
    admission_module = module_file_address(shared / "execution_admission.py")
    aperture = build_protected_aperture_decision(
        raw_invocation=_content_address(
            "gate0b-raw-claim-publication-invocation",
            {"intent": intent.intent_ref, "checked_at": checked_at},
        ),
        disposition="protected",
        aperture_id=None,
        surface="intake",
        operation=GATE0B_CLAIM_PUBLICATION_OPERATION,
        classifier_module=ingress_module,
    )
    protected_request = build_protected_action_request(
        aperture,
        coordinates,
        platform=intent.binding.platform,
        mode=intent.binding.mode,
        profile=intent.binding.profile,
        execution_host=GATE0B_CLAIM_PUBLICATION_EXECUTION_HOST,
        runtime_identity=runtime_identity,
        ingress_module=ingress_module,
        admission_module=admission_module,
        claim_mode=intent.claim_mode,
        effect_manifest=effect_address,
        active_generation_roots=executor_descriptor.active_generation_roots,
        requested_effect_targets=(mutation_scope,),
        requested_scope_refs=(mutation_scope.ref,),
        supersession_frontier_ref=f"gate0b-claim-publication:{receipt.receipt_hash}",
        requested_at=checked_at,
        mutating=True,
    )
    parent_spec = _content_address(
        "gate0b-parent-spec",
        {"request_ref": receipt.request_ref, "intent": intent.intent_ref},
    )
    decomposition = _content_address(
        "gate0b-decomposition",
        {"install_task_ref": receipt.install_task_ref, "intent": intent.intent_ref},
    )
    authority_receipt = _authority_receipt(
        intent,
        receipt,
        parent_spec=parent_spec,
        decomposition=decomposition,
        scope_refs=(mutation_scope.ref,),
        issued_at=checked_at,
        valid_until=valid_until,
    )
    authority_receipt_address = ContentAddress(
        ref=authority_receipt.receipt_ref,
        sha256=authority_receipt.receipt_hash,
    )
    authority_source = _content_address(
        "gate0b-authority-source",
        {
            "operator_inflection_ref": authority_receipt.operator_inflection_ref,
            "request_ref": authority_receipt.request_ref,
            "implementation_task_ref": authority_receipt.implementation_task_ref,
            "authority_case": authority_receipt.authority_case,
        },
    )
    authority_evidence = build_authority_evidence(
        authority_source=authority_source,
        authenticated_receipt=authority_receipt_address,
        issuer=receipt.authority_receipt_root,
        subject=runtime_identity,
        authority_case=intent.binding.authority_case,
        authority_ceiling="bounded_machine_execution",
        authorized_action_classes=("claim_publication",),
        authorized_operations=(GATE0B_CLAIM_PUBLICATION_OPERATION,),
        authorized_flags=("implementation_authorized",),
        scope_refs=(mutation_scope.ref,),
        not_before=checked_at,
        valid_until=valid_until,
        supersession_frontier_ref=f"gate0b-claim-publication:{receipt.receipt_hash}",
    )
    position = _content_address(
        "gate0b-context-position",
        {
            "claim_publication_intent": intent.intent_ref,
            "authority_case": intent.binding.authority_case,
            "scope_refs": (mutation_scope.ref,),
        },
    )
    action_body: dict[str, object] = {
        "schema": ACTION_INTENT_SCHEMA,
        "task_ref": intent.task_id,
        "position_ref": position.ref,
        "position_hash": position.sha256,
        "action_id": f"claim-publication:{intent.intent_sha256}",
        "action_class": "claim_publication",
        "operation": GATE0B_CLAIM_PUBLICATION_OPERATION,
        "capability_role": GATE0B_CLAIM_PUBLICATION_CAPABILITY_ROLE,
        "execution_host": GATE0B_CLAIM_PUBLICATION_EXECUTION_HOST,
        "acting_subject": runtime_identity,
        "protected_action_request": ContentAddress(
            ref=protected_request.request_ref,
            sha256=protected_request.request_hash,
        ),
        "effect_manifest": effect_address,
        "requested_effect_targets": (mutation_scope,),
        "parent_spec": parent_spec,
        "decomposition": decomposition,
        "requested_scope_refs": (mutation_scope.ref,),
        "required_authorization_flags": ("implementation_authorized",),
        "lifecycle_admission_ref": None,
        "lifecycle_transition_to": None,
        "lifecycle_transition_edge": None,
        "mutating": True,
        "may_authorize": False,
    }
    action_hash = _self_hash(ACTION_INTENT_SCHEMA, action_body)
    action = ActionIntent.model_validate(
        {
            **action_body,
            "intent_ref": f"action-intent@sha256:{action_hash}",
            "intent_hash": action_hash,
        }
    )
    action_address = ContentAddress(ref=action.intent_ref, sha256=action.intent_hash)
    evidence_address = ContentAddress(
        ref=authority_evidence.evidence_ref,
        sha256=authority_evidence.evidence_hash,
    )
    trust_query = build_execution_trust_query(
        trust_class="authenticated_authority_receipt",
        subject_roots=(
            action_address,
            evidence_address,
            position,
            authority_evidence.authority_source,
            authority_evidence.issuer,
            runtime_identity,
        ),
        presented_receipt=authority_receipt_address,
        required_roots=(
            action_address,
            evidence_address,
            position,
            authority_evidence.authority_source,
            authority_evidence.issuer,
            runtime_identity,
        ),
        supersession_frontier_ref=authority_evidence.supersession_frontier_ref,
        queried_at=checked_at,
    )
    authority_resolver = _trusted_resolver(
        trust_query,
        resolver=receipt.authority_receipt_root,
        valid_until=valid_until,
    )
    trust_envelope = authority_resolver.require_trusted(trust_query)
    grant_body: dict[str, object] = {
        "schema": VALID_AUTHORITY_GRANT_SCHEMA,
        "intent_ref": action.intent_ref,
        "intent_hash": action.intent_hash,
        "evidence_ref": authority_evidence.evidence_ref,
        "evidence_hash": authority_evidence.evidence_hash,
        "authority_source": authority_evidence.authority_source,
        "authenticated_receipt": authority_evidence.authenticated_receipt,
        "authority_issuer": authority_evidence.issuer,
        "acting_subject": runtime_identity,
        "authority_trust_query": trust_query,
        "authority_trust_envelope": trust_envelope,
        "position_ref": position.ref,
        "position_hash": position.sha256,
        "task_ref": intent.task_id,
        "authority_case": intent.binding.authority_case,
        "authority_ceiling": authority_evidence.authority_ceiling,
        "action_class": "claim_publication",
        "operation": GATE0B_CLAIM_PUBLICATION_OPERATION,
        "authorized_flags": ("implementation_authorized",),
        "scope_refs": (mutation_scope.ref,),
        "issued_at": checked_at,
        "valid_until": valid_until,
        "supersession_frontier_ref": authority_evidence.supersession_frontier_ref,
        "validation_method_ref": "method:gate0b-claim-publication-authority-v1",
        "authorizes_machine_admission": True,
        "authorizes_operator": False,
        "may_mint_sovereign_act": False,
    }
    grant_hash = _self_hash(VALID_AUTHORITY_GRANT_SCHEMA, grant_body)
    grant = ValidAuthorityGrant.model_validate(
        {
            **grant_body,
            "grant_ref": f"authority-grant@sha256:{grant_hash}",
            "grant_hash": grant_hash,
        }
    )
    leaf = executor_descriptor.selected_descriptor_leaf
    target = build_execution_target_evidence(
        host_scoped_claim=_content_address(
            "gate0b-host-scoped-claim",
            {"intent": intent.intent_ref, "receipt": receipt.receipt_ref},
        ),
        effect_manifest=effect_manifest,
        executor_descriptor=executor_descriptor,
        executor_registry_projection=registry,
        environment_observation=_content_address(
            "gate0b-environment-observation", {"operation": GATE0B_CLAIM_PUBLICATION_OPERATION}
        ),
        observed_at=checked_at,
        checked_at=checked_at,
        stale_after=valid_until,
    )
    decision = RouteDecision(
        decision_id=f"gate0b-claim-publication-route:{intent.intent_sha256}",
        created_at=datetime.fromisoformat(checked_at.replace("Z", "+00:00")),
        task_id=intent.task_id,
        lane=intent.role,
        route_id="codex.headless.full",
        platform=intent.binding.platform,
        mode=intent.binding.mode,
        profile=intent.binding.profile,
        action=DispatchAction.LAUNCH,
        policy_outcome="gate0b-claim-publication",
        launch_allowed=True,
        prompt_allowed=True,
        quality_floor_satisfied=True,
        authority_allowed=True,
        selected_descriptor_leaf=leaf,
        local_execution_target=GATE0B_CLAIM_PUBLICATION_EXECUTION_HOST,
        message="Gate 0B dormant claim-publication executor selected",
    )
    route_address = content_address(decision.decision_id, decision)
    target_address = ContentAddress(ref=target.target_ref, sha256=target.target_hash)
    grant_address = ContentAddress(ref=grant.grant_ref, sha256=grant.grant_hash)
    task_note = claim_publication_task_note_address(intent)
    admission_body: dict[str, object] = {
        "schema": EXECUTION_ADMISSION_SCHEMA,
        "decision": "admit",
        "lease_eligible": True,
        "task_ref": intent.task_id,
        "lane": intent.role,
        "session_ref": intent.session_id,
        "authority_case": intent.binding.authority_case,
        "intent": action_address,
        "effect_manifest": effect_address,
        "authority_grant": grant_address,
        "authority_trust_query": trust_query,
        "authority_trust_envelope": trust_envelope,
        "task_note": task_note,
        "parent_spec": parent_spec,
        "decomposition": decomposition,
        "context_frame": _content_address("gate0b-context-frame", {"position": position}),
        "context_position": position,
        "canon_bundle": _content_address("gate0b-canon-bundle", {"position": position}),
        "canon_image": _content_address("gate0b-canon-image", {"position": position}),
        "impingement_trace": _content_address("gate0b-impingement-trace", {"position": position}),
        "fact_frontier": _content_address("gate0b-fact-frontier", {"position": position}),
        "context_selection": _content_address("gate0b-context-selection", {"position": position}),
        "audience_seal_receipt": _content_address("gate0b-audience-seal", {"position": position}),
        "claim_publication_intent": claim_intent,
        "demand_vector": _content_address("gate0b-demand-vector", {"intent": intent.intent_ref}),
        "demand_derivation_receipt": _content_address(
            "gate0b-demand-derivation", {"intent": intent.intent_ref}
        ),
        "supply_vector": _content_address("gate0b-supply-vector", {"intent": intent.intent_ref}),
        "supply_refresh_receipt": _content_address(
            "gate0b-supply-refresh", {"intent": intent.intent_ref}
        ),
        "route_decision": route_address,
        "selected_descriptor_leaf": leaf,
        "dependency_closure": _content_address(
            "gate0b-dependency-closure", {"intent": intent.intent_ref}
        ),
        "quota_reservation": _content_address(
            "gate0b-quota-reservation", {"intent": intent.intent_ref}
        ),
        "execution_target": target_address,
        "dispatch_message_id": intent.binding.dispatch_message_id,
        "idempotency_key": intent.binding.coord_dispatch_idempotency_key,
        "authorized_flags": grant.authorized_flags,
        "immutable_scope_refs": grant.scope_refs,
        "issued_at": checked_at,
        "valid_until": valid_until,
        "supersession_frontier_ref": authority_evidence.supersession_frontier_ref,
        "supersedes_refs": (),
        "reason_codes": (),
        "repair_refs": (),
        "may_authorize": False,
        "authorizes_operator": False,
    }
    admission_hash = _self_hash(EXECUTION_ADMISSION_SCHEMA, admission_body)
    admission = ExecutionAdmission.model_validate(
        {
            **admission_body,
            "admission_ref": f"execution-admission@sha256:{admission_hash}",
            "admission_hash": admission_hash,
        }
    )
    attempt_fence = _sha256(
        PROOF_ROOT_SCHEMA.encode("ascii")
        + b"\0"
        + _canonical({"intent": intent.intent_ref, "checked_at": checked_at})
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
        executor_descriptor,
        registry,
        invocation_id=f"claim-publication:{intent.intent_sha256}",
        attempt_fence=attempt_fence,
    )
    issuer_query = build_execution_lease_issuer_trust_query(
        admission,
        grant,
        basis,
        target,
        bound_call,
        effect_manifest,
        executor_descriptor,
        registry,
        issuer_receipt=receipt.lease_issuer_receipt_root,
        queried_at=checked_at,
    )
    issuer_resolver = _trusted_resolver(
        issuer_query,
        resolver=receipt.lease_issuer_receipt_root,
        valid_until=valid_until,
    )
    lease = mint_execution_lease(
        admission,
        action,
        grant,
        basis,
        target,
        bound_call,
        effect_manifest,
        executor_descriptor,
        registry,
        issuer_receipt=receipt.lease_issuer_receipt_root,
        now=checked_at,
        trust_resolver=issuer_resolver,
    )
    checked_proof_root = (
        proof_root
        if proof_root is not None
        else _default_proof_root(
            intent,
            claim_transaction_root=Path(root.claim_transaction_root),
            attempt_fence=attempt_fence,
        )
    )
    return ClaimPublicationAdmissionPackage(
        intent=intent,
        proof_root=checked_proof_root,
        checked_at=checked_at,
        install_receipt=receipt,
        authority_receipt=authority_receipt,
        action_intent=action,
        authority_evidence=authority_evidence,
        valid_authority_grant=grant,
        execution_admission=admission,
        execution_lease=lease,
        protected_request=protected_request,
        effect_manifest=effect_manifest,
        executor_descriptor=executor_descriptor,
        executor_registry_projection=registry,
    )


def materialize_claim_publication_proofs(
    package: ClaimPublicationAdmissionPackage,
) -> ClaimAdmissionConsumption:
    _write_model(package.action_intent_path, package.action_intent)
    _write_model(package.authority_evidence_path, package.authority_evidence)
    _write_model(package.execution_admission_path, package.execution_admission)
    _write_model(package.valid_authority_grant_path, package.valid_authority_grant)
    _write_model(package.execution_lease_path, package.execution_lease)
    return ClaimAdmissionConsumption.create(
        package.intent,
        action_intent_path=package.action_intent_path,
        authority_evidence_path=package.authority_evidence_path,
        execution_admission_path=package.execution_admission_path,
        valid_authority_grant_path=package.valid_authority_grant_path,
        execution_lease_path=package.execution_lease_path,
        checked_at=package.checked_at,
    )


__all__ = [
    "AUTHORITY_RECEIPT_SCHEMA",
    "Gate0BClaimPublicationAuthorityReceipt",
    "ClaimPublicationAdmissionPackage",
    "materialize_claim_publication_proofs",
    "prepare_claim_publication_admission",
]
