"""Route/resource receipt envelopes for subagent and orchestrator fanout.

The envelope is evidence plumbing. It carries the parent dispatch route,
authority, resource/quota receipts, and stop conditions into child worker
spawns without granting any new authority.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from shared.dispatcher_policy import DispatchRequest, RouteDecision
from shared.platform_capability_receipts import parse_duration_spec

PARENT_ROUTE_RESOURCE_ENVELOPE_SCHEMA = 1
CHILD_SPAWN_ENVELOPE_SCHEMA = 1
DEFAULT_PARENT_ENVELOPE_STALE_AFTER = "6h"
PARENT_ROUTE_ENVELOPE_ENV = "HAPAX_PARENT_ROUTE_ENVELOPE"


class SubagentRouteReceiptError(ValueError):
    """Raised when child fanout lacks a valid parent route/resource receipt."""


class _EnvelopeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SpawnCapabilityShape(StrEnum):
    SUBAGENT = "subagent"
    ORCHESTRATOR = "orchestrator"
    CAPABILITY_AGGREGATOR = "capability_aggregator"
    EXISTING_AGENT_HARNESS = "existing_agent_harness"
    LOCAL_TOOL = "local_tool"
    MCP_CONNECTOR = "mcp_connector"
    REVIEW_SEAT = "review_seat"


class SpawnSurfaceDescriptor(_EnvelopeModel):
    surface_id: str
    shape: SpawnCapabilityShape
    path_globs: tuple[str, ...] = Field(min_length=1)
    receipt_requirement: str


KNOWN_SPAWN_SURFACES: tuple[SpawnSurfaceDescriptor, ...] = (
    SpawnSurfaceDescriptor(
        surface_id="claude_code_probabilistic_subagents",
        shape=SpawnCapabilityShape.SUBAGENT,
        path_globs=("tooling/claude-agents/*.md", "~/.claude/agents/*.md"),
        receipt_requirement="auto-fire subagents must inherit HAPAX_PARENT_ROUTE_ENVELOPE",
    ),
    SpawnSurfaceDescriptor(
        surface_id="governed_worker_lane_dispatch",
        shape=SpawnCapabilityShape.EXISTING_AGENT_HARNESS,
        path_globs=(
            "scripts/hapax-methodology-dispatch",
            "scripts/hapax-codex",
            "scripts/hapax-claude",
            "scripts/hapax-claude-headless",
        ),
        receipt_requirement="launched lanes receive a parent route/resource envelope path",
    ),
    SpawnSurfaceDescriptor(
        surface_id="fugu_style_orchestration",
        shape=SpawnCapabilityShape.ORCHESTRATOR,
        path_globs=("agents/**/orchestrator*.py", "shared/**/*orchestrator*.py"),
        receipt_requirement="orchestrator children must be admitted as child capabilities",
    ),
)


class ResourceBudgetReceipt(_EnvelopeModel):
    quota_state: str = "unknown"
    context_budget_tokens: int | None = Field(default=None, ge=0)
    estimated_context_tokens: int | None = Field(default=None, ge=0)
    quota_receipt_refs: tuple[str, ...] = Field(default=())
    resource_receipt_refs: tuple[str, ...] = Field(min_length=1)
    quota_freshness_green: bool = False
    resource_freshness_green: bool = False
    stale_after: str = DEFAULT_PARENT_ENVELOPE_STALE_AFTER

    @model_validator(mode="after")
    def _duration_is_valid(self) -> Self:
        parse_duration_spec(self.stale_after)
        return self


class ChildCapabilityRequest(_EnvelopeModel):
    child_id: str
    task_id: str
    authority_case: str
    shape: SpawnCapabilityShape
    route_id: str | None = None
    capability_id: str | None = None
    lane: str | None = None
    capability_role: str = "worker"
    requested_receipt_classes: tuple[str, ...] = Field(default=("route", "resource", "outcome"))
    proposed_child_capabilities: tuple[str, ...] = Field(default=())

    @model_validator(mode="after")
    def _shape_has_identity(self) -> Self:
        if not (self.route_id or self.capability_id):
            raise ValueError("child capability requires route_id or capability_id")
        if self.shape is SpawnCapabilityShape.ORCHESTRATOR and not self.proposed_child_capabilities:
            raise ValueError(
                "orchestrator child requires proposed_child_capabilities so nested fanout "
                "is represented as a capability aggregator"
            )
        return self


class ChildCapabilityReceipt(_EnvelopeModel):
    receipt_id: str
    parent_envelope_id: str
    child_envelope_id: str
    child_id: str
    task_id: str
    authority_case: str
    shape: SpawnCapabilityShape
    capability_role: str
    route_id: str | None = None
    capability_id: str | None = None
    emitted_at: datetime
    receipt_refs: tuple[str, ...] = Field(min_length=1)
    receipt_chain: tuple[str, ...] = Field(min_length=1)


class ParentRouteResourceEnvelope(_EnvelopeModel):
    parent_route_resource_envelope_schema: Literal[1] = PARENT_ROUTE_RESOURCE_ENVELOPE_SCHEMA
    envelope_id: str
    issued_at: datetime
    stale_after: str = DEFAULT_PARENT_ENVELOPE_STALE_AFTER
    task_id: str
    lane: str
    platform: str
    mode: str
    profile: str
    route_id: str
    authority_case: str
    parent_spec: str | None = None
    route_decision_id: str
    route_decision_receipt_ref: str
    capability_profile: str
    resource_budget: ResourceBudgetReceipt
    stop_conditions: tuple[str, ...] = Field(min_length=1)
    receipt_chain: tuple[str, ...] = Field(min_length=1)
    child_receipts: tuple[ChildCapabilityReceipt, ...] = Field(default=())

    @field_validator("receipt_chain", mode="before")
    @classmethod
    def _receipt_chain_is_tuple(cls, value: object) -> tuple[str, ...]:
        return _coerce_string_tuple(value)

    @model_validator(mode="after")
    def _has_route_and_resource_receipts(self) -> Self:
        parse_duration_spec(self.stale_after)
        if not self.route_decision_receipt_ref.strip():
            raise ValueError("parent envelope requires route_decision_receipt_ref")
        if self.route_decision_receipt_ref not in self.receipt_chain:
            raise ValueError("receipt_chain must include route_decision_receipt_ref")
        resource_refs = set(self.resource_budget.resource_receipt_refs)
        if not resource_refs.intersection(self.receipt_chain):
            raise ValueError("receipt_chain must include at least one resource receipt ref")
        for receipt in self.child_receipts:
            if receipt.parent_envelope_id != self.envelope_id:
                raise ValueError("child receipt parent_envelope_id mismatch")
        return self

    def is_fresh(self, *, now: datetime | None = None) -> bool:
        checked_at = _ensure_utc(now or datetime.now(UTC))
        return checked_at - _ensure_utc(self.issued_at) <= parse_duration_spec(self.stale_after)

    def require_fresh(self, *, now: datetime | None = None) -> None:
        if not self.is_fresh(now=now):
            raise SubagentRouteReceiptError(
                f"stale_parent_budget:{self.envelope_id}:stale_after={self.stale_after}"
            )

    def with_child_receipt(self, receipt: ChildCapabilityReceipt) -> ParentRouteResourceEnvelope:
        if receipt.parent_envelope_id != self.envelope_id:
            raise SubagentRouteReceiptError("child_receipt_parent_mismatch")
        return self.model_copy(update={"child_receipts": (*self.child_receipts, receipt)})


class ChildCapabilitySpawnEnvelope(_EnvelopeModel):
    child_spawn_envelope_schema: Literal[1] = CHILD_SPAWN_ENVELOPE_SCHEMA
    envelope_id: str
    parent_envelope_id: str
    issued_at: datetime
    task_id: str
    authority_case: str
    child: ChildCapabilityRequest
    capability_role: str
    receipt_chain: tuple[str, ...] = Field(min_length=1)
    stop_conditions: tuple[str, ...] = Field(min_length=1)
    child_receipt_required: Literal[True] = True


def spawn_surface_inventory() -> tuple[SpawnSurfaceDescriptor, ...]:
    return KNOWN_SPAWN_SURFACES


def build_parent_route_resource_envelope(
    *,
    request: DispatchRequest,
    decision: RouteDecision,
    route_decision_receipt_path: Path,
    parent_spec: str | None = None,
    issued_at: datetime | None = None,
    stale_after: str = DEFAULT_PARENT_ENVELOPE_STALE_AFTER,
) -> ParentRouteResourceEnvelope:
    """Project a launch-admitted dispatch decision into a child-spawn parent envelope."""

    issued = _ensure_utc(issued_at or decision.created_at)
    route_receipt_ref = f"route-decision-receipt:{route_decision_receipt_path}"
    quota_refs = tuple(decision.quota_evidence_refs)
    resource_refs = tuple(_dedupe((*decision.resource_state_refs, *quota_refs)))
    if not resource_refs:
        raise SubagentRouteReceiptError("missing_parent_resource_receipt_refs")
    receipt_chain = tuple(
        _dedupe(
            (
                route_receipt_ref,
                f"route-decision:{decision.decision_id}",
                *resource_refs,
            )
        )
    )
    budget = ResourceBudgetReceipt(
        quota_state=request.quota.route_subscription_quota_state
        or request.quota.subscription_quota_state
        if request.quota is not None
        else "unknown",
        context_budget_tokens=_context_budget_tokens(request),
        estimated_context_tokens=_estimated_context_tokens(request),
        quota_receipt_refs=quota_refs,
        resource_receipt_refs=resource_refs,
        quota_freshness_green=decision.quota_freshness_green,
        resource_freshness_green=decision.resource_freshness_green,
        stale_after=stale_after,
    )
    payload = {
        "task_id": request.task_id,
        "lane": request.lane,
        "route_id": decision.route_id,
        "decision_id": decision.decision_id,
        "route_receipt_ref": route_receipt_ref,
    }
    return ParentRouteResourceEnvelope(
        envelope_id=f"parent-route-{_stable_hash(payload)[:24]}",
        issued_at=issued,
        stale_after=stale_after,
        task_id=request.task_id,
        lane=request.lane,
        platform=request.platform,
        mode=request.mode,
        profile=request.profile,
        route_id=decision.route_id,
        authority_case=request.authority_case or "unknown",
        parent_spec=parent_spec,
        route_decision_id=decision.decision_id,
        route_decision_receipt_ref=route_receipt_ref,
        capability_profile=decision.selected_descriptor_leaf or decision.route_id,
        resource_budget=budget,
        stop_conditions=(
            "parent_task_closed",
            "authority_case_changes",
            "budget_or_resource_receipt_stale",
            "child_receipt_missing",
        ),
        receipt_chain=receipt_chain,
    )


def write_parent_route_resource_envelope(
    envelope: ParentRouteResourceEnvelope,
    *,
    ledger_dir: Path,
) -> Path:
    target_dir = ledger_dir / "parent-route-envelopes"
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{envelope.envelope_id}.json"
    path.write_text(json.dumps(envelope.model_dump(mode="json"), sort_keys=True) + "\n")
    return path


def load_parent_route_resource_envelope(path: Path) -> ParentRouteResourceEnvelope:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return ParentRouteResourceEnvelope.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise SubagentRouteReceiptError(f"invalid parent route envelope at {path}: {exc}") from exc


def admit_child_spawn(
    parent: ParentRouteResourceEnvelope | None,
    child: ChildCapabilityRequest,
    *,
    now: datetime | None = None,
) -> ChildCapabilitySpawnEnvelope:
    if parent is None:
        raise SubagentRouteReceiptError("missing_parent_route_resource_receipt")
    parent.require_fresh(now=now)
    if child.task_id != parent.task_id:
        raise SubagentRouteReceiptError("child_task_must_match_parent_task")
    if child.authority_case != parent.authority_case:
        raise SubagentRouteReceiptError("child_authority_case_must_match_parent")
    capability_role = child.capability_role
    if child.shape is SpawnCapabilityShape.ORCHESTRATOR:
        capability_role = "capability_aggregator"
    payload = {
        "parent_envelope_id": parent.envelope_id,
        "child_id": child.child_id,
        "shape": child.shape.value,
        "capability_role": capability_role,
    }
    return ChildCapabilitySpawnEnvelope(
        envelope_id=f"child-spawn-{_stable_hash(payload)[:24]}",
        parent_envelope_id=parent.envelope_id,
        issued_at=_ensure_utc(now or datetime.now(UTC)),
        task_id=parent.task_id,
        authority_case=parent.authority_case,
        child=child,
        capability_role=capability_role,
        receipt_chain=(
            *parent.receipt_chain,
            f"parent-route-envelope:{parent.envelope_id}",
        ),
        stop_conditions=parent.stop_conditions,
    )


def record_child_receipt(
    parent: ParentRouteResourceEnvelope,
    child_envelope: ChildCapabilitySpawnEnvelope,
    *,
    receipt_refs: Iterable[str],
    emitted_at: datetime | None = None,
) -> ParentRouteResourceEnvelope:
    refs = tuple(_dedupe(receipt_refs))
    if not refs:
        raise SubagentRouteReceiptError("child_receipt_refs_required")
    if child_envelope.parent_envelope_id != parent.envelope_id:
        raise SubagentRouteReceiptError("child_envelope_parent_mismatch")
    child = child_envelope.child
    payload = {
        "parent": parent.envelope_id,
        "child": child_envelope.envelope_id,
        "refs": refs,
    }
    receipt = ChildCapabilityReceipt(
        receipt_id=f"child-receipt-{_stable_hash(payload)[:24]}",
        parent_envelope_id=parent.envelope_id,
        child_envelope_id=child_envelope.envelope_id,
        child_id=child.child_id,
        task_id=parent.task_id,
        authority_case=parent.authority_case,
        shape=child.shape,
        capability_role=child_envelope.capability_role,
        route_id=child.route_id,
        capability_id=child.capability_id,
        emitted_at=_ensure_utc(emitted_at or datetime.now(UTC)),
        receipt_refs=refs,
        receipt_chain=(*child_envelope.receipt_chain, *refs),
    )
    return parent.with_child_receipt(receipt)


def _context_budget_tokens(request: DispatchRequest) -> int | None:
    demand = request.demand_vector
    if demand is not None:
        return demand.route_envelope.admission.context_budget_tokens
    value = request.context_shape.get("context_budget_tokens")
    return value if isinstance(value, int) else None


def _estimated_context_tokens(request: DispatchRequest) -> int | None:
    demand = request.demand_vector
    if demand is not None:
        return demand.task_demand.estimated_context_tokens
    value = request.context_shape.get("estimated_context_tokens")
    return value if isinstance(value, int) else None


def _coerce_string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Iterable):
        return tuple(str(item) for item in value)
    return (str(value),)


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values if str(value).strip()))


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _stable_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


_PYDANTIC_DYNAMIC_ENTRYPOINTS = (
    ResourceBudgetReceipt._duration_is_valid,
    ChildCapabilityRequest._shape_has_identity,
    ParentRouteResourceEnvelope._receipt_chain_is_tuple,
    ParentRouteResourceEnvelope._has_route_and_resource_receipts,
)


__all__ = [
    "CHILD_SPAWN_ENVELOPE_SCHEMA",
    "DEFAULT_PARENT_ENVELOPE_STALE_AFTER",
    "KNOWN_SPAWN_SURFACES",
    "PARENT_ROUTE_ENVELOPE_ENV",
    "PARENT_ROUTE_RESOURCE_ENVELOPE_SCHEMA",
    "ChildCapabilityRequest",
    "ChildCapabilityReceipt",
    "ChildCapabilitySpawnEnvelope",
    "ParentRouteResourceEnvelope",
    "ResourceBudgetReceipt",
    "SpawnCapabilityShape",
    "SpawnSurfaceDescriptor",
    "SubagentRouteReceiptError",
    "admit_child_spawn",
    "build_parent_route_resource_envelope",
    "load_parent_route_resource_envelope",
    "record_child_receipt",
    "spawn_surface_inventory",
    "write_parent_route_resource_envelope",
]
