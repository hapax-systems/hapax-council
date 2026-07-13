"""Pure Gate-0 coordination binding over composition-owned invocation carriers.

This module contains no actuator. MQ state, terminal mirrors, lane changes, and
process launch are operational projections that must traverse an activated
universal executor after Gate-0B.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from shared.execution_admission import (
    ContentAddress,
    ExecutionAdmissionError,
    ExecutionCompositionPorts,
    ExecutionCompositionRoot,
    ExecutionInvocationBundle,
    ExecutionInvocationBundlePointer,
    ExecutionInvocationContext,
    ExecutionLease,
    OutcomeProjectionSnapshot,
    OutcomeReplayResult,
    content_address,
    require_admitted_execution_lease,
)


class CoordDispatchError(RuntimeError):
    """Typed refusal at the coordination-to-composition boundary."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class DispatchLaunchRequest:
    """Path-free values binding one dispatch intent to one invocation bundle."""

    task_id: str
    lane: str
    platform: str
    mode: str
    profile: str
    authority_case: str
    parent_spec: str | None
    message_id: str
    idempotency_key: str | None = None
    authority_item: str | None = None
    reactivate_retired: bool = False

    def __post_init__(self) -> None:
        for name in (
            "task_id",
            "lane",
            "platform",
            "mode",
            "profile",
            "authority_case",
            "message_id",
        ):
            value = getattr(self, name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"{name} is required")
        for name in ("parent_spec", "idempotency_key", "authority_item"):
            value = getattr(self, name)
            if value is not None and (type(value) is not str or not value.strip()):
                raise ValueError(f"{name} must be null or nonblank")
        if type(self.reactivate_retired) is not bool:
            raise ValueError("reactivate_retired must be boolean")

    @property
    def normalized_lane(self) -> str:
        return self.lane.strip().lower().replace("_", "-")

    @property
    def effective_idempotency_key(self) -> str:
        if self.idempotency_key is not None:
            return self.idempotency_key.strip()
        return default_idempotency_key(
            task_id=self.task_id,
            lane=self.normalized_lane,
            platform=self.platform,
            mode=self.mode,
            profile=self.profile,
            message_id=self.message_id,
        )


@dataclass(frozen=True)
class DispatchLaunchResult:
    """Canonical outcome inspection result; never an MQ or mirror receipt."""

    launched: bool
    launch_returncode: int | None
    replayed: bool
    reason: str
    message_id: str
    idempotency_key: str
    event_id: str | None = None
    cleanup_state: Literal["accepted", "processed", "deferred"] | None = None
    outcome_projection_ref: str | None = None
    outcome_projection_hash: str | None = None
    outcome_receipt_ref: str | None = None
    outcome_receipt_hash: str | None = None
    outcome: Literal["succeeded", "failed", "indeterminate"] | None = None
    closure_state: Literal["closed", "open"] | None = None
    outcome_validity_ref: str | None = None
    outcome_validity_hash: str | None = None
    outcome_replay_ref: str | None = None
    outcome_replay_hash: str | None = None
    outcome_catalog_snapshot_ref: str | None = None
    outcome_catalog_snapshot_hash: str | None = None
    checked_frontier_ref: str | None = None
    checked_frontier_hash: str | None = None


def default_idempotency_key(
    *,
    task_id: str,
    lane: str,
    platform: str,
    mode: str,
    profile: str,
    message_id: str,
) -> str:
    """Return the stable dispatch identity; it is not an attempt lock."""

    return ":".join(
        [
            "coord-dispatch-v1",
            message_id,
            lane,
            task_id,
            platform,
            mode,
            profile,
        ]
    )


def _require_exact(value: object, expected: type[object], reason: str) -> None:
    if type(value) is not expected:
        raise CoordDispatchError(reason)


def _require_composition_ports(
    composition: ExecutionCompositionRoot,
) -> ExecutionCompositionPorts:
    try:
        ports = composition.require_composition_ports()
    except ExecutionAdmissionError as exc:
        raise CoordDispatchError(f"{exc.reason_code}:{exc.detail}") from exc
    _require_exact(ports, ExecutionCompositionPorts, "execution_composition_ports_invalid")
    return ports


def _require_dispatch_bundle_binding(
    request: DispatchLaunchRequest,
    bundle: ExecutionInvocationBundle,
    lease: ExecutionLease,
) -> None:
    admission = bundle.execution_admission
    intent = bundle.action_intent
    decision = bundle.route_decision
    call = lease.bound_call
    normalized_lease_lane = lease.lane.strip().lower().replace("_", "-")
    mismatches: list[str] = []
    if (
        request.task_id != lease.task_ref
        or request.task_id != admission.task_ref
        or request.task_id != intent.task_ref
    ):
        mismatches.append("task")
    if request.normalized_lane != normalized_lease_lane or request.normalized_lane != (
        admission.lane.strip().lower().replace("_", "-")
    ):
        mismatches.append("lane")
    if request.authority_case != admission.authority_case:
        mismatches.append("authority_case")
    if (
        request.parent_spec != intent.parent_spec.ref
        or request.parent_spec != admission.parent_spec.ref
    ):
        mismatches.append("parent_spec")
    if request.authority_item is not None and request.authority_item != request.task_id:
        mismatches.append("authority_item")
    if (
        decision.task_id != request.task_id
        or decision.lane.strip().lower().replace("_", "-") != request.normalized_lane
    ):
        mismatches.append("route_identity")
    if (
        decision.platform != request.platform
        or decision.mode != request.mode
        or decision.profile != request.profile
    ):
        mismatches.append("route_shape")
    if admission.route_decision != content_address(decision.decision_id, decision):
        mismatches.append("route_decision")
    selected_leaf = decision.selected_descriptor_leaf or f"{decision.route_id}#base"
    if selected_leaf != lease.selected_descriptor_leaf:
        mismatches.append("descriptor_leaf")
    if (
        call.task_ref != request.task_id
        or call.lane.strip().lower().replace("_", "-") != request.normalized_lane
        or call.dispatch_message_id != request.message_id
        or call.idempotency_key != request.effective_idempotency_key
    ):
        mismatches.append("bound_call_dispatch")
    if (
        call.platform != request.platform
        or call.mode != request.mode
        or call.profile != request.profile
        or call.route_id != decision.route_id
        or call.selected_descriptor_leaf != selected_leaf
    ):
        mismatches.append("bound_call_route")
    if request.message_id != admission.dispatch_message_id:
        mismatches.append("dispatch_message")
    if (
        request.effective_idempotency_key != lease.idempotency_key
        or request.effective_idempotency_key != admission.idempotency_key
    ):
        mismatches.append("idempotency")
    if lease.admission != ContentAddress(
        ref=admission.admission_ref,
        sha256=admission.admission_hash,
    ):
        mismatches.append("admission")
    call_reactivates = "lane.lifecycle.reactivate" in call.control_operations
    if request.reactivate_retired != call_reactivates:
        mismatches.append("lane_reactivation_operation")
    if call_reactivates and (
        "lane_reactivation_authorized" not in admission.authorized_flags
        or f"lane:{request.normalized_lane}" not in admission.immutable_scope_refs
    ):
        mismatches.append("lane_reactivation_authority")
    if mismatches:
        raise CoordDispatchError(
            "execution_invocation_binding_mismatch:" + ",".join(sorted(set(mismatches)))
        )


def _inspect_dispatch_bundle(
    request: DispatchLaunchRequest,
    *,
    composition: ExecutionCompositionRoot,
    invocation_pointer: ExecutionInvocationBundlePointer,
) -> tuple[ExecutionInvocationBundle, ExecutionLease, ExecutionCompositionPorts]:
    _require_exact(request, DispatchLaunchRequest, "dispatch_launch_request_invalid")
    _require_exact(
        composition,
        ExecutionCompositionRoot,
        "execution_composition_root_required",
    )
    _require_exact(
        invocation_pointer,
        ExecutionInvocationBundlePointer,
        "execution_invocation_bundle_pointer_required",
    )
    try:
        store = composition.require_bundle_resolution()
        bundle = store.inspect(invocation_pointer)
    except ExecutionAdmissionError as exc:
        raise CoordDispatchError(f"{exc.reason_code}:{exc.detail}") from exc
    except ValueError as exc:
        raise CoordDispatchError(f"execution_invocation_pointer_invalid:{exc}") from exc
    if type(bundle) is not ExecutionInvocationBundle:
        raise CoordDispatchError("active_execution_invocation_bundle_required")
    lease = require_admitted_execution_lease(bundle.execution_lease)
    _require_dispatch_bundle_binding(request, bundle, lease)
    return bundle, lease, _require_composition_ports(composition)


def _resolve_dispatch_invocation(
    request: DispatchLaunchRequest,
    *,
    composition: ExecutionCompositionRoot,
    invocation_pointer: ExecutionInvocationBundlePointer,
    queried_at: str | datetime,
) -> tuple[ExecutionInvocationContext, ExecutionLease, ExecutionCompositionPorts]:
    _, inspected_lease, ports = _inspect_dispatch_bundle(
        request,
        composition=composition,
        invocation_pointer=invocation_pointer,
    )
    try:
        invocation = composition.resolve_structural_invocation(
            invocation_pointer,
            queried_at=queried_at,
        )
        lease = invocation.require_admitted(queried_at=queried_at)
        invocation_ports = invocation.require_composition_ports()
    except ExecutionAdmissionError as exc:
        raise CoordDispatchError(f"{exc.reason_code}:{exc.detail}") from exc
    _require_exact(
        invocation,
        ExecutionInvocationContext,
        "execution_invocation_context_invalid",
    )
    if lease != inspected_lease or invocation_ports.descriptors != ports.descriptors:
        raise CoordDispatchError("execution_composition_invocation_mismatch")
    return invocation, lease, ports


def inspect_terminal_result(
    request: DispatchLaunchRequest,
    *,
    composition: ExecutionCompositionRoot,
    invocation_pointer: ExecutionInvocationBundlePointer,
    queried_at: str | datetime,
    idempotency_key: str | None = None,
) -> DispatchLaunchResult | None:
    """Inspect canonical outcome truth without projecting any operational state."""

    _, lease, ports = _inspect_dispatch_bundle(
        request,
        composition=composition,
        invocation_pointer=invocation_pointer,
    )
    try:
        replay = ports.outcomes.replay(lease, queried_at=queried_at)
    except ExecutionAdmissionError as exc:
        raise CoordDispatchError(f"{exc.reason_code}:{exc.detail}") from exc
    if replay is None:
        return None
    _require_exact(replay, OutcomeReplayResult, "canonical_outcome_replay_invalid")
    projection = replay.projection
    _require_exact(
        projection,
        OutcomeProjectionSnapshot,
        "canonical_outcome_projection_invalid",
    )
    checked_projection = OutcomeProjectionSnapshot.model_validate(
        projection.model_dump(mode="json", by_alias=True)
    )
    receipt = checked_projection.outcome_receipt
    key = idempotency_key or request.effective_idempotency_key
    if key != lease.idempotency_key or key != receipt.idempotency_key:
        raise CoordDispatchError("canonical_outcome_idempotency_mismatch")
    returncode = checked_projection.effect_observation.returncode
    if receipt.outcome == "succeeded" and receipt.effect_disposition == "applied":
        terminal_returncode = 0
    elif receipt.outcome == "failed":
        terminal_returncode = returncode if isinstance(returncode, int) and returncode != 0 else 1
    else:
        terminal_returncode = 10
    return DispatchLaunchResult(
        launched=True,
        launch_returncode=terminal_returncode,
        replayed=True,
        reason=f"replayed_canonical_{receipt.outcome}",
        message_id=request.message_id,
        idempotency_key=key,
        outcome_projection_ref=checked_projection.snapshot_ref,
        outcome_projection_hash=checked_projection.snapshot_hash,
        outcome_receipt_ref=receipt.receipt_ref,
        outcome_receipt_hash=receipt.receipt_hash,
        outcome=receipt.outcome,
        closure_state=receipt.closure_state,
        outcome_validity_ref=replay.validity.envelope_ref,
        outcome_validity_hash=replay.validity.envelope_hash,
        outcome_replay_ref=replay.result_ref,
        outcome_replay_hash=replay.result_hash,
        outcome_catalog_snapshot_ref=replay.catalog_snapshot.ref,
        outcome_catalog_snapshot_hash=replay.catalog_snapshot.sha256,
        checked_frontier_ref=replay.validity.checked_frontier.ref,
        checked_frontier_hash=replay.validity.checked_frontier.sha256,
    )


def replay_terminal_result(
    request: DispatchLaunchRequest,
    *,
    composition: ExecutionCompositionRoot,
    invocation_pointer: ExecutionInvocationBundlePointer,
    queried_at: str | datetime,
    idempotency_key: str | None = None,
) -> DispatchLaunchResult | None:
    """Compatibility spelling for pure canonical outcome inspection."""

    return inspect_terminal_result(
        request,
        composition=composition,
        invocation_pointer=invocation_pointer,
        queried_at=queried_at,
        idempotency_key=idempotency_key,
    )


def run_atomic_dispatch_launch(
    request: DispatchLaunchRequest,
    *,
    composition: ExecutionCompositionRoot,
    invocation_pointer: ExecutionInvocationBundlePointer,
    queried_at: str | datetime,
) -> DispatchLaunchResult:
    """Replay canonical truth, then HOLD before every Gate-0A effect."""

    replayed = inspect_terminal_result(
        request,
        composition=composition,
        invocation_pointer=invocation_pointer,
        queried_at=queried_at,
    )
    if replayed is not None:
        return replayed
    _resolve_dispatch_invocation(
        request,
        composition=composition,
        invocation_pointer=invocation_pointer,
        queried_at=queried_at,
    )
    try:
        composition.require_effect_activation()
    except ExecutionAdmissionError as exc:
        raise CoordDispatchError(f"{exc.reason_code}:{exc.detail}") from exc
    raise AssertionError("Gate-0A effect activation unexpectedly returned")  # pragma: no cover


__all__ = [
    "CoordDispatchError",
    "DispatchLaunchRequest",
    "DispatchLaunchResult",
    "default_idempotency_key",
    "inspect_terminal_result",
    "replay_terminal_result",
    "run_atomic_dispatch_launch",
]
