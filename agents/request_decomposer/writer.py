"""Lossless, recoverable writer for request decomposition graphs."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import yaml

from agents.request_decomposer.models import (
    DecompositionExternalDependency,
    PlannedTaskSpec,
    RequestDecomposition,
    RequestDecompositionPlan,
    TaskSpec,
)
from shared.frontmatter import parse_frontmatter
from shared.sdlc_task_store import (
    TaskIdentityWriteGuard,
    TaskIdentityWriteIntent,
    TaskStoreError,
    build_task_identity_index,
    load_task_identity_write_guard,
    open_task_store_directory_fd,
    prepare_task_identity_writes,
    reconcile_task_identity_writes,
    rename_task_store_no_replace,
    resolve_task_identity_projection,
)

_HISTORICAL_COMMIT_SCHEMA = "hapax.request-decomposition-commit.v1"
_PRE_GUARD_COMMIT_SCHEMA = "hapax.request-decomposition-commit.v2"
_COMMIT_SCHEMA = "hapax.request-decomposition-commit.v3"
_COMMIT_ID_SCHEMA = _PRE_GUARD_COMMIT_SCHEMA
_HISTORICAL_MANIFEST_SCHEMA = "hapax.request-decomposition-transaction.v1"
_PRE_GUARD_MANIFEST_SCHEMA = "hapax.request-decomposition-transaction.v2"
_MANIFEST_SCHEMA = "hapax.request-decomposition-transaction.v3"
_GENESIS_STAGE = "S0"
_TRANSACTION_DIR = ".request-decompose-transactions"
_RECEIPT_DIR = "_decomposition_receipts"
_LOCK_NAME = ".request-decompose.lock"

DEFAULT_TASK_ROOT = Path.home() / "Documents/Personal/20-projects/hapax-cc-tasks"


@dataclass
class _PreparedWrite:
    commit_id: str
    identity: dict[str, str]
    task_contents: dict[Path, bytes]
    request_path: Path | None
    request_preimage: bytes | None
    request_postimage: bytes | None
    receipt_path: Path
    receipt_content: bytes
    created_at: str
    transaction_path: Path
    source_guard_path: Path | None
    source_guard_preimage: bytes | None
    task_identity_guard: TaskIdentityWriteGuard | None = None


@dataclass(frozen=True)
class DecompositionJournalInspection:
    """Read-only state of one durable decomposition transaction journal."""

    commit_id: str
    state: Literal["prepared", "invalid", "committed"]
    request_id: str
    request_path: str
    plan_sha256: str
    task_ids: tuple[str, ...]
    reason_code: str
    schema: str
    history_only: bool
    system_atomic: Literal[False] = False
    atomicity_scope: Literal["module_local_recoverable_last_marker"] = (
        "module_local_recoverable_last_marker"
    )
    gate0b_hold_reason: Literal["single_committer_generation_fence_required"] = (
        "single_committer_generation_fence_required"
    )
    residue_policy: Literal["preserve_for_reconciliation"] = "preserve_for_reconciliation"
    cleanup_authorized: Literal[False] = False
    gate0b_cleanup_hold_reason: Literal["single_committer_residue_cleanup_required"] = (
        "single_committer_residue_cleanup_required"
    )
    projection_update_requirement: Literal["replace_only_no_in_place_mutation"] = (
        "replace_only_no_in_place_mutation"
    )
    may_authorize: Literal[False] = False


@dataclass
class _TaskRootAnchor:
    path: Path
    descriptor: int

    @classmethod
    def open(cls, path: Path, *, create: bool) -> _TaskRootAnchor:
        normalized = Path(os.path.abspath(os.path.expanduser(os.fspath(path))))
        descriptor = open_task_store_directory_fd(normalized, create=create)
        anchor = cls(path=normalized, descriptor=descriptor)
        try:
            anchor.assert_current()
            return anchor
        except Exception:
            anchor.close()
            raise

    def close(self) -> None:
        os.close(self.descriptor)

    def assert_current(self) -> None:
        current = open_task_store_directory_fd(self.path)
        try:
            opened_stat = os.fstat(self.descriptor)
            current_stat = os.fstat(current)
            if (
                opened_stat.st_dev != current_stat.st_dev
                or opened_stat.st_ino != current_stat.st_ino
            ):
                raise FileExistsError("task root identity changed during decomposition commit")
        finally:
            os.close(current)

def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(encoded)


def _render_note(frontmatter: dict[str, Any], body: str) -> str:
    yaml_text = yaml.safe_dump(
        frontmatter,
        sort_keys=False,
        allow_unicode=False,
        default_flow_style=False,
    ).strip()
    return f"---\n{yaml_text}\n---\n\n{body.rstrip()}\n"


def _lineage_refs(task_id: str, parent_request: str, parent_spec: str | None) -> list[str]:
    refs = [f"cc-task:{task_id}"]
    if parent_request:
        refs.append(f"request:{parent_request}")
    if parent_spec:
        refs.append(str(parent_spec))
    return refs


def _review_requirement(frontmatter: dict[str, Any], quality_floor: str) -> None:
    if quality_floor == "frontier_review_required":
        frontmatter["review_requirement"] = {
            "support_artifact_allowed": True,
            "independent_review_required": True,
            "authoritative_acceptor_profile": "frontier_full",
        }


def _render_task_note(
    task: TaskSpec,
    blocks: list[str],
    *,
    commit_id: str,
    receipt_path: Path,
    created_at: str,
) -> str:
    """Render legacy model output as a no-effect compatibility projection."""
    frontmatter: dict[str, Any] = {
        "type": "cc-task",
        "task_id": task.task_id,
        "title": task.title,
        "status": "blocked",
        "blocked_reason": task.blocked_reason
        or "decomposition_commit_requires_authority_transition",
        "assigned_to": "unassigned",
        "claimable": False,
        "stage": _GENESIS_STAGE,
        "priority": task.priority,
        "wsjf": task.wsjf,
        "effort_class": task.effort_class,
        "routing_class": task.routing_class,
        "requirement_vector": task.requirement_vector,
        "composition_tolerance": task.composition_tolerance,
        "requirement_vector_validity_mask": task.requirement_vector_validity_mask,
        "quality_floor": task.quality_floor,
        "mutation_surface": task.mutation_surface,
        "mutation_scope_refs": list(task.target_paths),
        "lineage_refs": _lineage_refs(task.task_id, task.parent_request, task.parent_spec),
        "target_paths": task.target_paths,
        "authority_level": "support_non_authoritative",
        "requested_authority_level": task.authority_level,
        "may_authorize": False,
        "implementation_authorized": False,
        "source_mutation_authorized": False,
        "docs_mutation_authorized": False,
        "runtime_mutation_authorized": False,
        "release_authorized": False,
        "public_mutation_authorized": False,
        "provider_spend_authorized": False,
        "route_metadata_schema": 1,
        "kind": task.kind,
        "risk_tier": "T2",
        "depends_on": task.depends_on,
        "blocks": blocks,
        "branch": None,
        "pr": None,
        "created_at": created_at,
        "updated_at": created_at,
        "claimed_at": None,
        "completed_at": None,
        "parent_request": task.parent_request,
        "parent_spec": task.parent_spec,
        "authority_case": task.authority_case,
        "decomposition_commit_id": commit_id,
        "decomposition_commit_receipt": str(receipt_path),
        "tags": ["cc-task", task.priority, "auto-decomposed", "authority-hold"],
    }
    if task.route_envelope is not None:
        frontmatter["route_envelope"] = task.route_envelope.model_dump(mode="json")
    if task.task_demand:
        frontmatter["task_demand"] = task.task_demand
    _review_requirement(frontmatter, task.quality_floor)
    criteria = "\n".join(f"- [ ] {criterion}" for criterion in task.acceptance_criteria)
    body = f"# {task.title}\n\n{task.intent}\n\n## Acceptance Criteria\n\n{criteria}"
    return _render_note(frontmatter, body)


def _external_dependencies_for_task(
    task: PlannedTaskSpec,
    bindings: dict[str, DecompositionExternalDependency],
) -> list[DecompositionExternalDependency]:
    return [bindings[dependency_id] for dependency_id in task.external_dependency_ids]


def _render_planned_task_note(
    task: PlannedTaskSpec,
    blocks: list[str],
    *,
    plan: RequestDecompositionPlan,
    external_bindings: dict[str, DecompositionExternalDependency],
    commit_id: str,
    receipt_path: Path,
    plan_ref: str,
    plan_sha256: str,
) -> str:
    external = _external_dependencies_for_task(task, external_bindings)
    legacy_external_task_ids = [
        binding.dependency_id for binding in external if binding.kind == "cc_task"
    ]
    authorization = task.initial_projection.authorization
    frontmatter: dict[str, Any] = {
        "type": "cc-task",
        "task_id": task.task_id,
        "title": task.title,
        "status": task.initial_projection.status,
        "blocked_reason": "decomposition_plan_hold",
        "assigned_to": task.initial_projection.assigned_to,
        "claimable": task.initial_projection.claimable,
        "stage": task.initial_projection.stage,
        "priority": task.priority,
        "wsjf": task.wsjf,
        "priority_basis": task.priority_basis,
        "priority_window": task.priority_window,
        "effort_class": task.effort_class,
        "routing_class": task.routing_class,
        "requirement_vector": task.requirement_vector,
        "composition_tolerance": task.composition_tolerance,
        "requirement_vector_validity_mask": task.requirement_vector_validity_mask,
        "task_demand": task.task_demand.model_dump(mode="json"),
        "quality_floor": task.quality_floor,
        "mutation_surface": task.mutation_surface,
        "scope_state": task.scope_state,
        "mutation_scope_refs": list(task.mutation_scope_refs),
        "lineage_refs": _lineage_refs(task.task_id, task.parent_request, task.parent_spec),
        "target_paths": list(task.target_paths),
        "authority_level": task.authority_level,
        "requested_authority_level": task.requested_authority_level,
        "may_authorize": task.may_authorize,
        "implementation_authorized": authorization.implementation_authorized,
        "source_mutation_authorized": authorization.source_mutation_authorized,
        "docs_mutation_authorized": authorization.docs_mutation_authorized,
        "runtime_mutation_authorized": authorization.runtime_mutation_authorized,
        "release_authorized": authorization.release_authorized,
        "public_mutation_authorized": authorization.public_mutation_authorized,
        "provider_spend_authorized": authorization.provider_spend_authorized,
        "hold_refs": list(task.initial_projection.hold_refs),
        "route_metadata_schema": 1,
        "kind": task.kind,
        "risk_tier": "T2",
        "depends_on": [*task.local_dependencies, *legacy_external_task_ids],
        "external_dependency_bindings": [binding.model_dump(mode="json") for binding in external],
        "blocks": blocks,
        "branch": None,
        "pr": None,
        "created_at": plan.created_at,
        "updated_at": plan.created_at,
        "claimed_at": None,
        "completed_at": None,
        "parent_request": task.parent_request,
        "parent_spec": task.parent_spec,
        "authority_case": task.authority_case,
        "decomposition_plan_schema": plan.schema_id,
        "decomposition_plan_id": plan.plan_id,
        "decomposition_plan_ref": plan_ref,
        "decomposition_plan_sha256": plan_sha256,
        "decomposition_source_bindings": [
            binding.model_dump(mode="json") for binding in plan.source_bindings
        ],
        "decomposition_commit_id": commit_id,
        "decomposition_commit_receipt": str(receipt_path),
        "decomposition_losses": list(task.losses),
        "decomposition_unresolveds": list(task.unresolveds),
        "tags": [
            "cc-task",
            task.priority,
            "precomputed-decomposition",
            "authority-hold",
        ],
    }
    _review_requirement(frontmatter, task.quality_floor)
    criteria = "\n".join(f"- [ ] {criterion}" for criterion in task.acceptance_criteria)
    body = f"# {task.title}\n\n{task.intent}\n\n## Acceptance Criteria\n\n{criteria}"
    return _render_note(frontmatter, body)


def _compute_blocks(tasks: list[TaskSpec]) -> dict[str, list[str]]:
    blocks: dict[str, list[str]] = {task.task_id: [] for task in tasks}
    for task in tasks:
        for dependency_id in task.depends_on:
            if dependency_id in blocks:
                blocks[dependency_id].append(task.task_id)
    return blocks


def _compute_planned_blocks(tasks: tuple[PlannedTaskSpec, ...]) -> dict[str, list[str]]:
    blocks: dict[str, list[str]] = {task.task_id: [] for task in tasks}
    for task in tasks:
        for dependency_id in task.local_dependencies:
            blocks[dependency_id].append(task.task_id)
    return blocks


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text or text in {"null", "None", "~"}:
        return []
    return [text]


def _top_level_key(line: str) -> str | None:
    if not line or line[0].isspace() or line.lstrip().startswith("#"):
        return None
    match = re.match(r"^([A-Za-z0-9_-]+):", line)
    return match.group(1) if match else None


def _continues_yaml_field(line: str) -> bool:
    stripped = line.strip()
    return not stripped or line[0].isspace() or line.startswith("- ")


def _update_frontmatter_bytes(raw: bytes, updates: dict[str, Any]) -> bytes:
    """Replace only named top-level YAML fields; preserve all other request bytes."""
    text = raw.decode("utf-8")
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise ValueError("parent request has no YAML frontmatter")
    close_index = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"),
        None,
    )
    if close_index is None:
        raise ValueError("parent request frontmatter is not closed")

    for key, value in updates.items():
        rendered = yaml.safe_dump(
            {key: value},
            sort_keys=False,
            allow_unicode=False,
            default_flow_style=False,
        ).splitlines(keepends=True)
        start = next(
            (index for index in range(1, close_index) if _top_level_key(lines[index]) == key),
            None,
        )
        if start is None:
            lines[close_index:close_index] = rendered
            close_index += len(rendered)
            continue
        end = start + 1
        while end < close_index and _continues_yaml_field(lines[end]):
            end += 1
        lines[start:end] = rendered
        close_index += len(rendered) - (end - start)
    return "".join(lines).encode("utf-8")


def _request_frontmatter(raw: bytes) -> dict[str, Any]:
    frontmatter, _body = parse_frontmatter(raw.decode("utf-8"))
    if not frontmatter:
        raise ValueError("parent request has no parseable frontmatter")
    return dict(frontmatter)


def _task_root_path(task_root: Path, *relative: str) -> Path:
    """Resolve one logical task-root path while rejecting every symlink hop below it."""

    logical_root = task_root.expanduser()
    if logical_root.is_symlink() or (logical_root.exists() and not logical_root.is_dir()):
        raise ValueError("task root must be one real directory")
    physical_root = logical_root.resolve(strict=False)
    candidate = logical_root.joinpath(*relative)
    expected_parent = physical_root.joinpath(*relative[:-1])
    if candidate.parent.resolve(strict=False) != expected_parent or candidate.is_symlink():
        raise ValueError(f"decomposition path escapes task root: {candidate}")
    return candidate


def _task_output_path(task_root: Path, task_id: str) -> Path:
    return _task_root_path(task_root, "active", f"{task_id}.md")


_REQUEST_ADMISSION_FIELDS = (
    "request_id",
    "status",
    "authority_level",
    "planning_case",
    "authority_case",
    "parent_spec",
    "parent_plan",
    "cctv_intake_receipt",
    "cctv_intake_verdict",
    "cctv_route_resource_admission",
    "cctv_capability_receipts",
    "downstream_tasks",
)


def request_admission_sha256(request_fields: dict[str, Any]) -> str:
    projection: dict[str, Any] = {}
    for field in _REQUEST_ADMISSION_FIELDS:
        value = request_fields.get(field)
        if field in {"cctv_capability_receipts", "downstream_tasks"}:
            value = _as_string_list(value)
        projection[field] = value
    return _canonical_hash(
        {
            "schema": "hapax.request-decomposition-admission-frontier.v1",
            "projection": projection,
        }
    )


def _plan_pointer(
    request_path: Path,
    request_frontmatter: dict[str, Any],
    plan: RequestDecompositionPlan,
) -> tuple[str, str]:
    raw_ref = str(request_frontmatter.get("decomposition_plan_ref") or "").strip()
    expected_hash = str(request_frontmatter.get("decomposition_plan_sha256") or "").strip()
    if not raw_ref or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise ValueError("request requires decomposition_plan_ref and decomposition_plan_sha256")
    plan_path = Path(raw_ref).expanduser()
    if not plan_path.is_absolute():
        plan_path = request_path.parent / plan_path
    plan_bytes = plan_path.read_bytes()
    if _sha256_bytes(plan_bytes) != expected_hash:
        raise ValueError("decomposition plan hash does not match request binding")
    loaded = yaml.safe_load(plan_bytes)
    if RequestDecompositionPlan.model_validate(loaded) != plan:
        raise ValueError("decomposition plan bytes do not match the supplied plan")
    return str(plan_path), expected_hash


def _verify_plan_bindings(
    plan: RequestDecompositionPlan,
    *,
    include_external: bool = True,
) -> None:
    bindings = plan.source_bindings
    if include_external:
        bindings = (*bindings, *plan.external_dependencies)
    for binding in bindings:
        path = Path(binding.path).expanduser()
        if not path.is_file():
            raise ValueError(f"decomposition binding is missing: {path}")
        if _sha256_path(path) != binding.sha256:
            raise ValueError(f"decomposition binding hash drift: {path}")
        if isinstance(binding, DecompositionExternalDependency) and binding.kind == "cc_task":
            fields, _body = parse_frontmatter(path)
            if str(fields.get("task_id") or "").strip() != binding.dependency_id:
                raise ValueError(
                    f"external task binding identity mismatch: {binding.dependency_id}"
                )


def _verify_plan_request_frontier(
    plan: RequestDecompositionPlan,
    request_path: Path,
    request_fields: dict[str, Any],
) -> None:
    if request_admission_sha256(request_fields) != plan.request_admission_sha256:
        raise ValueError("request admission frontier differs from decomposition plan")
    if str(request_fields.get("status") or "").strip() != "accepted_for_planning":
        raise ValueError("request is not accepted for planning")
    if str(request_fields.get("cctv_intake_verdict") or "").strip() not in {
        "ready_to_plan",
        "advance",
        "admitted",
    }:
        raise ValueError("request lacks a ready CCTV intake verdict")
    if str(request_fields.get("cctv_route_resource_admission") or "").strip() != "admitted":
        raise ValueError("request lacks admitted CCTV route/resource evidence")
    if not _as_string_list(request_fields.get("cctv_capability_receipts")):
        raise ValueError("request lacks CCTV capability receipts")
    if not str(request_fields.get("cctv_intake_receipt") or "").strip():
        raise ValueError("request lacks a CCTV intake receipt")

    existing = _as_string_list(request_fields.get("downstream_tasks"))
    if existing != list(plan.expected_existing_downstream_tasks):
        raise FileExistsError(
            "request downstream_tasks frontier differs from decomposition plan expectation"
        )
    planning_case = str(
        request_fields.get("planning_case") or request_fields.get("authority_case") or ""
    ).strip()
    parent_spec = str(
        request_fields.get("parent_spec") or request_fields.get("parent_plan") or request_path
    ).strip()
    parent_request = request_path.name
    for task in plan.tasks:
        if task.authority_case != planning_case:
            raise ValueError(f"planned task authority case differs from request: {task.task_id}")
        if task.parent_request != parent_request:
            raise ValueError(f"planned task parent request differs from request: {task.task_id}")
        if task.parent_spec != parent_spec:
            raise ValueError(f"planned task parent spec differs from request: {task.task_id}")


def _planned_commit_id(plan: RequestDecompositionPlan, plan_sha256: str) -> str:
    return _canonical_hash(
        {
            "schema": _COMMIT_ID_SCHEMA,
            "genesis_stage": _GENESIS_STAGE,
            "plan_id": plan.plan_id,
            "plan_sha256": plan_sha256,
            "request_id": plan.request_id,
            "request_admission_sha256": plan.request_admission_sha256,
            "request_source_path": plan.request_source_path,
            "request_source_sha256": plan.request_source_sha256,
            "task_ids": [task.task_id for task in plan.tasks],
        }
    )


def _legacy_commit_id(
    decomposition: RequestDecomposition,
    request_preimage: bytes | None,
) -> str:
    request_sha256 = decomposition.request_source_sha256 or (
        _sha256_bytes(request_preimage) if request_preimage else None
    )
    return _canonical_hash(
        {
            "schema": _COMMIT_ID_SCHEMA,
            "genesis_stage": _GENESIS_STAGE,
            "request_id": decomposition.request_id,
            "request_path": decomposition.request_path,
            "request_sha256": request_sha256,
            "task_ids": [task.task_id for task in decomposition.tasks],
            "model": decomposition.decomposition_model,
        }
    )


def _receipt_bytes(
    *,
    commit_id: str,
    identity: dict[str, str],
    task_contents: dict[Path, bytes],
    task_identity_guard: TaskIdentityWriteGuard,
    request_path: Path | None,
    request_preimage: bytes | None,
    request_postimage: bytes | None,
    created_at: str,
) -> bytes:
    payload: dict[str, Any] = {
        "schema": _COMMIT_SCHEMA,
        "commit_id": commit_id,
        "state": "committed",
        "created_at": created_at,
        "identity": identity,
        "task_identity_guard": task_identity_guard.to_record(),
        "tasks": [],
        "request": None,
        "may_authorize": False,
    }
    contents_by_relative = {
        path.resolve(strict=False).relative_to(task_identity_guard.vault_root).as_posix(): (
            path,
            content,
        )
        for path, content in task_contents.items()
    }
    for intent in task_identity_guard.intents:
        path, content = contents_by_relative[intent.relative_path]
        if _sha256_bytes(content) != intent.content_sha256:
            raise ValueError("decomposition receipt task bytes differ from identity guard")
        payload["tasks"].append(
            {
                "content_sha256": intent.content_sha256,
                "path": str(path),
                "relative_path": intent.relative_path,
                "state": intent.state,
                "task_id": intent.task_id,
            }
        )
    if request_path is not None and request_preimage is not None and request_postimage is not None:
        payload["request"] = {
            "path": str(request_path),
            "preimage_sha256": _sha256_bytes(request_preimage),
            "postimage_sha256": _sha256_bytes(request_postimage),
        }
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=False).encode("utf-8")


def _prepare_planned_write(
    plan: RequestDecompositionPlan,
    task_root: Path,
) -> _PreparedWrite:
    if not plan.materializable:
        raise ValueError("decomposition plan has unresolved scope, loss, or uncertainty")

    request_path = Path(plan.request_path).expanduser()
    request_preimage = request_path.read_bytes()
    request_fields = _request_frontmatter(request_preimage)
    request_id = str(request_fields.get("request_id") or request_path.stem).strip()
    if request_id != plan.request_id:
        raise ValueError("request identity does not match decomposition plan")
    plan_ref, plan_sha256 = _plan_pointer(request_path, request_fields, plan)
    commit_id = _planned_commit_id(plan, plan_sha256)
    receipt_path = _task_root_path(task_root, _RECEIPT_DIR, f"{commit_id}.yaml")

    external_bindings = {binding.dependency_id: binding for binding in plan.external_dependencies}
    blocks = _compute_planned_blocks(plan.tasks)
    task_contents: dict[Path, bytes] = {}
    for task in plan.tasks:
        path = _task_output_path(task_root, task.task_id)
        content = _render_planned_task_note(
            task,
            blocks[task.task_id],
            plan=plan,
            external_bindings=external_bindings,
            commit_id=commit_id,
            receipt_path=receipt_path,
            plan_ref=plan_ref,
            plan_sha256=plan_sha256,
        ).encode("utf-8")
        task_contents[path] = content

    identity = {
        "kind": "precomputed_plan",
        "genesis_stage": _GENESIS_STAGE,
        "plan_id": plan.plan_id,
        "plan_sha256": plan_sha256,
        "request_id": plan.request_id,
        "request_path": str(request_path),
        "request_admission_sha256": plan.request_admission_sha256,
        "request_source_path": plan.request_source_path,
        "request_source_sha256": plan.request_source_sha256,
    }
    return _PreparedWrite(
        commit_id=commit_id,
        identity=identity,
        task_contents=task_contents,
        request_path=None,
        request_preimage=None,
        request_postimage=None,
        receipt_path=receipt_path,
        receipt_content=b"",
        created_at=plan.created_at,
        transaction_path=_task_root_path(task_root, _TRANSACTION_DIR, commit_id),
        source_guard_path=request_path,
        source_guard_preimage=request_preimage,
    )


def _prepare_legacy_write(
    decomposition: RequestDecomposition,
    task_root: Path,
) -> _PreparedWrite:
    request_path = Path(decomposition.request_path).expanduser()
    if request_path.is_symlink() or not request_path.is_file():
        raise ValueError("model decomposition requires one existing request source file")
    request_preimage = request_path.read_bytes()
    current_request_sha256 = _sha256_bytes(request_preimage)
    if decomposition.request_source_sha256 is None:
        raise ValueError("model decomposition requires an exact request source binding")
    if (
        decomposition.request_source_sha256 is not None
        and current_request_sha256 != decomposition.request_source_sha256
    ):
        raise FileExistsError("request source changed after decomposition")
    request_fields = _request_frontmatter(request_preimage) if request_preimage is not None else {}
    existing = _as_string_list(request_fields.get("downstream_tasks"))
    if existing:
        raise FileExistsError(
            f"refusing duplicate decomposition for {request_path.name}; "
            f"already has downstream_tasks: {', '.join(existing)}"
        )
    created_at = str(
        request_fields.get("updated_at")
        or request_fields.get("created_at")
        or "1970-01-01T00:00:00Z"
    )
    commit_id = _legacy_commit_id(decomposition, request_preimage)
    receipt_path = _task_root_path(task_root, _RECEIPT_DIR, f"{commit_id}.yaml")
    blocks = _compute_blocks(decomposition.tasks)
    task_contents = {
        _task_output_path(task_root, task.task_id): _render_task_note(
            task,
            blocks[task.task_id],
            commit_id=commit_id,
            receipt_path=receipt_path,
            created_at=created_at,
        ).encode("utf-8")
        for task in decomposition.tasks
    }
    identity = {
        "kind": "model_proposal",
        "genesis_stage": _GENESIS_STAGE,
        "request_id": decomposition.request_id,
        "request_path": str(request_path),
        "request_sha256": current_request_sha256 or "absent",
    }
    return _PreparedWrite(
        commit_id=commit_id,
        identity=identity,
        task_contents=task_contents,
        request_path=None,
        request_preimage=None,
        request_postimage=None,
        receipt_path=receipt_path,
        receipt_content=b"",
        created_at=created_at,
        transaction_path=_task_root_path(task_root, _TRANSACTION_DIR, commit_id),
        source_guard_path=request_path if request_preimage is not None else None,
        source_guard_preimage=request_preimage,
    )


def _prepare_write(
    decomposition: RequestDecomposition | RequestDecompositionPlan,
    task_root: Path,
) -> _PreparedWrite:
    if isinstance(decomposition, RequestDecompositionPlan):
        return _prepare_planned_write(decomposition, task_root)
    return _prepare_legacy_write(decomposition, task_root)


def _prepared_task_intents(prepared: _PreparedWrite) -> tuple[TaskIdentityWriteIntent, ...]:
    task_root = prepared.receipt_path.parent.parent.resolve(strict=False)
    intents = []
    for path, content in sorted(prepared.task_contents.items(), key=lambda item: str(item[0])):
        relative_path = path.resolve(strict=False).relative_to(task_root).as_posix()
        parts = PurePosixPath(relative_path).parts
        if len(parts) != 2 or parts[0] not in {"active", "closed", "refused"}:
            raise ValueError("decomposition task destination is not one canonical state child")
        frontmatter, _body = parse_frontmatter(content.decode("utf-8"))
        task_id = str(frontmatter.get("task_id") or "").strip()
        intents.append(
            TaskIdentityWriteIntent.create(
                task_id=task_id,
                state=parts[0],
                relative_path=relative_path,
                content_sha256=_sha256_bytes(content),
            )
        )
    return tuple(sorted(intents, key=lambda intent: (intent.state, intent.relative_path)))


def _bind_task_identity_guard(
    prepared: _PreparedWrite,
    guard: TaskIdentityWriteGuard,
) -> _PreparedWrite:
    if guard.vault_root != prepared.receipt_path.parent.parent.resolve(strict=False):
        raise ValueError("decomposition identity guard task root mismatch")
    if guard.intents != _prepared_task_intents(prepared):
        raise ValueError("decomposition identity guard task projection mismatch")
    prepared.task_identity_guard = guard
    prepared.receipt_content = _receipt_bytes(
        commit_id=prepared.commit_id,
        identity=prepared.identity,
        task_contents=prepared.task_contents,
        task_identity_guard=guard,
        request_path=prepared.request_path,
        request_preimage=prepared.request_preimage,
        request_postimage=prepared.request_postimage,
        created_at=prepared.created_at,
    )
    return prepared


def _bind_new_task_identity_guard(prepared: _PreparedWrite) -> _PreparedWrite:
    task_root = prepared.receipt_path.parent.parent.resolve(strict=False)
    intents = _prepared_task_intents(prepared)
    staged_bytes = {
        path.resolve(strict=False).relative_to(task_root).as_posix(): content
        for path, content in prepared.task_contents.items()
    }
    guard = prepare_task_identity_writes(
        build_task_identity_index(task_root),
        intents,
        staged_bytes,
    )
    return _bind_task_identity_guard(prepared, guard)


def _bind_persisted_task_identity_guard(prepared: _PreparedWrite) -> _PreparedWrite:
    manifest_path = prepared.transaction_path / "manifest.yaml"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("decomposition transaction manifest is not one private file")
    manifest = yaml.safe_load(manifest_path.read_bytes())
    if not isinstance(manifest, dict) or manifest.get("schema") != _MANIFEST_SCHEMA:
        raise ValueError("decomposition transaction lacks a recoverable v3 identity guard")
    record = manifest.get("task_identity_guard")
    if not isinstance(record, dict):
        raise ValueError("decomposition transaction identity guard is malformed")
    guard = load_task_identity_write_guard(
        record,
        vault_root=prepared.receipt_path.parent.parent,
    )
    return _bind_task_identity_guard(prepared, guard)


def _prepared_task_projection(prepared: _PreparedWrite) -> list[dict[str, str]]:
    guard = prepared.task_identity_guard
    if guard is None:
        raise ValueError("decomposition transaction lacks a task identity guard")
    contents_by_relative = {
        path.resolve(strict=False).relative_to(guard.vault_root).as_posix(): (path, content)
        for path, content in prepared.task_contents.items()
    }
    projection = []
    for index, intent in enumerate(guard.intents):
        path, content = contents_by_relative[intent.relative_path]
        if _sha256_bytes(content) != intent.content_sha256:
            raise ValueError("decomposition staged task differs from identity intent")
        projection.append(
            {
                "content_sha256": intent.content_sha256,
                "final": str(path),
                "relative_path": intent.relative_path,
                "stage": f"tasks/{index}.md",
                "state": intent.state,
                "task_id": intent.task_id,
            }
        )
    return projection


def _manifest_payload(prepared: _PreparedWrite) -> dict[str, Any]:
    guard = prepared.task_identity_guard
    if guard is None:
        raise ValueError("decomposition manifest requires a task identity guard")
    payload: dict[str, Any] = {
        "schema": _MANIFEST_SCHEMA,
        "commit_id": prepared.commit_id,
        "identity": prepared.identity,
        "task_identity_guard": guard.to_record(),
        "tasks": _prepared_task_projection(prepared),
        "request": None,
        "receipt": {
            "stage": "receipt.yaml",
            "final": str(prepared.receipt_path),
            "sha256": _sha256_bytes(prepared.receipt_content),
        },
        "may_authorize": False,
    }
    if prepared.request_path is not None:
        assert prepared.request_preimage is not None
        assert prepared.request_postimage is not None
        payload["request"] = {
            "pre_stage": "request.pre",
            "post_stage": "request.post",
            "final": str(prepared.request_path),
            "preimage_sha256": _sha256_bytes(prepared.request_preimage),
            "postimage_sha256": _sha256_bytes(prepared.request_postimage),
        }
    payload["manifest_sha256"] = _canonical_hash(payload)
    return payload


def _write_bytes(path: Path, content: bytes) -> None:
    parent_fd = open_task_store_directory_fd(path.parent)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        descriptor = os.open(path.name, flags, 0o600, dir_fd=parent_fd)
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            _assert_path_directory_identity(path.parent, parent_fd)
        finally:
            os.close(descriptor)
    finally:
        os.close(parent_fd)


def _fsync_dir(path: Path) -> None:
    descriptor = open_task_store_directory_fd(path)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _assert_path_directory_identity(path: Path, descriptor: int) -> None:
    current = open_task_store_directory_fd(path)
    try:
        opened_stat = os.fstat(descriptor)
        current_stat = os.fstat(current)
        if opened_stat.st_dev != current_stat.st_dev or opened_stat.st_ino != current_stat.st_ino:
            raise FileExistsError(
                f"task-store parent identity changed during decomposition commit: {path}"
            )
    finally:
        os.close(current)


def _read_file_no_follow(path: Path) -> bytes:
    parent_fd = open_task_store_directory_fd(path.parent)
    try:
        content = _read_named_file(parent_fd, path.name)
        _assert_path_directory_identity(path.parent, parent_fd)
        return content
    finally:
        os.close(parent_fd)


def _read_named_file(parent_fd: int, name: str) -> bytes:
    descriptor = os.open(
        name,
        os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
        dir_fd=parent_fd,
    )
    try:
        return _read_regular_descriptor(descriptor, label=name)
    finally:
        os.close(descriptor)


def _read_regular_descriptor(descriptor: int, *, label: str) -> bytes:
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"decomposition path is not one regular file: {label}")
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while chunk := os.read(descriptor, 1024 * 1024):
        chunks.append(chunk)
    return b"".join(chunks)


@contextmanager
def _locked_task_root(task_root: Path):
    anchor = _TaskRootAnchor.open(task_root, create=True)
    try:
        flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW
        lock = os.open(_LOCK_NAME, flags, 0o600, dir_fd=anchor.descriptor)
        try:
            if not stat.S_ISREG(os.fstat(lock).st_mode):
                raise ValueError("decomposition lock is not one regular non-symlink file")
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                anchor.assert_current()
                yield anchor
                anchor.assert_current()
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
        finally:
            os.close(lock)
    finally:
        anchor.close()


def _stage_transaction(prepared: _PreparedWrite) -> dict[str, Any]:
    transaction_path = prepared.transaction_path
    task_root = prepared.receipt_path.parent.parent
    if _task_root_path(task_root, _TRANSACTION_DIR, prepared.commit_id) != transaction_path:
        raise ValueError("decomposition transaction destination changed after planning")
    manifest = _manifest_payload(prepared)
    manifest_bytes = yaml.safe_dump(manifest, sort_keys=False, allow_unicode=False).encode("utf-8")
    if transaction_path.exists():
        _validate_prepared_transaction(prepared, manifest_bytes=manifest_bytes)
        return manifest

    parent_fd = open_task_store_directory_fd(transaction_path.parent, create=True)
    try:
        staging_name = f".{prepared.commit_id}.staging-{secrets.token_hex(8)}"
        os.mkdir(staging_name, 0o700, dir_fd=parent_fd)
        staging = transaction_path.parent / staging_name
        (staging / "tasks").mkdir()
        for entry, content in zip(
            manifest["tasks"],
            (
                content
                for _path, content in sorted(
                    prepared.task_contents.items(), key=lambda item: str(item[0])
                )
            ),
            strict=True,
        ):
            _write_bytes(staging / entry["stage"], content)
        if prepared.request_path is not None:
            assert prepared.request_preimage is not None
            assert prepared.request_postimage is not None
            _write_bytes(staging / "request.pre", prepared.request_preimage)
            _write_bytes(staging / "request.post", prepared.request_postimage)
        _write_bytes(staging / "receipt.yaml", prepared.receipt_content)
        _write_bytes(staging / "manifest.yaml", manifest_bytes)
        _fsync_dir(staging / "tasks")
        _fsync_dir(staging)
        _assert_path_directory_identity(transaction_path.parent, parent_fd)
        rename_task_store_no_replace(
            parent_fd,
            staging_name,
            parent_fd,
            transaction_path.name,
        )
        os.fsync(parent_fd)
        _assert_path_directory_identity(transaction_path.parent, parent_fd)
    finally:
        os.close(parent_fd)
    return manifest


def _validate_exact_file(path: Path, expected: bytes, *, label: str) -> None:
    try:
        observed = _read_file_no_follow(path)
    except (OSError, TaskStoreError, ValueError):
        observed = None
    if observed != expected:
        raise ValueError(f"decomposition transaction postimage mismatch: {label}")


@contextmanager
def _locked_source_guard(prepared: _PreparedWrite):
    path = prepared.source_guard_path
    expected = prepared.source_guard_preimage
    if path is None or expected is None:
        yield lambda: None
        return
    if path.is_symlink():
        raise FileExistsError("decomposition source guard cannot follow a symlink")
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)

        def assert_current() -> None:
            opened = os.fstat(descriptor)
            named = os.stat(path, follow_symlinks=False)
            if (
                not stat.S_ISREG(opened.st_mode)
                or not stat.S_ISREG(named.st_mode)
                or opened.st_dev != named.st_dev
                or opened.st_ino != named.st_ino
            ):
                raise FileExistsError("decomposition source identity changed during commit")
            os.lseek(descriptor, 0, os.SEEK_SET)
            chunks: list[bytes] = []
            remaining = len(expected) + 1
            while remaining:
                chunk = os.read(descriptor, remaining)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            if b"".join(chunks) != expected:
                raise FileExistsError("decomposition source bytes changed during commit")

        assert_current()
        yield assert_current
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _validate_prepared_transaction(
    prepared: _PreparedWrite,
    *,
    manifest_bytes: bytes | None = None,
) -> dict[str, Any]:
    transaction_path = prepared.transaction_path
    task_root = prepared.receipt_path.parent.parent
    if _task_root_path(task_root, _TRANSACTION_DIR, prepared.commit_id) != transaction_path:
        raise ValueError("decomposition transaction path escaped task root")
    if transaction_path.is_symlink() or not transaction_path.is_dir():
        raise ValueError("decomposition transaction path is not a private directory")
    tasks_path = transaction_path / "tasks"
    if tasks_path.is_symlink() or not tasks_path.is_dir():
        raise ValueError("decomposition transaction tasks path is not a private directory")
    if any(path.is_symlink() for path in transaction_path.rglob("*")):
        raise ValueError("decomposition transaction tree cannot contain symlinks")
    manifest = _manifest_payload(prepared)
    expected_manifest = manifest_bytes or yaml.safe_dump(
        manifest, sort_keys=False, allow_unicode=False
    ).encode("utf-8")
    _validate_exact_file(
        transaction_path / "manifest.yaml",
        expected_manifest,
        label="manifest.yaml",
    )
    expected_paths = {"manifest.yaml", "receipt.yaml"}
    for entry, content in zip(
        manifest["tasks"],
        (
            content
            for _path, content in sorted(
                prepared.task_contents.items(), key=lambda item: str(item[0])
            )
        ),
        strict=True,
    ):
        relative = str(entry["stage"])
        expected_paths.add(relative)
        _validate_exact_file(transaction_path / relative, content, label=relative)
    if prepared.request_path is not None:
        assert prepared.request_preimage is not None
        assert prepared.request_postimage is not None
        expected_paths.update({"request.pre", "request.post"})
        _validate_exact_file(
            transaction_path / "request.pre",
            prepared.request_preimage,
            label="request.pre",
        )
        _validate_exact_file(
            transaction_path / "request.post",
            prepared.request_postimage,
            label="request.post",
        )
    _validate_exact_file(
        transaction_path / "receipt.yaml",
        prepared.receipt_content,
        label="receipt.yaml",
    )
    actual_paths = {
        path.relative_to(transaction_path).as_posix()
        for path in transaction_path.rglob("*")
        if not path.is_dir()
    }
    if actual_paths != expected_paths:
        raise ValueError("decomposition transaction file closure mismatch")
    return manifest


def _journal_inspection(
    commit_id: str,
    manifest: object,
    *,
    state: Literal["prepared", "invalid", "committed"],
    reason_code: str,
    history_only: bool = False,
    task_ids: tuple[str, ...] = (),
) -> DecompositionJournalInspection:
    identity = manifest.get("identity") if isinstance(manifest, dict) else None
    identity = identity if isinstance(identity, dict) else {}
    return DecompositionJournalInspection(
        commit_id=commit_id,
        state=state,
        request_id=str(identity.get("request_id") or "").strip(),
        request_path=str(identity.get("request_path") or "").strip(),
        plan_sha256=str(identity.get("plan_sha256") or "").strip(),
        task_ids=task_ids,
        reason_code=reason_code,
        schema=str(manifest.get("schema") or "") if isinstance(manifest, dict) else "",
        history_only=history_only,
    )


def _journal_stage_path(transaction_path: Path, raw_relative: object) -> Path:
    relative = str(raw_relative or "").strip()
    candidate = PurePosixPath(relative)
    if (
        not relative
        or candidate.is_absolute()
        or ".." in candidate.parts
        or candidate.as_posix() != relative
    ):
        raise ValueError("decomposition journal contains an invalid staged path")
    path = transaction_path.joinpath(*candidate.parts)
    if path.is_symlink():
        raise ValueError("decomposition journal staged path cannot be a symlink")
    return path


def _inspect_decomposition_journal(
    transaction_path: Path,
    task_root: Path,
) -> DecompositionJournalInspection:
    commit_id = transaction_path.name
    manifest: object = None
    try:
        if transaction_path.is_symlink() or not transaction_path.is_dir():
            raise ValueError("decomposition journal is not a private directory")
        if any(path.is_symlink() for path in transaction_path.rglob("*")):
            raise ValueError("decomposition journal tree cannot contain symlinks")
        manifest_path = transaction_path / "manifest.yaml"
        if not manifest_path.is_file():
            raise ValueError("decomposition journal manifest is missing")
        manifest_bytes = manifest_path.read_bytes()
        manifest = yaml.safe_load(manifest_bytes)
        if not isinstance(manifest, dict):
            raise ValueError("decomposition journal manifest is malformed")
        manifest_schema = manifest.get("schema")
        if manifest_schema not in {
            _HISTORICAL_MANIFEST_SCHEMA,
            _PRE_GUARD_MANIFEST_SCHEMA,
            _MANIFEST_SCHEMA,
        }:
            raise ValueError("decomposition journal schema is unsupported")
        history_only = manifest_schema != _MANIFEST_SCHEMA
        history_version = "v1" if manifest_schema == _HISTORICAL_MANIFEST_SCHEMA else "v2"
        if manifest.get("commit_id") != commit_id:
            raise ValueError("decomposition journal commit identity differs from its path")
        if manifest.get("may_authorize") is not False:
            raise ValueError("decomposition journal cannot authorize")
        manifest_without_hash = dict(manifest)
        claimed_manifest_hash = manifest_without_hash.pop("manifest_sha256", None)
        if claimed_manifest_hash != _canonical_hash(manifest_without_hash):
            raise ValueError("decomposition journal manifest hash mismatch")

        expected_files = {"manifest.yaml", "receipt.yaml"}
        expected_dirs = {"tasks"}
        manifest_tasks = manifest.get("tasks")
        if not isinstance(manifest_tasks, list) or not manifest_tasks:
            raise ValueError("decomposition journal has no task postimages")
        guard = None
        if not history_only:
            guard_record = manifest.get("task_identity_guard")
            if not isinstance(guard_record, dict):
                raise ValueError("decomposition journal identity guard is malformed")
            guard = load_task_identity_write_guard(guard_record, vault_root=task_root)
            if len(guard.intents) != len(manifest_tasks):
                raise ValueError("decomposition journal guard task cardinality mismatch")
        task_receipt_projection: list[dict[str, str]] = []
        task_id_hints: list[str] = []
        for index, entry in enumerate(manifest_tasks):
            if not isinstance(entry, dict):
                raise ValueError("decomposition journal task entry is malformed")
            stage = _journal_stage_path(transaction_path, entry.get("stage"))
            relative = stage.relative_to(transaction_path).as_posix()
            expected_files.add(relative)
            expected_hash = str(entry.get("sha256" if history_only else "content_sha256") or "")
            if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
                raise ValueError("decomposition journal task hash is malformed")
            if _sha256_path(stage) != expected_hash:
                raise ValueError("decomposition journal task hash mismatch")
            staged_fields, _body = parse_frontmatter(stage.read_text(encoding="utf-8"))
            staged_task_id = str(staged_fields.get("task_id") or "").strip()
            if not staged_task_id:
                raise ValueError("decomposition journal staged task identity is missing")
            task_id_hints.append(staged_task_id)
            if history_only:
                final = Path(str(entry.get("final") or "")).expanduser()
                if _task_output_path(task_root, final.name.removesuffix(".md")) != final:
                    raise ValueError("decomposition journal task destination escaped task root")
                task_receipt_projection.append({"path": str(final), "sha256": expected_hash})
                continue
            assert guard is not None
            intent = guard.intents[index]
            exact_entry = {
                "content_sha256": intent.content_sha256,
                "final": str(guard.vault_root / intent.relative_path),
                "relative_path": intent.relative_path,
                "stage": f"tasks/{index}.md",
                "state": intent.state,
                "task_id": intent.task_id,
            }
            if entry != exact_entry or staged_task_id != intent.task_id:
                raise ValueError("decomposition journal task projection differs from guard")
            task_receipt_projection.append(
                {
                    "content_sha256": intent.content_sha256,
                    "path": str(guard.vault_root / intent.relative_path),
                    "relative_path": intent.relative_path,
                    "state": intent.state,
                    "task_id": intent.task_id,
                }
            )

        request_entry = manifest.get("request")
        if request_entry is not None:
            if not isinstance(request_entry, dict):
                raise ValueError("decomposition journal request entry is malformed")
            for stage_field, hash_field in (
                ("pre_stage", "preimage_sha256"),
                ("post_stage", "postimage_sha256"),
            ):
                stage = _journal_stage_path(transaction_path, request_entry.get(stage_field))
                relative = stage.relative_to(transaction_path).as_posix()
                expected_files.add(relative)
                if _sha256_path(stage) != str(request_entry.get(hash_field) or ""):
                    raise ValueError("decomposition journal request hash mismatch")

        receipt_entry = manifest.get("receipt")
        if not isinstance(receipt_entry, dict):
            raise ValueError("decomposition journal receipt entry is malformed")
        staged_receipt = _journal_stage_path(transaction_path, receipt_entry.get("stage"))
        if staged_receipt.relative_to(transaction_path).as_posix() != "receipt.yaml":
            raise ValueError("decomposition journal receipt stage is noncanonical")
        receipt_hash = str(receipt_entry.get("sha256") or "")
        if _sha256_path(staged_receipt) != receipt_hash:
            raise ValueError("decomposition journal staged receipt hash mismatch")
        receipt_path = _task_root_path(task_root, _RECEIPT_DIR, f"{commit_id}.yaml")
        if Path(str(receipt_entry.get("final") or "")).expanduser() != receipt_path:
            raise ValueError("decomposition journal receipt destination escaped task root")

        actual_files = {
            path.relative_to(transaction_path).as_posix()
            for path in transaction_path.rglob("*")
            if path.is_file()
        }
        actual_dirs = {
            path.relative_to(transaction_path).as_posix()
            for path in transaction_path.rglob("*")
            if path.is_dir()
        }
        if actual_files != expected_files or actual_dirs != expected_dirs:
            raise ValueError("decomposition journal file closure mismatch")

        if not receipt_path.exists():
            if history_only:
                return _journal_inspection(
                    commit_id,
                    manifest,
                    state="invalid",
                    reason_code=f"historical_{history_version}_prepared_no_recovery",
                    history_only=True,
                    task_ids=tuple(task_id_hints),
                )
            return _journal_inspection(
                commit_id,
                manifest,
                state="prepared",
                reason_code="commit_receipt_missing",
            )
        if receipt_path.is_symlink() or not receipt_path.is_file():
            raise ValueError("decomposition journal commit receipt is not one private file")
        receipt_bytes = receipt_path.read_bytes()
        if _sha256_bytes(receipt_bytes) != receipt_hash:
            raise ValueError("decomposition journal commit receipt hash mismatch")
        receipt = yaml.safe_load(receipt_bytes)
        if not isinstance(receipt, dict):
            raise ValueError("decomposition journal commit receipt is malformed")
        expected_receipt_schema = (
            _HISTORICAL_COMMIT_SCHEMA
            if manifest_schema == _HISTORICAL_MANIFEST_SCHEMA
            else _PRE_GUARD_COMMIT_SCHEMA
            if manifest_schema == _PRE_GUARD_MANIFEST_SCHEMA
            else _COMMIT_SCHEMA
        )
        if (
            receipt.get("schema") != expected_receipt_schema
            or receipt.get("commit_id") != commit_id
            or receipt.get("state") != "committed"
            or receipt.get("may_authorize") is not False
            or receipt.get("identity") != manifest.get("identity")
            or receipt.get("tasks") != task_receipt_projection
            or (
                not history_only
                and receipt.get("task_identity_guard") != manifest.get("task_identity_guard")
            )
        ):
            raise ValueError("decomposition journal commit receipt contract mismatch")
        return _journal_inspection(
            commit_id,
            manifest,
            state="committed",
            reason_code=(
                f"historical_{history_version}_commit_receipt_valid"
                if history_only
                else "commit_receipt_valid"
            ),
            history_only=history_only,
            task_ids=tuple(task_id_hints),
        )
    except (OSError, TaskStoreError, TypeError, ValueError, yaml.YAMLError) as exc:
        return _journal_inspection(
            commit_id,
            manifest,
            state="invalid",
            reason_code=f"journal_invalid:{exc}",
            history_only=(
                isinstance(manifest, dict)
                and manifest.get("schema")
                in {
                    _HISTORICAL_MANIFEST_SCHEMA,
                    _PRE_GUARD_MANIFEST_SCHEMA,
                }
            ),
        )


def inspect_decomposition_journals(
    task_root: Path = DEFAULT_TASK_ROOT,
) -> tuple[DecompositionJournalInspection, ...]:
    """Enumerate durable journals without consulting mutable request pointers."""

    transaction_root = _task_root_path(task_root, _TRANSACTION_DIR)
    if not transaction_root.exists():
        return ()
    if transaction_root.is_symlink() or not transaction_root.is_dir():
        raise ValueError("decomposition transaction root is not one private directory")
    inspections = []
    for transaction_path in sorted(transaction_root.iterdir()):
        if not re.fullmatch(r"[0-9a-f]{64}", transaction_path.name):
            continue
        inspections.append(_inspect_decomposition_journal(transaction_path, task_root))
    return tuple(inspections)


def _install_no_replace(stage: Path, final: Path, expected_hash: str) -> None:
    stage_parent_fd = open_task_store_directory_fd(stage.parent)
    try:
        stage_descriptor = os.open(
            stage.name,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
            dir_fd=stage_parent_fd,
        )
        try:
            stage_metadata = os.fstat(stage_descriptor)
            content = _read_regular_descriptor(stage_descriptor, label=str(stage))
            if _sha256_bytes(content) != expected_hash:
                raise ValueError("staged decomposition artifact changed before install")
            _assert_path_directory_identity(stage.parent, stage_parent_fd)

            parent_fd = open_task_store_directory_fd(final.parent, create=True)
            try:
                try:
                    existing = _read_named_file(parent_fd, final.name)
                except FileNotFoundError:
                    existing = None
                except (OSError, ValueError) as exc:
                    raise FileExistsError(f"refusing to overwrite existing path {final}") from exc
                if existing is not None:
                    if _sha256_bytes(existing) != expected_hash:
                        raise FileExistsError(f"refusing to overwrite existing path {final}")
                    _assert_path_directory_identity(final.parent, parent_fd)
                    return

                linked = False
                try:
                    os.link(
                        stage.name,
                        final.name,
                        src_dir_fd=stage_parent_fd,
                        dst_dir_fd=parent_fd,
                        follow_symlinks=False,
                    )
                    linked = True
                except FileExistsError:
                    try:
                        raced = _read_named_file(parent_fd, final.name)
                    except (OSError, ValueError) as exc:
                        raise FileExistsError(
                            f"refusing to overwrite raced path {final}"
                        ) from exc
                    if _sha256_bytes(raced) != expected_hash:
                        raise FileExistsError(
                            f"refusing to overwrite raced path {final}"
                        ) from None
                os.fsync(parent_fd)
                _assert_path_directory_identity(final.parent, parent_fd)
                _assert_path_directory_identity(stage.parent, stage_parent_fd)
                installed = _read_named_file(parent_fd, final.name)
                if _sha256_bytes(installed) != expected_hash:
                    raise ValueError("installed decomposition artifact hash mismatch")
                if linked:
                    named_stage = os.stat(
                        stage.name,
                        dir_fd=stage_parent_fd,
                        follow_symlinks=False,
                    )
                    installed_metadata = os.stat(
                        final.name,
                        dir_fd=parent_fd,
                        follow_symlinks=False,
                    )
                    for observed in (named_stage, installed_metadata):
                        if (
                            observed.st_dev != stage_metadata.st_dev
                            or observed.st_ino != stage_metadata.st_ino
                        ):
                            raise FileExistsError(
                                "staged decomposition identity changed during hard-link install"
                            )
            finally:
                os.close(parent_fd)
        finally:
            os.close(stage_descriptor)
    finally:
        os.close(stage_parent_fd)


def _reconcile_prepared_task_identities(prepared: _PreparedWrite):
    guard = prepared.task_identity_guard
    if guard is None:
        raise ValueError("decomposition recovery lacks a task identity guard")
    return reconcile_task_identity_writes(
        guard,
        build_task_identity_index(guard.vault_root),
    )


def _live_projection_paths(task_root: Path, task_ids: tuple[str, ...]) -> list[Path]:
    entries = resolve_task_identity_projection(task_root, task_ids)
    return [entry.path for entry in entries]


def _prepared_live_projection_paths(prepared: _PreparedWrite) -> list[Path]:
    guard = prepared.task_identity_guard
    if guard is None:
        raise ValueError("decomposition live projection requires a task identity guard")
    return _live_projection_paths(
        guard.vault_root,
        tuple(intent.task_id for intent in guard.intents),
    )


def _roll_forward(
    prepared: _PreparedWrite,
    manifest: dict[str, Any],
    *,
    source_check: Callable[[], None],
) -> list[Path]:
    transaction_path = prepared.transaction_path
    if manifest.get("may_authorize") is not False:
        raise ValueError("decomposition transaction cannot authorize")
    _validate_prepared_transaction(prepared)
    task_paths: list[Path] = []
    guard = prepared.task_identity_guard
    if guard is None:
        raise ValueError("decomposition transaction lacks a task identity guard")
    for entry, intent in zip(manifest.get("tasks", []), guard.intents, strict=True):
        source_check()
        before = _reconcile_prepared_task_identities(prepared)
        final = guard.vault_root / intent.relative_path
        if entry != _prepared_task_projection(prepared)[len(task_paths)]:
            raise ValueError("decomposition task projection changed after planning")
        stage = transaction_path / str(entry["stage"])
        if intent.task_id not in before.installed_task_ids:
            _install_no_replace(stage, final, intent.content_sha256)
        after = _reconcile_prepared_task_identities(prepared)
        if intent.task_id not in after.installed_task_ids:
            raise ValueError("decomposition task install lacks an exact identity postcondition")
        task_paths.append(final)
    receipt = manifest["receipt"]
    source_check()
    complete = _reconcile_prepared_task_identities(prepared)
    if not complete.complete:
        raise ValueError("decomposition receipt requires the complete guarded task frontier")
    if (
        _task_root_path(guard.vault_root, _RECEIPT_DIR, prepared.receipt_path.name)
        != prepared.receipt_path
    ):
        raise ValueError("decomposition receipt destination changed after planning")
    _install_no_replace(
        transaction_path / str(receipt["stage"]),
        Path(str(receipt["final"])),
        str(receipt["sha256"]),
    )
    source_check()
    committed = _reconcile_prepared_task_identities(prepared)
    if not committed.complete:
        raise ValueError("decomposition receipt lacks the exact guarded task post-frontier")
    return _prepared_live_projection_paths(prepared)


def _receipt_is_complete(
    prepared: _PreparedWrite,
) -> list[Path] | None:
    receipt_path = prepared.receipt_path
    task_root = receipt_path.parent.parent
    if _task_root_path(task_root, _RECEIPT_DIR, receipt_path.name) != receipt_path:
        raise ValueError("decomposition receipt path escaped task root")
    if not receipt_path.is_file():
        return None
    _validate_exact_file(
        receipt_path,
        prepared.receipt_content,
        label="commit receipt",
    )
    _validate_prepared_transaction(prepared)
    return _prepared_live_projection_paths(prepared)


def _historical_commit_paths(prepared: _PreparedWrite) -> list[Path] | None:
    if not prepared.transaction_path.exists():
        return None
    inspection = _inspect_decomposition_journal(
        prepared.transaction_path,
        prepared.receipt_path.parent.parent,
    )
    if not inspection.history_only:
        return None
    if inspection.state != "committed":
        raise ValueError(inspection.reason_code)
    return _live_projection_paths(
        prepared.receipt_path.parent.parent,
        inspection.task_ids,
    )


def _inspect_or_recover_planned_commit(
    plan: RequestDecompositionPlan,
    task_root: Path,
    *,
    recover: bool,
) -> list[Path] | None:
    prepared = _prepare_planned_write(plan, task_root)
    if not prepared.transaction_path.exists():
        return None
    historical = _historical_commit_paths(prepared)
    if historical is not None:
        return historical
    _bind_persisted_task_identity_guard(prepared)
    complete = _receipt_is_complete(prepared)
    if complete is not None:
        return complete
    manifest = _validate_prepared_transaction(prepared)
    _verify_plan_bindings(plan)
    request_path = Path(plan.request_path).expanduser()
    _verify_plan_request_frontier(
        plan,
        request_path,
        _request_frontmatter(request_path.read_bytes()),
    )
    if not recover:
        _reconcile_prepared_task_identities(prepared)
        return sorted(prepared.task_contents, key=str)
    with _locked_source_guard(prepared) as source_check:
        return _roll_forward(prepared, manifest, source_check=source_check)


def decomposition_commit_state(
    plan: RequestDecompositionPlan,
    task_root: Path = DEFAULT_TASK_ROOT,
) -> Literal["absent", "prepared", "committed"]:
    """Return the exact plan-derived journal state without writes or recovery."""

    prepared = _prepare_planned_write(plan, task_root)
    if not prepared.transaction_path.exists():
        return "absent"
    inspection = _inspect_decomposition_journal(prepared.transaction_path, task_root)
    if inspection.history_only:
        if inspection.state == "invalid":
            raise ValueError(inspection.reason_code)
        return inspection.state
    _bind_persisted_task_identity_guard(prepared)
    if _receipt_is_complete(prepared) is not None:
        return "committed"
    _validate_prepared_transaction(prepared)
    return "prepared"


def _apply_prepared(prepared: _PreparedWrite) -> list[Path]:
    historical = _historical_commit_paths(prepared)
    if historical is not None:
        return historical
    recovering = prepared.transaction_path.exists()
    if recovering:
        _bind_persisted_task_identity_guard(prepared)
    else:
        _bind_new_task_identity_guard(prepared)
    complete = _receipt_is_complete(prepared)
    if complete is not None:
        return complete
    with _locked_source_guard(prepared) as source_check:
        manifest = _stage_transaction(prepared)
        source_check()
        if not recovering:
            staged = _reconcile_prepared_task_identities(prepared)
            if staged.installed_task_ids:
                raise ValueError(
                    "decomposition task identity appeared between guard and journal staging"
                )
        return _roll_forward(prepared, manifest, source_check=source_check)


def write_decomposition(
    decomposition: RequestDecomposition | RequestDecompositionPlan,
    task_root: Path = DEFAULT_TASK_ROOT,
    *,
    dry_run: bool = False,
) -> list[Path]:
    """Durably stage and recover a blocked, non-authorizing task graph.

    The receipt is a module-local recoverable last marker. System-wide atomic
    publication remains held for the single-committer generation fence.
    """
    if isinstance(decomposition, RequestDecompositionPlan):
        if dry_run:
            existing = _inspect_or_recover_planned_commit(
                decomposition,
                task_root,
                recover=False,
            )
            if existing is not None:
                return existing
            prepared = _prepare_planned_write(decomposition, task_root)
            _verify_plan_bindings(decomposition)
            request_path = Path(decomposition.request_path).expanduser()
            _verify_plan_request_frontier(
                decomposition,
                request_path,
                _request_frontmatter(request_path.read_bytes()),
            )
            _bind_new_task_identity_guard(prepared)
            return sorted(prepared.task_contents, key=str)

        with _locked_task_root(task_root):
            existing = _inspect_or_recover_planned_commit(
                decomposition,
                task_root,
                recover=True,
            )
            if existing is not None:
                return existing
            prepared = _prepare_planned_write(decomposition, task_root)
            _verify_plan_bindings(decomposition)
            request_path = Path(decomposition.request_path).expanduser()
            _verify_plan_request_frontier(
                decomposition,
                request_path,
                _request_frontmatter(request_path.read_bytes()),
            )
            return _apply_prepared(prepared)

    prepared = _prepare_write(decomposition, task_root)
    paths = list(prepared.task_contents)
    if dry_run:
        historical = _historical_commit_paths(prepared)
        if historical is not None:
            return historical
        if prepared.transaction_path.exists():
            _bind_persisted_task_identity_guard(prepared)
            complete = _receipt_is_complete(prepared)
            if complete is not None:
                return complete
            _validate_prepared_transaction(prepared)
            _reconcile_prepared_task_identities(prepared)
        else:
            _bind_new_task_identity_guard(prepared)
        return paths

    with _locked_task_root(task_root):
        prepared = _prepare_write(decomposition, task_root)
        return _apply_prepared(prepared)
