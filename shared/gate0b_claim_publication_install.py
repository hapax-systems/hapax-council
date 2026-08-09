"""Dormant Gate-0B claim-publication composition install machinery."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from shared.execution_admission import (
    _MAX_EXECUTION_INVOCATION_BUNDLE_BYTES,
    CompletionEvaluator,
    ContentAddress,
    EffectManifestResolver,
    ExecutionAdmissionError,
    ExecutionCompositionManifest,
    ExecutionCompositionPortDescriptors,
    ExecutionCompositionPorts,
    ExecutionCompositionRoot,
    ExecutionCurrentnessResolver,
    ExecutionExecutorBinding,
    ExecutionExecutorRegistry,
    ExecutionInvocationBundleStore,
    ExecutionTrustResolver,
    ExecutorDescriptor,
    ExecutorRegistryProjection,
    OutcomeCommitter,
    OutcomePipelineReadinessResolver,
    build_execution_composition_manifest,
    build_execution_composition_port_descriptors,
    build_executor_descriptor,
    build_executor_registry_projection,
    execution_composition_manifest_bytes,
    module_file_address,
)

INSTALL_RECEIPT_SCHEMA = "hapax.gate0b-claim-publication-install-receipt.v1"
INSTALL_RECEIPT_FILENAME = "activation-receipt.json"
GATE0B_CLAIM_PUBLICATION_OPERATION = "claim.publish"
GATE0B_CLAIM_PUBLICATION_CAPABILITY_ROLE = "claim_publisher"
GATE0B_CLAIM_PUBLICATION_EXECUTION_HOST = "appendix"
GATE0B_SLICE1_RATIFIED_INFLECTION_REF = "pli-84ef9835580da432"
GATE0B_SLICE1_REQUEST_REF = "REQ-20260807163000-gate0b-rewire-descoped-paths"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


def _canonical_timestamp(value: str | datetime) -> str:
    parsed = (
        datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    )
    if parsed.tzinfo is None:
        raise ValueError("Next action: supply a timezone-aware UTC timestamp")
    return parsed.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _jsonable(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
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


def _absolute(path: Path, *, label: str) -> Path:
    expanded = path.expanduser()
    if not expanded.is_absolute() or expanded == Path("/"):
        raise ValueError(f"Next action: set {label} to an absolute bounded path")
    return expanded.resolve(strict=False)


class ClaimPublicationCompositionRoots(_FrozenModel):
    invocation_store_root: str
    claim_vault_root: str
    claim_cache_dir: str
    claim_transaction_root: str
    claim_receipt_root: str
    claim_lock_root: str

    @field_validator(
        "invocation_store_root",
        "claim_vault_root",
        "claim_cache_dir",
        "claim_transaction_root",
        "claim_receipt_root",
        "claim_lock_root",
    )
    @classmethod
    def validate_path(cls, value: str) -> str:
        return str(_absolute(Path(value), label="claim-publication composition root"))


class Gate0BClaimPublicationInstallReceipt(_FrozenModel):
    schema_id: Literal["hapax.gate0b-claim-publication-install-receipt.v1"] = Field(alias="schema")
    receipt_ref: str
    receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    activation_generation: ContentAddress
    roots: ClaimPublicationCompositionRoots
    port_descriptors: ContentAddress
    executor_descriptor: ContentAddress
    executor_registry_projection: ContentAddress
    supported_operations: tuple[Literal["claim.publish"], ...]
    capability_role: Literal["claim_publisher"]
    execution_host: Literal["appendix"]
    authority_receipt_root: ContentAddress
    lease_issuer_receipt_root: ContentAddress
    operator_inflection_ref: str
    request_ref: str
    install_task_ref: str
    installed_at: str
    may_authorize: Literal[False]
    authorizes_direct_fallthrough: Literal[False]

    @field_validator(
        "receipt_ref",
        "operator_inflection_ref",
        "request_ref",
        "install_task_ref",
        "installed_at",
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError(
                "Next action: restore receipt strings as nonblank values without edge whitespace"
            )
        return value

    @field_validator("installed_at")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        if value != _canonical_timestamp(value):
            raise ValueError("installed_at must be canonical UTC; Next action: rewrite it as UTC Z")
        return value

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        if self.supported_operations != (GATE0B_CLAIM_PUBLICATION_OPERATION,):
            raise ValueError("Next action: reinstall a receipt that supports only claim.publish")
        if self.receipt_ref != f"gate0b-claim-publication-install@sha256:{self.receipt_hash}":
            raise ValueError("Next action: restore the install receipt reference bound to its hash")
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"receipt_ref", "receipt_hash"},
        )
        expected = _self_hash(INSTALL_RECEIPT_SCHEMA, body)
        if self.receipt_hash != expected:
            raise ValueError("Next action: restore the exact self-hashed install receipt body")
        return self


@dataclass(frozen=True)
class ClaimPublicationCompositionInstall:
    root: ExecutionCompositionRoot
    receipt: Gate0BClaimPublicationInstallReceipt


def default_claim_publication_roots(
    *, home: Path | None = None
) -> ClaimPublicationCompositionRoots:
    base = _absolute(home or Path.home(), label="claim-publication home")
    return ClaimPublicationCompositionRoots(
        invocation_store_root=str(
            base / ".local/share/hapax/execution-invocations/gate0b-claim-publish-v1"
        ),
        claim_vault_root=str(base / "Documents/Personal/20-projects/hapax-cc-tasks"),
        claim_cache_dir=str(base / ".cache/hapax"),
        claim_transaction_root=str(
            base / ".local/share/hapax/claim-publications/gate0b-claim-publish-v1"
        ),
        claim_receipt_root=str(base / ".cache/hapax/claim-publication-receipts"),
        claim_lock_root=str(base / ".local/state/hapax/task-locks/gate0b-claim-publish-v1"),
    )


def claim_publication_install_receipt_bytes(
    receipt: Gate0BClaimPublicationInstallReceipt,
) -> bytes:
    checked = Gate0BClaimPublicationInstallReceipt.model_validate(
        receipt.model_dump(mode="json", by_alias=True)
    )
    return _canonical(checked.model_dump(mode="json", by_alias=True)) + b"\n"


def _write_private_file(path: Path, payload: bytes, *, mode: int = 0o600) -> None:
    path = _absolute(path, label="private install file")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent_meta = path.parent.stat(follow_symlinks=False)
    if not stat.S_ISDIR(parent_meta.st_mode) or parent_meta.st_uid != os.geteuid():
        raise ExecutionAdmissionError(
            "gate0b_install_directory_unsafe",
            "restore an euid-owned private install directory",
            str(path.parent),
        )
    try:
        existing = path.read_bytes()
    except FileNotFoundError:
        existing = None
    if existing == payload:
        return
    if existing is not None:
        raise ExecutionAdmissionError(
            "gate0b_install_file_collision",
            "quarantine the colliding install artifact",
            str(path),
        )
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{secrets.token_hex(8)}")
    fd = os.open(
        tmp,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
        mode,
    )
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        os.replace(tmp, path)
        os.chmod(path, mode, follow_symlinks=False)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _load_install_receipt(path: Path) -> Gate0BClaimPublicationInstallReceipt:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ExecutionAdmissionError(
            "gate0b_install_receipt_missing",
            "install the exact Gate-0B claim-publication activation receipt",
            str(path),
        ) from exc
    try:
        record = json.loads(payload.decode("ascii"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ExecutionAdmissionError(
            "gate0b_install_receipt_unreadable",
            "restore canonical ASCII JSON activation receipt bytes",
            str(path),
        ) from exc
    receipt = Gate0BClaimPublicationInstallReceipt.model_validate(record)
    if payload != claim_publication_install_receipt_bytes(receipt):
        raise ExecutionAdmissionError(
            "gate0b_install_receipt_noncanonical",
            "restore canonical ASCII JSON activation receipt bytes",
            str(path),
        )
    return receipt


def _build_port_descriptors(
    *,
    executor_registry: ContentAddress,
) -> ExecutionCompositionPortDescriptors:
    return build_execution_composition_port_descriptors(
        trust_resolver=_content_address("gate0b-trust-resolver", {"component": "trust"}),
        effect_manifest_resolver=_content_address(
            "gate0b-effect-manifest-resolver", {"component": "effect-manifest"}
        ),
        currentness_resolver=_content_address(
            "gate0b-currentness-resolver", {"component": "currentness"}
        ),
        executor_registry=executor_registry,
        completion_evaluator=_content_address(
            "gate0b-completion-evaluator", {"component": "completion"}
        ),
        readiness_resolver=_content_address(
            "gate0b-readiness-resolver", {"component": "readiness"}
        ),
        outcome_committer=_content_address("gate0b-outcome-committer", {"component": "outcomes"}),
        event_plane=_content_address("gate0b-event-plane", {"component": "event-plane"}),
        outcome_projection_resolver=_content_address(
            "gate0b-outcome-projection-resolver", {"component": "projection"}
        ),
        outcome_validity_resolver=_content_address(
            "gate0b-outcome-validity-resolver", {"component": "validity"}
        ),
    )


def _generation_roots(activation_generation: ContentAddress) -> tuple[ContentAddress, ...]:
    shared = Path(__file__).resolve().parent
    roots = (
        activation_generation,
        module_file_address(shared / "execution_admission.py"),
        module_file_address(Path(__file__)),
        module_file_address(shared / "gate0b_claim_publication_lease.py"),
        module_file_address(shared / "gate0b_claim_publication_effect.py"),
    )
    return tuple(
        sorted({(item.ref, item.sha256): item for item in roots}.values(), key=lambda x: x.ref)
    )


def _build_executor_descriptor(
    activation_generation: ContentAddress,
    *,
    installed_at: str,
) -> ExecutorDescriptor:
    return build_executor_descriptor(
        executor=_content_address(
            "gate0b-claim-publication-executor", {"installed_at": installed_at}
        ),
        adapter=_content_address(
            "gate0b-claim-publication-adapter", {"installed_at": installed_at}
        ),
        harness=_content_address(
            "gate0b-claim-publication-harness", {"installed_at": installed_at}
        ),
        runtime_identity=_content_address(
            "gate0b-claim-publication-runtime", {"installed_at": installed_at}
        ),
        active_generation_roots=_generation_roots(activation_generation),
        execution_host=GATE0B_CLAIM_PUBLICATION_EXECUTION_HOST,
        platform="codex",
        mode="headless",
        profile="ultra",
        selected_descriptor_leaf="codex.headless.full#gate0b-claim-publisher",
        entrypoint="shared.gate0b_claim_publication_effect:apply_claim_publication_effect",
    )


def _build_executor_registry_projection(
    descriptor: ExecutorDescriptor,
    *,
    installed_at: str,
) -> ExecutorRegistryProjection:
    return build_executor_registry_projection(
        execution_host=GATE0B_CLAIM_PUBLICATION_EXECUTION_HOST,
        registry_source=_content_address(
            "gate0b-claim-publication-registry-source", {"installed_at": installed_at}
        ),
        event_frontier=_content_address(
            "gate0b-claim-publication-registry-frontier", {"installed_at": installed_at}
        ),
        descriptors=(descriptor,),
        observed_at=installed_at,
        checked_at=installed_at,
        stale_after="9999-12-31T23:59:59.999999Z",
    )


def claim_publication_executor_descriptor(
    receipt: Gate0BClaimPublicationInstallReceipt,
) -> ExecutorDescriptor:
    descriptor = _build_executor_descriptor(
        receipt.activation_generation,
        installed_at=receipt.installed_at,
    )
    if ContentAddress(ref=descriptor.descriptor_ref, sha256=descriptor.descriptor_hash) != (
        receipt.executor_descriptor
    ):
        raise ExecutionAdmissionError(
            "gate0b_install_executor_descriptor_mismatch",
            "restore the executor descriptor bound by the install receipt",
            receipt.receipt_ref,
        )
    return descriptor


def claim_publication_executor_registry_projection(
    receipt: Gate0BClaimPublicationInstallReceipt,
    descriptor: ExecutorDescriptor,
) -> ExecutorRegistryProjection:
    registry = _build_executor_registry_projection(descriptor, installed_at=receipt.installed_at)
    if ContentAddress(ref=registry.projection_ref, sha256=registry.projection_hash) != (
        receipt.executor_registry_projection
    ):
        raise ExecutionAdmissionError(
            "gate0b_install_executor_registry_mismatch",
            "restore the executor registry projection bound by the install receipt",
            receipt.receipt_ref,
        )
    return registry


def _build_ports(
    descriptors: ExecutionCompositionPortDescriptors,
    *,
    executor_descriptor: ExecutorDescriptor | None = None,
    registry_projection: ExecutorRegistryProjection | None = None,
) -> ExecutionCompositionPorts:
    bindings = ()
    if executor_descriptor is not None and registry_projection is not None:
        bindings = (ExecutionExecutorBinding(executor_descriptor),)
    return ExecutionCompositionPorts(
        descriptors=descriptors,
        trust=ExecutionTrustResolver(resolver=descriptors.trust_resolver),
        manifests=EffectManifestResolver(resolver=descriptors.effect_manifest_resolver),
        currentness=ExecutionCurrentnessResolver(resolver=descriptors.currentness_resolver),
        executors=ExecutionExecutorRegistry(
            projection=registry_projection,
            bindings=bindings,
            descriptor=descriptors.executor_registry,
        ),
        completion=CompletionEvaluator(evaluator=descriptors.completion_evaluator),
        readiness=OutcomePipelineReadinessResolver(resolver=descriptors.readiness_resolver),
        outcomes=OutcomeCommitter(
            committer=descriptors.outcome_committer,
            event_plane=descriptors.event_plane,
            projection_resolver=descriptors.outcome_projection_resolver,
            validity_resolver=descriptors.outcome_validity_resolver,
        ),
    )


def _build_install_receipt(
    *,
    roots: ClaimPublicationCompositionRoots,
    activation_generation: ContentAddress,
    descriptors: ExecutionCompositionPortDescriptors,
    executor_descriptor: ExecutorDescriptor,
    registry_projection: ExecutorRegistryProjection,
    installed_at: str,
    install_task_ref: str,
    operator_inflection_ref: str,
    request_ref: str,
) -> Gate0BClaimPublicationInstallReceipt:
    descriptor_address = ContentAddress(
        ref=descriptors.descriptors_ref,
        sha256=descriptors.descriptors_hash,
    )
    executor_address = ContentAddress(
        ref=executor_descriptor.descriptor_ref,
        sha256=executor_descriptor.descriptor_hash,
    )
    registry_address = ContentAddress(
        ref=registry_projection.projection_ref,
        sha256=registry_projection.projection_hash,
    )
    body: dict[str, object] = {
        "schema": INSTALL_RECEIPT_SCHEMA,
        "activation_generation": activation_generation,
        "roots": roots,
        "port_descriptors": descriptor_address,
        "executor_descriptor": executor_address,
        "executor_registry_projection": registry_address,
        "supported_operations": (GATE0B_CLAIM_PUBLICATION_OPERATION,),
        "capability_role": GATE0B_CLAIM_PUBLICATION_CAPABILITY_ROLE,
        "execution_host": GATE0B_CLAIM_PUBLICATION_EXECUTION_HOST,
        "authority_receipt_root": _content_address(
            "gate0b-authority-receipt-root",
            {"operator_inflection_ref": operator_inflection_ref, "request_ref": request_ref},
        ),
        "lease_issuer_receipt_root": _content_address(
            "gate0b-lease-issuer-receipt-root",
            {"install_task_ref": install_task_ref, "request_ref": request_ref},
        ),
        "operator_inflection_ref": operator_inflection_ref,
        "request_ref": request_ref,
        "install_task_ref": install_task_ref,
        "installed_at": installed_at,
        "may_authorize": False,
        "authorizes_direct_fallthrough": False,
    }
    digest = _self_hash(INSTALL_RECEIPT_SCHEMA, body)
    return Gate0BClaimPublicationInstallReceipt.model_validate(
        {
            **body,
            "receipt_ref": f"gate0b-claim-publication-install@sha256:{digest}",
            "receipt_hash": digest,
        }
    )


def build_claim_publication_composition(
    *,
    roots: ClaimPublicationCompositionRoots | None = None,
    installed_at: str | datetime,
    install_task_ref: str,
    operator_inflection_ref: str = GATE0B_SLICE1_RATIFIED_INFLECTION_REF,
    request_ref: str = GATE0B_SLICE1_REQUEST_REF,
) -> ClaimPublicationCompositionInstall:
    checked_at = _canonical_timestamp(installed_at)
    checked_roots = roots or default_claim_publication_roots()
    activation_generation = _content_address(
        "gate0b-claim-publication-generation",
        {
            "install_task_ref": install_task_ref,
            "operator_inflection_ref": operator_inflection_ref,
            "request_ref": request_ref,
            "installed_at": checked_at,
        },
    )
    executor_descriptor = _build_executor_descriptor(
        activation_generation,
        installed_at=checked_at,
    )
    registry_projection = _build_executor_registry_projection(
        executor_descriptor,
        installed_at=checked_at,
    )
    descriptors = _build_port_descriptors(
        executor_registry=ContentAddress(
            ref=registry_projection.projection_ref,
            sha256=registry_projection.projection_hash,
        )
    )
    receipt = _build_install_receipt(
        roots=checked_roots,
        activation_generation=activation_generation,
        descriptors=descriptors,
        executor_descriptor=executor_descriptor,
        registry_projection=registry_projection,
        installed_at=checked_at,
        install_task_ref=install_task_ref,
        operator_inflection_ref=operator_inflection_ref,
        request_ref=request_ref,
    )
    manifest = build_execution_composition_manifest(
        activation_generation=activation_generation,
        invocation_store_root=Path(checked_roots.invocation_store_root),
        max_bundle_bytes=_MAX_EXECUTION_INVOCATION_BUNDLE_BYTES,
        claim_vault_root=Path(checked_roots.claim_vault_root),
        claim_cache_dir=Path(checked_roots.claim_cache_dir),
        claim_transaction_root=Path(checked_roots.claim_transaction_root),
        claim_receipt_root=Path(checked_roots.claim_receipt_root),
        claim_lock_root=Path(checked_roots.claim_lock_root),
        port_descriptors=descriptors,
        attempt_journal=_content_address(
            "gate0b-claim-publication-attempt-journal",
            {"install_task_ref": install_task_ref, "installed_at": checked_at},
        ),
        activation_receipt=ContentAddress(
            ref=receipt.receipt_ref,
            sha256=receipt.receipt_hash,
        ),
    )
    store = ExecutionInvocationBundleStore(
        root=Path(checked_roots.invocation_store_root),
        composition_manifest=manifest,
    )
    root = ExecutionCompositionRoot(
        composition_manifest=manifest,
        invocation_store=store,
        claim_vault_root=Path(checked_roots.claim_vault_root),
        claim_cache_dir=Path(checked_roots.claim_cache_dir),
        claim_transaction_root=Path(checked_roots.claim_transaction_root),
        claim_receipt_root=Path(checked_roots.claim_receipt_root),
        claim_lock_root=Path(checked_roots.claim_lock_root),
        ports=_build_ports(
            descriptors,
            executor_descriptor=executor_descriptor,
            registry_projection=registry_projection,
        ),
    )
    return ClaimPublicationCompositionInstall(root=root, receipt=receipt)


def install_claim_publication_composition(
    *,
    roots: ClaimPublicationCompositionRoots | None = None,
    installed_at: str | datetime,
    install_task_ref: str,
    operator_inflection_ref: str = GATE0B_SLICE1_RATIFIED_INFLECTION_REF,
    request_ref: str = GATE0B_SLICE1_REQUEST_REF,
) -> ClaimPublicationCompositionInstall:
    install = build_claim_publication_composition(
        roots=roots,
        installed_at=installed_at,
        install_task_ref=install_task_ref,
        operator_inflection_ref=operator_inflection_ref,
        request_ref=request_ref,
    )
    assert install.root.invocation_store is not None
    _write_private_file(
        install.root.invocation_store.root / INSTALL_RECEIPT_FILENAME,
        claim_publication_install_receipt_bytes(install.receipt),
    )
    assert install.root.composition_manifest is not None
    _write_private_file(
        install.root.invocation_store.root / "composition-manifest.json",
        execution_composition_manifest_bytes(install.root.composition_manifest),
    )
    return install


def load_claim_publication_composition(
    invocation_store_root: Path,
) -> ClaimPublicationCompositionInstall:
    root_path = _absolute(invocation_store_root, label="claim-publication invocation store root")
    receipt = _load_install_receipt(root_path / INSTALL_RECEIPT_FILENAME)
    try:
        manifest_payload = (root_path / "composition-manifest.json").read_bytes()
        manifest_record = json.loads(manifest_payload.decode("ascii"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ExecutionAdmissionError(
            "gate0b_install_manifest_missing",
            "restore the exact installed composition manifest",
            str(root_path / "composition-manifest.json"),
        ) from exc
    manifest = ExecutionCompositionManifest.model_validate(manifest_record)
    if manifest_payload != execution_composition_manifest_bytes(manifest):
        raise ExecutionAdmissionError(
            "gate0b_install_manifest_noncanonical",
            "restore canonical ASCII JSON composition manifest bytes",
            str(root_path / "composition-manifest.json"),
        )
    store = ExecutionInvocationBundleStore(root=root_path, composition_manifest=manifest)
    root = ExecutionCompositionRoot(
        composition_manifest=manifest,
        invocation_store=store,
        claim_vault_root=Path(receipt.roots.claim_vault_root),
        claim_cache_dir=Path(receipt.roots.claim_cache_dir),
        claim_transaction_root=Path(receipt.roots.claim_transaction_root),
        claim_receipt_root=Path(receipt.roots.claim_receipt_root),
        claim_lock_root=Path(receipt.roots.claim_lock_root),
        ports=_build_ports(manifest.port_descriptors),
    )
    require_claim_publication_install_receipt(root)
    return ClaimPublicationCompositionInstall(root=root, receipt=receipt)


def _require_receipt_for_manifest(
    manifest: ExecutionCompositionManifest,
    *,
    invocation_store_root: Path,
    operation: str = GATE0B_CLAIM_PUBLICATION_OPERATION,
) -> Gate0BClaimPublicationInstallReceipt:
    if manifest.activation_receipt is None:
        raise ExecutionAdmissionError(
            "gate0b_install_receipt_missing",
            "install the exact Gate-0B claim-publication activation receipt",
            manifest.manifest_ref,
        )
    receipt = _load_install_receipt(invocation_store_root / INSTALL_RECEIPT_FILENAME)
    receipt_address = ContentAddress(ref=receipt.receipt_ref, sha256=receipt.receipt_hash)
    descriptor_address = ContentAddress(
        ref=manifest.port_descriptors.descriptors_ref,
        sha256=manifest.port_descriptors.descriptors_hash,
    )
    root_values = ClaimPublicationCompositionRoots(
        invocation_store_root=manifest.invocation_store_root,
        claim_vault_root=manifest.claim_vault_root,
        claim_cache_dir=manifest.claim_cache_dir,
        claim_transaction_root=manifest.claim_transaction_root,
        claim_receipt_root=manifest.claim_receipt_root,
        claim_lock_root=manifest.claim_lock_root,
    )
    if (
        receipt_address != manifest.activation_receipt
        or receipt.activation_generation != manifest.activation_generation
        or receipt.roots != root_values
        or receipt.port_descriptors != descriptor_address
        or receipt.capability_role != GATE0B_CLAIM_PUBLICATION_CAPABILITY_ROLE
        or receipt.execution_host != GATE0B_CLAIM_PUBLICATION_EXECUTION_HOST
        or operation not in receipt.supported_operations
        or receipt.may_authorize is not False
        or receipt.authorizes_direct_fallthrough is not False
    ):
        raise ExecutionAdmissionError(
            "gate0b_install_receipt_mismatch",
            "restore the activation receipt bound to this exact composition manifest",
            manifest.manifest_ref,
        )
    return receipt


def require_claim_publication_install_receipt(
    root: ExecutionCompositionRoot,
    *,
    operation: str = GATE0B_CLAIM_PUBLICATION_OPERATION,
) -> Gate0BClaimPublicationInstallReceipt:
    if root.composition_manifest is None or root.invocation_store is None:
        raise ExecutionAdmissionError(
            "execution_composition_activation_unvalidated",
            "obtain a Gate-0B validated install receipt before any effect path",
            "composition-uninstalled",
        )
    root.require_composition_ports()
    return _require_receipt_for_manifest(
        root.composition_manifest,
        invocation_store_root=root.invocation_store.root,
        operation=operation,
    )


def require_invocation_store_activation(
    store: ExecutionInvocationBundleStore,
) -> Gate0BClaimPublicationInstallReceipt:
    return _require_receipt_for_manifest(
        store.composition_manifest,
        invocation_store_root=store.root,
    )


__all__ = [
    "GATE0B_CLAIM_PUBLICATION_CAPABILITY_ROLE",
    "GATE0B_CLAIM_PUBLICATION_OPERATION",
    "GATE0B_SLICE1_RATIFIED_INFLECTION_REF",
    "GATE0B_SLICE1_REQUEST_REF",
    "Gate0BClaimPublicationInstallReceipt",
    "ClaimPublicationCompositionInstall",
    "ClaimPublicationCompositionRoots",
    "build_claim_publication_composition",
    "claim_publication_install_receipt_bytes",
    "claim_publication_executor_descriptor",
    "claim_publication_executor_registry_projection",
    "default_claim_publication_roots",
    "install_claim_publication_composition",
    "load_claim_publication_composition",
    "require_claim_publication_install_receipt",
    "require_invocation_store_activation",
]
