"""Capability-surface delta contracts.

This module is inert by design. It does not probe providers, launch routes, or
write intake files. It defines the typed evidence rows that an SDLC-owned
detector can emit when observed capability supply differs from registered
descriptors, or when a determination has gone stale.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

REPO_ROOT = Path(__file__).resolve().parents[1]
CAPABILITY_SURFACE_DELTA_FIXTURES = REPO_ROOT / "config" / "capability-surface-delta-fixtures.json"
CAPABILITY_SURFACE_DELTA_SCHEMA_REF = "schemas/capability-surface-delta.schema.json"
DEFAULT_CAPABILITY_SURFACE_DELTA_TASK_ROOT = (
    Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
)
DEFAULT_PARENT_REQUEST = "REQ-20260629-purview-intake-consolidation"
DEFAULT_PARENT_SPEC = str(
    Path.home()
    / "Documents"
    / "Personal"
    / "30-areas"
    / "hapax"
    / "capability-demand-shape-routing-research-2026-06-30.md"
)
DEFAULT_AUTHORITY_CASE = "CASE-CAPACITY-ROUTING-001"
DEFAULT_DISCOVERY_TASK = (
    "cc-task-capability-freshness-remediation-and-discovery-automation-20260630"
)


class CapabilitySurfaceDeltaError(ValueError):
    """Raised when capability-surface delta fixtures fail closed."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SurfaceKind(StrEnum):
    MODEL_ROUTE = "model_route"
    LOCAL_TOOL = "local_tool"
    MCP_TOOL = "mcp_tool"
    ORCHESTRATOR = "orchestrator"
    REVIEW_SEAT = "review_seat"
    CCTV = "cctv"
    PUBLICATION_BUS = "publication_bus"
    MONEY_RAIL = "money_rail"
    REINS_PROJECTION = "reins_projection"


class AuthorityCeiling(StrEnum):
    AUTHORITATIVE = "authoritative"
    FRONTIER_REVIEW_REQUIRED = "frontier_review_required"
    READ_ONLY = "read_only"
    SUPPORT_ONLY = "support_only"
    UNKNOWN = "unknown"


class FreshnessState(StrEnum):
    FRESH = "fresh"
    AGING = "aging"
    STALE = "stale"
    ABSENT = "absent"
    DARK = "dark"
    HELD = "held"
    DELTA_PENDING = "delta_pending"
    UNKNOWN = "unknown"


class DeltaKind(StrEnum):
    NEW_CAPABILITY = "new_capability"
    DESCRIPTOR_CHANGED = "descriptor_changed"
    AUTHORITY_CHANGED = "authority_changed"
    RESOURCE_POOL_CHANGED = "resource_pool_changed"
    PUBLIC_EGRESS_CHANGED = "public_egress_changed"
    MONEY_RAIL_CHANGED = "money_rail_changed"
    HARNESS_BOUNDARY_CHANGED = "harness_boundary_changed"
    ORCHESTRATION_CHILD_CHANGED = "orchestration_child_changed"
    STALE_DETERMINATION = "stale_determination"
    ABSENT_DETERMINATION = "absent_determination"


class RequiredIntakeAction(StrEnum):
    NONE = "none"
    UPDATE_DESCRIPTOR = "update_descriptor"
    MINT_INTAKE_ITEM = "mint_intake_item"
    REFRESH_RECEIPT = "refresh_receipt"
    QUARANTINE_SURFACE = "quarantine_surface"
    DEPRECATE_SURFACE = "deprecate_surface"


class CapabilitySurfaceDescriptor(StrictModel):
    descriptor_schema: Literal[1] = 1
    surface_id: str = Field(min_length=1)
    descriptor_ref: str = Field(min_length=1)
    surface_kind: SurfaceKind
    authority_ceiling: AuthorityCeiling
    observed_at: datetime
    stale_after: str
    evidence_refs: list[str] = Field(min_length=1)
    route_id: str | None = None
    supply_leaf_id: str | None = None
    carrier_platform: str | None = None
    model_id: str | None = None
    provider_id: str | None = None
    effort: str | None = None
    context_window: str | None = None
    resource_pools: list[str] = Field(default_factory=list)
    tool_refs: list[str] = Field(default_factory=list)
    harness_refs: list[str] = Field(default_factory=list)
    orchestration_child_refs: list[str] = Field(default_factory=list)
    privacy_sensitive: bool = False
    public_egress: bool = False
    money_rail: bool = False

    @model_validator(mode="after")
    def _duration_is_valid(self) -> Self:
        parse_duration_spec(self.stale_after)
        return self

    def freshness_state(self, *, now: datetime | None = None) -> FreshnessState:
        checked_now = ensure_utc(now or datetime.now(UTC))
        observed = ensure_utc(self.observed_at)
        if checked_now - observed > parse_duration_spec(self.stale_after):
            return FreshnessState.STALE
        return FreshnessState.FRESH

    def significant_signature(self) -> str:
        payload = {
            "surface_kind": self.surface_kind.value,
            "authority_ceiling": self.authority_ceiling.value,
            "route_id": self.route_id,
            "supply_leaf_id": self.supply_leaf_id,
            "carrier_platform": self.carrier_platform,
            "model_id": self.model_id,
            "provider_id": self.provider_id,
            "effort": self.effort,
            "context_window": self.context_window,
            "resource_pools": sorted(self.resource_pools),
            "tool_refs": sorted(self.tool_refs),
            "harness_refs": sorted(self.harness_refs),
            "orchestration_child_refs": sorted(self.orchestration_child_refs),
            "privacy_sensitive": self.privacy_sensitive,
            "public_egress": self.public_egress,
            "money_rail": self.money_rail,
        }
        return stable_hash(payload)


class CapabilitySurfaceDelta(StrictModel):
    delta_schema: Literal[1] = 1
    delta_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    observed_at: datetime
    detected_by: str = Field(min_length=1)
    surface_id: str = Field(min_length=1)
    delta_kind: DeltaKind
    prior_descriptor_ref: str | None = None
    observed_descriptor_ref: str | None = None
    evidence_refs: list[str] = Field(min_length=1)
    authority_ceiling: AuthorityCeiling
    affected_resource_pools: list[str] = Field(default_factory=list)
    privacy_sensitive: bool = False
    public_egress: bool = False
    money_rail: bool = False
    freshness_state: FreshnessState
    required_intake_action: RequiredIntakeAction
    remediation_ref: str | None = None
    summary: str = Field(min_length=1)

    @model_validator(mode="after")
    def _delta_contract_is_actionable(self) -> Self:
        if self.delta_kind is not DeltaKind.NEW_CAPABILITY and self.prior_descriptor_ref is None:
            raise ValueError("non-new deltas require prior_descriptor_ref")
        if (
            self.delta_kind is not DeltaKind.ABSENT_DETERMINATION
            and self.observed_descriptor_ref is None
        ):
            raise ValueError("non-absent deltas require observed_descriptor_ref")
        if self.delta_kind in {
            DeltaKind.NEW_CAPABILITY,
            DeltaKind.DESCRIPTOR_CHANGED,
            DeltaKind.AUTHORITY_CHANGED,
            DeltaKind.RESOURCE_POOL_CHANGED,
            DeltaKind.PUBLIC_EGRESS_CHANGED,
            DeltaKind.MONEY_RAIL_CHANGED,
            DeltaKind.HARNESS_BOUNDARY_CHANGED,
            DeltaKind.ORCHESTRATION_CHILD_CHANGED,
        }:
            if self.required_intake_action not in {
                RequiredIntakeAction.MINT_INTAKE_ITEM,
                RequiredIntakeAction.UPDATE_DESCRIPTOR,
                RequiredIntakeAction.QUARANTINE_SURFACE,
            }:
                raise ValueError("surface deltas require descriptor update or intake action")
            if self.freshness_state is not FreshnessState.DELTA_PENDING:
                raise ValueError("surface deltas must be delta_pending until reconciled")
        if self.delta_kind is DeltaKind.STALE_DETERMINATION:
            if self.required_intake_action is not RequiredIntakeAction.REFRESH_RECEIPT:
                raise ValueError("stale determinations require refresh_receipt")
            if self.freshness_state is not FreshnessState.STALE:
                raise ValueError("stale determinations require stale freshness_state")
        if self.delta_kind is DeltaKind.ABSENT_DETERMINATION:
            if self.required_intake_action not in {
                RequiredIntakeAction.MINT_INTAKE_ITEM,
                RequiredIntakeAction.QUARANTINE_SURFACE,
            }:
                raise ValueError("absent determinations require intake or quarantine")
            if self.freshness_state is not FreshnessState.ABSENT:
                raise ValueError("absent determinations require absent freshness_state")
        if (
            self.required_intake_action is not RequiredIntakeAction.NONE
            and not self.remediation_ref
        ):
            raise ValueError("actionable deltas require remediation_ref")
        return self

    def allows_demand_fulfillment(self) -> bool:
        return (
            self.delta_kind not in {DeltaKind.STALE_DETERMINATION, DeltaKind.ABSENT_DETERMINATION}
            and self.freshness_state is FreshnessState.FRESH
            and self.required_intake_action is RequiredIntakeAction.NONE
        )


class CapabilitySurfaceDeltaFixtureSet(StrictModel):
    schema_version: Literal[1] = 1
    fixture_set_id: str = Field(min_length=1)
    schema_ref: Literal["schemas/capability-surface-delta.schema.json"]
    generated_from: list[str] = Field(min_length=1)
    declared_at: datetime
    descriptors: list[CapabilitySurfaceDescriptor] = Field(min_length=1)
    deltas: list[CapabilitySurfaceDelta] = Field(min_length=1)

    @model_validator(mode="after")
    def _fixtures_cover_required_cases(self) -> Self:
        kinds = {delta.delta_kind for delta in self.deltas}
        required = {
            DeltaKind.NEW_CAPABILITY,
            DeltaKind.STALE_DETERMINATION,
            DeltaKind.AUTHORITY_CHANGED,
        }
        missing = required - kinds
        if missing:
            raise ValueError(
                f"fixture deltas missing required cases: {sorted(m.value for m in missing)}"
            )
        return self


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def parse_duration_spec(spec: str) -> timedelta:
    count_text = spec[:-1]
    unit = spec[-1:]
    if not count_text.isdigit() or count_text.startswith("0") or unit not in {"s", "m", "h", "d"}:
        raise ValueError(f"invalid duration spec {spec!r}; use an integer plus s, m, h, or d")
    count = int(count_text)
    if unit == "s":
        return timedelta(seconds=count)
    if unit == "m":
        return timedelta(minutes=count)
    if unit == "h":
        return timedelta(hours=count)
    return timedelta(days=count)


def stable_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def delta_id_for(
    surface_id: str, delta_kind: DeltaKind, observed_descriptor_ref: str | None
) -> str:
    payload = {
        "surface_id": surface_id,
        "delta_kind": delta_kind.value,
        "observed_descriptor_ref": observed_descriptor_ref,
    }
    return f"capability-surface-delta:{stable_hash(payload)[:16]}"


def slug_token(value: str, *, max_len: int = 72) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (slug[:max_len] or "capability-surface").rstrip("-")


def task_id_for_delta(delta: CapabilitySurfaceDelta) -> str:
    suffix = stable_hash(
        {
            "delta_id": delta.delta_id,
            "surface_id": delta.surface_id,
            "delta_kind": delta.delta_kind.value,
        }
    )[:12]
    return f"cc-task-capability-surface-delta-{slug_token(delta.surface_id, max_len=36)}-{suffix}"


def task_filename_for_delta(delta: CapabilitySurfaceDelta) -> str:
    return f"{task_id_for_delta(delta)}.md"


def _frontmatter_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    return json.dumps(str(value), ensure_ascii=True)


def _frontmatter_lines(fields: dict[str, Any]) -> list[str]:
    lines = ["---"]
    for key, value in fields.items():
        if isinstance(value, (list, tuple)):
            if not value:
                lines.append(f"{key}: []")
            else:
                lines.append(f"{key}:")
                for item in value:
                    lines.append(f"  - {_frontmatter_scalar(item)}")
        else:
            lines.append(f"{key}: {_frontmatter_scalar(value)}")
    lines.append("---")
    return lines


def _delta_priority(delta: CapabilitySurfaceDelta) -> str:
    if delta.public_egress or delta.money_rail or delta.privacy_sensitive:
        return "p0"
    if delta.delta_kind in {DeltaKind.NEW_CAPABILITY, DeltaKind.AUTHORITY_CHANGED}:
        return "p0"
    return "p1"


def _delta_title(delta: CapabilitySurfaceDelta) -> str:
    action = {
        DeltaKind.NEW_CAPABILITY: "Register new capability surface",
        DeltaKind.STALE_DETERMINATION: "Refresh stale capability determination",
        DeltaKind.ABSENT_DETERMINATION: "Quarantine absent capability surface",
        DeltaKind.AUTHORITY_CHANGED: "Reconcile capability authority change",
        DeltaKind.RESOURCE_POOL_CHANGED: "Reconcile capability resource-pool change",
        DeltaKind.PUBLIC_EGRESS_CHANGED: "Reconcile capability public-egress change",
        DeltaKind.MONEY_RAIL_CHANGED: "Reconcile capability money-rail change",
        DeltaKind.HARNESS_BOUNDARY_CHANGED: "Reconcile capability harness-boundary change",
        DeltaKind.ORCHESTRATION_CHILD_CHANGED: "Reconcile capability orchestration-child change",
        DeltaKind.DESCRIPTOR_CHANGED: "Reconcile capability descriptor change",
    }[delta.delta_kind]
    return f"{action}: {delta.surface_id}"


def _delta_mutation_scope(delta: CapabilitySurfaceDelta) -> tuple[str, ...]:
    base = [
        "hapax-council/shared/platform_capability_registry.py",
        "hapax-council/shared/platform_capability_receipts.py",
        "hapax-council/shared/dispatcher_policy.py",
        "hapax-council/shared/capability_surface_delta.py",
        "hapax-council/tests/",
    ]
    if delta.public_egress:
        base.append("hapax-council/shared/publication_bus*")
    if delta.money_rail:
        base.append("hapax-council/shared/*quota*")
    return tuple(base)


def render_capability_surface_delta_task(
    delta: CapabilitySurfaceDelta,
    *,
    generated_at: datetime | None = None,
    parent_request: str = DEFAULT_PARENT_REQUEST,
    parent_spec: str = DEFAULT_PARENT_SPEC,
    authority_case: str = DEFAULT_AUTHORITY_CASE,
    discovery_task: str = DEFAULT_DISCOVERY_TASK,
) -> str:
    generated = ensure_utc(generated_at or datetime.now(UTC))
    generated_s = generated.strftime("%Y-%m-%dT%H:%M:%SZ")
    task_id = task_id_for_delta(delta)
    fields: dict[str, Any] = {
        "type": "cc-task",
        "task_id": task_id,
        "title": _delta_title(delta),
        "status": "offered",
        "assigned_to": "unassigned",
        "blocked_reason": None,
        "priority": _delta_priority(delta),
        "wsjf": 13.0,
        "route_metadata_schema": 1,
        "effort_class": "small",
        "quality_floor": "deterministic_ok",
        "mutation_surface": "source",
        "mutation_scope_refs": _delta_mutation_scope(delta),
        "authority_level": "support_non_authoritative",
        "kind": "implementation",
        "risk_tier": "T1",
        "depends_on": [discovery_task],
        "blocks": [],
        "branch": None,
        "pr": None,
        "created_at": generated_s,
        "claimed_at": None,
        "completed_at": None,
        "parent_request": parent_request,
        "parent_spec": parent_spec,
        "authority_case": authority_case,
        "stage": "S2_INTAKE",
        "implementation_authorized": True,
        "source_mutation_authorized": True,
        "docs_mutation_authorized": True,
        "runtime_mutation_authorized": False,
        "release_authorized": False,
        "public_current": False,
        "provider_spend_authorized": False,
        "no_secret_value_storage": True,
        "capability_surface_delta_id": delta.delta_id,
        "capability_surface_id": delta.surface_id,
        "capability_delta_kind": delta.delta_kind.value,
        "capability_freshness_state": delta.freshness_state.value,
        "required_intake_action": delta.required_intake_action.value,
        "tags": [
            "cc-task",
            "capability-routing",
            "capability-surface-delta",
            delta.delta_kind.value,
            delta.freshness_state.value,
        ],
    }
    evidence_lines = [f"- `{ref}`" for ref in delta.evidence_refs]
    body = [
        f"# {_delta_title(delta)}",
        "",
        "## Delta",
        "",
        f"- Surface: `{delta.surface_id}`",
        f"- Kind: `{delta.delta_kind.value}`",
        f"- Freshness: `{delta.freshness_state.value}`",
        f"- Required action: `{delta.required_intake_action.value}`",
        f"- Remediation ref: `{delta.remediation_ref}`",
        f"- Authority ceiling: `{delta.authority_ceiling.value}`",
        f"- Privacy sensitive: `{delta.privacy_sensitive}`",
        f"- Public egress: `{delta.public_egress}`",
        f"- Money rail: `{delta.money_rail}`",
        "",
        "## Evidence",
        "",
        *evidence_lines,
        "",
        "## Required Handling",
        "",
        "- [ ] Reconcile the capability descriptor or receipt before this surface can satisfy demand.",
        "- [ ] Preserve evidence refs and the deterministic `capability_surface_delta_id`.",
        "- [ ] Update routing/resource-utilization policy if this delta changes demand fulfillment.",
        "- [ ] Add or update tests for the affected capability surface class.",
        "",
        "## Session Log",
        "",
        f"- {generated_s} auto-minted from `capability_surface_delta` by SDLC intake automation.",
    ]
    return "\n".join(_frontmatter_lines(fields) + [""] + body) + "\n"


def write_capability_surface_delta_tasks(
    deltas: list[CapabilitySurfaceDelta],
    *,
    task_root: Path = DEFAULT_CAPABILITY_SURFACE_DELTA_TASK_ROOT,
    generated_at: datetime | None = None,
    apply: bool = True,
) -> dict[str, Any]:
    written: list[str] = []
    skipped_existing: list[str] = []
    would_write: list[str] = []
    errors: list[str] = []
    active_root = task_root / "active"
    for delta in deltas:
        path = active_root / task_filename_for_delta(delta)
        if path.exists():
            skipped_existing.append(str(path))
            continue
        rendered = render_capability_surface_delta_task(delta, generated_at=generated_at)
        if not apply:
            would_write.append(str(path))
            continue
        try:
            active_root.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(rendered, encoding="utf-8")
            tmp.replace(path)
            written.append(str(path))
        except OSError as exc:
            errors.append(f"{path}: {exc}")
    return {
        "ok": not errors,
        "loaded": len(deltas),
        "written": written,
        "would_write": would_write,
        "skipped_existing": skipped_existing,
        "errors": errors,
    }


def _descriptor_change_kind(
    prior: CapabilitySurfaceDescriptor,
    observed: CapabilitySurfaceDescriptor,
) -> DeltaKind:
    if prior.authority_ceiling is not observed.authority_ceiling:
        return DeltaKind.AUTHORITY_CHANGED
    if sorted(prior.resource_pools) != sorted(observed.resource_pools):
        return DeltaKind.RESOURCE_POOL_CHANGED
    if prior.public_egress != observed.public_egress:
        return DeltaKind.PUBLIC_EGRESS_CHANGED
    if prior.money_rail != observed.money_rail:
        return DeltaKind.MONEY_RAIL_CHANGED
    if sorted(prior.harness_refs) != sorted(observed.harness_refs):
        return DeltaKind.HARNESS_BOUNDARY_CHANGED
    if sorted(prior.orchestration_child_refs) != sorted(observed.orchestration_child_refs):
        return DeltaKind.ORCHESTRATION_CHILD_CHANGED
    return DeltaKind.DESCRIPTOR_CHANGED


def build_surface_delta(
    *,
    prior: CapabilitySurfaceDescriptor | None,
    observed: CapabilitySurfaceDescriptor | None,
    source: str,
    detected_by: str,
    now: datetime | None = None,
    remediation_ref: str,
) -> CapabilitySurfaceDelta | None:
    checked_now = ensure_utc(now or datetime.now(UTC))
    if prior is None and observed is None:
        raise ValueError("prior and observed cannot both be None")
    if observed is None:
        assert prior is not None
        return CapabilitySurfaceDelta(
            delta_id=delta_id_for(prior.surface_id, DeltaKind.ABSENT_DETERMINATION, None),
            source=source,
            observed_at=checked_now,
            detected_by=detected_by,
            surface_id=prior.surface_id,
            delta_kind=DeltaKind.ABSENT_DETERMINATION,
            prior_descriptor_ref=prior.descriptor_ref,
            observed_descriptor_ref=None,
            evidence_refs=prior.evidence_refs,
            authority_ceiling=prior.authority_ceiling,
            affected_resource_pools=prior.resource_pools,
            privacy_sensitive=prior.privacy_sensitive,
            public_egress=prior.public_egress,
            money_rail=prior.money_rail,
            freshness_state=FreshnessState.ABSENT,
            required_intake_action=RequiredIntakeAction.QUARANTINE_SURFACE,
            remediation_ref=remediation_ref,
            summary=f"registered surface {prior.surface_id} was not observed",
        )
    freshness = observed.freshness_state(now=checked_now)
    if freshness is FreshnessState.STALE:
        return CapabilitySurfaceDelta(
            delta_id=delta_id_for(
                observed.surface_id, DeltaKind.STALE_DETERMINATION, observed.descriptor_ref
            ),
            source=source,
            observed_at=checked_now,
            detected_by=detected_by,
            surface_id=observed.surface_id,
            delta_kind=DeltaKind.STALE_DETERMINATION,
            prior_descriptor_ref=prior.descriptor_ref if prior else observed.descriptor_ref,
            observed_descriptor_ref=observed.descriptor_ref,
            evidence_refs=observed.evidence_refs,
            authority_ceiling=observed.authority_ceiling,
            affected_resource_pools=observed.resource_pools,
            privacy_sensitive=observed.privacy_sensitive,
            public_egress=observed.public_egress,
            money_rail=observed.money_rail,
            freshness_state=FreshnessState.STALE,
            required_intake_action=RequiredIntakeAction.REFRESH_RECEIPT,
            remediation_ref=remediation_ref,
            summary=f"observed surface {observed.surface_id} is stale",
        )
    if prior is None:
        return CapabilitySurfaceDelta(
            delta_id=delta_id_for(
                observed.surface_id, DeltaKind.NEW_CAPABILITY, observed.descriptor_ref
            ),
            source=source,
            observed_at=checked_now,
            detected_by=detected_by,
            surface_id=observed.surface_id,
            delta_kind=DeltaKind.NEW_CAPABILITY,
            prior_descriptor_ref=None,
            observed_descriptor_ref=observed.descriptor_ref,
            evidence_refs=observed.evidence_refs,
            authority_ceiling=observed.authority_ceiling,
            affected_resource_pools=observed.resource_pools,
            privacy_sensitive=observed.privacy_sensitive,
            public_egress=observed.public_egress,
            money_rail=observed.money_rail,
            freshness_state=FreshnessState.DELTA_PENDING,
            required_intake_action=RequiredIntakeAction.MINT_INTAKE_ITEM,
            remediation_ref=remediation_ref,
            summary=f"new capability surface {observed.surface_id} observed",
        )
    if prior.significant_signature() == observed.significant_signature():
        return None
    delta_kind = _descriptor_change_kind(prior, observed)
    return CapabilitySurfaceDelta(
        delta_id=delta_id_for(observed.surface_id, delta_kind, observed.descriptor_ref),
        source=source,
        observed_at=checked_now,
        detected_by=detected_by,
        surface_id=observed.surface_id,
        delta_kind=delta_kind,
        prior_descriptor_ref=prior.descriptor_ref,
        observed_descriptor_ref=observed.descriptor_ref,
        evidence_refs=observed.evidence_refs,
        authority_ceiling=observed.authority_ceiling,
        affected_resource_pools=observed.resource_pools,
        privacy_sensitive=observed.privacy_sensitive,
        public_egress=observed.public_egress,
        money_rail=observed.money_rail,
        freshness_state=FreshnessState.DELTA_PENDING,
        required_intake_action=RequiredIntakeAction.UPDATE_DESCRIPTOR,
        remediation_ref=remediation_ref,
        summary=f"capability surface {observed.surface_id} descriptor changed",
    )


def detect_surface_deltas(
    *,
    registered: list[CapabilitySurfaceDescriptor],
    observed: list[CapabilitySurfaceDescriptor],
    source: str,
    detected_by: str,
    remediation_ref: str,
    now: datetime | None = None,
) -> list[CapabilitySurfaceDelta]:
    registered_by_id = {descriptor.surface_id: descriptor for descriptor in registered}
    observed_by_id = {descriptor.surface_id: descriptor for descriptor in observed}
    deltas: list[CapabilitySurfaceDelta] = []
    for surface_id in sorted(set(registered_by_id) | set(observed_by_id)):
        delta = build_surface_delta(
            prior=registered_by_id.get(surface_id),
            observed=observed_by_id.get(surface_id),
            source=source,
            detected_by=detected_by,
            remediation_ref=remediation_ref,
            now=now,
        )
        if delta is not None:
            deltas.append(delta)
    return deltas


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CapabilitySurfaceDeltaError(f"{path} did not contain a JSON object")
    return payload


def load_capability_surface_delta_fixtures(
    path: Path = CAPABILITY_SURFACE_DELTA_FIXTURES,
) -> CapabilitySurfaceDeltaFixtureSet:
    try:
        return CapabilitySurfaceDeltaFixtureSet.model_validate(_load_json(path))
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise CapabilitySurfaceDeltaError(
            f"invalid capability-surface delta fixtures: {exc}"
        ) from exc


_PYDANTIC_DYNAMIC_ENTRYPOINTS = (
    CapabilitySurfaceDescriptor._duration_is_valid,
    CapabilitySurfaceDelta._delta_contract_is_actionable,
    CapabilitySurfaceDeltaFixtureSet._fixtures_cover_required_cases,
)
